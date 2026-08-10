# Work and Holonomy in Time-Varying Acoustic Networks

**Status:** integrated paper architecture for Ariadne round 2  
**Supersedes:** the provisional split of WATSN and Ordered Scattering Memory into two foundational papers  
**Keeps separate:** the later RDF / KG-ULTRA / neuro-symbolic inverse-design contribution

## One sentence

**Ariadne treats a modulated recursive acoustic system as a family of metric state spaces over control space, and decomposes every control-induced state transport into an energy-changing part that performs measurable work and an energy-preserving part that can accumulate path-dependent holonomy.**

That is the deeper paper. Work accounting and ordered scattering memory are not merely adjacent contributions. They are the two irreducible aspects of what a control trajectory does to stored acoustic state:

1. it can change the **amount** of stored energy;
2. it can change the **orientation** of that state among modes, delays, bodies, and room paths.

The first is work. The second is transport. When transport factors do not commute, its closed-path residue is holonomy.

---

## 1. Why the previous two-paper split was too shallow

The original split was intellectually clean but mathematically incomplete:

- Work-Accounted Time-Varying Scattering Networks asked whether changing a delay, metric, or topology secretly injects or removes energy.
- Ordered Scattering Memory asked whether changing the order of lossless local couplings leaves a path-dependent acoustic state.

Both questions arise at the same boundary: **the map that carries acoustic state from one control configuration to the next**.

The measured facts already point to both sides of that boundary:

- a time-varying bend changes peak behavior even though each explicit Givens scattering operation is norm-preserving;
- reversing scattering traversal changes the resulting sound while preserving level and coarse spectrum closely enough that the difference is not explained by a trivial gain or EQ change.

The bend asks what the configuration change did to the state's norm. The chirality experiment asks what it did to the state's direction. A complete theory of modulation must answer both at once.

The integrated paper therefore does not contain “Paper 1” and “Paper 2.” It contains:

- **Part I — Metric geometry:** energy, state transport, loss, radiation, and control work.
- **Part II — Connection geometry:** ordered transport, noncommutation, curvature, and closed-loop memory.
- **Part III — Acoustic compilation:** strings, bodies, rooms, and topology changes as one executable graph with both receipts.

---

## 2. The central object: an acoustic state bundle

Let `Lambda` be the admissible control/configuration space. A point `lambda` may specify:

- delay lengths;
- string tension and dispersion;
- impedance or coordinate normalization;
- scattering angles and their order;
- body and room couplings;
- active graph topology;
- source and pickup placement;
- control-dependent loss or radiation.

At each `lambda`, the compiled acoustic network has a state space

`H_lambda = R^(N_lambda)`

with a symmetric positive-definite energy metric

`M_lambda`.

The pair `(H_lambda, M_lambda)` is the acoustic state fiber over `lambda`. The stored energy is

`E_lambda(x) = 1/2 x^T M_lambda x`.

A performance or automation path

`gamma : lambda_0 -> lambda_1 -> ... -> lambda_T`

therefore does not merely update coefficients. It moves a live acoustic state through a family of possibly different metric spaces.

For one step, write

`T_n : H_(lambda_n) -> H_(lambda_(n+1))`

for the state transport associated with the control change. This is the object ordinary parameter setters hide.

Fixed-configuration propagation, scattering, loss, sources, and pickups still exist, but the new theory begins by making `T_n` first-class.

### 2.1 Fixed-configuration dynamics

Within one fiber, an unforced step may be factored as

`p_n = P_n x_n`  
`q_n = Q_n(p_n, lambda_n) p_n`  
`y_n = D_n q_n`.

Require

`P_n^T M_n P_n = M_n`

for lossless propagation,

`Q_n(z)^T M_n Q_n(z) = M_n`

for pointwise lossless scattering, and

`D_n^T M_n D_n <= M_n`

for explicit loss.

The next state is then

`x_(n+1) = T_n y_n`.

The transport cannot be excused by the passivity of `P`, `Q`, or `D`. It receives its own decomposition and receipt.

---

## 3. The work–holonomy decomposition

Let the old and new metrics be `M` and `M'`, and let

`T : H -> H'`

be a full-rank linear state transport. Move into energy-normalized coordinates:

`z = M^(1/2) x`

and define the whitened transport

`A = M'^(1/2) T M^(-1/2)`.

For equal-dimensional invertible transport, the polar decomposition is unique:

`A = U H`

where

`U^T U = I`

and

`H = H^T > 0`.

This is the central decomposition of the paper.

### 3.1 `H`: deformation and work

After transport,

`E'(Tx) = 1/2 z^T H^2 z`.

Therefore the exact control work is

`W_ctrl(x; T) = 1/2 z^T (H^2 - I) z`.

The orthogonal factor `U` cancels from the scalar energy balance. All energy change caused by the transport is carried by the positive factor `H`.

Interpretation:

- `H = I`: energy-neutral transport;
- singular values of `H` above one: amplified state directions;
- singular values below one: contracted state directions;
- `H != I` with zero work for one particular state: a state-contingent cancellation, not a globally neutral map.

This makes “control work” more informative than a global gain compensation. The receipt records which energy directions were stretched or compressed, not only the final scalar difference.

### 3.2 `U`: metric-compatible transport

The factor

`T_iso = M'^(-1/2) U M^(1/2)`

satisfies

`T_iso^T M' T_iso = M`.

It changes the orientation of state while preserving energy exactly. It is the discrete metric-compatible transport between the two fibers.

For a single step, `U` may be musically silent or highly audible depending on the pickup and future dynamics. Across a path, its order matters.

### 3.3 Why this unifies the two previous papers

The previous WATSN state-transport correction retained only the polar isometry `U` in order to remove hidden energy scaling. The previous Ordered Scattering Memory program studied ordered products of orthogonal local factors.

They are literally the two polar factors of the same modulation map:

- WATSN studied the consequences of `H` and the conditions under which it should be replaced by `I` or exposed as actuator work.
- Ordered Scattering Memory studied the path-ordered consequences of `U`.

The holistic contribution is the theory and compiler in which every control operation yields both parts and neither can hide behind the other.

---

## 4. The global energy law

Let explicit loss during the old configuration remove

`L_n = E_n(q_n) - E_n(D_n q_n) >= 0`.

Let source injection contribute exact work `W_in,n`, and physically radiating ports remove `L_rad,n` or deliver `W_out,n` according to the declared port convention.

The transport work is computed from the positive polar factor `H_n` of the whitened `T_n`.

Then the complete discrete balance is

`Delta E_n = W_in,n + W_ctrl,n - L_internal,n - L_rad,n - W_out,n + epsilon_num,n`.

The paper's first implementation theorem is not that every graph is passive. It is:

> If fixed-configuration propagation and scattering satisfy their declared metric identities, explicit losses are contractive, and every configuration change is compiled through a transport with a polar receipt, then every change in stored energy is attributable to a source, loss, radiation port, output port, control deformation, or numerical residual.

That permits three useful operating modes:

- **neutral:** replace `H` with `I` and use only the metric-compatible factor;
- **physical:** derive `H` from a boundary-force or actuator model;
- **budgeted:** admit generic work but enforce per-step and cumulative bounds.

The existing behavior becomes `legacy`: measured, reproducible, and explicitly outside the stronger contract.

---

## 5. Path composition, monodromy, and holonomy

For a control path `gamma`, the total whitened transport is the ordered product

`A[gamma] = A_(T-1) ... A_1 A_0`.

Because

`A_n = U_n H_n`,

one generally has

`A[gamma] != (product U_n)(product H_n)`.

This nonseparability is the paper's deepest consequence. Energy-neutral rotation changes which state directions later deformation acts on. Work and transport are locally distinguishable but globally coupled by order.

### 5.1 Pure metric-compatible paths

If every `H_n = I`, then

`A[gamma] = U[gamma] = U_(T-1) ... U_0`.

For a closed path in control space, `lambda_T = lambda_0`, the resulting operator is a holonomy candidate.

If the local generators commute and the connection is flat over the tested region, closed loops reduce to identity. If they do not commute, a loop can return every control to its starting value while rotating stored acoustic state.

The minimal reference protocol remains

`C(a,b) = R01(a) R12(b) R01(-a) R12(-b)`.

Each factor is energy-preserving. The controls close. The product is generally nonidentity.

### 5.2 Gauge and basis robustness

A change of energy-normalized basis at each configuration transforms the local transport factors. For a closed loop, the holonomy transforms by conjugation.

Therefore robust loop observables include:

- eigenvalues of the loop operator;
- principal rotation angles;
- trace and characteristic polynomial;
- singular values of `U_loop - I`;
- conjugacy class;
- pickup-specific audible displacement when the pickup map is declared.

A raw matrix entry is not a basis-invariant scientific claim.

### 5.3 Continuous-time form

Within a fixed-rank region, write the energy-normalized state equation induced by control motion as

`dot z = G_i(lambda) dot(lambda^i) z`.

Decompose each generator into skew and symmetric parts:

`G_i = Omega_i + Sigma_i`

with

`Omega_i^T = -Omega_i`

and

`Sigma_i^T = Sigma_i`.

Then

`d/dt (1/2 z^T z) = z^T Sigma_i z dot(lambda^i)`.

The skew part performs no instantaneous work. It defines the metric-compatible connection. Its curvature is

`F_ij = partial_i Omega_j - partial_j Omega_i + [Omega_i, Omega_j]`.

The symmetric part is the infinitesimal work/deformation field.

This is the continuous analogue of the polar split. The paper should present the discrete formulation as authoritative for implementation and the continuous formulation as the geometric interpretation.

### 5.4 Terminology discipline

Use:

- **monodromy** for the total state map around a closed control cycle;
- **metric-compatible holonomy** for the closed-loop `U` operator when the connection construction is explicit;
- **ordered scattering memory** for the audible phenomenon in the current system;
- **geometric phase** only when the specific geometric hypotheses and invariant are established;
- **topological** only when robustness to a defined class of deformations is shown.

Ariadne need not claim topological sound in order to make a substantial contribution.

---

## 6. The four kinds of closed control loop

The organizing figure for the paper should be a two-axis diagram:

| | Trivial transport residue | Nontrivial transport residue |
|---|---:|---:|
| **Zero net control work** | neutral null loop | pure holonomy / ordered memory |
| **Nonzero control work** | pure parametric pumping or extraction | mixed work–holonomy loop |

This taxonomy is more powerful than the previous paper split.

### 6.1 Neutral null loop

Controls close, ledgered work is zero, and the final metric-compatible transport is identity. This is the negative control.

### 6.2 Pure holonomy loop

Controls close, every step has `H = I`, total work is zero, but the ordered product of `U` factors is nonidentity.

This is the clean `A, B, -A, -B` experiment.

### 6.3 Pure work loop

Controls close and the final orthogonal polar factor is identity, but the positive factor is nonidentity or the state-contingent work integral is nonzero.

This is a parametric pump or extractor without residual mode rotation.

### 6.4 Mixed work–holonomy loop

Controls close, work is nonzero, and the final transport contains nontrivial rotation.

This is the genuinely new musical object enabled by the unified theory. A loop can pump energy into particular modes while also rotating which modes those are. Reversing the path can change both timbre and work, even though the endpoint patch is identical.

The paper should not claim that geometric pumping itself is new physics. The contribution is to make this decomposition explicit, compiler-enforced, reproducible, and musically addressable in recursive audio networks.

---

## 7. Rank changes and topology edits

A globally fixed-rank vector bundle is insufficient for inserting or removing resonators, splitting a waveguide, changing delay-cell count, or attaching a room halo.

Ariadne should treat configuration space as stratified by state dimension. Within one stratum, the ordinary polar decomposition applies. Across strata, use the rectangular polar decomposition

`A = U H`

where `U` is a partial isometry.

### 7.1 Expanding state

If `N' >= N` and the raw map has full column rank, `U^T U = I`. Existing energy can be embedded isometrically. New orthogonal state begins at zero unless a source or actuator supplies work.

### 7.2 Shrinking state

If `N' < N`, no injective globally energy-preserving map exists. The discarded subspace must be handled explicitly:

- radiate it;
- dissipate it;
- retire it into a decaying hidden tail;
- reject the edit.

The partial-isometry projector identifies the lost directions, and their energy becomes a first-class receipt entry.

### 7.3 Why topology belongs in the main paper

Topology change is not an ornamental extension. It demonstrates that the framework is about changing acoustic geometry rather than one repaired variable delay. A modest insert/remove-resonator experiment is enough for the main text; arbitrary live graph surgery can remain future work.

---

## 8. One paper, three technical layers

### Part I — Energy geometry

1. State fibers and metrics.
2. Fixed-configuration structure preservation.
3. State transport between configurations.
4. Polar decomposition.
5. Exact work ledger.
6. Partial isometries at rank changes.

### Part II — Connection geometry

1. Sparse local metric-compatible factors.
2. Ordered products and commutators.
3. Closed control loops.
4. Gauge-robust observables.
5. Curvature and holonomy in the fixed-rank regime.
6. Mixed work–holonomy monodromy.

### Part III — Compiled acoustic medium

1. String as a short-delay region.
2. Body as a modal region.
3. Room as a long-delay halo.
4. Bidirectional bridge and wall couplings.
5. Control-path compiler.
6. Work, loss, radiation, and holonomy receipts.
7. Perceptual and compositional demonstrations.

The paper's overall claim is earned only when all three layers meet in one implementation.

---

## 9. Proposed title and abstract

### Working title

**Ariadne: Work and Holonomy in Time-Varying Acoustic Networks**

Alternative, more descriptive title:

**A Metric-Geometric Compiler for Work and Path Memory in Recursive Audio Networks**

### Draft abstract

Recursive acoustic models are usually analyzed at fixed parameters even when practical instruments and reverberators continuously modify delays, impedances, couplings, and topology. Such modulation can inject unexplained energy, while noncommuting lossless couplings can retain a memory of the path through control space. We introduce a metric-geometric formulation of time-varying recursive acoustic networks. Each control configuration defines a finite-dimensional acoustic state space with a declared energy metric, and every configuration change is represented by an explicit state transport. In energy-normalized coordinates, the transport admits a polar decomposition into an orthogonal factor and a positive factor. The positive factor determines exact state-dependent control work; the orthogonal factor is metric-compatible transport whose ordered closed-loop product can exhibit holonomy. This yields a discrete energy identity that separates source input, loss, radiation, output power, control work, and numerical residual while also exposing path-dependent state rotation. We implement the formulation as a sparse graph compiler and evaluate it on continuously retuned strings, noncommuting three-mode scattering loops, mixed work–holonomy cycles, topology edits, and a bidirectionally coupled instrument–room network. Listening studies test whether zero-work closed-loop transport and mixed cycles form identifiable and musically usable control dimensions. The result is a general modulation semantics for recursive audio systems in which control paths are executable acoustic objects rather than coefficient histories.

---

## 10. Core mathematical results to pursue

The paper should aim for four formal results.

### Result 1 — Discrete work identity

For the declared factorization of propagation, scattering, loss, ports, and transport, prove exact balance in real arithmetic and bound floating-point residual in the implementation.

### Result 2 — Local work–transport decomposition

For full-rank transport between metric spaces, state the weighted polar decomposition and show:

- uniqueness in the invertible equal-rank case;
- all transport-induced energy change is determined by the positive factor;
- the orthogonal factor is a metric isometry;
- the closest neutral transport to a raw proposal is its weighted polar isometry under the selected norm.

The linear algebra is established mathematics. The contribution is its role as a compile-time and render-time semantics for arbitrary authored acoustic graph changes.

### Result 3 — Closed-loop transport and gauge invariants

Define the fixed-rank connection induced by neutral transports, derive its path-ordered loop operator, and specify basis-robust observables. Prove the small-angle commutator law for the reference three-mode system.

### Result 4 — Rank-changing energy partition

Use rectangular polar/SVD structure to identify retained and discarded state subspaces and prove closure when discarded energy is routed through the declared radiation, dissipation, retirement, or rejection policy.

---

## 11. Experimental program

### E0 — Preserve the current baseline

Freeze the existing implementation, audio fixtures, and measurements:

- tuning across E2–E6;
- T60 behavior;
- dispersion behavior;
- path-contrast render pair;
- 3.24 unbent versus 5.38 upward-fifth peak;
- deterministic and block-invariant rendering;
- byte-inert telemetry.

No stronger implementation may erase the counterexample that motivated it.

### E1 — Neutral variable-delay transport

Implement a float64 oracle and a real-time approximation for `retune=neutral`.

Sweep:

- fundamentals across the guitar range;
- upward and downward intervals;
- bend duration and curvature;
- damping and dispersion;
- sample rate;
- host block size.

Measure:

- ledger residual;
- peak stored energy relative to unbent control;
- pitch landing error;
- spectral and transient difference from legacy;
- CPU and allocation behavior.

The target is not merely lower output peak. It is zero transport work within declared tolerance.

### E2 — Pure zero-work holonomy

Use a three-state normalized system with two overlapping rotations.

Protocol:

`A(a) >> B(b) >> A(-a) >> B(-b)`.

Required findings:

- every local factor has `H = I`;
- cumulative work is zero within tolerance;
- the loop operator is nonidentity when `a*b != 0`;
- the leading small-angle effect scales as `a*b`;
- the effect vanishes for commuting/disjoint factors;
- exact matrix, internal-state, and rendered-audio observables agree.

### E3 — Pure work loop

Construct a closed control cycle whose total orthogonal residue is identity but whose positive deformation is nontrivial.

This can begin as a synthetic two- or three-state metric squeeze rather than a physical instrument. It supplies the second axis of the taxonomy and verifies that endpoint equality does not imply zero actuator work.

### E4 — Mixed work–holonomy commutator

Interleave a metric-compatible rotation with an anisotropic positive deformation, for example a controlled sequence built from

`U(a)`, `H(s)`, `U(-a)`, and `H(-s)`.

The exact sequence should be chosen so the control parameters close and the null cases are simple.

Measure:

- total monodromy;
- polar factors of the loop;
- cumulative state-dependent work;
- path reversal;
- dependence on initial state orientation;
- audible consequences under matched final level.

This is the experiment that proves the two previous contributions are one theory rather than two features.

### E5 — Compile current Weave into the formalism

Replace hard-coded traversal with an explicit factor schedule.

For every render, emit:

- local factor IDs and angles;
- local polar contracts;
- cumulative work;
- loop/segment monodromy where requested;
- basis-robust path observables;
- pickup-specific path contrast.

Reproduce the current mirrored-chirality result, then construct a genuinely same-endpoint score-level control loop.

### E6 — Instrument and room as one network

Compile:

- a dense short-delay string/body cluster;
- a sparse 10–300 ms room halo;
- bidirectional bridge/room couplings;
- explicit radiation pickups.

Compare:

1. instrument plus post-effect reverb;
2. one-way instrument-to-room graph;
3. bidirectionally coupled instrument–room graph;
4. neutral versus budgeted room modulation;
5. flat versus noncommuting room-cycle transport.

The same energy and path semantics must cover every case.

### E7 — Topology edit

Insert and remove one resonator during a sustained state. Exercise all four shrinking policies:

- radiate;
- dissipate;
- retire;
- reject.

Verify exact energy partition and artifact-free state continuity under the admissible policies.

### E8 — Perceptual and musical validation

Run two studies.

**Discrimination study**

- preregistered same-endpoint zero-work loop stimuli;
- loudness and coarse-spectrum matching;
- commuting nulls;
- listener-level results, not only pooled accuracy.

**Control-use study**

- participants manipulate loop area/order to reach a timbral or spatial target;
- compare holonomy control with conventional macro controls;
- test repeatability and learnability;
- collect descriptions without treating language as direct acoustic ground truth.

A mathematical state difference becomes a musical contribution only when listeners can detect or use it under controls that remove obvious confounds.

---

## 12. The unifying demonstration

The paper needs one complete artifact rather than a gallery of disconnected tests.

A proposed piece or interactive study should contain one sustained excitation traveling through:

1. a physical-string limit;
2. a neutral retuning gesture;
3. a zero-work closed scattering loop that rotates state among virtual courses;
4. a prescribed-work metric gesture that pumps selected directions;
5. a bidirectionally coupled room halo whose cycle order changes the late field;
6. a topology edit that releases or retires one resonator;
7. a return to the original endpoint patch.

The render should expose synchronized views of:

- stored energy by region;
- source, loss, radiation, and control-work ledger;
- singular values of local deformation factors;
- loop holonomy angles;
- active graph topology;
- audible output.

The scientific claim and the musical experience then point to the same object: **the path through acoustic geometry**.

---

## 13. Compiler consequences

The pure Rust implementation should revolve around one new core rather than separate “safety” and “holonomy” subsystems.

Suggested objects:

- `MetricStateSpace`
- `Configuration`
- `StateTransport`
- `WhitenedTransport`
- `PolarTransport { isometry, deformation }`
- `PartialIsometry`
- `ConnectionFactor`
- `ControlPath`
- `MonodromyReceipt`
- `WorkReceipt`
- `HolonomyReceipt`
- `LossPort`
- `RadiationPort`
- `TopologyTransition`
- `CompiledAcousticGraph`

The sample path should not perform arbitrary dense decompositions. The compiler may:

- precompute transport families;
- factor isometries into sparse Givens or Householder operations;
- approximate positive factors with bounded diagonal or low-rank structures;
- run expensive decomposition only at control-block or topology-edit boundaries;
- retain a float64 dense oracle for verification.

Every compiled control operation should carry a contract:

```text
configuration before / after
old and new metric digests
raw transport digest
isometric factor digest
positive factor or actuator model
predicted work bounds
rank-change policy
numerical tolerance
```

The audio receipt accumulates those local contracts into path-level work and monodromy.

---

## 14. Relationship to prior art

The paper must explicitly acknowledge that its mathematical ingredients are not individually new:

- polar decomposition separates orthogonal and positive parts of a linear map;
- port-Hamiltonian systems describe storage, interconnection, dissipation, and supplied work;
- moving-boundary port-Hamiltonian work treats boundary motion as a power port;
- energy-compensated time-varying digital waveguides already exist;
- energy-preserving time-varying allpass structures already exist;
- orthogonal and paraunitary scattering/feedback networks are established;
- geometric phase and non-Abelian acoustic mode braiding are established in physical wave systems;
- parametric pumping and Floquet monodromy are established phenomena.

The candidate contribution is the synthesis:

> a general, executable audio-graph formalism in which arbitrary recursive acoustic reconfiguration is compiled into metric state transport, locally decomposed into work and metric-compatible motion, globally composed into energy and monodromy receipts, and exposed as a reproducible musical control path across instruments and rooms.

A novelty search may narrow the claim further. The experiments should remain valuable under that narrowing.

---

## 15. Claims to avoid

Do not claim:

- that polar decomposition is new;
- that moving boundaries doing work is new;
- that all time-varying audio filters are unstable;
- that every zero-work closed loop is a geometric phase;
- that noncommutation alone is topological;
- that output-level normalization proves internal passivity;
- that a bounded render proves zero control work;
- that a nonidentity matrix is perceptually meaningful without listening evidence;
- that the semantic layer proves the DSP theory.

---

## 16. Publication architecture after this revision

### Main foundational paper

**Ariadne: Work and Holonomy in Time-Varying Acoustic Networks**

This paper contains the former contributions A and B as Parts I and II of one theory. It should be aimed at a full journal treatment, with a DAFx or similar systems paper as a possible preliminary publication rather than as a permanently separate conceptual contribution.

### Later companion paper

**Neuro-Symbolic Inverse Design of Acoustic Graphs**

MUS-F, RDF lowering, KG-ULTRA structural proposals, constrained fitting, and the proof/receipt loop remain a separate paper. They use the work–holonomy compiler as an oracle and safety boundary. They are not necessary for the foundational paper.

### Optional later perception/composition paper

If the listener and musical-task work grows beyond what fits in the journal article, a later paper may focus on composition and interaction. It should be presented as empirical elaboration of the same control theory, not as the missing second half of the foundational claim.

---

## 17. Revised research constitution

1. A control path is a first-class acoustic object.
2. Every configuration has a declared state space and energy metric.
3. Every configuration change has an explicit state transport.
4. Every full-rank transport is examined through its weighted polar factors.
5. Positive deformation is booked as state-dependent control work.
6. Metric-compatible transport is composed in order and may retain closed-path memory.
7. Loss, radiation, source work, and control work remain distinct ledger entries.
8. A bounded render is not automatically passive or neutral.
9. Holonomy claims require a closed path and basis-robust observable.
10. Topology changes require partial-isometry and discarded-energy semantics.
11. Objective state differences do not substitute for perceptual evidence.
12. RDF and KG-ULTRA remain optional design layers, never proof of the audio claim.
13. Every major result must be reproducible from graph, path, compiler digest, state/metric contract, and receipt.

---

## 18. Bottom line

The deeper contribution is not “safe modulation” plus “a strange noncommutative timbre control.”

It is:

> **A theory of acoustic control paths in which the same state transport explains both how modulation performs work and how it leaves path-dependent memory.**

In the simplest one-dimensional feedback loop, the geometry is nearly trivial and modulation is mostly a work problem. In a multi-mode scattering graph, the metric-compatible part becomes non-Abelian and the path itself can rotate sound. In a coupled instrument–room network, both effects coexist across timescales. In a topology-changing graph, the same theory determines what happens to state that no longer has somewhere to live.

Karplus–Strong made a loop sound. Ariadne's stronger claim is that a changing network of loops has a geometry—and that geometry can be measured, compiled, traversed, and played.
