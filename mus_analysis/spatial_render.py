"""Offline renderers for MUS object scenes.

The interactive canvas uses Web Audio's HRTF ``PannerNode``.  These offline
renderers provide deterministic stereo audition and portable FOA AmbiX
(ACN/SN3D, channel order W,Y,Z,X).  They do not claim to reproduce an original
historical scene.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .psychoacoustic_controls import apply_controls
from .spatial_scene import Listener, Position, SpatialObject, SpatialScene, position_at


@dataclass(frozen=True, slots=True)
class RenderReceipt:
    scene_id: str
    target: str
    sample_rate: int
    channels: int
    duration_seconds: float
    peak_before_safety: float
    safety_gain_db: float
    output_peak: float
    channel_order: tuple[str, ...]
    renderer: str
    object_receipts: tuple[Mapping[str, Any], ...]
    metadata: Mapping[str, Any]
    schema: str = "https://sophia-labs.ai/schemas/mus-spatial-render-receipt/1"

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


def render_to_file(
    scene_path: str | Path,
    output_path: str | Path,
    *,
    target: str = "stereo",
    block_size: int = 256,
) -> RenderReceipt:
    scene_path = Path(scene_path)
    scene = SpatialScene.read(scene_path)
    root = scene_path.parent
    if target == "stereo":
        audio, receipt = render_stereo(scene, root, block_size=block_size)
    elif target in {"foa", "ambix", "foa-ambix"}:
        audio, receipt = render_foa(scene, root, block_size=block_size)
    else:
        raise ValueError("target must be 'stereo' or 'foa'")
    _, _, _, sf = _dependencies()
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output, audio, receipt.sample_rate, subtype="FLOAT")
    sidecar = output.with_suffix(output.suffix + ".receipt.json")
    payload = receipt.to_dict()
    payload["outputFile"] = output.name
    payload["outputSha256"] = sha256(output.read_bytes()).hexdigest()
    sidecar.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")
    return receipt


def render_stereo(scene: SpatialScene, root: str | Path, *, block_size: int = 256) -> tuple[Any, RenderReceipt]:
    np, scipy_signal, librosa, sf = _dependencies()
    sample_rate = scene.sample_rate
    length = max(1, int(math.ceil(scene.duration_seconds * sample_rate)))
    mix = np.zeros((length, 2), dtype=np.float64)
    room_bus = np.zeros(length, dtype=np.float64)
    object_receipts: list[Mapping[str, Any]] = []

    for obj in scene.objects:
        if obj.muted:
            continue
        y, source_sr = _load_object_audio(root, obj.audio, sf)
        if source_sr != sample_rate:
            y = librosa.resample(y, orig_sr=source_sr, target_sr=sample_rate, res_type="soxr_hq")
        if obj.duration_seconds is not None:
            y = y[: max(1, int(round(obj.duration_seconds * sample_rate)))]
        manipulated, manipulation = apply_controls(y, sample_rate, obj.controls)
        object_gain = 10.0 ** (obj.gain_db / 20.0)
        manipulated = manipulated * object_gain
        spatial, send, spatial_meta = _spatialize_stereo_object(
            manipulated,
            sample_rate,
            obj,
            listener=scene.listener,
            block_size=block_size,
        )
        start = int(round(obj.start_seconds * sample_rate))
        if start >= length:
            continue
        available = min(len(spatial), length - start)
        mix[start : start + available] += spatial[:available]
        room_bus[start : start + available] += send[:available] * obj.reverb_send
        object_receipts.append(
            {
                "objectId": obj.object_id,
                "audio": obj.audio,
                "startSeconds": obj.start_seconds,
                "samplesRendered": available,
                "gainDb": obj.gain_db,
                "spread": obj.spread,
                "reverbSend": obj.reverb_send,
                "manipulation": manipulation.to_dict(),
                "spatial": spatial_meta,
            }
        )

    if scene.room.enabled and np.any(room_bus):
        reverb = _synthetic_room(room_bus, sample_rate, scene.room.decay_seconds, scene.room.damping, scene.room.seed)
        wet = float(scene.room.wet)
        mix[: len(reverb)] += wet * reverb[:length]

    peak_before = float(np.max(np.abs(mix)))
    safety_gain_db = 0.0
    if peak_before > 0.98:
        scale = 0.98 / peak_before
        mix *= scale
        safety_gain_db = 20.0 * math.log10(scale)
    receipt = RenderReceipt(
        scene_id=scene.scene_id,
        target="stereo-equalpower-plus-diffuse",
        sample_rate=sample_rate,
        channels=2,
        duration_seconds=length / sample_rate,
        peak_before_safety=peak_before,
        safety_gain_db=safety_gain_db,
        output_peak=float(np.max(np.abs(mix))),
        channel_order=("left", "right"),
        renderer="mus.spatial-stereo/1",
        object_receipts=tuple(object_receipts),
        metadata={
            "coordinateSystem": scene.coordinate_system,
            "claim": "Deterministic production render from authored object metadata; not an HRTF binaural render.",
            "listenerPoseHonored": True,
        },
    )
    return mix, receipt


def render_foa(scene: SpatialScene, root: str | Path, *, block_size: int = 256) -> tuple[Any, RenderReceipt]:
    """Render ACN/SN3D first-order Ambisonics in channel order W,Y,Z,X."""
    np, _, librosa, sf = _dependencies()
    sample_rate = scene.sample_rate
    length = max(1, int(math.ceil(scene.duration_seconds * sample_rate)))
    mix = np.zeros((length, 4), dtype=np.float64)
    room_bus = np.zeros(length, dtype=np.float64)
    object_receipts: list[Mapping[str, Any]] = []

    for obj in scene.objects:
        if obj.muted:
            continue
        y, source_sr = _load_object_audio(root, obj.audio, sf)
        if source_sr != sample_rate:
            y = librosa.resample(y, orig_sr=source_sr, target_sr=sample_rate, res_type="soxr_hq")
        if obj.duration_seconds is not None:
            y = y[: max(1, int(round(obj.duration_seconds * sample_rate)))]
        y, manipulation = apply_controls(y, sample_rate, obj.controls)
        y *= 10.0 ** (obj.gain_db / 20.0)
        coefficients, distance_gain, air_cutoff = _foa_coefficients(obj, scene.listener, sample_rate, len(y), block_size)
        y = _air_absorption(y, sample_rate, air_cutoff)
        encoded = y[:, None] * coefficients * distance_gain[:, None]
        start = int(round(obj.start_seconds * sample_rate))
        if start >= length:
            continue
        available = min(len(encoded), length - start)
        mix[start : start + available] += encoded[:available]
        room_bus[start : start + available] += y[:available] * distance_gain[:available] * obj.reverb_send
        object_receipts.append(
            {
                "objectId": obj.object_id,
                "samplesRendered": available,
                "manipulation": manipulation.to_dict(),
                "spatial": {
                    "format": "ACN/SN3D",
                    "channelOrder": ["W", "Y", "Z", "X"],
                    "spread": obj.spread,
                    "airAbsorptionCutoffHz": air_cutoff,
                },
            }
        )

    if scene.room.enabled and np.any(room_bus):
        # Diffuse synthetic room energy is placed in the omnidirectional channel.
        stereo_reverb = _synthetic_room(room_bus, sample_rate, scene.room.decay_seconds, scene.room.damping, scene.room.seed)
        omni = np.mean(stereo_reverb, axis=1)
        mix[: min(length, len(omni)), 0] += scene.room.wet * omni[:length]

    peak_before = float(np.max(np.abs(mix)))
    safety_gain_db = 0.0
    if peak_before > 0.98:
        scale = 0.98 / peak_before
        mix *= scale
        safety_gain_db = 20.0 * math.log10(scale)
    return mix, RenderReceipt(
        scene_id=scene.scene_id,
        target="foa-ambix",
        sample_rate=sample_rate,
        channels=4,
        duration_seconds=length / sample_rate,
        peak_before_safety=peak_before,
        safety_gain_db=safety_gain_db,
        output_peak=float(np.max(np.abs(mix))),
        channel_order=("W", "Y", "Z", "X"),
        renderer="mus.foa-ambix-encoder/1",
        object_receipts=tuple(object_receipts),
        metadata={
            "normalization": "SN3D",
            "channelNumbering": "ACN",
            "coordinateSystem": scene.coordinate_system,
            "claim": "Portable plane-wave object encoding; binaural or loudspeaker decoding is downstream.",
            "listenerPoseHonored": True,
        },
    )


def _spatialize_stereo_object(
    y: Any,
    sample_rate: int,
    obj: SpatialObject,
    *,
    listener: Listener,
    block_size: int,
) -> tuple[Any, Any, Mapping[str, Any]]:
    np, _, _, _ = _dependencies()
    times = np.arange(len(y), dtype=float) / sample_rate + obj.start_seconds
    control_times = np.arange(0, len(y), max(1, block_size), dtype=int)
    if control_times.size == 0 or control_times[-1] != len(y) - 1:
        control_times = np.append(control_times, len(y) - 1)
    positions = [
        _listener_relative(position_at(obj, obj.start_seconds + index / sample_rate), listener)
        for index in control_times
    ]
    pans = np.asarray([math.sin(item.azimuth_radians) for item in positions], dtype=float)
    distances = np.asarray([max(0.001, item.distance) for item in positions], dtype=float)
    pan = np.interp(np.arange(len(y)), control_times, pans)
    distance = np.interp(np.arange(len(y)), control_times, distances)
    x = (np.clip(pan, -1.0, 1.0) + 1.0) / 2.0
    gain_left = np.cos(x * math.pi / 2.0)
    gain_right = np.sin(x * math.pi / 2.0)
    distance_gain = _inverse_distance_gain(distance)
    air_cutoff = _distance_air_cutoff(float(np.median(distance)))
    dry = _air_absorption(y, sample_rate, air_cutoff) * distance_gain
    point = np.column_stack([dry * gain_left, dry * gain_right])
    effective_spread = max(obj.spread, 0.78 if obj.kind in {"diffuse", "ambient"} else 0.0)
    if effective_spread > 0:
        diffuse = _decorrelate_stereo(dry, sample_rate, seed=_seed_from_id(obj.object_id))
        spatial = (1.0 - effective_spread) * point + effective_spread * diffuse
    else:
        spatial = point
    return spatial, dry, {
        "panning": "equal-power",
        "distanceModel": "inverse",
        "medianDistance": float(np.median(distance)),
        "minimumDistance": float(np.min(distance)),
        "maximumDistance": float(np.max(distance)),
        "airAbsorptionCutoffHz": air_cutoff,
        "effectiveSpread": effective_spread,
    }


def _foa_coefficients(obj: SpatialObject, listener: Listener, sample_rate: int, length: int, block_size: int) -> tuple[Any, Any, float]:
    np, _, _, _ = _dependencies()
    control = np.arange(0, length, max(1, block_size), dtype=int)
    if control.size == 0 or control[-1] != length - 1:
        control = np.append(control, length - 1)
    positions = [
        _listener_relative(position_at(obj, obj.start_seconds + index / sample_rate), listener)
        for index in control
    ]
    rows = []
    distances = []
    directional_gain = 1.0 - max(obj.spread, 0.9 if obj.kind in {"diffuse", "ambient"} else 0.0)
    for position in positions:
        azimuth = position.azimuth_radians
        elevation = position.elevation_radians
        rows.append(
            [
                1.0,
                directional_gain * math.cos(elevation) * math.sin(azimuth),
                directional_gain * math.sin(elevation),
                directional_gain * math.cos(elevation) * math.cos(azimuth),
            ]
        )
        distances.append(max(0.001, position.distance))
    rows = np.asarray(rows, dtype=float)
    coefficients = np.column_stack([
        np.interp(np.arange(length), control, rows[:, channel]) for channel in range(4)
    ])
    distance = np.interp(np.arange(length), control, np.asarray(distances))
    return coefficients, _inverse_distance_gain(distance), _distance_air_cutoff(float(np.median(distance)))


def _listener_relative(position: Position, listener: Listener) -> Position:
    """Transform a world-space position into Web-Audio-style listener space."""
    np, _, _, _ = _dependencies()
    origin = np.asarray([listener.position.x, listener.position.y, listener.position.z], dtype=float)
    forward = np.asarray([listener.forward.x, listener.forward.y, listener.forward.z], dtype=float)
    up = np.asarray([listener.up.x, listener.up.y, listener.up.z], dtype=float)
    forward_norm = float(np.linalg.norm(forward))
    up_norm = float(np.linalg.norm(up))
    if forward_norm < 1e-12 or up_norm < 1e-12:
        raise ValueError("listener forward and up vectors must be non-zero")
    forward /= forward_norm
    up /= up_norm
    right = np.cross(forward, up)
    right_norm = float(np.linalg.norm(right))
    if right_norm < 1e-12:
        raise ValueError("listener forward and up vectors must not be collinear")
    right /= right_norm
    up = np.cross(right, forward)
    delta = np.asarray([position.x, position.y, position.z], dtype=float) - origin
    return Position(
        x=float(np.dot(delta, right)),
        y=float(np.dot(delta, up)),
        z=float(-np.dot(delta, forward)),
    )


def _inverse_distance_gain(distance: Any, ref_distance: float = 1.0, rolloff: float = 0.72) -> Any:
    np, _, _, _ = _dependencies()
    d = np.maximum(np.asarray(distance, dtype=float), ref_distance)
    return ref_distance / (ref_distance + rolloff * (d - ref_distance))


def _distance_air_cutoff(distance: float) -> float:
    return float(max(2200.0, min(20000.0, 20000.0 * math.exp(-0.035 * max(0.0, distance - 1.0)))))


def _air_absorption(y: Any, sample_rate: int, cutoff_hz: float) -> Any:
    np, scipy_signal, _, _ = _dependencies()
    if cutoff_hz >= sample_rate * 0.47:
        return np.asarray(y, dtype=float)
    sos = scipy_signal.butter(2, cutoff_hz / (sample_rate / 2.0), btype="low", output="sos")
    return scipy_signal.sosfilt(sos, np.asarray(y, dtype=float))


def _decorrelate_stereo(y: Any, sample_rate: int, *, seed: int) -> Any:
    np, scipy_signal, _, _ = _dependencies()
    y = np.asarray(y, dtype=float)
    # Cascaded Schroeder all-pass filters: deterministic, short, and cheap.
    delay_sets = (
        (0.0037, 0.0113, 0.0179),
        (0.0053, 0.0137, 0.0197),
    )
    outputs = []
    for channel, delays in enumerate(delay_sets):
        out = y.copy()
        for index, delay_seconds in enumerate(delays):
            delay = max(1, int(round(delay_seconds * sample_rate)))
            gain = 0.55 + 0.03 * ((seed + channel + index) % 5)
            b = np.zeros(delay + 1)
            a = np.zeros(delay + 1)
            b[0], b[-1] = -gain, 1.0
            a[0], a[-1] = 1.0, -gain
            out = scipy_signal.lfilter(b, a, out)
        outputs.append(out)
    stereo = np.column_stack(outputs)
    input_rms = float(np.sqrt(np.mean(y**2)))
    output_rms = float(np.sqrt(np.mean(stereo**2)))
    if output_rms > 1e-15:
        stereo *= input_rms / output_rms
    return stereo


def _synthetic_room(y: Any, sample_rate: int, decay_seconds: float, damping: float, seed: int) -> Any:
    np, scipy_signal, _, _ = _dependencies()
    length = max(64, int(round(decay_seconds * sample_rate)))
    time = np.arange(length) / sample_rate
    envelope = np.exp(-6.91 * time / max(decay_seconds, 1e-3))
    outputs = []
    for channel in range(2):
        rng = np.random.default_rng(seed + channel * 7919)
        impulse = rng.standard_normal(length) * envelope
        impulse[0] += 1.0
        cutoff = 18000.0 - 13000.0 * damping
        if cutoff < sample_rate * 0.47:
            sos = scipy_signal.butter(2, cutoff / (sample_rate / 2.0), btype="low", output="sos")
            impulse = scipy_signal.sosfilt(sos, impulse)
        impulse /= max(float(np.sqrt(np.sum(impulse**2))), 1e-15)
        outputs.append(scipy_signal.fftconvolve(y, impulse, mode="full"))
    return np.column_stack(outputs)


def _load_object_audio(root: str | Path, relative: str, sf: Any) -> tuple[Any, int]:
    np, _, _, _ = _dependencies()
    root = Path(root).resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"object audio escapes scene root: {relative}") from exc
    data, sample_rate = sf.read(path, always_2d=True, dtype="float64")
    return np.mean(data, axis=1), int(sample_rate)


def _seed_from_id(value: str) -> int:
    return int.from_bytes(sha256(value.encode("utf-8")).digest()[:4], "big")


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _dependencies() -> tuple[Any, Any, Any, Any]:
    try:
        import numpy as np
        from scipy import signal as scipy_signal
        import librosa
        import soundfile as sf
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("spatial rendering requires the 'audio' optional dependencies") from exc
    return np, scipy_signal, librosa, sf
