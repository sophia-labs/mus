//! Pitch and time: varispeed (libsoxr, the same C library behind librosa's
//! `soxr_hq`), the librosa-compatible STFT phase vocoder (`vocode`,
//! `stretch`), the pure-numpy `pitch_ramp` and `pitch_polyline`, and the
//! sample/tape load path.
//!
//! Owned by stage WF4. Oracle cases: `varispeed_*` (rel_rms 5e-4),
//! `vocode_*`/`stretch_*` (rel_rms 5e-3, exact lengths), `pitch_ramp_*`,
//! `pitch_polyline` (max_abs 1e-5), `load_buzz01_native` (max_abs 1e-6).
