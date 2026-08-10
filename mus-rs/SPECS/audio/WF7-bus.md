# WF7 — buses, reverb, master (`mus-dsp/src/bus.rs`)

Depends on WFRNG (`np-rand`), WF3 (filters), WF2 (`maximum_filter1d`,
`np_hanning`). Port the room and the mastering chain.

1. **`make_ir(seconds) -> [Vec<f32>; 2]`** — port `mus_audio.make_ir`
   (seed fixed at 7): `n = int(seconds*SR)`; noise =
   `default_rng(7).standard_normal((2, n))` via np-rand (**row-major**:
   channel 0 is draws 0..n, channel 1 is draws n..2n) × envelope
   `exp(-4.2·t/seconds)` (f64 env times f64 noise, cast f32 — mirror
   numpy: `standard_normal((2,n)).astype(float32) * env` — check the
   Python line: `rng.standard_normal((2, n)).astype(np.float32) * env`
   promotes back to f64, then `.astype(float32)` after the filter — read
   it and mirror the exact cast points); `butter(2, 5200/(SR/2), low)`
   `sosfilt` per channel; 18 ms zero pre-delay prepended; normalize each
   channel? No — **joint**: `ir /= sqrt(sum(ir², axis=1, keepdims)) +
   1e-9` is per-channel (axis=1 keeps rows) — per-channel energy, then
   `× 0.9`. Fixtures: `make_ir_0_6`, `make_ir_2_6`, `make_ir_4_5`
   (`max_abs 1e-6`, planar stereo — split expected in half).
2. **`oaconvolve(x, ir) -> Vec<f32>`** — FFT overlap-add convolution
   (use `realfft`), full length `len(x)+len(ir)-1`; the render truncates
   to `n_total` at the call site. Match scipy's `oaconvolve` numerics to
   `max_abs 1e-5` — block-size choice is free (it must not affect the
   result beyond float noise). Fixture: `reverb_apply_0_6` (input mono,
   convolved with make_ir(0.6)'s two channels, planar expected, truncated
   to input length).
3. **`master(x: [Vec<f32>; 2], target_rms_db) -> [Vec<f32>; 2]`** — port
   `mus_audio.master` step-for-step (ceiling fixed 0.89):
   - pre-gain to RMS target: joint RMS over both channels
     (`sqrt(mean(x²))` over the 2×n array).
   - limiter envelope: `maximum_filter1d(max(|L|,|R|) per sample, size =
     int(0.02*SR)|1)` (WF2); gain `min(1, 0.89/(env+1e-9))`; smooth by
     `fftconvolve(g, hann/Σhann, mode="same")` with `np_hanning(int(0.03*
     SR)|1)` — implement `fftconvolve same` via your §2 FFT machinery
     (same-mode centering must match scipy).
   - `tanh(x·1.08)·0.95`.
   - final trim: `want` = gain to hit target RMS; `allowed` =
     `10^(-1/20) / max|x|`; multiply by `min(want, allowed)`.
   Fixture: `master_rms14` (`max_abs 5e-4`, planar stereo).
4. **`highpass28(x) -> x`** — the output high-pass: `butter(2, 28/(SR/2),
   high)` + `sosfilt` per channel (WF3 pieces; no own fixture — covered
   by WF9 end-to-end; unit-test DC rejection).

**Tests:** golden for the five fixtures; a linearity unit test for
`oaconvolve` (conv(a+b) == conv(a)+conv(b) within float noise); a
determinism test for `make_ir` (two calls identical).

**If np-rand did not land** (check whether `np_rand::Pcg64` exists and its
tests are green): implement everything except `make_ir`'s noise source and
load the `make_ir_*` fixture binaries as the IR source behind the same
function signature, with a loud `// FALLBACK` comment and a note in your
summary. Do not approximate the RNG.

**DoD:** builds; `cargo test -p mus-dsp` green; fmt clean; tests in diff.
