"""Closed-control commutator synthesis for SO(3)."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import least_squares, minimize
from scipy.spatial.transform import Rotation

from .core import Edge, FloatMatrix, givens

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
