"""Work/deformation budgets and exact order statistics."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .core import FloatMatrix, random_so

def spectral_log_radius(positive: FloatMatrix) -> float:
    values = np.linalg.eigvalsh(positive)
    if np.min(values) <= 0.0:
        raise ValueError("matrix must be positive definite")
    return float(np.max(np.abs(np.log(values))))


def volume_neutral_anisotropy(positive: FloatMatrix) -> float:
    values = np.linalg.eigvalsh(positive)
    logs = np.log(values)
    centered = logs - np.mean(logs)
    return float(np.max(np.abs(centered)))


@dataclass(frozen=True)
class PumpBoundCertificate:
    steps: int
    radius_sum: float
    lower_energy_ratio: float
    upper_energy_ratio: float
    observed_min_ratio: float
    observed_max_ratio: float
    bound_violations: int
    total_determinant_error: float


def verify_pump_bound(
    *,
    n: int,
    steps: int,
    states: int,
    seed: int,
) -> PumpBoundCertificate:
    rng = np.random.default_rng(seed)
    factors: list[FloatMatrix] = []
    radius_sum = 0.0
    for _ in range(steps):
        U = random_so(n, rng)
        q = random_so(n, rng)
        logs = rng.uniform(-0.18, 0.18, size=n)
        # Remove isotropic scale: this is a volume-neutral cyclic actuator
        # budget, so all possible pumping comes from anisotropy plus order.
        logs -= np.mean(logs)
        H = q @ np.diag(np.exp(logs)) @ q.T
        factors.append(U @ H)
        radius_sum += volume_neutral_anisotropy(H)
    total = np.eye(n)
    for factor in factors:
        total = factor @ total

    samples = rng.normal(size=(states, n))
    samples /= np.linalg.norm(samples, axis=1, keepdims=True)
    transformed = samples @ total.T
    ratios = np.sum(transformed * transformed, axis=1)
    lower = math.exp(-2.0 * radius_sum)
    upper = math.exp(2.0 * radius_sum)
    violations = int(np.sum((ratios < lower - 1e-12) | (ratios > upper + 1e-12)))
    return PumpBoundCertificate(
        steps=steps,
        radius_sum=radius_sum,
        lower_energy_ratio=lower,
        upper_energy_ratio=upper,
        observed_min_ratio=float(np.min(ratios)),
        observed_max_ratio=float(np.max(ratios)),
        bound_violations=violations,
        total_determinant_error=abs(float(np.linalg.det(total)) - 1.0),
    )


@dataclass(frozen=True)
class WorkOrderCertificate:
    n: int
    state_samples: int
    exact_operator_norm: float
    spectral_spread_bound: float
    observed_max_abs_work_difference: float
    exact_max_abs_work_difference: float
    observed_rms_work_difference: float
    analytic_rms_work_difference: float
    observed_mean_work_difference: float
    analytic_mean_work_difference: float
    bound_violations: int


def verify_factor_order_work(
    *,
    n: int,
    states: int,
    seed: int,
) -> WorkOrderCertificate:
    """Verify exact spherical statistics for turn/stretch order.

    Compare ``U H`` (stretch, then preserving turn) with ``H U`` (turn,
    then stretch) on unit-energy directions.  With ``D = H^2-U^T H^2 U``,

        Delta W(x) = 1/2 x^T D x.

    ``tr D = 0``, so the spherical mean is exactly zero.  For a uniform unit
    vector in R^n,

        RMS(Delta W)^2 = tr(D^2)/(2 n (n+2)).

    The worst-case absolute work difference is ``||D||_2/2`` and
    ``||D||_2`` is bounded by the spectral spread of ``H^2``.
    """
    if n < 2:
        raise ValueError("n must be at least two")
    rng = np.random.default_rng(seed)
    U = random_so(n, rng)
    basis = random_so(n, rng)
    logs = np.linspace(-0.55, 0.55, n)
    logs -= np.mean(logs)
    H = basis @ np.diag(np.exp(logs)) @ basis.T
    H2 = H @ H
    D = H2 - U.T @ H2 @ U

    samples = rng.normal(size=(states, n))
    samples /= np.linalg.norm(samples, axis=1, keepdims=True)
    values = 0.5 * np.einsum("bi,ij,bj->b", samples, D, samples)

    exact_norm = float(np.linalg.norm(D, ord=2))
    eigenvalues = np.linalg.eigvalsh(H2)
    spread = float(eigenvalues[-1] - eigenvalues[0])
    exact_max = 0.5 * exact_norm
    analytic_rms = math.sqrt(
        float(np.trace(D @ D)) / (2.0 * n * (n + 2.0))
    )
    tolerance = 1e-12
    violations = int(np.sum(np.abs(values) > exact_max + tolerance))
    return WorkOrderCertificate(
        n=n,
        state_samples=states,
        exact_operator_norm=exact_norm,
        spectral_spread_bound=spread,
        observed_max_abs_work_difference=float(np.max(np.abs(values))),
        exact_max_abs_work_difference=exact_max,
        observed_rms_work_difference=float(np.sqrt(np.mean(values * values))),
        analytic_rms_work_difference=analytic_rms,
        observed_mean_work_difference=float(np.mean(values)),
        analytic_mean_work_difference=0.0,
        bound_violations=violations,
    )
