# Ariadne implementation consensus

**Authoritative branch:** `agent/ariadne-research-consensus`  
**Constituent research heads:**

- executable transport/retuning work: `agent/ariadne-next-phase` at `abfc5e1474c6d4bdf925060edcb771df8e0fcade`;
- inverse gesture/compiler work: `agent/ariadne-gesture-compiler` at `982cc8af516a6cf9ef905df2ef226e4a017095be`.

**Status:** binding implementation handoff. This document controls implementation order and module boundaries where older handoffs differ. The detailed theorem notes, numerical receipts, and negative results in the constituent branches remain authoritative for their own claims.

---

## 1. Consensus in one sentence

Ariadne needs both halves of the same executable semantics:

> **`mus-gesture` chooses a reachable, costed, certified control path; `mus-watsn` executes the resulting state transports and factors while measuring work, loss, rank effects, and monodromy.**

The two parallel branches are not competing architectures. They meet at the exact seam the paper requires:

```text
authored field + target effect + budgets
    -> inverse gesture compiler
    -> sparse operator / transport schedule
    -> work-accounted executor
    -> audio + immutable receipt
```

The gesture compiler answers *which path should be run*. The work-accounted executor answers *what that path actually did to live acoustic state*.

---

## 2. What each branch contributes

| Concern | Executable retuning branch | Gesture compiler branch | Unified interpretation |
|---|---|---|---|
| Local recursive-stage energy | Exact first-order allpass storage and neutral state transport | Assumes declared energy-normalized coordinates | `mus-watsn` owns stage laws and metric-facing execution |
| Changing delay state | Production-shaped oracle; scalar-neutral remap accepted only as a negative/control result | Does not solve variable-rank delay transport | Still an open transport problem; do not hide it behind gesture synthesis |
| Sparse factor execution | `OperatorProgram` and `PlaneRotation` | Exact graph-restricted schedules | Gesture compiler must lower directly to the existing executor representation |
| Reachability | Local three-mode commutator utilities | Connected-graph `SO(n)` compiler and exact closed `SO(3)` synthesis | Accepted as the normalized, fixed-rank rotation layer |
| Work ledger | Executable block/sample ledger and retuning receipts | Path cost, deformation bounds, effect typing | One receipt schema, with predicted and measured fields kept distinct |
| Optimization | Model-selection experiments for retuning policies | Exact fixed-word timing and finite graph-factorization search | Optimization is allowed only after exact endpoint synthesis |
| Formal core | Work/holonomy path skeleton | Reachability, braid, and passivity-effect skeletons | Lean specifies algebraic laws; Rust/Python conformance tests police implementations |
| Authoring | Existing MUS and proposed field layer | MUS-F inverse gesture syntax | Parser and semantic projection come after the compiler/executor contracts |

---

## 3. Scientific decisions

### 3.1 Accepted for production-facing implementation

1. **Exact neutral first-order allpass transport.** The storage law is exact for the current realization, removes coefficient-update work to binary64 roundoff, and retains high waveform continuity in the production-shaped sweep.
2. **`mus-watsn` as the low-level law and execution crate.** It owns state transports, sparse factor application, work frames, rank policies, and numerical receipts.
3. **Exact tree-QR synthesis as the rotation compiler oracle.** Within a fixed-rank, energy-normalized connected control graph, it emits authored-edge Givens schedules with exact endpoint replay to float64 tolerance.
4. **Exact closed `SO(3)` compilation.** The conjugated balanced commutator plus graph-edge lowering is the reachability backend for the first same-endpoint production experiment.
5. **Constant-thermodynamic-speed timing for a fixed word and constant edge weights.** This is an exact scheduler for that declared cost model, not a perceptual law.
6. **Explicit disposal for rank contraction.** `radiate`, `dissipate`, `retire`, or `reject` is mandatory; silent deletion is ill-typed.
7. **Separate predicted and measured receipts.** A compiler prediction never substitutes for replay in the float64 oracle or production executor.

### 3.2 Retained as research controls, not production truth

1. **State-contingent scalar-normalized delay remapping.** It closes a scalar ledger but fails waveform/state fidelity in difficult cases. It remains a useful negative control and diagnostic.
2. **The three-rectangle nonlinear closed-loop solver.** It may refine cost, but the exact commutator construction carries the reachability claim.
3. **Numerical Lie-rank tests.** They support implementation checks but do not replace theorem hypotheses or establish constrained global controllability.
4. **Thermodynamic friction as an audibility/naturalness metric.** It is an effort/artifact model until listener evidence exists.
5. **Topological precursors.** The Abelian protected pump and non-Abelian geometric bundle remain isolated research fixtures, not production instrument claims.

### 3.3 Rejected claims

- Energy closure alone determines the correct state correspondence.
- Connectivity alone makes every graph-edge coupling physically legitimate.
- Edge-angle sums returning to zero prove a physical actuator with hysteresis has returned internally.
- Orthogonal factor work is zero for the whole render when propagation, loss, metric motion, or actuators are interleaved.
- The quantized Lean effect calculus proves the float DSP passive.
- Non-Abelian transport is automatically topologically protected.

---

## 4. The critical reconciliation

The gesture compiler's exact `SO(n)` results and the retuning branch's unresolved delay-state problem live at different layers.

The exact graph compiler acts **inside one fixed-rank, energy-normalized fiber**. It synthesizes the orthogonal/isometric sector `U`. It does not choose the connection between different delay discretizations, metrics, or topologies, and it does not synthesize the positive deformation `H` unless an actuator model is declared.

Therefore the full state-transition pipeline is:

```text
physical/configuration state x in metric M0
    -> metric frame / declared state correspondence
    -> optional rank transport and disposal policy
    -> positive deformation or actuator work H
    -> normalized rotation schedule U from mus-gesture
    -> propagation, loss, source, radiation
    -> measured receipt in mus-watsn
```

For a static metric and rank, the middle transport may be identity and the gesture compiler can operate directly. For a changing delay, body, room, or topology, the transport policy remains explicit and independently testable.

---

## 5. Module and dependency consensus

### 5.1 `mus-watsn`

Low-level, parser-free, host-free executable law layer.

It owns:

- metrics and normalized state coordinates;
- `PlaneRotation` and `OperatorProgram` execution;
- exact stage storage laws;
- state transport plans;
- work/loss/radiation frames and ledgers;
- rank-changing receipts and disposal policies;
- dense reference hooks behind test/reference features.

It must not depend on MUS parsing, RDF, Garden, KG-ULTRA, or an audio host.

### 5.2 `mus-gesture`

New pure Rust inverse compiler crate. It **depends on `mus-watsn`** and emits `mus_watsn::OperatorProgram`; it must not create a second factor executor or a competing work ledger.

It owns:

- stable `ModeId`, `EdgeId`, and normalized `ControlGraph` IR;
- reachability and connected-component reports;
- exact tree-QR graph compiler;
- exact closed `SO(3)` compiler;
- fixed-word timing and finite factorization search;
- target, cost, and compiler-side receipt structures;
- typed `Unreachable`, `Unsupported`, `SolverFailed`, and `Certified` outcomes.

Dense matrix algebra may be feature-gated or construction-time-only. No dense factorization occurs in the audio callback.

### 5.3 Python reference package

`paper/ariadne-gesture-compiler/reference/ariadne_gesture` remains the independent float64 oracle and test-vector generator. Rust must replay committed or generated fixtures rather than merely sharing code paths.

### 5.4 Lean formal package

The Lean modules remain a specification/proof layer. They do not become runtime dependencies. A future real-valued soundness effort must explicitly connect typed IR, SPD metrics, partial isometries, and numerical intervals to Rust execution.

### 5.5 `mus-field` and MUS-F

The later field IR owns instrument/body/space graph declarations, units, ports, topology, and metric provenance. It lowers a normalized control graph to `mus-gesture` and executable stages to `mus-watsn`.

The inverse gesture syntax in `SPEC-GESTURE.md` is implemented only after the Rust compiler API is stable. RDF projection and KG-ULTRA remain downstream proposal/provenance layers.

---

## 6. Binding implementation sequence

Two tracks may proceed in parallel, but their integration gates are fixed.

```text
Track A: production state law
A0 neutral allpass integration + telemetry
A1 full-network energy/work localization
A2 metric-consistent delay transport oracle
A3 production neutral delay implementation

Track B: inverse gesture compilation
B0 mus-gesture IR + exact tree QR
B1 timing/cost receipts
B2 exact closed SO(3) compiler
B3 within-note automation + production replay

A0 + B0 may proceed together.
B3 requires B2 and host-block-invariant automation.
A3 requires A2 and A1.
The coupled room/topology phase begins only after A1 and B3 are green.
```

### Phase 0 — preserve and instrument

1. Preserve `retune=legacy` byte behavior.
2. Add `retune=neutral_filters` using the exact allpass transport.
3. Make no-op coefficient updates byte-inert.
4. Add observer-only telemetry for delay cells, allpass storage, body modes, contact, scattering, sources, and outputs.
5. Locate the production 3.24-to-5.38 transient internally instead of assigning it to a stage by assumption.

### Phase 1 — exact rotation compiler in Rust

1. Add `mus-gesture` with stable graph IDs and validation.
2. Port exact tree QR from the Python oracle.
3. Emit `mus_watsn::OperatorProgram` directly.
4. Replay Python fixtures and randomized Rust targets.
5. Add exact constant-speed timing and compiler receipts.

### Phase 2 — same-endpoint production experiment

1. Add deterministic, sample-indexed within-note automation.
2. Port exact closed `SO(3)` compilation.
3. Compile a three-state local loop into the actual Weave executor.
4. Provide identity, commuting, inverse-loop, and orientation controls.
5. Render matched-loss and matched-descriptor listening stimuli.

### Phase 3 — delay-state connection

1. Declare metric provenance for delay cells, including spatial-step weighting where appropriate.
2. Build a dense weighted remapping operator and polar/partial-isometry oracle.
3. Compare fixed-capacity material coordinates with variable-rank remapping.
4. Measure energy closure, state/operator error, tuning, sidebands, repeated-cycle drift, CPU, and memory separately.
5. Promote a candidate only if it passes both the work gate and state-fidelity gate.

### Phase 4 — full audited retuning

1. Integrate the selected delay transport behind `retune=neutral`.
2. Retain `legacy` and `neutral_filters` as scientific controls.
3. Close the complete production ledger within declared tolerance.
4. Re-run the extreme bend and identify every positive and negative contribution.

### Phase 5 — instrument, body, and room as one graph

1. Add a bidirectional long-delay halo to the same executor and metric framework.
2. Compile at least one exact gesture spanning string, body, and space modes.
3. Add one insertion and one contraction fixture with all disposal policies.
4. Demonstrate decoupled limits and silence under source removal.

### Phase 6 — mixed polar and protected research

Only after the previous phases:

- signed anisotropic/isotropic actuator compilation;
- mixed `U,H` inverse design;
- bounded deformation-radius optimization;
- topological pump lowering;
- protected non-Abelian fusion attempt;
- perceptual validation of gesture metrics.

---

## 7. Acceptance gates

### Phase 0

- Legacy render parity retained.
- Observer enabled/disabled renders are byte-identical.
- Static `neutral_filters` equals legacy exactly.
- Production allpass coefficient-update work is at numerical tolerance.
- Full-network telemetry sums to final-minus-initial energy within the declared residual.

### Phase 1

- Dimensions 2–32 over path, star, tree, complete, and random connected graphs.
- Every gate is on an authored edge.
- Generic full-target count is `n(n-1)/2`; special targets may be shorter.
- Worst reconstruction error below `1e-11` Frobenius.
- Determinant `-1` and cross-component targets are rejected or explicitly decomposed.
- Python and Rust independently replay the same fixtures.

### Phase 2

- Controls and configuration endpoints close exactly by construction.
- Per-edge schedule closure is exact in the compiled representation.
- Factor-stage work is zero in the declared fixed metric within tolerance.
- Direct dense target, Python lowering, Rust operator replay, and live Weave state agree.
- Commuting controls produce the null result.
- Loop inversion produces inverse monodromy.
- Audio output is host-block invariant.

### Phase 3/4

- Metric and connection policy named in every receipt.
- Dense oracle and real-time approximation compared by operator/state error, not only scalar energy.
- No unexplained positive drift under reversals, rapid modulation, or repeated cycles.
- Pitch and artifact metrics reported separately from energy closure.
- The extreme production bend has an attributable ledger.

### Phase 5

- One ledger spans instrument, body, and room.
- Bridge-zero recovers the separate limits.
- Room state feeds back into instrument state.
- Rank contraction cannot compile without a disposal policy.
- Every accepted edit is replayable from a content-addressed receipt.

---

## 8. Unified claim ledger

| Claim | Consensus status |
|---|---|
| First-order allpass coefficient changes have an exact neutral state map | Established analytically and numerically; production trial next |
| Scalar energy normalization is a sufficient delay connection | Rejected by state-fidelity experiment |
| Connected normalized edge graph generates `SO(n)` | Established/classical boundary; exact project compiler implemented in Python |
| Every `SO(3)` target has an exact closed-control compiled word | Established in the reference oracle; Rust/live-audio port next |
| Fixed-word constant-speed timing minimizes declared quadratic effort | Established for constant per-gate weights and fixed word |
| Connected graph implies physically arbitrary acoustic controllability | Rejected |
| One reversible traceless deformation plus rotations generates `SL(n,R)` | Operator-level theorem under signed reversible assumptions; not yet a production actuator |
| Passivity effect typing prevents unaccounted operations at the IR level | Established in quantized Lean skeleton; Rust soundness not yet proved |
| Existing production bend is work-accounted | Not yet; internal instrumentation remains mandatory |
| Current chirality audio is closed-loop holonomy | Not yet; exact same-endpoint production path remains to be rendered |
| Non-Abelian Ariadne transport is topologically protected | Not established |

---

## 9. Implementation-team rules

1. Do not duplicate `OperatorProgram`, Givens execution, or the work ledger in `mus-gesture`.
2. Do not call a compiler target reachable without listing its metric, rank, graph component, and control hypotheses.
3. Do not treat compiler-predicted zero work as measured whole-render zero work.
4. Do not promote a transport on scalar energy closure alone.
5. Do not begin semantic/RDF integration before exact Rust replay exists.
6. Do not let optimization alter endpoint correctness; every candidate is independently replayed.
7. Do not use the master limiter in energy experiments.
8. Do not use `holonomy`, `geometric`, or `protected` interchangeably.
9. Every negative result is retained as a fixture rather than tuned away.
10. The implementation report must separate theorem, oracle computation, production measurement, and listener evidence.

---

## 10. Start here

Implementation agents should read, in order:

1. this consensus;
2. `.string-research/NEXT-PHASE-REPORT.md`;
3. `paper/ariadne-gesture-compiler/IMPLEMENTATION-HANDOFF.md`;
4. `paper/ariadne-gesture-compiler/EXACT-CLOSED-SO3.md`;
5. `SPEC-GESTURE.md`;
6. `mus-rs/crates/mus-watsn/src/`;
7. `paper/ariadne-gesture-compiler/reference/ariadne_gesture/`;
8. `formal/MusFormal/WorkHolonomy.lean`, `Reachability.lean`, and `PassivityTypes.lean`.

The first implementation return note should cover **Phase 0 and Phase 1 only** unless every acceptance gate for those phases is already green.
