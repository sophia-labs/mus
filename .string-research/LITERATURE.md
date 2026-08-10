# Ariadne literature map

This is a working annotated bibliography, not an exhaustive novelty determination. It distinguishes established ingredients from the specific Ariadne research program.

## Foundations

### Karplus & Strong (1983)

**“Digital Synthesis of Plucked-String and Drum Timbres.”** *Computer Music Journal* 7(2), 43–55. DOI `10.2307/3680062`.

The canonical short excitation plus recirculating averaging loop. Ariadne preserves its efficiency but makes strings, junctions, bodies, and topology explicit.

### Jaffe & Smith (1983)

**“Extensions of the Karplus–Strong Plucked-String Algorithm.”** *Computer Music Journal* 7(2), 56–69. DOI `10.2307/3680063`.

The direct prior art for tuning, decay, excitation, and plucked-string controls. Fractional delay, pick position, and extended loss filtering are not Ariadne novelty claims.

### Smith (1983)

**“Techniques for Digital Filter Design and System Identification, with Application to the Violin.”** PhD dissertation, Stanford University.

The digital-waveguide interpretation and system-identification posture behind modern efficient physical modeling.

### Karjalainen, Välimäki & Tolonen (1998)

**“Plucked-string models: from the Karplus–Strong algorithm to digital waveguides and beyond.”** *Computer Music Journal* 22(3), 17–32.

The compact taxonomy to use when judging whether a proposed guitar refinement is genuinely beyond standard EKS practice.

### Tablas de Paula, Smith, Välimäki & Reiss (2026)

**“Four Decades of Digital Waveguides.”** arXiv `2604.12878`.

A current field review covering instruments, sound effects, reverberation, and modern optimization. It is the best entry point for the next research pass.

## Time variation and nonlinear strings

### Välimäki, Tolonen & Karjalainen (1999)

**“Plucked-string synthesis algorithms with tension modulation nonlinearity.”** IEEE ICASSP 1999, 977–980.

Direct prior art for amplitude-dependent pitch movement using time-varying fractional delays. The draft’s `tension` control should be compared against these models.

### Pakarinen, Puputti & Välimäki (2008)

**“Virtual Slide Guitar.”** *Computer Music Journal* 32(3), 42–54. DOI `10.1162/comj.2008.32.3.42`.

Uses an energy-compensated time-varying digital waveguide and models slide/string contact. This is the highest-priority source for repairing the current passivity gap around bends and moving delays.

### Issanchou, Bilbao, Le Carrou, Touzé & Doaré (2017)

**“A modal-based approach to the nonlinear vibration of strings against a unilateral obstacle.”** *Journal of Sound and Vibration* 393, 229–251. DOI `10.1016/j.jsv.2016.12.025`.

A stiff damped string, penalty contact, conservative time integration, and experiment. This is a rigorous successor path for `buzz` and moving obstacles.

### “String/frets contacts in the electric bass sound” (2018)

*Applied Acoustics* 129, 217–228. DOI `10.1016/j.apacoust.2017.07.021`.

Numerical and experimental work on fret collisions, structure coupling, and string polarization. It shows how much richer realistic contact is than a scalar saturator.

## Body admittance and radiation

### Maestre, Scavone & Smith (2017)

**“Joint Modeling of Bridge Admittance and Body Radiativity for Efficient Synthesis of String Instrument Sound by Digital Waveguides.”** *IEEE/ACM TASLP* 25(5), 1128–1139. DOI `10.1109/TASLP.2017.2689241`.

Provides modal decomposition of measured bridge admittance, a common modal basis for admittance and radiation, and passivity enforcement. It is the blueprint for replacing Ariadne’s rough ten-mode body with content-addressed measured or designed body profiles.

## Lossless networks and scattering

### Rocchesso & Smith (1997)

**“Circulant and elliptic feedback delay networks for artificial reverberation.”** *IEEE Transactions on Speech and Audio Processing* 5(1), 51–63. DOI `10.1109/89.554269`.

Relates orthogonal FDNs to normalized digital-waveguide junctions and develops structured lossless matrices. Orthogonal multi-delay coupling is established prior art.

### Schlecht & Habets (2020)

**“Scattering in Feedback Delay Networks.”** *IEEE/ACM TASLP* 28, 1915–1924. DOI `10.1109/TASLP.2020.3001395`; arXiv `1912.08888`.

Generalizes feedback matrices to arbitrary lossless filter feedback matrices. This is a route from scalar Givens couplings to frequency-dependent lossless junction filters.

### Das, Schlecht & De Sena (2023)

**“Grouped Feedback Delay Networks with Frequency-Dependent Coupling.”** *IEEE/ACM TASLP* 31, 2004–2015. DOI `10.1109/TASLP.2023.3277368`.

Stable paraunitary coupling among groups of delay networks. Relevant to course groups, body groups, and frequency-selective bridges.

## Ordered acoustic transport

### Chen, Zhang, Chan & Ma (2022)

**“Classical non-Abelian braiding of acoustic modes.”** *Nature Physics* 18, 179–184. DOI `10.1038/s41567-021-01431-9`.

Demonstrates order-dependent acoustic transport of degenerate modes through a Berry–Wilczek–Zee phase. It proves that genuinely non-Abelian acoustic transport is possible, but also sets a higher formal bar than current Weave meets.

Current distinction:

- Weave has noncommuting ordered Givens products and measurable path memory;
- it does not yet have an adiabatically transported degenerate subspace, connection, or gauge-invariant cyclic observable;
- cite this as a neighboring target, not as proof that current Ariadne is topological.

## Spectral dimension and impossible geometry

### Avrachenkov, Cottatellucci & Hamidouche (2019)

**“Eigenvalues and Spectral Dimension of Random Geometric Graphs in Thermodynamic Regime.”** arXiv `1910.08869`.

Treats spectral dimension as a property of graph Laplacian eigenvalue density and random-walk behavior. It supports upgrading `dimension` from a frequency exponent to a measured property of a generated topology.

### Lapidus & Pomerance (1993)

**“The Riemann Zeta-Function and the One-Dimensional Weyl–Berry Conjecture for Fractal Drums.”** *Proceedings of the London Mathematical Society* 66(1), 41–69. DOI `10.1112/plms/s3-66.1.41`.

A rigorous relationship among fractal strings, dimension, and spectral asymptotics. It is the right background for operator-derived fractal-string instruments and a warning against calling a folded power-law list a fractal geometry.

### Fedorov, Beccari, Engelsen & Kippenberg (2020)

**“Fractal-like Mechanical Resonators with a Soft-Clamped Fundamental Mode.”** *Physical Review Letters* 124, 025502. DOI `10.1103/PhysRevLett.124.025502`.

A physical self-similar network of tensioned strings with unusual modal and dissipation properties. It is concrete inspiration for impossible but mechanically interpretable Ariadne topologies.

## Perceptual validation

Relevant starting points include Grey’s multidimensional scaling of musical timbre, McAdams and collaborators’ perceptual scaling of synthesized timbres, and the Timbre Toolbox work by Peeters and collaborators.

Ariadne implication:

- do not reduce success to brightness or one embedding coordinate;
- retain listener-level variation;
- use descriptors to select and explain listening samples, not to replace listening.

## Known ingredients

The following are independently established:

- KS/EKS and digital-waveguide strings;
- fractional-delay tuning and pick-position excitation;
- dispersion and tension modulation;
- time-varying waveguides with energy compensation;
- nonlinear string/contact models;
- body modal synthesis and passive bridge/radiation fitting;
- sympathetic string coupling;
- orthogonal, unitary, and paraunitary delay networks;
- acoustic order-dependent modal transport;
- fractal and graph spectral geometry.

## Proposed Ariadne synthesis

The distinctive research hypothesis is a playable family in which:

1. an improved guitar is the conservative limit;
2. virtual courses and bodies form explicit resonator geometries;
3. coupling is factored into sparse local isometries;
4. the order and path of those couplings is a performance variable;
5. state-dependent angles create nonlinear routing while retaining pointwise norm;
6. path contrast is measured mathematically, psychoacoustically, and by listener identification;
7. the same block kernel serves MUS and a real-time plugin.

That combination appears research-worthy. It is not yet a defensible “first” claim.

## Immediate reading order

For implementation:

1. Pakarinen et al. 2008 — variable-delay energy compensation.
2. Maestre et al. 2017 — passive body admittance and radiativity.
3. Issanchou et al. 2017 — contact stability.
4. Karjalainen et al. 1998 — plucked-string model taxonomy.
5. Schlecht & Habets 2020 — lossless filter feedback matrices.

For the novel program:

1. Chen et al. 2022 — the formal requirements of acoustic non-Abelian transport.
2. Rocchesso & Smith 1997 — network prior art.
3. Das et al. 2023 — stable frequency-dependent coupling.
4. Avrachenkov et al. 2019 and Lapidus–Pomerance 1993 — spectral dimension.
5. Tablas de Paula et al. 2026 — current survey and optimization directions.

## Conclusions

1. The guitar upgrade is plausible but its ingredients are known; quality comes from integration, fitting, and control.
2. The time-varying-delay proof gap is real and fixable with established methods.
3. Orthogonal coupling is known; ordered state-dependent coupling must earn novelty through audible same-endpoint path experiments.
4. Measured passive body modeling is mature enough to adopt.
5. Strong geometric-holonomy language requires a cyclic modal-transport formalism not yet present.
6. Spectral dimension should eventually arise from an operator, not only a power law.
7. The central evidence should be a reproducible path-memory demonstration that listeners can identify and use musically.
