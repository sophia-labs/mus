//! scipy-parity IIR filtering: Butterworth design to second-order sections,
//! `sosfilt`, `sosfilt_zi`, and the block-interpolated [`sweep_filter`] of
//! `mus_audio.py` line 385.
//!
//! Owned by stage WF3. Oracle cases: `sos_butter*` (coefficient tables,
//! f64, `max_abs 1e-10`), `sosfilt_low_noise`, `sosfilt_zi_low_1200`,
//! `sweep_static_low`, `sweep_low_fall`, `sweep_high_rise`.
