# Implementation handoff — from receipt emitter to gesture compiler

**Target branch:** `agent/ariadne-gesture-compiler`  
**Authority:** this file describes the intended implementation sequence; the production agent may change APIs, algorithms, and module boundaries while preserving the acceptance gates and scientific distinctions.

## 1. Immediate objective

Land one production path:

```text
SO(n) target
+ authored connected factor graph
+ edge friction weights
+ duration
-> exact edge-Givens schedule
-> constant-speed timing
-> Rust execution
-> monodromy / work receipt
```

Do not begin with KG-ULTRA or a general nonlinear optimizer. The exact compiler is the oracle around which later search can safely grow.

## 2. Commit sequence

### Commit A — `mus-gesture` crate and graph IR

Create a pure Rust crate with no parser, RDF, or audio-device dependencies.

Suggested types:

```rust
pub struct ModeId(pub u32);
pub struct EdgeId(pub u32);
pub struct EdgeControl {
    pub id: EdgeId,
    pub left: ModeId,
    pub right: ModeId,
    pub friction: f64,
    pub max_angle_rate: Option<f64>,
}

pub struct ControlGraph {
    pub modes: Vec<ModeId>,
    pub edges: Vec<EdgeControl>,
}

pub struct RotationTarget {
    pub matrix: DMatrix<f64>,
    pub tolerance: f64,
}

pub struct GivensGate {
    pub edge: EdgeId,
    pub theta: f64,
}
```

Validation:

- stable IDs;
- no self-edges;
- finite positive friction;
- target shape and determinant;
- connected-component report;
- declared energy-normalized coordinates.

### Commit B — exact tree-QR compiler

Port `compile_so_on_tree` from the Python oracle.

Required properties:

- reject a disconnected graph for a full `SO(n)` target;
- permit component-wise targets on disconnected graphs;
- use any caller-supplied spanning tree and leaf order;
- emit exactly `n(n-1)/2` gates for a full target;
- every gate resolves to an authored edge;
- reconstruct within tolerance in float64;
- no dense factorization in the audio callback.

Property tests:

- dimensions 2–32;
- path, star, balanced tree, complete graph, random connected graph;
- random Haar `SO(n)` targets;
- determinant `-1` rejection;
- disconnected cross-component target rejection;
- target replay and inverse replay.

### Commit C — thermodynamic scheduler

Implement:

```text
length_k = sqrt(friction(edge_k)) * abs(theta_k)
tau_k = total_duration * length_k / sum(length)
D_min = sum(length)^2 / total_duration
```

Handle zero-angle gates explicitly. Emit per-segment speed and a constant-speed residual.

Then add finite graph search over:

- spanning trees;
- root/leaf orders;
- optionally equivalent target gauges or mode permutations.

The first accepted optimizer can be deterministic beam search. It need not be globally optimal; it must preserve exact endpoint synthesis and report the searched candidate count.

### Commit D — execution and receipts

Compile the gate word into the existing Weave factor executor. The same operation schedule must be executable in:

- the float64 oracle;
- Rust offline renderer;
- telemetry/Observatory;
- eventual plugin block automation.

Receipt fields:

```text
graph digest
target digest
spanning-tree digest
leaf order
gates and angles
segment durations
friction metric digest
thermodynamic length
predicted minimum quadratic cost
actual endpoint operator
endpoint error
work residual
orthogonality residual
compiler version
```

For a pure rotation schedule, control work must be zero in the declared metric within tolerance.

### Commit E — MUS-F inverse surface

Implement the minimum syntax from `SPEC-GESTURE.md`:

```mus
achieve rotation(target=@R) on @field
  over 2s
  using edges(@field)
  minimize thermodynamic_length(metric=@hand)
  require controls.closed
  require work.abs <= 1e-9J
```

The first parser may accept a serialized target matrix or axis-angle target. Do not wait for the full query language.

### Commit F — closed-loop `SO(3)` solver

Port the three-commutator prototype as an explicitly experimental backend:

```text
C(a,b) = A(a) >> B(b) >> A(-a) >> B(-b)
```

Requirements:

- every primitive closes scalar controls symbolically;
- every factor is metric-orthogonal;
- nonlinear solve reports endpoint error and Jacobian singular values;
- multiple deterministic restarts;
- hard angle bounds;
- solver failure is a typed result, not a near-target schedule silently accepted;
- exact replay in Rust and Python.

Do not claim universal three-loop coverage. Add a broad deterministic target corpus and retain failures.

### Commit G — deformation controls and reachable-pair IR

Add:

```rust
pub enum DeformationControl {
    TracelessSymmetric { generator: SymmetricMatrix, signed: bool },
    Isotropic { signed: bool },
    PhysicalActuator { model: ActuatorModelId },
}
```

Static analysis reports the generated Lie-algebra target class:

- rotations only: `SO(component sizes)`;
- rotations + signed traceless anisotropy: candidate `SL(n,R)`;
- plus signed isotropic scale: candidate `GL+(n,R)`.

The report must distinguish theorem hypotheses from numerical Lie-rank evidence. One-sided controls are semigroup controls and must not be labeled fully controllable.

### Commit H — deformation budget and work-order probes

Implement local polar radius

```text
r_k = ||log H_k||_2
R = sum r_k
energy_ratio_bound = [exp(-2R), exp(2R)]
```

Add the exact one-turn/one-stretch statistic:

```text
D = H^2 - U^T H^2 U
max_abs_work = 0.5 * ||D||_2
sphere_rms^2 = tr(D^2) / (2 n (n+2))
```

These become optimizer constraints and Observatory probes.

### Commit I — type/effect checker

Introduce an effect object for every graph operation:

```rust
pub struct AcousticEffect {
    pub before: MetricSpaceDigest,
    pub after: MetricSpaceDigest,
    pub source_work: EnergyInterval,
    pub control_work: EnergyInterval,
    pub internal_loss: EnergyInterval,
    pub radiation: EnergyInterval,
    pub retired_state: Option<StateTailId>,
    pub numerical_tolerance: f64,
}
```

Composition must fail if:

- state/metric interfaces do not match;
- a rank contraction has no disposal policy;
- an energy source lacks a work port;
- an interval cannot close within tolerance.

The Lean `PassivityTypes` module is the quantized model, not generated production code.

### Commit J — topological lab, isolated from production claims

Port two reference models:

1. Rice–Mele Chern pump and FHS invariant;
2. rank-two constant-gap Grassmann bundle and Wilson loops.

Lower one propagator step from each model through the exact edge compiler. Keep this behind an experimental feature and require:

- maintained spectral gap;
- invariant computation;
- perturbation suite;
- work ledger;
- explicit label `geometric` versus `topologically protected`.

## 3. Instrument–body–space integration

The compiler graph must not stop at the body output. Add room halo modes and bidirectional edges to the same `ControlGraph`.

The combined graph supplies:

- short-cycle string coordinates;
- intermediate body modes;
- long-cycle spatial modes;
- bridge, wall, and return couplings;
- friction/effort weights by region;
- controls for body and room dimensions over time.

A connected combined graph is controllable at the normalized rotation level under the theorem, but this does not license physically arbitrary coupling. Impedance metrics, propagation delay, causality, and loss remain separate contracts.

## 4. Acceptance gates

### Exact compiler

- 1,000 random targets through dimension 32.
- Zero gate-count mismatch.
- Worst float64 reconstruction `< 1e-11` Frobenius.
- Every gate on an authored edge.
- Generic schedule count `n(n-1)/2`.

### Cost

- Constant-speed identity closes analytically and numerically.
- Search never worsens the baseline.
- Cost receipt reproduces under independent replay.
- At least one production acoustic gesture shows predicted artifact/effort ordering across three schedules.

### Closed loop

- Controls return exactly by construction.
- Target endpoint `< 1e-8` rad or typed failure.
- Work residual `< declared tolerance`.
- Corpus includes near-identity and near-pi targets.
- Listener stimuli are level and coarse-spectrum controlled.

### Type soundness

- Deliberate silent rank drop rejected.
- Deliberate undeclared gain rejected.
- Radiate/dissipate/retire policies each close a fixture.
- Lean package builds with no `sorry`.

### Topological

- Integer invariant retained under declared gap-preserving perturbations.
- Gap-closing perturbation allowed to change the invariant.
- Non-Abelian Wilson loops pass gauge-invariant observable checks.
- No use of “protected” for the geometric-only bundle.

## 5. Claims the implementation must not make

- that connected-graph Givens universality is new;
- that numerical Lie rank proves constrained global controllability;
- that three commutator loops universally cover `SO(3)`;
- that thermodynamic friction is perceptual smoothness before measurement;
- that endpoint closure bounds pumping without an actuator budget;
- that a braid relation alone is topological protection;
- that the modal room surrogate is a production room;
- that a type index over natural numbers proves the real DSP implementation passive.

## 6. Deliverable report

The implementation agent's return note should contain:

- exact commit range;
- compiler architecture and deviations;
- randomized property-test table;
- target/cost/receipt examples;
- one same-endpoint musical render;
- one coupled instrument–room render;
- rejected malformed programs;
- exact remaining blockers to real-valued Lean soundness and protected non-Abelian transport.
