"""Reference segmentation operators for the Aigua segmentation lattice."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

from .canonical import content_urn
from .segmentation import Segment


@dataclass(frozen=True, slots=True)
class SegmentationConfig:
    sample_rate: int = 48_000
    n_fft: int = 1024
    hop_length: int = 128
    band_low_hz: float = 900.0
    band_high_hz: float = 11_000.0
    noise_block_seconds: float = 2.0
    minimum_duration_seconds: float = 0.045
    merge_gap_seconds: float = 0.035
    maximum_duration_seconds: float = 1.6

    def __post_init__(self) -> None:
        if self.sample_rate <= 0 or self.n_fft <= 0 or self.hop_length <= 0:
            raise ValueError("sample rate, FFT size and hop length must be positive")
        if not (0 < self.band_low_hz < self.band_high_hz < self.sample_rate / 2):
            raise ValueError("analysis band must lie below Nyquist")
        if self.noise_block_seconds <= 0:
            raise ValueError("noise block must be positive")
        if not (0 < self.minimum_duration_seconds <= self.maximum_duration_seconds):
            raise ValueError("invalid duration range")
        if self.merge_gap_seconds < 0:
            raise ValueError("merge gap must be non-negative")


@dataclass(frozen=True, slots=True)
class ActivityTrace:
    times_seconds: tuple[float, ...]
    activity: tuple[float, ...]
    local_floor: tuple[float, ...]
    high_threshold: tuple[float, ...]
    low_threshold: tuple[float, ...]
    value_semantics: str


@dataclass(frozen=True, slots=True)
class SegmentationResult:
    run_id: str
    operator_id: str
    segments: tuple[Segment, ...]
    activity_trace: ActivityTrace
    parameters: dict[str, object]


def aigua_hysteresis_segmentation(
    y: "object",
    sr: int,
    config: SegmentationConfig,
    *,
    run_id: str = "aigua.hysteresis-segmentation/2",
    spectral_gate_alpha: float = 2.4,
) -> SegmentationResult:
    """A typed, non-mutating form of the historical Aigua detector."""
    import librosa
    import numpy as np
    import scipy.signal as signal

    band = _bandpass(np.asarray(y, dtype=float), sr, config.band_low_hz, config.band_high_hz)
    S = librosa.stft(band, n_fft=config.n_fft, hop_length=config.hop_length)
    magnitude, phase = np.abs(S), np.angle(S)
    block_frames = max(1, int(round(config.noise_block_seconds * sr / config.hop_length)))
    noise = _blockwise_percentile_2d(magnitude, 15.0, block_frames)
    gain = np.clip((magnitude - spectral_gate_alpha * noise) / (magnitude + 1e-12), 0.0, 1.0)
    gain = signal.medfilt2d(gain.astype(np.float32), kernel_size=(3, 5))
    clean = librosa.istft(
        magnitude * gain * np.exp(1j * phase),
        hop_length=config.hop_length,
        length=len(band),
    )
    rms = librosa.feature.rms(
        y=clean,
        frame_length=config.n_fft,
        hop_length=config.hop_length,
        center=True,
    )[0]
    activity = 20.0 * np.log10(rms + 1e-12)
    times = librosa.frames_to_time(np.arange(len(activity)), sr=sr, hop_length=config.hop_length)
    return _hysteresis_result(
        activity,
        times,
        config,
        run_id=run_id,
        operator_id="aigua.local-floor-hysteresis/2",
        floor_quantile=30.0,
        peak_quantile=99.0,
        high_fraction=0.38,
        low_fraction=0.20,
        minimum_local_range=6.0,
        value_semantics="band-limited-spectrally-gated-frame-rms-dbfs",
        parameters={
            "spectralGateAlpha": spectral_gate_alpha,
            "noisePercentile": 15.0,
            "noiseBlockSeconds": config.noise_block_seconds,
        },
    )


def pcen_segmentation(
    y: "object",
    sr: int,
    config: SegmentationConfig,
    *,
    run_id: str = "aigua.pcen-segmentation/1",
    mel_bins: int = 64,
) -> SegmentationResult:
    """Independent PCEN-based event proposal lane.

    The detector uses the high quantile across PCEN mel bands as its activity
    trace.  It is intentionally independent of the historical spectral gate,
    giving the reconciliation layer a meaningful alternative rather than a
    cosmetic reimplementation.
    """
    import librosa
    import numpy as np

    signal = np.asarray(y, dtype=float)
    mel = librosa.feature.melspectrogram(
        y=signal,
        sr=sr,
        n_fft=config.n_fft,
        hop_length=config.hop_length,
        n_mels=mel_bins,
        fmin=config.band_low_hz,
        fmax=config.band_high_hz,
        power=1.0,
    )
    pcen = librosa.pcen(mel * (2.0 ** 31), sr=sr, hop_length=config.hop_length)
    # A sparse tonal chirp may occupy only a few mel bands; the 90th percentile
    # is more sensitive than a mean while remaining less brittle than max.
    activity_linear = np.percentile(pcen, 90.0, axis=0)
    activity = 20.0 * np.log10(activity_linear + 1e-8)
    times = librosa.frames_to_time(np.arange(len(activity)), sr=sr, hop_length=config.hop_length)
    return _hysteresis_result(
        activity,
        times,
        config,
        run_id=run_id,
        operator_id="aigua.pcen-activity-hysteresis/1",
        floor_quantile=30.0,
        peak_quantile=98.0,
        high_fraction=0.42,
        low_fraction=0.22,
        minimum_local_range=3.0,
        value_semantics="pcen-mel-band-90th-percentile-db",
        parameters={"melBins": mel_bins, "pcenScale": 2.0 ** 31},
    )


def _hysteresis_result(
    activity: "object",
    times: "object",
    config: SegmentationConfig,
    *,
    run_id: str,
    operator_id: str,
    floor_quantile: float,
    peak_quantile: float,
    high_fraction: float,
    low_fraction: float,
    minimum_local_range: float,
    value_semantics: str,
    parameters: dict[str, object],
) -> SegmentationResult:
    import numpy as np

    values = np.asarray(activity, dtype=float)
    frame_times = np.asarray(times, dtype=float)
    block_frames = max(1, int(round(config.noise_block_seconds * config.sample_rate / config.hop_length)))
    floor = _blockwise_percentile_1d(values, floor_quantile, block_frames)
    peak = _blockwise_percentile_1d(values, peak_quantile, block_frames)
    local_range = np.maximum(peak - floor, minimum_local_range)
    high = floor + high_fraction * local_range
    low = floor + low_fraction * local_range
    active = np.zeros(len(values), dtype=bool)
    on = False
    for index, value in enumerate(values):
        if not on and value > high[index]:
            on = True
        elif on and value < low[index]:
            on = False
        active[index] = on
    # Include the lower-threshold attack immediately preceding each high-gate
    # crossing, matching the scientific intent of the v1 implementation.
    for index in range(1, len(active)):
        if active[index] and not active[index - 1]:
            cursor = index
            while cursor > 0 and values[cursor - 1] > low[cursor - 1]:
                cursor -= 1
                active[cursor] = True

    intervals = _active_intervals(active, frame_times)
    intervals = _merge_intervals(intervals, config.merge_gap_seconds)
    split: list[tuple[float, float]] = []
    for start, end in intervals:
        if end - start > config.maximum_duration_seconds:
            split.extend(
                _split_long_interval(
                    start,
                    end,
                    values,
                    frame_times,
                    sr=config.sample_rate,
                    hop_length=config.hop_length,
                )
            )
        else:
            split.append((start, end))
    split = [interval for interval in split if interval[1] - interval[0] >= config.minimum_duration_seconds]
    segments = []
    for index, (start, end) in enumerate(split):
        identity = {"runId": run_id, "index": index, "start": start, "end": end}
        segments.append(
            Segment(
                content_urn("segment", identity),
                run_id,
                float(start),
                float(end),
            )
        )
    return SegmentationResult(
        run_id,
        operator_id,
        tuple(segments),
        ActivityTrace(
            tuple(float(item) for item in frame_times),
            tuple(float(item) for item in values),
            tuple(float(item) for item in floor),
            tuple(float(item) for item in high),
            tuple(float(item) for item in low),
            value_semantics,
        ),
        {
            **parameters,
            "floorQuantile": floor_quantile,
            "peakQuantile": peak_quantile,
            "highFraction": high_fraction,
            "lowFraction": low_fraction,
            "minimumLocalRange": minimum_local_range,
            "minimumDurationSeconds": config.minimum_duration_seconds,
            "mergeGapSeconds": config.merge_gap_seconds,
            "maximumDurationSeconds": config.maximum_duration_seconds,
        },
    )


def _bandpass(y: "object", sr: int, low: float, high: float) -> "object":
    import numpy as np
    import scipy.signal as signal

    sos = signal.butter(6, [low, high], btype="bandpass", fs=sr, output="sos")
    return signal.sosfiltfilt(sos, np.asarray(y, dtype=float))


def _blockwise_percentile_1d(values: "object", quantile: float, block: int) -> "object":
    import numpy as np

    array = np.asarray(values, dtype=float)
    centers: list[float] = []
    estimates: list[float] = []
    for start in range(0, len(array), block):
        end = min(len(array), start + block)
        centers.append((start + end - 1) / 2.0)
        estimates.append(float(np.percentile(array[start:end], quantile)))
    if len(centers) == 1:
        return np.repeat(estimates[0], len(array))
    return np.interp(np.arange(len(array)), np.asarray(centers), np.asarray(estimates))


def _blockwise_percentile_2d(values: "object", quantile: float, block: int) -> "object":
    import numpy as np

    array = np.asarray(values)
    centers: list[float] = []
    estimates: list[object] = []
    for start in range(0, array.shape[1], block):
        end = min(array.shape[1], start + block)
        centers.append((start + end - 1) / 2.0)
        estimates.append(np.percentile(array[:, start:end], quantile, axis=1))
    stacked = np.stack(estimates, axis=1)
    if len(centers) == 1:
        return np.repeat(stacked, array.shape[1], axis=1)
    out = np.empty_like(array, dtype=float)
    for bin_index in range(array.shape[0]):
        out[bin_index] = np.interp(np.arange(array.shape[1]), centers, stacked[bin_index])
    return out


def _active_intervals(active: "object", times: "object") -> list[tuple[float, float]]:
    intervals: list[tuple[float, float]] = []
    index = 0
    while index < len(active):
        if not bool(active[index]):
            index += 1
            continue
        end = index
        while end < len(active) and bool(active[end]):
            end += 1
        end_index = min(end, len(times) - 1)
        intervals.append((float(times[index]), float(times[end_index])))
        index = end
    return intervals


def _merge_intervals(
    intervals: Sequence[tuple[float, float]], gap_seconds: float
) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for start, end in intervals:
        if merged and start - merged[-1][1] < gap_seconds:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _split_long_interval(
    start: float,
    end: float,
    activity: "object",
    times: "object",
    *,
    sr: int,
    hop_length: int,
) -> list[tuple[float, float]]:
    import numpy as np
    import scipy.signal as signal

    begin_index = max(0, int(round(start * sr / hop_length)))
    end_index = min(len(activity), int(round(end * sr / hop_length)))
    segment = np.asarray(activity[begin_index:end_index], dtype=float)
    if len(segment) < 20:
        return [(start, end)]
    window = min(51, len(segment) if len(segment) % 2 else len(segment) - 1)
    if window < 5:
        return [(start, end)]
    smooth = signal.savgol_filter(segment, window, 2)
    peaks, _ = signal.find_peaks(
        -smooth,
        distance=max(1, int(0.09 * sr / hop_length)),
        prominence=0.30 * (smooth.max() - smooth.min() + 1e-9),
    )
    if len(peaks) == 0:
        return [(start, end)]
    cuts = [start] + [float(times[min(begin_index + int(peak), len(times) - 1)]) for peak in peaks] + [end]
    return list(zip(cuts[:-1], cuts[1:]))
