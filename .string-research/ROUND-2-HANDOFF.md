# Round 2 implementation handoff — Ariadne field theory

**Target branch:** `agent/ariadne-field-theory`  
**Starting point:** `agent/weave-string-network` at `554d19e`  
**Primary objective:** establish a standalone audio/DSP contribution before adding the semantic reasoning layer.

## 0. Read first

In order:

1. `.string-research/SPRINT-1-REPORT.md`
2. `.string-research/RETURN-NOTE.md`
3. `.string-research/ACADEMIC-THESIS.md`
4. `.string-research/WORK-ACCOUNTED-NETWORKS.md`
5. `SPEC-FIELD.md`
6. `.string-research/RDF-KG-ULTRA-FIELD-COMPILER.md`
7. `.string-research/ARIADNE-MATHEMATICS.md`
8. `.string-research/LITERATURE.md`

The current implementation is in:

- `mus-rs/crates/mus-dsp/src/pluck.rs`
- `mus-rs/crates/mus-dsp/tests/pluck_invariants.rs`
- `mus-rs/crates/mus-engine/src/source.rs`

The score graph and current RDF posture are in:

- `mus-rs/crates/mus-graph/src/lib.rs`
- `mus_analysis/rdf.py`
- `ontology/mus-score.ttl`
- `ontology/mus-audio.ttl`

---

## 1. Non-negotiable research ordering

Do not begin with KG-ULTRA.

The work order is:

1. exact standalone energy/work model;
2. changing-delay reference construction;
3. same-endpoint ordered-scattering experiment;
4. graph compiler and MUS-F subset;
5. coupled instrument-room realization;
6. operator-derived geometry;
7. RDF projection and KG-ULTRA candidate loop.

A successful round 2 can stop after step 3 and still be scientifically important. A semantic demo without steps 1–3 is not the result.

---

## 2. Preserve the existing evidence

Before changing audio:

### 2.1 Pin the baseline

Record:

- branch and commit;
- compiler and platform;
- existing invariant results;
- `guitar_upgrade_demo.mus` and `ariadne_demo.mus` render digests;
- current extreme unbent peak `3.24`;
- current upward-fifth-bend peak `5.38`;
- current chirality contrast `0.713` relative RMS;
- loudness and centroid matching figures;
- current runtime.

Store a machine-readable baseline under:

```text
.string-research/round-2/baseline.json
```

### 2.2 Add no-observer regression

Any energy/work observer introduced before the audio repair must be a tap.

**Gate:** render with observer disabled and enabled is byte-identical.

### 2.3 Do not widen existing tolerances

A changed threshold needs a measurement, rationale, and explicit review. Preserve `retune=legacy` until the new mode has its own evidence.

---

## 3. Create a pure DSP law crate

Add a workspace crate:

```text
mus-rs/crates/mus-watsn/
```

This crate must not depend on:

- RDF libraries;
- Garden;
- KG-ULTRA;
- the MUS parser;
- network services.

It may depend on a small deterministic linear-algebra library behind a `reference` or dev-only feature. The real-time core should use static/sparse structures and preallocated buffers.

### 3.1 Module layout

```text
src/
  lib.rs
  metric.rs
  stage.rs
  givens.rs
  loss.rs
  transport.rs
  ledger.rs
  ports.rs
  program.rs
  reference.rs        # feature-gated dense oracle
tests/
  static_energy.rs
  transport_energy.rs
  topology_change.rs
  work_ledger.rs
  ordered_path.rs
```

### 3.2 Minimum types

```rust
pub struct DiagonalMetric { ... }
pub struct BlockMetric { ... }
pub enum EnergyContract {
    Isometry,
    Contractive,
    WorkAccounted,
    Unchecked,
}
pub struct WorkFrame { ... }
pub struct WorkLedger { ... }
pub struct SparseRotation { ... }
pub struct WeightedRotation { ... }
pub struct TransportPlan { ... }
pub struct OperatorProgram { ... }
```

Do not design a maximal generic algebra framework. Support the exact first experiments:

- diagonal and small dense block metrics;
- sparse two-coordinate rotations;
- permutation/shift propagation;
- explicit diagonal loss;
- dense reference transport;
- ordered factor programs.

### 3.3 Energy API

Every reference-stage application must be able to report:

```text
energy_before
source_work
control_work
loss
energy_after
residual
```

The API must distinguish:

- an observation-only output;
- an energy-carrying output port;
- a source injection;
- a configuration transport.

### 3.4 Property tests

Use seeded random generation. At minimum:

- Euclidean Givens preserves energy;
- weighted Givens preserves metric energy;
- products of preserving factors preserve energy;
- contractive diagonal loss never increases energy;
- pointwise state-dependent rotation preserves energy;
- work ledger closes for random small graphs;
- commuting disjoint rotations have zero order defect;
- overlapping rotations have the expected nonzero defect.

---

## 4. Build the float64 state-transport oracle

Do not attempt a real-time variable-delay replacement first.

### 4.1 Raw transport

Implement a test-only/reference path taking:

- old metric `M`;
- new metric `M'`;
- raw interpolation/remapping matrix `R`.

Construct the weighted polar correction described in `WORK-ACCOUNTED-NETWORKS.md`.

### 4.2 Rank cases

Test separately:

- square full-rank remap;
- expansion (`N' > N`);
- contraction (`N' < N`);
- near-rank-deficient remap;
- metric changes without dimension changes.

Contraction must return:

- preserved state;
- discarded-state projector or energy;
- selected routing policy.

### 4.3 Required policies

```text
Neutral
Radiate
Dissipate
Retire
Reject
Legacy
```

`Physical` and `Budgeted` may follow once neutral closure works.

### 4.4 Numerical gates

Initial float64 gates:

- local isometry residual `<= 1e-12` relative;
- ledger residual `<= 1e-9` over the test horizon;
- deterministic SVD/polar sign convention or digest-stable canonicalization;
- explicit refusal when rank conditions fail.

### 4.5 Reference artifacts

Write compact JSON/NPZ artifacts for:

- old/new metrics;
- raw map;
- corrected map;
- singular values;
- initial/final state;
- energy terms;
- residual.

Dense arrays are artifacts, not RDF literals.

---

## 5. Changing-delay research spike

Create a research module before altering `DelayString`.

```text
mus-rs/crates/mus-watsn/src/delay_reference.rs
```

Test two strategies.

### Strategy A — fixed-capacity material coordinate

- fixed state dimension;
- variable propagation operator;
- explicit metric if physical length changes;
- no allocation during render.

### Strategy B — variable-length remap

- high-quality raw resampler;
- weighted polar correction;
- explicit shrink policy;
- block-rate and event-rate versions.

Compare:

- tuning;
- amplitude/energy envelope;
- sidebands;
- transient spectrum;
- CPU;
- memory;
- work closure.

Use simple impulse and sinusoidal fixtures before plucked-string audio.

### Required sweeps

- old/new delays from 8 to 1024 samples;
- ratios `1/2`, `2/3`, `1`, `3/2`, `2`;
- slow ramps, abrupt steps, triangular sweeps, random bounded paths;
- repeated up/down cycles;
- float64 and candidate float32/runtime versions.

### Stop condition

Choose one method for integration only after it has:

- an exact reference interpretation;
- characterized audio artifacts;
- a declared control-work policy;
- no unexplained positive drift.

---

## 6. Integrate retuning without deleting legacy behavior

Add a typed retune mode to `PluckPatch`:

```text
legacy
neutral
budget
physical
```

The parameter spelling may initially be `retune=...`.

### 6.1 First integration target

One isolated string:

- no body;
- no sympathetic strings;
- no stiffness;
- no tension transient;
- no buzz;
- no detune.

Repair bends there first.

### 6.2 Then reintroduce stages

In order:

1. damping;
2. fractional tuning;
3. dispersion;
4. tension transient;
5. body coupling;
6. sympathetic strings;
7. contact;
8. full Weave.

At each step, identify the energy metric and state of every internal filter. A changing allpass coefficient is itself time variation; do not account only for the delay buffer and ignore filter memory.

### 6.3 Regression fixture

The old extreme patch remains:

```text
couple=.45
chirality=1
orbit=20Hz
orbit_depth=1
curvature=1
body=1
courses=24
gliss=3/2
```

Expected outcome:

- `legacy` reproduces the historical transient within documented tolerance;
- `neutral` has near-zero cumulative control work and no unexplained 66% peak increase;
- `budget` never exceeds its declared step and total work;
- `physical` accounts for its energy change through a named actuator model.

Do not use the master limiter in these measurements.

---

## 7. Add within-note control automation

The current patch is event-constant. Implement the smallest seam that supports a sample- or block-rate control frame.

### 7.1 DSP boundary

Add a control structure conceptually like:

```rust
pub struct StringNetworkControlFrame {
    pub couple: f64,
    pub chirality: f64,
    pub orbit_hz: f64,
    pub orbit_depth: f64,
    pub curvature: f64,
    pub body: f64,
    pub target_pitch_ratio: f64,
}
```

Avoid cloning maps or parsing strings in `next_sample`.

### 7.2 Automation source

The first implementation may use a precomputed, piecewise-linear lane. It must be:

- deterministic;
- host-block invariant;
- allocation-free on the sample path;
- able to hit exact endpoints;
- receipted.

### 7.3 Null tests

- constant automation equals old constant patch byte-for-byte where feasible;
- a zero-depth lane is inert;
- different host block sizes render identically;
- telemetry remains a tap.

---

## 8. Replace hard-coded Weave order with an operator program

Current `scatter_weave` contains forward and reverse loops directly. Extract an internal sparse program.

### 8.1 Program representation

At minimum:

```rust
pub enum FactorRef {
    RingEdge { index: usize, sign: f64, weight: f64 },
    BodyEdge { string: usize, mode: usize, sign: f64, weight: f64 },
}
pub struct OperatorProgram {
    pub factors: Vec<FactorRef>,
}
```

Construction may allocate; execution may not.

### 8.2 Preserve parity

Compile the current forward/reverse algorithm into a program and prove render identity before adding new paths.

### 8.3 Closed-loop program

Add the exact three-state reference:

```text
A = G01(a)
B = G12(b)
C = A >> B >> -A >> -B
```

Then embed an analogous local loop in Weave.

### 8.4 Tests

- endpoint control values are identical;
- factor energy is exact;
- matrix product and state result agree;
- small-angle defect scales with `|ab|`;
- swapping to disjoint planes gives a null result;
- reversing the loop yields the inverse within tolerance;
- losses disabled for the mathematical fixture;
- matched-loss audio fixtures for perception.

---

## 9. Perceptual experiment package

Add a generator, not ad hoc WAVs.

```text
.string-research/round-2/listening/
  protocol.md
  stimuli.toml
  generate.py or Rust CLI command
  analysis.py
  manifests/
```

Stimulus families:

- closed loop versus identity;
- loop orientation;
- order `AB` versus `BA`;
- commuting null pair;
- level-matched and descriptor-matched controls;
- phrase-level compositional examples.

Every stimulus manifest names:

- graph/program digest;
- controls;
- seed;
- render digest;
- loudness;
- spectral centroid and bandwidth;
- path-defect observable;
- work ledger summary.

Do not tune the primary hypothesis after listening to pilot results. Separate pilot and confirmatory sets.

---

## 10. Introduce the field IR

After the DSP laws exist, add:

```text
mus-rs/crates/mus-field/
```

### 10.1 Dependency direction

`mus-field` may depend on small shared notation/value types but not on the engine UI or semantic services.

Suggested responsibility:

- typed graph declarations;
- stable local IDs;
- units;
- state/port/edge/factor/control/path structures;
- static selectors;
- contracts and probes;
- canonical serialization;
- lowering into `mus-watsn`.

Parsing can live in `mus-text` or a later `mus-field-text`; do not couple the core IR to one surface syntax.

### 10.2 MUS-F v0 subset

Implement only:

- companion `.musf`;
- `field`, `region`, `state`, `factor`, `metric`, `control`, `path`, `pickup`;
- arrays and finite comprehensions;
- units;
- ordered `>>`;
- Givens and weighted Givens;
- static assertions;
- ledger observation;
- score binding.

Use `SPEC-FIELD.md` as the reserved language, not a demand to implement every form now.

### 10.3 Canonical fixtures

Encode:

1. scalar Karplus–Strong;
2. three-state commutator;
3. current Weave ring;
4. current guitar + body;
5. minimal instrument + room.

Each fixture must round-trip text -> IR -> canonical text and compile deterministically.

---

## 11. Couple instrument and room

Do this in `mus-field`/`mus-watsn`, not by adding another post-effect send.

### 11.1 Graph shape

- dense short-delay instrument region;
- sparse 10–300 ms room region;
- weighted bidirectional bridge;
- explicit source and pickup;
- one metric and one ledger.

### 11.2 Limits

Tests must recover:

- instrument alone when bridge angle is zero;
- room alone under direct room excitation;
- current-style post-reverb comparison as a separate non-feedback baseline;
- silence under loss with source removed.

### 11.3 Demonstrations

- ordinary passive room;
- room tuned to a modal target;
- directed/nonreciprocal candidate only if its energy contract is valid;
- per-bounce rotation/echo drift;
- impossible dispersion wall.

Do not call a directed graph passive merely from edge orientation. Supply the operator construction and metric condition.

---

## 12. Replace the spectral-dimension scaffold

Keep `dimension` as a legacy sound control while adding an operator-derived path.

### 12.1 Offline graph operator

Build weighted incidence/stiffness and metric matrices. Solve:

```text
K phi = omega^2 M phi
```

Use a deterministic eigensolver in a research/offline path.

### 12.2 Descriptors

Compute:

- eigenfrequency count;
- heat or wave trace;
- spectral dimension over declared scale windows;
- localization/participation;
- cycle structure;
- excitation and pickup participation.

### 12.3 Rendering

Start with modal-bank realization linked to the graph/operator digest. Later compile selected graph regions to waveguides or hybrid state.

**Gate:** the descriptor and render arise from the same authoritative operator or a declared approximation.

---

## 13. Add RDF only after the field graph is stable

Create:

```text
ontology/mus-field.ttl
mus_analysis/field_rdf.py        # or Rust projector
```

Follow current MUS analysis doctrine:

- dense numeric bundles remain artifacts;
- RDF carries identity, type, provenance, relations, compact results, and evidence;
- deterministic sorted output;
- no silent semantic loss.

Tests:

- field snapshot -> RDF determinism;
- order sequence preserved;
- stable IDs preserved;
- units preserved;
- candidate and accepted graphs separated;
- numeric-bundle digest linked.

---

## 14. KG-ULTRA integration

Reuse the Garden service boundary rather than importing model source.

### 14.1 Initial candidate task

Keep the first task small:

> Given a legal field graph and a target relation whitelist, rank one-edge or one-factor structural patches.

Candidate classes:

- add coupling;
- remove coupling;
- type an untyped relation;
- insert one modal state;
- alter factor order;
- connect instrument region to room region.

### 14.2 Validation pipeline

Every candidate runs:

```text
schema
-> units
-> identity/fork
-> graph well-formedness
-> metric completeness
-> energy contract
-> transition policy
-> low-rank prediction
-> optional fit
-> render
-> receipt
```

### 14.3 Evaluation baselines

- random legal patch;
- motif frequency;
- embedding/text similarity;
- KG-ULTRA;
- KG-ULTRA + linearized operator prediction;
- KG-ULTRA + constrained fit.

Primary engineering metric: useful target improvement per expensive render, not raw link-prediction score alone.

---

## 15. Formal work

Extend `formal/` only after the executable definitions settle.

Priority:

1. weighted Givens metric preservation;
2. product of preserving stages;
3. loss-stage energy inequality;
4. state-transport work identity;
5. polar-corrected transport is metric-isometric under rank hypotheses;
6. closed-loop commutator small-angle term;
7. composition theorem for dense instrument and sparse room regions.

Keep finite-dimensional exact statements separate from claims about a continuous physical string or room.

---

## 16. Commit sequence

Recommended commits:

1. `research: pin round-2 baseline and work-gap fixtures`
2. `watsn: add metric, sparse rotation, loss, and ledger core`
3. `watsn: add reference state transports and rank policies`
4. `research: characterize changing-delay strategies`
5. `dsp: add typed automation frames without audio change`
6. `dsp: compile legacy weave scattering into operator program`
7. `research: add closed-loop ordered-scattering fixtures`
8. `dsp: add neutral retune mode behind explicit parameter`
9. `field: add typed graph IR and canonical fixtures`
10. `field-text: parse MUS-F v0 companion files`
11. `field: compile coupled instrument-room fixture`
12. `research: add operator-derived spectral geometry`
13. `ontology: add mus-field projection`
14. `kg-ultra: add candidate-patch facade and evaluation harness`

Each commit should leave workspace tests and clippy clean.

---

## 17. Global gates

Run at every landing point:

```bash
cargo fmt --check
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
```

Additional gates:

- legacy score parity unchanged;
- deterministic content-keyed renders;
- host-block invariance;
- no steady-state allocation;
- work-ledger closure;
- no unchecked stage in a research-mode feedback cycle;
- documentation claim table updated;
- all generated artifacts carry digests.

---

## 18. Stop conditions for this round

Round 2 is successful when all of the following exist:

### Pure DSP result

- a formal and executable work identity;
- a reference state-transport construction;
- one repaired changing-delay path;
- one explicit topology-change policy;
- exact work receipts;
- a closed same-endpoint scattering loop;
- reproducible objective and audio evidence.

### Language result

- a MUS-F v0 file can declare and compile the three-state loop and current Weave topology;
- operator order and units round-trip;
- a score can bind to a field/path.

### Optional semantic result

- one field snapshot lowers deterministically to RDF and numeric artifacts;
- one KG-ULTRA candidate is validated, rendered, and accepted or rejected through the proper authority path.

Do not hold the pure DSP paper hostage to the optional semantic result.

---

## 19. Expected scientific artifacts

At the end, the repository should be able to generate:

1. `work-balance-static.pdf/svg` — exact stage/ledger diagram;
2. `bend-legacy-v-neutral.wav` and internal energy/work traces;
3. `transport-rank-cases.json`;
4. `commutator-loop-v-identity.wav`;
5. a path-defect scaling plot;
6. listener-study manifest;
7. `ks.musf`, `commutator.musf`, `weave.musf`, `instrument-room.musf`;
8. compile and render receipts;
9. a frozen paper dataset manifest.

Figures and audio must be generated from commands in the repository, not assembled manually.

---

## 20. Final warning

The current code has already taught the central lesson:

- every explicit scattering rotation can be exactly energy-preserving;
- the complete modulated instrument can still gain energy through changing propagation state.

Round 2 succeeds by refusing to let that distinction disappear again—whether the future edit comes from a human, a MUS-F transform, a numerical optimizer, or KG-ULTRA.
