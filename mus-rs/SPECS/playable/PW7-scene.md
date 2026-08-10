# PW7 — the scene renderer: `mus-dsp/src/scene.rs` + CLI verb

Port the offline half of the spatial scene contract to Rust. Oracle:
`mus_analysis/spatial_render.py` (`render_stereo`, `render_foa`) over
`mus_analysis/spatial_scene.py` (`SpatialScene`/`SpatialObject`/
`Position`/`PositionKeyframe`/`Room`/`Listener`). Read BOTH files top to
bottom — including `_spatialize_stereo_object`, `_synthetic_room`,
`apply_controls` — before writing a line. Golden fixtures are already
dumped: `mus-rs/fixtures/scene/` (3 scenes, stereo planar f32le, one FOA,
`manifest.json` owns metric+tol; scene JSONs produced by the oracle's own
`to_dict`).

Deliverables:
1. **`mus-dsp/src/scene.rs`** (+ `pub mod scene;` in lib.rs): serde types
   for the scene JSON exactly as `to_dict` emits it (unknown fields
   preserved-or-ignored deliberately — document which); coordinate math
   (`Position`: −Z front, azimuth `atan2(x, −z)`, spherical constructor);
   keyframe interpolation and the oracle's block-interpolated
   spatialization (`block_size = 256`), equal-power pan + spread +
   distance model + listener pose EXACTLY as `_spatialize_stereo_object`
   computes them; object pipeline (load stem via `pitch` load path;
   resample via soxr ONLY when stem sr ≠ scene sr; `duration_seconds`
   trim; gain; start placement); room bus → `_synthetic_room` port
   (seeded noise via **np-rand** — it must reproduce the numpy stream for
   the fixture seeds; scipy filter bits via `filters`); wet mix; the
   0.98 peak-safety scale; a receipt mirroring `RenderReceipt`
   (`renderer: "mus.spatial-stereo/1"`, safetyGainDb, per-object
   receipts, the honest `claim` string).
2. **`render_foa`** for the same scenes (4-channel ACN/SN3D as the
   oracle does it — read `render_foa`, do not guess).
3. **`PsychoacousticControls`**: implement exactly the subset the
   fixture scenes exercise (they use defaults — verify what
   `apply_controls` does with defaults and match it); any non-default
   control encountered at render time is a **typed refusal**
   (`unsupported-control`, naming the control) — never a silent skip.
4. **CLI**: `mus scene-render <scene.json> --root <dir> [-o out.wav]
   [--foa]` printing the receipt JSON; plus service method
   `renderScene {sceneJson, root}` in `service.rs` returning the same
   PCM-envelope shape as `renderScore` (memoized by content).
5. **Tests** (same diff): golden per fixture (stereo max_abs 2e-5;
   FOA same; frames exact; safetyGainDb matches manifest); invariants:
   determinism (same scene → same digest), silence-in → silence-out,
   azimuth mirror symmetry (−az swaps channels within tolerance on a
   room-off scene); a refusal test for an unsupported control.

House rules as ever: fmt clean, workspace tests green, uncommitted,
own files only (`scene.rs`, service/CLI additions, tests). If a
tolerance cannot be met, report the measured number — the manifest is
the only place tolerances change.
