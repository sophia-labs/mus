//! NumPy-compatible random generation, bit-faithful to
//! `np.random.default_rng(seed)`.
//!
//! Three layers, each verified against golden vectors dumped from NumPy
//! (`mus-rs/fixtures/dsp/{seedseq_7_state,pcg64_7_raw}.json` and the
//! `standard_normal_*` cases in `manifest.json`):
//!
//! 1. **SeedSequence** — NumPy's entropy-mixing pool (128-bit pool,
//!    murmur-style hashing) that turns an integer seed into PCG64 state
//!    words. `SeedSequence(7).generate_state(8, uint64)` is the oracle.
//! 2. **PCG64** — the XSL-RR 128/64 generator NumPy uses as its default
//!    BitGenerator. `np.random.PCG64(7).random_raw(64)` is the oracle.
//! 3. **standard_normal** — NumPy's 256-region ziggurat for f64 gaussians
//!    (ported from numpy's `random/src/distributions/distributions.c`,
//!    including its exact constant tables and its uint64→(index, sign,
//!    mantissa) bit slicing). `default_rng(7).standard_normal(64)` must
//!    match to the last bit; the parity target in the manifest is
//!    `max_abs 1e-12`, i.e. bit-faithful in practice.
//!
//! Row-major fill order for shaped output is part of the contract
//! (`standard_normal_2x32`): NumPy fills `(2, n)` row by row, and
//! `mus_audio.make_ir` depends on that ordering for its stereo IR. This
//! crate has no notion of shape at all — [`Pcg64::standard_normal_vec`]
//! just returns draws in stream order, which *is* row-major once the
//! caller reshapes it (see the `standard_normal_2x32_matches_2x32_shape`
//! test).
//!
//! This crate exists because the mus render face reproduces
//! `mus_audio.make_ir` — a reverb impulse built from
//! `default_rng(7).standard_normal((2, n))` — sample-for-sample. It is
//! deliberately dependency-free and usable standalone: NumPy-stream
//! compatibility is a recurring need when porting scientific Python to
//! Rust, and nothing maintained on crates.io provides it.

mod ziggurat_tables;

use ziggurat_tables::{FI_DOUBLE, KI_DOUBLE, WI_DOUBLE};

// ---------------------------------------------------------------------
// SeedSequence — numpy's entropy-mixing pool
// (`numpy/random/bit_generator.pyx`: `SeedSequence.mix_entropy` /
// `generate_state`, the "hashmix" / "mix" murmur-style constants).
// ---------------------------------------------------------------------

const DEFAULT_POOL_SIZE: usize = 4;
const XSHIFT: u32 = 16;
const INIT_A: u32 = 0x43b0_d7e5;
const MULT_A: u32 = 0x931e_8875;
const INIT_B: u32 = 0x8b51_f9dd;
const MULT_B: u32 = 0x58f3_8ded;
const MIX_MULT_L: u32 = 0xca01_f9dd;
const MIX_MULT_R: u32 = 0x4973_f715;

/// `hashmix(value, hash_const)`: folds `value` into a running hash
/// constant that itself evolves (multiplied by `MULT_A`) on every call —
/// the same `(value, hash_const)` pair called twice in a row yields two
/// *different* results, which is load-bearing in [`mix_entropy`] below.
fn hashmix(value: u32, hash_const: &mut u32) -> u32 {
    let mut value = value ^ *hash_const;
    *hash_const = hash_const.wrapping_mul(MULT_A);
    value = value.wrapping_mul(*hash_const);
    value ^= value >> XSHIFT;
    value
}

/// `mix(x, y)`: numpy's pairwise pool-mixing step.
fn mix(x: u32, y: u32) -> u32 {
    let mut result = MIX_MULT_L
        .wrapping_mul(x)
        .wrapping_sub(MIX_MULT_R.wrapping_mul(y));
    result ^= result >> XSHIFT;
    result
}

/// A `u64` seed as numpy's `_int_to_uint32_array`: little words first,
/// `[0]` for a zero seed. (Our public API only takes `u64` seeds, so this
/// never emits more than two words — but the algorithm below still walks
/// a general `&[u32]` entropy slice, matching numpy's seeding path for
/// arbitrary-width entropy exactly rather than only the two-word case we
/// happen to need.)
fn seed_to_words(seed: u64) -> Vec<u32> {
    if seed == 0 {
        return vec![0];
    }
    let mut n = seed;
    let mut words = Vec::with_capacity(2);
    while n > 0 {
        words.push((n & 0xffff_ffff) as u32);
        n >>= 32;
    }
    words
}

/// Mixes `entropy` into `mixer` in place: numpy's `SeedSequence.mix_entropy`.
/// First pass seeds each pool word from `entropy` (or zero, once entropy
/// runs out); second pass mixes every pool word into every *other* pool
/// word so a late entropy word can still affect an early pool word; third
/// pass (unreachable for our `u64`-only seeds, since entropy never
/// exceeds `DEFAULT_POOL_SIZE` words, but kept for fidelity to numpy's
/// general algorithm) folds in any entropy beyond the pool size.
fn mix_entropy(mixer: &mut [u32; DEFAULT_POOL_SIZE], entropy: &[u32]) {
    let mut hash_const = INIT_A;
    for (i, slot) in mixer.iter_mut().enumerate() {
        *slot = hashmix(entropy.get(i).copied().unwrap_or(0), &mut hash_const);
    }
    for i_src in 0..mixer.len() {
        for i_dst in 0..mixer.len() {
            if i_src != i_dst {
                let hashed_src = hashmix(mixer[i_src], &mut hash_const);
                mixer[i_dst] = mix(mixer[i_dst], hashed_src);
            }
        }
    }
    // Index loop kept: mirrors numpy's C mixing loop structure exactly.
    #[allow(clippy::needless_range_loop)]
    for i_src in mixer.len()..entropy.len() {
        for slot in mixer.iter_mut() {
            let hashed_src = hashmix(entropy[i_src], &mut hash_const);
            *slot = mix(*slot, hashed_src);
        }
    }
}

/// NumPy's `SeedSequence`: turns an integer seed into an entropy-mixed
/// 4-word `u32` pool, from which [`SeedSequence::generate_state`] draws
/// the `u64` seed words a `BitGenerator` is constructed from.
pub struct SeedSequence {
    pool: [u32; DEFAULT_POOL_SIZE],
}

impl SeedSequence {
    /// `numpy.random.SeedSequence(seed)`.
    pub fn new(seed: u64) -> Self {
        let entropy = seed_to_words(seed);
        let mut pool = [0u32; DEFAULT_POOL_SIZE];
        mix_entropy(&mut pool, &entropy);
        SeedSequence { pool }
    }

    /// `SeedSequence.generate_state(n_words, dtype=np.uint64)`: cycles
    /// through the pool, running each draw through a second hashmix pass
    /// (with its own evolving `INIT_B`/`MULT_B` hash constant) to produce
    /// `2 * n_words` fresh `u32`s, then pairs them little-endian into
    /// `n_words` `u64`s.
    pub fn generate_state(&self, n_words: usize) -> Vec<u64> {
        let n32 = n_words * 2;
        let mut hash_const = INIT_B;
        let mut state32 = vec![0u32; n32];
        for (i, slot) in state32.iter_mut().enumerate() {
            let mut data_val = self.pool[i % self.pool.len()];
            data_val ^= hash_const;
            hash_const = hash_const.wrapping_mul(MULT_B);
            data_val = data_val.wrapping_mul(hash_const);
            data_val ^= data_val >> XSHIFT;
            *slot = data_val;
        }
        (0..n_words)
            .map(|i| (state32[2 * i] as u64) | ((state32[2 * i + 1] as u64) << 32))
            .collect()
    }
}

// ---------------------------------------------------------------------
// PCG64 — numpy's default BitGenerator: PCG XSL-RR 128/64.
// ---------------------------------------------------------------------

/// The PCG family's default 128-bit LCG multiplier.
const PCG_MULT_128: u128 = 0x2360_ed05_1fc6_5da4_4385_df64_9fcc_f645;

/// `2^-53`, numpy's `random_double` scale: `(next_uint64() >> 11) * 2^-53`.
const TWO_POW_NEG_53: f64 = 1.0 / 9_007_199_254_740_992.0;

/// The tail-start boundary of the standard-normal ziggurat (numpy's
/// `ziggurat_nor_r`) and its reciprocal (`ziggurat_nor_inv_r`). Both
/// transcribed verbatim from the same `ziggurat_constants.h` source as
/// `ziggurat_tables`'s KI/WI/FI arrays — numpy ships `ziggurat_nor_inv_r`
/// as its own literal (a comment there notes it *is* `1.0 /
/// ziggurat_nor_r`, computed once at table-generation time, not at
/// runtime), so it is transcribed as its own literal here too rather than
/// computed by a runtime division whose rounding would need separate
/// verification. (Checked: `1.0 / ZIGGURAT_R` does land on this exact bit
/// pattern too, but matching the source directly needs no such check.)
#[allow(clippy::excessive_precision)] // full source precision, see above
const ZIGGURAT_R: f64 = 3.6541528853610087963519472518;
#[allow(clippy::excessive_precision)]
const ZIGGURAT_INV_R: f64 = 0.27366123732975827203338247596;

/// NumPy's default `BitGenerator`: a 128-bit LCG output through the
/// XSL-RR (xor-shift-low, random-rotate) permutation, seeded from a
/// [`SeedSequence`]. Also carries the ziggurat-based
/// [`Pcg64::standard_normal`] sampler, since that's the one distribution
/// the mus render face needs (`make_ir`'s `standard_normal((2, n))`).
pub struct Pcg64 {
    state: u128,
    inc: u128,
}

/// Which acceptance path a [`Pcg64::standard_normal`] draw took.
/// Crate-private — this exists purely so tests can *prove* the ziggurat's
/// slow paths (the ~1% of draws that fail the fast accept-reject test) are
/// actually exercised by the streams checked against the oracle, rather
/// than silently assuming it. The tables that shipped in the first review
/// round were wrong (see `ziggurat_tables`'s module doc), yet a 64-draw
/// `max_abs 1e-12` stream comparison against those wrong tables still
/// passed — the wrongness happened to live in table entries that specific
/// stream's fast-path draws never compared against. A test that cannot
/// show it exercised [`ZigguratBranch::Wedge`] or [`ZigguratBranch::Tail`]
/// cannot tell a correct table from a subtly wrong one.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ZigguratBranch {
    /// `rabs < KI_DOUBLE[idx]`: the common case, no further test needed.
    Fast,
    /// `idx != 0`, the fast test failed, but the wedge accept/reject test
    /// against `FI_DOUBLE` passed on this attempt.
    Wedge,
    /// `idx == 0`: the tail-adjacent layer, resolved by the dedicated
    /// exponential-tail sampler rather than a wedge test.
    Tail,
}

impl Pcg64 {
    /// `PCG64(seed_sequence)`: numpy's `pcg64_set_seed` composed with
    /// `pcg64_srandom_r` — draw 4 `u64` seed words (2 for state, 2 for
    /// increment), assemble the increment as `(inc_seed << 1) | 1`
    /// (PCG64 requires an odd increment), then run the LCG step twice:
    /// once to fold in the increment alone, once more after adding the
    /// state seed.
    pub fn from_seed_sequence(seq: &mut SeedSequence) -> Self {
        let words = seq.generate_state(4);
        let state_seed = ((words[0] as u128) << 64) | (words[1] as u128);
        let inc_seed = ((words[2] as u128) << 64) | (words[3] as u128);
        let mut pcg = Pcg64 {
            state: 0,
            inc: (inc_seed << 1) | 1,
        };
        pcg.step();
        pcg.state = pcg.state.wrapping_add(state_seed);
        pcg.step();
        pcg
    }

    /// `np.random.default_rng(seed)`'s bit-generator: `PCG64(SeedSequence(seed))`.
    pub fn seeded(seed: u64) -> Self {
        let mut seq = SeedSequence::new(seed);
        Self::from_seed_sequence(&mut seq)
    }

    fn step(&mut self) {
        self.state = self.state.wrapping_mul(PCG_MULT_128).wrapping_add(self.inc);
    }

    /// `PCG64.random_raw()` / `BitGenerator.next_uint64`: step the LCG,
    /// then output via XSL-RR — xor the high and low 64 bits of the new
    /// 128-bit state together, and rotate right by the state's top 6 bits.
    pub fn next_u64(&mut self) -> u64 {
        self.step();
        let hi = (self.state >> 64) as u64;
        let lo = self.state as u64;
        let rot = ((self.state >> 122) as u32) & 63;
        (hi ^ lo).rotate_right(rot)
    }

    /// `next_double`: a uniform `f64` in `[0, 1)` from the top 53 bits of
    /// a raw draw.
    fn next_f64(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 * TWO_POW_NEG_53
    }

    /// `Generator.standard_normal()`: numpy's ziggurat for `f64` gaussians
    /// (`random_standard_normal` in numpy's `distributions.c`).
    ///
    /// Draw a raw `u64` `r` and slice it into a 256-way layer index
    /// (`idx`, low byte), a sign bit, and a 52-bit mantissa (`rabs`).
    /// `x = rabs * WI_DOUBLE[idx]` is provisionally the sample; if `rabs`
    /// falls under `KI_DOUBLE[idx]` that provisional `x` is immediately
    /// correct (true on ~99% of draws — every layer's inner rectangle is
    /// entirely under the curve, no further test needed). Otherwise:
    /// `idx == 0` is the tail-adjacent layer and falls back to a
    /// dedicated exponential-tail sampler (loops until accepted, drawing
    /// two fresh uniforms per attempt); any other `idx` runs one
    /// accept/reject "wedge" test against the true density, using a
    /// fresh uniform, and loops back to a brand new `r`/`idx` draw on
    /// rejection.
    ///
    /// See `ziggurat_tables` for why the `idx` numbering runs the
    /// opposite direction from the construction that built the tables,
    /// and why `FI_DOUBLE[0]` is `1.0` rather than the tail layer's own
    /// density — both are load-bearing, oracle-diagnosed corrections,
    /// not stylistic choices.
    pub fn standard_normal(&mut self) -> f64 {
        self.standard_normal_traced().0
    }

    /// Shared implementation behind [`Pcg64::standard_normal`]: identical
    /// computation, but also reports which [`ZigguratBranch`] produced the
    /// result, so whitebox tests can assert slow-path coverage rather than
    /// assume it. See that type's doc for why this matters.
    pub(crate) fn standard_normal_traced(&mut self) -> (f64, ZigguratBranch) {
        loop {
            let r = self.next_u64();
            let idx = (r & 0xff) as usize;
            let sign = (r >> 8) & 1;
            let rabs = (r >> 9) & 0x000f_ffff_ffff_ffff;

            let mut x = rabs as f64 * WI_DOUBLE[idx];
            if sign != 0 {
                x = -x;
            }
            if rabs < KI_DOUBLE[idx] {
                return (x, ZigguratBranch::Fast);
            }

            if idx == 0 {
                // Tail: propose `xx` from a shifted/scaled exponential,
                // accept with probability `exp(-xx^2 / 2)` via a second
                // exponential `yy` (`log1p(-next_f64())`, not
                // `log(next_f64())`, matching numpy's `npy_log1p` use —
                // `next_f64()` can return exactly `0.0`, which `log`
                // cannot take). The sign here is drawn from a *different*
                // bit than the one used above (`rabs`'s own bit 8, not
                // the `sign` bit that gated the fast path) — numpy
                // reuses `rabs`'s entropy rather than the original sign,
                // confirmed by bisecting an oracle mismatch down to this
                // exact draw.
                loop {
                    let xx = -ZIGGURAT_INV_R * (-self.next_f64()).ln_1p();
                    let yy = -(-self.next_f64()).ln_1p();
                    if yy + yy > xx * xx {
                        let tail_sign = (rabs >> 8) & 1;
                        let x = if tail_sign != 0 {
                            -(ZIGGURAT_R + xx)
                        } else {
                            ZIGGURAT_R + xx
                        };
                        return (x, ZigguratBranch::Tail);
                    }
                }
            } else {
                let u = self.next_f64();
                let lhs = (FI_DOUBLE[idx - 1] - FI_DOUBLE[idx]) * u + FI_DOUBLE[idx];
                let rhs = (-0.5 * x * x).exp();
                if lhs < rhs {
                    return (x, ZigguratBranch::Wedge);
                }
                // Rejected: fall through to the outer loop and draw a
                // brand new `r` (not a retry of this `idx`).
            }
        }
    }

    /// `n` draws from [`Pcg64::standard_normal`], in stream order. Stream
    /// order *is* numpy's row-major fill order for any `(rows, cols)`
    /// reshape the caller wants — this crate has no shape of its own.
    pub fn standard_normal_vec(&mut self, n: usize) -> Vec<f64> {
        (0..n).map(|_| self.standard_normal()).collect()
    }
}

// ---------------------------------------------------------------------
// Whitebox coverage tests. `tests/golden.rs` is the blackbox oracle
// check (public API only, no visibility into which ziggurat branch a
// draw took); it cannot itself prove the stream it checks exercises the
// slow paths rather than 64 lucky fast-accepts. This module can, because
// unit tests compiled into the crate see `pub(crate)` items
// (`standard_normal_traced`, `ZigguratBranch`, the tables themselves).
// ---------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::path::PathBuf;

    fn fixtures_dir() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/dsp")
    }

    fn read_f64_bin(name: &str) -> Vec<f64> {
        let path = fixtures_dir().join(name);
        let bytes = fs::read(&path)
            .unwrap_or_else(|e| panic!("read {}: {e} — run gen_dsp_fixtures.py", path.display()));
        bytes
            .chunks_exact(8)
            .map(|c| f64::from_le_bytes(c.try_into().unwrap()))
            .collect()
    }

    /// Whitebox companion to `tests/golden.rs`'s `standard_normal_64` /
    /// `standard_normal_2x32` checks: those prove the *values* match the
    /// oracle via the public API alone. This proves — via direct access to
    /// [`ZigguratBranch`] — that the same `default_rng(7).standard_normal(64)`
    /// stream those tests check is not a 64-for-64 fast-accept run, so a
    /// wrong `KI_DOUBLE`/`WI_DOUBLE`/`FI_DOUBLE` entry reachable only from
    /// the slow paths cannot hide behind an all-fast-path stream the way
    /// the first review round's wrong tables did.
    ///
    /// Every draw is also checked bit-for-bit (`to_bits`, not a tolerance)
    /// against the oracle, branch-by-branch — so this doesn't just prove
    /// *a* slow path ran, it proves the slow path that ran produced the
    /// oracle-exact value.
    ///
    /// Coverage measured on this stream, seed 7: draw index 31 takes
    /// [`ZigguratBranch::Wedge`]; every other draw is
    /// [`ZigguratBranch::Fast`]. **No draw in this 64-draw stream reaches
    /// `idx == 0`**, so [`ZigguratBranch::Tail`] has no oracle-verified
    /// coverage in this crate's test suite — reported here rather than
    /// left implicit, per the stage's tolerance-honesty rule applied to
    /// coverage: don't claim what wasn't measured.
    #[test]
    fn standard_normal_64_stream_exact_bits_with_wedge_coverage() {
        let expected = read_f64_bin("standard_normal_64.out.bin");
        assert_eq!(expected.len(), 64, "fixture shape sanity");

        let mut pcg = Pcg64::seeded(7);
        let mut wedge_at: Option<usize> = None;
        let mut tail_at: Option<usize> = None;
        for (i, e) in expected.iter().enumerate() {
            let (x, branch) = pcg.standard_normal_traced();
            assert_eq!(
                x.to_bits(),
                e.to_bits(),
                "standard_normal_64[{i}]: bit-exact oracle match required \
                 (branch {branch:?}), got {x:.17e} expected {e:.17e}"
            );
            match branch {
                ZigguratBranch::Wedge => wedge_at.get_or_insert(i),
                ZigguratBranch::Tail => tail_at.get_or_insert(i),
                ZigguratBranch::Fast => continue,
            };
        }

        assert_eq!(
            wedge_at,
            Some(31),
            "expected exactly one measured wedge-path draw, at index 31 — \
             a different index (or none) means the branch decisions in \
             this stream shifted, which is itself worth investigating even \
             though the bit-exact checks above already passed per-draw"
        );
        assert_eq!(
            tail_at, None,
            "this stream was measured to never reach idx == 0; if it now \
             does, the comment above is stale — update it rather than the \
             assertion, since the tail branch newly getting real oracle \
             coverage here would be a welcome change"
        );
    }
}
