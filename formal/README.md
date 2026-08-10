# mus-formal — kernel-checked receipts

Lean 4 (v4.31.0, pure-core, **zero dependencies** — the Garden
`ontology-to-lean` convention: `lake build` fetches nothing). Build:

    ~/.elan/bin/lake build      # from this directory

**The two-layer law.** Lean proves the *model*; the Rust tests police
the *bytes*. A theorem here never substitutes for an invariant or golden
test there — it says the design cannot be wrong, while the tests say the
floats and the code aren't. No sorries, ever: an admitted proof is worse
than none.

## Modules ↔ implementation

| Lean | proves | Rust counterpart (tests policing the same law) |
|---|---|---|
| `MusFormal.Oplog.canon_converges` | replicas holding the same ops replay **identically**, any arrival order/duplication | `mus-oplog` union merge + `(lamport, actor, seq, id)` total order; merge law tests |
| `MusFormal.Oplog.merge_{comm,idem,assoc}` | the CRDT join-semilattice corollaries | same |
| `MusFormal.Holonomy.network_silences` | energy-preserving junctions + one lossy edge ⇒ silence within `energy x` circulations (quantized skeleton of *contractive holonomy*) | `mus-dsp` pluck/braid boundedness invariants |

The `Ops` class models the op-id order abstractly; the Rust tuple order
is an instance. The `Energized`/`Preserving`/`Lossy` triple is the
discrete shadow of "Givens junctions are isometries; every loop crosses
a loss" — the analytic body (operator norms, fractional harmonic
ladders on ℝ) arrives with the mathematician's holonomy package and a
deliberate mathlib upgrade, as its own reviewed step.
