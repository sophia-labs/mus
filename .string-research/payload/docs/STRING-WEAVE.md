# The string after Karplus–Strong

This note specifies the two related instruments implemented in
`mus-dsp::pluck`:

- `synth=pluck`: a deepened, physically informed guitar;
- `synth=weave`: an impossible network of strings, body modes, and moving
  lossless junctions.

The second is not an effects chain applied to the first. Both are instances
of one stateful string-network kernel, and the guitar is the conservative
limit of the larger construction.

## 1. What changed in the guitar

The first MUS pluck was already a good extended Karplus–Strong (EKS) voice:
it had fractional-delay tuning, a one-zero loss filter, a pick-position comb,
honest per-circulation T60, bends, strums, palm mute, a detuned copy, and two
post-loop body resonances. Its decisive limitation was structural: each
string was synthesized in isolation and the body was an output coloration.
No energy could leave one string, enter the bridge/body, and return to that
string or another string.

The new guitar makes five changes.

### 1.1 Physical initial displacement

The delay line is initialized primarily with the triangular displacement of
a string pulled at position `pos`. For string coordinate `x in [0,1]` and
pluck point `p`, the idealized shape is

```
y(x) = x/p                 for x < p
       (1-x)/(1-p)         for x >= p.
```

This shape, rather than a filtered noise period, is now responsible for the
large-scale harmonic envelope and its nodal nulls. Content-keyed roughness is
mixed in as a smaller contact term. `pick` controls the roughness mix and its
spatial smoothing, so a finger and a hard plectrum differ without changing
the note's identity or relying on a global random stream.

### 1.2 Phase-budgeted damping and dispersion

One circulation of course `i` contains an integer delay, a one-zero loss
filter, two first-order allpass dispersion sections, and an exact-at-f0
fractional allpass. At each control update, the algorithm budgets the phase
of every element:

```
D_i + tau_loss(w0) + tau_disp(w0) + tau_frac(w0) = Fs / f_i.
```

The fractional allpass coefficient is solved from its desired phase delay at
the current fundamental, not approximated only from its DC group delay. The
fundamental remains tuned while `stiff` increases the phase delay of upper
partials and therefore their inharmonicity. If a very high note has too
little round-trip delay for the requested stiffness, stiffness is reduced
rather than violating causality or silently detuning the note.

The scalar circulation gain compensates the loss filter's magnitude at the
fundamental:

```
g_i = min(0.9999995, 10^(-3/(T60_i f_i)) / |H_loss(exp(j w0))|).
```

Thus `sus` continues to denote the fundamental's approximate -60 dB time,
while upper partials decay faster according to `damp`.

### 1.3 Tension glide tied to energy decay

A hard pluck stretches a real string, temporarily raising all of its partial
frequencies. Recorded guitar tones are well described by an exponential
relaxation

```
f_i(t) = f_i * (1 + alpha exp(-t/tau)).
```

MUS exposes the initial elevation as `tension` in cents. It does not add an
independent arbitrary time constant: if amplitude reaches 0.001 at `T60`,
squared displacement and mean elongation decay with

```
tau_tension = T60 / (2 ln 1000).
```

This creates the audible sharp-then-settling onset of a hard pluck while
keeping the control surface small and physically legible.

### 1.4 A body inside the loop

The body is a bank of damped modal rotations. Each mode has normalized
position and momentum `(q_m, p_m)`, free evolution

```
[q_m']   = r_m [ cos(w_m)  -sin(w_m) ] [q_m]
[p_m']         [ sin(w_m)   cos(w_m) ] [p_m],
```

and a small coupling angle to every string endpoint. The coupling is a
Givens rotation of a string wave `s_i` and modal momentum `p_m`:

```
[s_i']   [ cos(theta)  -sin(theta) ] [s_i]
[p_m'] = [ sin(theta)   cos(theta) ] [p_m].
```

This is exactly norm-preserving before the mode's declared damping. Energy
can now move from string to body and back. Optional standard-tuning open
strings (`symp`) join the same bridge and can ring without direct excitation.
The body's current modal table is a deliberately synthetic steel-string
body, not a claim to reproduce a particular measured guitar. `body_size`
scales its resonance frequencies.

### 1.5 Contractive contact

`buzz` introduces a soft unilateral contact at the lumped endpoint. Above a
clearance threshold, `tanh` compression guarantees that the feedback
magnitude does not exceed the incoming magnitude. The removed component is
radiated as a bright contact signal but is never reinjected. The model is
not yet a spatial fretboard; it is a stable, audible first contact model and
a placeholder for a future two-polarization, spatially located fret junction.

## 2. Weave: an impossible instrument

A Weave note contains the directly played courses plus enough virtual
courses to reach `courses`. Their fundamental distribution is not a normal
harmonic series. It is derived from a spectral dimension `d`:

```
N(f) proportional to f^d     =>     f_k proportional to k^(1/d),
```

then octave-folded into a playable register. Integer `d=1` is sparse and
string-like; larger `d` packs modes more densely; non-integer values produce
structured inharmonicity.

The courses share the same modal body as the guitar, but also scatter around
a ring. For edge `e=(i,i+1)`, sample `n`, and local state `x_n`, the angle is

```
theta_e(n,x) = couple
             * [1 + orbit_depth sin(2 pi orbit n/Fs + phi_e)]
             * [1 + 0.72 curvature tanh(energy_gradient_e(x))].
```

Each edge update is still a Givens rotation. `chirality` divides the angle
between a forward ordered sweep and a reverse ordered sweep. At zero, both
directions participate equally. Near +1 or -1, one ordering dominates, and
energy visibly travels around the virtual instrument.

### 2.1 Pointwise nonlinear passivity theorem

Let `Q_n(x)` be any product of the state-dependent Givens rotations used at
sample `n`. For every finite state `x`, every factor is orthogonal, hence

```
Q_n(x)^T Q_n(x) = I
```

and, even though the map `x -> Q_n(x)x` is nonlinear,

```
||Q_n(x)x||_2 = ||x||_2.
```

Let `D_n` collect the declared string and body losses, with operator norm at
most one. With no excitation,

```
x_(n+1) = D_n Q_n(x_n) x_n
```

satisfies

```
E_(n+1) = 1/2 ||x_(n+1)||_2^2 <= 1/2 ||x_n||_2^2 = E_n.
```

This is stronger than testing that a few patches happen not to explode. The
exotic modulation and the state-dependent geometry are unable to manufacture
stored energy by construction.

The theorem applies to the normalized scattering state. The full delay-line
system additionally contains finite excitation injection, explicitly
contractive loop filters, damped body evolution, and contractive contact.
The pure-core Lean theorem in `formal/MusFormal/Holonomy.lean` proves the
quantized skeleton of the same argument: preserving junctions followed by a
strictly lossy edge must silence. The floating-point invariant suite below
polices the analytic implementation until the planned mathlib layer can
state the real-valued operator theorem directly.

### 2.2 Audible holonomy and the Weave defect

Adjacent rotations do not commute. On three courses, let `R01(a)` rotate
courses 0 and 1, and `R12(b)` rotate courses 1 and 2. The two gesture words

```
A then B: R12(b) R01(a)
B then A: R01(a) R12(b)
```

end at the same scalar control values but generally produce different modal
states. MUS defines the normalized Frobenius commutator magnitude

```
h(a,b) = ||R01(a)R12(b) - R12(b)R01(a)||_F / sqrt(2)
```

and derives the closed form

```
h(a,b)^2 = (cos(a)-1)^2 sin(b)^2
           + (cos(b)-1)^2 sin(a)^2
           + sin(a)^2 sin(b)^2.
```

For small angles, `h(a,b) ~ |ab|`. The implementation exports
`weave_holonomy_defect(a,b)` and proves the closed form against direct matrix
action in the test suite. This scalar is not merely a stability metric: it
estimates how strongly the order of two coupling gestures can alter the
resulting timbre.

The term *holonomy* is used carefully here. This is a discrete control-cycle
holonomy of a synthesized wave network. It is inspired by, but does not
claim the topological protection or adiabatic degeneracy conditions of
non-Abelian acoustic-mode braiding experiments.

## 3. Controls

The original controls remain:

- `sus`, `damp`, `pos`, `pick`, `body`, `strum`, `pm`, `detune`.

The guitar extensions are:

- `stiff` — dispersive stiffness, 0..1;
- `tension` — initial pitch elevation, cents;
- `symp` — sympathetic-open-string bridge coupling, 0..1;
- `buzz` — contractive contact amount, 0..1;
- `body_size` — body scale ratio, 0.45..2.4.

The Weave controls are:

- `courses` — total courses, 3..24;
- `dimension` — spectral dimension, 0.55..3;
- `couple` — ring-scattering angle, 0..0.45 radians;
- `chirality` — forward/reverse ordering bias, -1..1;
- `orbit` — travelling modulation rate, Hz;
- `orbit_depth` — travelling modulation depth, 0..1;
- `curvature` — energy-dependent metric amount, 0..1.

## 4. Relationship to prior work

This implementation deliberately composes established physical-modeling
ideas before departing from them:

1. Jaffe and Smith's extended Karplus–Strong and digital-waveguide framing.
2. Tunable allpass dispersion filters for stiff-string waveguides:
   J. Rauhala and V. Välimäki, “Dispersion Modeling in Waveguide Piano
   Synthesis Using Tunable Allpass Filters,” DAFx-06.
3. Measured guitar pitch glide and exponential tension relaxation:
   N. Lee, J. O. Smith III, J. Abel, and D. Berners, “Pitch Glide Analysis
   and Synthesis from Recorded Tones,” DAFx-09.
4. Structurally passive pluck and contact junctions:
   G. Evangelista and J. O. Smith III, “Structurally Passive Scattering
   Element for Modelling Guitar Pluck Action,” DAFx-10.
5. Passive multidimensional bridge admittance:
   B. Bank and M. Karjalainen, “Passive Admittance Matrix Modeling for
   Guitar Synthesis,” DAFx-10.
6. Energy-based real-time nonlinear interconnection:
   M. Ducceschi, S. Bilbao, and C. Webb, “Real-Time Modal Synthesis of
   Nonlinearly Interconnected Networks,” DAFx-23.
7. Classical non-Abelian acoustic mode braiding:
   Z.-G. Chen, R.-Y. Zhang, C. T. Chan, and G. Ma, “Classical non-Abelian
   Braiding of Acoustic Modes,” Nature Physics 18, 179–184 (2022).

The first six establish that dispersion, pitch glide, passive junctions,
body admittance, and nonlinear networks are mature ideas. Acoustic braiding
establishes that path-order-dependent mode transformations are physically
meaningful wave phenomena. The candidate contribution here is the particular
real-time synthesis construction joining them: a guitar-compatible
Karplus–Strong family whose generalized instrument uses state-dependent,
time-periodic, ordered orthogonal scattering and exposes its noncommutativity
as a musical control and measurable defect.

A literature search found no prior musical string synthesizer with this exact
combination. That is evidence for novelty, not proof of priority. A serious
publication claim would require a broader systematic review, ablation studies,
listening tests, CPU benchmarks, and comparison against measured guitar
recordings.

## 5. Validation and next research steps

The current invariant suite checks:

- byte determinism and content-keyed variation;
- block-size invariance for a future plugin host;
- tuning across the guitar neck;
- fundamental T60;
- midpoint-pluck harmonic suppression;
- stiffness-induced upper-partial spreading while retaining f0;
- onset pitch relaxation;
- actual body-coupling spectral change;
- bend landing;
- Weave path sensitivity and determinism;
- finite, bounded behavior at extreme controls;
- exact norm preservation of fixed and state-dependent Givens scattering;
- the closed-form Weave defect.

The next scientifically valuable steps are not more knobs. They are:

1. Fit the body modal table and bridge coupling to measured admittance and
   radiativity from one real guitar.
2. Add two polarizations per string and a spatially located fret/contact
   junction.
3. Measure partial T60 and inharmonicity against isolated recorded notes.
4. Run MUSHRA-style listening tests for realism and separate preference tests
   for Weave patches.
5. Expose the allocation-free `StringNetworkVoice::render_block` kernel in
   the existing VST/CLAP host and measure worst-case real-time cost.
6. Treat Weave control paths as first-class score objects, then compare
   protocol words with identical endpoints but different holonomy defects.
