# MUS-F — field notation for acoustic graphs

*Working design, draft 0.1. Extends MUS from a compact score language into a compact language for acoustic fields, graph transformations, controls, constraints, experiments, and inverse design.*

## 1. Why MUS needs a field layer

Core MUS is optimized for a score: pitches, durations, tracks, bars, articulations, dynamics, quotations, and event parameters. MUS-A extends the event surface into recorded sound and continuous parameter sweeps. Neither is the right language for declaring:

- resonator and delay topology;
- state coordinates and energy metrics;
- sparse scattering factors and their order;
- time-varying geometry;
- topology transitions and state-transport policy;
- sources, pickups, and radiation ports;
- whole-graph transformations;
- constraints, work budgets, and invariants;
- probes, comparisons, and listening-study stimuli;
- inverse-design goals;
- graph queries;
- semantic identities and evidence links.

Putting all of that into per-note `[key=value]` suffixes would destroy the compactness that makes MUS useful. Writing raw RDF or matrices would make composition unbearable.

**MUS-F is a graph-native, unit-typed, declarative field layer that compiles to the same authoritative graph and DSP intermediate representation as the UI and agent tools.** It is designed for a human to inspect and for a superhuman agent to manipulate at graph scale.

The design goal is semantic compression, not punctuation golf.

---

## 2. File and embedding model

MUS-F can exist in either form.

### 2.1 Companion field file

```text
piece.mus
piece.musf
```

The score binds the field:

```mus
# field: piece.musf#thread
```

This is the first implementation target because it does not disturb the existing score parser.

### 2.2 Embedded field block

A future unified parser may allow:

```mus
@field thread {
  ...
}
```

Ordinary MUS syntax remains unchanged outside `@` blocks. A file containing MUS-F declares:

```mus
# mus-field: 0.1
```

An old parser may reject the extension loudly; it must never silently render a field-bound track with a different synth.

---

## 3. Principles

1. **Graph-shaped source.** Topology is written as topology, not encoded in parameter names.
2. **Stable identity.** Every declared object has a stable ID independent of line number.
3. **Units everywhere.** `110Hz`, `18ms`, `-21.5c`, `0.31rad`, `2.4s`, `-6dB`.
4. **Order is explicit.** Sequential operator composition is never inferred from RDF set order.
5. **Selectors operate over the whole graph.** An agent can address a family, relation, cycle, region, or predicate without rewriting each member.
6. **Controls are values or fields.** A parameter may vary over time, graph position, state, or evidence.
7. **Constraints are source.** Energy, work, range, topology, and reproducibility rules live beside the graph.
8. **Goals are declarative.** Inverse design specifies targets, variables, constraints, and budgets.
9. **Every stochastic choice is seeded.**
10. **Every lowering is canonical and receipted.**
11. **Escape hatches are typed.** Direct matrices and code exist, but are explicit foreign artifacts.
12. **The notation remains skimmable.** Common structures have strong sugar; unusual structures remain fully expressible.

---

## 4. Lexical conventions

### Identifiers

```text
thread
room.halo
strings[0]
&urn-backed-id
```

Names are local aliases. The compiler assigns or resolves stable graph IDs.

### References

- `$name` — control or parameter value;
- `@name` — declared field, region, path, gesture, transform, probe, or solve task;
- `artifact("sha256:...")` — immutable external artifact;
- `iri("https://...")` — explicit semantic identity.

### Ranges and sets

```text
0..5          # inclusive integer range
0..<6         # half-open range
[0,2,4]
strings[*]
strings[where f0 > 440Hz]
edge[region=room & kind=scatter]
```

Selectors are evaluated in stable-ID order unless an explicit order is requested.

### Quantities

```text
110Hz
12.5ms
2.4s
-21.5c
0.31rad
74dBSPL
-20dBFS
0.5eu          # normalized energy unit when no physical calibration exists
```

A bare number is dimensionless.

### Curves

```text
0 -> 1
0 -> 1 ease=smooth
curve[(0,0),(.2,1),(.8,.7),(1,0)]
sin(rate=.31Hz, phase=0rad)
quote(@gesture.h67)
```

### Composition operators

```text
A >> B         # ordered sequential composition
A || B         # explicitly parallel/disjoint composition
A + B          # signal or control sum, type checked
k * A          # scalar action where defined
inverse(A)     # declared inverse
-A             # sugar for inverse of an angle-parameterized rotation
A^4            # repeated ordered composition
```

`>>` is semantically load-bearing and survives every round trip.

---

## 5. Top-level forms

```text
import
field
region
state
junction
port
edge
factor
metric
source
pickup
control
signal
path
gesture
transition
transform
set
assert
observe
probe
query
variant
solve
export
```

The language is declarative. It has bounded comprehensions and macro expansion, not unrestricted ambient I/O or nonterminating loops.

---

## 6. Minimal example: Karplus–Strong as a field

```mus
@field ks {
  control f0  : Hz[20..9000] = 110Hz
  control t60 : s[.05..20]   = 2.5s

  state loop : delay(
    length = sr / $f0,
    metric = unit,
    loss = t60($t60)
  )

  source pluck -> loop.in : triangle(pos=.13) + noise(seed=content)
  edge loop.out -> loop.in : average(.5,.5)
  pickup out <- loop.out

  assert energy.propagation == preserve
  assert energy.loss <= 0
}
```

This is intentionally more explicit than `synth=pluck`. It is the scientific object from which a compact preset may be derived.

---

## 7. Declaring graph families

### 7.1 Arrays

```mus
state strings[0..5] : string(
  f0 = [E2,A2,D3,G3,B3,E4],
  t60 = 2.6s,
  stiff = .08
)
```

Array-valued arguments zip by index. Scalars broadcast.

### 7.2 Comprehensions

```mus
state virtual[k in 0..<18] : delay(
  f0 = base * mode_frequency(@lattice, k),
  t60 = 2.4s * (1 + .04*k)
)
```

Comprehensions are finite and deterministic.

### 7.3 Structural sugar

```mus
ring room[24] : delay(
  length = primes(37..241) * sample,
  loss = band_t60(@room_decay)
)
```

`ring` expands to state blocks, successor edges, stable member IDs, and an explicit cycle. The expansion appears in the compile receipt and can be reduced back to the sugar when unchanged.

Other candidate sugars:

```text
chain
star
mesh
tree
clique
bipartite
modal_bank
waveguide
fdn
sdn_room
```

Sugar never bypasses contracts.

---

## 8. Ports and connections

```mus
port bridge.in[6]  : wave(impedance=@string_Z)
port bridge.body   : wave(impedance=@body_Z)
port room.src      : wave(impedance=@air_Z)
port out           : observation
```

Connections use direction visibly:

```mus
edge strings[*].bridge <-> bridge.in[*]
edge bridge.body <-> body.port
edge body.radiation -> room.src
edge room.mic -> out
```

- `<->` declares bidirectional interconnection;
- `->` declares directed propagation or a source/pickup relation;
- `~>` may be used as sugar for an explicitly lossy boundary, but the loss operator remains named in the lowered graph.

A directed edge is not automatically nonreciprocal physics. Its operator contract determines whether it is a one-way observation, active element, or passive directed realization.

---

## 9. Energy metrics

```mus
metric @M {
  strings[*] = impedance(@string_Z)
  body[*]    = modal_mass(@body_profile)
  room[*]    = normalized_wave
}
```

Or locally:

```mus
state b3 : mode(f=221Hz, mass=.014kg, metric=physical)
```

Scientific mode refuses executable state without a metric or a declared normalization profile.

Weighted scattering is concise:

```mus
factor bridge_mix : rotate(
  strings[*].bridge,
  body[*].momentum,
  theta = $body * @coupling_profile,
  metric = @M
)
```

The compiler lowers this to metric-normalize -> Euclidean sparse rotation -> denormalize.

---

## 10. Controls and fields

A control is a typed externally addressable value.

```mus
control chirality : ratio[-1..1] = .72
control couple    : rad[0.. .48] = .11rad
control orbit     : Hz[0..20]    = .31Hz
control depth     : ratio[0..1]  = .62
```

A signal is a derived runtime value.

```mus
signal phase(t) = tau * $orbit * t
signal local_energy[i] = energy(strings[i])
signal gradient[i] =
  tanh((local_energy[prev(i)] - local_energy[next(i)]) /
       max(sum(local_energy), 1e-14eu))
```

A field varies over graph position and time.

```mus
signal theta[i,t] =
  $couple
  * (1 + $depth * sin(phase(t) + tau*i/count(strings)))
  * (1 + .72*$curvature*gradient[i])
```

The type checker distinguishes compile-time selectors, control-rate signals, and audio-rate signals.

---

## 11. Sparse factors and order

```mus
factor F[i in ring(strings)] :
  rotate(strings[i], strings[next(i)], theta=theta[i,t])

path forward  = F[0] >> F[1] >> ... >> F[last]
path backward = F[last] >> ... >> F[1] >> F[0]

path weave =
  weight((1+$chirality)/2) * @forward
  >>
  weight((1-$chirality)/2) * @backward
```

The ellipsis is legal only over a statically finite ordered selector and expands canonically.

A more explicit form is available:

```mus
path weave = sequence(F[*], order=index.asc)
          >> sequence(F[*], order=index.desc)
```

Changing path order is an edit to the operator graph, not merely a value change.

---

## 12. Closed paths and ordered scattering memory

```mus
factor A(a) : rotate(s0,s1, theta=a)
factor B(b) : rotate(s1,s2, theta=b)

path commutator(a=.31rad, b=-.47rad) =
  A(a) >> B(b) >> A(-a) >> B(-b)

assert @commutator preserves energy @M
observe defect = norm(operator(@commutator) - identity)
```

A time-domain gesture may drive a loop rather than instantiate one composite operator:

```mus
gesture control_loop dur=2q {
  0/4..1/4 : A.theta 0rad -> .31rad
  1/4..2/4 : B.theta 0rad -> -.47rad
  2/4..3/4 : A.theta .31rad -> 0rad
  3/4..4/4 : B.theta -.47rad -> 0rad
}
```

The receipt records both the control trajectory and the executed factor schedule.

---

## 13. State-dependent topology and transitions

Topology edits are named transitions.

```mus
transition open_room : @closed_room -> @open_room {
  map state by transport(
    raw = bandlimited_resample,
    policy = neutral,
    metric = @M
  )
  new room.extra[*] = zero
}
```

Shrinking must name a policy:

```mus
transition remove_modes : @rich_body -> @small_body {
  remove body[where participation < .01]
  discarded_state -> radiation.tail
}
```

Allowed policies include:

```text
neutral
physical(profile=...)
budget(max_step=..., max_total=...)
radiate(port=...)
dissipate(stage=...)
retire(t60=...)
reject
legacy
```

No topology-changing syntax has an implicit state policy.

---

## 14. Whole-graph selectors and transformations

This is the main superhuman ergonomics surface.

### 14.1 Static selection

```mus
set edge[region=room & kind=propagation].loss *= 1.08
set state[kind=mode & f>2kHz].t60 *= .7
set factor[acts_on any strings[*]].theta *= .9
```

### 14.2 Relational selection

```mus
set edge[from in descendants(@bridge, max_hops=3)].loss += .01
set state[in_cycle & cycle.length>8].tag += "late-field"
set factor[between(region=instrument, region=room)].work_budget = .02eu
```

### 14.3 Transform definitions

```mus
transform mirror_path(field) {
  reverse path[field/**]
  set control[field/chirality] *= -1
}

variant left  = @thread
variant right = mirror_path(@thread)
```

### 14.4 Parametric transforms

```mus
transform scale_body(field, ratio) {
  set state[field/body/**].f /= ratio
  set metric[field/body/**] = remap(@M, body_scale=ratio)
}
```

Transforms are pure graph-to-graph functions. Their expanded operations and source snapshot are receipted.

---

## 15. Score binding

A track can bind to a field realization:

```mus
# instruments:
#   g = Ariadne guitar (treble, field=@thread, source=pluck, pickup=out)
```

Event parameters may select paths, controls, pickups, or transitions:

```mus
g 1: E3h[path=@forward,couple=.08rad]
g 2: E3h[path=@backward,couple=.08rad]
g 3: E3h[path=@commutator(a=.21rad,b=.34rad)]
g 4: B2h[gesture=@control_loop,retune=neutral]
```

Score-time automation can target the field globally:

```mus
@automate b9..b16 {
  @thread/chirality : .92 -> -.92 ease=smooth
  @thread/room.send : .1 -> .8
}
```

Event and global automation lower to one control timeline. Conflicts are represented as contested operations rather than silently ordered by file accident.

---

## 16. Assertions and contracts

```mus
assert energy(@thread/scattering) == preserve
assert loss(@thread/damping) >= 0eu
assert abs(ledger.balance_residual) < 1e-9eu
assert cumulative(control_work) <= .05eu
assert no algebraic_loop unless solver=@block_newton
assert every(state) has metric
assert every(topology_transition) has transport_policy
assert random.seed is explicit
```

Assertions may be:

- compile-time structural checks;
- algebraic proofs over known operators;
- property tests over a declared domain;
- render-time monitors;
- research claims linked to evidence.

The receipt states which kind was performed. A sampled test is never labeled a proof.

---

## 17. Observations and probes

```mus
observe {
  energy by region every 256sample
  control_work by parameter
  spectrum(out) over sustain
  path_defect(@commutator)
  graph.spectral_dimension scale=100..4kHz
}
```

A reproducible probe packages fixtures and stop conditions:

```mus
probe bend_gap {
  fixture note = A2h
  variant base = { gliss=1, retune=legacy }
  variant bend = { gliss=3/2, retune=legacy }

  measure internal_peak, cumulative(control_work), ledger.residual
  expect legacy.bend.internal_peak > legacy.base.internal_peak
  archive audio, trace, receipt
}
```

A repaired probe:

```mus
probe neutral_bend {
  sweep f0 in [82.4,110,220,440,880,1318.5]Hz
  sweep interval in [1/2,2/3,1,3/2,2]
  set retune=neutral

  expect abs(cumulative(control_work)) < 1e-8eu
  expect abs(ledger.residual) < 1e-9eu
}
```

---

## 18. Queries

Queries inspect the authored or realized graph.

```mus
query cycles(@room) where length>4 & path_defect>.1
query paths(from=strings[*], to=out, max_hops=12)
query factors where not proven(metric_orthogonal)
query transitions where policy=legacy
query modes where participation(out)<.01 & energy>.1eu
```

A query may return a view, selector, report, or artifact. It does not mutate the graph.

SPARQL remains available at the RDF boundary; MUS-F queries cover common acoustic and operator concepts compactly.

---

## 19. Inverse design

A `solve` block is a durable optimization question.

```mus
solve room_in_e_minor {
  base = @thread.room

  target modes ~= [E2,B2,E3,G3,B3] weight=2
  target t60 = curve[
    (125Hz,2.8s),
    (1kHz,2.2s),
    (8kHz,.9s)
  ]
  target echo_pitch_drift = -21.5c / bounce
  target path_defect in .08.. .18

  vary room[*].length in 10..300ms
  vary factor[region=room].theta in -.4.. .4rad
  vary pickup.room[*] in -1..1

  subject {
    energy.scattering == preserve
    cumulative(control_work) <= .02eu
    ledger.residual < 1e-8eu
    state.count <= 128
  }

  method = hybrid(
    structure=@kg_ultra,
    continuous=adam,
    refine=cmaes
  )

  budget renders=512, wall=2h, seed=4815162342
}
```

The method declaration is optional. A solve task remains meaningful if KG-ULTRA is absent; another structure proposer may be used.

Results are variants with full provenance, not in-place magical edits.

---

## 20. Evidence and uncertainty

Measured or inferred values can name evidence.

```mus
state body[3] : mode(
  f = 221Hz ± 2Hz @observation("urn:..."),
  t60 = .82s @fit("sha256:..."),
  mass = unknown
)
```

Unknown, refused, estimated, and asserted values are distinct:

```text
unknown
refused(reason=uncalibrated)
estimate(value, uncertainty, method)
asserted(value, agent)
measured(value, observation)
```

The DSP compiler may require a concrete realization. A realization policy samples, bounds, substitutes, or refuses uncertain values and records the choice.

---

## 21. Direct operator escape hatch

Some research cannot be expressed initially through high-level graph sugar.

```mus
foreign operator Q {
  kind = sparse_matrix
  artifact = artifact("sha256:...")
  shape = [24,24]
  contract = metric_orthogonal(@M)
  proof = artifact("sha256:...")
}
```

Or:

```mus
operator Q(theta) = exp(skew {
  (0,1): theta
  (1,2): .7*theta
})
```

Foreign code or matrices are not trusted merely because they declare a contract. They must pass the specified verifier or remain `unchecked`, which scientific mode refuses inside a feedback cycle.

---

## 22. Canonical lowering

```text
MUS-F text
  -> parsed AST
  -> bounded macro/comprehension expansion
  -> typed graph operations
  -> op log
  -> FieldGraph projection
  -> contract validation
  -> numeric field IR
  -> executable schedule
  -> RDF/evidence projection
  -> receipts
```

Important laws:

- expansion is deterministic;
- selectors are stable-ID ordered;
- units normalize canonically;
- operator order is preserved;
- aliases never become identity;
- every executable construct has a numeric lowering;
- every non-executable construct is marked as annotation/query/evidence;
- reduction fails loudly when it cannot reproduce semantics.

---

## 23. Modes

### Performance mode

Allows curated defaults and compact presets. Receipts still name them.

### Research mode

Requires:

- explicit metric or normalization;
- explicit random seeds;
- explicit transport policy;
- explicit units;
- contract verification;
- no unchecked feedback operator;
- versioned artifacts;
- complete work ledger.

A paper fixture uses research mode.

---

## 24. Complete example: one instrument and room

```mus
# mus-field: 0.1

@field labyrinth mode=research {
  region instrument {
    control couple : rad[0.. .48] = .11rad
    control chirality : ratio[-1..1] = .72
    control orbit : Hz[0..20] = .31Hz
    control depth : ratio[0..1] = .62
    control curvature : ratio[0..1] = .28

    state strings[0..10] : delay(
      f0 = @operator_lattice(base=E2, dimension=1.35),
      t60 = 2.6s,
      metric = normalized_wave
    )

    state body[0..9] : mode(profile=artifact("sha256:body-profile"))

    signal phase(t) = tau*$orbit*t
    signal grad[i] =
      tanh((energy(strings[prev(i)]) - energy(strings[next(i)])) /
           max(sum(energy(strings[*])),1e-14eu))

    factor S[i in ring(strings)] : rotate(
      strings[i],
      strings[next(i)],
      theta=$couple
        * (1+$depth*sin(phase(t)+tau*i/count(strings)))
        * (1+.72*$curvature*grad[i])
    )

    path forward = sequence(S[*], order=index.asc)
    path backward = sequence(S[*], order=index.desc)
    path weave = @forward >> @backward

    factor B[i in strings, j in body] : weighted_rotate(
      strings[i], body[j].momentum,
      theta=@body_profile.coupling[j],
      metric=@M
    )

    source pluck -> strings[played].in
    port bridge <- strings[*].out
  }

  region room {
    ring cell[24] : delay(
      length=primes(503..1429)*sample,
      loss=band_t60(@room_decay),
      metric=normalized_wave
    )

    factor R[i in ring(cell)] :
      rotate(cell[i],cell[next(i)],theta=@room_theta[i])

    path circulation = sequence(R[*],order=@room_order)
    pickup mic <- sum(cell[*],weights=@mic_pattern)
  }

  edge instrument/bridge <-> room/cell[0] :
    weighted_rotate(theta=.03rad,metric=@M)

  pickup out <- instrument/body.radiation + room/mic

  metric @M {
    instrument/strings[*] = normalized_wave
    instrument/body[*] = @body_metric
    room/cell[*] = normalized_wave
  }

  assert every(state) has metric
  assert every(factor) metric_orthogonal @M
  assert every(loss) contractive @M
  assert every(transition) has transport_policy
  observe energy by region every 256sample
  observe control_work by control
}
```

This is verbose enough to be a scientific object and compact enough for an LLM to hold, compare, and transform as one coherent thing.

---

## 25. Superhuman ergonomics checklist

A superhuman authoring mind does not need more tiny knobs. It needs leverage.

MUS-F therefore must support:

- stable references across a large graph;
- selectors over types, relations, regions, cycles, paths, evidence, and runtime state;
- vectorized edits;
- pure reusable transforms;
- graph variants rather than destructive mutation;
- explicit composition order;
- dimensional types;
- derived fields over time and topology;
- declarative goals and constraints;
- introspection and queries;
- deterministic reductions;
- receipts that explain what actually ran.

The language should let an agent say “reverse every room cycle that shares a bridge-connected mode above 2 kHz, preserve the metric, cap total actuator work, and render matched variants” as one auditable transformation—not as hundreds of fragile parameter edits.

---

## 26. Initial implementation subset

Do not attempt the whole language at once.

### MUS-F v0

Implement:

- companion `.musf` files;
- `field`, `region`, `state`, `factor`, `metric`, `control`, `path`, `pickup`;
- arrays and finite comprehensions;
- typed units;
- `>>` ordered composition;
- Givens and weighted Givens factors;
- static selectors;
- `assert` for metric orthogonality and contraction;
- `observe` for the work ledger;
- score binding by `field=`, `path=`, and control overrides;
- canonical JSON IR and text reduction.

### MUS-F v0.1

Add:

- within-note gestures;
- topology transitions and transport policies;
- probes and variants;
- queries;
- operator-derived graph modes.

### MUS-F v0.2

Add:

- transforms;
- inverse-design blocks;
- RDF projection;
- KG-ULTRA candidate hooks;
- uncertainty/evidence syntax.

The parser and IR must reserve the later forms now so that v0 does not paint the language into an event-parameter corner.
