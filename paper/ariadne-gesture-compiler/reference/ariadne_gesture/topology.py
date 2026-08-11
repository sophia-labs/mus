"""Abelian and non-Abelian topological/geometric reference models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
import math

import numpy as np
from numpy.typing import NDArray
from scipy.linalg import expm

from .core import FloatMatrix, Graph, compile_so_on_tree

def rice_mele_hamiltonian(
    momentum: float,
    phase: float,
    *,
    coupling: float = 1.0,
    radius: float = 0.6,
    offset: float = 0.0,
    warp: float = 0.0,
    warp_phase: float = 0.0,
) -> NDArray[np.complex128]:
    angle = phase + warp * math.sin(3.0 * phase + warp_phase)
    dimerization = offset + radius * math.cos(angle)
    detuning = radius * math.sin(angle)
    t1 = coupling + dimerization
    t2 = coupling - dimerization
    dx = t1 + t2 * math.cos(momentum)
    dy = t2 * math.sin(momentum)
    return np.array(
        [[detuning, dx - 1j * dy], [dx + 1j * dy, -detuning]],
        dtype=np.complex128,
    )


def _lower_band_vector(matrix: NDArray[np.complex128]) -> NDArray[np.complex128]:
    _, vectors = np.linalg.eigh(matrix)
    return vectors[:, 0]


def chern_number_fhs(
    *,
    momentum_points: int = 51,
    phase_points: int = 51,
    **hamiltonian_parameters: float,
) -> tuple[float, float]:
    vectors = np.empty(
        (momentum_points, phase_points, 2), dtype=np.complex128
    )
    min_gap = math.inf
    for i, momentum in enumerate(
        np.linspace(0.0, 2.0 * math.pi, momentum_points, endpoint=False)
    ):
        for j, phase in enumerate(
            np.linspace(0.0, 2.0 * math.pi, phase_points, endpoint=False)
        ):
            matrix = rice_mele_hamiltonian(
                momentum, phase, **hamiltonian_parameters
            )
            values = np.linalg.eigvalsh(matrix)
            min_gap = min(min_gap, float(values[1] - values[0]))
            vectors[i, j] = _lower_band_vector(matrix)

    flux = 0.0
    for i in range(momentum_points):
        for j in range(phase_points):
            u = vectors[i, j]
            uk = vectors[(i + 1) % momentum_points, j]
            ut = vectors[i, (j + 1) % phase_points]
            ukt = vectors[(i + 1) % momentum_points, (j + 1) % phase_points]
            U_k = np.vdot(u, uk)
            U_t = np.vdot(u, ut)
            U_k_t = np.vdot(ut, ukt)
            U_t_k = np.vdot(uk, ukt)
            U_k /= abs(U_k)
            U_t /= abs(U_t)
            U_k_t /= abs(U_k_t)
            U_t_k /= abs(U_t_k)
            flux += float(np.angle(U_k * U_t_k / (U_k_t * U_t)))
    return flux / (2.0 * math.pi), min_gap


def polarization_winding(
    *,
    momentum_points: int = 151,
    phase_points: int = 151,
    **hamiltonian_parameters: float,
) -> float:
    phases: list[float] = []
    momenta = np.linspace(0.0, 2.0 * math.pi, momentum_points, endpoint=False)
    for phase in np.linspace(0.0, 2.0 * math.pi, phase_points):
        vectors = [
            _lower_band_vector(
                rice_mele_hamiltonian(
                    momentum, phase, **hamiltonian_parameters
                )
            )
            for momentum in momenta
        ]
        product = 1.0 + 0.0j
        for index, vector in enumerate(vectors):
            overlap = np.vdot(vector, vectors[(index + 1) % momentum_points])
            product *= overlap / abs(overlap)
        phases.append(float(np.angle(product)))
    unwrapped = np.unwrap(np.asarray(phases))
    polarization = -unwrapped / (2.0 * math.pi)
    return float(polarization[-1] - polarization[0])


def realified_schrodinger_generator(
    hamiltonian: NDArray[np.complex128],
) -> FloatMatrix:
    """Realify dot(psi)=-i H psi into dot([q,p])=A[q,p]."""
    real = np.real(hamiltonian)
    imag = np.imag(hamiltonian)
    return np.block([[imag, real], [-real, imag]]).astype(np.float64)


@dataclass(frozen=True)
class TopologicalCertificate:
    nontrivial_chern: float
    nontrivial_min_gap: float
    nontrivial_polarization_winding: float
    trivial_chern: float
    trivial_min_gap: float
    deformations: int
    deformation_chern_max_error: float
    deformation_min_gap: float
    realification_skew_error_fro: float


def verify_topological_pump(*, deformations: int, seed: int) -> TopologicalCertificate:
    nontrivial_chern, nontrivial_gap = chern_number_fhs()
    winding = polarization_winding()
    trivial_chern, trivial_gap = chern_number_fhs(offset=1.0, radius=0.35)

    rng = np.random.default_rng(seed)
    chern_errors: list[float] = []
    gaps: list[float] = []
    for _ in range(deformations):
        warp = float(rng.uniform(-0.45, 0.45))
        phase = float(rng.uniform(0.0, 2.0 * math.pi))
        chern, gap = chern_number_fhs(warp=warp, warp_phase=phase)
        chern_errors.append(abs(chern - 1.0))
        gaps.append(gap)

    sample_h = rice_mele_hamiltonian(0.71, 1.23, warp=0.31, warp_phase=0.4)
    realified = realified_schrodinger_generator(sample_h)
    skew_error = float(np.linalg.norm(realified + realified.T, ord="fro"))
    return TopologicalCertificate(
        nontrivial_chern=nontrivial_chern,
        nontrivial_min_gap=nontrivial_gap,
        nontrivial_polarization_winding=winding,
        trivial_chern=trivial_chern,
        trivial_min_gap=trivial_gap,
        deformations=deformations,
        deformation_chern_max_error=max(chern_errors),
        deformation_min_gap=min(gaps),
        realification_skew_error_fro=skew_error,
    )


@dataclass(frozen=True)
class PropagatorCompileCertificate:
    dimension: int
    duration: float
    gate_count: int
    generator_skew_error_fro: float
    propagator_orthogonality_error_fro: float
    propagator_determinant_error: float
    reconstruction_error_fro: float


def compile_skew_propagator(
    generator: FloatMatrix,
    *,
    duration: float,
    graph: Graph | None = None,
) -> PropagatorCompileCertificate:
    """Exponentiate a real skew generator and lower it to graph-edge gates."""
    if expm is None:
        raise RuntimeError("scipy is required for propagator compilation")
    generator = np.asarray(generator, dtype=np.float64)
    if generator.ndim != 2 or generator.shape[0] != generator.shape[1]:
        raise ValueError("generator must be square")
    n = generator.shape[0]
    graph = graph or Graph(n=n, edges=tuple((i, i + 1) for i in range(n - 1)))
    propagator = np.asarray(expm(duration * generator), dtype=np.float64)
    certificate = compile_so_on_tree(propagator, graph, tolerance=1e-8)
    identity = np.eye(n)
    return PropagatorCompileCertificate(
        dimension=n,
        duration=duration,
        gate_count=certificate.gate_count,
        generator_skew_error_fro=float(
            np.linalg.norm(generator + generator.T, ord="fro")
        ),
        propagator_orthogonality_error_fro=float(
            np.linalg.norm(propagator.T @ propagator - identity, ord="fro")
        ),
        propagator_determinant_error=abs(float(np.linalg.det(propagator)) - 1.0),
        reconstruction_error_fro=certificate.reconstruction_error_fro,
    )


# ---------------------------------------------------------------------------
# Constant-gap non-Abelian mode-bundle surrogate


def _pauli_matrices() -> tuple[NDArray[np.complex128], ...]:
    sigma_x = np.array([[0.0, 1.0], [1.0, 0.0]], dtype=np.complex128)
    sigma_y = np.array([[0.0, -1.0j], [1.0j, 0.0]], dtype=np.complex128)
    sigma_z = np.array([[1.0, 0.0], [0.0, -1.0]], dtype=np.complex128)
    return sigma_x, sigma_y, sigma_z


def _grassmann_generators() -> tuple[NDArray[np.complex128], ...]:
    """Three simple skew-Hermitian generators on Gr(2,4)."""
    generators: list[NDArray[np.complex128]] = []
    zero = np.zeros((2, 2), dtype=np.complex128)
    for block in _pauli_matrices():
        generator = np.block([[zero, block], [-block.conj().T, zero]])
        generator /= np.linalg.norm(generator, ord="fro")
        generators.append(generator)
    return tuple(generators)


def grassmann_frame(coordinates: Sequence[float]) -> NDArray[np.complex128]:
    if expm is None:
        raise RuntimeError("scipy is required for the non-Abelian bundle")
    if len(coordinates) != 3:
        raise ValueError("the reference bundle has three coordinates")
    total = np.eye(4, dtype=np.complex128)
    for coordinate, generator in zip(
        coordinates, _grassmann_generators(), strict=True
    ):
        total = total @ expm(float(coordinate) * generator)
    return total[:, :2]


def grassmann_hamiltonian(coordinates: Sequence[float]) -> NDArray[np.complex128]:
    """A doubly-degenerate, constant-gap Hamiltonian I-2P(lambda)."""
    frame = grassmann_frame(coordinates)
    projector = frame @ frame.conj().T
    return np.eye(4, dtype=np.complex128) - 2.0 * projector


def rectangular_parameter_loop(
    first: int,
    second: int,
    first_extent: float,
    second_extent: float,
    *,
    steps_per_edge: int = 64,
) -> tuple[NDArray[np.float64], ...]:
    if first == second or not (0 <= first < 3 and 0 <= second < 3):
        raise ValueError("invalid coordinate plane")
    if steps_per_edge < 2:
        raise ValueError("steps_per_edge must be at least two")
    points: list[NDArray[np.float64]] = []

    def point(a: float, b: float) -> NDArray[np.float64]:
        out = np.zeros(3, dtype=np.float64)
        out[first] = a
        out[second] = b
        return out

    for value in np.linspace(0.0, first_extent, steps_per_edge, endpoint=False):
        points.append(point(float(value), 0.0))
    for value in np.linspace(0.0, second_extent, steps_per_edge, endpoint=False):
        points.append(point(first_extent, float(value)))
    for value in np.linspace(first_extent, 0.0, steps_per_edge, endpoint=False):
        points.append(point(float(value), second_extent))
    for value in np.linspace(second_extent, 0.0, steps_per_edge + 1):
        points.append(point(0.0, float(value)))
    return tuple(points)


def _polar_unitary(matrix: NDArray[np.complex128]) -> NDArray[np.complex128]:
    left, _, right = np.linalg.svd(matrix)
    return left @ right


def wilson_loop(
    path: Sequence[Sequence[float]],
    *,
    gauges: Sequence[NDArray[np.complex128]] | None = None,
) -> NDArray[np.complex128]:
    """Discrete parallel transport of the doubly-degenerate subspace.

    The unitary polar factor of each adjacent frame overlap is multiplied in
    path order.  For a closed path, a frame-gauge change conjugates the result,
    so trace, determinant and eigenvalues are invariant.
    """
    frames = [grassmann_frame(point) for point in path]
    if gauges is not None:
        if len(gauges) != len(frames):
            raise ValueError("one gauge matrix is required per path point")
        frames = [frame @ gauge for frame, gauge in zip(frames, gauges, strict=True)]
    total = np.eye(2, dtype=np.complex128)
    for current, nxt in zip(frames, frames[1:]):
        link = _polar_unitary(current.conj().T @ nxt)
        total = total @ link
    return total


def _unitary_generator_2(axis: NDArray[np.float64]) -> NDArray[np.complex128]:
    axis = np.asarray(axis, dtype=np.float64)
    axis /= np.linalg.norm(axis)
    sx, sy, sz = _pauli_matrices()
    return 1j * (axis[0] * sx + axis[1] * sy + axis[2] * sz)


@dataclass(frozen=True)
class NonAbelianBundleCertificate:
    dimension_complex: int
    degenerate_rank: int
    constant_gap: float
    loop_a_unitarity_error_fro: float
    loop_b_unitarity_error_fro: float
    loop_commutator_norm_fro: float
    loop_a_eigenphases: tuple[float, ...]
    loop_b_eigenphases: tuple[float, ...]
    gauge_trace_error: float
    gauge_determinant_error: float
    same_homotopy_deformation_change_fro: float
    realification_skew_error_fro: float
    compiled_real_dimension: int
    compiled_gate_count: int
    compiled_reconstruction_error_fro: float


def verify_nonabelian_bundle(*, seed: int) -> NonAbelianBundleCertificate:
    """Verify noncommuting Wilson loops in a constant-gap rank-two bundle.

    This is a geometric, not yet topologically protected, non-Abelian seed.  A
    smooth deformation of a loop generally changes its Wilson operator, and the
    certificate reports that sensitivity explicitly.
    """
    if expm is None:
        raise RuntimeError("scipy is required for the non-Abelian bundle")
    loop_a_path = rectangular_parameter_loop(0, 1, 1.4, 1.1)
    loop_b_path = rectangular_parameter_loop(1, 2, 1.2, 1.3)
    loop_a = wilson_loop(loop_a_path)
    loop_b = wilson_loop(loop_b_path)

    # A smooth base-point-preserving gauge transformation.
    rng = np.random.default_rng(seed)
    axis = rng.normal(size=3)
    gauge_generator = _unitary_generator_2(axis)
    gauges: list[NDArray[np.complex128]] = []
    denominator = max(1, len(loop_a_path) - 1)
    for index in range(len(loop_a_path)):
        phase = 0.55 * math.sin(2.0 * math.pi * index / denominator)
        gauges.append(expm(phase * gauge_generator))
    gauged = wilson_loop(loop_a_path, gauges=gauges)

    deformed_path = rectangular_parameter_loop(0, 1, 1.46, 1.04)
    deformed = wilson_loop(deformed_path)

    values_a = tuple(float(value) for value in np.sort(np.angle(np.linalg.eigvals(loop_a))))
    values_b = tuple(float(value) for value in np.sort(np.angle(np.linalg.eigvals(loop_b))))

    sample_hamiltonian = grassmann_hamiltonian((0.42, -0.31, 0.27))
    real_generator = realified_schrodinger_generator(sample_hamiltonian)
    compiled = compile_skew_propagator(real_generator, duration=0.013)

    sampled_gaps: list[float] = []
    for path in (loop_a_path, loop_b_path):
        stride = max(1, len(path) // 32)
        for point in path[::stride]:
            eigenvalues = np.linalg.eigvalsh(grassmann_hamiltonian(point))
            sampled_gaps.append(float(eigenvalues[2] - eigenvalues[1]))

    return NonAbelianBundleCertificate(
        dimension_complex=4,
        degenerate_rank=2,
        constant_gap=min(sampled_gaps),
        loop_a_unitarity_error_fro=float(
            np.linalg.norm(loop_a.conj().T @ loop_a - np.eye(2), ord="fro")
        ),
        loop_b_unitarity_error_fro=float(
            np.linalg.norm(loop_b.conj().T @ loop_b - np.eye(2), ord="fro")
        ),
        loop_commutator_norm_fro=float(
            np.linalg.norm(loop_a @ loop_b - loop_b @ loop_a, ord="fro")
        ),
        loop_a_eigenphases=values_a,
        loop_b_eigenphases=values_b,
        gauge_trace_error=abs(complex(np.trace(gauged) - np.trace(loop_a))),
        gauge_determinant_error=abs(complex(np.linalg.det(gauged) - np.linalg.det(loop_a))),
        same_homotopy_deformation_change_fro=float(
            np.linalg.norm(deformed - loop_a, ord="fro")
        ),
        realification_skew_error_fro=float(
            np.linalg.norm(real_generator + real_generator.T, ord="fro")
        ),
        compiled_real_dimension=compiled.dimension,
        compiled_gate_count=compiled.gate_count,
        compiled_reconstruction_error_fro=compiled.reconstruction_error_fro,
    )
