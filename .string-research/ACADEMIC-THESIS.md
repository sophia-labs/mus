# Ariadne academic thesis

**Status:** research constitution for round 2  
**Branch:** `agent/ariadne-field-theory`  
**Scope:** separate the publishable audio/DSP contribution from the optional semantic and machine-reasoning layer.

## One sentence

**Ariadne is a compiler and synthesis theory for work-accounted, time-varying acoustic graphs whose local scattering can be ordered noncommutatively, so that a network may change geometry, topology, and control path without hiding where energy came from—and so that the path through control space can itself become an audible musical state.**

Karplus–Strong is the one-cycle scalar limit. Digital-waveguide instruments, feedback delay networks, scattering delay networks, modal bodies, and rooms are larger static or specially structured limits. The proposed contribution is not that all of these use delays and scattering. That is established. The proposed contribution is a general audio-rate graph formalism in which:

1. every state coordinate has a declared energy metric;
2. every fixed-configuration propagation and scattering stage is structure-preserving;
3. every loss is explicit;
4. every change of delay, metric, topology, or state dimension is a **state transport** with an exact work term;
5. ordered, overlapping local scattering operators are exposed as a compositional control path, with exact path-contrast observables;
6. the same graph compiler spans string, body, instrument, room, and coupled instrument-in-room;
7. the implementation emits an energy/work receipt beside the audio.

Nothing in points 1–7 requires RDF, KG-ULTRA, an ontology, or an agent. A plain Rust graph or a JSON fixture is enough. The semantic layer is a separate application and acceleration layer.

---

## 1. Three contributions, not one entangled claim

### Contribution A — Work-Accounted Time-Varying Scattering Networks

This is the foundational audio/DSP paper and the load-bearing result.

A **Work-Accounted Time-Varying Scattering Network** (WATSN) is a recursive audio network whose configuration may change sample by sample. Each configuration has a positive energy metric. Static propagation and local scattering are lossless in that metric; damping is contractive; reconfiguration is represented by an explicit map between old and new state spaces. The energy difference caused by that map is the control work.

The practical consequence is stronger than “stable modulation.” It distinguishes four cases that ordinary parameter smoothing tends to conflate:

- a truly energy-neutral geometry change;
- a physical actuator doing positive or negative work on the acoustic state;
- intentional radiation or dissipation caused by removing state;
- an accidental numerical energy injection.

The current upward-fifth bend gives the motivating counterexample: it peaks at 5.38 where the unbent extreme patch peaks at 3.24. That is a measured 66% transient. Today we can only call it empirically bounded. WATSN turns that unexplained transient into either a zero-work transport, a prescribed-work physical model, or a failed invariant.

**Standalone novelty target:** a general, real-time-capable audio network compiler and exact discrete work ledger for changing delays, scattering, impedance metrics, and topology—not merely one energy-compensated string, one time-varying allpass, or one fixed feedback matrix.

The broader mathematics of passivity, port-Hamiltonian systems, structure-preserving discretization, and time-varying systems is prior art. The claim must therefore be made at the audio architecture and compiler level: a practical class of recursive delay/scattering graphs, its sufficient conditions, its state-transport construction, and its demonstrated use across instrument and room models.

### Contribution B — Ordered Scattering Memory

This is a second standalone audio synthesis and perception paper.

Ariadne already applies overlapping Givens rotations in an order controlled by `chirality`, with time- and state-dependent angles. Each rotation preserves instantaneous Euclidean energy, but adjacent rotations do not commute. Two paths ending at the same control values can therefore leave different acoustic state.

What is established now:

- the local order-defect closed form agrees with direct matrix computation to below `1e-13`;
- mirrored chirality produces a relative RMS distance of `0.713`;
- the two renders are within `0.7 dB` in loudness and `1.4%` in spectral centroid;
- the render is deterministic;
- the effect is used compositionally in *Romanza del hilo*.

What is not established yet:

- a closed control loop whose endpoint parameters are exactly identical;
- a gauge- or basis-robust cyclic observable;
- listener identification and musical-use studies;
- a defensible claim of geometric phase rather than ordered operator memory.

The next experiment uses the group commutator

`C(a,b) = R01(a) R12(b) R01(-a) R12(-b)`.

The controls return to their starting point, but `C(a,b)` is generally not the identity. For small angles, the leading displacement is generated by the commutator of the two rotation generators and scales as `ab`. This is the clean same-endpoint test the current implementation lacks.

**Standalone novelty target:** the first systematic treatment of noncommuting, energy-preserving scattering order as a playable synthesis parameter, including exact defect measures, closed-loop protocols, deterministic reference code, and perceptual validation.

Classical non-Abelian acoustic mode braiding is important neighboring work and raises the standard of proof. Ariadne should not claim topological or Berry–Wilczek–Zee transport unless it actually constructs the required transported subspace and invariant. “Ordered scattering memory” is already accurate and strong.

### Contribution C — Semantic acoustic field compilation

This is optional with respect to A and B.

MUS, RDF, and KG-ULTRA can represent the network as a durable, queryable object; lower it to sparse matrices; propose structural hypotheses; and round-trip accepted changes back to authoritative graph operations. That can become a substantial neuro-symbolic inverse-design contribution.

It is not evidence for the DSP result. WATSN must compile and pass its laws from a normal in-memory graph. KG-ULTRA does not certify truth, stability, or musical value. It proposes defeasible structural candidates that the DSP compiler, probes, and listeners may accept or reject.

---

## 2. The actual Karplus–Strong succession

The historical progression should be stated precisely.

### Karplus–Strong

A short excitation recirculates through a scalar delay loop and averaging/loss filter. It is an extraordinarily efficient sound-producing dynamical system.

### Extended Karplus–Strong and digital waveguides

Fractional delay, pick position, dispersion, frequency-dependent loss, tension modulation, nonlinear contact, body admittance, and bidirectional traveling waves make the model tunable and physically interpretable.

### Feedback and scattering delay networks

Many delays are coupled through lossless or contractive matrices and filters, making reverberators and room approximations. Sparse scattering junctions can reflect physical enclosure geometry.

### Ariadne

The network graph itself becomes a time-varying musical object. Its state is transported when the graph changes; the transport has an energy/work meaning; local sparse scattering factors are addressable and orderable; and instrument and room are regions of one compiled acoustic graph.

The strongest historical sentence is therefore not “we made a more complicated Karplus–Strong guitar.” It is:

> Karplus–Strong made a feedback loop into an instrument. Ariadne makes a changing, work-accounted graph of feedback loops into a general acoustic medium.

That is an ambition, not yet a result. The work ledger and closed-loop path experiment are the two facts required to earn it.

---

## 3. Relevant theoretical fields

The project sits at a useful intersection.

### Physical modeling synthesis and digital waveguides

This supplies the efficient traveling-wave interpretation, delay-line physics, termination filters, dispersion, excitation, and instrument-modeling lineage.

### Wave digital filters and network scattering

This supplies port variables, impedance normalization, passive interconnection, local scattering adaptors, nonlinear component models, and time-varying-reactance precedents.

### Feedback/scattering delay networks and artificial reverberation

This supplies orthogonal, unitary, paraunitary, and filter-valued feedback operators; room-derived scattering topology; decay design; and differentiable optimization of delay networks.

### Port-Hamiltonian systems and structure-preserving numerics

This supplies the mature language for storage, interconnection, dissipation, ports, and energy balance. Ariadne should borrow it rather than rediscover it. The audio-specific work is to compile delay/scattering graphs into a sample-rate process with explicit reconfiguration work and usable authoring controls.

### Linear time-varying and switched systems

This supplies stability criteria for products of changing state matrices and warns that stable frozen configurations do not imply stable arbitrary switching.

### Metric graphs, quantum graphs, and spectral graph theory

This supplies operator-derived modes, Laplacians, cycle structure, Weyl-like counting, spectral dimension, and the correct replacement for the current folded power-law `dimension` scaffold.

### Differential geometry, Lie groups, and geometric control

This supplies path-ordered products, commutators, curvature, holonomy, reachable sets, and inverse construction of control loops. It also supplies terminology that must be used conservatively.

### Psychoacoustics and timbre perception

This supplies the experimental discipline needed to distinguish a mathematical state difference from a robust audible and musically useful dimension.

### Differentiable DSP and inverse problems

This supplies parameter fitting and target matching. WATSN adds a constrained architecture in which learned or optimized changes cannot silently violate the declared energy law.

### Programming languages and verified compilation

This supplies typed units, canonical lowering, graph rewrites, effect systems, proof-carrying compilation, property testing, and receipts. The compiler is part of the scientific contribution because it makes the theorem executable on arbitrary authored graphs.

---

## 4. Defensible novelty boundary

### Established ingredients that are not claims

Do not claim novelty for:

- Karplus–Strong or extended Karplus–Strong;
- fractional-delay tuning;
- energy-compensated time-varying digital waveguide strings;
- orthogonal or unitary feedback matrices;
- scattering delay networks;
- passive body admittance fitting;
- time-varying allpass structures;
- graph Laplacians or spectral dimension;
- non-Abelian transport in physical acoustic metamaterials;
- differentiable FDN optimization;
- RDF-to-tensor lowering or link prediction in isolation.

### Plausible first claims, conditional on experiments

The strongest candidate claims are:

1. **A general work-accounted reconfiguration law for recursive audio delay/scattering graphs**, implemented as a compiler and verified across moving delays, metric changes, and graph edits.
2. **A state-transport construction that converts an arbitrary interpolation proposal into a metric-isometric transport when the rank conditions permit, and exposes residual energy through explicit ports when they do not.**
3. **A complete audio-rate work ledger** that decomposes each sample or block into source input, dissipation, radiation, and control work with numerical closure.
4. **Ordered scattering memory as a synthesis primitive**, demonstrated with same-endpoint control loops and listener-level identification.
5. **A single compiled graph that couples instrument and room bidirectionally while preserving the same energy law**, rather than treating reverb as a post-effect.
6. **Constrained inverse design over time-varying acoustic graphs**, where targets may include spectrum, decay, echo drift, path defect, and work budget.

A novelty search may narrow these. The research should be designed so that even if claim 1 has a broader systems-theory analogue, the combination of compiler, audio structures, topology change, real-time execution, and perceptual demonstration remains a publishable contribution.

---

## 5. What changes the world materially

The material contribution is not philosophical vocabulary. It is a new engineering capability.

### Safe automated synthesis architecture search

A model or optimizer can propose delay lengths, couplings, graph motifs, modulation paths, or room structures. The compiler rejects or accounts for unsafe energy behavior before the proposal reaches a loudspeaker. This is a route to generative audio systems whose internal architecture is editable, inspectable, and bounded by construction.

### One substrate for instruments, effects, and spaces

Strings, membranes approximated by modes, bodies, coupled resonators, reverbs, spatial fields, and impossible rooms become graph regions using the same ports and laws. Tools no longer need a hard boundary between “synth” and “effect.”

### Physical exaggeration without numerical superstition

A designer may intentionally create a slide that pumps energy, a wall that extracts it, or a cyclic control that rotates energy among modes. The result can be impossible and still have an exact account of what the controls did.

### Reproducible acoustic objects

A patch is not only a bag of parameters. It is a graph, a configuration path, a compiler version, an energy contract, a render receipt, and a set of probes. Academic claims and commercial presets can point to the same executable object.

### New musical dimensions

Path order, cycle class, topology edits, metric motion, and work budget become compositional variables alongside pitch, rhythm, and timbre. The existing mirrored-chirality composition is the first small example.

---

## 6. Evidence ledger: now versus required

### Established in the current branch

- extended string model with dispersion, calibrated decay, tension transient, body, sympathetic strings, contact, and deterministic excitation;
- sparse pointwise orthogonal Givens scattering;
- state- and time-dependent coupling angles;
- exact local order-defect implementation and numerical verification;
- deterministic audible path contrast;
- distinct but scaffolded spectral lattices;
- a measured time-varying-delay energy transient;
- no allocation in the sample kernel by construction;
- telemetry that is byte-inert with respect to audio;
- corpus scores and a composed use of mirrored traversal order.

### Required for Contribution A

- an explicit energy metric over all delay, mode, and junction state;
- input/output port accounting;
- state transport for changing delay geometry;
- exact work ledger closure;
- topology-add and topology-remove semantics;
- random-graph property tests;
- a reference float64 implementation and bounded float32 error;
- comparison with established energy-compensated waveguide methods;
- instrument-room coupled demonstration;
- performance measurements.

### Required for Contribution B

- within-note sample- or block-rate control automation;
- the `A, B, -A, -B` same-endpoint protocol;
- exact matrix and audio observables for the closed loop;
- matched controls that remove level, spectrum, and simple modulation confounds;
- preregistered discrimination studies;
- a musical-task study, not only odd-one-out identification;
- careful terminology relative to acoustic braiding literature.

### Required for Contribution C

- a canonical field graph and ontology;
- deterministic graph-to-tensor lowering;
- round-trip identity and provenance;
- KG-ULTRA candidate records separated from accepted graph operations;
- static and dynamic validation of every candidate;
- a benchmark of whether structural intuition improves inverse-design search.

---

## 7. Publication architecture

### Paper 1 — Work-Accounted Time-Varying Scattering Networks for Audio

Core theorem, state transport, compiler, delay-bend repair, topology edits, instrument-room union, benchmarks.

Likely venues: IEEE/ACM TASLP, Journal of the Audio Engineering Society, DAFx as an earlier systems paper, or Computer Music Journal for a broader synthesis framing.

### Paper 2 — Ordered Scattering Memory as a Musical Control Dimension

Exact commutator observables, closed-loop protocol, plugin/notation, perception, composition.

Likely venues: Computer Music Journal, New Interfaces for Musical Expression, Sound and Music Computing, DAFx, or a psychoacoustic venue depending on study depth.

### Paper 3 — Neuro-Symbolic Inverse Design of Acoustic Graphs

MUS-F, RDF lowering, KG-ULTRA structural proposals, differentiable fitting, proof/receipt loop.

Likely venues depend on emphasis: ISMIR/ML, semantic web, or audio DSP.

The papers should share code and data but should not require one another's claims.

---

## 8. Naming

Use descriptive names in papers and Ariadne as the project name.

- **WATSN** — Work-Accounted Time-Varying Scattering Network.
- **OSM** — Ordered Scattering Memory.
- **MUS-F** — MUS Field notation and compiler.
- **Ariadne** — the integrated research instrument and reference implementation.

Avoid naming the foundational paper “semantic” anything. Avoid “topological” in the title until there is an invariant that warrants it.

---

## 9. Research constitution

1. The pure DSP system must run without RDF.
2. Every energy claim names its metric and ports.
3. Every topology or metric change emits control work.
4. A bounded render is not automatically passive.
5. A pointwise orthogonal scattering map does not excuse an unexamined delay update.
6. “Holonomy” is reserved for closed-path evidence; ordinary order contrast is called path or ordered scattering memory.
7. `dimension` becomes a property of an operator before it becomes a scientific claim.
8. Objective descriptors choose and explain stimuli; listeners establish perception.
9. KG-ULTRA proposes; the authoritative graph, compiler, probes, and humans dispose.
10. Every impressive render must be reproducible from a score, graph, compiler digest, and receipt.

---

## 10. Bottom line

There is a serious academic program here, but the breakthrough is not yet “we connected more delays.”

The pure audio breakthrough candidate is:

> **A general executable theory of changing recursive acoustic graphs in which energy injected by control is exactly distinguished from loss, radiation, and numerical error, combined with a new path-dependent synthesis dimension created by noncommuting lossless local scattering.**

The semantic graph is then unusually well matched to the system because the DSP object is already literally a graph. It can make design, search, memory, and explanation far more powerful. It is not what makes the acoustics true.
