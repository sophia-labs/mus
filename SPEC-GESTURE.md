# MUS-F Gesture — inverse control-path specification

**Status:** proposed companion surface for `SPEC-FIELD.md`  
**Principle:** a composer or agent specifies the acoustic effect and constraints; the compiler chooses a certified path.

## 1. Design goals

The surface must let a superhuman author manipulate string, body, and space as one graph without writing hundreds of actuator events. It must expose:

- target monodromy or deformation;
- endpoint and closed-control requirements;
- duration;
- work, loss, radiation, and deformation budgets;
- a gesture metric;
- robustness requirements;
- allowed graph regions and controls;
- proof and receipt demands.

A compiled gesture is an immutable value that can be inspected, replayed, transformed, and compared.

## 2. Minimal syntax

### 2.1 Open-path rotation target

```mus
@gesture rotate_field = achieve {
  on: @ariadne.field
  target: rotation(axis=[.31, -.72, .62], angle=37deg)
  duration: 2s

  use: edges(@ariadne.instrument | @ariadne.body | @ariadne.space)
  minimize: thermodynamic_length(metric=@metrics.hand_and_room)

  require {
    endpoint.error <= 1e-8rad
    work.abs <= 1e-9J
    controls.speed <= @limits.performance
    ledger.residual <= 1e-10J
  }
}
```

### 2.2 Closed visible controls

```mus
@gesture thread_returns = achieve {
  on: @ariadne.field
  target: holonomy(rotation(axis=@modes.shadow, angle=15deg))
  duration: 1.5s

  path_class: closed.controls
  basis: commutator(edges=[@e01, @e12], loops<=4)

  minimize: weighted {
    1.0 * thermodynamic_length(metric=@metrics.hand)
    0.2 * control.acceleration
    3.0 * sensitivity(parameter_noise=0.5%)
  }

  require {
    controls.start == controls.end
    deformation.radius_sum <= 0.01
    work.abs <= 1e-8J
  }
}
```

### 2.3 Work–holonomy pair

```mus
@gesture pump_and_turn = achieve {
  target: polar {
    isometry: rotation(subspace=@body.low, angle=28deg)
    deformation: stretch(
      along=@room.mode[2],
      log_gain=0.12,
      volume_neutral=true
    )
  }

  duration: 4s
  use: controls(signed=true)

  require {
    energy.ratio <= exp(2 * 0.30)
    deformation.radius_sum <= 0.30
    radiation.total <= -18dBJ
  }
}
```

### 2.4 Space as an instrument region

```mus
@gesture fold_the_hall = achieve {
  on: @ariadne.field

  transform {
    body.scale: 1.0 -> 0.84 -> 1.0
    space.lengths[@north,*]: 1.0 -> 1.31 -> 1.0
    coupling(@bridge, @space): reciprocal -> gyre(clockwise) -> reciprocal
  }

  target {
    late_field.rotation: 21.5cent per bounce
    return_to: @initial.configuration
  }

  minimize: thermodynamic_length(metric=@metrics.architecture)
  require: work.total within [-0.02J, 0.02J]
}
```

The room controls participate in the same path, metric, work ledger, and monodromy as the body controls.

### 2.5 Protected gesture

```mus
@gesture one_quantum = achieve protected {
  family: @rice_mele_space_ring
  invariant: chern == 1
  transport: polarization_winding == 1
  cycles: 1

  tolerate {
    timing_jitter <= 8%
    coupling_error <= 2%
    path_warp <= @smooth.class_C1
  }

  require {
    spectral_gap >= 0.2
    work.abs <= 1e-7J
    invariant.recomputed == 1
  }
}
```

The compiler must refuse `protected` if only a geometric Wilson loop has been demonstrated.

## 3. Target forms

```text
identity
rotation(axis, angle)
rotation(matrix)
subspace_rotation(subspace, principal_angles)
holonomy(conjugacy_class | eigenphases | trace)
polar { isometry, deformation }
work { state | distribution, interval }
spectrum(target)
decay(target)
spatial_drift(cents_per_bounce)
topological { invariant, value }
```

A target may be partial. Unspecified degrees of freedom become compiler freedom and must be listed in the receipt.

## 4. Path classes

```text
open
closed.controls
closed.configuration
neutral
physical(actuator_model)
budgeted
commutator(generator_family, depth)
geodesic(metric)
protected(family, invariant)
```

`closed.controls` means scalar actuator coordinates return. `closed.configuration` additionally requires graph, metric, topology, source, pickup, and boundary parameters to return. Neither condition implies zero work.

## 5. Cost language

```text
thermodynamic_length(metric)
quadratic_effort(metric)
control.velocity
control.acceleration
factor_count
wall_clock_compile_time
sensitivity(parameter_noise, timing_noise)
artifact(transient, aliasing, zipper, pitch_error)
perceptual(model, descriptor_set)
```

Costs may be:

- lexicographic;
- weighted sums;
- Pareto fronts;
- hard constraints.

The compiler must report units and normalization. A perceptual cost is model evidence, not a physical law.

## 6. Reachability report

Before optimization, the compiler emits:

```json
{
  "components": [[0,1,2,3,4]],
  "rotation_group": "SO(5)",
  "rotation_lie_rank": 10,
  "deformation_class": "SL(5,R)",
  "deformation_lie_rank": 24,
  "hypotheses": {
    "graph_connected": true,
    "anisotropic_actuator_signed": true,
    "isotropic_actuator_signed": false
  },
  "target_reachable_operator_level": true,
  "caveats": ["velocity bounds not yet considered"]
}
```

Static theorem results, numerical rank tests, and heuristic inferences must be separate fields.

## 7. Compiled gesture value

```mus
@compiled thread_returns : Gesture = receipt("sha256:...") {
  graph: @ariadne.field@sha256:...
  target: @target@sha256:...
  backend: commutator-so3/v0
  factors: 12
  duration: 1.5s
  length: 3.861528
  cost.quadratic: 9.941867
  endpoint.error: 4.32e-14rad
  work.residual: 1.33e-15J
  controls.closed: true
}
```

The full factor word may be folded in ordinary notation and expanded on demand.

## 8. Receipt schema

Required sections:

```text
identity
  gesture id, compiler digest, graph digest, target digest

reachability
  connected components, generated algebra/group, hypotheses, obstructions

path
  control points, factors, angles, times, topology transitions

metric
  energy metric digest, friction metric digest, coordinate normalization

endpoint
  requested and realized polar factors, distance, basis-invariant observables

energy
  source work, control work, loss, radiation, output, residual

cost
  thermodynamic length, quadratic effort, factor count, robustness score

proof
  theorem IDs, Lean build digest, numeric oracle version, tolerances

provenance
  optimizer seeds, candidate count, accepted/rejected alternatives
```

## 9. Compiler phases

1. Resolve graph, units, stable identities, and metrics.
2. Run static reachability and obstruction analysis.
3. Select an exact or approximate synthesis backend.
4. Generate candidate factor words.
5. Optimize geometry and timing.
6. Lower to sparse executable operators.
7. Replay in float64 and production precision.
8. Type-check work/rank effects.
9. Evaluate robustness and perceptual probes.
10. Emit immutable gesture and receipt.

## 10. Backend selection

```text
exact-tree-qr
  open SO(n) target, connected graph, continuous edge angles

exact-commutator-so3
  exact same-endpoint SO(3), conjugated balanced commutator, 12 edge gates

closed-rectangles-so3
  cost-refined same-endpoint SO(3), experimental numerical solver

subriemannian-shooting
  bounded continuous controls, future

mixed-polar
  work + holonomy, future

protected-pump
  invariant-constrained family only
```

A backend may return `Unreachable`, `Unsupported`, `SolverFailed`, or `Certified`. Approximate success never silently becomes certified success.

## 11. Type/effect rules

Conceptual judgments:

```text
Gamma |- op : State(M0,n0) -[effect]-> State(M1,n1)
```

Effects compose linearly:

```text
source + control = delta_stored + loss + radiation + output + residual
```

Rank contraction requires exactly one disposition for the discarded subspace. The surface syntax:

```mus
remove @room.mode[7] using radiate(@out.rear)
remove @body.mode[3] using dissipate(@loss.felt)
remove @string.course[11] using retire(t60=180ms)
```

There is no unqualified `remove`.

## 12. Agent ergonomics

The intended agent interaction is specification-level:

```mus
find 8 diverse closed gestures that rotate @space.late by 12–18deg,
keep total work below 0.01J,
prefer paths robust to 1% wall-coupling error,
and return a Pareto set over length and spectral drift.
```

The compiler, not the agent's prose, owns reachability, operator replay, energy accounting, and acceptance tolerances.
