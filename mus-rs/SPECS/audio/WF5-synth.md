# WF5 — the subtractive soft synth (`mus-dsp/src/synth.rs`)

Depends on WF3 (`sweep_filter`). Two functions, both `max_abs` tier.

1. **`osc(wave, phase) -> Vec<f32>`** — port `mus_audio._osc`: `frac =
   phase - floor(phase)`; square = ±1 at frac<0.5; tri = `2|2·frac-1|-1`;
   sine = `sin(2π·frac)`; default saw = `2·frac-1`. Phase arrives as f64
   (fixture `osc_phase` is the shared input), output f32. Fixtures:
   `osc_saw`, `osc_square`, `osc_tri`, `osc_sine` (`max_abs 1e-6`).

2. **`synth_note(patch, freqs_hz, slot_s, gliss_ratio) -> Vec<f32>`** —
   port `mus_audio.synth_note` with its exact dtype flow (this is where
   ports usually drift — numpy accumulates the phase **in f32** here):
   - `n = max(64, int((slot_s + srel) * SR))`.
   - Per fundamental `f`: `ramp` = f32 linspace 1→gliss_ratio (only when
     `|ratio-1| > 1e-6`, else scalar 1.0); `freq = f * ramp` (f32);
     `phase = cumsum(freq)/SR` — **f32 cumsum**, matching numpy; tone =
     osc(wave, phase).
   - `detune` cents > 0: add `osc(wave, cumsum(freq*r)/SR)` and
     `osc(wave, cumsum(freq/r)/SR)` with `r = 2^(det/1200)`, divide by 3.
   - `osc2`: mix `(1-mix2)*tone + mix2*osc(osc2, cumsum(freq)/SR * 2)`.
   - `sub` > 0: `+ sub * osc("sine", cumsum(freq*0.5)/SR)`.
   - Sum over fundamentals, `/ sqrt(len(freqs))`.
   - ADSR: env full of `ssus`; attack `linspace(0,1,na)`; decay
     `linspace(1,ssus,nd2)` with `nd2 = min(nd, n-na)`; from `ns =
     int(slot_s*SR)`: multiply tail by `linspace(1,0,n-ns)^1.4` **scaled
     by env[min(ns, n-1)]** (release starts from the level it was at).
   - Filter: `famt > 0` → `sweep_filter(out, cutoff+famt, cutoff, "low")`,
     else static `sweep_filter(out, cutoff, cutoff, "low")`.
   - Return `out * 0.5`.

   Patch defaults: satk 0.004, sdec 0.05, ssus 0.75, srel 0.12, wave
   "saw", mix2 0.5, detune 0, sub 0, cutoff 4200, famt 0. Represent the
   patch as a small struct with these defaults (`From<&BTreeMap>` or a
   builder — WF8 will feed it from event params; keep the constructor
   string-typed friendly).

   Fixtures: `synth_note_funk_bass` (saw + detune + sub + filter
   envelope), `synth_note_chord_gliss` (square + osc2, 3-note chord,
   gliss_ratio 1.5) — `max_abs 5e-5` (the tolerance absorbs the filter).

**Tests:** golden per fixture; a unit test that chord normalization is
`1/sqrt(k)`; a unit test that `slot+srel` sizing yields `n ≥ 64`.

**DoD:** builds; `cargo test -p mus-dsp` green; fmt clean; tests in diff.
