# Work-Accounted Time-Varying Scattering Networks

**Proposed paper/system name:** WATSN  
**Project name:** Ariadne  
**Dependency posture:** standalone audio/DSP; no RDF, KG-ULTRA, or semantic service is required.

## Abstract

Recursive audio models become difficult to reason about as soon as their delays, impedances, couplings, or topology change over time. A fixed scattering junction can be lossless, while the state representation around it silently gains energy when a delay is shortened, a filter coefficient changes, or a resonator is inserted. Existing audio work contains important solutions for particular time-varying waveguides, reactances, allpasses, and stable filter structures, but the current Ariadne implementation demonstrates the remaining architectural problem directly: an upward-fifth bend creates a 66% peak transient even though every explicit Givens scattering operation is orthogonal.

This document specifies **Work-Accounted Time-Varying Scattering Networks**: a graph-compiled class of recursive audio systems with a declared energy metric, lossless local interconnection, contractive loss, explicit state transport between configurations, and a numerical ledger that attributes every energy change to input, dissipation, radiation, or control work. The same system also exposes ordered noncommuting local scattering as a musical state variable.

The research result is not “all modulation must conserve energy.” Physical controls can do work. The result is that the work is represented, bounded, testable, and audible by design rather than arriving as unexplained numerical gain.

---

## 1. Problem statement

A practical physical-modeling system wants all of the following at once:

- fractional and continuously changing delays;
- moving boundaries and tension changes;
- state-dependent nonlinear couplings;
- changing impedance or energy normalization;
- insertion and removal of resonators;
- graph topology edits;
- bidirectional instrument/body/room coupling;
- sparse real-time processing;
- arbitrary automation;
- differentiable parameter fitting;
- deterministic offline rendering;
- a useful, not merely formal, safety contract.

Frozen-parameter stability is insufficient. Even if every instantaneous feedback matrix is orthogonal, an implementation may inject energy through changing state coordinates. Even if every frozen filter is stable, arbitrary products of time-varying state matrices may not be. Smoothing a parameter hides clicks; it does not supply an energy model.

WATSN treats **reconfiguration as an operator on state**. That operator is subject to the same scrutiny as propagation and scattering.

---

## 2. State, configuration, and energy

At sample or block index `n`, let the acoustic configuration be `lambda_n`. It determines:

- a finite state space `H_n = R^(N_n)`;
- a symmetric positive-definite energy metric `M_n`;
- a graph of propagation, scattering, loss, source, pickup, and control ports;
- a compiled processing schedule.

For state `x_n`, define stored energy

`E_n(x_n) = 1/2 x_n^T M_n x_n`.

The metric is not decoration. It records the normalization of traveling-wave ports, modal coordinates, delay cells, and other stored state. Unit Euclidean energy is permitted only when the compiler has explicitly normalized the coordinates.

A no-input step is factored as

`p_n = P_n x_n`  
`q_n = Q_n(p_n, lambda_n) p_n`  
`y_n = D_n q_n`  
`x_(n+1) = T_n y_n`.

Interpretation:

- `P_n` — propagation within the current configuration: delay shifts, fixed allpasses, modal free evolution;
- `Q_n` — local scattering/interconnection, possibly dependent on state and control;
- `D_n` — explicit damping, radiation loss, contact loss, or other contractive processing;
- `T_n : H_n -> H_(n+1)` — state transport from the old configuration to the new one.

This factorization is conceptual. A compiler may fuse operations, but the receipt must preserve their energy meaning.

### 2.1 Fixed-configuration propagation

Require

`P_n^T M_n P_n = M_n`

for a lossless propagation stage.

A circular delay shift is a permutation and is lossless in a uniform metric. A fixed allpass section has internal state and requires the correct augmented metric. A modal rotation with radius one is lossless; radius below one belongs in `D_n`.

### 2.2 Local scattering

Require, pointwise,

`Q_n(z, lambda_n)^T M_n Q_n(z, lambda_n) = M_n`

for every admissible state `z`.

This includes sparse Givens rotations in normalized coordinates and weighted rotations after impedance normalization. State-dependent angles remain pointwise energy-preserving because the matrix applied at that state is metric-orthogonal. This statement is about stored energy, not by itself a complete input/output passivity theorem.

### 2.3 Explicit loss

Require

`D_n^T M_n D_n <= M_n`

in the positive-semidefinite order.

Define dissipated energy

`L_n = 1/2 q_n^T (M_n - D_n^T M_n D_n) q_n >= 0`.

A nonlinear loss can use the direct difference

`L_n = E_n(q_n) - E_n(D_n(q_n))`

and must prove or test nonnegativity over its declared domain.

### 2.4 State transport and control work

The configuration-change work is

`W_ctrl,n = 1/2 y_n^T (T_n^T M_(n+1) T_n - M_n) y_n`.

Therefore, in the unforced case,

`E_(n+1) - E_n = W_ctrl,n - L_n`.

This identity is elementary, but making `T_n` explicit is the architectural move. A delay update, impedance change, topology edit, state resize, or coefficient-state reinterpretation cannot disappear behind a setter.

- `W_ctrl = 0`: energy-neutral state transport.
- `W_ctrl > 0`: the control did positive work on the acoustic state.
- `W_ctrl < 0`: the control extracted energy.
- a balance residual outside tolerance: implementation or accounting defect.

### 2.5 Sources and output ports

The first implementation may treat an excitation as an explicit state injection. If `y` becomes `y + B u`, source work is computed exactly as the energy difference, including the cross term:

`W_in = E(y + B u) - E(y)`.

A pickup that merely reads state is an observation and removes no energy. A physically radiating output must be represented as a port or damping operator whose removed energy appears as `L_rad`. The receipt must distinguish these two cases.

With wave-variable ports, the compiler may instead use incident/reflected power waves and their standard supply rate. With effort/flow ports, it may use `u^T v`. WATSN does not mandate one external port convention in v0; it mandates that the convention and supply rate be declared.

The complete receipt closes

`Delta E = W_in + W_ctrl - L_internal - L_rad - W_out + epsilon_num`.

---

## 3. Constructing energy-neutral state transports

An author usually begins with a desirable raw interpolation or remapping `R`, not an isometry. Examples include:

- resampling a delay line from one length to another;
- remapping wave state after moving a junction;
- copying state into a newly refined graph;
- changing impedance normalization;
- morphing between two modal bases.

Let old and new metrics be `M` and `M'`, and let

`R : R^N -> R^(N')`.

Define the whitened raw map

`A = M'^(1/2) R M^(-1/2)`.

If `N' >= N` and `A` has full column rank, its polar factor

`U = A (A^T A)^(-1/2)`

satisfies `U^T U = I`. The corrected transport

`T = M'^(-1/2) U M^(1/2)`

then satisfies exactly

`T^T M' T = M`.

This construction preserves the directional intention of `R` as closely as its weighted polar factor permits while removing hidden energy scaling.

### 3.1 Equal-dimensional changes

For invertible square `R`, the construction gives a metric isometry. This is the first target for continuous delay and impedance changes.

### 3.2 Expanding state dimension

When new delay cells or resonators are inserted and `N' >= N`, an isometric embedding can preserve all old energy. Newly introduced orthogonal degrees of freedom begin with declared zero state or receive explicit source work.

### 3.3 Shrinking state dimension

When `N' < N`, no map can preserve the energy of every old state injectively. The compiler must choose one of four explicit semantics:

1. **radiate** the discarded subspace through an output port;
2. **dissipate** it and record the loss;
3. **retire** it into hidden tail state that remains until its energy decays;
4. **reject** the topology edit because no policy was declared.

A silent truncation is forbidden.

Using the singular-value decomposition of the whitened map yields a partial isometry and an explicit discarded projector. The energy in that projector is the amount that must be routed or reported.

### 3.4 Prescribed-work transports

Some controls should do work: shortening a real string under tension, striking a boundary, or changing an active wall. A simple first policy is:

1. construct an energy-neutral transport `T0`;
2. apply a declared actuator map whose energy increment is `W_target`;
3. bound the actuator by per-step and cumulative work budgets.

A global scalar rescaling can realize a target energy change but is rarely the most physical distribution. It should be labeled a generic actuator, not a string-mechanics model. Later physical models can distribute work according to boundary velocity, tension, or port forces.

---

## 4. The changing-delay problem

The existing `DelayString` changes integer delay, fractional-allpass coefficient, and dispersion compensation as pitch moves. The delayed state remains in buffers and filter memories whose coordinates were defined by the previous configuration. Orthogonality of later scattering does not repair this reinterpretation.

WATSN offers two implementation families.

### 4.1 Fixed-capacity material coordinates

Represent the traveling wave on a fixed normalized spatial grid. Pitch changes alter the propagation map and metric, not state dimension. A structure-preserving discretization transports the field while recording boundary work.

Advantages:

- stable allocation and plugin suitability;
- topology does not change for ordinary bends;
- straightforward work ledger.

Risks:

- more computation than a short variable delay;
- dispersion and interpolation accuracy require careful design.

### 4.2 Variable-length delay with corrected remapping

Treat a retune event as resampling from old delay state to new delay state. Use a band-limited or high-quality fractional-delay interpolation as raw `R`, then apply the weighted polar correction or an equivalent energy-compensated construction.

Advantages:

- close to existing digital-waveguide implementation;
- efficient when changes are infrequent or block-rate.

Risks:

- polar correction may be too expensive sample by sample;
- shrinking requires a declared discarded-state policy;
- a globally corrected interpolation may alter local phase behavior.

The research should implement both a float64 oracle and at least one real-time approximation.

### 4.3 Required bend modes

Every pitch path must select one of:

- `retune=neutral` — no control work within tolerance;
- `retune=physical(profile=...)` — a mechanics-derived work model;
- `retune=budget(max=...)` — generic bounded control work;
- `retune=legacy` — old behavior, measured and labeled, for comparison only.

The current 3.24-to-5.38 extreme bend is the regression fixture.

---

## 5. Weighted scattering and impedance

Current Givens rotations preserve an unweighted sum of squares. String endpoint samples and body modal momenta are not automatically equal-impedance physical coordinates.

For metric block

`M_pair = diag(m_i, m_j)`,

one safe construction is:

1. normalize `z = M_pair^(1/2) x`;
2. apply a Euclidean Givens rotation `G(theta)`;
3. denormalize.

The physical-coordinate scattering is

`Q = M_pair^(-1/2) G(theta) M_pair^(1/2)`,

which satisfies

`Q^T M_pair Q = M_pair`.

The compiler should factor global scattering into sparse weighted local operations. Dense orthogonal or paraunitary blocks remain possible, but sparse factors make topology, order, telemetry, differentiation, and real-time scheduling explicit.

Measured bridge admittance and radiativity can determine metric and coupling blocks. Designed impossible bodies may use synthetic metrics, but they must declare them.

---

## 6. Ordered scattering memory

Lossless does not mean order-insensitive.

Let `R01(a)` rotate coordinates `(0,1)` and `R12(b)` rotate `(1,2)`. In general,

`R01(a) R12(b) != R12(b) R01(a)`.

The current implementation exposes the norm of this order defect. The next protocol is the closed group commutator

`C(a,b) = R01(a) R12(b) R01(-a) R12(-b)`.

The control path returns to its endpoint. The acoustic state generally does not. At small angles, the Baker–Campbell–Hausdorff expansion gives a leading generator proportional to

`a b [J01, J12]`,

which acts in the remaining `(0,2)` plane, with higher-order error.

### 6.1 Why this belongs in the foundational system

The same operator factorization used for energy safety exposes path order. WATSN can therefore guarantee:

- each factor is metric-orthogonal;
- the closed loop has zero scattering energy change;
- any final difference is attributable to noncommutation, propagation/loss between factors, or declared control work;
- the exact operator product is present in the receipt.

This is much cleaner than comparing two arbitrary presets.

### 6.2 Terminology

Use:

- **order defect** for `AB - BA`;
- **ordered scattering memory** for path-dependent state;
- **closed-loop transport** for the group-commutator experiment;
- **holonomy** only after a closed-path construction and the relevant geometric assumptions are explicit;
- **topological** only when an invariant robust to allowed deformations is demonstrated.

---

## 7. Operator-derived geometry

The current `dimension` control creates course frequencies from a folded power law. It is an audible scaffold, not a spectral dimension.

A field graph should instead define mass/energy and stiffness/coupling operators. For a linearized region, solve the generalized eigenproblem

`K phi_k = omega_k^2 M phi_k`.

Possible graph constructions use a weighted incidence matrix `B`, edge stiffness `W`, and

`K = B^T W B`

with boundary conditions and additional local terms. The realized spectrum and heat/wave traces then support operator-derived descriptors:

- eigenfrequency counting `N(omega)`;
- spectral dimension over a declared scale range;
- localization and participation ratio;
- cycle-sensitive modes;
- modal coupling to excitation and pickup ports.

The compiler may realize the operator with modal banks, waveguide edges, or a hybrid. The graph, not a hand-authored frequency list, is authoritative.

---

## 8. Compiler intermediate representation

Create a pure Rust crate, tentatively `mus-field`, with no semantic-store dependency.

### 8.1 Core objects

- `FieldGraph`
- `StateBlock`
- `EnergyMetric`
- `Port`
- `PropagationStage`
- `ScatteringFactor`
- `LossStage`
- `TransportPlan`
- `ControlField`
- `Pickup`
- `Invariant`
- `WorkLedger`
- `CompileReceipt`
- `RenderReceipt`

### 8.2 Required traits

Conceptually:

```rust
trait Energy {
    fn stored_energy(&self, state: &[f64]) -> f64;
}

trait Stage {
    fn apply(&mut self, state: &mut [f64], control: &ControlFrame);
    fn energy_contract(&self) -> EnergyContract;
}

trait StateTransport {
    fn map(&mut self, old: &[f64], new: &mut [f64]);
    fn control_work(&self, old_metric: &Metric, new_metric: &Metric) -> f64;
}
```

The actual API should avoid dynamic dispatch on the sample path and precompile stage schedules.

### 8.3 Compilation

1. resolve units and stable IDs;
2. construct state blocks and metrics;
3. validate local stage contracts;
4. detect algebraic loops and choose an explicit solve policy;
5. factor scattering into sparse operations;
6. allocate delay and modal state;
7. precompute transport families or block-rate transport plans;
8. compile controls and automation;
9. emit probes and ledger layout;
10. hash the graph, compiler version, and contracts.

### 8.4 Execution classes

- `static`: no configuration changes; cheapest path;
- `parametric`: same state dimension, precompiled metric/transport family;
- `switching`: finite set of precompiled configurations and transitions;
- `structural-offline`: arbitrary graph edits allowed at block boundaries;
- `structural-realtime`: only edits with preallocated state and bounded transition cost.

---

## 9. Work ledger

The ledger is part of the scientific output.

Per sample or block:

```text
energy_start
source_work
control_work
internal_loss
radiation_loss
output_work
energy_end
numeric_residual
```

Optional attribution:

```text
control_work_by_parameter
loss_by_stage
energy_by_state_block
energy_by_graph_region
work_by_topology_edit
```

The default render stores block summaries, extrema, cumulative totals, and selected trace windows rather than every sample.

A valid receipt names:

- energy metric digest;
- graph/configuration digest;
- transport policy;
- numerical precision;
- tolerance;
- maximum absolute and relative closure residual;
- any refused or clipped control operation.

---

## 10. Experiments

### E0 — Reproduce the measured gap

Render the existing extreme patch unbent and with an upward fifth. Preserve the current 3.24 and 5.38 measurements as historical fixtures. Add ledger instrumentation without changing audio.

**Stop condition:** the legacy path's energy increase is localized to specific configuration updates rather than scattering.

### E1 — Static random-network law

Generate thousands of small weighted graphs with random delay permutations, weighted Givens factors, and contractive losses.

**Assertions:**

- lossless stages preserve metric energy;
- losses never increase it;
- ledger closes in float64;
- equivalent factorizations agree within tolerance.

### E2 — Energy-neutral delay sweep

Sweep one string over at least two octaves with `retune=neutral`, including reversals and high modulation rates.

**Stop conditions:**

- cumulative control work is near zero;
- no unexplained peak inflation;
- tuning and spectral error are characterized;
- interpolation artifacts are reported separately from energy closure.

### E3 — Prescribed-work bend

Drive the same pitch paths with a simple physical or budgeted actuator.

**Stop conditions:**

- measured energy change follows declared work;
- positive and negative work paths are distinguishable;
- the same final pitch reached by different paths may have different state only when the work/path model predicts it.

### E4 — Topology expansion and contraction

Insert and remove delay cells, a body mode, and a room node during a sustained sound.

**Stop conditions:**

- expansion preserves old energy and initializes new state explicitly;
- contraction routes discarded energy by the selected policy;
- no state vanishes without a ledger term.

### E5 — Metric/impedance change

Change a port impedance or modal mass while sound is present.

**Stop condition:** neutral and physical policies obey their declared energy equations.

### E6 — Closed scattering loop

Implement `A, B, -A, -B` within one note.

**Stop conditions:**

- controls end exactly where they began;
- all scattering factors are energy-preserving;
- final state displacement agrees with the matrix product;
- small-angle scaling follows `|ab|` over a declared regime;
- a commuting control pair gives the null result.

### E7 — Perceptual path-memory study

Use same-endpoint stimuli matched for level and simple spectral descriptors.

**Tasks:**

- ABX discrimination;
- identify loop orientation or class;
- reproduce a target phrase using path controls;
- rate musical usefulness separately from detectability.

Retain listener-level data and preregister exclusions and primary outcomes.

### E8 — Coupled instrument and room

Build a dense short-delay instrument region and sparse long-delay room region joined bidirectionally.

**Stop conditions:**

- the union obeys one ledger;
- room energy can feed back into the instrument;
- decoupling the bridge recovers the separate limits;
- decay and echo behavior are measured against a fixed reference.

### E9 — Operator-derived spectral geometry

Generate at least three graph families whose measured spectra differ in dimension/localization/cycle structure.

**Stop conditions:**

- the reported descriptor is computed from the operator;
- rendering uses the same operator or a receipt-linked approximation;
- the old folded-power-law control is labeled as a legacy scaffold.

### E10 — Inverse design

Fit graph parameters to targets such as:

- modal lattice;
- bandwise T60;
- echo density;
- pitch drift per cycle;
- path defect;
- maximum control-work budget.

Compare unconstrained fitting, stability-penalized fitting, and WATSN-constrained fitting.

### E11 — Performance

Measure:

- construction time;
- sample and block throughput;
- allocation count;
- state memory;
- transport cost;
- ledger overhead;
- gradient cost where enabled.

### E12 — Adversarial automation

Randomly and deliberately stress every control at maximum rate.

**Stop conditions:**

- unsafe operations are rejected, clipped, or fully accounted;
- no NaNs, infinities, denorm storms, or unbounded state over the declared domain;
- the test corpus and parity oracle remain unchanged for legacy synths.

---

## 11. Numerical gates

Initial targets, subject to revision after the oracle exists:

- float64 local lossless-stage relative energy error: `<= 1e-12`;
- float64 long-run ledger relative residual: `<= 1e-9` over the declared test horizon;
- float32/block implementation residual: empirically bounded and compared to float64, with no unreported positive drift;
- deterministic render and receipt under fixed platform contract;
- no allocation in the steady-state sample path;
- every refused edit reports the failed condition and graph element.

These are engineering gates, not universal mathematical constants.

---

## 12. Relation to prior art

WATSN must cite and distinguish at least:

- Karplus–Strong and extended digital-waveguide strings;
- energy-compensated time-varying waveguides, especially *Virtual Slide Guitar*;
- time-varying wave digital reactances with power metrics;
- energy-preserving time-varying Schroeder allpasses;
- time-varying filter stability via products of state matrices;
- orthogonal, unitary, and paraunitary feedback/scattering delay networks;
- scattering delay networks derived from room geometry;
- passive bridge-admittance/body-radiativity models;
- discrete port-Hamiltonian and structure-preserving integration;
- differentiable FDN optimization and learnable delay networks;
- classical non-Abelian acoustic mode braiding.

The honest distinction is:

> The mathematics of energy and passive interconnection is mature. The proposed new object is an audio-specific graph compiler that applies those principles to arbitrary recursive delay/scattering structures and their reconfiguration, emits an exact control-work ledger, and exposes noncommuting local scattering as a synthesis dimension.

A thorough novelty review is still required before a “first” claim.

---

## 13. Implementation sequence

### P0 — Observe before repairing

Add an explicit approximate energy observer and configuration-change trace to the existing `StringNetworkVoice`. Preserve byte-identical audio. Locate the bend transient stage by stage.

### P1 — Float64 transport oracle

Implement metric matrices, raw interpolation maps, weighted polar correction, and exact ledger tests in a small reference module.

### P2 — Neutral retuning

Replace or supplement the current retune update with one neutral method. Keep `legacy` for A/B and regression.

### P3 — Automation and closed loop

Add within-note control trajectories and the group-commutator experiment.

### P4 — `mus-field` IR

Extract graph, metric, stages, controls, and receipts into a standalone crate. Compile the current guitar and Weave as fixtures rather than rewriting them blindly.

### P5 — Structural edits and coupled room

Add precompiled topology transitions, state retirement/radiation policy, and the one-network demonstration.

### P6 — Optimization and plugin

Only after the laws and reference implementation are stable, add differentiable fitting and real-time host integration.

---

## 14. Failure modes to avoid

- Calling every bounded output passive.
- Computing energy only from output waveform rather than internal state.
- Treating a pickup tap as physical radiation loss.
- Rescaling after the fact without recording control work.
- Hiding discarded state during graph shrinkage.
- Assuming each stable frozen matrix implies stable arbitrary modulation.
- Using a Euclidean norm for coordinates with undeclared impedance.
- Calling order contrast holonomy without a closed path.
- optimizing through a limiter and mistaking the limiter for stability;
- letting an ontology or model proposal bypass the compiler contract.

---

## 15. Minimal publishable result

The smallest strong paper is not the entire vision. It is:

1. a formal discrete energy balance for a class of time-varying delay/scattering networks;
2. a state-transport construction;
3. a float64 oracle and real-time approximation;
4. repair of the measured bend transient;
5. insertion/removal of one resonator with explicit energy routing;
6. a work receipt;
7. comparison to relevant time-varying waveguide/filter methods;
8. open reference code and reproducible audio.

Ordered scattering memory can appear as a motivating application or remain a second paper. RDF and KG-ULTRA should not appear in the foundational evaluation except, at most, as future work.
