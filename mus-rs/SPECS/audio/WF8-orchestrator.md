# WF8 — the render orchestrator (`mus-engine` + `mus-cli render`)

Rewrite `mus-engine`'s render path on top of `mus-dsp`, to full semantic
parity with `mus_audio.render()` (read it top to bottom in `mus_audio.py`;
it is ~340 lines and every branch is in scope). `mus-cli check`'s event
walk (`crates/mus-cli/src/check.rs`) already reproduces the layout
semantics at report parity — treat it as the semantic reference for
bar-time math, swing, and token handling; `mus_audio.py` is the oracle for
everything the check path skips (sample selection, DSP application,
mixing, buses).

The full checklist, in oracle order (grep `mus_audio.py` for each):

- **Headers**: `tuning` (A=… regex), `pack`, `gestures`, `tape` (load via
  `mus_dsp::pitch` load path), `swing` (unit+pct, the `swung()` mapping —
  onsets only), `sidechain` (track, depth, rel), `reverb` (seconds,
  clamped [0.3, 12]), `master` (rms=…).
- **Voices**: pack resolution, `sample=` override, `root=` fallback f0,
  synth patches from SYNTH_KEYS, per-track defaults (params not in
  STRUCTURAL_PARAMS ∪ SYNTH_KEYS become event defaults), `gain`/`pan`/
  `send`/`mode`, missing-source tracks skipped with a warning.
- **Bar map**: tempo/time changes (header + inline), bar_start/qlen/spq,
  `total_s = end + 4.0`.
- **Event walk per track**: dynamics state (DYN_DB), hairpins (retroactive
  ±9 dB linear-in-index spans over `pending`, resolved at `{|}` or track
  end), rests advance time, `split_attached_dynamics`, pattern-repetition
  expansion, unparseable tokens recorded (stats parity matters — WF9
  compares receipts).
- **Source**: synth (patch merge: voice patch ⊕ event SYNTH_KEYS; gliss
  ratio from `gliss_midi`; needs-pitch error) vs sample (`s=` 1-based
  clamped select, `off=` ms trim, `reverse` flag, `< 32` samples skip).
- **Transposition**: `st` from first midi vs sample f0; `st_end` from
  gliss; unpitched `st=` param-pair; `curve`/`tau`.
- **Quotation**: `gest=` + `gsrc=raw` (tape slice by contour t0/t1;
  notated pitch → `vocode` shift from median, |shift| > 0.05; X events
  verbatim) and `gest=` pack-sample polyline (`glayer` anchors, `base_st +
  12·log2(hz/med)` trajectory → `pitch_polyline`); all failure modes
  produce the same stats/bad strings as Python.
- **Chords**: all tones layered (varispeed per tone, or vocode when
  `mode=vocoder`), `1/sqrt(k)` normalization; quoted events skip chord
  layering.
- **Transforms** in exact order: `chop` → `ring` (`rwet`) → glow (guard
  `len ≥ 2048`, `mus_dsp::glow::glow_chain`) → `str` (`fit` = stretch to
  slot, else factor) → articulation cuts (ART_SHORTEN flags, `gate`,
  `fer` = stretch 1.75) → envelope (`atk`/`rel`, `mus_dsp::glow::
  event_envelope`) → `lpf`/`hpf` (param_pair sweeps) → `drive` →
  `dist` → `crush`/`decim` → `stut`.
- **Level & placement**: DYN_DB + voice gain + ART_GAIN + `gain=` param;
  onset sample truncation at `n_total`; `< 32` samples skip; pan
  param-pair → `pan_stereo`; `haas`; `send`.
- **Mixing**: eager per-bar flush when no sidechain (memory discipline);
  deferred `placed` when sidechaining; duck envelope from trigger onsets
  applied to ducking tracks (`duck=` opt-out, trigger track exempt); wet
  bus = send-scaled copy.
- **Buses**: `make_ir(reverb_s)`, `oaconvolve` per channel truncated to
  n_total, dry + wet; `highpass28`; `master(target_rms)`.
- **Output**: 24-bit PCM WAV at the oracle's convention — match
  `soundfile` PCM_24 conversion (float × 2²³, clip, round-to-nearest-even;
  verify against a Python-written file in a unit test); plus the existing
  render receipt (peak/rms/event counts) extended with: sidechain hit
  count, bad-token list, per-track event counts — the receipt is what WF9
  diffs first.
- **CLI**: `mus-cli render <score.mus> [--base <dir>] [-o <out.wav>]`,
  exit 0 with a receipt on stdout (JSON), refusals as structured errors.

Keep the existing `RenderedAudio`/`RenderError` surface where it fits;
replace rubato internals with `mus_dsp::pitch`. Add `mus-dsp` to
`mus-engine`'s dependencies. Delete nothing that `check` uses.

**Tests**: unit tests for hairpin math, duck opt-out, eager-vs-deferred
equivalence on a no-sidechain score; an integration test rendering
`aigua/smoke.mus` and asserting receipt fields against
`mus-cli/tests/` conventions; a PCM_24 byte-level round-trip test.

**DoD:** workspace builds; all tests green; fmt clean; tests in diff;
`mus-cli render aigua/smoke.mus` produces a wav and a receipt.
