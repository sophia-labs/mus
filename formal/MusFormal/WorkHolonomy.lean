/-!
# Work and holonomy: a pure-core executable skeleton

This file formalizes the algebraic part of the Ariadne paper without real
analysis or matrices. The analytic implementation uses positive-definite
metrics and a polar decomposition; the statements below isolate the laws that
remain true for any state space carrying an integer-valued energy witness.

The file proves four facts used by the paper:

1. work telescopes exactly along a path;
2. an energy-preserving turn contributes zero work;
3. a closed zero-work path can still have a nontrivial residue;
4. interleaving a preserving turn with a work-bearing stretch can change the
   work, even when the same two local factors are used.

The finite three-mode witness is the permutation shadow of the continuous
Givens commutator. The two-coordinate witness is the discrete shadow of the
nonseparability of the polar factors along a path.
-/

namespace MusFormal.WorkHolonomy

/-- Explicit composition, named locally so the file remains independent of
    mathlib's function API. -/
def compose {σ : Type} (g f : σ → σ) : σ → σ := fun x => g (f x)

infixr:90 " ∘w " => compose

/-- A state space with a signed energy witness. Physical stored energy is
    nonnegative; `Int` is used here so that work may be positive or negative. -/
structure Energized (σ : Type) where
  energy : σ → Int

variable {σ : Type} (E : Energized σ)

/-- Exact work performed by a state map at one state. -/
def work (f : σ → σ) (x : σ) : Int := E.energy (f x) - E.energy x

/-- A turn preserves the energy witness at every state. -/
def Preserving (f : σ → σ) : Prop := ∀ x, E.energy (f x) = E.energy x

/-- Work is a telescoping difference under composition. -/
theorem work_comp (g f : σ → σ) (x : σ) :
    work E (g ∘w f) x = work E g (f x) + work E f x := by
  simp [work, compose, Int.sub_eq_add_neg, Int.add_assoc, Int.add_comm]
  symm
  rw [← Int.add_assoc, Int.add_right_neg, Int.zero_add]

/-- A preserving map performs zero work. -/
theorem preserving_work_zero {u : σ → σ} (hu : Preserving E u) (x : σ) :
    work E u x = 0 := by
  simp [work, hu x]

/-- A preserving turn applied after a stretch does not alter the stretch's
    scalar work. This is the abstract shadow of the orthogonal polar factor
    cancelling out of `xᵀ(AᵀA-I)x/2`. -/
theorem preserving_after_work {u h : σ → σ} (hu : Preserving E u) (x : σ) :
    work E (u ∘w h) x = work E h x := by
  simp [work, compose, hu (h x)]

/-- If the same preserving turn occurs before the work-bearing map, the work
    is evaluated on the turned state. It therefore need not agree with the
    previous theorem. -/
theorem preserving_before_work {u h : σ → σ} (hu : Preserving E u) (x : σ) :
    work E (h ∘w u) x = work E h (u x) := by
  rw [work_comp]
  rw [preserving_work_zero E hu]
  simp

/-- Execute a path from left to right. -/
def run : List (σ → σ) → σ → σ
  | [], x => x
  | f :: rest, x => run rest (f x)

/-- Sum the work at the states where each path segment is actually applied. -/
def pathWork : List (σ → σ) → σ → Int
  | [], _ => 0
  | f :: rest, x => work E f x + pathWork rest (f x)

/-- The work ledger closes exactly for every finite path. -/
theorem path_work_closes : ∀ (path : List (σ → σ)) (x : σ),
    pathWork E path x = E.energy (run path x) - E.energy x := by
  intro path
  induction path with
  | nil =>
      intro x
      simp [pathWork, run]
  | cons f rest ih =>
      intro x
      simp [pathWork, run, ih, work, Int.sub_eq_add_neg, Int.add_assoc,
        Int.add_comm]
      rw [← Int.add_assoc, Int.add_right_neg, Int.zero_add]

/-- If every segment is preserving, the whole path preserves energy. -/
def AllPreserving : List (σ → σ) → Prop
  | [] => True
  | f :: rest => Preserving E f ∧ AllPreserving rest

/-- A path made entirely of turns has zero total work. -/
theorem preserving_path_zero_work : ∀ (path : List (σ → σ)),
    AllPreserving E path → ∀ x, pathWork E path x = 0 := by
  intro path
  induction path with
  | nil =>
      intro _ x
      simp [pathWork]
  | cons f rest ih =>
      intro hall x
      have hf : Preserving E f := hall.1
      have hrest : AllPreserving E rest := hall.2
      simp [pathWork, preserving_work_zero E hf x, ih hrest (f x)]

-- --------------------------------------------------------------------------
-- A finite noncommutative, zero-work loop

/-- Three acoustic modes in the smallest discrete witness. -/
inductive Mode where
  | a
  | b
  | c
  deriving DecidableEq, Repr

/-- Swap the first two modes. -/
def swapAB : Mode → Mode
  | .a => .b
  | .b => .a
  | .c => .c

/-- Swap the last two modes. -/
def swapBC : Mode → Mode
  | .a => .a
  | .b => .c
  | .c => .b

/-- Every mode carries the same quantized energy. -/
def modeEnergy : Energized Mode := ⟨fun _ => 1⟩

/-- The two local turns are individually energy preserving. -/
theorem swapAB_preserving : Preserving modeEnergy swapAB := by
  intro x
  cases x <;> rfl

theorem swapBC_preserving : Preserving modeEnergy swapBC := by
  intro x
  cases x <;> rfl

/-- Since the swaps are involutions, `A B A B` is their group commutator. -/
def discreteCommutator : Mode → Mode :=
  swapAB ∘w swapBC ∘w swapAB ∘w swapBC

/-- The closed path is not the identity: mode `a` is transported to `c`. -/
theorem discrete_commutator_nontrivial : discreteCommutator Mode.a = Mode.c := by
  rfl

/-- Yet the commutator performs exactly zero work. -/
theorem discrete_commutator_zero_work :
    work modeEnergy discreteCommutator Mode.a = 0 := by
  rfl

/-- The full four-segment path is certified as preserving. -/
theorem discrete_commutator_path_zero_work :
    pathWork modeEnergy [swapBC, swapAB, swapBC, swapAB] Mode.a = 0 := by
  rfl

-- --------------------------------------------------------------------------
-- A finite work--turn order witness

abbrev Vec2 := Int × Int

/-- Euclidean quadratic energy on two integer coordinates. -/
def vecEnergy : Energized Vec2 :=
  ⟨fun x => x.1 * x.1 + x.2 * x.2⟩

/-- A zero-work quarter turn in this discrete witness: swap the axes. -/
def turn : Vec2 → Vec2 := fun x => (x.2, x.1)

/-- A work-bearing anisotropic stretch. -/
def stretchX : Vec2 → Vec2 := fun x => (2 * x.1, x.2)

/-- The turn preserves the quadratic energy. -/
theorem turn_preserving : Preserving vecEnergy turn := by
  intro x
  cases x with
  | mk a b =>
      simp [vecEnergy, turn, Int.add_comm]

/-- Applying the turn after the stretch leaves the stretch's work unchanged. -/
theorem turn_after_stretch_work : ∀ x,
    work vecEnergy (turn ∘w stretchX) x = work vecEnergy stretchX x := by
  intro x
  exact preserving_after_work vecEnergy turn_preserving x

/-- At the reference state, stretch then turn performs three units of work. -/
theorem stretch_then_turn_reference :
    work vecEnergy (turn ∘w stretchX) (1, 0) = 3 := by
  decide

/-- The same two factors in the opposite order perform no work at that state. -/
theorem turn_then_stretch_reference :
    work vecEnergy (stretchX ∘w turn) (1, 0) = 0 := by
  decide

/-- Hence work and turn are locally distinguishable but globally
    nonseparable by order. -/
theorem factor_order_changes_work :
    work vecEnergy (turn ∘w stretchX) (1, 0) ≠
      work vecEnergy (stretchX ∘w turn) (1, 0) := by
  decide

end MusFormal.WorkHolonomy
