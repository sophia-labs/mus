/-!
# Op-log convergence: order from membership

The Meaningful-Object engine's collaboration warrant, formalized. In
`mus-oplog` (Rust), a log is a content-addressed set of ops with the
total order `(lamport, actor, seq, id)`, merge is union, and every face
replays ops in that order. The load-bearing law:

> **Two replicas that hold the same ops — in any arrival order, with any
> duplication — replay identically.**

Model: ops are any strictly-ordered type (the Rust tuple order is one
instance; `Ops` below is a mini order class because pure-core Lean has
none). A replica's canonical state is its ops sorted strictly ascending
(sorted AND deduplicated at once). We prove the canonical form depends
only on membership — so merge (concatenation, in either order, with
repeats) converges. Pure core, no dependencies, no sorries; the Rust
property tests police the same laws on the concrete implementation.
Lean proves the model; tests police the bytes.
-/

namespace MusFormal.Oplog

/-- The order the op-id tuple carries: strict, transitive, trichotomous,
    decidable. Pure-core stand-in for mathlib's `LinearOrder`. -/
class Ops (α : Type) where
  lt : α → α → Prop
  trans : ∀ {a b c : α}, lt a b → lt b c → lt a c
  irrefl : ∀ a : α, ¬ lt a a
  trichotomy : ∀ a b : α, lt a b ∨ a = b ∨ lt b a
  decLt : ∀ a b : α, Decidable (lt a b)
  decEq : ∀ a b : α, Decidable (a = b)

variable {α : Type} [Ops α]

local infix:50 " ≺ " => Ops.lt

instance (a b : α) : Decidable (a ≺ b) := Ops.decLt a b
instance : DecidableEq α := Ops.decEq

theorem asymm {a b : α} (h : a ≺ b) : ¬ b ≺ a := fun h' =>
  Ops.irrefl a (Ops.trans h h')

/-- Strictly ascending: the canonical replay shape. -/
def Ascending : List α → Prop
  | [] => True
  | [_] => True
  | a :: b :: rest => a ≺ b ∧ Ascending (b :: rest)

theorem ascending_tail {a : α} {t : List α} (h : Ascending (a :: t)) :
    Ascending t := by
  cases t with
  | nil => trivial
  | cons b rest => exact h.2

/-- The head of an ascending list precedes every tail element. -/
theorem head_min {a : α} {t : List α} (h : Ascending (a :: t)) :
    ∀ y ∈ t, a ≺ y := by
  induction t generalizing a with
  | nil => intro y hy; cases hy
  | cons c tc ih =>
    intro y hy
    cases List.mem_cons.mp hy with
    | inl he => rw [he]; exact h.1
    | inr hy' => exact Ops.trans h.1 (ih h.2 y hy')

/-- Insert into an ascending list, keeping it ascending, ignoring
    duplicates — one op arriving at a replica. -/
def insertOp (x : α) : List α → List α
  | [] => [x]
  | a :: rest =>
    if x ≺ a then x :: a :: rest
    else if x = a then a :: rest
    else a :: insertOp x rest

theorem mem_insertOp (x y : α) (l : List α) :
    y ∈ insertOp x l ↔ y = x ∨ y ∈ l := by
  induction l with
  | nil => simp [insertOp]
  | cons a rest ih =>
    by_cases hlt : x ≺ a
    · simp [insertOp, if_pos hlt, List.mem_cons]
    · by_cases heq : x = a
      · simp only [insertOp, if_neg hlt, if_pos heq, List.mem_cons]
        constructor
        · intro h; exact Or.inr h
        · intro h
          cases h with
          | inl h => rw [h, heq]; exact Or.inl rfl
          | inr h => exact h
      · simp only [insertOp, if_neg hlt, if_neg heq, List.mem_cons, ih]
        constructor
        · intro h
          cases h with
          | inl h => exact Or.inr (Or.inl h)
          | inr h =>
            cases h with
            | inl h => exact Or.inl h
            | inr h => exact Or.inr (Or.inr h)
        · intro h
          cases h with
          | inl h => exact Or.inr (Or.inl h)
          | inr h =>
            cases h with
            | inl h => exact Or.inl h
            | inr h => exact Or.inr (Or.inr h)

theorem ascending_insertOp (x : α) (l : List α) (h : Ascending l) :
    Ascending (insertOp x l) := by
  induction l with
  | nil => trivial
  | cons a rest ih =>
    by_cases hlt : x ≺ a
    · simp only [insertOp, if_pos hlt]
      show _ ∧ _
      exact ⟨hlt, h⟩
    · by_cases heq : x = a
      · simp only [insertOp, if_neg hlt, if_pos heq]
        exact h
      · have hax : a ≺ x := by
          cases Ops.trichotomy x a with
          | inl h1 => exact absurd h1 hlt
          | inr h1 =>
            cases h1 with
            | inl h1 => exact absurd h1 heq
            | inr h1 => exact h1
        simp only [insertOp, if_neg hlt, if_neg heq]
        have hi := ih (ascending_tail h)
        cases rest with
        | nil => exact show _ ∧ _ from ⟨hax, trivial⟩
        | cons b tail =>
          simp only [insertOp] at hi ⊢
          by_cases hxb : x ≺ b
          · simp only [if_pos hxb] at hi ⊢
            exact show _ ∧ _ from ⟨hax, hi⟩
          · by_cases hxeqb : x = b
            · simp only [if_neg hxb, if_pos hxeqb] at hi ⊢
              exact show _ ∧ _ from ⟨h.1, hi⟩
            · simp only [if_neg hxb, if_neg hxeqb] at hi ⊢
              exact show _ ∧ _ from ⟨h.1, hi⟩

/-- A replica's canonical state after any arrival sequence. -/
def canon : List α → List α
  | [] => []
  | x :: rest => insertOp x (canon rest)

theorem ascending_canon (l : List α) : Ascending (canon l) := by
  induction l with
  | nil => trivial
  | cons x rest ih => exact ascending_insertOp x (canon rest) ih

theorem mem_canon (y : α) (l : List α) : y ∈ canon l ↔ y ∈ l := by
  induction l with
  | nil => simp [canon]
  | cons x rest ih =>
    simp only [canon, mem_insertOp, ih, List.mem_cons]

/-- The heart: an ascending list is determined by its membership. Two
    sorted-deduplicated replays over the same op-set are EQUAL. -/
theorem ascending_ext :
    ∀ (l₁ l₂ : List α), Ascending l₁ → Ascending l₂ →
      (∀ y, y ∈ l₁ ↔ y ∈ l₂) → l₁ = l₂ := by
  intro l₁
  induction l₁ with
  | nil =>
    intro l₂ _ _ hmem
    cases l₂ with
    | nil => rfl
    | cons b tail =>
      have : b ∈ ([] : List α) := (hmem b).mpr (List.mem_cons_self ..)
      cases this
  | cons a t₁ ih =>
    intro l₂ h₁ h₂ hmem
    cases l₂ with
    | nil =>
      have : a ∈ ([] : List α) := (hmem a).mp (List.mem_cons_self ..)
      cases this
    | cons b t₂ =>
      have hab : a = b := by
        have ha₂ : a ∈ b :: t₂ := (hmem a).mp (List.mem_cons_self ..)
        have hb₁ : b ∈ a :: t₁ := (hmem b).mpr (List.mem_cons_self ..)
        cases List.mem_cons.mp ha₂ with
        | inl h => exact h
        | inr h =>
          cases List.mem_cons.mp hb₁ with
          | inl h' => exact h'.symm
          | inr h' =>
            exact absurd (Ops.trans (head_min h₂ a h) (head_min h₁ b h'))
              (Ops.irrefl b)
      subst hab
      have htails : ∀ y, y ∈ t₁ ↔ y ∈ t₂ := by
        intro y
        constructor
        · intro hy
          have := (hmem y).mp (List.mem_cons.mpr (Or.inr hy))
          cases List.mem_cons.mp this with
          | inl he =>
            rw [he] at hy
            exact absurd (head_min h₁ a hy) (Ops.irrefl a)
          | inr h => exact h
        · intro hy
          have := (hmem y).mpr (List.mem_cons.mpr (Or.inr hy))
          cases List.mem_cons.mp this with
          | inl he =>
            rw [he] at hy
            exact absurd (head_min h₂ a hy) (Ops.irrefl a)
          | inr h => exact h
      exact congrArg (a :: ·)
        (ih t₂ (ascending_tail h₁) (ascending_tail h₂) htails)

/-- **Convergence.** Any two arrival histories carrying the same ops —
    reordered, duplicated, interleaved however replication delivered
    them — canonicalize to the identical replay. -/
theorem canon_converges (l₁ l₂ : List α)
    (hmem : ∀ y, y ∈ l₁ ↔ y ∈ l₂) : canon l₁ = canon l₂ :=
  ascending_ext (canon l₁) (canon l₂)
    (ascending_canon l₁) (ascending_canon l₂)
    (fun y => by rw [mem_canon, mem_canon]; exact hmem y)

/-- Merge is concatenation-then-canon; the corollary forms the Rust
    property tests exercise. -/
theorem merge_comm (l₁ l₂ : List α) :
    canon (l₁ ++ l₂) = canon (l₂ ++ l₁) :=
  canon_converges _ _ (fun y => by
    simp only [List.mem_append]
    exact Or.comm)

theorem merge_idem (l : List α) : canon (l ++ l) = canon l :=
  canon_converges _ _ (fun y => by
    simp only [List.mem_append]
    exact or_self_iff)

theorem merge_assoc (l₁ l₂ l₃ : List α) :
    canon ((l₁ ++ l₂) ++ l₃) = canon (l₁ ++ (l₂ ++ l₃)) :=
  canon_converges _ _ (fun y => by
    simp only [List.mem_append]
    exact or_assoc)

end MusFormal.Oplog
