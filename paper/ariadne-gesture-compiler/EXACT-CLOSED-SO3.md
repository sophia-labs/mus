# Exact closed-control synthesis in `SO(3)`

**Status:** exact constructive addendum to `THEORY.md`  
**Supersedes:** treating the three-rectangle nonlinear solver as the reachability argument  
**Retains:** that solver as an optional cost-refinement backend

## Result

Every target `Q in SO(3)` can be realized by a closed control word on any connected three-mode Givens graph. For a nonidentity target, the reference compiler emits twelve authored-edge Givens gates. Every scalar edge-control integral returns exactly to zero, every factor is orthogonal, and the compiled word reconstructs `Q` to floating-point precision.

This is a project-specific constructive instance of the older general fact, due to Gotô, that every element of a compact connected semisimple Lie group is a commutator. The general commutator theorem is prior art. The new engineering object here is its explicit acoustic lowering, closure receipt, and exact inverse design law for the balanced local macro.

## Balanced local commutator

Let

```text
A0(t) = R01(t)
B0(t) = R12(t)
C0(t) = A0(t) B0(t) A0(-t) B0(-t).
```

The work-and-holonomy preprint derives, for `x = sin(t/2)^2`,

```text
sin(phi/2)^2 = 4 x^2 (1 - x^2),
```

where `phi` is the principal rotation angle of `C0(t)`. On the principal branch,

```text
t(phi) = 2 asin(sqrt(sin(phi/4))),   0 <= phi <= pi.
```

Thus one balanced local commutator realizes every principal angle in `SO(3)`.

## Axis conjugation

Let the target have axis `n` and principal angle `phi`. Compute `t(phi)` and the axis `n0` of `C0(t)`. Choose any `S in SO(3)` such that

```text
S n0 = n.
```

Define

```text
A = S A0(t) S^-1
B = S B0(t) S^-1.
```

Then

```text
A B A^-1 B^-1
  = S C0(t) S^-1
  = Q.
```

The visible macro controls close because each of `A` and `B` appears once with its inverse.

## Lowering to an authored edge graph

On a connected three-mode graph, compile each dense macro rotation `A` and `B` with the exact tree-QR compiler. Each macro uses three graph-edge Givens gates. Under the reference executor's left-action convention, execute

```text
B^-1, A^-1, B, A.
```

This yields twelve edge gates. Because the inverse schedules are exact reversals with negated angles, the sum of angles on every authored edge is exactly zero—not merely numerically small.

The identity target compiles to the empty word.

## Numerical receipt

The deterministic float64 oracle compiled 1,000 random Haar targets in `SO(3)` on the path graph `0-1-2`:

```text
factor-count mismatches             0
maximum Frobenius endpoint error    2.469154477134275e-15
maximum principal-angle error       1.72145910194806e-15 rad
maximum per-edge closure residual   0.0
```

The three named targets at 37, 103, and 171 degrees also closed with twelve gates and endpoint errors below `7.2e-16` Frobenius.

## What this does and does not prove

It proves exact reachability and gives a deterministic compiler for closed `SO(3)` effects. It does not solve the optimal closed-loop problem. The conjugator `S`, its graph factorization, equivalent commutator decompositions, friction metric, duration, velocity limits, and robustness constraints still change gesture cost.

For `SO(n)`, `n >= 3`, Gotô's theorem supplies existence of a one-commutator representation, while the connected-edge tree compiler supplies exact lowering of any chosen macro factors. A constructive, cost-aware algorithm for selecting those macro factors in general dimension remains open in this packet.
