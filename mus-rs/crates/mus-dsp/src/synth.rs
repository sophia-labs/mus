//! The subtractive soft synth: `_osc` (naive saw/square/tri/sine on a
//! phase array) and `synth_note` (detuned unison, optional osc2 and sub,
//! ADSR, filter-envelope sweep) — `mus_audio.py` lines 232–295.
//!
//! Owned by stage WF5 (depends on WF3's `sweep_filter`). Oracle cases:
//! `osc_phase` + `osc_{saw,square,tri,sine}`, `synth_note_funk_bass`,
//! `synth_note_chord_gliss` (max_abs 5e-5).
