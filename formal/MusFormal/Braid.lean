/-!
# An exact signed-axis braid witness

Quarter-turn Givens rotations on adjacent coordinate planes do not commute,
but they satisfy the braid relation.  The continuous matrices live in SO(3);
this finite model records their exact action on the six signed coordinate axes.
It is a quotient representation of the braid relation, not by itself a proof
of topological protection.
-/

namespace MusFormal.Braid

inductive Axis
  | a
  | b
  | c
  deriving DecidableEq, Repr

structure SignedAxis where
  axis : Axis
  negative : Bool
  deriving DecidableEq, Repr

/-- Quarter turn in the `(a,b)` plane:
    `a ↦ b`, `b ↦ -a`, `c ↦ c`. -/
def qAB : SignedAxis → SignedAxis
  | ⟨.a, sign⟩ => ⟨.b, sign⟩
  | ⟨.b, sign⟩ => ⟨.a, !sign⟩
  | ⟨.c, sign⟩ => ⟨.c, sign⟩

/-- Quarter turn in the `(b,c)` plane:
    `b ↦ c`, `c ↦ -b`, `a ↦ a`. -/
def qBC : SignedAxis → SignedAxis
  | ⟨.a, sign⟩ => ⟨.a, sign⟩
  | ⟨.b, sign⟩ => ⟨.c, sign⟩
  | ⟨.c, sign⟩ => ⟨.b, !sign⟩

/-- Adjacent quarter turns satisfy `ABA = BAB` exactly. -/
theorem braid_relation (state : SignedAxis) :
    qAB (qBC (qAB state)) = qBC (qAB (qBC state)) := by
  cases state with
  | mk axis sign =>
      cases axis <;> cases sign <;> rfl

/-- Yet the two generators do not commute. -/
theorem generators_noncommute :
    qAB (qBC ⟨.a, false⟩) ≠ qBC (qAB ⟨.a, false⟩) := by
  decide

/-- Four applications of either signed quarter turn return every axis. -/
theorem qAB_four (state : SignedAxis) :
    qAB (qAB (qAB (qAB state))) = state := by
  cases state with
  | mk axis sign =>
      cases axis <;> cases sign <;> rfl

theorem qBC_four (state : SignedAxis) :
    qBC (qBC (qBC (qBC state))) = state := by
  cases state with
  | mk axis sign =>
      cases axis <;> cases sign <;> rfl

end MusFormal.Braid
