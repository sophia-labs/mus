//! Sample-faithful DSP for the MUS render face.
//!
//! Every public function here is a port of the equivalently named function
//! in `mus_audio.py`, and the oracle is not prose: `mus-rs/tools/
//! gen_dsp_fixtures.py` dumps golden input/output vectors from the Python
//! implementation into `mus-rs/fixtures/dsp/`, and every port carries a
//! test that replays them through [`fixtures`]. A passing suite means
//! "same math", not "similar idea".
//!
//! Parity tiers (the manifest records the metric and tolerance per case):
//!
//! - **Pure-numpy ports** (`kernels`, `synth`, most of `filters`,
//!   `pitch::pitch_ramp`/`pitch_polyline`): `max_abs` at 1e-6..5e-5 —
//!   effectively exact in f32.
//! - **Same-C-library paths** (`pitch::varispeed` via libsoxr, the same
//!   library librosa's `soxr_hq` binds): `rel_rms` at 5e-4.
//! - **Reimplemented-algorithm paths** (`pitch::vocode`/`stretch`, a port
//!   of librosa's STFT phase vocoder over a different FFT): `rel_rms` at
//!   5e-3, with exact output lengths.
//!
//! Where the port cannot meet its tier, the correct move is to say so —
//! record the measured divergence and surface it, never to widen a
//! tolerance silently. Refusal is a result.

pub mod bus;
pub mod filters;
pub mod fixtures;
pub mod glow;
pub mod kernels;
pub mod pitch;
pub mod pluck;
pub mod synth;

/// Engine sample rate. `mus_audio.py` line 47: `SR = 48_000`.
pub const SR: usize = 48_000;
/// `SR` as f32, for rate math in kernel code.
pub const SR_F: f32 = 48_000.0;
/// `SR` as f64, for phase/frequency math done in double precision.
pub const SR_F64: f64 = 48_000.0;
