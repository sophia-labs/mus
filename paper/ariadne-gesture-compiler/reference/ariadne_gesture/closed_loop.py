"""Closed-control commutator synthesis for SO(3)."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import least_squares, minimize
from scipy.spatial.transform import Rotation

from .core import (
    Edge, FloatMatrix, Gate, Graph, compile_so_on_tree, givens, schedule_matrix,
)

def _commutator_matrix(
    pair_a: Edge, pair_b: Edge, a: float, b: float
) -> FloatMatrix:
    A = givens(3, *pair_a, a)
    B = givens(3, *pair_b, b)
    return A @ B @ givens(3, *pair_a, -a) @ givens(3, *pair_b, -b)


def _loop_product(parameters: NDArray[np.float64], loops: int) -> FloatMatrix:
    total = np.eye(3, dtype=np.float64)
    for index in range(loops):
        a, b = parameters[2 * index : 2 * index + 2]
        total = total @ _commutator_matrix((0, 1), (1, 2), float(a), float(b))
    return total


def _rotation_vector(matrix: FloatMatrix) -> NDArray[np.float64]:
    if Rotation is None:
        raise RuntimeError("scipy is required for the closed-loop compiler")
    return Rotation.from_matrix(matrix).as_rotvec()


def _rotation_from_to(
    source: NDArray[np.float64], target: NDArray[np.float64]
) -> FloatMatrix:
    """Return a proper rotation mapping one unit vector to another."""
    source = np.asarray(source, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    source /= np.linalg.norm(source)
    target /= np.linalg.norm(target)
    cross = np.cross(source, target)
    cosine = float(np.dot(source, target))
    sine = float(np.linalg.norm(cross))
    if sine < 1e-12:
        if cosine > 0.0:
            return np.eye(3, dtype=np.float64)
        # Antipodal case: choose a deterministic perpendicular axis and turn pi.
        coordinate = int(np.argmin(np.abs(source)))
        axis = np.zeros(3, dtype=np.float64)
        axis[coordinate] = 1.0
        axis -= source * float(np.dot(source, axis))
        axis /= np.linalg.norm(axis)
        generator = np.array(
            [
                [0.0, -axis[2], axis[1]],
                [axis[2], 0.0, -axis[0]],
                [-axis[1], axis[0], 0.0],
            ],
            dtype=np.float64,
        )
        return np.eye(3, dtype=np.float64) + 2.0 * (generator @ generator)
    generator = np.array(
        [
            [0.0, -cross[2], cross[1]],
            [cross[2], 0.0, -cross[0]],
            [-cross[1], cross[0], 0.0],
        ],
        dtype=np.float64,
    )
    return (
        np.eye(3, dtype=np.float64)
        + generator
        + generator @ generator * ((1.0 - cosine) / (sine * sine))
    )


def balanced_commutator_angle(target_angle: float) -> float:
    """Exact balanced local angle whose commutator has `target_angle`.

    For A=R01(t), B=R12(t), the closed commutator has principal angle phi with

        sin(phi/2)^2 = 4 x^2 (1-x^2),  x=sin(t/2)^2.

    The principal-branch inverse is

        t = 2 asin(sqrt(sin(phi/4))).
    """
    if not (0.0 <= target_angle <= math.pi + 1e-12):
        raise ValueError("principal SO(3) angle must lie in [0, pi]")
    clamped = min(math.pi, max(0.0, target_angle))
    return 2.0 * math.asin(math.sqrt(math.sin(clamped / 4.0)))


@dataclass(frozen=True)
class ExactClosedLoopCertificate:
    target_angle_rad: float
    balanced_generator_angle_rad: float
    factor_count: int
    reconstruction_error_rad: float
    reconstruction_error_fro: float
    orthogonality_error_fro: float
    zero_work_residual: float
    max_edge_control_closure: float
    thermodynamic_length: float
    minimum_quadratic_cost: float
    duration: float
    schedule: tuple[Gate, ...]


def compile_exact_closed_loop_so3(
    target: FloatMatrix,
    *,
    graph: Graph | None = None,
    duration: float = 1.0,
    tolerance: float = 1e-9,
) -> ExactClosedLoopCertificate:
    """Compile every SO(3) target as one exact closed macro commutator.

    A balanced local commutator supplies the requested principal angle.  A
    conjugation rotates its axis onto the target axis.  The resulting dense
    macro rotations A and B are each lowered exactly to graph-edge Givens
    gates; execution of B^-1, A^-1, B, A realizes A B A^-1 B^-1 under the
    left-action schedule convention.  Every scalar gate angle appears once
    with its inverse, so the integrated edge controls close exactly.
    """
    if duration <= 0.0:
        raise ValueError("duration must be positive")
    target = np.asarray(target, dtype=np.float64)
    if target.shape != (3, 3):
        raise ValueError("exact closed-loop compiler currently targets SO(3)")
    identity = np.eye(3, dtype=np.float64)
    if np.linalg.norm(target.T @ target - identity, ord="fro") > tolerance:
        raise ValueError("target is not orthogonal within tolerance")
    if abs(float(np.linalg.det(target)) - 1.0) > tolerance:
        raise ValueError("target must lie in SO(3)")
    graph = graph or Graph(n=3, edges=((0, 1), (1, 2)))
    if graph.n != 3 or not graph.is_connected():
        raise ValueError("a connected three-mode graph is required")

    target_rotvec = _rotation_vector(target)
    target_angle = float(np.linalg.norm(target_rotvec))
    if target_angle < 1e-14:
        return ExactClosedLoopCertificate(
            target_angle_rad=0.0,
            balanced_generator_angle_rad=0.0,
            factor_count=0,
            reconstruction_error_rad=0.0,
            reconstruction_error_fro=0.0,
            orthogonality_error_fro=0.0,
            zero_work_residual=0.0,
            max_edge_control_closure=0.0,
            thermodynamic_length=0.0,
            minimum_quadratic_cost=0.0,
            duration=duration,
            schedule=(),
        )

    target_axis = target_rotvec / target_angle
    local_angle = balanced_commutator_angle(target_angle)
    A0 = givens(3, 0, 1, local_angle)
    B0 = givens(3, 1, 2, local_angle)
    local_commutator = A0 @ B0 @ A0.T @ B0.T
    local_rotvec = _rotation_vector(local_commutator)
    local_axis = local_rotvec / np.linalg.norm(local_rotvec)
    conjugator = _rotation_from_to(local_axis, target_axis)
    A = conjugator @ A0 @ conjugator.T
    B = conjugator @ B0 @ conjugator.T

    compiled_a = compile_so_on_tree(A, graph, tolerance=tolerance)
    compiled_b = compile_so_on_tree(B, graph, tolerance=tolerance)
    inverse_a = tuple(gate.inverse() for gate in reversed(compiled_a.schedule))
    inverse_b = tuple(gate.inverse() for gate in reversed(compiled_b.schedule))
    # Under schedule_matrix's left action, this execution order yields
    # A B A^-1 B^-1.
    schedule = inverse_b + inverse_a + compiled_b.schedule + compiled_a.schedule
    actual = schedule_matrix(3, schedule)
    endpoint_error = float(np.linalg.norm(_rotation_vector(target.T @ actual)))
    edge_closure = {
        edge: sum(gate.theta for gate in schedule if gate.edge == edge)
        for edge in graph.edges
    }
    length = float(sum(abs(gate.theta) for gate in schedule))
    return ExactClosedLoopCertificate(
        target_angle_rad=target_angle,
        balanced_generator_angle_rad=local_angle,
        factor_count=len(schedule),
        reconstruction_error_rad=endpoint_error,
        reconstruction_error_fro=float(np.linalg.norm(actual - target, ord="fro")),
        orthogonality_error_fro=float(
            np.linalg.norm(actual.T @ actual - identity, ord="fro")
        ),
        zero_work_residual=abs(float(np.linalg.norm(actual @ np.ones(3)) ** 2 - 3.0)),
        max_edge_control_closure=max(abs(value) for value in edge_closure.values()),
        thermodynamic_length=length,
        minimum_quadratic_cost=length * length / duration,
        duration=duration,
        schedule=schedule,
    )


@dataclass(frozen=True)
class ClosedLoopCertificate:
    loops: int
    parameters: tuple[float, ...]
    factor_count: int
    reconstruction_error_rad: float
    orthogonality_error_fro: float
    zero_work_residual: float
    thermodynamic_length: float
    minimum_quadratic_cost: float
    duration: float
    jacobian_min_singular_value: float
    jacobian_max_singular_value: float
    jacobian_condition_number: float


def compile_closed_loop_so3(
    target: FloatMatrix,
    *,
    loops: int = 3,
    restarts: int = 12,
    seed: int = 0,
    duration: float = 1.0,
    regularization: float = 1e-6,
) -> ClosedLoopCertificate:
    """Compile an SO(3) target from rectangular loops on two edge controls.

    Each primitive is A(a) B(b) A(-a) B(-b); both control coordinates return
    exactly to zero and every factor is orthogonal.  The solver is numerical,
    so the certificate reports the endpoint error and Jacobian conditioning.
    """
    if least_squares is None or minimize is None:
        raise RuntimeError("scipy is required for the closed-loop compiler")
    target = np.asarray(target, dtype=np.float64)
    if target.shape != (3, 3):
        raise ValueError("closed-loop prototype currently targets SO(3)")
    rng = np.random.default_rng(seed)

    def endpoint_residual(parameters: NDArray[np.float64]) -> NDArray[np.float64]:
        return _rotation_vector(target.T @ _loop_product(parameters, loops))

    best: tuple[float, float, NDArray[np.float64]] | None = None
    for _ in range(restarts):
        initial = rng.uniform(-2.5, 2.5, size=2 * loops)
        solution = least_squares(
            endpoint_residual,
            initial,
            bounds=(-math.pi, math.pi),
            max_nfev=4000,
            xtol=1e-12,
            ftol=1e-12,
            gtol=1e-12,
        )
        error = float(np.linalg.norm(endpoint_residual(solution.x)))
        smooth_length = float(2.0 * np.linalg.norm(solution.x))
        score = error + regularization * smooth_length
        if best is None or score < best[0]:
            best = (score, error, solution.x.copy())
    assert best is not None
    parameters = best[2]

    # Refine the exact endpoint subject to minimum squared control amplitude.
    # SLSQP can fail near singular charts; retain the least-squares solution if
    # its endpoint is already better.
    def objective(values: NDArray[np.float64]) -> float:
        return float(4.0 * np.dot(values, values))

    constraints = {
        "type": "eq",
        "fun": endpoint_residual,
    }
    refined = minimize(
        objective,
        parameters,
        method="SLSQP",
        bounds=[(-math.pi, math.pi)] * len(parameters),
        constraints=constraints,
        options={"maxiter": 3000, "ftol": 1e-12},
    )
    if refined.success:
        refined_error = float(np.linalg.norm(endpoint_residual(refined.x)))
        if refined_error <= max(1e-9, best[1] * 10.0):
            parameters = refined.x.copy()

    actual = _loop_product(parameters, loops)
    endpoint_error = float(np.linalg.norm(endpoint_residual(parameters)))
    # A rectangular loop has four factors and absolute angular length
    # 2(|a|+|b|).  Unit friction is used in this reference certificate.
    length = float(2.0 * np.sum(np.abs(parameters)))
    min_cost = length * length / duration

    # Finite-difference endpoint Jacobian; rank three is the local
    # controllability witness for the compiled word.
    eps = 1e-6
    jac = np.zeros((3, len(parameters)), dtype=np.float64)
    base = endpoint_residual(parameters)
    for k in range(len(parameters)):
        shifted = parameters.copy()
        shifted[k] += eps
        jac[:, k] = (endpoint_residual(shifted) - base) / eps
    singular_values = np.linalg.svd(jac, compute_uv=False)

    return ClosedLoopCertificate(
        loops=loops,
        parameters=tuple(float(x) for x in parameters),
        factor_count=4 * loops,
        reconstruction_error_rad=endpoint_error,
        orthogonality_error_fro=float(
            np.linalg.norm(actual.T @ actual - np.eye(3), ord="fro")
        ),
        zero_work_residual=abs(float(np.linalg.norm(actual @ np.ones(3)) ** 2 - 3.0)),
        thermodynamic_length=length,
        minimum_quadratic_cost=min_cost,
        duration=duration,
        jacobian_min_singular_value=float(singular_values[-1]),
        jacobian_max_singular_value=float(singular_values[0]),
        jacobian_condition_number=float(
            singular_values[0] / singular_values[-1]
            if singular_values[-1] > 0.0
            else math.inf
        ),
    )
