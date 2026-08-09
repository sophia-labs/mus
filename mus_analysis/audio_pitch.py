"""Reference pitch-trajectory operators for Aigua v2.

These operators intentionally emit independent trajectories.  The consensus
layer decides whether they agree; no estimator is allowed to overwrite another.
Heavy audio dependencies are imported lazily so the provenance/data model stays
usable in lightweight environments.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Sequence

from .pitch import PitchSample, PitchTrajectory


@dataclass(frozen=True, slots=True)
class PitchExtractionConfig:
    sample_rate: int = 48_000
    n_fft: int = 2048
    hop_length: int = 128
    fmin_hz: float = 500.0
    fmax_hz: float = 8_000.0
    energy_gate_fraction: float = 0.2

    def __post_init__(self) -> None:
        if self.sample_rate <= 0 or self.n_fft <= 0 or self.hop_length <= 0:
            raise ValueError("sample rate, FFT size and hop length must be positive")
        if not (0 < self.fmin_hz < self.fmax_hz < self.sample_rate / 2):
            raise ValueError("pitch range must lie below Nyquist")
        if not 0 <= self.energy_gate_fraction < 1:
            raise ValueError("energy_gate_fraction must lie in [0, 1)")


def load_audio_region(
    path: str | Path,
    *,
    sample_rate: int = 48_000,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
) -> tuple["object", int]:
    import librosa

    offset = 0.0 if start_seconds is None else start_seconds
    if offset < 0:
        raise ValueError("start_seconds must be non-negative")
    duration = None
    if end_seconds is not None:
        if end_seconds <= offset:
            raise ValueError("end_seconds must be greater than start_seconds")
        duration = end_seconds - offset
    y, sr = librosa.load(path, sr=sample_rate, mono=True, offset=offset, duration=duration)
    return y, sr


def shs_trajectory(
    y: "object",
    sr: int,
    config: PitchExtractionConfig = PitchExtractionConfig(),
    *,
    candidate_step_cents: float = 5.0,
    harmonic_count: int = 6,
    harmonic_decay: float = 0.84,
    score_threshold: float = 3.0,
) -> PitchTrajectory:
    """Log-frequency subharmonic-summation trajectory.

    Compared with Aigua v1's fixed 6 Hz candidate spacing, this reference uses
    constant cents resolution, making estimator precision comparable across the
    full search range.  The score remains a peak-to-mean ratio, not probability.
    """
    import librosa
    import numpy as np

    if candidate_step_cents <= 0 or harmonic_count < 1 or not 0 < harmonic_decay <= 1:
        raise ValueError("invalid SHS configuration")
    S = np.abs(
        librosa.stft(
            np.asarray(y, dtype=float),
            n_fft=config.n_fft,
            hop_length=config.hop_length,
            center=True,
        )
    )
    freqs = librosa.fft_frequencies(sr=sr, n_fft=config.n_fft)
    log_min = math.log2(config.fmin_hz)
    log_max = math.log2(config.fmax_hz)
    candidate_count = int(math.floor((log_max - log_min) * 1200.0 / candidate_step_cents)) + 1
    candidates = 2.0 ** (log_min + np.arange(candidate_count) * candidate_step_cents / 1200.0)
    frame_energy = S.sum(axis=0)
    energy_threshold = config.energy_gate_fraction * (frame_energy.max() if frame_energy.size else 0.0)
    times = librosa.frames_to_time(np.arange(S.shape[1]), sr=sr, hop_length=config.hop_length)
    samples: list[PitchSample] = []
    for frame_index, time in enumerate(times):
        column = S[:, frame_index]
        score = np.zeros_like(candidates)
        for harmonic in range(1, harmonic_count + 1):
            targets = candidates * harmonic
            valid = targets <= freqs[-1]
            if not np.any(valid):
                break
            score[valid] += (harmonic_decay ** (harmonic - 1)) * np.interp(
                targets[valid], freqs, column
            )
        best_index = int(np.argmax(score))
        peak_to_mean = float(score[best_index] / (score.mean() + 1e-12))
        frequency = None
        if frame_energy[frame_index] > energy_threshold and peak_to_mean >= score_threshold:
            frequency = float(candidates[best_index])
        samples.append(
            PitchSample(
                float(time),
                frequency,
                peak_to_mean,
                "aigua-shs-peak-to-mean-score",
            )
        )
    return PitchTrajectory("aigua.shs-log-cents/2", tuple(samples))


def pyin_trajectory(
    y: "object",
    sr: int,
    config: PitchExtractionConfig = PitchExtractionConfig(),
) -> PitchTrajectory:
    """librosa pYIN trajectory with its voiced-probability output preserved."""
    import librosa
    import numpy as np

    f0, voiced, probability = librosa.pyin(
        np.asarray(y, dtype=float),
        fmin=config.fmin_hz,
        fmax=config.fmax_hz,
        sr=sr,
        frame_length=config.n_fft,
        hop_length=config.hop_length,
        center=True,
    )
    times = librosa.frames_to_time(np.arange(len(f0)), sr=sr, hop_length=config.hop_length)
    samples = []
    for time, frequency, is_voiced, score in zip(times, f0, voiced, probability):
        usable = bool(is_voiced) and np.isfinite(frequency)
        samples.append(
            PitchSample(
                float(time),
                float(frequency) if usable else None,
                float(score) if np.isfinite(score) else 0.0,
                "librosa-pyin-voiced-probability",
            )
        )
    return PitchTrajectory("librosa.pyin/0.11", tuple(samples))


def dominant_ridge_trajectory(
    y: "object",
    sr: int,
    config: PitchExtractionConfig = PitchExtractionConfig(),
    *,
    score_threshold: float = 8.0,
) -> PitchTrajectory:
    """Track the strongest local spectral ridge.

    This is deliberately named a dominant ridge rather than f0: on a
    harmonic-stack call it may follow an overtone.  Octave conflicts against
    f0 estimators are therefore meaningful evidence, not a bug to hide.
    """
    import librosa
    import numpy as np

    S = np.abs(
        librosa.stft(
            np.asarray(y, dtype=float),
            n_fft=config.n_fft,
            hop_length=config.hop_length,
            center=True,
        )
    )
    freqs = librosa.fft_frequencies(sr=sr, n_fft=config.n_fft)
    mask = (freqs >= config.fmin_hz) & (freqs <= config.fmax_hz)
    band_freqs = freqs[mask]
    band = S[mask]
    frame_energy = band.sum(axis=0)
    energy_threshold = config.energy_gate_fraction * (frame_energy.max() if frame_energy.size else 0.0)
    times = librosa.frames_to_time(np.arange(S.shape[1]), sr=sr, hop_length=config.hop_length)
    samples: list[PitchSample] = []
    for frame_index, time in enumerate(times):
        column = band[:, frame_index]
        index = int(np.argmax(column))
        score = float(column[index] / (np.median(column) + 1e-12))
        frequency = None
        if frame_energy[frame_index] > energy_threshold and score >= score_threshold:
            # Quadratic interpolation in log magnitude for sub-bin frequency.
            delta = 0.0
            if 0 < index < len(column) - 1:
                left, center, right = np.log(column[index - 1 : index + 2] + 1e-12)
                denominator = left - 2.0 * center + right
                if abs(denominator) > 1e-12:
                    delta = 0.5 * (left - right) / denominator
            bin_width = freqs[1] - freqs[0]
            frequency = float(band_freqs[index] + delta * bin_width)
        samples.append(
            PitchSample(
                float(time),
                frequency,
                score,
                "dominant-spectral-ridge-peak-to-median-score",
            )
        )
    return PitchTrajectory("aigua.dominant-spectral-ridge/1", tuple(samples))


def extract_reference_ensemble(
    y: "object",
    sr: int,
    config: PitchExtractionConfig = PitchExtractionConfig(),
) -> tuple[PitchTrajectory, ...]:
    """Run the dependency-light Aigua reference ensemble."""
    return (
        shs_trajectory(y, sr, config),
        pyin_trajectory(y, sr, config),
        dominant_ridge_trajectory(y, sr, config),
    )
