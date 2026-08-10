# WF4 — resampling, phase vocoder, pitch geometry (`mus-dsp/src/pitch.rs`)

The hardest DSP stage. Four families:

## 1. `varispeed(x, semitones)` — libsoxr (same C library as the oracle)

Python: `librosa.resample(x, orig_sr=len(x), target_sr=n_out,
res_type="soxr_hq")` with `n_out = max(8, round(len(x)/rate))`,
`rate = 2^(st/12)`; passthrough when `|st| < 1e-4` or `len < 8`.

librosa's `soxr_hq` calls the `soxr` python package = **libsoxr**, which the
`libsoxr` crate (already a dependency) binds. Match the quality recipe:
python-soxr "HQ" is libsoxr's `SOXR_HQ` preset (20-bit). Iterate the
crate's `QualitySpec`/`IOSpec` settings until the fixtures pass —
`varispeed_up5` and `varispeed_down12` at `rel_rms 5e-4` with **exact
output lengths** (25172 and 33600). Note librosa uses the "rates are the
two lengths" trick — arbitrary rational ratio, one-shot (not streaming)
resample of the whole buffer; use soxr's oneshot API. If the binding
cannot reach 5e-4, report the best recipe found and its measured rel_rms —
do not silently fall back to rubato.

## 2. `vocode(x, st)` / `stretch(x, factor)` — librosa's phase vocoder, ported

Passthroughs: `vocode` when `|st| < 1e-4` or `len < 2048`; `stretch` when
`|factor-1| < 1e-3` or `len < 2048`.

Port the exact algorithm from `.venv/lib/python3.12/site-packages/librosa/`
(read `effects.py` `pitch_shift`/`time_stretch`, `core/spectrum.py` `stft`/
`istft`, `core/audio.py` `phase_vocoder`):

- `stft`: n_fft=2048, hop=512, hann window (scipy `get_window('hann')` =
  periodic? — read the source; librosa uses `filters.get_window` →
  symmetric=False), center=True with **reflect** padding.
- `phase_vocoder(D, rate)`: time steps `arange(0, n_frames, rate)`, linear
  magnitude interpolation between consecutive frames, accumulated phase
  advance: `phi_advance = linspace(0, π*hop, 1+n_fft/2)` plus wrapped phase
  deviation.
- `istft`: inverse rFFT per frame, hann-windowed overlap-add with
  window-sum-squares normalization, `length=` trimming.
- `pitch_shift(x, sr, n_steps, bins_per_octave=12)`: `rate =
  2^(-st/12)`, `time_stretch(x, rate=1/rate)`? — read the source for the
  exact composition, then `resample(..., res_type="soxr_hq")` (reuse your
  §1 machinery) and `util.fix_length` to the input length.
- `time_stretch(x, rate)`: `phase_vocoder(stft(x), rate)` → `istft` with
  `length = round(len(x)/rate)`.

Use `realfft` (already a dependency). FFT numerics differ from numpy's at
~1e-7 — the manifest tier is `rel_rms 5e-3` with exact lengths. Fixtures:
`vocode_up35`, `vocode_down7`, `stretch_140`, `stretch_060`.

## 3. `pitch_ramp` / `pitch_polyline` — pure numpy geometry

Port verbatim (`max_abs 1e-5`), reading `mus_audio.py`:

- `pitch_ramp(x, st0, st1, curve, tau)`: degenerate → `varispeed(x, st0)`;
  ramp array f64 (`np.linspace` / `exp` on `arange/SR`); iterative length
  solve (3 rounds: `n_out = max(16, n_out*(n_in-1)/total)` with
  `total = Σ 2^(ramp/12)`); read positions `pos = cumsum(2^(ramp/12))`
  clipped to `[0, n_in-1]`; linear interpolation (`np.interp` semantics)
  of the f32 signal; `< 8` positions → `varispeed(x, st1)`. Fixtures:
  `pitch_ramp_lin`, `pitch_ramp_exp_kick` (the exp case ends at 158984
  samples — the length solve must converge identically).
- `pitch_polyline(x, t_anchor, st_anchor)` (anchors in args): duration from
  anchor span, `n_out = max(16, int(dur*SR))`; st interpolated over a
  linspace of times; `pos = cumsum(rate) - rate[0]`; the tape-runs-out
  branch: valid mask, 10 ms fade at the boundary (`f = min(k, int(0.010*
  SR))`, applied when `f > 1`), zeros after. Fixture: `pitch_polyline`.

## 4. `load_decode(path)` — the sample/tape load path

`librosa.load(path, sr=SR, mono=True)` where every corpus asset is already
SR-native (48 kHz): pure decode. Implement with `hound` (already a
dependency): PCM_16 → f32 by `/32768.0`; FLOAT wavs read verbatim; stereo
would average to mono (assets are mono; implement the general rule).
If a file's native rate ≠ SR, resample with §1's soxr machinery (that is
what librosa would do) — cover with a unit test via a synthetic wav, and
note the corpus never hits it today. Fixture: `load_buzz01_native`
(`max_abs 1e-6` against the real pack sample).

**Tests:** golden per fixture; a `fix_length`-style unit test that
`vocode` output length always equals input length; a determinism test
(same input twice → identical output).

**DoD:** builds; `cargo test -p mus-dsp` green; fmt clean; tests in diff;
any tolerance you could not meet reported with measured numbers, not
widened.
