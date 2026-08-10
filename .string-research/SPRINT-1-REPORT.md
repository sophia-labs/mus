# Ariadne sprint 1 — implementation agent report

**Branch:** `agent/weave-string-network` (this file lands with the final sprint commit; per-stage commits: `190cb6c` assembly+dispersion fix, `6c3b46a` wiring+scores, `1bd03e0` clippy hygiene, then measurements/report).
**Baseline:** handoff `bf2d9cb` merged with `agent/aigua-analysis-foundation` at `0339aed` (merge `836f583`).

## What was implemented

The full P0 sequence from HANDOFF.md:

1. Payload assembled via `assemble.sh --apply` (validated: 1181 + 363 lines, sentinels intact).
2. Compiled with **one warning** on first `cargo check` (dead `DelayString.active` field — removed). No structural defects. This is remarkable for blind-drafted DSP and is noted as such.
3. Invariant suite: **10 of 11 passed on first run**. The one failure was a genuine model defect (below), not an estimator defect. Zero tolerances were widened; one bound was *raised with its measurement written into the test* (below).
4. `synth=weave` dispatched in `mus-engine/src/source.rs` exactly per the handoff's match shape; `SYNTH_KEYS` extended with the 12 names; the typed vocabulary gained `weave` in the synth enum plus all 12 controls; `mus vocab` dump tests assert the enum, an `hz` control, the signed `chirality` ratio, a `count`, and `dimension`'s range.
5. Both research scores land in `aigua/` **unmodified** — they parse and round-trip through `mus-text` as-written (corpus pins 13 → 16; the pin was already stale at 14 from our own `pluck_demo.mus`).
6. Whole-repository gates: `cargo fmt` clean; `cargo test --workspace` **213 tests green across 31 suites**; `cargo clippy --workspace --all-targets -- -D warnings` passes — for the first time in this repo's history (pre-existing debt in seven crates cleaned; `np-rand` and two checker functions carry justified allows).

## Changes from the handoff, and why

1. **Stiffness dispersion mapping replaced.** Staged: `a = −0.72·stiff^0.75`. Measured 5th-partial sharpening at 110 Hz, stiff=0.75: **+0.16 cents** — an order of magnitude below physical guitar inharmonicity and below the invariant test's own estimator resolution (it failed with `ratio 1.000000` on both sides). Landed: `a = −0.93·stiff^0.35`, which measures ~0.03 c at the 0.08 default, ~4.6 c at 0.75, ~44 c at 1.0 (110 Hz; roughly ×6 at 220 Hz). Tuning stays exact at the fundamental via the payload's own phase-budget compensation; the budget-shrink loop protects short high-note loops. The test passes with no threshold change.
2. **`detune` registry unified at 0..100 cents** (PARAMETERS.md option 1): the string clamp was raised to match the existing public vocabulary rather than documenting a model-specific 60.
3. **`body` default kept at the public 0.25**, per the parameter contract's own instruction that 0.42 is a listening decision. The demo scores carry stronger explicit values (0.32–0.84), so the A/B material exists; the default moves only after ears vote.
4. **Dead `active` field removed** from `DelayString`/`DelayStringSpec` (played-course bookkeeping lives in `StringNetworkVoice.active_count`).
5. **Parity harness skips post-parity scores loudly** (`synth=pluck|weave` ⇒ printed skip, never silent shrinkage): those voices have no oracle line by definition.
6. **Invariant suite extended** beyond the payload: the zero-limit laws of PARAMETERS.md §9 tested directly (couple=0 ∧ body=0 makes chirality/orbit/orbit_depth/curvature/dimension byte-inert; orbit_depth=0 makes orbit byte-inert under live coupling); E6 (1318.5 Hz) joins the tuning sweep; boundedness now also probed **under an upward-fifth bend** at both extreme patches.

## Measurements

**Tuning (invariant test):** E2–E6 (82.4/110/220/440/880/1318.5 Hz), settled estimate within **8 cents** everywhere (test tolerance; autocorrelation + parabolic refinement).

**T60 honesty (raw voice output, Goertzel at the fundamental, damp=0):** requested 0.5/1/2/4 s measured −53.0/−56.5/−58.3/−59.2 dB at t=sus — converging on −60 with the residual consistent with the 100 ms measurement windows. **By band (sus=2, damp=0.35):** fundamental −30.0 dB after exactly 1 s — precisely the promised 60·t/T60 slope, i.e. the §7 damping-magnitude compensation works — while h2/h3/h5 run −30.3/−31.0/−33.4 dB. `sus` means what it says at the fundamental; `damp` shapes the spectrum above it.

**Caveat discovered while measuring:** full-engine renders pass the master limiter (receipts show peak exactly −1.0 dBFS), so end-to-end decay measurements understate the string's own T60. All decay numbers above are raw `pluck_note` output.

**Path memory (E14 shape):** identical patch, chirality +0.92 vs −0.92, five-note chord: **relative RMS distance 0.713** between the two renders, with loudness within 0.7 dB (−20.2 vs −19.5 dBFS) and spectral centroid within 1.4 % (1765 vs 1790 Hz). Order of traversal is a first-class audible variable, not a level or EQ artifact. Determinism and difference are also locked by tests (`weave_is_path_sensitive_but_deterministic`).

**Local order defect (E13):** the closed form `weave_holonomy_defect` matches the basis-vector Frobenius computation to <1e-13 (in-module test). The ‖U−V‖₂ = ‖U−V‖_F/√2 identity from ARIADNE-MATHEMATICS §5 is exercised numerically; Lean formalization remains backlog.

**Spectral-dimension scaffold (E19 shape):** sustained-segment peak lattices on A2, courses=15, couple=0.13 — measured peak-ratio sets differ per `d` (d=1.35 shows 1.67/2.31 among 1/2/3; d=2.6 compresses to 2.00/2.12/2.61/2.87; d=1.0 collapses toward near-harmonic 1.97/2.03/3.00). The 0.89 line present at every `d` is the 98 Hz body mode, as it should be. `dimension` is audible as lattice structure.

**Boundedness under modulated delay — the predicted gap, demonstrated:** the extreme weave patch (couple 0.45, chirality 1, orbit 20 Hz, depth 1, curvature 1, body 1, courses 24) peaks **3.24 unbent** and **5.38 during an upward-fifth bend** — a ~0.3 s energy transient (+66 %) that then decays monotonically to silence. This is exactly HANDOFF issue A / MATHEMATICS §3's "time-varying propagation is not an isometry," now with numbers. It is bounded and physically interpretable (the fretting hand does work on a shortening string), but it is **empirical boundedness, not passivity**. The invariant bound for the bent case is 8.0 with the measurement and reasoning written into the test. Resolution chosen: **option 3 (narrowed claim)**; energy-compensated retuning (Virtual Slide Guitar lineage) is the round-2 item.

**Renders (Gate G/A render halves):**
- `guitar_upgrade_demo.mus`: 36.7 s, 66 events, peak −1.0 dBFS, RMS −16.16, wall 18.2 s (≈0.5× realtime, release build). Receipt digests recorded.
- `ariadne_demo.mus` (*The Thread Remembers the Labyrinth*): 48.2 s, 42 events, 5 voices, peak −2.0 dBFS, RMS −16.02, wall 41.0 s (≈0.85× realtime; the 24-course `ex` instrument dominates). Spectrograms show the bar-8 dimension ladder as four visibly different overtone lattices, clean bend trails, dense-but-bounded extreme passages, and tails that reach true silence.
- A/B listening material prepared (old engine built at `0339aed`): `pluck_demo_OLD/NEW.wav`, `guitar_upgrade_OLD.wav` (shared-param subset) vs `guitar_upgrade.wav`. **Listening verdicts are open — they belong to human ears.**

**CPU/allocation:** ≈0.5×–0.85× realtime for full scores in release on this machine; the per-sample `sin_cos` in body/weave scattering dominates (10 modes × N courses × 2 passes). `next_sample` allocates nothing by construction (all buffers preallocated; verified by code review, not yet by instrumentation). Body-coupling angles are constant per voice — precomputing their sin/cos is the obvious first optimization when a realtime host arrives.

**Parity:** post-parity scores are skipped by name with a printed reason; the 13-score oracle corpus re-ran (report `parity_post_ariadne.json` in the session scratchpad; summarized in the landing commit).

## Claim table audit (MATHEMATICS §14, updated)

| Claim | Status after sprint 1 |
|---|---|
| Givens scattering preserves Euclidean norm | proved algebraically; tested numerically (in-module) |
| State-dependent scattering pointwise norm-preserving | proved; tested (2000-step drift < 2e-11) |
| Ordered overlap ⇒ path-dependent state | closed form verified < 1e-13; **audibly measured at 0.713 rel RMS** |
| Defect = worst-case local displacement | argued (SO(3) equal singular values); Lean formalization backlog |
| Fixed-delay + strict loss ⇒ contractive | standard; quantized Lean skeleton in `formal/` |
| Entire modulated network passive | **not established — and now measurably false as stated**: +66 % transient under bend; narrowed to "scattering lossless; modulated system empirically bounded over tested domain" |
| `dimension` = spectral dimension of realized topology | not established; **but the scaffold is measurably audible as distinct lattices** |
| Ordered scattering = non-Abelian geometric phase | not established; path-ordering language only (E15 closed-loop needs a within-note control-automation API that does not exist yet) |
| Body = measured guitar | false; exploratory 10-mode profile (unchanged) |
| Ariadne musically novel | strengthened: renders exist, path memory measured; still needs listening studies (E10/E11) |

## Remaining P0 gaps

1. **Energy-compensated time-varying retuning** (issue A) — the one measured passivity gap. Round-2 mathematics ask.
2. **Weighted energy metric** (issue B) — body modes are treated as unit-impedance; unchanged from handoff.
3. **E15 closed-loop commutator (A, B, −A, −B)** — requires within-note control automation; currently params are per-event. This is an engine capability, not a DSP change.
4. **Aliasing characterization** (E6/issue G) — not yet measured; extreme presets stay laboratory presets.
5. **Listening studies** (E10/E11, Gate G's blind A/B) — material prepared, ears pending.
6. Body profile struct / measured admittance (issue C); collision-aware or operator-derived dimension (E20/E21).

## Recommendation

**Merge.** The staged design survived contact with the compiler, the invariant suite, the render pipeline, and measurement with one real model fix (dispersion strength) and one honest narrowing (bend-transient boundedness instead of passivity). The instrument is playable, path memory is real and measured, nothing in the parity corpus moved, and every weakened claim is weakened in writing.
