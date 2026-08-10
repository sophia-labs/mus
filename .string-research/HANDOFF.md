# Ariadne / Weave — rough-ready implementation handoff

**Instrument name:** Ariadne  
**Synthesis model:** Weave  
**Formal name:** Ariadne String Network  
**Research title:** *Ariadne: A Contractive Holonomy String Network for Physical and Impossible Instrument Synthesis*

This directory is a handoff to the implementation/review agent. It is intentionally complete enough to build from and intentionally rough enough that no one should mistake it for a reviewed, compiled, or publication-ready result.

## Status

The code payload was drafted from `agent/aigua-analysis-foundation` at commit `a2c3a07afc41f89365ca9a1992f88964665ac058` and staged on `agent/weave-string-network` through commit `6bd226f1aa012b2f392816808f81f7c2783f051c`.

The staged implementation is **not installed in the Rust source tree**. It currently exists as:

- `.string-research/payload/chunks/pluck/part-00` through `part-06`: a complete proposed replacement for `mus-rs/crates/mus-dsp/src/pluck.rs`;
- `.string-research/payload/chunks/tests/part-00` through `part-02`: a complete proposed replacement for `mus-rs/crates/mus-dsp/tests/pluck_invariants.rs`.

The payload is 1,181 lines of DSP and 363 lines of invariant tests. It has not been compiled, run, profiled, or auditioned in the integrated engine. Treat every threshold and default as a hypothesis until measured.

Use `bash .string-research/assemble.sh` for a dry run and `bash .string-research/assemble.sh --apply` to install the two generated files. Inspect the diff before compiling.

## What the payload tries to accomplish

### The guitar limit

`synth=pluck` remains the ordinary, physically legible instrument. The proposed replacement deepens it with:

1. a triangular displaced-string initial condition plus content-keyed contact roughness;
2. fractional-delay tuning that compensates the fundamental phase of both damping and dispersion filters;
3. frequency-dependent decay with a requested fundamental T60;
4. stiff-string dispersion;
5. amplitude-dependent onset pitch elevation and relaxation;
6. a ten-mode resonant body coupled *inside* the feedback network;
7. sympathetic standard-guitar open strings;
8. detuned courses, signed strums, physical bends, palm muting, and contractive fret/bridge contact;
9. a stateful block API suitable for a later CLAP/VST wrapper.

This is syntax-compatible with the existing `pluck_note` call site, but it is **not intended to be byte- or timbre-compatible** with the old pluck. The change in sound is the point. Existing non-pluck corpus parity must remain untouched.

### The impossible instrument

`synth=weave` generalizes the guitar into a network of physical and virtual courses. Virtual-course frequencies follow a spectral-dimension scaffold. At every sample, neighboring course states are mixed by an ordered product of real Givens rotations. A travelling coupling field, directional bias, and state-dependent metric make the route through coupling space audible.

The individual scattering operations are pointwise norm-preserving. Adjacent rotations on overlapping coordinate planes do not generally commute, so reversing the order of the same local couplings produces a different state. This is the operative musical idea behind **Ariadne**: the thread remembers how it moved through the labyrinth.

## P0 implementation sequence

Do these in order. A later step must not be used to conceal a failure in an earlier one.

### 1. Assemble and compile the isolated DSP

Install the two staged files, then run:

```bash
cd mus-rs
cargo fmt --all -- --check
cargo check --workspace
cargo test -p mus-dsp --test pluck_invariants -- --nocapture
cargo test -p mus-dsp
```

Expected first outcome: compile or threshold failures. Fix the model or the test method; do not widen tolerances without writing down the measured reason.

### 2. Wire `synth=weave`

In `mus-rs/crates/mus-engine/src/source.rs`:

- import `weave_note` beside `pluck_note`;
- dispatch `synth=weave` to `weave_note`;
- keep `synth=pluck` dispatched to `pluck_note`;
- keep every other synth routed to the existing subtractive engine.

The intended shape is:

```rust
match patch_map.get("synth").map(String::as_str) {
    Some("pluck") => pluck_note(&patch_map, &freqs, slot_s, ratio),
    Some("weave") => weave_note(&patch_map, &freqs, slot_s, ratio),
    _ => synth_note(&Patch::from(&patch_map), &freqs, slot_s, ratio),
}
```

### 3. Extend patch propagation

In `mus-rs/crates/mus-engine/src/pack.rs`, extend `SYNTH_KEYS` with:

```text
stiff tension symp buzz body_size couple chirality orbit orbit_depth curvature courses dimension
```

`detune`, `sus`, `damp`, `pos`, `pick`, `body`, `strum`, and `pm` are already present. Do not create a second parameter path for them.

### 4. Extend the typed vocabulary

In `mus-rs/crates/mus-vocab/src/param_specs.rs`:

- add `weave` to the `synth` enum;
- add typed controls for every new parameter in `.string-research/PARAMETERS.md`;
- describe `weave` as the Ariadne string-network voice, not as an oscillator waveform;
- preserve the vocabulary-as-UI-schema convention;
- update `mus-cli` vocabulary tests with at least one Weave enum check and one check each for a frequency, signed ratio, count, and spectral-dimension control.

### 5. Add scores and render through the real engine

Copy or adapt the research scores into `aigua/` only after dispatch lands:

- `.string-research/scores/guitar_upgrade_demo.mus`;
- `.string-research/scores/ariadne_demo.mus`.

Render WAV, MP3 if desired, spectrogram, receipt, and parameter manifest. Keep the raw WAVs outside Git unless there is an established artifact policy.

### 6. Run the whole repository

At minimum:

```bash
cd mus-rs
cargo fmt --all -- --check
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
```

Then run the existing parity harness. No pre-existing non-pluck result may regress because Ariadne was added.

## P0 scientific and engineering issues

These are not optional polish. They define which claims the implementation may honestly make.

### A. Time-varying delay energy is not covered by the rotation proof

The Givens scattering is pointwise orthogonal. That does **not** prove passivity of a delay line whose effective length or allpass coefficient changes over time. Bends and tension relaxation can inject or remove numerical energy. Before claiming whole-network contraction, either:

1. implement an energy-compensated time-varying waveguide/interpolator;
2. formulate the delay change as a passive state transformation in a declared weighted norm; or
3. narrow the claim to: “the scattering stage is lossless; the full modulated system is empirically bounded under the tested control domain.”

This is the most important mathematical gap in the current draft.

### B. Physical energy is generally weighted

A Euclidean Givens rotation preserves `a²+b²`. A coupled string/body model normally has an energy metric `E=xᵀMx`, where coordinates carry different impedance or modal normalization. Either normalize every state coordinate so Euclidean norm really is energy, or use `M`-orthogonal scattering satisfying `QᵀMQ=M`.

### C. The body model is an exploratory modal body, not a calibrated guitar

The ten modal frequencies and weights are plausible design values, not measurements of an instrument. A production guitar model should derive bridge admittance and radiativity from measured or explicitly designed modal data and preserve passivity of the coupled model.

### D. “Holonomy” is currently algebraic path-order dependence

The implementation genuinely uses noncommuting ordered transformations. It does not yet establish a Berry or Wilczek–Zee geometric phase, a gauge bundle, an adiabatic degenerate subspace, or a topological invariant. Use **holonomy-inspired**, **ordered-scattering holonomy**, or simply **path memory** in product prose until the cyclic protocol and invariant observable in `ARIADNE-MATHEMATICS.md` exist.

### E. Spectral dimension is a scaffold, not yet a graph spectrum

The current rule `f_k ∝ k^(1/d)` comes from inverting a Weyl-like counting law. Octave folding makes it musically playable but destroys literal monotone mode counting and can create collisions. Call `dimension` a spectral-dimension control or scaffold, not a measured dimension of the implemented network. The stronger version generates a graph or fractal operator and uses its eigenfrequencies.

### F. Contact is contractive but radiation is not exact energy bookkeeping

The draft clips/compresses the feedback magnitude and derives a contact output from what was removed. That guarantees a non-expansive feedback contact, but amplitude difference is not automatically equal to removed physical energy. Do not describe the contact signal as exact energy conservation without a power calculation.

### G. Retuning cadence and aliasing need measurement

The delay/filter state currently retunes every 16 samples. Listen and measure for zipper sidebands, especially on fast bends and high notes. The state-dependent coupling, nonlinear contact, and high virtual courses can also alias. Establish an oversampling or band-limiting policy before extreme presets become release presets.

## Acceptance gates

### Gate G — guitar

- deterministic for identical note content;
- in tune to the declared cents tolerance over at least E2–E6;
- `sus` behavior documented and measured by fundamental and bands;
- pick-position nulls audibly and numerically present;
- stiffness increases upper-partial inharmonicity without moving the settled fundamental beyond tolerance;
- onset tension glide is present, decays, and does not explode;
- body and sympathetic strings are inside the coupled dynamics, not post-EQ aliases;
- bends land and remain bounded;
- a blind A/B against the old pluck is preferred by listeners for at least clean single notes, chords, and fingerstyle.

### Gate A — Ariadne

- `weave_note` deterministic for identical content;
- block-size invariant;
- opposite chirality or AB/BA coupling paths produce measurably and audibly different results;
- zero coupling reduces to independent courses plus body coupling;
- zero orbit depth produces a static network;
- zero curvature removes state-dependent metric deformation;
- no NaN, Inf, denormal storm, unbounded tail, or hidden allocation in the audio callback;
- at least one moderate preset sounds like an instrument rather than an effect chain;
- the extreme preset remains controllable and mixable.

### Gate M — mathematical language

- every theorem-like product claim has either a proof, a testable finite-precision contract, or an explicit “conjecture/design hypothesis” label;
- the whole-network passivity claim stays disabled until the variable-delay and weighted-energy issues are resolved;
- the commutator/path-order claim is verified analytically and numerically;
- the Lean model and Rust model state clearly where they correspond and where they do not.

### Gate R — repository

- full Rust workspace tests pass;
- old non-pluck parity report does not regress;
- vocabulary dump covers all controls;
- demo scores parse and render through `mus`, not a private prototype;
- receipts identify `synth=weave` and the parameter set;
- generated audio is reproducible from score plus engine version.

## Review order for the eager implementation agent

1. Read this file.
2. Read `ARIADNE-MATHEMATICS.md`, especially the nonclaims.
3. Read the assembled `pluck.rs` once without editing.
4. Review `DelayString::update_loop`, `scatter_weave`, `scatter_body`, and `next_sample` as the four load-bearing regions.
5. Compile and fix structural defects.
6. Run invariant tests and inspect each failure rather than bulk-adjusting thresholds.
7. Wire engine/vocabulary.
8. Render the two scores.
9. Perform the experiments in `EXPERIMENTS.md`.
10. Only then decide which defaults and public claims survive.

## Definition of a complete first handoff

This packet is complete when it contains the code payload, assembly path, integration seams, parameter contract, mathematical statement and limitations, listening/measurement protocol, reference literature, and demonstrator scores. It is **not** the completed Ariadne instrument. The implementation agent owns the transition from a coherent research prototype to compiled, auditioned software.
