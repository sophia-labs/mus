# RDF, KG-ULTRA, and the Ariadne field compiler

**Status:** architecture for the optional semantic and machine-reasoning layer  
**Dependency rule:** the WATSN DSP kernel and its proofs must run without this layer.

## 1. Purpose

Ariadne's acoustic object is already a graph in the literal engineering sense:

- state blocks and resonators are vertices or vertex-owned state;
- propagation paths and delays are edges;
- junctions are sparse operators over incident ports;
- controls select parameters and operator order;
- pickups and sources are ports;
- analyses, invariants, and listening reports are evidence about graph realizations.

RDF gives the object durable identity, relation types, provenance, queryability, and a place to attach evidence. Sparse linear algebra gives the same object executable acoustic meaning. KG-ULTRA can operate between them as a structural-intuition service.

The intended loop is:

```text
MUS-F / graph operations
  -> authoritative FieldGraph
  -> RDF projection
  -> deterministic tensor/operator lowering
  -> KG-ULTRA structural candidates
  -> candidate graph patches
  -> static law checks + linearized predictions
  -> constrained numeric fitting
  -> render + work receipt + analysis + listening evidence
  -> accept/reject through ordinary graph authority
```

KG-ULTRA never makes an acoustic claim true and never writes accepted topology directly.

---

## 2. Separation of authority

The Garden integration already establishes the correct boundary:

- the host graph owns identity, snapshots, RDF/SPARQL export, accepted writes, and durable intuition records;
- KG-ULTRA owns RDF-to-integer lowering, relation-graph construction, model state, caching, and ranking;
- private tensors and checkpoint state are implementation details;
- only inspectable candidate records become durable Meaningful Objects;
- acceptance goes through the ordinary authoritative graph path.

MUS should preserve that boundary.

### MUS/FieldGraph owns

- score and field operation logs;
- stable IDs and conflict/fork representation;
- canonical projection into `ScoreGraph` and `FieldGraph`;
- units, schemas, and contracts;
- authoritative topology and control paths;
- compilation and safety checks;
- accepted graph mutations;
- render, analysis, work, and listening receipts.

### KG-ULTRA owns

- deterministic lowering of an RDF snapshot to private integer IDs;
- relation-specific graph representation;
- checkpoint/model loading;
- structural ranking and link prediction;
- graph-level and query-conditioned candidate generation;
- private caches.

### The numeric optimizer owns

- fitting continuous parameters under compiler constraints;
- differentiable or derivative-free search;
- objective and constraint traces;
- no authority over graph identity.

### Humans and agents own

- research questions;
- interpretation;
- listening judgments;
- acceptance or rejection;
- attribution.

---

## 3. Canonical object layers

Keep five layers distinct.

### Layer 1 — Authoring operations

MUS-F text, UI edits, or agent actions become explicit operations. Stable identity comes from the operation log, not from a line number or textual alias. Forks remain represented.

### Layer 2 — Authoritative field graph

A pure in-memory `FieldGraph` contains the current graph body, controls, invariants, and selected heads. It is the source for compilation.

### Layer 3 — RDF projection

RDF records identity, typed relations, provenance, compact parameters, contracts, receipts, observations, and claims. Dense arrays remain content-addressed artifacts, following the existing `mus_analysis.rdf` posture.

### Layer 4 — Numeric bundle

A deterministic lowering produces:

- node and relation dictionaries;
- incidence and adjacency matrices;
- energy metric;
- delay and state layouts;
- sparse scattering factor schedule;
- loss blocks;
- transport maps or transport-family IDs;
- source and pickup matrices;
- control Jacobians;
- graph spectral summaries.

This bundle is versioned and digest-addressed. It is not itself the authority.

### Layer 5 — Intuition and evidence projections

KG-ULTRA candidates, optimization results, compile refusals, render receipts, descriptor observations, perceptual reports, and accepted/rejected decisions are projections linked to the source snapshot.

---

## 4. Proposed ontology module

Use a separate namespace, tentatively:

`https://sophia-labs.ai/ontology/mus-field#`

Prefix: `musf:`.

This module extends rather than overloads `mus-score` and `mus-audio`.

### 4.1 Core classes

```text
musf:AcousticField
musf:GraphRegion
musf:StateBlock
musf:DelayState
musf:ModalState
musf:Junction
musf:Port
musf:SourcePort
musf:PickupPort
musf:RadiationPort
musf:PropagationEdge
musf:ScatteringFactor
musf:LossStage
musf:EnergyMetric
musf:MetricBlock
musf:ControlField
musf:ControlPath
musf:OperatorSequence
musf:StateTransport
musf:TransportPolicy
musf:TopologyTransition
musf:Invariant
musf:CompileReceipt
musf:WorkReceipt
musf:RenderRealization
musf:Probe
musf:InverseDesignTask
musf:CandidatePatch
```

### 4.2 Important object properties

```text
musf:hasRegion
musf:hasStateBlock
musf:hasPort
musf:connectsPort
musf:fromPort
musf:toPort
musf:actsOn
musf:usesMetric
musf:hasFactor
musf:precedesFactor
musf:controlledBy
musf:usesTransport
musf:fromConfiguration
musf:toConfiguration
musf:hasInvariant
musf:compiledFrom
musf:realizesGraph
musf:evaluatesSnapshot
musf:proposesPatch
musf:acceptedAs
musf:rejectedBy
musf:supportedBy
musf:contradictedBy
```

### 4.3 Important datatype properties

```text
musf:delaySeconds
musf:impedance
musf:frequencyHz
musf:t60Seconds
musf:factorAngle
musf:sequenceIndex
musf:metricDigest
musf:stateLayoutDigest
musf:contractKind
musf:controlWork
musf:sourceWork
musf:internalLoss
musf:radiationLoss
musf:energyStart
musf:energyEnd
musf:balanceResidual
musf:compileStatus
musf:refusalCode
```

All numeric literals carry units either through typed fields with fixed units or an explicit quantity node. Do not store ambiguous naked numbers.

### 4.4 Order is semantic data

RDF triples are unordered, but Ariadne's operator order is audible. An operator path therefore cannot be represented only as a set of `hasFactor` edges.

Use an `OperatorSequence` whose membership nodes contain stable factor identity and integer/rational sequence index. A canonical RDF list is also possible, but explicit indexed membership is easier to query and patch. The compiler rejects duplicate or missing indices unless a partial-order execution policy is declared.

---

## 5. Deterministic RDF-to-linear-algebra lowering

Let the snapshot contain `N` relevant entities and relation types `r in R`.

### 5.1 Knowledge-graph representation

For each relation `r`, form a sparse relation-specific adjacency matrix

`A_r in R^(N x N)`.

KG-ULTRA may maintain its own private integer graph and relation graph, but the mapping from IRI to integer is deterministic for a snapshot and appears in a digest-addressed manifest.

### 5.2 Acoustic incidence

For acoustic propagation or stiffness edges, form an oriented incidence matrix `B`. An edge `e=(i,j)` contributes a column or row with `+1` and `-1` according to the chosen convention.

A weighted graph operator may be

`K = B^T W B`

or its block/port generalization. Together with the energy/mass metric `M`, this yields the generalized eigenproblem

`K phi = omega^2 M phi`.

### 5.3 Relation to graph patches

A proposed weighted edge has a simple low-rank algebraic effect. For incidence vector `b_e` and weight `w`,

`Delta K = w b_e b_e^T`.

A proposed Givens coupling between state coordinates `i` and `j` inserts a sparse factor generated by `J_ij`. Its derivative with respect to angle is known analytically.

This is the key conversation between KG-ULTRA and the acoustic compiler:

- KG-ULTRA proposes **where and what kind** of relation may be useful;
- linear algebra predicts the first-order or exact local operator change;
- an optimizer determines admissible continuous parameters;
- the compiler enforces energy, work, units, and execution constraints;
- rendering and evidence determine whether the candidate is useful.

### 5.4 Numeric bundle contents

A snapshot lowering should produce a manifest such as:

```json
{
  "snapshot": "urn:...",
  "entity_dictionary": "sha256:...",
  "relation_dictionary": "sha256:...",
  "incidence": "sha256:...",
  "relation_adjacencies": {"couplesTo": "sha256:..."},
  "metric": "sha256:...",
  "stiffness_or_laplacian": "sha256:...",
  "delay_layout": "sha256:...",
  "scattering_schedule": "sha256:...",
  "transport_family": "sha256:...",
  "source_matrix": "sha256:...",
  "pickup_matrix": "sha256:...",
  "compiler_contract": "sha256:..."
}
```

RDF points to these artifacts and records provenance. It does not inline million-element arrays.

---

## 6. Two coupled graphs

Ariadne benefits from representing two related graphs explicitly.

### 6.1 Physical/state graph

This graph answers:

- what stores energy?
- what is connected?
- where does a wave propagate?
- what is the delay, metric, impedance, or loss?
- where are sources and pickups?

### 6.2 Operator/control graph

This graph answers:

- in what order do factors execute?
- which controls change which factors?
- what paths and cycles exist in control space?
- which state transports connect configurations?
- what invariants and work budgets apply?
- what operator sequence produced a render?

The graphs share entities but are not identical. A physical ring may be processed by several operator factorizations. Two factorizations can realize the same frozen matrix but differ under automation, differentiation, telemetry, or finite precision.

KG-ULTRA should be able to query either graph and cross-graph relations.

---

## 7. KG-ULTRA tasks

KG-ULTRA is strongest when asked structural questions, not to hallucinate dense DSP coefficients.

### 7.1 Missing coupling candidates

Given active regions, ports, and target relations, rank plausible `couplesTo`, `radiatesThrough`, `sharesBoundaryWith`, or `feedsBackTo` edges.

### 7.2 Relation typing

Given endpoints, rank the likely operator kind:

- propagation;
- lossless scattering;
- lossy boundary;
- source;
- pickup;
- control;
- evidence;
- analogy.

### 7.3 Motif completion

Recognize and complete known motifs:

- string–bridge–body;
- coupled sympathetic courses;
- FDN/SDN room cells;
- modal radiation banks;
- chiral cycles;
- multiscale dense-core/sparse-halo graphs.

### 7.4 Analogy transfer

Propose a structural adaptation from one graph family to another, such as transferring a passive bridge motif from a measured guitar body into an impossible resonator family while preserving type constraints.

### 7.5 Query-conditioned inverse-design priors

For a task like “increase late echo density without increasing high-band decay” or “make path defect audible while keeping source work fixed,” rank graph edits likely to give the numeric optimizer a useful starting point.

### 7.6 Anomaly detection

Rank suspicious graph shapes:

- an untyped feedback edge;
- a state block with no metric;
- a topology transition with no transport policy;
- an operator sequence missing order;
- a claimed passive realization with positive unexplained work;
- a candidate that duplicates an equivalent motif.

Compiler checks remain authoritative; KG-ULTRA can prioritize review.

---

## 8. Candidate-patch contract

A KG-ULTRA result is a defeasible `CandidatePatch`, not an accepted edit.

A candidate contains:

```text
candidate ID
source snapshot
model/checkpoint
query
proposed add/remove/replace operations
rank and score
structural explanation
expected affected operators
optional analogical precedents
no accepted truth status
```

The candidate then passes through:

1. schema/type/unit validation;
2. stable-identity and fork check;
3. graph well-formedness;
4. metric completeness;
5. static energy-contract validation;
6. transition-policy validation;
7. low-rank/spectral prediction;
8. constrained parameter fit;
9. render and work ledger;
10. analysis and, where relevant, listening review.

Only an accepted result becomes an ordinary graph operation. The intuition record remains as provenance whether accepted or rejected.

---

## 9. Structural proposal plus numeric optimization

Do not ask one model to do both jobs poorly.

### KG-ULTRA proposes discrete structure

Examples:

- add an edge between room nodes 7 and 12;
- insert a body mode between bridge port and radiation port;
- reverse one cycle orientation;
- reuse the `measuredBridge` relation pattern;
- group these delays under a paraunitary coupling block;
- place a transport policy on a topology transition.

### A constrained optimizer fits continuous values

Examples:

- delay length;
- coupling angle;
- impedance;
- T60;
- dispersion coefficient;
- control trajectory;
- actuator-work budget;
- pickup weights.

The optimizer sees analytic derivatives where available:

- `d G_ij(theta) / d theta`;
- rank-one Laplacian edge updates;
- differentiable delay approximations;
- modal eigenvalue sensitivities;
- work-ledger constraints.

This division makes KG-ULTRA useful even when it is not numerically precise.

---

## 10. Round-trip invariants

### 10.1 Identity

Textual names are aliases. Stable IRIs derive from operation IDs, declared IDs, or content-addressed immutable entities.

### 10.2 Canonical projection

The same operation log projects to the same `FieldGraph`, RDF graph, entity dictionary, and numeric bundle digest.

### 10.3 No silent loss

Every MUS-F construct either lowers to RDF and numeric IR, remains an explicitly non-executable annotation, or fails loudly.

### 10.4 Order preservation

Operator and control-path order survives text -> op log -> graph -> RDF -> numeric schedule -> receipt -> text reduction.

### 10.5 Units

Round-trip preserves quantities and units exactly or records a declared normalization.

### 10.6 Evidence separation

Observation, estimate, interpretation, and claim remain distinct. A KG score is never rewritten as a measured acoustic fact.

### 10.7 Candidate separation

Intuition graphs and accepted field graphs use separate projection sinks or graph names.

---

## 11. Example

### 11.1 MUS-F source

```mus
@field thread {
  state s[0..2] : wave(metric=unit)
  factor A : rotate(s0,s1, theta=$a)
  factor B : rotate(s1,s2, theta=$b)
  path commutator = A >> B >> -A >> -B
  pickup out = s0 + s2
  assert energy.scatter == preserve
}
```

### 11.2 RDF shape

```turtle
:thread a musf:AcousticField ;
  musf:hasStateBlock :s0, :s1, :s2 ;
  musf:hasControlPath :commutator ;
  musf:hasInvariant :scatterEnergy .

:A a musf:ScatteringFactor ;
  musf:actsOn :s0, :s1 ;
  musf:controlledBy :a .

:commutator a musf:ControlPath, musf:OperatorSequence ;
  musf:hasSequenceMember :m0, :m1, :m2, :m3 .

:m0 musf:sequenceIndex 0 ; musf:referencesFactor :A ; musf:factorSign 1 .
:m1 musf:sequenceIndex 1 ; musf:referencesFactor :B ; musf:factorSign 1 .
:m2 musf:sequenceIndex 2 ; musf:referencesFactor :A ; musf:factorSign -1 .
:m3 musf:sequenceIndex 3 ; musf:referencesFactor :B ; musf:factorSign -1 .
```

### 11.3 Numeric lowering

```text
M = I_3
Q(path) = G01(a) G12(b) G01(-a) G12(-b)
C = [1, 0, 1]
```

The digest of the ordered factor schedule is part of the render receipt.

### 11.4 Candidate

KG-ULTRA might propose a third factor `G02(c)` or a different factor order based on a target path defect. The compiler can calculate its exact energy contract and local derivatives before any render.

---

## 12. Learning data

Each evaluated graph can contribute a structured record:

```text
source graph snapshot
candidate patch
compile status/refusal
optimized parameters
work-budget result
render digest
acoustic descriptors
path/cycle descriptors
listener outcomes
accepted/rejected status
task context
```

Important safeguards:

- split evaluation by graph family and composition to avoid near-duplicate leakage;
- retain negative and refused candidates;
- distinguish objective target success from listener preference;
- never train on hidden chain-of-thought;
- attribute human reports and preserve cohort effects;
- version the lowering and ontology.

---

## 13. Evaluation

Compare:

1. random legal graph patches;
2. motif/popularity priors;
3. text or embedding similarity;
4. KG-ULTRA structure only;
5. KG-ULTRA plus linearized operator prediction;
6. KG-ULTRA plus constrained optimization.

Metrics:

- legal/compilable candidate rate;
- passivity/work-contract acceptance rate;
- target improvement per render;
- optimization steps to target;
- structural diversity;
- novelty relative to training motifs;
- listener preference or task success;
- explanation/provenance completeness.

The strongest result would be that KG-ULTRA materially reduces expensive renders or optimizer steps while maintaining graph diversity and safety.

---

## 14. Service boundary

A local service can expose:

```text
POST /api/mus-field/snapshots/{id}/lower
GET  /api/mus-field/snapshots/{id}/bundle
POST /api/mus-field/intuition
POST /api/mus-field/candidates/{id}/validate
POST /api/mus-field/candidates/{id}/fit
POST /api/mus-field/candidates/{id}/render
POST /api/mus-field/candidates/{id}/accept
POST /api/mus-field/candidates/{id}/reject
```

`accept` still emits an ordinary authoritative operation after permission checks; it does not grant the model a direct write lane.

---

## 15. What KG-ULTRA adds that ordinary optimization does not

Continuous optimization is good at moving within one chosen architecture. It is usually much worse at proposing discrete, typed, semantically meaningful architectural changes.

KG-ULTRA can provide:

- structural priors across many instrument and room graphs;
- analogical motif transfer;
- relation-aware candidate generation;
- graph-shape anomaly signals;
- a memory of which structural hypotheses worked under which tasks;
- query-conditioned proposals over sparse discrete edits.

Linear algebra then makes those proposals immediately concrete. A single edge is not prose: it becomes a low-rank operator update, a possible scattering factor, a change in cycles, and a set of predicted spectral/work consequences.

That is the deep conversation between the knowledge graph and the acoustic graph.

---

## 16. Dependency firewall

The pure DSP paper must demonstrate all of the following with the semantic layer absent:

- graph construction from Rust fixtures or plain serialized IR;
- deterministic compilation;
- energy/work law;
- changing-delay repair;
- topology transitions;
- ordered scattering memory;
- instrument-room coupling;
- benchmarks.

The semantic paper may import all of those results. The reverse dependency is forbidden.
