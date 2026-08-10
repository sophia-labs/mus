# Guitar and Ariadne design

This document describes the instrument family rather than the implementation mechanics. The core product decision is that Ariadne is not “a weird effect after a guitar.” The guitar and the impossible instrument are two regions of one string-network ontology.

## 1. Names and boundaries

- **String Network**: the general DSP abstraction.
- **Guitar**: the conservative physical region, selected by `synth=pluck`.
- **Weave**: the ordered-coupling synthesis model, selected by `synth=weave`.
- **Ariadne**: the playable instrument and eventual plugin/product built from Weave.

The ordinary guitar should be obtainable as a low-coupling, physically calibrated limit of the wider system. Ariadne should remain playable as it departs from that limit.

## 2. The shared ontology

Every voice consists of:

1. **courses** — active or sympathetic delay-line resonators;
2. **excitation** — where, how, and with what contact the courses are set in motion;
3. **propagation** — delay, damping, dispersion, and time-varying length/tension;
4. **junctions** — sparse lossless or passive scattering between courses and body modes;
5. **body** — stored modal state that receives energy and radiates it;
6. **contacts** — bridge, fret, slide, mute, collision, or other nonlinear boundary events;
7. **radiation** — the pickup map from internal state to audible output;
8. **gesture path** — the ordered trajectory of couplings and geometry through time.

A guitar preset constrains these to a plausible wooden instrument. Ariadne deliberately relaxes course count, spectrum, topology, and coupling trajectory while preserving causal, bounded behavior.

## 3. Guitar development ladder

### G0 — existing extended Karplus–Strong

Current baseline:

- one recirculating delay per pitch;
- fractional allpass tuning;
- one-zero brightness decay;
- position-combed noise burst;
- two post-filter body peaks;
- bends, strum, palm mute, detune.

This is a good musical prototype and a weak physical guitar. Preserve it as the comparison point.

### G1 — credible isolated string

The staged payload adds:

- triangular displaced-string excitation;
- contact roughness as a secondary component rather than the entire initial state;
- fundamental-phase compensation across damping and dispersion;
- stiff-string allpass dispersion;
- onset tension modulation;
- contractive contact/buzz.

Acceptance question: can one isolated note move from “recognizable KS pluck” to “convincing string under a hand” before body or reverb is added?

### G2 — coupled modal body

Replace post-EQ body coloration with stored body modes coupled inside the feedback system.

The rough model uses ten normalized oscillators and sparse rotations. The production model should support a body profile containing:

```text
mode frequency
modal T60 / damping
bridge admittance residue
radiation residue per pickup/microphone
modal normalization / impedance
optional cross-polarization or duplicate modes
```

A measured or designed profile should be serializable and content-addressed. The same representation can describe a dreadnought, parlor guitar, steel plate, glass shell, or impossible body.

### G3 — bridge-mediated sympathetic resonance

The rough implementation adds six hidden standard-guitar open courses and couples them through the body. The stronger model treats the bridge as a multiport admittance shared by all strings and body modes.

Required behaviors:

- an open course responds most strongly near its own modes;
- fretting/muting alters the set of available sympathetic resonators;
- sympathetic energy remains much lower than directly excited energy;
- disabling `symp` removes the effect continuously;
- a chord can excite plausible after-ring without turning into reverb.

### G4 — player and contact vocabulary

Add independent, physically interpretable event controls:

- fingertip, nail, felt, thin pick, thick pick;
- pluck displacement and velocity components;
- pick angle and scrape duration;
- left-hand damping;
- fret position and action/clearance;
- slide/bar contact;
- bridge and nut hardness;
- string gauge/material profile;
- finger release, squeak, and reposition events.

The current `pick`, `pm`, `buzz`, and `pos` controls are compact macros over this larger space.

### G5 — calibrated guitar instrument

A release-quality guitar profile should include:

- six explicit string material/geometry records;
- measured or fitted body admittance and radiativity;
- pickup/microphone positions;
- bridge/nut/contact profiles;
- validation recordings or descriptor targets;
- performance gestures expressed in MUS rather than hidden randomization.

This is a separate milestone from Ariadne’s novelty. A dazzling impossible instrument does not excuse an unconvincing conservative limit.

## 4. Weave development ladder

### W0 — static unitary course network

Start with fixed-length courses and a fixed sparse orthogonal coupling matrix. This is the clean mathematical control condition.

Expected sound: a family of coupled strings whose energy migrates among resonators, with stable decays and denser modal beating than independent KS strings.

### W1 — ordered chiral coupling

Factor the coupling into local Givens rotations and expose the order bias:

- `chirality=+1`: forward ordered pass;
- `chirality=-1`: reverse ordered pass;
- `chirality=0`: balanced forward/reverse passes.

Because overlapping rotations do not commute, the sign is not merely stereo direction. It changes the internal state trajectory.

### W2 — travelling orbit

Move coupling strength around the ring or graph:

- `orbit`: rate in hertz;
- `orbit_depth`: modulation depth;
- per-course phase offsets create a travelling field.

Expected sound: sidebands and timbral motion generated by energy routing, not by an output chorus.

### W3 — state-dependent metric

Let local energy gradients deform coupling angles through `curvature`. This makes the scattering map nonlinear while retaining pointwise orthogonality.

Expected sound: notes with identical nominal controls can develop different internal routes depending on where energy currently resides. This is the first genuinely ecology-like Ariadne behavior.

Safety rule: the state-dependent scalar may change angles, but it must never replace the orthogonal map with arbitrary gain.

### W4 — operator-derived virtual geometry

Replace the current power-law frequency scaffold with an explicit topology:

- ring, chain, tree, lattice, Möbius ladder, hyperbolic tiling patch, fractal string, or arbitrary graph;
- edge weights define coupling;
- vertex masses/impedances define the energy metric;
- a graph/Laplacian or wave operator supplies modes;
- excitation and radiation are spatial functions over the graph.

This makes “impossible instrument geometry” literal rather than metaphorical.

### W5 — moving topology and cyclic transport

Allow edges, junction order, or modal basis to move through a declared control cycle. Track the path-ordered transport and expose cyclic path observables.

This is the milestone where geometric-holonomy language may become technically deserved. It should not block the first playable instrument.

## 5. Rough presets

These are starting hypotheses, not approved defaults.

### `guitar_clean`

```text
synth=pluck
sus=2.7 damp=0.30 pos=0.14 pick=0.52 body=0.48
stiff=0.07 tension=6 symp=0.18 buzz=0
body_size=1 detune=0 strum=11
```

Goal: articulate steel/nylon-adjacent fingerstyle without obvious synthesis shimmer.

### `guitar_steel_course`

```text
synth=pluck
sus=3.4 damp=0.24 pos=0.09 pick=0.78 body=0.55
stiff=0.18 tension=12 symp=0.28 buzz=0.04
detune=5 strum=14
```

Goal: brighter steel string, modest course beating, audible body and after-ring.

### `guitar_felt_muted`

```text
synth=pluck
sus=1.5 damp=0.62 pos=0.18 pick=0.12 body=0.32
stiff=0.04 tension=2 symp=0.08 buzz=0 pm=1
```

Goal: close, soft, percussive, with little synthetic click.

### `ariadne_thread`

```text
synth=weave
sus=3.1 damp=0.30 pos=0.17 pick=0.46 body=0.52
stiff=0.16 tension=7
courses=11 dimension=1.35
couple=0.11 chirality=0.72 orbit=0.31 orbit_depth=0.62 curvature=0.28
```

Goal: clearly beyond guitar but stable, pitched, and useful for harmony.

### `ariadne_labyrinth`

```text
synth=weave
sus=4.3 damp=0.24 pos=0.23 pick=0.58 body=0.68
stiff=0.34 tension=15 buzz=0.08
courses=17 dimension=1.08
couple=0.19 chirality=-0.86 orbit=0.57 orbit_depth=0.82 curvature=0.61
```

Goal: path-sensitive, dense, mobile partials with a recognizable plucked onset.

### `ariadne_extreme`

```text
synth=weave
sus=5.2 damp=0.16 pos=0.31 pick=0.84 body=0.84
stiff=0.72 tension=28 buzz=0.24
courses=24 dimension=0.72
couple=0.34 chirality=1 orbit=2.3 orbit_depth=1 curvature=0.92
```

Goal: impossible broad-band string ecology. This should remain a laboratory preset until aliasing, loudness, CPU, and modulation-energy behavior are characterized.

## 6. Performance-level macro controls

A plugin should not put nineteen scientific parameters on the first page. Keep the complete expert surface in MUS and expose a smaller musically coherent macro surface.

### Thread

How much identity remains attached to the played pitch.

Suggested mapping:

- low Thread: more virtual courses, lower dimension, stronger coupling;
- high Thread: fewer courses, higher direct radiation, lower coupling and curvature.

### Labyrinth

How path-sensitive and internally routed the sound is.

Suggested mapping:

- `couple` nonlinear rise;
- absolute `chirality` rise;
- `orbit_depth` rise;
- `curvature` rise only in the upper half.

### Motion

Rate and liveliness of internal geometry.

Suggested mapping:

- `orbit` on an exponential 0–8 Hz scale;
- modest tension and contact modulation if safe;
- never modulate raw delay discontinuously from this macro.

### Material

String stiffness, contact hardness, and high-frequency decay.

Suggested mapping:

- coordinated `stiff`, `pick`, `damp`, and `buzz` curves;
- preserve loudness and settled pitch while moving from felt/organic to wire/glass.

### Body

Coupling and scale of the resonant body.

Suggested mapping:

- `body` amount;
- `body_size` over a musically useful 0.65–1.7 range;
- optional morph between body profiles when the profile system exists.

### Memory

Persistence of prior internal routing.

The rough engine has no independent memory scalar. A first mapping can coordinate longer `sus`, stronger but stable coupling, and slower orbit. The stronger implementation explicitly separates course loss from junction mixing and defines a decay time for path contrast.

### Hand

Human contact and imperfection.

Suggested mapping:

- `pick`, `pos`, `tension`, micro-strum, modest `buzz`, and sympathetic coupling;
- all variation remains content-keyed or explicitly performed, never global nondeterministic drift.

## 7. Macro interpolation law

Raw linear interpolation across the entire control cube will cross ugly and unsafe regions. Presets should be manifolds, not corners.

For a macro \(m\in[0,1]\), use shaped mappings such as:

\[
p(m)=p_0+(p_1-p_0)m^\alpha
\]

or bounded logistic curves. Coupled parameters should be generated together, then projected into a safe set. The projection may enforce:

- maximum predicted feedback gain;
- maximum virtual frequency;
- minimum course spacing;
- maximum estimated CPU;
- maximum orbit-depth × coupling product;
- compatible body/coupling normalization.

The parameter manifest should record both macro values and resolved scientific parameters.

## 8. MUS and plugin architecture

`StringNetworkVoice` is deliberately stateful:

```rust
StringNetworkVoice::guitar(...)
StringNetworkVoice::weave(...)
voice.render_block(&mut output)
```

That is the right seam for both offline MUS rendering and a plugin voice. The plugin wrapper should not reimplement synthesis.

Recommended layering:

```text
mus-dsp
  StringNetworkVoice, topology, body profiles, passive contacts

mus-engine
  score/event dispatch, deterministic identity, rendering and receipts

ariadne-plugin
  voice allocation, MIDI/MPE/automation, preset and macro mapping,
  CLAP/VST3 host integration, UI bridge

Atril/Shrubbery
  expert graph editor, score-to-parameter automation, analysis views
```

The plugin should be a client of the declared vocabulary, not a second hand-maintained parameter registry.

## 9. Performance expression

Ariadne benefits from per-note expression more than ordinary subtractive synthesis.

High-value mappings:

- velocity → displacement/contact energy, not output gain alone;
- poly pressure → coupling or body transfer;
- timbre/CC74 → Material or pick position;
- pitch bend → physically retuned delay with energy compensation;
- slide gesture → moving contact and string length;
- release velocity → finger lift/mute behavior;
- note-to-note legato → preserve selected network state rather than always reinitialize.

A future “thread transfer” gesture could move state from one played pitch/course subset to another. This would make the metaphor operational: the performer hands the same vibrating thread into a new geometry.

## 10. What should be audible

The first listening milestone is not “many parameters work.” It is a sequence of qualitative recognitions:

1. `pluck` sounds more like a string under a hand than the original KS voice.
2. body amount changes the evolution and after-ring, not merely the EQ.
3. sympathetic strings create sparse pitch-specific response, not wash.
4. low-coupling Weave sounds like a plausible multi-course instrument.
5. chirality reversal changes timbral history without a gross pitch or loudness trick.
6. orbit creates moving internal sidebands that remain causally attached to the pluck.
7. high curvature makes the instrument react to its own state.
8. extreme Ariadne sounds physically impossible but still intentional.

If steps 1–4 fail, more exotic mathematics will not save the instrument.

## 11. Product nonclaims

Until the relevant experiments land, do not market Ariadne as:

- the first non-Abelian musical instrument;
- a proven passive system under arbitrary automation;
- a physical simulation of a specific real guitar;
- a literal fractal or fractional-dimensional body;
- a topological instrument;
- perceptually superior to state-of-the-art guitar physical models.

The defensible early description is:

> Ariadne is a playable network of digitally modelled strings and bodies. It uses ordered, energy-structured coupling so that the path taken through its controls can become part of the sound. Its conservative limit is a deeply modelled plucked guitar; its extended geometries describe instruments that cannot conveniently exist in matter.
