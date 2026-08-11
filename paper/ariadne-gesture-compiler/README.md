# Ariadne gesture compiler — round 3 research packet

The work-and-holonomy preprint provides a forward semantics:

```text
control path -> transport -> work / loss / monodromy receipt
```

This packet begins the converse:

```text
target effect + graph + budgets -> certified control path
```

## What is implemented

`reference/ariadne_gesture/` contains a deterministic float64 oracle for:

- exact `SO(n)` synthesis on any connected edge graph;
- graph and mixed work/rotation Lie-closure ranks;
- exact constant-speed scheduling for a fixed factor word;
- spanning-tree and leaf-order cost search;
- closed rectangular-loop synthesis for `SO(3)`;
- deformation-budget and factor-order work bounds;
- an Abelian Rice–Mele topological pump;
- a constant-gap non-Abelian Wilson-loop model;
- exact lowering of real skew propagators to graph-edge Givens schedules.

`reference/run_experiments.py` regenerates `reference/results.json` and fails closed on the theorem-shaped numerical invariants.

```bash
python -m pip install numpy scipy
cd paper/ariadne-gesture-compiler/reference
python run_experiments.py
```

A smaller CI run is:

```bash
python run_experiments.py --quick --no-write
```

## Formal core

The branch adds three pure-core Lean modules:

- `formal/MusFormal/Reachability.lean`
- `formal/MusFormal/PassivityTypes.lean`
- `formal/MusFormal/Braid.lean`

They prove the graph/bracket skeleton of reachability, a quantized passivity effect soundness theorem, and an exact noncommuting braid-relation witness. They intentionally do not pretend to formalize real SPD polar decomposition or numerical analysis yet.

## Load-bearing results

1. A connected `n`-vertex edge graph can compile every `SO(n)` target in exactly `n(n-1)/2` edge Givens gates. The implementation reproduces 360 random targets through dimension 16 with worst Frobenius error `2.19e-15`.
2. Adding one reversible traceless anisotropic actuator to the connected rotation controls generates `sl(n,R)` at the Lie-algebra level; adding isotropic scale generates `gl(n,R)`. The operator-level polar target becomes all volume-neutral, then all positive-determinant, work–holonomy pairs.
3. For a fixed word, the exact minimum quadratic gesture cost is `L^2 / duration`, reached by constant thermodynamic speed. A 192-candidate graph search reduced one eight-mode target's cost by 52.0% without changing target or gate count.
4. Three closed rectangular commutator loops compiled 40 random `SO(3)` targets with no endpoint error above `1e-8` radians; the worst was `2.85e-13` radians. This is numerical evidence, not a coverage theorem.
5. The topological work now has two explicit halves: a robust Chern-one pump and a noncommuting constant-gap rank-two Wilson bundle. The first is protected but Abelian; the second is non-Abelian but geometric rather than protected.

## Files

- `THEORY.md` — theorem statements, proofs, bounds, empirical receipts, and novelty boundary.
- `IMPLEMENTATION-HANDOFF.md` — a commit-level plan for the in-codebase agent.
- `../../SPEC-GESTURE.md` — proposed MUS-F inverse-gesture surface and receipt schema.
- `reference/` — executable scientific computing and full deterministic results.

## Honest boundary

Restricted-rotation QR, controllability on Lie groups, thermodynamic length, holonomic quantum computation, and Thouless pumping are established fields. The candidate contribution is their integration into a typed, work-accounted, instrument–body–space acoustic compiler. The existing room proposal remains load-bearing: the room is a long-cycle region of the same graph, not a downstream reverb.
