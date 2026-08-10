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
//! `mus_audio.make_ir` depends on that ordering for its stereo IR.
//!
//! This crate exists because the mus render face reproduces
//! `mus_audio.make_ir` — a reverb impulse built from
//! `default_rng(7).standard_normal((2, n))` — sample-for-sample. It is
//! deliberately dependency-free and usable standalone: NumPy-stream
//! compatibility is a recurring need when porting scientific Python to
//! Rust, and nothing maintained on crates.io provides it.
