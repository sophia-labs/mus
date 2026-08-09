"""Perceptually grounded analysis for MUS audio objects.

The module keeps three epistemic layers separate:

* physical/engineering descriptors computed directly from digital samples;
* auditory and psychoacoustic *proxies* that are meaningful for relative
  comparison but are not standardised psychophysical quantities;
* calibration-gated standard metrics delegated to a pinned MoSQITo operator.

A digital waveform is never silently interpreted as pascals.  ISO/ECMA-style
metrics are only attempted when a pressure calibration is supplied explicitly.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from io import BytesIO
import importlib.metadata
import math
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "https://sophia-labs.ai/schemas/mus-psychoacoustic-report/1"


@dataclass(frozen=True, slots=True)
class CalibrationSpec:
    """How digital samples are related to acoustic pressure.

    ``relative`` means that only digital and normalised relative measures are
    defensible.  ``pascal-per-digital-unit`` makes one sample unit equal to the
    declared pressure and enables calibrated sound-quality models.

    ``reference-rms`` is a convenience form: a signal whose digital RMS is
    ``reference_rms_dbfs`` is declared to correspond to ``reference_spl_db``.
    """

    kind: str = "relative"
    pascal_per_digital_unit: float | None = None
    reference_rms_dbfs: float | None = None
    reference_spl_db: float | None = None
    reference_pressure_pa: float = 20e-6
    field_type: str = "free"
    note: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"relative", "pascal-per-digital-unit", "reference-rms"}:
            raise ValueError("unsupported calibration kind")
        if self.field_type not in {"free", "diffuse"}:
            raise ValueError("field_type must be 'free' or 'diffuse'")
        if self.kind == "pascal-per-digital-unit":
            if self.pascal_per_digital_unit is None or self.pascal_per_digital_unit <= 0:
                raise ValueError("pascal_per_digital_unit must be positive")
        if self.kind == "reference-rms":
            if self.reference_rms_dbfs is None or self.reference_spl_db is None:
                raise ValueError("reference-rms calibration requires both reference values")
        if self.reference_pressure_pa <= 0:
            raise ValueError("reference_pressure_pa must be positive")

    @property
    def calibrated(self) -> bool:
        return self.kind != "relative"

    def pressure_scale(self) -> float | None:
        if self.kind == "relative":
            return None
        if self.kind == "pascal-per-digital-unit":
            return float(self.pascal_per_digital_unit)
        assert self.reference_rms_dbfs is not None
        assert self.reference_spl_db is not None
        digital_rms = 10.0 ** (self.reference_rms_dbfs / 20.0)
        pressure_rms = self.reference_pressure_pa * 10.0 ** (self.reference_spl_db / 20.0)
        return pressure_rms / max(digital_rms, 1e-15)


@dataclass(frozen=True, slots=True)
class Metric:
    metric_id: str
    label: str
    value: float | None
    unit: str | None
    status: str
    evidence_kind: str
    operator: str
    construct: str | None = None
    summary: Mapping[str, float] = field(default_factory=dict)
    caveats: tuple[str, ...] = ()
    score_semantics: str | None = None


@dataclass(frozen=True, slots=True)
class Trajectory:
    trajectory_id: str
    label: str
    unit: str | None
    times_seconds: tuple[float, ...]
    values: tuple[float | None, ...]
    operator: str
    evidence_kind: str
    construct: str | None = None


@dataclass(frozen=True, slots=True)
class PsychoacousticReport:
    source_id: str
    sample_rate: int
    duration_seconds: float
    calibration: CalibrationSpec
    metrics: tuple[Metric, ...]
    trajectories: tuple[Trajectory, ...]
    manipulation_axes: Mapping[str, Mapping[str, Any]]
    diagnostics: tuple[Mapping[str, Any], ...] = ()
    implementation: Mapping[str, str] = field(default_factory=dict)
    schema: str = SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


def load_mono(path: str | Path, *, sample_rate: int | None = None) -> tuple[Any, int]:
    """Load an audio file as finite mono float64 samples.

    libsndfile is used first.  When it cannot decode a container such as AAC in
    M4A, the function falls back to a real ``ffmpeg`` decode into an in-memory
    float WAV.  The fallback is explicit and fails loudly when ffmpeg is absent;
    it never substitutes silence or an empty object.
    """
    np, _, _, sf = _audio_dependencies()
    source = Path(path)
    try:
        y, sr = sf.read(str(source), always_2d=True, dtype="float64")
    except Exception as soundfile_error:
        command = [
            "ffmpeg", "-nostdin", "-v", "error", "-i", str(source),
            "-f", "wav", "-acodec", "pcm_f32le", "-ac", "1",
        ]
        if sample_rate is not None:
            command.extend(["-ar", str(int(sample_rate))])
        command.append("pipe:1")
        try:
            decoded = subprocess.run(command, capture_output=True, check=False, timeout=300)
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"libsndfile could not decode {source.name}, and ffmpeg is not installed: {soundfile_error}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"ffmpeg timed out while decoding {source.name}") from exc
        if decoded.returncode != 0 or not decoded.stdout:
            detail = decoded.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"could not decode {source.name}; libsndfile: {soundfile_error}; ffmpeg: {detail or decoded.returncode}"
            )
        y, sr = sf.read(BytesIO(decoded.stdout), always_2d=True, dtype="float64")
    if y.size == 0:
        raise ValueError("audio file is empty")
    y = np.mean(y, axis=1)
    if not np.all(np.isfinite(y)):
        raise ValueError("audio contains NaN or infinite samples")
    if sample_rate is not None and int(sample_rate) != int(sr):
        _, _, librosa, _ = _audio_dependencies()
        y = librosa.resample(y, orig_sr=int(sr), target_sr=int(sample_rate), res_type="soxr_hq")
        sr = int(sample_rate)
    return y.astype(np.float64, copy=False), int(sr)


def analyze_file(
    path: str | Path,
    *,
    calibration: CalibrationSpec | None = None,
    sample_rate: int | None = None,
    include_standardized: bool = True,
    max_trajectory_points: int = 2048,
) -> PsychoacousticReport:
    y, sr = load_mono(path, sample_rate=sample_rate)
    digest = sha256(Path(path).read_bytes()).hexdigest()
    return analyze_signal(
        y,
        sr,
        source_id=f"urn:sophia:mus:audio:sha256:{digest}",
        calibration=calibration,
        include_standardized=include_standardized,
        max_trajectory_points=max_trajectory_points,
    )


def analyze_signal(
    signal: Any,
    sample_rate: int,
    *,
    source_id: str = "urn:sophia:mus:audio:in-memory",
    calibration: CalibrationSpec | None = None,
    include_standardized: bool = True,
    max_trajectory_points: int = 2048,
) -> PsychoacousticReport:
    """Compute an operational psychoacoustic report.

    Relative metrics are always produced.  Standard metrics are produced only
    when the signal is calibrated to pascals and MoSQITo is importable; all
    refusal states are returned as typed metric rows rather than exceptions.
    """
    np, scipy_signal, librosa, _ = _audio_dependencies()
    y = np.asarray(signal, dtype=np.float64).reshape(-1)
    if y.size < 32:
        raise ValueError("audio signal is too short")
    if sample_rate < 8000:
        raise ValueError("sample_rate must be at least 8 kHz")
    if not np.all(np.isfinite(y)):
        raise ValueError("audio contains NaN or infinite samples")
    calibration = calibration or CalibrationSpec()
    duration = y.size / float(sample_rate)
    diagnostics: list[Mapping[str, Any]] = []

    frame_length = _power_of_two_near(max(512, int(round(0.046 * sample_rate))))
    frame_length = min(frame_length, max(64, _largest_power_of_two(y.size)))
    hop = max(1, frame_length // 4)
    stft = librosa.stft(y, n_fft=frame_length, hop_length=hop, window="hann", center=True)
    magnitude = np.abs(stft)
    power = magnitude**2
    freqs = librosa.fft_frequencies(sr=sample_rate, n_fft=frame_length)
    frame_times = librosa.frames_to_time(np.arange(power.shape[1]), sr=sample_rate, hop_length=hop)
    eps = 1e-15

    rms_frames = librosa.feature.rms(S=magnitude, frame_length=frame_length, hop_length=hop)[0]
    rms_dbfs = 20.0 * np.log10(np.maximum(rms_frames, eps))
    active = rms_dbfs > float(np.max(rms_dbfs) - 50.0)
    if not np.any(active):
        active = np.ones_like(rms_dbfs, dtype=bool)

    centroid = librosa.feature.spectral_centroid(S=magnitude, sr=sample_rate)[0]
    bandwidth = librosa.feature.spectral_bandwidth(S=magnitude, sr=sample_rate)[0]
    rolloff95 = librosa.feature.spectral_rolloff(S=magnitude, sr=sample_rate, roll_percent=0.95)[0]
    flatness = librosa.feature.spectral_flatness(S=np.maximum(power, eps))[0]
    flux = _spectral_flux(power)
    bark_axis, bark_energy, bark_envelopes = _bark_representation(power, freqs)
    sharpness_proxy = _relative_sharpness_proxy(bark_axis, bark_energy)
    roughness_proxy, fluctuation_proxy, modulation_peak_hz = _modulation_proxies(
        bark_envelopes,
        sample_rate / hop,
        bark_energy,
    )
    env = _smoothed_envelope(y, sample_rate)
    attack_seconds = _attack_time(env, sample_rate)
    temporal_centroid_seconds = _temporal_centroid(env, sample_rate)
    spectral_slope = _spectral_slope_db_per_octave(magnitude, freqs, active)
    harmonic_ratio, pitch_salience = _harmonicity_and_pitch_salience(y, sample_rate)
    tonal_prominence_db, tonal_peak_count = _relative_tonal_prominence(magnitude, freqs, active)

    peak = float(np.max(np.abs(y)))
    whole_rms = float(np.sqrt(np.mean(y**2)))
    true_peak = _true_peak(y, sample_rate)
    lufs_value, lufs_caveat = _programme_loudness(y, sample_rate)
    if lufs_caveat:
        diagnostics.append({"code": "MUSP-LUFS-UNAVAILABLE", "message": lufs_caveat, "severity": "info"})

    metrics: list[Metric] = [
        Metric("digital.rms-dbfs", "Digital RMS", _db(whole_rms), "dBFS", "available", "directly-measured", "mus.digital-rms/1"),
        Metric("digital.peak-dbfs", "Sample peak", _db(peak), "dBFS", "available", "directly-measured", "mus.sample-peak/1"),
        Metric("digital.true-peak-dbfs", "Approximate 4× true peak", _db(true_peak), "dBTP", "available", "deterministically-computed", "mus.true-peak-4x/1", caveats=("Four-times oversampling is an engineering approximation, not a conformance certificate.",)),
        Metric("digital.crest-factor-db", "Crest factor", _db(peak / max(whole_rms, eps)), "dB", "available", "deterministically-computed", "mus.crest-factor/1"),
        Metric("programme.integrated-loudness", "Integrated programme loudness", lufs_value, "LUFS", "available" if lufs_value is not None else "unavailable", "deterministically-computed", "pyloudnorm.bs1770", construct="ProgrammeLoudness", caveats=(("Programme loudness is not ISO psychoacoustic loudness in sones.",) if lufs_value is not None else (lufs_caveat or "pyloudnorm unavailable",))),
        Metric("spectrum.centroid-hz", "Spectral centroid", _median(centroid[active]), "Hz", "available", "deterministically-computed", "librosa.spectral-centroid", construct="PhysicalSpectralDistribution", caveats=("Spectral centroid is not equivalent to perceived brightness.",)),
        Metric("spectrum.bandwidth-hz", "Spectral bandwidth", _median(bandwidth[active]), "Hz", "available", "deterministically-computed", "librosa.spectral-bandwidth"),
        Metric("spectrum.rolloff95-hz", "95% spectral rolloff", _median(rolloff95[active]), "Hz", "available", "deterministically-computed", "librosa.spectral-rolloff"),
        Metric("spectrum.flatness", "Spectral flatness", _median(flatness[active]), "ratio", "available", "deterministically-computed", "librosa.spectral-flatness"),
        Metric("spectrum.slope-db-per-octave", "Spectral slope", spectral_slope, "dB/octave", "available", "statistically-estimated", "mus.log-frequency-spectral-slope/1"),
        Metric("temporal.attack-10-90-seconds", "Initial attack time, 10–90%", attack_seconds, "s", "available", "deterministically-computed", "mus.initial-attack/1", caveats=("For long scenes this describes the first dominant onset, not every event.",)),
        Metric("temporal.centroid-seconds", "Temporal energy centroid", temporal_centroid_seconds, "s", "available", "deterministically-computed", "mus.temporal-centroid/1"),
        Metric("auditory.relative-sharpness", "Relative auditory sharpness proxy", sharpness_proxy, "relative-acum-proxy", "proxy", "model-inferred", "mus.bark-sharpness-proxy/1", construct="PsychoacousticSharpness", caveats=("This is an uncalibrated Bark-energy proxy, not DIN 45692 sharpness.",)),
        Metric("auditory.roughness-proxy", "Auditory-band roughness proxy", roughness_proxy, "relative", "proxy", "model-inferred", "mus.bark-modulation-proxy/1", construct="PsychoacousticRoughness", caveats=("This is modulation energy weighted around 70 Hz, not Daniel–Weber asper.",)),
        Metric("auditory.fluctuation-proxy", "Auditory-band fluctuation proxy", fluctuation_proxy, "relative", "proxy", "model-inferred", "mus.bark-modulation-proxy/1", construct="FluctuationStrength", caveats=("This is modulation energy weighted around 4 Hz, not a standard vacil value.",)),
        Metric("auditory.modulation-peak-hz", "Dominant auditory-envelope modulation rate", modulation_peak_hz, "Hz", "proxy", "statistically-estimated", "mus.bark-modulation-spectrum/1"),
        Metric("auditory.harmonic-energy-ratio", "HPSS harmonic energy ratio", harmonic_ratio, "ratio", "proxy", "model-inferred", "librosa.hpss", construct="Harmonicity", caveats=("HPSS component ratio is not a universal perceptual harmonicity metric.",)),
        Metric("auditory.pitch-salience-proxy", "Median pYIN voiced probability", pitch_salience, "probability", "proxy" if pitch_salience is not None else "unavailable", "model-inferred", "librosa.pyin", construct="PitchSalience", score_semantics="pYIN voiced probability", caveats=("The estimator was not trained specifically for every source class.",)),
        Metric("auditory.tonal-prominence-proxy-db", "Relative spectral peak prominence", tonal_prominence_db, "dB", "proxy" if tonal_prominence_db is not None else "unavailable", "statistically-estimated", "mus.relative-tonal-prominence/1", construct="Tonality", caveats=("This relative spectral peak model is not ECMA prominence ratio or tone-to-noise ratio.",)),
        Metric("auditory.tonal-peak-count", "Relative prominent spectral peak count", float(tonal_peak_count), "count", "proxy", "statistically-estimated", "mus.relative-tonal-prominence/1", construct="Tonality"),
    ]

    trajectories: list[Trajectory] = [
        _trajectory("digital.rms-dbfs", "Frame RMS", "dBFS", frame_times, rms_dbfs, "librosa.rms", max_trajectory_points),
        _trajectory("spectrum.centroid-hz", "Spectral centroid", "Hz", frame_times, centroid, "librosa.spectral-centroid", max_trajectory_points, "PhysicalSpectralDistribution"),
        _trajectory("spectrum.flatness", "Spectral flatness", "ratio", frame_times, flatness, "librosa.spectral-flatness", max_trajectory_points),
        _trajectory("spectrum.flux", "Spectral flux", "relative", frame_times, flux, "mus.spectral-flux/1", max_trajectory_points),
    ]

    if include_standardized:
        standard_metrics, standard_trajectories, standard_diagnostics = _standardized_metrics(
            y,
            sample_rate,
            calibration,
            max_trajectory_points=max_trajectory_points,
        )
        metrics.extend(standard_metrics)
        trajectories.extend(standard_trajectories)
        diagnostics.extend(standard_diagnostics)

    manipulation_axes = _manipulation_axes(metrics)
    implementation = {
        "numpy": _version("numpy"),
        "scipy": _version("scipy"),
        "librosa": _version("librosa"),
        "soundfile": _version("soundfile"),
        "pyloudnorm": _version("pyloudnorm"),
        "mosqito": _version("mosqito"),
    }
    return PsychoacousticReport(
        source_id=source_id,
        sample_rate=int(sample_rate),
        duration_seconds=float(duration),
        calibration=calibration,
        metrics=tuple(metrics),
        trajectories=tuple(trajectories),
        manipulation_axes=manipulation_axes,
        diagnostics=tuple(diagnostics),
        implementation=implementation,
    )


def metric_map(report: PsychoacousticReport | Mapping[str, Any]) -> dict[str, float | None]:
    """Return ``metric_id -> value`` for layout and UI code."""
    rows: Iterable[Any]
    if isinstance(report, PsychoacousticReport):
        rows = report.metrics
    else:
        rows = report.get("metrics", [])
    out: dict[str, float | None] = {}
    for row in rows:
        if isinstance(row, Metric):
            out[row.metric_id] = row.value
        elif isinstance(row, Mapping):
            metric_id = row.get("metric_id", row.get("metricId"))
            if isinstance(metric_id, str):
                value = row.get("value")
                out[metric_id] = float(value) if isinstance(value, (int, float)) else None
    return out


def _standardized_metrics(
    y: Any,
    sample_rate: int,
    calibration: CalibrationSpec,
    *,
    max_trajectory_points: int,
) -> tuple[list[Metric], list[Trajectory], list[Mapping[str, Any]]]:
    np, _, _, _ = _audio_dependencies()
    ids = (
        ("psychoacoustic.loudness-zwicker", "ISO 532-1 time-varying loudness", "sone", "PsychoacousticLoudness"),
        ("psychoacoustic.sharpness-din", "DIN 45692 sharpness", "acum", "PsychoacousticSharpness"),
        ("psychoacoustic.roughness-daniel-weber", "Daniel–Weber roughness", "asper", "PsychoacousticRoughness"),
        ("psychoacoustic.loudness-ecma-hms", "ECMA 418-2:2022 hearing-model loudness", "sone_HMS", "PsychoacousticLoudness"),
        ("psychoacoustic.roughness-ecma-hms", "ECMA 418-2:2022 hearing-model roughness", "asper_HMS", "PsychoacousticRoughness"),
        ("tonality.prominence-ratio-ecma", "ECMA 418-1 prominence ratio", "dB", "Tonality"),
        ("tonality.tone-to-noise-ratio-ecma", "ECMA 418-1 tone-to-noise ratio", "dB", "Tonality"),
    )
    if not calibration.calibrated:
        caveat = "Pressure calibration is required; digital full scale was not treated as pascals."
        return (
            [Metric(i, label, None, unit, "refused", "unresolved", "mosqito", construct=construct, caveats=(caveat,)) for i, label, unit, construct in ids],
            [],
            [{"code": "MUSP-CALIBRATION-REQUIRED", "message": caveat, "severity": "info"}],
        )
    try:
        from mosqito import sq_metrics as mosqito_metrics
        loudness_zwtv = mosqito_metrics.loudness_zwtv
        roughness_dw = mosqito_metrics.roughness_dw
        sharpness_din_tv = mosqito_metrics.sharpness_din_tv
    except Exception as exc:
        message = f"MoSQITo is unavailable: {type(exc).__name__}: {exc}"
        return (
            [Metric(i, label, None, unit, "unavailable", "unresolved", "mosqito>=1.2.1", construct=construct, caveats=(message,)) for i, label, unit, construct in ids],
            [],
            [{"code": "MUSP-MOSQITO-UNAVAILABLE", "message": message, "severity": "info"}],
        )

    scale = calibration.pressure_scale()
    assert scale is not None
    pressure = np.asarray(y, dtype=float) * scale
    metrics: list[Metric] = []
    trajectories: list[Trajectory] = []
    diagnostics: list[Mapping[str, Any]] = []

    try:
        loudness, specific, bark, times = loudness_zwtv(pressure, int(sample_rate), field_type=calibration.field_type)
        loudness = np.asarray(loudness, dtype=float).reshape(-1)
        metrics.append(_summary_metric("psychoacoustic.loudness-zwicker", "ISO 532-1 time-varying loudness", loudness, "sone", "mosqito.loudness_zwtv/1.2.1", "PsychoacousticLoudness"))
        trajectories.append(_trajectory("psychoacoustic.loudness-zwicker", "Time-varying loudness", "sone", times, loudness, "mosqito.loudness_zwtv/1.2.1", max_trajectory_points, "PsychoacousticLoudness"))
        specific = np.asarray(specific, dtype=float)
        if specific.ndim == 2 and specific.size:
            metrics.append(Metric("psychoacoustic.specific-loudness-peak-bark", "Bark band of maximum median specific loudness", float(np.asarray(bark)[int(np.argmax(np.median(specific, axis=1)))]), "Bark", "available", "model-inferred", "mosqito.loudness_zwtv/1.2.1", construct="SpecificLoudness"))
    except Exception as exc:
        diagnostics.append(_operator_failure("MUSP-LOUDNESS-FAILED", "MoSQITo loudness", exc))
        metrics.append(Metric(ids[0][0], ids[0][1], None, ids[0][2], "failed", "unresolved", "mosqito.loudness_zwtv/1.2.1", construct=ids[0][3], caveats=(str(exc),)))

    try:
        sharpness, times = sharpness_din_tv(pressure, int(sample_rate), weighting="din", field_type=calibration.field_type)
        sharpness = np.asarray(sharpness, dtype=float).reshape(-1)
        metrics.append(_summary_metric("psychoacoustic.sharpness-din", "DIN 45692 sharpness", sharpness, "acum", "mosqito.sharpness_din_tv/1.2.1", "PsychoacousticSharpness"))
        trajectories.append(_trajectory("psychoacoustic.sharpness-din", "Time-varying sharpness", "acum", times, sharpness, "mosqito.sharpness_din_tv/1.2.1", max_trajectory_points, "PsychoacousticSharpness"))
    except Exception as exc:
        diagnostics.append(_operator_failure("MUSP-SHARPNESS-FAILED", "MoSQITo sharpness", exc))
        metrics.append(Metric(ids[1][0], ids[1][1], None, ids[1][2], "failed", "unresolved", "mosqito.sharpness_din_tv/1.2.1", construct=ids[1][3], caveats=(str(exc),)))

    try:
        roughness, _, _, times = roughness_dw(pressure, int(sample_rate))
        roughness = np.asarray(roughness, dtype=float).reshape(-1)
        metrics.append(_summary_metric("psychoacoustic.roughness-daniel-weber", "Daniel–Weber roughness", roughness, "asper", "mosqito.roughness_dw/1.2.1", "PsychoacousticRoughness"))
        trajectories.append(_trajectory("psychoacoustic.roughness-daniel-weber", "Time-varying roughness", "asper", times, roughness, "mosqito.roughness_dw/1.2.1", max_trajectory_points, "PsychoacousticRoughness"))
    except Exception as exc:
        diagnostics.append(_operator_failure("MUSP-ROUGHNESS-FAILED", "MoSQITo roughness", exc))
        metrics.append(Metric(ids[2][0], ids[2][1], None, ids[2][2], "failed", "unresolved", "mosqito.roughness_dw/1.2.1", construct=ids[2][3], caveats=(str(exc),)))

    loudness_ecma = getattr(mosqito_metrics, "loudness_ecma", None)
    if loudness_ecma is None:
        metrics.append(_unavailable_metric(ids[3], "MoSQITo 1.2.1 does not expose loudness_ecma in this installation."))
    else:
        try:
            representative, time_values, _, _, time_axis = loudness_ecma(pressure, int(sample_rate))
            values = np.asarray(time_values, dtype=float).reshape(-1)
            times = _ecma_time_axis(time_axis, values.size)
            metric = _summary_metric(ids[3][0], ids[3][1], values, ids[3][2], "mosqito.loudness_ecma/1.2.1", ids[3][3])
            metrics.append(Metric(**{**asdict(metric), "value": _finite_scalar(representative, metric.value)}))
            trajectories.append(_trajectory(ids[3][0], "ECMA hearing-model loudness over time", ids[3][2], times, values, "mosqito.loudness_ecma/1.2.1", max_trajectory_points, ids[3][3]))
        except Exception as exc:
            diagnostics.append(_operator_failure("MUSP-LOUDNESS-ECMA-FAILED", "MoSQITo ECMA loudness", exc))
            metrics.append(_failed_metric(ids[3], "mosqito.loudness_ecma/1.2.1", exc))

    roughness_ecma = getattr(mosqito_metrics, "roughness_ecma", None)
    if roughness_ecma is None:
        metrics.append(_unavailable_metric(ids[4], "MoSQITo 1.2.1 does not expose roughness_ecma in this installation."))
    else:
        try:
            representative, time_values, _, _, times = roughness_ecma(pressure, int(sample_rate))
            values = np.asarray(time_values, dtype=float).reshape(-1)
            metric = _summary_metric(ids[4][0], ids[4][1], values, ids[4][2], "mosqito.roughness_ecma/1.2.1", ids[4][3])
            metrics.append(Metric(**{**asdict(metric), "value": _finite_scalar(representative, metric.value)}))
            trajectories.append(_trajectory(ids[4][0], "ECMA hearing-model roughness over time", ids[4][2], times, values, "mosqito.roughness_ecma/1.2.1", max_trajectory_points, ids[4][3]))
        except Exception as exc:
            diagnostics.append(_operator_failure("MUSP-ROUGHNESS-ECMA-FAILED", "MoSQITo ECMA roughness", exc))
            metrics.append(_failed_metric(ids[4], "mosqito.roughness_ecma/1.2.1", exc))

    for index, attribute, operator_id in (
        (5, "pr_ecma_st", "mosqito.pr_ecma_st/1.2.1"),
        (6, "tnr_ecma_st", "mosqito.tnr_ecma_st/1.2.1"),
    ):
        operator = getattr(mosqito_metrics, attribute, None)
        if operator is None:
            metrics.append(_unavailable_metric(ids[index], f"MoSQITo does not expose {attribute} in this installation."))
            continue
        try:
            total, values, prominent, frequencies = operator(pressure, int(sample_rate), prominence=True)
            total_value = _finite_scalar(total, None)
            values = np.asarray(values, dtype=float).reshape(-1)
            frequencies = np.asarray(frequencies, dtype=float).reshape(-1)
            prominent = np.asarray(prominent, dtype=bool).reshape(-1)
            summary = {
                "detectedToneCount": float(values.size),
                "prominentToneCount": float(np.sum(prominent)),
            }
            if values.size:
                summary["maximumToneMetricDb"] = float(np.nanmax(values))
            if frequencies.size:
                summary["strongestToneFrequencyHz"] = float(frequencies[int(np.nanargmax(values))]) if values.size == frequencies.size else float(frequencies[0])
            metrics.append(Metric(ids[index][0], ids[index][1], total_value, ids[index][2], "available", "model-inferred", operator_id, construct=ids[index][3], summary=summary, caveats=("Stationary ECMA tonal-component analysis over the complete object.",)))
        except Exception as exc:
            diagnostics.append(_operator_failure(f"MUSP-{attribute.upper()}-FAILED", f"MoSQITo {attribute}", exc))
            metrics.append(_failed_metric(ids[index], operator_id, exc))
    return metrics, trajectories, diagnostics


def _failed_metric(spec: tuple[str, str, str, str], operator: str, exc: Exception) -> Metric:
    return Metric(spec[0], spec[1], None, spec[2], "failed", "unresolved", operator, construct=spec[3], caveats=(str(exc),))


def _unavailable_metric(spec: tuple[str, str, str, str], message: str) -> Metric:
    return Metric(spec[0], spec[1], None, spec[2], "unavailable", "unresolved", "mosqito>=1.2.1", construct=spec[3], caveats=(message,))


def _finite_scalar(value: Any, fallback: float | None) -> float | None:
    np, _, _, _ = _audio_dependencies()
    rows = np.asarray(value, dtype=float).reshape(-1)
    rows = rows[np.isfinite(rows)]
    return float(rows[0]) if rows.size else fallback


def _ecma_time_axis(value: Any, length: int) -> Any:
    np, _, _, _ = _audio_dependencies()
    rows = np.asarray(value, dtype=float)
    if rows.ndim > 1:
        rows = rows[0]
    rows = rows.reshape(-1)
    if rows.size == length:
        return rows
    if length <= 1:
        return np.asarray([0.0])
    maximum = float(rows[-1]) if rows.size else float(length - 1)
    return np.linspace(0.0, maximum, length)


def _summary_metric(metric_id: str, label: str, values: Any, unit: str, operator: str, construct: str) -> Metric:
    np, _, _, _ = _audio_dependencies()
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return Metric(metric_id, label, None, unit, "failed", "unresolved", operator, construct=construct, caveats=("Operator returned no finite values.",))
    summary = {
        "minimum": float(np.min(finite)),
        "p05": float(np.percentile(finite, 5)),
        "median": float(np.median(finite)),
        "mean": float(np.mean(finite)),
        "p95": float(np.percentile(finite, 95)),
        "maximum": float(np.max(finite)),
    }
    return Metric(metric_id, label, summary["median"], unit, "available", "model-inferred", operator, construct=construct, summary=summary)


def _trajectory(
    trajectory_id: str,
    label: str,
    unit: str | None,
    times: Any,
    values: Any,
    operator: str,
    maximum_points: int,
    construct: str | None = None,
) -> Trajectory:
    np, _, _, _ = _audio_dependencies()
    t = np.asarray(times, dtype=float).reshape(-1)
    v = np.asarray(values, dtype=float).reshape(-1)
    n = min(t.size, v.size)
    t, v = t[:n], v[:n]
    if n > maximum_points:
        idx = np.linspace(0, n - 1, maximum_points).round().astype(int)
        t, v = t[idx], v[idx]
    value_rows = tuple(None if not math.isfinite(float(item)) else float(item) for item in v)
    return Trajectory(
        trajectory_id=trajectory_id,
        label=label,
        unit=unit,
        times_seconds=tuple(float(item) for item in t),
        values=value_rows,
        operator=operator,
        evidence_kind="model-inferred" if construct else "deterministically-computed",
        construct=construct,
    )


def _bark_representation(power: Any, freqs: Any) -> tuple[Any, Any, Any]:
    np, _, _, _ = _audio_dependencies()
    freqs = np.asarray(freqs, dtype=float)
    bark = _hz_to_bark(freqs)
    centers = np.arange(0.5, 24.5, 0.5)
    filters = np.maximum(0.0, 1.0 - np.abs(bark[:, None] - centers[None, :]) / 0.75).T
    norm = np.sum(filters, axis=1, keepdims=True)
    filters = filters / np.maximum(norm, 1e-12)
    band_power = filters @ np.asarray(power, dtype=float)
    envelopes = np.sqrt(np.maximum(band_power, 0.0))
    energy = np.mean(band_power, axis=1)
    return centers, energy, envelopes


def _relative_sharpness_proxy(bark_axis: Any, bark_energy: Any) -> float:
    np, _, _, _ = _audio_dependencies()
    z = np.asarray(bark_axis, dtype=float)
    n_specific = np.sqrt(np.maximum(np.asarray(bark_energy, dtype=float), 0.0))
    weighting = np.where(z <= 15.8, 1.0, 0.066 * np.exp(0.171 * z))
    denominator = np.sum(n_specific) + 1e-15
    return float(0.11 * np.sum(n_specific * weighting * z) / denominator)


def _modulation_proxies(envelopes: Any, envelope_rate: float, band_energy: Any) -> tuple[float, float, float | None]:
    np, scipy_signal, _, _ = _audio_dependencies()
    env = np.asarray(envelopes, dtype=float)
    if env.shape[1] < 8 or envelope_rate <= 1:
        return 0.0, 0.0, None
    env = env / np.maximum(np.mean(env, axis=1, keepdims=True), 1e-12) - 1.0
    window = scipy_signal.windows.hann(env.shape[1], sym=False)
    spectrum = np.abs(np.fft.rfft(env * window[None, :], axis=1)) ** 2
    modulation_hz = np.fft.rfftfreq(env.shape[1], d=1.0 / envelope_rate)
    carrier_weights = np.asarray(band_energy, dtype=float)
    carrier_weights = carrier_weights / max(float(np.sum(carrier_weights)), 1e-15)
    aggregate = np.sum(spectrum * carrier_weights[:, None], axis=0)
    if aggregate.size:
        aggregate[0] = 0.0
    rough_weight = np.exp(-0.5 * (np.log2(np.maximum(modulation_hz, 1e-6) / 70.0) / 0.85) ** 2)
    rough_weight[(modulation_hz < 20.0) | (modulation_hz > 300.0)] = 0.0
    fluct_weight = np.exp(-0.5 * (np.log2(np.maximum(modulation_hz, 1e-6) / 4.0) / 1.05) ** 2)
    fluct_weight[(modulation_hz < 0.25) | (modulation_hz > 20.0)] = 0.0
    total = float(np.sum(aggregate)) + 1e-15
    roughness = float(np.sum(aggregate * rough_weight) / total)
    fluctuation = float(np.sum(aggregate * fluct_weight) / total)
    valid = (modulation_hz >= 0.25) & (modulation_hz <= min(300.0, envelope_rate / 2.0))
    peak = float(modulation_hz[np.where(valid)[0][int(np.argmax(aggregate[valid]))]]) if np.any(valid) else None
    return roughness, fluctuation, peak


def _harmonicity_and_pitch_salience(y: Any, sample_rate: int) -> tuple[float, float | None]:
    np, _, librosa, _ = _audio_dependencies()
    try:
        harmonic, _ = librosa.effects.hpss(np.asarray(y, dtype=float))
        harmonic_ratio = float(np.sum(harmonic**2) / max(float(np.sum(np.asarray(y) ** 2)), 1e-15))
    except Exception:
        harmonic_ratio = 0.0
    try:
        fmax = min(5000.0, sample_rate * 0.45)
        if fmax <= 50.0:
            return harmonic_ratio, None
        _, _, voiced = librosa.pyin(
            np.asarray(y, dtype=float),
            fmin=50.0,
            fmax=fmax,
            sr=sample_rate,
            frame_length=min(4096, _power_of_two_near(max(1024, int(sample_rate * 0.085)))),
            hop_length=max(128, int(sample_rate * 0.01)),
        )
        finite = np.asarray(voiced, dtype=float)
        finite = finite[np.isfinite(finite)]
        pitch_salience = float(np.median(finite)) if finite.size else None
    except Exception:
        pitch_salience = None
    return max(0.0, min(1.0, harmonic_ratio)), pitch_salience


def _relative_tonal_prominence(magnitude: Any, freqs: Any, active: Any) -> tuple[float | None, int]:
    np, scipy_signal, _, _ = _audio_dependencies()
    spectrum = np.median(np.asarray(magnitude, dtype=float)[:, active], axis=1)
    frequencies = np.asarray(freqs, dtype=float)
    keep = (frequencies >= 40.0) & (frequencies <= min(18000.0, float(frequencies[-1])))
    spectrum = spectrum[keep]
    if spectrum.size < 5 or not np.any(spectrum > 0):
        return None, 0
    db = 20.0 * np.log10(np.maximum(spectrum, 1e-15))
    # A broad median baseline prevents single-bin FFT leakage from becoming an
    # unbounded score while retaining an inspectable relative tonal cue.
    width = min(31, max(5, (len(db) // 30) * 2 + 1))
    baseline = scipy_signal.medfilt(db, kernel_size=width)
    residual = db - baseline
    peaks, properties = scipy_signal.find_peaks(residual, prominence=3.0)
    if peaks.size == 0:
        return 0.0, 0
    return float(np.max(properties["prominences"])), int(peaks.size)


def _spectral_flux(power: Any) -> Any:
    np, _, _, _ = _audio_dependencies()
    p = np.asarray(power, dtype=float)
    p = p / np.maximum(np.sum(p, axis=0, keepdims=True), 1e-15)
    diff = np.maximum(np.diff(p, axis=1, prepend=p[:, :1]), 0.0)
    return np.sqrt(np.sum(diff**2, axis=0))


def _spectral_slope_db_per_octave(magnitude: Any, freqs: Any, active: Any) -> float | None:
    np, _, _, _ = _audio_dependencies()
    spectrum = np.median(np.asarray(magnitude)[:, active], axis=1)
    frequencies = np.asarray(freqs, dtype=float)
    keep = (frequencies >= 80.0) & (frequencies <= max(100.0, frequencies[-1] * 0.95)) & (spectrum > 1e-12)
    if np.count_nonzero(keep) < 8:
        return None
    x = np.log2(frequencies[keep] / 1000.0)
    y = 20.0 * np.log10(spectrum[keep])
    slope, _ = np.polyfit(x, y, 1)
    return float(slope)


def _smoothed_envelope(y: Any, sample_rate: int) -> Any:
    np, scipy_signal, _, _ = _audio_dependencies()
    analytic = scipy_signal.hilbert(np.asarray(y, dtype=float))
    envelope = np.abs(analytic)
    width = max(3, int(round(sample_rate * 0.01)))
    kernel = np.ones(width, dtype=float) / width
    return np.convolve(envelope, kernel, mode="same")


def _attack_time(envelope: Any, sample_rate: int) -> float | None:
    np, _, _, _ = _audio_dependencies()
    env = np.asarray(envelope, dtype=float)
    if env.size == 0 or float(np.max(env)) <= 1e-12:
        return None
    peak_index = int(np.argmax(env))
    peak = float(env[peak_index])
    before = env[: peak_index + 1]
    ten = np.where(before >= 0.1 * peak)[0]
    ninety = np.where(before >= 0.9 * peak)[0]
    if ten.size == 0 or ninety.size == 0:
        return None
    return float(max(0, int(ninety[0]) - int(ten[0])) / sample_rate)


def _temporal_centroid(envelope: Any, sample_rate: int) -> float | None:
    np, _, _, _ = _audio_dependencies()
    energy = np.asarray(envelope, dtype=float) ** 2
    total = float(np.sum(energy))
    if total <= 1e-15:
        return None
    times = np.arange(energy.size, dtype=float) / sample_rate
    return float(np.sum(times * energy) / total)


def _programme_loudness(y: Any, sample_rate: int) -> tuple[float | None, str | None]:
    try:
        import pyloudnorm as pyln
        meter = pyln.Meter(int(sample_rate))
        value = float(meter.integrated_loudness(y))
        if not math.isfinite(value):
            return None, "Programme-loudness operator returned no finite value."
        return value, None
    except Exception as exc:
        return None, f"pyloudnorm is unavailable or refused the signal: {type(exc).__name__}: {exc}"


def _true_peak(y: Any, sample_rate: int) -> float:
    np, scipy_signal, _, _ = _audio_dependencies()
    if len(y) < 8:
        return float(np.max(np.abs(y)))
    up = scipy_signal.resample_poly(np.asarray(y, dtype=float), 4, 1)
    return float(np.max(np.abs(up)))


def _manipulation_axes(metrics: Sequence[Metric]) -> dict[str, Mapping[str, Any]]:
    values = {metric.metric_id: metric.value for metric in metrics}
    return {
        "loudness": {
            "current": values.get("programme.integrated-loudness"),
            "unit": "LUFS",
            "control": "gainDb or targetLufs",
            "claim": "Programme-level manipulation; not a promise of equal perceived loudness in every context.",
        },
        "brightness": {
            "current": values.get("spectrum.centroid-hz"),
            "supportingMetric": "spectrum.centroid-hz",
            "control": "brightnessDb",
            "claim": "High-shelf spectral-envelope intervention targeting brightness-related cues.",
        },
        "sharpness": {
            "current": values.get("psychoacoustic.sharpness-din") or values.get("auditory.relative-sharpness"),
            "control": "brightnessDb",
            "claim": "The same filter can alter sharpness, but brightness and sharpness remain distinct constructs.",
        },
        "roughness": {
            "current": values.get("psychoacoustic.roughness-daniel-weber") or values.get("auditory.roughness-proxy"),
            "control": "roughnessDepth and roughnessRateHz",
            "claim": "Audible-band amplitude modulation is an intervention on one major roughness cue, not a universal roughness dial.",
        },
        "fluctuation": {
            "current": values.get("auditory.fluctuation-proxy"),
            "control": "fluctuationDepth and fluctuationRateHz",
            "claim": "Slow amplitude modulation targets fluctuation/pulsation cues.",
        },
        "attack": {
            "current": values.get("temporal.attack-10-90-seconds"),
            "unit": "s",
            "control": "attackSeconds",
            "claim": "Envelope intervention over the object onset.",
        },
        "pitchSalience": {
            "current": values.get("auditory.pitch-salience-proxy"),
            "control": "tonalFocus and pitchSemitones",
            "claim": "Tonal/percussive balance and pitch transformation affect pitchability but do not guarantee a listener report.",
        },
    }


def _hz_to_bark(frequency: Any) -> Any:
    np, _, _, _ = _audio_dependencies()
    f = np.asarray(frequency, dtype=float)
    z = 26.81 * f / (1960.0 + f) - 0.53
    z = np.where(z < 2.0, z + 0.15 * (2.0 - z), z)
    z = np.where(z > 20.1, z + 0.22 * (z - 20.1), z)
    return np.maximum(z, 0.0)


def _median(values: Any) -> float | None:
    np, _, _, _ = _audio_dependencies()
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    return float(np.median(finite)) if finite.size else None


def _db(value: float) -> float:
    return float(20.0 * math.log10(max(float(value), 1e-15)))


def _largest_power_of_two(value: int) -> int:
    return 1 << max(0, int(value).bit_length() - 1)


def _power_of_two_near(value: int) -> int:
    if value <= 2:
        return 2
    lower = _largest_power_of_two(value)
    upper = lower * 2
    return lower if value - lower <= upper - value else upper


def _operator_failure(code: str, name: str, exc: Exception) -> Mapping[str, Any]:
    return {"code": code, "message": f"{name} failed: {type(exc).__name__}: {exc}", "severity": "warning"}


def _version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _audio_dependencies() -> tuple[Any, Any, Any, Any]:
    try:
        import numpy as np
        from scipy import signal as scipy_signal
        import librosa
        import soundfile as sf
    except Exception as exc:  # pragma: no cover - environment-specific
        raise RuntimeError("audio analysis requires the 'audio' optional dependencies") from exc
    return np, scipy_signal, librosa, sf
