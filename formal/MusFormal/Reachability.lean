/-!
# Sparse acoustic reachability: the graph-theoretic skeleton

The analytic theorem uses edge-plane generators `Jᵢⱼ` and the identity

    [Jᵢⱼ, Jⱼₖ] = -Jᵢₖ.

This pure-core file formalizes the combinatorial content: direct edge planes
and bracket closure propagate along a simple path, while a disconnected cut is
an invariant obstruction.  The matrix identity and dimension statement remain
in the float64 oracle and the planned mathlib layer.
-/

namespace MusFormal.Reachability

universe u

variable {Vertex : Type u}

/-- A path whose extension never returns to its starting vertex.  This is the
    exact shape needed by repeated adjacent-plane brackets.  Ordinary finite
    connected graphs always admit such a path between distinct vertices after
    cycle removal. -/
inductive BracketPath (edge : Vertex → Vertex → Prop) : Vertex → Vertex → Type u
  | direct {a b : Vertex} (h : edge a b) : BracketPath edge a b
  | extend {a b c : Vertex}
      (path : BracketPath edge a b)
      (h : edge b c)
      (hne : a ≠ c) : BracketPath edge a c

/-- Plane relations available from authored edges and repeated Lie brackets.
    `bracket` is the symbolic shadow of `[J_ab, J_bc] = ±J_ac`. -/
inductive GeneratedPlane (edge : Vertex → Vertex → Prop) : Vertex → Vertex → Prop
  | direct {a b : Vertex} (h : edge a b) : GeneratedPlane edge a b
  | reverse {a b : Vertex}
      (h : GeneratedPlane edge a b) : GeneratedPlane edge b a
  | bracket {a b c : Vertex}
      (left : GeneratedPlane edge a b)
      (right : GeneratedPlane edge b c)
      (hne : a ≠ c) : GeneratedPlane edge a c

/-- Every bracket path yields its endpoint plane. -/
theorem path_generates {edge : Vertex → Vertex → Prop} {a b : Vertex}
    (path : BracketPath edge a b) : GeneratedPlane edge a b := by
  induction path with
  | direct h => exact GeneratedPlane.direct h
  | extend path h hne ih =>
      exact GeneratedPlane.bracket ih (GeneratedPlane.direct h) hne

/-- Connectivity phrased in the path form directly consumed by the algebra. -/
def BracketConnected (edge : Vertex → Vertex → Prop) : Prop :=
  ∀ a b, a ≠ b → Nonempty (BracketPath edge a b)

/-- A bracket-connected coupling graph generates every off-diagonal plane. -/
theorem connected_generates_all {edge : Vertex → Vertex → Prop}
    (connected : BracketConnected edge) {a b : Vertex} (hne : a ≠ b) :
    GeneratedPlane edge a b := by
  have path := connected a b hne
  cases path with
  | intro witness => exact path_generates witness

/-- Any two-coloring respected by every authored edge is also respected by
    every generated plane.  Brackets cannot cross a disconnected cut. -/
theorem generated_preserves_color
    {edge : Vertex → Vertex → Prop}
    (color : Vertex → Bool)
    (edge_preserves : ∀ {a b}, edge a b → color a = color b) :
    ∀ {a b}, GeneratedPlane edge a b → color a = color b := by
  intro a b generated
  induction generated with
  | direct h => exact edge_preserves h
  | reverse _ ih => exact ih.symm
  | bracket _ _ _ ihLeft ihRight => exact ihLeft.trans ihRight

/-- A witnessed cut proves non-reachability across that cut. -/
theorem cut_obstructs_generation
    {edge : Vertex → Vertex → Prop}
    (color : Vertex → Bool)
    (edge_preserves : ∀ {a b}, edge a b → color a = color b)
    {a b : Vertex}
    (crosses : color a ≠ color b) :
    ¬ GeneratedPlane edge a b := by
  intro generated
  exact crosses (generated_preserves_color color edge_preserves generated)

/-- The scalar-gate count used by tree QR: one gate for every remaining
    non-root vertex at each elimination stage. -/
def triangularGates : Nat → Nat
  | 0 => 0
  | n + 1 => triangularGates n + n

@[simp] theorem triangularGates_zero : triangularGates 0 = 0 := rfl

@[simp] theorem triangularGates_succ (n : Nat) :
    triangularGates (n + 1) = triangularGates n + n := rfl

example : triangularGates 3 = 3 := by decide
example : triangularGates 8 = 28 := by decide
example : triangularGates 16 = 120 := by decide

end MusFormal.Reachability
