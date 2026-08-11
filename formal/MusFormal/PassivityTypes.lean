/-!
# Passivity as type soundness: a quantized linear-resource core

A production MUS-F type system will track real-valued energy metrics, ports,
state transports, and tolerances.  This pure-core model captures the crucial
resource discipline with natural-number energy quanta:

* a neutral operation preserves the account;
* a source must declare every supplied quantum;
* disappearing state must be handled by radiation, dissipation, or retirement;
* sequential composition adds receipts.

There is intentionally no constructor for an unaccounted energy injection or
silent state drop.
-/

namespace MusFormal.PassivityTypes

/-- Every removed quantum must name a handler. -/
inductive Disposal
  | radiation
  | dissipation
  | retirement
  deriving DecidableEq, Repr

/-- `Patch before after supplied disposed` is a well-typed acoustic operation.
    The indices are the complete resource effect of the operation. -/
inductive Patch : Nat → Nat → Nat → Nat → Type
  | neutral (energy : Nat) : Patch energy energy 0 0
  | supply (energy amount : Nat) : Patch energy (energy + amount) amount 0
  | dispose (handler : Disposal) (after amount : Nat) :
      Patch (after + amount) after 0 amount
  | seq {before middle after supplied₁ disposed₁ supplied₂ disposed₂ : Nat}
      (first : Patch before middle supplied₁ disposed₁)
      (second : Patch middle after supplied₂ disposed₂) :
      Patch before after (supplied₁ + supplied₂) (disposed₁ + disposed₂)

/-- Every well-typed patch closes its quantized energy account exactly. -/
theorem balance :
    ∀ {before after supplied disposed : Nat},
      Patch before after supplied disposed →
      after + disposed = before + supplied := by
  intro before after supplied disposed patch
  induction patch with
  | neutral energy => rfl
  | supply energy amount => rfl
  | dispose handler after amount =>
      simp [Nat.add_comm]
  | @seq before middle after supplied₁ disposed₁ supplied₂ disposed₂ first second ihFirst ihSecond =>
      calc
        after + (disposed₁ + disposed₂)
            = (after + disposed₂) + disposed₁ := by
                rw [Nat.add_comm disposed₁ disposed₂, ← Nat.add_assoc]
        _ = (middle + supplied₂) + disposed₁ := by rw [ihSecond]
        _ = (middle + disposed₁) + supplied₂ := by
                rw [Nat.add_assoc, Nat.add_comm supplied₂ disposed₁, ← Nat.add_assoc]
        _ = (before + supplied₁) + supplied₂ := by rw [ihFirst]
        _ = before + (supplied₁ + supplied₂) := by rw [Nat.add_assoc]

/-- An unforced typed patch cannot finish with more energy than it started
    with.  Any decrease is exactly its declared disposal. -/
theorem unforced_nonincreasing
    {before after disposed : Nat}
    (patch : Patch before after 0 disposed) : after ≤ before := by
  have closes : after + disposed = before := by
    have h := balance patch
    simpa using h
  have grows : after ≤ after + disposed := Nat.le_add_right after disposed
  rw [closes] at grows
  exact grows

/-- A closed, unforced, zero-disposal operation preserves the exact account. -/
theorem closed_neutral
    {before after : Nat}
    (patch : Patch before after 0 0) : after = before := by
  have h := balance patch
  simpa using h

/-- Example: supply three quanta, then radiate two. -/
def examplePatch : Patch 5 6 3 2 :=
  Patch.seq (Patch.supply 5 3) (Patch.dispose .radiation 6 2)

example : 6 + 2 = 5 + 3 := balance examplePatch

end MusFormal.PassivityTypes
