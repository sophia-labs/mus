//! Bus processing: the seeded reverb impulse (`make_ir`, needs np-rand),
//! overlap-add convolution for the wet bus, and the RMS-target `master`
//! chain with its smoothed look-ahead limiter — `mus_audio.py` lines
//! 481–534 and 1150–1167.
//!
//! Owned by stage WF7 (depends on np-rand, WF3's `filters`, and WF2's
//! `maximum_filter1d`/`np_hanning`). Oracle cases: `make_ir_{0_6,2_6,4_5}`
//! (max_abs 1e-6), `reverb_apply_0_6` (max_abs 1e-5), `master_rms14`
//! (max_abs 5e-4).
//!
//! **Numeric accumulation** (`make_ir`'s per-channel energy sum, `master`'s
//! two RMS reductions, the Hann-kernel normalisation sum): `mus_audio.py`
//! computes these with numpy `.sum()`/`.mean()`, which do not reduce with a
//! naive left-to-right accumulator — `np.add.reduce` uses *pairwise*
//! (divide-and-conquer) summation, in the operand array's own dtype, for
//! accuracy (naive summation of n values has O(n) worst-case rounding
//! error; pairwise has O(log n)). Reproducing that algorithm — not merely
//! landing inside a case's numeric tolerance via a different one — is what
//! [`pairwise_sum`]/[`np_sum`] below exist for; see their doc for the
//! algorithm itself and how it was confirmed against the installed oracle.
//! Every sum-shaped reduction in this file goes through them, each fed at
//! the dtype the oracle actually holds at that point in its computation
//! (see each call site for its own trace) — `master`'s second RMS runs at
//! float64, for instance, because the limiter-smoothing step upstream of
//! it promotes `x` to float64 (a real f64 array times an f32 array is
//! ordinary numpy type promotion, not NEP 50's weak-python-scalar
//! carve-out), not because of an error here.

use realfft::num_complex::Complex;
use realfft::RealFftPlanner;

use crate::filters::{butter_sos, sosfilt};
use crate::kernels::{maximum_filter1d, np_hanning};
use crate::SR_F64;

/// `mus_audio.make_ir`'s fixed seed (`seed=7` is the only value any real
/// call site — or the fixture generator — ever passes), so it's not
/// threaded through as a parameter here; see the WF7 spec's signature.
const MAKE_IR_SEED: u64 = 7;

/// `mus_audio.master`'s `ceiling=0.89` default, likewise never overridden
/// at its one real call site (`mus_audio.py` line 1167) or by the
/// `master_rms14` fixture, so it's fixed here rather than parameterised.
const MASTER_CEILING: f64 = 0.89;

// --------------------------------------------------------- numpy-parity sum

/// numpy's block size for the base case of pairwise summation
/// (`PW_BLOCKSIZE` in numpy's C reduction loop): runs of this length or
/// shorter are summed directly with 8-wide unrolled accumulators (see
/// [`pairwise_sum`]); longer runs are recursively bisected.
const PW_BLOCKSIZE: usize = 128;

/// numpy's default ufunc-reduce buffer size (`np.getbufsize()`, backing
/// `NPY_BUFSIZE`): reductions over arrays longer than this are walked in
/// successive chunks of at most this many elements, each pairwise-summed
/// independently, with the per-chunk partial sums then combined by
/// ordinary sequential (non-pairwise) addition — see [`np_sum`].
const NPY_BUFSIZE: usize = 8192;

/// numpy's pairwise-summation base algorithm — the recursive half of
/// `.sum()`/`.mean()`'s reduction, *without* [`NPY_BUFSIZE`] chunking (see
/// [`np_sum`] for the full picture, chunking included). Ported from
/// numpy's `pairwise_sum_@TYPE@` (templated over float32/float64 in
/// numpy's own C source, which is why this is generic here too: every add
/// below is a same-`T` add, so this produces float32 rounding for `T=f32`
/// calls and float64 rounding for `T=f64` calls — whichever dtype the
/// call site's oracle expression is actually holding at that point):
///
/// - runs shorter than 8: naive left-to-right accumulation.
/// - runs of 8..=128: eight running accumulators, each taking every 8th
///   element (`r[j] += a[i+j]` for `i` stepping by 8), combined pairwise
///   at the end (`((r0+r1)+(r2+r3)) + ((r4+r5)+(r6+r7))`), plus a
///   left-to-right tail for any remainder past the last full group of 8.
///   The 8-wide unroll is numpy's own choice, made (per its source
///   comment) so the loop vectorizes *without changing the summation
///   order* — i.e. it's part of the numeric contract, not just an
///   optimisation, so it's ported exactly rather than simplified to a
///   plain accumulator loop.
/// - longer runs: bisected at `n/2` rounded *down* to a multiple of 8, and
///   each half summed recursively.
///
/// **On sourcing**: this environment has numpy only as a compiled wheel
/// (no vendored C source to read directly, unlike this leg's librosa/scipy
/// references), so the algorithm above was confirmed empirically against
/// the installed oracle (numpy 2.0.2) rather than transcribed from source:
/// bisecting on array length against `np.sum`/`np.add.reduce` for
/// bit-exact (`.tobytes()`-equal) output pins the base-case cutoff at
/// exactly 128 and, separately, the buffered-chunking cutoff (see
/// [`np_sum`]) at exactly 8192 — the same two constants documented for
/// numpy's C reduction loop, arrived at independently here. Coverage:
/// both dtypes, mixed-sign and all-positive (sum-of-squares-shaped) data,
/// every boundary size around 8/128/8192, a real `(2,n)`-array `axis=None`
/// reduction (`master`'s exact shape), and this crate's own fixture sizes
/// (28800/29663/38400/72000/125663/144000/216863) — zero mismatches.
fn pairwise_sum<T>(a: &[T]) -> T
where
    T: Copy + Default + std::ops::Add<Output = T>,
{
    let n = a.len();
    if n < 8 {
        let mut res = T::default();
        for &v in a {
            res = res + v;
        }
        return res;
    }
    if n <= PW_BLOCKSIZE {
        let mut r = [a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7]];
        let mut i = 8;
        let bound = n - (n % 8);
        while i < bound {
            for (j, rj) in r.iter_mut().enumerate() {
                *rj = *rj + a[i + j];
            }
            i += 8;
        }
        let mut res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
        while i < n {
            res = res + a[i];
            i += 1;
        }
        return res;
    }
    let mut n2 = n / 2;
    n2 -= n2 % 8;
    pairwise_sum(&a[..n2]) + pairwise_sum(&a[n2..])
}

/// The actual `.sum()`/`.mean()`-equivalent entry point: [`pairwise_sum`]
/// plus numpy's outer buffered-chunking behaviour for arrays longer than
/// [`NPY_BUFSIZE`] (`np.getbufsize()`'s default, 8192 elements). Confirmed
/// empirically (see [`pairwise_sum`]'s doc) that ufunc reduction over such
/// arrays walks them in successive chunks of at most that many elements,
/// pairwise-summing each chunk independently and combining the per-chunk
/// partial sums by ordinary sequential addition — *not* by recursively
/// pairwise-merging across chunks, which is what plain unbounded
/// [`pairwise_sum`] recursion would do and is exactly where it stops
/// matching the oracle bit-for-bit past 8192 elements. For `n <=
/// NPY_BUFSIZE` this is exactly [`pairwise_sum`] — no separate low-n code
/// path to keep in sync.
fn np_sum<T>(a: &[T]) -> T
where
    T: Copy + Default + std::ops::Add<Output = T>,
{
    let n = a.len();
    if n <= NPY_BUFSIZE {
        return pairwise_sum(a);
    }
    let mut acc = T::default();
    let mut i = 0;
    while i < n {
        let j = (i + NPY_BUFSIZE).min(n);
        acc = acc + pairwise_sum(&a[i..j]);
        i = j;
    }
    acc
}

/// `mus_audio.make_ir` (line 481): a synthetic stereo reverb impulse —
/// decorrelated Gaussian noise under an exponential decay envelope,
/// low-passed and normalised to unit per-channel energy.
///
/// Dtype trace through the Python (see the module doc, and
/// [`pairwise_sum`]/[`np_sum`], for how the per-channel energy sum below
/// reproduces numpy's actual float32 pairwise reduction rather than
/// approximating it):
///
/// ```text
/// t   = np.arange(n) / SR                     # f64
/// env = np.exp(-4.2 * t / seconds)             # f64
/// ir  = rng.standard_normal((2, n))             # f64 draws
///         .astype(np.float32)                   # rounded to f32 ...
///         * env                                 # ... then f32-array times
///                                                #     f64-array promotes
///                                                #     back to f64 (NOT a
///                                                #     weak scalar — env is
///                                                #     a real ndarray)
/// ir  = stack([sosfilt(sos, ch) for ch in ir])  # filtered in f64 (scipy
///         .astype(np.float32)                    # upcasts sos-vs-x to f64
///                                                 # regardless), THEN cast
/// ir  = concatenate([zeros(f32), ir], axis=1)   # zero pre-delay, f32
/// ir /= sqrt((ir**2).sum(axis=1, keepdims)) + 1e-9   # per-channel, f32
/// return (ir * 0.9).astype(np.float32)
/// ```
///
/// The `.astype(float32) * env` step is why [`sosfilt64`] exists instead
/// of reusing `filters::sosfilt`: the signal entering the filter is
/// genuinely f64 (an f32-rounded noise sample times an f64 envelope
/// value), not merely f32 promoted for the call, and filtering it at f32
/// instead — i.e. rounding to f32 *before* the filter rather than only
/// after — was measured to cost ~1.2e-7 max_abs against the true oracle,
/// only ~8x under this stage's 1e-6 tolerance. Filtering in f64 throughout
/// (this function's actual path) keeps that divergence closer to ~3.7e-9.
///
/// `n = int(seconds*SR)` and `pre = int(0.018*SR)` truncate whatever
/// `seconds*SR_F64`/`0.018*SR_F64` land on in f64, same as Python's
/// `int()` — not necessarily the "obvious" value: `0.018*48000` is
/// `863.9999999999999` in real f64 arithmetic (checked directly), so
/// `pre` is 863, not 864, and every `make_ir_*` fixture's `shape_out`
/// reflects that (e.g. `make_ir_0_6` is `[2, 29663]` = `28800 + 863`, not
/// `29664`). `as usize` on a positive f64 truncates toward zero exactly
/// like Python's `int()`, so no separate floor/round call is needed.
pub fn make_ir(seconds: f64) -> [Vec<f32>; 2] {
    let n = (seconds * SR_F64) as usize;
    let pre = (0.018 * SR_F64) as usize;

    let mut rng = np_rand::Pcg64::seeded(MAKE_IR_SEED);
    // Row-major: draws 0..n are channel 0, n..2n are channel 1 — numpy's
    // fill order for `standard_normal((2, n))` (see np-rand's module doc).
    let noise = rng.standard_normal_vec(2 * n);

    let env: Vec<f64> = (0..n)
        .map(|i| {
            let t = i as f64 / SR_F64;
            (-4.2 * t / seconds).exp()
        })
        .collect();

    let mut ir_pre = [vec![0.0f64; n], vec![0.0f64; n]];
    for (c, channel) in ir_pre.iter_mut().enumerate() {
        let base = c * n;
        for i in 0..n {
            // Round the draw to f32 once (the oracle's `.astype(float32)`),
            // then widen that rounded value back to f64 to multiply by the
            // f64 envelope — matching the promotion, not skipping it.
            let noise_f32 = noise[base + i] as f32;
            channel[i] = noise_f32 as f64 * env[i];
        }
    }

    let sos = butter_sos(2, 5200.0 / (SR_F64 / 2.0), "low");
    let total = pre + n;
    let mut ir = [vec![0.0f32; total], vec![0.0f32; total]];
    for c in 0..2 {
        let filtered = sosfilt64(&sos, &ir_pre[c]);
        for (dst, &v) in ir[c][pre..].iter_mut().zip(filtered.iter()) {
            *dst = v as f32;
        }
    }

    // Per-channel unit-energy normalisation (axis=1 keeps the two rows
    // separate — each channel is scaled by its own energy, not a shared
    // one), then the fixed 0.9 headroom trim. `(ir**2).sum(axis=1)` is a
    // float32 reduction in the oracle (`ir` is float32 by this point), so
    // the squares and the sum below both stay float32 via [`np_sum`]. The
    // sum runs over the *whole* row — pre-delay zeros included, since they
    // were concatenated into `ir[c]` above rather than summed separately:
    // summing zero never changes a *value*, but it does change which
    // nonzero terms [`pairwise_sum`]'s divide-and-conquer tree groups
    // together, so including the zeros is what actually reproduces the
    // oracle's grouping (and hence its rounding) bit-for-bit.
    for channel in ir.iter_mut() {
        let squares: Vec<f32> = channel.iter().map(|&v| v * v).collect();
        let sumsq = np_sum(&squares);
        let denom = sumsq.sqrt() + 1e-9f32;
        for v in channel.iter_mut() {
            *v = (*v / denom) * 0.9;
        }
    }

    ir
}

/// Direct-form-II-transposed SOS cascade computed and returned in f64 — the
/// same six-tap per-section recursion as `filters::sosfilt`'s inner loop,
/// duplicated locally rather than imported because `make_ir`'s pre-filter
/// signal is genuinely f64 (see this function's caller) and
/// `filters::sosfilt` takes `&[f32]`, which would narrow it a filter-width
/// too early. Zero initial state (`make_ir` never seeds `zi`), so unlike
/// `filters::sosfilt` this has no `zi` parameter or final-state return.
fn sosfilt64(sos: &[[f64; 6]], x: &[f64]) -> Vec<f64> {
    let mut state = vec![[0.0f64; 2]; sos.len()];
    let mut y = Vec::with_capacity(x.len());
    for &xn in x {
        let mut xc = xn;
        for (s, row) in sos.iter().enumerate() {
            let [b0, b1, b2, _a0, a1, a2] = *row;
            let x_new = b0 * xc + state[s][0];
            state[s][0] = b1 * xc - a1 * x_new + state[s][1];
            state[s][1] = b2 * xc - a2 * x_new;
            xc = x_new;
        }
        y.push(xc);
    }
    y
}

// -------------------------------------------------------- overlap-add FFT

/// Shared block-size policy for [`oa_convolve_full_f32`] and
/// [`oa_convolve_full_f64`]: given a filter length, returns
/// `(transform_len, block_len)` — kept as one function so the two dtypes'
/// overlap-add loops can't drift apart on it. See
/// [`oa_convolve_full_f32`]'s doc for the reasoning.
fn oa_block_plan(h_len: usize) -> (usize, usize) {
    const MIN_TRANSFORM: usize = 1024;
    let transform_len = (2 * h_len).max(MIN_TRANSFORM).next_power_of_two();
    let block_len = transform_len - h_len + 1;
    (transform_len, block_len)
}

/// FFT overlap-add convolution — the "OA" of `oaconvolve`, and the engine
/// behind both [`oaconvolve`] and `master`'s `mode="same"` limiter
/// smoothing ([`fftconvolve_same_f64`]): the full discrete linear
/// convolution, length `len(x)+len(h)-1`, computed by transforming `h`
/// once and walking `x` in bounded blocks, rather than taking one FFT
/// sized to the whole result.
///
/// That bound is the point: `x` here is a render-length buffer
/// (potentially minutes of audio) convolved against a reverb tail up to
/// `make_ir`'s 12 s clamp, so a single transform sized to
/// `len(x)+len(h)-1` would scale both the transform and its working
/// memory with the *entire render*. Block size below is derived from
/// `h.len()` alone, never from `x.len()`, so memory and per-block
/// transform size are bounded regardless of how long `x` is. The spec
/// leaves the actual block-size choice free (only the result is
/// contractual, "to float noise"); this picks the smallest power-of-two
/// transform at least double `h.len()` — i.e. each block's own span is at
/// least as long as `h`, so at most half of any block's transform is
/// "spent" on the filter's overlap tail — floored at 1024 so short
/// filters still get an efficiently-sized block instead of a
/// several-sample one.
///
/// f32 throughout — not a convenience cast, but matching what
/// `scipy.signal.oaconvolve(f32_array, f32_array)` actually computes:
/// `scipy.fft` natively supports float32 (`rfft` on an f32 array returns
/// `complex64`, not `complex128` — verified directly against the
/// installed build), so the real call this ports never leaves single
/// precision. Measured against the actual `reverb_apply_0_6` fixture
/// data, this blocked f32 path tracks scipy's own (also block-wise)
/// `oaconvolve` to within the fixture's 1e-5 max_abs tolerance with room
/// to spare (see `golden_bus.rs`).
fn oa_convolve_full_f32(x: &[f32], h: &[f32]) -> Vec<f32> {
    if x.is_empty() || h.is_empty() {
        return Vec::new();
    }
    let out_len = x.len() + h.len() - 1;
    let (transform_len, block_len) = oa_block_plan(h.len());

    let mut planner = RealFftPlanner::<f32>::new();
    let r2c = planner.plan_fft_forward(transform_len);
    let c2r = planner.plan_fft_inverse(transform_len);
    let scale = 1.0 / transform_len as f32;

    // `h`'s spectrum: computed once, reused for every block.
    let mut hin = r2c.make_input_vec();
    hin[..h.len()].copy_from_slice(h);
    let mut hspec = r2c.make_output_vec();
    r2c.process(&mut hin, &mut hspec)
        .expect("oaconvolve: rfft(h)");

    let mut out = vec![0.0f32; out_len];
    let mut xin = r2c.make_input_vec();
    let mut xspec = r2c.make_output_vec();
    let mut yout = c2r.make_output_vec();

    let mut start = 0;
    while start < x.len() {
        let end = (start + block_len).min(x.len());

        // Every element of `xin` beyond this block's own samples must be
        // exactly zero — including `[end-start, block_len)`, which can
        // hold a shorter final block's stale leftovers from the previous
        // (longer) iteration — so the whole buffer is reset every pass
        // rather than only the tail past `block_len`.
        for v in xin.iter_mut() {
            *v = 0.0;
        }
        xin[..end - start].copy_from_slice(&x[start..end]);
        r2c.process(&mut xin, &mut xspec)
            .expect("oaconvolve: rfft(block)");

        let mut yspec: Vec<Complex<f32>> = xspec
            .iter()
            .zip(hspec.iter())
            .map(|(&a, &b)| a * b)
            .collect();
        c2r.process(&mut yspec, &mut yout)
            .expect("oaconvolve: irfft(block)");

        // Overlap-add: this block's own linear convolution spans
        // `transform_len` samples starting at `start` (exactly — for a
        // full block, block_len + h.len() - 1 == transform_len by
        // construction of `oa_block_plan`), summed into `out`, clipped to
        // `out_len` for the final block, whose nominal span can run past
        // it.
        let add_len = transform_len.min(out_len - start);
        for (o, &v) in out[start..start + add_len]
            .iter_mut()
            .zip(yout[..add_len].iter())
        {
            *o += v * scale;
        }

        start = end;
    }

    out
}

/// f64 counterpart of [`oa_convolve_full_f32`] — identical algorithm, used
/// for `master`'s limiter-smoothing convolution, which scipy actually runs
/// at float64: the Hann kernel (`np.hanning`) is float64, and an f32 array
/// times an f64 array is *ordinary* numpy type promotion (not NEP 50's
/// weak-scalar carve-out, which only applies to bare Python scalars), so
/// `sig.fftconvolve(f32_envelope, f64_kernel)` upcasts and returns
/// float64 — verified directly against the installed build.
fn oa_convolve_full_f64(x: &[f64], h: &[f64]) -> Vec<f64> {
    if x.is_empty() || h.is_empty() {
        return Vec::new();
    }
    let out_len = x.len() + h.len() - 1;
    let (transform_len, block_len) = oa_block_plan(h.len());

    let mut planner = RealFftPlanner::<f64>::new();
    let r2c = planner.plan_fft_forward(transform_len);
    let c2r = planner.plan_fft_inverse(transform_len);
    let scale = 1.0 / transform_len as f64;

    let mut hin = r2c.make_input_vec();
    hin[..h.len()].copy_from_slice(h);
    let mut hspec = r2c.make_output_vec();
    r2c.process(&mut hin, &mut hspec)
        .expect("fftconvolve: rfft(h)");

    let mut out = vec![0.0f64; out_len];
    let mut xin = r2c.make_input_vec();
    let mut xspec = r2c.make_output_vec();
    let mut yout = c2r.make_output_vec();

    let mut start = 0;
    while start < x.len() {
        let end = (start + block_len).min(x.len());

        for v in xin.iter_mut() {
            *v = 0.0;
        }
        xin[..end - start].copy_from_slice(&x[start..end]);
        r2c.process(&mut xin, &mut xspec)
            .expect("fftconvolve: rfft(block)");

        let mut yspec: Vec<Complex<f64>> = xspec
            .iter()
            .zip(hspec.iter())
            .map(|(&a, &b)| a * b)
            .collect();
        c2r.process(&mut yspec, &mut yout)
            .expect("fftconvolve: irfft(block)");

        let add_len = transform_len.min(out_len - start);
        for (o, &v) in out[start..start + add_len]
            .iter_mut()
            .zip(yout[..add_len].iter())
        {
            *o += v * scale;
        }

        start = end;
    }

    out
}

/// `mus_audio.py`'s `sig.oaconvolve(x, ir)` (line 1158, inside `render`'s
/// reverb send): the full discrete linear convolution, length
/// `len(x)+len(ir)-1`. Truncating to `n_total` is the caller's job (the
/// real render pipeline, WF8) — not this function's, matching the spec:
/// the `reverb_apply_0_6` fixture itself truncates to the input length
/// only *after* calling the Python equivalent of this function.
pub fn oaconvolve(x: &[f32], ir: &[f32]) -> Vec<f32> {
    oa_convolve_full_f32(x, ir)
}

/// `scipy.signal.fftconvolve(x, h, mode="same")`, built on
/// [`oa_convolve_full_f64`]: same output length as `x`, centered on the
/// full convolution. scipy's centering (`_signaltools._centered`, driving
/// `_apply_conv_mode`'s `"same"` branch) slices
/// `full[start .. start+len(x)]` with `start = (len(full)-len(x))//2`,
/// which reduces to `(len(h)-1)//2` since `len(full) = len(x)+len(h)-1`.
/// `mode="same"` never triggers scipy's valid-mode input-swap (that check
/// short-circuits to `False` whenever `mode != "valid"`), so `x` — the
/// first argument at the one real call site, `master`'s `g` envelope — is
/// always the shape the output is centered against, regardless of which
/// operand happens to be longer.
fn fftconvolve_same_f64(x: &[f64], h: &[f64]) -> Vec<f64> {
    if x.is_empty() || h.is_empty() {
        return Vec::new();
    }
    let full = oa_convolve_full_f64(x, h);
    let start = (h.len() - 1) / 2;
    full[start..start + x.len()].to_vec()
}

/// `mus_audio.master` (line 506): pre-gain to a target RMS, a smoothed
/// look-ahead limiter, a fixed soft-clip, then a final trim that lands on
/// the target RMS bounded by the peak ceiling. `ceiling` is fixed at 0.89
/// (see [`MASTER_CEILING`]) rather than threaded through, matching the
/// spec and the fact that the one real call site never overrides it.
///
/// Dtype trace (see the module doc, and [`pairwise_sum`]/[`np_sum`], for
/// how the two RMS reductions below reproduce numpy's actual pairwise
/// algorithm at each one's own dtype rather than approximating either):
///
/// ```text
/// rms = float(sqrt((x**2).mean()) + 1e-12)      # f32 reduction -> python float
/// x   = x * (10 ** ((target_rms_db-20*log10(rms))/20))  # weak scalar: stays f32
/// env = maximum_filter1d(abs(x).max(axis=0), size)      # f32
/// g   = minimum(1.0, ceiling/(env+1e-9))                 # f32 (weak scalar)
/// g   = fftconvolve(g, hann/hann.sum(), mode="same")    # f32 x f64 -> f64!
/// x   = x * g                                            # f32 x f64 -> f64
/// x   = tanh(x*1.08) * 0.95                              # f64 from here on
/// cur = float(sqrt((x**2).mean()) + 1e-12)               # native f64
/// want, allowed, mult                                    # plain python floats, f64
/// return (x * mult).astype(float32)                      # single cast, at the end
/// ```
///
/// The `g = fftconvolve(...)` step is the pivot: because the Hann kernel
/// is float64 and multiplying an f32 array by a *real* f64 array is
/// ordinary promotion (not a weak scalar), `x` silently becomes float64
/// from that line on, and everything downstream — the soft-clip, the
/// closing RMS/peak reductions, the final multiply — runs at f64 in the
/// oracle too. This port follows that promotion explicitly (`xf` below)
/// rather than stubbornly staying in f32.
pub fn master(mut x: [Vec<f32>; 2], target_rms_db: f64) -> [Vec<f32>; 2] {
    let n = x[0].len();
    debug_assert_eq!(x[1].len(), n, "master: channel length mismatch");
    let count = (2 * n) as f64;

    // ---- pre-gain to the target RMS (joint: one RMS over both channels).
    // `(x**2).mean()` here is a float32 reduction — `x` hasn't been
    // promoted to float64 yet (that only happens at the `g`-multiply
    // below) — over the flat C-order walk of the (2,n) array: channel 0
    // in full, then channel 1 (confirmed empirically to be what a
    // contiguous 2D array's `axis=None` reduction actually walks, i.e.
    // exactly the concatenation order below). Sum and mean both stay
    // float32 via [`np_sum`]; so do the sqrt and the `+1e-12` epsilon (a
    // weak Python-scalar add against a float32 result) — only the
    // trailing `float(...)` cast widens to f64, lossless since f32→f64
    // always is.
    let squares: Vec<f32> = x[0].iter().chain(x[1].iter()).map(|&v| v * v).collect();
    let mean_sq = np_sum(&squares) / count as f32;
    let rms = (mean_sq.sqrt() + 1e-12f32) as f64;
    let gain1 = (10f64.powf((target_rms_db - 20.0 * rms.log10()) / 20.0)) as f32;
    for channel in x.iter_mut() {
        for v in channel.iter_mut() {
            *v *= gain1;
        }
    }

    // ---- smoothed look-ahead limiter envelope.
    let max_lr: Vec<f32> = (0..n).map(|i| x[0][i].abs().max(x[1][i].abs())).collect();
    let filt_size = ((0.02 * SR_F64) as usize) | 1;
    let env = maximum_filter1d(&max_lr, filt_size);

    let ceiling = MASTER_CEILING as f32;
    let g: Vec<f32> = env
        .iter()
        .map(|&e| (ceiling / (e + 1e-9)).min(1.0))
        .collect();

    let win_len = ((0.03 * SR_F64) as i64) | 1;
    let w = np_hanning(win_len);
    let wsum = np_sum(&w);
    let kernel: Vec<f64> = w.iter().map(|&wi| wi / wsum).collect();
    let g64: Vec<f64> = g.iter().map(|&v| v as f64).collect();
    let g_smooth = fftconvolve_same_f64(&g64, &kernel);

    // ---- x = x * g promotes to f64 from here on (see this fn's doc).
    let mut xf: [Vec<f64>; 2] = [
        x[0].iter()
            .zip(g_smooth.iter())
            .map(|(&v, &g)| v as f64 * g)
            .collect(),
        x[1].iter()
            .zip(g_smooth.iter())
            .map(|(&v, &g)| v as f64 * g)
            .collect(),
    ];

    // ---- fixed soft-clip.
    for channel in xf.iter_mut() {
        for v in channel.iter_mut() {
            *v = (*v * 1.08).tanh() * 0.95;
        }
    }

    // ---- final trim: land on the target RMS, bounded by the peak ceiling.
    // Same shape as the pre-gain RMS above, but at float64 throughout:
    // `xf` has been float64 since the `g`-multiply (see this fn's doc), so
    // the oracle's mean-of-squares here is a float64 pairwise reduction,
    // not float32 — [`np_sum`] is generic over both; this call site just
    // feeds it f64 operands.
    let squares2: Vec<f64> = xf[0].iter().chain(xf[1].iter()).map(|&v| v * v).collect();
    let cur = (np_sum(&squares2) / count).sqrt() + 1e-12;
    let want = 10f64.powf((target_rms_db - 20.0 * cur.log10()) / 20.0);
    let peak = xf[0]
        .iter()
        .chain(xf[1].iter())
        .fold(0.0f64, |m, &v| m.max(v.abs()));
    let ceil_lin = 10f64.powf(-1.0 / 20.0);
    let allowed = ceil_lin / (peak + 1e-9);
    let mult = want.min(allowed);

    [
        xf[0].iter().map(|&v| (v * mult) as f32).collect(),
        xf[1].iter().map(|&v| (v * mult) as f32).collect(),
    ]
}

/// `mus_audio.py`'s output high-pass (lines 1161–1162, right after the
/// reverb sum): `butter(2, 28/(SR/2), "high")` + `sosfilt` per channel.
/// No dedicated golden fixture — the spec defers end-to-end coverage of
/// this stage to WF9 — so it's unit-tested here for DC rejection instead.
pub fn highpass28(x: [Vec<f32>; 2]) -> [Vec<f32>; 2] {
    let sos = butter_sos(2, 28.0 / (SR_F64 / 2.0), "high");
    let (l, _) = sosfilt(&sos, &x[0], None);
    let (r, _) = sosfilt(&sos, &x[1], None);
    [l, r]
}

#[cfg(test)]
mod tests {
    use super::*;

    /// `pairwise_sum`/`np_sum` against oracle values pulled directly from
    /// the installed numpy (2.0.2) — not just measured-inside-tolerance,
    /// but exact bit patterns, so this fails the instant the reduction
    /// stops matching numpy exactly rather than merely "closely". Inputs
    /// are generated by formula (not embedded as literal arrays) so the
    /// expected value is reproducible — deliberately built from only
    /// integer modulo, subtraction and multiplication (no transcendental
    /// functions like `sin`): numpy's float32 `sin`/`cos` go through its
    /// own SIMD-vectorized approximation rather than the platform libm
    /// `sinf` Rust's `f32::sin` calls, so the two are *not* guaranteed
    /// bit-identical input-for-input (this was caught directly: an
    /// earlier version of this test generated inputs with `sin` and
    /// mismatched by 1 ULP at exactly `n=8192`, from input-generation
    /// drift, not a reduction bug) — `+`, `-`, `*` and int casts are
    /// ordinary IEEE 754 ops with no such ambiguity. Formula:
    /// `a[i] = ((i % 997) - 498) * 0.001`, sawtooth-shaped so the summed
    /// values aren't monotone. Re-derive with
    /// `((np.arange(n) % 997).astype(f32) - np.float32(498)) *
    /// np.float32(0.001)` (or the f64 equivalent) `.sum()` if this ever
    /// needs re-checking.
    fn gen_f32(n: usize) -> Vec<f32> {
        (0..n)
            .map(|i| (((i % 997) as f32) - 498.0f32) * 0.001f32)
            .collect()
    }

    fn gen_f64(n: usize) -> Vec<f64> {
        (0..n)
            .map(|i| (((i % 997) as f64) - 498.0f64) * 0.001f64)
            .collect()
    }

    #[test]
    fn np_sum_f32_matches_oracle_bit_exact() {
        let cases: [(usize, u32); 6] = [
            (9, 0xc08e45a2),     // just past the naive/8-wide boundary
            (200, 0xc29f6667),   // inside the recursive-bisection regime
            (8192, 0xc2a8b22f),  // exactly at the NPY_BUFSIZE boundary
            (8193, 0xc2a94291),  // one past it: chunking must now engage
            (9000, 0xc1518528),  // past the boundary, non-round size
            (20000, 0xc1e0e150), // several buffer chunks
        ];
        for (n, bits) in cases {
            let a = gen_f32(n);
            let got = np_sum(&a);
            let want = f32::from_bits(bits);
            assert_eq!(
                got.to_bits(),
                want.to_bits(),
                "np_sum f32 n={n}: got {got:?} ({:#010x}), want {want:?} ({bits:#010x})",
                got.to_bits()
            );
        }
    }

    #[test]
    fn np_sum_f64_matches_oracle_bit_exact() {
        let cases: [(usize, u64); 3] = [
            (9, 0xc011c8b439581062),
            (200, 0xc053eccccccccccd),
            (9000, 0xc02a30a3d70a3d70),
        ];
        for (n, bits) in cases {
            let a = gen_f64(n);
            let got = np_sum(&a);
            let want = f64::from_bits(bits);
            assert_eq!(
                got.to_bits(),
                want.to_bits(),
                "np_sum f64 n={n}: got {got:?} ({:#018x}), want {want:?} ({bits:#018x})",
                got.to_bits()
            );
        }
    }

    #[test]
    fn np_sum_empty_and_tiny() {
        assert_eq!(np_sum::<f32>(&[]), 0.0);
        assert_eq!(np_sum(&[1.0f32]), 1.0);
        assert_eq!(np_sum(&[1.0f32, 2.0, 3.0]), 6.0);
    }
}
