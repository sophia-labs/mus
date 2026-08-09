"""Causal sound interventions for the MUS spatial canvas.

The controls target cues associated with perceptual constructs.  They are not
inverse psychophysical models: ``brightness_db=6`` means a six-decibel
high-shelf intervention, not "six units of experienced brightness".  Every
application returns an explicit receipt so the intervention can be analyzed,
auditioned, and compared with listener reports.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class PsychoacousticControls:
    gain_db: float = 0.0
    target_lufs: float | None = None
    brightness_db: float = 0.0
    brightness_hz: float = 2500.0
    roughness_depth: float = 0.0
    roughness_rate_hz: float = 70.0
    fluctuation_depth: float = 0.0
    fluctuation_rate_hz: float = 4.0
    attack_seconds: float | None = None
    pitch_semitones: float = 0.0
    tonal_focus: float = 0.0
    safety_peak: float = 0.98

    def __post_init__(self) -> None:
        for name in ("roughness_depth", "fluctuation_depth"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        if not -1.0 <= self.tonal_focus <= 1.0:
            raise ValueError("tonal_focus must be in [-1, 1]")
        if self.brightness_hz <= 0:
            raise ValueError("brightness_hz must be positive")
        if self.roughness_rate_hz <= 0 or self.fluctuation_rate_hz <= 0:
            raise ValueError("modulation rates must be positive")
        if self.attack_seconds is not None and self.attack_seconds < 0:
            raise ValueError("attack_seconds cannot be negative")
        if not 0 < self.safety_peak <= 1:
            raise ValueError("safety_peak must be in (0, 1]")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "PsychoacousticControls":
        if value is None:
            return cls()
        aliases = {
            "gainDb": "gain_db",
            "targetLufs": "target_lufs",
            "brightnessDb": "brightness_db",
            "brightnessHz": "brightness_hz",
            "roughnessDepth": "roughness_depth",
            "roughnessRateHz": "roughness_rate_hz",
            "fluctuationDepth": "fluctuation_depth",
            "fluctuationRateHz": "fluctuation_rate_hz",
            "attackSeconds": "attack_seconds",
            "pitchSemitones": "pitch_semitones",
            "tonalFocus": "tonal_focus",
            "safetyPeak": "safety_peak",
        }
        kwargs = {aliases.get(key, key): item for key, item in value.items()}
        allowed = set(cls.__dataclass_fields__)
        unknown = set(kwargs) - allowed
        if unknown:
            raise ValueError(f"unknown psychoacoustic controls: {sorted(unknown)}")
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True, slots=True)
class ManipulationReceipt:
    controls: PsychoacousticControls
    operations: tuple[Mapping[str, Any], ...]
    input_peak: float
    output_peak: float
    safety_gain_db: float
    schema: str = "https://sophia-labs.ai/schemas/mus-psychoacoustic-manipulation/1"

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


def apply_controls(signal: Any, sample_rate: int, controls: PsychoacousticControls | Mapping[str, Any] | None = None) -> tuple[Any, ManipulationReceipt]:
    """Apply psychoacoustic-cue interventions to a mono object."""
    np, scipy_signal, librosa = _dependencies()
    controls = controls if isinstance(controls, PsychoacousticControls) else PsychoacousticControls.from_mapping(controls)
    y = np.asarray(signal, dtype=np.float64).reshape(-1).copy()
    if y.size == 0:
        raise ValueError("signal is empty")
    if not np.all(np.isfinite(y)):
        raise ValueError("signal contains NaN or infinite samples")
    operations: list[Mapping[str, Any]] = []
    input_peak = float(np.max(np.abs(y)))

    if abs(controls.pitch_semitones) > 1e-9:
        y = librosa.effects.pitch_shift(y, sr=int(sample_rate), n_steps=float(controls.pitch_semitones), res_type="soxr_hq")
        operations.append({
            "operator": "librosa.pitch_shift",
            "targetCue": "pitch-height",
            "parameters": {"semitones": float(controls.pitch_semitones)},
            "claim": "Duration-preserving pitch intervention; source identity and quality require separate evaluation.",
        })

    if abs(controls.tonal_focus) > 1e-9:
        harmonic, percussive = librosa.effects.hpss(y)
        focus = float(controls.tonal_focus)
        if focus >= 0:
            mixed = harmonic + (1.0 - focus) * percussive
        else:
            mixed = (1.0 + focus) * harmonic + percussive
        y = _match_rms(mixed, y)
        operations.append({
            "operator": "librosa.hpss-mix",
            "targetCue": "pitch-salience/harmonicity",
            "parameters": {"tonalFocus": focus},
            "claim": "A harmonic/percussive decomposition mix, not a direct harmonicity control.",
        })

    if abs(controls.brightness_db) > 1e-9:
        b, a = _high_shelf_coefficients(sample_rate, controls.brightness_hz, controls.brightness_db)
        y = scipy_signal.sosfilt(scipy_signal.tf2sos(b, a), y)
        operations.append({
            "operator": "mus.rbj-high-shelf/1",
            "targetCue": "brightness/sharpness",
            "parameters": {"gainDb": float(controls.brightness_db), "cornerHz": float(controls.brightness_hz)},
            "claim": "Spectral-envelope intervention targeting high-frequency energy; brightness and sharpness remain distinct.",
        })

    if controls.attack_seconds is not None:
        attack_samples = min(y.size, max(0, int(round(controls.attack_seconds * sample_rate))))
        if attack_samples > 1:
            phase = np.linspace(0.0, 1.0, attack_samples, endpoint=True)
            ramp = np.sin(phase * math.pi / 2.0) ** 2
            y[:attack_samples] *= ramp
        operations.append({
            "operator": "mus.object-attack-envelope/1",
            "targetCue": "attack-time/impulsiveness",
            "parameters": {"attackSeconds": float(controls.attack_seconds)},
            "claim": "Object-onset envelope intervention.",
        })

    if controls.roughness_depth > 0:
        y = _amplitude_modulate(y, sample_rate, controls.roughness_rate_hz, controls.roughness_depth)
        operations.append({
            "operator": "mus.amplitude-modulation/1",
            "targetCue": "psychoacoustic-roughness",
            "parameters": {"rateHz": float(controls.roughness_rate_hz), "depth": float(controls.roughness_depth)},
            "claim": "Introduces a major roughness cue in the 20–300 Hz modulation range; does not set roughness in asper.",
        })

    if controls.fluctuation_depth > 0:
        y = _amplitude_modulate(y, sample_rate, controls.fluctuation_rate_hz, controls.fluctuation_depth)
        operations.append({
            "operator": "mus.amplitude-modulation/1",
            "targetCue": "fluctuation-strength/pulsation",
            "parameters": {"rateHz": float(controls.fluctuation_rate_hz), "depth": float(controls.fluctuation_depth)},
            "claim": "Introduces a slow fluctuation cue; does not set fluctuation strength in vacil.",
        })

    gain_db = float(controls.gain_db)
    if controls.target_lufs is not None:
        current = _integrated_loudness(y, sample_rate)
        if current is None:
            raise RuntimeError("target_lufs requires pyloudnorm and a signal accepted by its BS.1770 meter")
        gain_db += float(controls.target_lufs) - current
        operations.append({
            "operator": "pyloudnorm.bs1770-gain-match",
            "targetCue": "programme-loudness",
            "parameters": {"beforeLufs": current, "targetLufs": float(controls.target_lufs)},
            "claim": "Programme loudness matching, not universal equal-loudness matching.",
        })
    if abs(gain_db) > 1e-9:
        y *= 10.0 ** (gain_db / 20.0)
        operations.append({
            "operator": "mus.linear-gain/1",
            "targetCue": "level/loudness",
            "parameters": {"gainDb": gain_db},
        })

    peak = float(np.max(np.abs(y)))
    safety_gain_db = 0.0
    if peak > controls.safety_peak:
        scale = controls.safety_peak / peak
        y *= scale
        safety_gain_db = 20.0 * math.log10(scale)
        operations.append({
            "operator": "mus.safety-peak-scale/1",
            "targetCue": "digital-integrity",
            "parameters": {"maximumPeak": float(controls.safety_peak), "gainDb": safety_gain_db},
            "claim": "Linear safety attenuation; no hidden nonlinear limiter.",
        })

    receipt = ManipulationReceipt(
        controls=controls,
        operations=tuple(operations),
        input_peak=input_peak,
        output_peak=float(np.max(np.abs(y))),
        safety_gain_db=safety_gain_db,
    )
    return y.astype(np.float64, copy=False), receipt


def _amplitude_modulate(y: Any, sample_rate: int, rate_hz: float, depth: float) -> Any:
    np, _, _ = _dependencies()
    time = np.arange(len(y), dtype=float) / float(sample_rate)
    gain = 1.0 + float(depth) * np.sin(2.0 * math.pi * float(rate_hz) * time)
    # Preserve expected mean-square level for long stationary signals.
    gain /= math.sqrt(1.0 + 0.5 * float(depth) ** 2)
    return np.asarray(y, dtype=float) * gain


def _high_shelf_coefficients(sample_rate: int, frequency_hz: float, gain_db: float, slope: float = 1.0) -> tuple[Any, Any]:
    """RBJ high-shelf biquad coefficients."""
    np, _, _ = _dependencies()
    frequency_hz = min(float(frequency_hz), 0.49 * sample_rate)
    a_gain = 10.0 ** (float(gain_db) / 40.0)
    omega = 2.0 * math.pi * frequency_hz / sample_rate
    cosine = math.cos(omega)
    sine = math.sin(omega)
    alpha = sine / 2.0 * math.sqrt((a_gain + 1.0 / a_gain) * (1.0 / slope - 1.0) + 2.0)
    beta = 2.0 * math.sqrt(a_gain) * alpha
    b0 = a_gain * ((a_gain + 1.0) + (a_gain - 1.0) * cosine + beta)
    b1 = -2.0 * a_gain * ((a_gain - 1.0) + (a_gain + 1.0) * cosine)
    b2 = a_gain * ((a_gain + 1.0) + (a_gain - 1.0) * cosine - beta)
    a0 = (a_gain + 1.0) - (a_gain - 1.0) * cosine + beta
    a1 = 2.0 * ((a_gain - 1.0) - (a_gain + 1.0) * cosine)
    a2 = (a_gain + 1.0) - (a_gain - 1.0) * cosine - beta
    return np.asarray([b0, b1, b2]) / a0, np.asarray([1.0, a1 / a0, a2 / a0])


def _match_rms(candidate: Any, reference: Any) -> Any:
    np, _, _ = _dependencies()
    candidate = np.asarray(candidate, dtype=float)
    reference = np.asarray(reference, dtype=float)
    c_rms = float(np.sqrt(np.mean(candidate**2)))
    r_rms = float(np.sqrt(np.mean(reference**2)))
    if c_rms <= 1e-15:
        return candidate
    return candidate * (r_rms / c_rms)


def _integrated_loudness(y: Any, sample_rate: int) -> float | None:
    try:
        import pyloudnorm as pyln
        value = float(pyln.Meter(int(sample_rate)).integrated_loudness(y))
        return value if math.isfinite(value) else None
    except Exception:
        return None


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _dependencies() -> tuple[Any, Any, Any]:
    try:
        import numpy as np
        from scipy import signal as scipy_signal
        import librosa
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("psychoacoustic controls require the 'audio' optional dependencies") from exc
    return np, scipy_signal, librosa
