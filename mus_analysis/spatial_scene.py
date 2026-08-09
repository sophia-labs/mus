"""Portable object-scene contract for the MUS spatial canvas.

Coordinates follow Web Audio's default listener convention:

* +X is right;
* +Y is up;
* -Z is in front of the listener.

The scene stores mono object streams plus metadata.  Binaural, stereo and
Ambisonic signals are derived render targets, never authoring authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from .psychoacoustic_controls import PsychoacousticControls


SCHEMA = "https://sophia-labs.ai/schemas/mus-spatial-scene/1"


@dataclass(frozen=True, slots=True)
class Position:
    x: float = 0.0
    y: float = 0.0
    z: float = -1.0

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in (self.x, self.y, self.z)):
            raise ValueError("position values must be finite")

    @property
    def distance(self) -> float:
        return math.sqrt(self.x**2 + self.y**2 + self.z**2)

    @property
    def azimuth_radians(self) -> float:
        # Front (-Z) is zero; positive azimuth points right.
        return math.atan2(self.x, -self.z)

    @property
    def elevation_radians(self) -> float:
        horizontal = math.sqrt(self.x**2 + self.z**2)
        return math.atan2(self.y, horizontal)

    @classmethod
    def spherical(cls, azimuth_degrees: float, elevation_degrees: float, distance: float) -> "Position":
        if distance < 0:
            raise ValueError("distance cannot be negative")
        azimuth = math.radians(azimuth_degrees)
        elevation = math.radians(elevation_degrees)
        horizontal = distance * math.cos(elevation)
        return cls(
            x=horizontal * math.sin(azimuth),
            y=distance * math.sin(elevation),
            z=-horizontal * math.cos(azimuth),
        )


@dataclass(frozen=True, slots=True)
class PositionKeyframe:
    time_seconds: float
    position: Position

    def __post_init__(self) -> None:
        if not math.isfinite(self.time_seconds) or self.time_seconds < 0:
            raise ValueError("keyframe time must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class Listener:
    position: Position = Position(0.0, 0.0, 0.0)
    forward: Position = Position(0.0, 0.0, -1.0)
    up: Position = Position(0.0, 1.0, 0.0)


@dataclass(frozen=True, slots=True)
class SpatialObject:
    object_id: str
    label: str
    audio: str
    start_seconds: float = 0.0
    duration_seconds: float | None = None
    kind: str = "point"
    position: Position = Position()
    trajectory: tuple[PositionKeyframe, ...] = ()
    gain_db: float = 0.0
    spread: float = 0.0
    reverb_send: float = 0.0
    loop: bool = False
    muted: bool = False
    controls: PsychoacousticControls = PsychoacousticControls()
    analysis: Mapping[str, Any] = field(default_factory=dict)
    source_region: Mapping[str, Any] | None = None
    placement_provenance: str = "composition-authored"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.object_id or not self.label or not self.audio:
            raise ValueError("object_id, label and audio are required")
        if self.kind not in {"point", "extended", "diffuse", "ambient"}:
            raise ValueError("unsupported spatial-object kind")
        if self.start_seconds < 0 or not math.isfinite(self.start_seconds):
            raise ValueError("start_seconds must be finite and non-negative")
        if self.duration_seconds is not None and self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        if not 0.0 <= self.spread <= 1.0:
            raise ValueError("spread must be in [0, 1]")
        if not 0.0 <= self.reverb_send <= 1.0:
            raise ValueError("reverb_send must be in [0, 1]")
        if tuple(sorted(item.time_seconds for item in self.trajectory)) != tuple(item.time_seconds for item in self.trajectory):
            raise ValueError("trajectory keyframes must be time ordered")


@dataclass(frozen=True, slots=True)
class Room:
    enabled: bool = True
    decay_seconds: float = 1.6
    wet: float = 0.16
    damping: float = 0.45
    seed: int = 17

    def __post_init__(self) -> None:
        if self.decay_seconds <= 0:
            raise ValueError("room decay_seconds must be positive")
        if not 0 <= self.wet <= 1 or not 0 <= self.damping <= 1:
            raise ValueError("room wet and damping must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class SpatialScene:
    scene_id: str
    title: str
    sample_rate: int
    duration_seconds: float
    objects: tuple[SpatialObject, ...]
    listener: Listener = Listener()
    room: Room = Room()
    coordinate_system: str = "+X right, +Y up, -Z front"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        if not self.scene_id or not self.title:
            raise ValueError("scene_id and title are required")
        if self.sample_rate < 8000:
            raise ValueError("sample_rate must be at least 8 kHz")
        if self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        ids = [item.object_id for item in self.objects]
        if len(ids) != len(set(ids)):
            raise ValueError("spatial object ids must be unique")

    def to_dict(self) -> dict[str, Any]:
        return _camelize(asdict(self))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SpatialScene":
        objects = tuple(_object_from_dict(row) for row in value.get("objects", []))
        listener_row = value.get("listener", {})
        room_row = value.get("room", {})
        return cls(
            scene_id=str(value.get("sceneId", value.get("scene_id", ""))),
            title=str(value.get("title", "")),
            sample_rate=int(value.get("sampleRate", value.get("sample_rate", 48000))),
            duration_seconds=float(value.get("durationSeconds", value.get("duration_seconds", 0.0))),
            objects=objects,
            listener=Listener(
                position=_position_from_dict(listener_row.get("position", {}), default=Position(0, 0, 0)),
                forward=_position_from_dict(listener_row.get("forward", {}), default=Position(0, 0, -1)),
                up=_position_from_dict(listener_row.get("up", {}), default=Position(0, 1, 0)),
            ),
            room=Room(
                enabled=bool(room_row.get("enabled", True)),
                decay_seconds=float(room_row.get("decaySeconds", room_row.get("decay_seconds", 1.6))),
                wet=float(room_row.get("wet", 0.16)),
                damping=float(room_row.get("damping", 0.45)),
                seed=int(room_row.get("seed", 17)),
            ),
            coordinate_system=str(value.get("coordinateSystem", "+X right, +Y up, -Z front")),
            metadata=value.get("metadata", {}),
            schema=str(value.get("schema", SCHEMA)),
        )

    @classmethod
    def read(cls, path: str | Path) -> "SpatialScene":
        value = json.loads(Path(path).read_text("utf-8"))
        if not isinstance(value, Mapping):
            raise ValueError("scene file must contain an object")
        return cls.from_dict(value)

    def write(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", "utf-8")
        return target


def object_from_analysis(
    *,
    object_id: str,
    label: str,
    audio: str,
    start_seconds: float,
    duration_seconds: float,
    analysis: Mapping[str, Any],
    kind: str = "point",
    source_region: Mapping[str, Any] | None = None,
    family: str | None = None,
    index: int = 0,
    count: int = 1,
) -> SpatialObject:
    """Create a pleasant initial placement from explicit analysis mappings."""
    metrics = _metric_values(analysis)
    centroid = metrics.get("spectrum.centroid-hz") or 2000.0
    roughness = metrics.get("auditory.roughness-proxy") or 0.0
    rms_dbfs = metrics.get("digital.rms-dbfs") or -30.0
    pitch_salience = metrics.get("auditory.pitch-salience-proxy") or 0.0

    family_key = family or label or object_id
    family_angle = _stable_fraction(family_key) * 300.0 - 150.0
    local_offset = ((index + 0.5) / max(1, count) - 0.5) * min(36.0, 8.0 + 4.0 * math.sqrt(count))
    azimuth = family_angle + local_offset
    brightness_norm = _log_normalize(centroid, 250.0, 8000.0)
    elevation = -18.0 + 72.0 * brightness_norm
    distance = _clamp(2.0 + (-rms_dbfs - 12.0) / 5.0, 1.5, 16.0)
    if kind in {"diffuse", "ambient"}:
        distance = max(distance, 7.0)
    spread = _clamp((roughness * 1.7) + (0.3 if kind != "point" else 0.0), 0.0, 1.0)
    gain_db = -2.0 if pitch_salience > 0.7 else 0.0
    return SpatialObject(
        object_id=object_id,
        label=label,
        audio=audio,
        start_seconds=start_seconds,
        duration_seconds=duration_seconds,
        kind=kind,
        position=Position.spherical(azimuth, elevation, distance),
        gain_db=gain_db,
        spread=spread,
        reverb_send=0.08 + 0.28 * min(1.0, distance / 16.0),
        analysis=analysis,
        source_region=source_region,
        placement_provenance="analysis-mapped",
        metadata={
            "layoutStrategy": "psychoacoustic-constellation-v1",
            "mapping": {
                "familyOrLabelToAzimuth": family_key,
                "spectralCentroidToElevation": centroid,
                "digitalRmsToDistance": rms_dbfs,
                "roughnessProxyToSpread": roughness,
            },
        },
    )


def make_scene(
    title: str,
    sample_rate: int,
    duration_seconds: float,
    objects: Sequence[SpatialObject],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> SpatialScene:
    identity = {
        "title": title,
        "sampleRate": sample_rate,
        "durationSeconds": duration_seconds,
        "objects": [item.object_id for item in objects],
    }
    digest = sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return SpatialScene(
        scene_id=f"urn:sophia:mus:spatial-scene:sha256:{digest}",
        title=title,
        sample_rate=sample_rate,
        duration_seconds=duration_seconds,
        objects=tuple(objects),
        metadata=metadata or {},
    )


def position_at(obj: SpatialObject, scene_time_seconds: float) -> Position:
    """Linearly interpolate an object's trajectory in scene time."""
    if not obj.trajectory:
        return obj.position
    frames = obj.trajectory
    if scene_time_seconds <= frames[0].time_seconds:
        return frames[0].position
    if scene_time_seconds >= frames[-1].time_seconds:
        return frames[-1].position
    for left, right in zip(frames, frames[1:]):
        if left.time_seconds <= scene_time_seconds <= right.time_seconds:
            span = right.time_seconds - left.time_seconds
            alpha = 0.0 if span <= 0 else (scene_time_seconds - left.time_seconds) / span
            return Position(
                x=left.position.x + alpha * (right.position.x - left.position.x),
                y=left.position.y + alpha * (right.position.y - left.position.y),
                z=left.position.z + alpha * (right.position.z - left.position.z),
            )
    return obj.position


def _object_from_dict(row: Mapping[str, Any]) -> SpatialObject:
    trajectory = tuple(
        PositionKeyframe(
            time_seconds=float(item.get("timeSeconds", item.get("time_seconds", 0.0))),
            position=_position_from_dict(item.get("position", {})),
        )
        for item in row.get("trajectory", [])
    )
    return SpatialObject(
        object_id=str(row.get("objectId", row.get("object_id", ""))),
        label=str(row.get("label", "")),
        audio=str(row.get("audio", "")),
        start_seconds=float(row.get("startSeconds", row.get("start_seconds", 0.0))),
        duration_seconds=None if row.get("durationSeconds", row.get("duration_seconds")) is None else float(row.get("durationSeconds", row.get("duration_seconds"))),
        kind=str(row.get("kind", "point")),
        position=_position_from_dict(row.get("position", {})),
        trajectory=trajectory,
        gain_db=float(row.get("gainDb", row.get("gain_db", 0.0))),
        spread=float(row.get("spread", 0.0)),
        reverb_send=float(row.get("reverbSend", row.get("reverb_send", 0.0))),
        loop=bool(row.get("loop", False)),
        muted=bool(row.get("muted", False)),
        controls=PsychoacousticControls.from_mapping(row.get("controls", {})),
        analysis=row.get("analysis", {}),
        source_region=row.get("sourceRegion", row.get("source_region")),
        placement_provenance=str(row.get("placementProvenance", row.get("placement_provenance", "composition-authored"))),
        metadata=row.get("metadata", {}),
    )


def _position_from_dict(row: Mapping[str, Any], default: Position | None = None) -> Position:
    default = default or Position()
    return Position(float(row.get("x", default.x)), float(row.get("y", default.y)), float(row.get("z", default.z)))


def _metric_values(report: Mapping[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in report.get("metrics", []):
        if not isinstance(row, Mapping):
            continue
        key = row.get("metricId", row.get("metric_id"))
        value = row.get("value")
        if isinstance(key, str) and isinstance(value, (int, float)) and math.isfinite(float(value)):
            out[key] = float(value)
    return out


def _stable_fraction(value: str) -> float:
    digest = sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(2**64 - 1)


def _log_normalize(value: float, low: float, high: float) -> float:
    return _clamp(math.log(max(value, low) / low) / math.log(high / low), 0.0, 1.0)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _camelize(value: Any) -> Any:
    if isinstance(value, dict):
        return {_camel_key(key): _camelize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_camelize(item) for item in value]
    if isinstance(value, tuple):
        return [_camelize(item) for item in value]
    return value


def _camel_key(value: str) -> str:
    pieces = value.split("_")
    return pieces[0] + "".join(piece[:1].upper() + piece[1:] for piece in pieces[1:])
