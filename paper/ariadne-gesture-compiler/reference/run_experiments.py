"""Run the deterministic Ariadne inverse-geometry reference experiments.

The full run writes ``results.json``.  ``--quick --no-write`` is intended for
CI: it exercises every theorem-shaped invariant with smaller Monte Carlo
budgets while leaving the durable full receipt untouched.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import argparse
import json
import math

import numpy as np

from ariadne_gesture import (
    Graph,
    canonical_edge,
    chern_number_fhs,
    compile_closed_loop_so3,
    compile_skew_propagator,
    compile_so_on_tree,
    graph_rotation_lie_rank,
    graph_transport_lie_rank,
    optimize_tree_compilation,
    random_so,
    realified_schrodinger_generator,
    rice_mele_hamiltonian,
    verify_factor_order_work,
    verify_nonabelian_bundle,
    verify_pump_bound,
    verify_topological_pump,
)

SEED = 0xA71AD0C


def random_connected_graph(n: int, rng: np.random.Generator) -> Graph:
    """Random recursive tree followed by sparse extra edges."""
    edges: set[tuple[int, int]] = set()
    for node in range(1, n):
        parent = int(rng.integers(0, node))
        edges.add(canonical_edge(parent, node))
    for i in range(n):
        for j in range(i + 1, n):
            if rng.random() < 0.18:
                edges.add((i, j))
    return Graph(n=n, edges=tuple(sorted(edges)))


def axis_angle_target(axis: np.ndarray, angle: float) -> np.ndarray:
    axis = axis / np.linalg.norm(axis)
    x, y, z = axis
    generator = np.array(
        [[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]],
        dtype=np.float64,
    )
    return (
        np.eye(3)
        + math.sin(angle) * generator
        + (1.0 - math.cos(angle)) * (generator @ generator)
    )


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def run(*, quick: bool) -> dict:
    rng = np.random.default_rng(SEED)

    exact_compiler_trials = 0
    max_reconstruction_error = 0.0
    max_orthogonality_error = 0.0
    max_determinant_error = 0.0
    gate_count_mismatches = 0
    rotation_rank_mismatches = 0
    transport_rank_mismatches = 0
    affine_rank_mismatches = 0
    disconnected_rank_mismatches = 0

    max_dimension = 10 if quick else 16
    trials_per_dimension = 8 if quick else 24
    by_dimension: dict[str, dict[str, float | int]] = {}
    for n in range(2, max_dimension + 1):
        local_max = 0.0
        for _ in range(trials_per_dimension):
            graph = random_connected_graph(n, rng)
            target = random_so(n, rng)
            certificate = compile_so_on_tree(target, graph)
            expected = n * (n - 1) // 2
            gate_count_mismatches += int(certificate.gate_count != expected)
            local_max = max(local_max, certificate.reconstruction_error_fro)
            max_reconstruction_error = max(
                max_reconstruction_error, certificate.reconstruction_error_fro
            )
            max_orthogonality_error = max(
                max_orthogonality_error, certificate.orthogonality_error_fro
            )
            max_determinant_error = max(
                max_determinant_error, certificate.determinant_error
            )
            exact_compiler_trials += 1
        by_dimension[str(n)] = {
            "trials": trials_per_dimension,
            "gate_count": n * (n - 1) // 2,
            "max_reconstruction_error_fro": local_max,
        }

    # Lie closure is more expensive than QR.  A path graph is the minimal
    # connected witness; disconnected forests test the component formula.
    rank_max = 7 if quick else 8
    for n_rank in range(2, rank_max + 1):
        rank_graph = Graph(
            n=n_rank,
            edges=tuple((i, i + 1) for i in range(n_rank - 1)),
        )
        expected_so = n_rank * (n_rank - 1) // 2
        rotation_rank_mismatches += int(
            graph_rotation_lie_rank(rank_graph) != expected_so
        )
        transport_rank_mismatches += int(
            graph_transport_lie_rank(rank_graph) != n_rank * n_rank - 1
        )
        affine_rank_mismatches += int(
            graph_transport_lie_rank(rank_graph, include_scalar=True)
            != n_rank * n_rank
        )

    disconnected_trials = 8 if quick else 24
    for _ in range(disconnected_trials):
        n_disc = int(rng.integers(4, 9))
        cut = int(rng.integers(1, n_disc))
        disc_edges: list[tuple[int, int]] = []
        for start, stop in ((0, cut), (cut, n_disc)):
            for node in range(start + 1, stop):
                parent = int(rng.integers(start, node))
                disc_edges.append((parent, node))
        disc_graph = Graph(n=n_disc, edges=tuple(sorted(disc_edges)))
        predicted = sum(
            len(component) * (len(component) - 1) // 2
            for component in disc_graph.components()
        )
        disconnected_rank_mismatches += int(
            graph_rotation_lie_rank(disc_graph) != predicted
        )

    # Heterogeneous actuator friction.  Topology and leaf order preserve exact
    # gate count but materially alter thermodynamic gesture length.
    n = 8
    dense_edges = tuple(
        (i, j)
        for i in range(n)
        for j in range(i + 1, n)
        if (j == i + 1) or ((i * 7 + j * 11) % 5 == 0)
    )
    weighted_graph = Graph(n=n, edges=tuple(sorted(set(dense_edges))))
    weighted_target = random_so(n, rng)
    edge_friction = {
        edge: float(math.exp(rng.uniform(-1.5, 1.5)))
        for edge in weighted_graph.edges
    }
    tree_candidates = 64 if quick else 192
    tree_optimization = optimize_tree_compilation(
        weighted_target,
        weighted_graph,
        edge_friction=edge_friction,
        duration=2.0,
        candidates=tree_candidates,
        seed=SEED + 1,
    )

    # Three named closed-loop targets and a random-target survey.  Each word is
    # a product of rectangular commutators on J01 and J12; controls close and
    # every factor is zero-work in the Euclidean metric.
    closed_loop_targets = [
        axis_angle_target(np.array([1.0, 2.0, -0.7]), math.radians(37.0)),
        axis_angle_target(np.array([-0.3, 0.4, 1.0]), math.radians(103.0)),
        axis_angle_target(np.array([0.2, -1.0, 0.1]), math.radians(171.0)),
    ]
    closed_loop_certificates = [
        compile_closed_loop_so3(
            target,
            loops=3,
            restarts=8 if quick else 16,
            seed=SEED + 100 + index,
            duration=2.0,
        )
        for index, target in enumerate(closed_loop_targets)
    ]

    survey_targets = 8 if quick else 40
    survey_errors: list[float] = []
    survey_costs: list[float] = []
    survey_conditions: list[float] = []
    for index in range(survey_targets):
        certificate = compile_closed_loop_so3(
            random_so(3, rng),
            loops=3,
            restarts=6 if quick else 10,
            seed=SEED + 1000 + index,
            duration=2.0,
        )
        survey_errors.append(certificate.reconstruction_error_rad)
        survey_costs.append(certificate.minimum_quadratic_cost)
        survey_conditions.append(certificate.jacobian_condition_number)

    pump_bound = verify_pump_bound(
        n=7,
        steps=12,
        states=10_000 if quick else 50_000,
        seed=SEED + 2,
    )
    factor_order = verify_factor_order_work(
        n=7,
        states=20_000 if quick else 100_000,
        seed=SEED + 22,
    )
    topological = verify_topological_pump(
        deformations=4 if quick else 16,
        seed=SEED + 3,
    )
    rice_mele_generator = realified_schrodinger_generator(
        rice_mele_hamiltonian(0.71, 1.23, warp=0.31, warp_phase=0.4)
    )
    topological_step = compile_skew_propagator(
        rice_mele_generator,
        duration=0.01,
    )
    nonabelian = verify_nonabelian_bundle(seed=SEED + 4)

    results = {
        "schema": "ariadne-inverse-geometry/2",
        "mode": "quick" if quick else "full",
        "seed": SEED,
        "exact_edge_compiler": {
            "theorem_target": (
                "connected graph => exact SO(n) synthesis in "
                "n(n-1)/2 graph-edge Givens gates"
            ),
            "trials": exact_compiler_trials,
            "max_reconstruction_error_fro": max_reconstruction_error,
            "max_orthogonality_error_fro": max_orthogonality_error,
            "max_determinant_error": max_determinant_error,
            "gate_count_mismatches": gate_count_mismatches,
            "rotation_lie_rank_mismatches": rotation_rank_mismatches,
            "sl_lie_rank_mismatches": transport_rank_mismatches,
            "gl_lie_rank_mismatches": affine_rank_mismatches,
            "disconnected_rank_mismatches": disconnected_rank_mismatches,
            "by_dimension": by_dimension,
        },
        "weighted_tree_search": {
            "vertices": n,
            "edges": len(weighted_graph.edges),
            "candidates": tree_optimization.candidates,
            "baseline_minimum_quadratic_cost": tree_optimization.baseline_cost,
            "best_minimum_quadratic_cost": tree_optimization.best_cost,
            "improvement_fraction": tree_optimization.improvement_fraction,
            "best_thermodynamic_length": (
                tree_optimization.thermodynamic.thermodynamic_length
            ),
            "best_constant_speed_residual": (
                tree_optimization.thermodynamic.constant_speed_residual
            ),
            "best_reconstruction_error_fro": (
                tree_optimization.compile.reconstruction_error_fro
            ),
        },
        "closed_loop_so3": [asdict(item) for item in closed_loop_certificates],
        "closed_loop_so3_survey": {
            "targets": survey_targets,
            "failures_above_1e-8_rad": sum(error > 1e-8 for error in survey_errors),
            "max_endpoint_error_rad": max(survey_errors),
            "median_endpoint_error_rad": percentile(survey_errors, 50.0),
            "p95_endpoint_error_rad": percentile(survey_errors, 95.0),
            "median_minimum_quadratic_cost": percentile(survey_costs, 50.0),
            "max_minimum_quadratic_cost": max(survey_costs),
            "median_jacobian_condition_number": percentile(
                survey_conditions, 50.0
            ),
            "max_jacobian_condition_number": max(survey_conditions),
        },
        "pump_bound": asdict(pump_bound),
        "factor_order_work": asdict(factor_order),
        "topological_pump": asdict(topological),
        "topological_step_compilation": asdict(topological_step),
        "nonabelian_constant_gap_bundle": asdict(nonabelian),
    }

    # Stop conditions: executable theorem receipts rather than illustrative
    # plots.  Fail closed if any core invariant drifts.
    exact = results["exact_edge_compiler"]
    assert exact["gate_count_mismatches"] == 0
    assert exact["rotation_lie_rank_mismatches"] == 0
    assert exact["sl_lie_rank_mismatches"] == 0
    assert exact["gl_lie_rank_mismatches"] == 0
    assert exact["disconnected_rank_mismatches"] == 0
    assert exact["max_reconstruction_error_fro"] < 1e-10
    assert all(item.reconstruction_error_rad < 1e-8 for item in closed_loop_certificates)
    assert results["closed_loop_so3_survey"]["failures_above_1e-8_rad"] == 0
    assert pump_bound.bound_violations == 0
    assert factor_order.bound_violations == 0
    assert abs(topological.nontrivial_chern - 1.0) < 1e-9
    assert abs(topological.trivial_chern) < 1e-9
    assert topological.deformation_chern_max_error < 1e-9
    assert topological_step.reconstruction_error_fro < 1e-10
    assert nonabelian.constant_gap > 1.99
    assert nonabelian.loop_commutator_norm_fro > 0.1
    assert nonabelian.gauge_trace_error < 1e-10
    assert nonabelian.compiled_reconstruction_error_fro < 1e-10
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    results = run(quick=args.quick)
    if not args.no_write:
        output = Path(__file__).with_name("results.json")
        output.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
