//! Bus processing: the seeded reverb impulse (`make_ir`, needs np-rand),
//! overlap-add convolution for the wet bus, the sidechain duck envelope
//! application, and the RMS-target `master` chain with its smoothed
//! look-ahead limiter — `mus_audio.py` lines 418–471 and 1147–1164.
//!
//! Owned by stage WF7 (depends on np-rand and WF3). Oracle cases:
//! `make_ir_{0_6,2_6,4_5}` (max_abs 1e-6), `reverb_apply_0_6` (1e-5),
//! `master_rms14` (5e-4), `maximum_filter1d` (in kernels).
