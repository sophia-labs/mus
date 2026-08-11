"""Exact graph-constrained rotation compilation and gesture metrics."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from collections import deque
from typing import Iterable, Mapping, Sequence
import math

import numpy as np
from numpy.typing import NDArray

FloatMatrix = NDArray[np.float64]
Edge = tuple[int, int]

def canonical_edge(i: int, j: int) -> Edge:
    if i == j:
        raise ValueError("self edges are not valid Givens controls")
    return (i, j) if i < j else (j, i)


def givens(n: int, i: int, j: int, theta: float) -> FloatMatrix:
    """Return the SO(n) plane rotation exp(theta J_ij)."""
    if not (0 <= i < n and 0 <= j < n and i != j):
        raise ValueError(f"invalid plane ({i}, {j}) for n={n}")
    c = math.cos(theta)
    s = math.sin(theta)
    out = np.eye(n, dtype=np.float64)
    out[i, i] = c
    out[i, j] = -s
    out[j, i] = s
    out[j, j] = c
    return out


def skew_generator(n: int, i: int, j: int) -> FloatMatrix:
    out = np.zeros((n, n), dtype=np.float64)
    out[i, j] = -1.0
    out[j, i] = 1.0
    return out


def schedule_matrix(n: int, schedule: Sequence["Gate"]) -> FloatMatrix:
    """Compose gates in execution order: state <- gate @ state."""
    total = np.eye(n, dtype=np.float64)
    for gate in schedule:
        total = givens(n, gate.i, gate.j, gate.theta) @ total
    return total


def random_so(n: int, rng: np.random.Generator) -> FloatMatrix:
    q, _ = np.linalg.qr(rng.normal(size=(n, n)))
    if np.linalg.det(q) < 0.0:
        q[:, 0] *= -1.0
    return q


def rotation_error(actual: FloatMatrix, target: FloatMatrix) -> float:
    return float(np.linalg.norm(actual - target, ord="fro"))


@dataclass(frozen=True)
class Gate:
    i: int
    j: int
    theta: float

    @property
    def edge(self) -> Edge:
        return canonical_edge(self.i, self.j)

    def inverse(self) -> "Gate":
        return Gate(self.i, self.j, -self.theta)


@dataclass(frozen=True)
class Graph:
    n: int
    edges: tuple[Edge, ...]

    def __post_init__(self) -> None:
        normalized = tuple(sorted({canonical_edge(*edge) for edge in self.edges}))
        if normalized != self.edges:
            object.__setattr__(self, "edges", normalized)
        for i, j in self.edges:
            if not (0 <= i < self.n and 0 <= j < self.n):
                raise ValueError(f"edge {(i, j)} is outside graph of size {self.n}")

    @property
    def adjacency(self) -> tuple[frozenset[int], ...]:
        rows = [set() for _ in range(self.n)]
        for i, j in self.edges:
            rows[i].add(j)
            rows[j].add(i)
        return tuple(frozenset(row) for row in rows)

    def components(self) -> list[list[int]]:
        adj = self.adjacency
        unseen = set(range(self.n))
        out: list[list[int]] = []
        while unseen:
            root = min(unseen)
            queue = deque([root])
            unseen.remove(root)
            component: list[int] = []
            while queue:
                node = queue.popleft()
                component.append(node)
                for nxt in sorted(adj[node]):
                    if nxt in unseen:
                        unseen.remove(nxt)
                        queue.append(nxt)
            out.append(component)
        return out

    def is_connected(self) -> bool:
        return self.n > 0 and len(self.components()) == 1

    def bfs_spanning_tree(self, root: int = 0) -> tuple[Edge, ...]:
        if not (0 <= root < self.n):
            raise ValueError("invalid root")
        adj = self.adjacency
        seen = {root}
        queue = deque([root])
        tree: list[Edge] = []
        while queue:
            node = queue.popleft()
            for nxt in sorted(adj[node]):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
                    tree.append(canonical_edge(node, nxt))
        if len(seen) != self.n:
            raise ValueError("graph is disconnected")
        return tuple(tree)

    def random_spanning_tree(self, rng: np.random.Generator) -> tuple[Edge, ...]:
        if self.n == 0:
            raise ValueError("empty graph")
        adj = self.adjacency
        root = int(rng.integers(0, self.n))
        seen = {root}
        stack = [root]
        tree: list[Edge] = []
        while stack:
            node = stack[-1]
            candidates = [v for v in adj[node] if v not in seen]
            if not candidates:
                stack.pop()
                continue
            nxt = int(rng.choice(candidates))
            seen.add(nxt)
            tree.append(canonical_edge(node, nxt))
            stack.append(nxt)
        if len(seen) != self.n:
            raise ValueError("graph is disconnected")
        return tuple(sorted(tree))


@dataclass(frozen=True)
class CompileCertificate:
    n: int
    graph_edges: tuple[Edge, ...]
    tree_edges: tuple[Edge, ...]
    leaf_order: tuple[int, ...]
    gate_count: int
    dimension_lower_bound: int
    reconstruction_error_fro: float
    orthogonality_error_fro: float
    determinant_error: float
    all_gates_on_graph: bool
    schedule: tuple[Gate, ...]

    def to_json_dict(self) -> dict:
        data = asdict(self)
        data["schedule"] = [asdict(gate) for gate in self.schedule]
        return data


def _tree_adjacency(n: int, tree_edges: Sequence[Edge]) -> list[set[int]]:
    if len(tree_edges) != max(0, n - 1):
        raise ValueError("a spanning tree must have n-1 edges")
    adj = [set() for _ in range(n)]
    for i, j in tree_edges:
        adj[i].add(j)
        adj[j].add(i)
    if n > 0:
        seen = {0}
        queue = deque([0])
        while queue:
            node = queue.popleft()
            for nxt in adj[node]:
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        if len(seen) != n:
            raise ValueError("tree edges are disconnected")
    return adj


def _leaf_order(
    n: int,
    tree_edges: Sequence[Edge],
    *,
    rng: np.random.Generator | None = None,
) -> tuple[int, ...]:
    adj = _tree_adjacency(n, tree_edges)
    alive = set(range(n))
    order: list[int] = []
    while len(alive) > 1:
        leaves = [v for v in alive if len(adj[v] & alive) == 1]
        if not leaves:
            raise RuntimeError("tree lost its leaf invariant")
        leaf = min(leaves) if rng is None else int(rng.choice(leaves))
        order.append(leaf)
        alive.remove(leaf)
    order.extend(alive)
    return tuple(order)


def _elimination_edges_to_root(
    alive: set[int],
    tree_adj: Sequence[set[int]],
    root: int,
    *,
    rng: np.random.Generator | None = None,
) -> list[tuple[int, int]]:
    active = set(alive)
    out: list[tuple[int, int]] = []
    while len(active) > 1:
        leaves = [
            v
            for v in active
            if v != root and len(tree_adj[v] & active) == 1
        ]
        if not leaves:
            raise RuntimeError("no removable non-root leaf")
        leaf = min(leaves) if rng is None else int(rng.choice(leaves))
        parent = next(iter(tree_adj[leaf] & active))
        out.append((parent, leaf))
        active.remove(leaf)
    return out


def compile_so_on_tree(
    target: FloatMatrix,
    graph: Graph,
    *,
    tree_edges: Sequence[Edge] | None = None,
    rng: np.random.Generator | None = None,
    tolerance: float = 1e-9,
) -> CompileCertificate:
    """Exact graph-constrained QR factorization using only tree edges.

    The algorithm processes columns in a leaf-elimination order.  For each
    selected leaf/root, rotations on the remaining tree collapse that column
    onto the root.  Removing the fixed leaf leaves a connected tree for the
    next column.  The elimination uses exactly (n-1)+(n-2)+...+1 gates.
    """
    target = np.asarray(target, dtype=np.float64)
    if target.shape != (graph.n, graph.n):
        raise ValueError("target shape does not match graph")
    identity = np.eye(graph.n)
    if np.linalg.norm(target.T @ target - identity, ord="fro") > tolerance:
        raise ValueError("target is not orthogonal within tolerance")
    if abs(np.linalg.det(target) - 1.0) > tolerance:
        raise ValueError("target must lie in SO(n)")
    if not graph.is_connected():
        raise ValueError("disconnected graph cannot generate all of SO(n)")

    tree = tuple(tree_edges or graph.bfs_spanning_tree())
    tree_adj = _tree_adjacency(graph.n, tree)
    order = _leaf_order(graph.n, tree, rng=rng)
    alive = set(range(graph.n))
    reduced = target.copy()
    elimination: list[Gate] = []

    for root in order[:-1]:
        column = root
        for parent, leaf in _elimination_edges_to_root(
            alive, tree_adj, root, rng=rng
        ):
            a = float(reduced[parent, column])
            b = float(reduced[leaf, column])
            theta = math.atan2(-b, a)
            gate = Gate(parent, leaf, theta)
            reduced = givens(graph.n, parent, leaf, theta) @ reduced
            elimination.append(gate)
        alive.remove(root)

    schedule = tuple(gate.inverse() for gate in reversed(elimination))
    actual = schedule_matrix(graph.n, schedule)
    graph_edge_set = set(graph.edges)
    gate_count = graph.n * (graph.n - 1) // 2
    if len(schedule) != gate_count:
        raise AssertionError("tree-QR gate-count invariant failed")

    return CompileCertificate(
        n=graph.n,
        graph_edges=graph.edges,
        tree_edges=tuple(sorted(tree)),
        leaf_order=order,
        gate_count=len(schedule),
        dimension_lower_bound=gate_count,
        reconstruction_error_fro=rotation_error(actual, target),
        orthogonality_error_fro=float(
            np.linalg.norm(actual.T @ actual - identity, ord="fro")
        ),
        determinant_error=abs(float(np.linalg.det(actual)) - 1.0),
        all_gates_on_graph=all(gate.edge in graph_edge_set for gate in schedule),
        schedule=schedule,
    )


@dataclass(frozen=True)
class ThermodynamicCertificate:
    duration: float
    thermodynamic_length: float
    minimum_quadratic_cost: float
    segment_durations: tuple[float, ...]
    constant_speed_residual: float


def thermodynamic_schedule(
    schedule: Sequence[Gate],
    *,
    edge_friction: Mapping[Edge, float] | None = None,
    duration: float,
) -> ThermodynamicCertificate:
    """Minimize sum_k w_k theta_k^2 / tau_k at fixed total duration.

    Cauchy-Schwarz gives D >= L^2 / duration with
    L=sum sqrt(w_k)|theta_k|.  Equality holds at constant thermodynamic speed,
    tau_k proportional to sqrt(w_k)|theta_k|.
    """
    if duration <= 0.0:
        raise ValueError("duration must be positive")
    friction = edge_friction or {}
    lengths: list[float] = []
    for gate in schedule:
        weight = float(friction.get(gate.edge, 1.0))
        if weight <= 0.0:
            raise ValueError("friction weights must be positive")
        lengths.append(math.sqrt(weight) * abs(gate.theta))
    total_length = float(sum(lengths))
    if total_length == 0.0:
        durations = tuple(duration / max(1, len(schedule)) for _ in schedule)
        return ThermodynamicCertificate(duration, 0.0, 0.0, durations, 0.0)
    durations = tuple(duration * length / total_length for length in lengths)
    speeds = [
        length / tau for length, tau in zip(lengths, durations, strict=True)
        if tau > 0.0
    ]
    residual = max(speeds) - min(speeds) if speeds else 0.0
    return ThermodynamicCertificate(
        duration=duration,
        thermodynamic_length=total_length,
        minimum_quadratic_cost=total_length * total_length / duration,
        segment_durations=durations,
        constant_speed_residual=float(residual),
    )


@dataclass(frozen=True)
class OptimizedTreeCertificate:
    baseline_cost: float
    best_cost: float
    improvement_fraction: float
    candidates: int
    compile: CompileCertificate
    thermodynamic: ThermodynamicCertificate


def optimize_tree_compilation(
    target: FloatMatrix,
    graph: Graph,
    *,
    edge_friction: Mapping[Edge, float],
    duration: float,
    candidates: int,
    seed: int,
) -> OptimizedTreeCertificate:
    rng = np.random.default_rng(seed)
    baseline_compile = compile_so_on_tree(target, graph)
    baseline_thermo = thermodynamic_schedule(
        baseline_compile.schedule,
        edge_friction=edge_friction,
        duration=duration,
    )
    best_compile = baseline_compile
    best_thermo = baseline_thermo

    for _ in range(max(0, candidates - 1)):
        tree = graph.random_spanning_tree(rng)
        certificate = compile_so_on_tree(target, graph, tree_edges=tree, rng=rng)
        thermo = thermodynamic_schedule(
            certificate.schedule,
            edge_friction=edge_friction,
            duration=duration,
        )
        if thermo.minimum_quadratic_cost < best_thermo.minimum_quadratic_cost:
            best_compile = certificate
            best_thermo = thermo

    baseline = baseline_thermo.minimum_quadratic_cost
    best = best_thermo.minimum_quadratic_cost
    return OptimizedTreeCertificate(
        baseline_cost=baseline,
        best_cost=best,
        improvement_fraction=(baseline - best) / baseline if baseline > 0 else 0.0,
        candidates=candidates,
        compile=best_compile,
        thermodynamic=best_thermo,
    )


def _orthonormal_rank(matrices: Iterable[FloatMatrix], tolerance: float) -> int:
    basis: list[NDArray[np.float64]] = []
    for matrix in matrices:
        vector = np.asarray(matrix, dtype=np.float64).reshape(-1).copy()
        for unit in basis:
            vector -= float(np.dot(unit, vector)) * unit
        norm = float(np.linalg.norm(vector))
        if norm > tolerance:
            basis.append(vector / norm)
    return len(basis)


def lie_closure_rank(
    generators: Sequence[FloatMatrix], *, tolerance: float = 1e-10
) -> int:
    """Numerically close a finite matrix generator set under commutators."""
    if not generators:
        return 0
    n = generators[0].shape[0]
    basis: list[FloatMatrix] = []
    vectors: list[NDArray[np.float64]] = []

    def add(matrix: FloatMatrix) -> bool:
        vector = matrix.reshape(-1).astype(np.float64, copy=True)
        for unit in vectors:
            vector -= float(np.dot(unit, vector)) * unit
        norm = float(np.linalg.norm(vector))
        if norm <= tolerance:
            return False
        vectors.append(vector / norm)
        basis.append(matrix.copy())
        return True

    for generator in generators:
        if generator.shape != (n, n):
            raise ValueError("inconsistent generator dimensions")
        add(generator)

    frontier = 0
    while frontier < len(basis) and len(basis) < n * n:
        left = basis[frontier]
        snapshot = list(basis)
        for right in snapshot:
            add(left @ right - right @ left)
            if len(basis) >= n * n:
                break
        frontier += 1
    return len(basis)


def graph_rotation_lie_rank(graph: Graph) -> int:
    return lie_closure_rank(
        [skew_generator(graph.n, i, j) for i, j in graph.edges]
    )


def graph_transport_lie_rank(
    graph: Graph,
    *,
    anisotropic_pair: Edge = (0, 1),
    include_scalar: bool = False,
) -> int:
    i, j = anisotropic_pair
    deformation = np.zeros((graph.n, graph.n), dtype=np.float64)
    deformation[i, i] = 1.0
    deformation[j, j] = -1.0
    generators = [skew_generator(graph.n, a, b) for a, b in graph.edges]
    generators.append(deformation)
    if include_scalar:
        generators.append(np.eye(graph.n, dtype=np.float64))
    return lie_closure_rank(generators)
