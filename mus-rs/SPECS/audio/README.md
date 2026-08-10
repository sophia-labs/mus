# Audio-parity leg — full render pipeline in Rust

**Mission.** Port the complete `mus_audio.py` render path into the Rust
workspace at sample-level parity, so `mus-cli render` can replace the Python
renderer. Python's role after this leg: migration oracle, not implementation.

**The oracle is executable.** `mus-rs/tools/gen_dsp_fixtures.py` dumps golden
input/output vectors from the Python functions into `mus-rs/fixtures/dsp/`
(49 cases, `manifest.json` carries args + metric + tolerance per case).
Tests replay cases through `mus_dsp::fixtures` (see
`crates/mus-dsp/tests/golden_kernels.rs` for the exemplar pattern). Rules:

- **Tolerances live in the manifest, never in test code.** If your port
  cannot meet a case's tolerance, do not widen it — report the measured
  divergence in your summary. Refusal is a result.
- **Output length is part of the contract** — a length mismatch is a hard
  failure under every metric.
- Parity tiers: pure-numpy ports = `max_abs` 1e-6..5e-5; same-C-library
  (libsoxr) = `rel_rms` 5e-4; reimplemented-algorithm (phase vocoder) =
  `rel_rms` 5e-3 with exact lengths.

**Numeric discipline for ports.** Mirror numpy's dtype flow: numpy arange /
linspace default to f64; `.astype(np.float32)` marks the cast points; a
python-float scalar times an f32 array stays f32. When the Python does its
cumsum in f32 (e.g. `synth_note` phase), the port must accumulate in f32
too — matching precision loss is part of matching the oracle.

**Module ownership (pre-laid; do not touch other stages' files):**

| Stage | Files | Depends on |
|---|---|---|
| WF2 | `mus-dsp/src/kernels.rs` | — |
| WF3 | `mus-dsp/src/filters.rs` | — |
| WF4 | `mus-dsp/src/pitch.rs` | — |
| WFRNG | `np-rand/src/lib.rs` (may add modules) | — |
| WF5 | `mus-dsp/src/synth.rs` | WF3 |
| WF6 | `mus-dsp/src/glow.rs` (new; add `pub mod glow;` to lib.rs) | WF4, WF3, WF2 |
| WF7 | `mus-dsp/src/bus.rs` | WFRNG, WF3, WF2 |
| WF8 | `mus-engine/src/*`, `mus-cli` render verb | all |
| WF9 | `mus-rs/tools/parity_render.py`, `mus-cli/tests/` | WF8 |

Rounds: R1 = {WF2, WF3, WF4, WFRNG} in parallel worktrees · R2 = {WF5, WF6,
WF7} in parallel worktrees · R3 = WF8 then WF9. Each stage: implement in
your worktree, write your own golden tests, leave the tree building +
green + `cargo fmt`-clean. A gate verifies (witness only), Terra reviews
the staged diff, a landing clerk commits on approval.

**Every stage ships its own tests in the same diff.** A stage whose diff
contains no test files fails its gate — this is the system working.

**Reference locations.** Python oracle: `mus_audio.py` at repo root (function
names cited per spec; grep, don't trust line numbers). librosa/scipy source
for algorithm porting: `.venv/lib/python3.12/site-packages/{librosa,scipy}/`
— read the actual implementation you are matching. numpy RNG reference:
numpy's `_bit_generator`/`distributions` sources (WFRNG spec details).
