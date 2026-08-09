from __future__ import annotations

import numpy as np

from mus_analysis.decomposition import (
    Region,
    auditory_band_decomposition,
    event_soft_mask_decomposition,
    hpss_decomposition,
    nmf_decomposition,
)


def synthetic_mix(sr: int = 16000) -> tuple[np.ndarray, int]:
    y = np.zeros(sr * 2, dtype=float)
    t1 = np.arange(int(.35 * sr)) / sr
    t2 = np.arange(int(.45 * sr)) / sr
    y[int(.2 * sr):int(.55 * sr)] += .15 * np.sin(2 * np.pi * 900 * t1) * np.hanning(len(t1))
    y[int(1.0 * sr):int(1.45 * sr)] += .12 * np.sin(2 * np.pi * 2400 * t2) * np.hanning(len(t2))
    y += np.random.default_rng(3).standard_normal(len(y)) * .002
    return y, sr


def placed_sum(result) -> np.ndarray:
    y = np.zeros(result.source_length_samples)
    for stem in result.stems:
        start = int(round(stem.start_seconds * result.source_sample_rate))
        available = min(len(stem.audio), len(y) - start)
        y[start:start + available] += stem.audio[:available]
    y[:len(result.residual.audio)] += result.residual.audio
    return y


def test_event_masks_are_additive_with_explicit_residual() -> None:
    y, sr = synthetic_mix()
    regions = (
        Region("one", .2, .55, "low event"),
        Region("two", 1.0, 1.45, "high event"),
    )
    result = event_soft_mask_decomposition(y, sr, regions, n_fft=1024, hop_length=128)
    reconstructed = placed_sum(result)
    assert len(result.stems) == 2
    assert np.sqrt(np.mean((y - reconstructed) ** 2)) < 1e-6
    assert result.closure_peak_error < 1e-6


def test_nmf_keeps_exact_time_domain_residual() -> None:
    y, sr = synthetic_mix()
    result = nmf_decomposition(y, sr, components=2, n_fft=1024, hop_length=128)
    assert len(result.stems) == 2
    assert np.max(np.abs(y - placed_sum(result))) < 1e-12
    assert result.residual.kind == "residual"


def test_auditory_band_layers_close_and_are_frequency_ordered() -> None:
    y, sr = synthetic_mix()
    result = auditory_band_decomposition(y, sr, bands=6, n_fft=1024, hop_length=128)
    assert len(result.stems) == 6
    centers = [stem.metadata["centerFrequencyHz"] for stem in result.stems]
    assert centers == sorted(centers)
    assert np.max(np.abs(y - placed_sum(result))) < 1e-12
    assert all(stem.kind == "auditory-band-component" for stem in result.stems)


def test_hpss_layers_close_without_claiming_sources() -> None:
    y, sr = synthetic_mix()
    result = hpss_decomposition(y, sr, n_fft=1024, hop_length=128)
    assert [stem.kind for stem in result.stems] == ["harmonic-component", "percussive-component"]
    assert np.max(np.abs(y - placed_sum(result))) < 1e-12
    assert "not a physical-source" in result.stems[0].metadata["interpretation"]
