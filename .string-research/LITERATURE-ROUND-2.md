# Round 2 literature supplement — time variation, work, graphs, and inverse design

**Status:** targeted map for the standalone WATSN and ordered-scattering claims.  
**Warning:** this is not a patent search or exhaustive novelty opinion.

## 1. Current survey anchor

### Tablas de Paula, Smith, Välimäki & Reiss (2026)

**“Four Decades of Digital Waveguides.”** arXiv `2604.12878`.

This current survey is the first source to use when positioning Ariadne historically. It covers the digital-waveguide lineage across musical instruments, vocal models, effects, reverberation, and modern optimization, including machine-learning and differentiable approaches.

**Implication:** “a graph of delays” and “optimize a digital waveguide” are not novelty claims. Ariadne must distinguish its work-accounted reconfiguration and ordered control paths.

---

## 2. Time-varying waveguides and filters

### Pakarinen, Puputti & Välimäki (2008)

**“Virtual Slide Guitar.”** *Computer Music Journal* 32(3), 42–54. DOI `10.1162/comj.2008.32.3.42`.

Uses an energy-compensated time-varying digital waveguide for a playable slide guitar and models slide contact.

**Establishes:** energy compensation for an important moving-delay instrument case.

**Does not by itself establish:** a general graph-wide transport and work ledger for arbitrary state metrics, topology edits, or ordered scattering programs.

### Bogason & Werner (2018)

**“Modeling Time-Varying Reactances using Wave Digital Filters.”** DAFx-2018.

Extends wave-digital modeling to time-varying reactive components, derives a power metric, discretizes generalized models, and validates time-varying resistance/capacitance cases.

**Establishes:** time variation must be modeled in the component power law; ordinary time-invariant WDF assumptions are not enough.

**Ariadne use:** direct conceptual precedent for treating a delay or metric update as a work-bearing component rather than a setter.

### Werner (2020)

**“Energy-Preserving Time-Varying Schroeder Allpass Filters.”** DAFx-2020.

Constructs Schroeder-style allpass structures that preserve energy under arbitrary continuous gain variation.

**Establishes:** particular recursive audio structures can be designed to retain exact energy behavior under modulation.

**Ariadne distinction:** WATSN seeks a compiler-level composition and state-transport law across heterogeneous graph stages and topology changes.

### Werner & McClellan (2022)

**“Time-Varying Filter Stability and State Matrix Products.”** DAFx-2022.

Provides a sufficient stability criterion based on products of state matrices over multiple time steps, extending one-step frozen-matrix reasoning.

**Establishes:** stability of each instantaneous configuration is not the whole time-varying problem.

**Ariadne use:** adversarial automation must be studied as operator products, not only parameter bounds.

### Wishnick (2014)

**“Time-Varying Filters for Musical Applications.”** DAFx-2014.

Studies stable, artifact-aware filter structures for sample-rate musical control and presents a time-varying state-variable-filter argument.

**Ariadne use:** perceptual artifact quality and stability are separate requirements.

---

## 3. Port-Hamiltonian and structure-preserving systems

### Celledoni & Høiseth (2017)

**“Energy-Preserving and Passivity-Consistent Numerical Discretization of Port-Hamiltonian Systems.”** arXiv `1706.08621`.

Develops discrete-gradient and splitting methods yielding discrete port-Hamiltonian systems with a discrete passivity property.

### Mehrmann & Morandin (2019)

**“Structure-preserving discretization for port-Hamiltonian descriptor systems.”** arXiv `1903.10451`.

Extends port-Hamiltonian descriptor modeling, emphasizes explicit input/dissipation and modularity, and studies structure-preserving time discretization.

### Delvenne & Sandberg (2013)

**“Finite-time thermodynamics of port-Hamiltonian systems.”** arXiv `1308.1213`.

Treats a class of time-varying port-Hamiltonian systems that can modify internal structure and environmental interconnection while retaining thermodynamic work/energy reasoning.

### van der Schaft & Jeltsema (2021)

**“On Energy Conversion in Port-Hamiltonian Systems.”** arXiv `2103.09116`.

Studies energy conversion between ports and the role of internal interconnection topology.

**Collective implication:** energy storage, dissipation, ports, time variation, and changing interconnection have mature systems-theory languages. WATSN should import this discipline.

**Defensible audio claim:** not invention of work accounting in dynamical systems, but an executable sample-rate architecture for recursive delay/scattering audio graphs, including practical state transport, topology edits, sparse compilation, receipts, and perceptual applications.

---

## 4. Feedback and scattering delay networks

### Rocchesso & Smith (1997)

**“Circulant and elliptic feedback delay networks for artificial reverberation.”** *IEEE Transactions on Speech and Audio Processing* 5(1), 51–63. DOI `10.1109/89.554269`.

Structured lossless feedback matrices and their relation to normalized waveguide junctions.

### De Sena, Hacihabiboglu, Cvetković & Smith (2015)

**“Efficient Synthesis of Room Acoustics via Scattering Delay Networks.”** arXiv `1502.05751`.

Derives a delay-and-scattering reverberator from enclosure geometry, reproduces first-order reflections exactly, and approximates later reflections efficiently.

### Schlecht & Habets (2020)

**“Scattering in Feedback Delay Networks.”** *IEEE/ACM TASLP* 28, 1915–1924; arXiv `1912.08888`.

Generalizes scalar feedback matrices to arbitrary lossless filter feedback matrices.

### Das, Schlecht & De Sena (2023)

**“Grouped Feedback Delay Networks with Frequency-Dependent Coupling.”** *IEEE/ACM TASLP* 31, 2004–2015. DOI `10.1109/TASLP.2023.3277368`.

Uses stable paraunitary frequency-dependent coupling among delay-network groups.

**Collective implication:** orthogonal/unitary/paraunitary coupling and instrument/room delay-network structures are established. “The room is a network too” is a unifying design principle, not the central first claim.

**Ariadne opportunity:** heterogeneous instrument and room regions can become one graph governed by a reconfiguration/work law and an explicit ordered factor program.

---

## 5. Differentiable and learned delay networks

### Dal Santo, Prawda, Schlecht & Välimäki (2024)

**“Efficient Optimization of Feedback Delay Networks for Smooth Reverberation.”** arXiv `2402.11216`.

Optimizes differentiable FDN parameters to reduce coloration while preserving temporal density.

### Ilic Mezza, Giampiccolo, De Sena & Bernardini (2024)

**“Data-Driven Room Acoustic Modeling Via Differentiable Feedback Delay Networks With Learnable Delay Lines.”** arXiv `2404.00082`.

Introduces differentiable FDN fitting with trainable delay lines and perceptually motivated losses.

### Gerami & Duraiswami (2025)

**“Room Impulse Response Synthesis via Differentiable Feedback Delay Networks for Efficient Spatial Audio Rendering.”** arXiv `2510.00238`.

Optimizes FDNs for room-response and psychoacoustic targets and discusses dynamic rendering for source/listener movement.

### Jin et al. (2024)

**“DiffSound: Differentiable Modal Sound Rendering and Inverse Rendering for Diverse Inference Tasks.”** arXiv `2409.13486`.

Provides differentiable physics-based modal sound rendering for inverse problems including physical parameters, geometry, and impact position.

**Implication:** differentiability and inverse sound design are active fields. Ariadne's distinct offer is structural graph search constrained by executable energy/work contracts, not differentiability alone.

---

## 6. Ordered and non-Abelian acoustics

### Chen, Zhang, Chan & Ma (2022)

**“Classical non-Abelian braiding of acoustic modes.”** *Nature Physics* 18, 179–184. DOI `10.1038/s41567-021-01431-9`.

Demonstrates order-dependent braiding of degenerate acoustic waveguide modes captured by a non-Abelian Berry–Wilczek–Zee phase.

**Establishes:** genuinely non-Abelian acoustic transport is physically realizable and order is observable.

**Raises the bar:** a synthesis system should not borrow “non-Abelian geometric phase” merely because two matrices fail to commute.

**Ariadne distinction to test:** sparse lossless local scattering order as a continuously playable audio-synthesis control, with a same-endpoint closed loop, exact operator receipt, and listener validation.

Targeted searches for “holonomy audio synthesis,” “noncommutative sound synthesis,” and “path-dependent scattering network” did not surface a clear prior audio-synthesis treatment matching that combination. This absence is only a search result, not proof of novelty.

---

## 7. Claim matrix

| Proposed statement | Current posture |
|---|---|
| Energy-compensated moving delay is new | False; direct prior art exists. |
| Orthogonal scattering network is new | False. |
| Instrument and room can both be delay networks | False as a component claim. |
| Time-varying systems require more than frozen stability | Established prior art. |
| Port-Hamiltonian work accounting is new | False in general systems theory. |
| A sample-rate compiler for arbitrary changing recursive acoustic graphs with explicit state transport and work receipts | Plausible audio-specific contribution; novelty search required. |
| Ordered overlapping scattering produces deterministic audible path memory | Implemented and measured in Ariadne. |
| Same-endpoint closed-loop ordered scattering is a new synthesis primitive | Plausible; not yet implemented or validated. |
| Current Weave demonstrates non-Abelian geometric phase | Not established. |
| KG-ULTRA makes the DSP contribution novel | False; it is a separate design/reasoning layer. |

---

## 8. Immediate reading order

### For the work law

1. Pakarinen et al. 2008.
2. Bogason & Werner 2018.
3. Werner 2020.
4. Werner & McClellan 2022.
5. Celledoni & Høiseth 2017.
6. Mehrmann & Morandin 2019.
7. Delvenne & Sandberg 2013.

### For the graph compiler

1. De Sena et al. 2015.
2. Schlecht & Habets 2020.
3. Das et al. 2023.
4. Tablas de Paula et al. 2026.

### For optimization

1. Dal Santo et al. 2024.
2. Ilic Mezza et al. 2024.
3. DiffSound 2024.

### For ordered scattering

1. Chen et al. 2022.
2. the Lie-group/group-commutator derivation in Ariadne;
3. a fresh systematic search in DAFx, JAES, TASLP, SMC, NIME, and computer-music literature before submission.

---

## 9. Literature task for the research agent

Build a versioned bibliography database with:

- DOI/arXiv/venue;
- accessible manuscript artifact;
- exact claim supported;
- model class;
- time-varying variables;
- energy/storage function;
- topology assumptions;
- real-time status;
- source code/data availability;
- relation to WATSN;
- relation to ordered scattering;
- novelty risk.

Do not summarize from abstracts alone for the final paper. The sources above are the map for full-text review.
