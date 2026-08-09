"""Continuous gesture analysis for Aigua vocalizations.

The bundle preserves frame trajectories and derives compact summaries only from
explicitly valid frames.  It is designed to replace one-row-per-event thinking,
not merely add more scalar columns to it.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import median
from typing import Sequence

from .audio_pitch import PitchExtractionConfig, extract_reference_ensemble
from .pitch import ConsensusStatus, PitchConsensus, build_pitch_consensus, frequency_to_cents


@dataclass(frozen=True, slots=True)
class TrajectorySeries:
    property_id: str
    times_seconds: tuple[float, ...]
    values: tuple[float | None, ...]
    unit: str | None
    value_semantics: str

    def __post_init__(self) -> None:
        if len(self.times_seconds) != len(self.values):
            raise ValueError("trajectory times and values must have equal length")
        if list(self.times_seconds) != sorted(self.times_seconds):
            raise ValueError("trajectory times must be non-decreasing")


@dataclass(frozen=True, slots=True)
class ModulationSummary:
    dominant_rate_hz: float | None
    spectral_peak_to_median_score: float | None
    robust_modulation_index: float | None
    rate_search_range_hz: tuple[float, float]


@dataclass(frozen=True, slots=True)
class GestureSummary:
    duration_seconds: float
    attack_seconds: float | None
    release_seconds: float | None
    resolved_pitch_fraction: float
    median_pitch_hz: float | None
    pitch_span_semitones: float | None
    median_absolute_fm_velocity_semitones_per_second: float | None
    max_absolute_fm_velocity_semitones_per_second: float | None
    fm_inflection_count: int | None
    median_spectral_centroid_hz: float
    spectral_centroid_range_hz: float
    median_spectral_flatness: float
    amplitude_modulation: ModulationSummary


@dataclass(frozen=True, slots=True)
class GestureObservationBundle:
    schema: str
    trajectories: tuple[TrajectorySeries, ...]
    pitch_consensus: PitchConsensus
    summary: GestureSummary
    parameters: dict[str, object]


def analyze_gesture(
    y: "object",
    sr: int,
    config: PitchExtractionConfig,
    *,
    pitch_consensus: PitchConsensus | None = None,
    maximum_pitch_spread_cents: float = 100.0,
) -> GestureObservationBundle:
    import librosa
    import numpy as np

    signal = np.asarray(y, dtype=float)
    if signal.ndim != 1 or signal.size < config.n_fft:
        raise ValueError("gesture analysis requires a mono signal at least one FFT window long")
    S_complex = librosa.stft(
        signal,
        n_fft=config.n_fft,
        hop_length=config.hop_length,
        center=True,
    )
    magnitude = np.abs(S_complex)
    power = magnitude ** 2
    times = librosa.frames_to_time(
        np.arange(magnitude.shape[1]), sr=sr, hop_length=config.hop_length
    )
    rms = librosa.feature.rms(
        S=magnitude, frame_length=config.n_fft, hop_length=config.hop_length
    )[0]
    rms_dbfs = 20.0 * np.log10(rms + 1e-12)
    centroid = librosa.feature.spectral_centroid(S=magnitude, sr=sr)[0]
    bandwidth = librosa.feature.spectral_bandwidth(S=magnitude, sr=sr)[0]
    flatness = librosa.feature.spectral_flatness(S=magnitude)[0]
    rolloff = librosa.feature.spectral_rolloff(S=magnitude, sr=sr, roll_percent=0.95)[0]
    flux = np.concatenate([[0.0], np.sqrt(np.sum(np.diff(_unit_columns(magnitude), axis=1) ** 2, axis=0))])

    if pitch_consensus is None:
        ensemble = extract_reference_ensemble(signal, sr, config)
        pitch_consensus = build_pitch_consensus(
            ensemble,
            minimum_estimators=2,
            maximum_spread_cents=maximum_pitch_spread_cents,
            maximum_time_delta_seconds=0.5 * config.hop_length / sr,
        )
    pitch_by_time = {
        round(frame.time_seconds, 9): frame.frequency_hz
        for frame in pitch_consensus.frames
        if frame.status is ConsensusStatus.RESOLVED
    }
    pitch_values = tuple(pitch_by_time.get(round(float(time), 9)) for time in times)

    trajectories = (
        TrajectorySeries(
            "frameRmsDbfs",
            tuple(float(item) for item in times),
            tuple(float(item) for item in rms_dbfs),
            "dBFS",
            "frame RMS over the declared analysis STFT view",
        ),
        TrajectorySeries(
            "spectralCentroidHz",
            tuple(float(item) for item in times),
            tuple(float(item) for item in centroid),
            "Hz",
            "power-independent centroid of each magnitude-spectrum frame",
        ),
        TrajectorySeries(
            "spectralBandwidthHz",
            tuple(float(item) for item in times),
            tuple(float(item) for item in bandwidth),
            "Hz",
            "frame spectral bandwidth around centroid",
        ),
        TrajectorySeries(
            "spectralFlatness",
            tuple(float(item) for item in times),
            tuple(float(item) for item in flatness),
            "ratio",
            "geometric-to-arithmetic mean ratio per magnitude-spectrum frame",
        ),
        TrajectorySeries(
            "spectralRolloff95Hz",
            tuple(float(item) for item in times),
            tuple(float(item) for item in rolloff),
            "Hz",
            "frequency below which 95 percent of frame spectral energy lies",
        ),
        TrajectorySeries(
            "spectralFlux",
            tuple(float(item) for item in times),
            tuple(float(item) for item in flux),
            "euclidean-distance",
            "Euclidean distance between consecutive L2-normalized magnitude frames",
        ),
        TrajectorySeries(
            "consensusPitchHz",
            tuple(float(item) for item in times),
            pitch_values,
            "Hz",
            "frequency only where at least two reference estimators agree within tolerance",
        ),
    )

    attack, release = _attack_release(rms, config.hop_length / sr)
    fm = _fm_summary(times, pitch_values, config.hop_length / sr)
    modulation = _modulation_summary(signal, sr)
    resolved = [value for value in pitch_values if value is not None]
    summary = GestureSummary(
        duration_seconds=len(signal) / sr,
        attack_seconds=attack,
        release_seconds=release,
        resolved_pitch_fraction=len(resolved) / max(1, len(pitch_values)),
        median_pitch_hz=float(median(resolved)) if resolved else None,
        pitch_span_semitones=(
            12.0 * math.log2(max(resolved) / min(resolved)) if len(resolved) >= 2 else None
        ),
        median_absolute_fm_velocity_semitones_per_second=fm[0],
        max_absolute_fm_velocity_semitones_per_second=fm[1],
        fm_inflection_count=fm[2],
        median_spectral_centroid_hz=float(np.median(centroid)),
        spectral_centroid_range_hz=float(np.percentile(centroid, 95) - np.percentile(centroid, 5)),
        median_spectral_flatness=float(np.median(flatness)),
        amplitude_modulation=modulation,
    )
    return GestureObservationBundle(
        "mus-gesture-observation-bundle/1",
        trajectories,
        pitch_consensus,
        summary,
        {
            "sampleRate": sr,
            "nFft": config.n_fft,
            "hopLength": config.hop_length,
            "fminHz": config.fmin_hz,
            "fmaxHz": config.fmax_hz,
            "maximumPitchSpreadCents": maximum_pitch_spread_cents,
        },
    )


def _unit_columns(magnitude: "object") -> "object":
    import numpy as np

    norms = np.sqrt(np.sum(magnitude ** 2, axis=0, keepdims=True)) + 1e-12
    return magnitude / norms


def _attack_release(rms: "object", seconds_per_frame: float) -> tuple[float | None, float | None]:
    import numpy as np

    values = np.asarray(rms, dtype=float)
    if values.size == 0 or values.max() <= 0:
        return None, None
    peak_index = int(np.argmax(values))
    threshold = 0.1 * values[peak_index]
    before = np.where(values[: peak_index + 1] >= threshold)[0]
    after = np.where(values[peak_index:] <= threshold)[0]
    attack = (peak_index - int(before[0])) * seconds_per_frame if before.size else None
    release = int(after[0]) * seconds_per_frame if after.size else None
    return attack, release


def _fm_summary(
    times: Sequence[float],
    frequencies: Sequence[float | None],
    expected_step: float,
) -> tuple[float | None, float | None, int | None]:
    velocities: list[float] = []
    signed: list[float] = []
    for index in range(1, len(frequencies)):
        left, right = frequencies[index - 1], frequencies[index]
        dt = times[index] - times[index - 1]
        if left is None or right is None or dt <= 0 or dt > 1.6 * expected_step:
            continue
        velocity = (frequency_to_cents(right) - frequency_to_cents(left)) / 100.0 / dt
        velocities.append(abs(velocity))
        signed.append(velocity)
    if not velocities:
        return None, None, None
    # Ignore tiny sign changes that are likely estimator jitter rather than a
    # meaningful FM inflection.
    signs = [1 if value > 5.0 else -1 if value < -5.0 else 0 for value in signed]
    compact = [sign for sign in signs if sign]
    inflections = sum(compact[index] != compact[index - 1] for index in range(1, len(compact)))
    return float(median(velocities)), float(max(velocities)), inflections


def _modulation_summary(signal: "object", sr: int) -> ModulationSummary:
    import numpy as np
    import scipy.signal as scipy_signal

    envelope = np.abs(scipy_signal.hilbert(np.asarray(signal, dtype=float)))
    # Downsample the envelope after anti-alias filtering; 1 kHz retains the
    # declared 8--220 Hz modulation search range.
    target_rate = min(1000, sr)
    if target_rate < sr:
        divisor = max(1, sr // target_rate)
        envelope = scipy_signal.decimate(envelope, divisor, ftype="fir", zero_phase=True)
        envelope_rate = sr / divisor
    else:
        envelope_rate = sr
    low, high = 8.0, min(220.0, 0.45 * envelope_rate)
    if envelope.size < 32 or high <= low:
        return ModulationSummary(None, None, None, (low, high))
    centered = envelope - scipy_signal.savgol_filter(
        envelope,
        min(len(envelope) if len(envelope) % 2 else len(envelope) - 1, max(5, int(envelope_rate * 0.08) // 2 * 2 + 1)),
        2,
    )
    frequencies, power = scipy_signal.periodogram(centered, fs=envelope_rate, scaling="spectrum")
    mask = (frequencies >= low) & (frequencies <= high)
    if not np.any(mask) or power[mask].max() <= 0:
        rate = score = None
    else:
        local_power = power[mask]
        local_freqs = frequencies[mask]
        index = int(np.argmax(local_power))
        rate = float(local_freqs[index])
        score = float(local_power[index] / (np.median(local_power) + 1e-18))
    p05, p95 = np.percentile(envelope, [5, 95])
    modulation_index = float((p95 - p05) / (p95 + p05 + 1e-12))
    return ModulationSummary(rate, score, modulation_index, (low, high))

@dataclass(frozen=True, slots=True)
class PersistedGestureBundle:
    manifest: "object"
    arrays: tuple["object", ...]


def persist_gesture_bundle(
    store: "object",
    bundle: GestureObservationBundle,
    *,
    role_prefix: str = "gesture",
) -> PersistedGestureBundle:
    """Externalize frame trajectories as NPY artifacts and store a compact manifest."""
    import numpy as np

    from .arrays import put_array

    rows = []
    refs = []
    for trajectory in bundle.trajectories:
        times = put_array(
            store,
            np.asarray(trajectory.times_seconds, dtype=np.float64),
            role=f"{role_prefix}:{trajectory.property_id}:times",
        )
        values = put_array(
            store,
            np.asarray(
                [np.nan if value is None else value for value in trajectory.values],
                dtype=np.float64,
            ),
            role=f"{role_prefix}:{trajectory.property_id}:values",
            missing_value_semantics="unresolved-or-unavailable" if any(value is None for value in trajectory.values) else None,
        )
        refs.extend((times, values))
        rows.append(
            {
                "propertyId": trajectory.property_id,
                "unit": trajectory.unit,
                "valueSemantics": trajectory.value_semantics,
                "times": times,
                "values": values,
            }
        )
    manifest = store.put_json(
        {
            "schema": "mus-persisted-gesture-bundle/1",
            "summary": bundle.summary,
            "pitchConsensusSummary": bundle.pitch_consensus.summary,
            "parameters": bundle.parameters,
            "trajectories": rows,
        },
        role=f"{role_prefix}:manifest",
    )
    return PersistedGestureBundle(manifest, tuple(refs))
