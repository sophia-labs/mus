/-!
# Holonomy loops, quantized: silence is inevitable

The mathematician's core claim — *contractive holonomy delay network* —
splits into an algebraic skeleton and an analytic body. The body
(operator norms, spectral radius, fractional ladders on ℝ) waits for
mathlib and the full package. The skeleton is provable today, pure-core:

> junctions are **energy-preserving** (holonomy: they transform state,
> never its energy) and every circulation crosses a **strictly lossy**
> edge — therefore every signal reaches silence, in a number of
> circulations bounded by its initial energy.

Energy is quantized as `Nat` — the honest discrete shadow of the
analytic statement, and the shape the engine's tests already police at
`f32`. Two-layer law: Lean proves the model, the invariant tests police
the floats.
-/

namespace MusFormal.Holonomy

/-- Iterate a map `n` times (pure-core; `Function.iterate` is mathlib's). -/
def iterate {σ : Type} (f : σ → σ) : Nat → σ → σ
  | 0, x => x
  | n + 1, x => iterate f n (f x)

/-- A state space with a quantized energy. -/
structure Energized (σ : Type) where
  energy : σ → Nat

variable {σ : Type} (E : Energized σ)

/-- A junction is energy-preserving: holonomy moves state around the
    fiber, never up or down the energy ladder. Givens rotations are the
    analytic instance. -/
def Preserving (f : σ → σ) : Prop :=
  ∀ x, E.energy (f x) = E.energy x

/-- A lossy edge strictly decreases positive energy and fixes silence. -/
def Lossy (f : σ → σ) : Prop :=
  ∀ x, (E.energy x = 0 → E.energy (f x) = 0) ∧
       (0 < E.energy x → E.energy (f x) < E.energy x)

/-- Composing any energy-preserving holonomy with a lossy edge is lossy:
    the loop's rotation cannot rescue the energy the edge takes. -/
theorem lossy_comp_preserving {j l : σ → σ}
    (hj : Preserving E j) (hl : Lossy E l) : Lossy E (fun x => l (j x)) := by
  intro x
  constructor
  · intro h0
    have hjx : E.energy (j x) = 0 := by rw [hj x]; exact h0
    exact (hl (j x)).1 hjx
  · intro hpos
    have hjx : 0 < E.energy (j x) := by rw [hj x]; exact hpos
    have := (hl (j x)).2 hjx
    rw [hj x] at this
    exact this

/-- Iterating a lossy map `n` times from `x` with `energy x ≤ n` reaches
    silence: every circulation pays, and the purse is finite. -/
theorem silence_within (f : σ → σ) (hf : Lossy E f) :
    ∀ (n : Nat) (x : σ), E.energy x ≤ n → E.energy (iterate f n x) = 0 := by
  intro n
  induction n with
  | zero =>
    intro x hx
    exact Nat.le_zero.mp hx
  | succ n ih =>
    intro x hx
    have step : E.energy (f x) ≤ n := by
      cases Nat.eq_zero_or_pos (E.energy x) with
      | inl h0 =>
        have : E.energy (f x) = 0 := (hf x).1 h0
        rw [this]; exact Nat.zero_le n
      | inr hpos =>
        have hlt : E.energy (f x) < E.energy x := (hf x).2 hpos
        exact Nat.le_of_lt_succ (Nat.lt_of_lt_of_le hlt hx)
    exact ih (f x) step

/-- The network statement: a circulation built from an energy-preserving
    junction chain and a lossy edge silences every state within
    `energy x` circulations. This is the quantized skeleton of
    “contractive holonomy”; the analytic ladder arithmetic joins it when
    the mathematician's package (and mathlib) land. -/
theorem network_silences (j l : σ → σ)
    (hj : Preserving E j) (hl : Lossy E l) (x : σ) :
    E.energy (iterate (fun y => l (j y)) (E.energy x) x) = 0 :=
  silence_within E _ (lossy_comp_preserving E hj hl) (E.energy x) x
    (Nat.le_refl _)

end MusFormal.Holonomy
