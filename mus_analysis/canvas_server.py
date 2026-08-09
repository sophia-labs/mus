"""Same-origin server for the MUS psychoacoustic spatial canvas."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from hashlib import sha256
import json
import mimetypes
from pathlib import Path
import os
import re
from threading import Lock
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .decomposition import (
    Stem,
    auditory_band_decomposition,
    event_soft_mask_decomposition,
    hpss_decomposition,
    hybrid_decomposition,
    nmf_decomposition,
    propose_regions,
    write_decomposition,
)
from .psychoacoustic_controls import PsychoacousticControls, apply_controls
from .psychoacoustics import CalibrationSpec, analyze_signal, load_mono
from .spatial_scene import Position, SpatialObject, SpatialScene, object_from_analysis


_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


@dataclass
class CanvasState:
    scene_path: Path
    scene: SpatialScene
    editable: bool = False
    save_path: Path | None = None

    def __post_init__(self) -> None:
        self.scene_path = self.scene_path.resolve()
        self.root = self.scene_path.parent
        self.lock = Lock()
        self.save_path = (self.save_path or self.scene_path.with_name("scene.edited.json")).resolve()

    def object_audio(self, object_id: str) -> Path:
        obj = next((item for item in self.scene.objects if item.object_id == object_id), None)
        if obj is None:
            raise KeyError(object_id)
        path = (self.root / obj.audio).resolve()
        path.relative_to(self.root)
        return path

    def persist(self, scene: SpatialScene) -> Path:
        with self.lock:
            self.scene = scene
            self.save_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.save_path.with_suffix(self.save_path.suffix + ".tmp")
            temporary.write_text(json.dumps(scene.to_dict(), indent=2, sort_keys=True) + "\n", "utf-8")
            temporary.replace(self.save_path)
        return self.save_path


def make_handler(state: CanvasState) -> type[BaseHTTPRequestHandler]:
    class CanvasHandler(BaseHTTPRequestHandler):
        server_version = "MUSSpatialCanvas/1"

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/scene":
                self._json(HTTPStatus.OK, state.scene.to_dict())
                return
            if path == "/api/capabilities":
                self._json(
                    HTTPStatus.OK,
                    {
                        "editable": state.editable,
                        "reanalyze": True,
                        "maxUploadBytes": 512_000_000,
                        "ingestModes": ["whole", "events", "hybrid", "nmf", "bands", "hpss"],
                    },
                )
                return
            if path.startswith("/media/"):
                object_id = unquote(path[len("/media/") :])
                try:
                    media = state.object_audio(object_id)
                except (KeyError, ValueError):
                    self._text(HTTPStatus.NOT_FOUND, "unknown spatial object\n")
                    return
                self._file(media, allow_range=True)
                return
            if path in {"/", "/index.html"}:
                self._static("index.html")
                return
            if path in {"/app.js", "/styles.css"}:
                self._static(path.lstrip("/"))
                return
            self._text(HTTPStatus.NOT_FOUND, "not found\n")

        def do_HEAD(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/capabilities":
                data = b'{"editable":true}\n' if state.editable else b'{"editable":false}\n'
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            if path.startswith("/media/"):
                object_id = unquote(path[len("/media/") :])
                try:
                    media = state.object_audio(object_id)
                except (KeyError, ValueError):
                    self._text(HTTPStatus.NOT_FOUND, "unknown spatial object\n", head=True)
                    return
                self._file(media, allow_range=True, head=True)
                return
            if path in {"/", "/index.html", "/app.js", "/styles.css"}:
                name = "index.html" if path in {"/", "/index.html"} else path.lstrip("/")
                self._static(name, head=True)
                return
            self._text(HTTPStatus.NOT_FOUND, "not found\n", head=True)

        def do_POST(self) -> None:  # noqa: N802
            if not self._origin_allowed():
                self._text(HTTPStatus.FORBIDDEN, "cross-origin mutation refused\n")
                return
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/api/objects":
                self._ingest_object(parse_qs(parsed.query))
                return
            if path.startswith("/api/objects/") and path.endswith("/derive"):
                object_id = unquote(path[len("/api/objects/") : -len("/derive")].rstrip("/"))
                self._derive_object(object_id)
                return
            if path.startswith("/api/analyze/"):
                self._reanalyze_object(unquote(path[len("/api/analyze/") :]))
                return
            self._text(HTTPStatus.NOT_FOUND, "not found\n")

        def do_DELETE(self) -> None:  # noqa: N802
            if not self._origin_allowed():
                self._text(HTTPStatus.FORBIDDEN, "cross-origin mutation refused\n")
                return
            path = urlparse(self.path).path
            if not path.startswith("/api/objects/"):
                self._text(HTTPStatus.NOT_FOUND, "not found\n")
                return
            if not state.editable:
                self._text(HTTPStatus.FORBIDDEN, "canvas is read-only\n")
                return
            object_id = unquote(path[len("/api/objects/") :])
            kept = tuple(item for item in state.scene.objects if item.object_id != object_id)
            if len(kept) == len(state.scene.objects):
                self._text(HTTPStatus.NOT_FOUND, "unknown spatial object\n")
                return
            scene = replace(state.scene, objects=kept)
            saved = state.persist(scene)
            self._json(HTTPStatus.OK, {"removed": object_id, "saved": str(saved), "scene": scene.to_dict()})

        def _reanalyze_object(self, object_id: str) -> None:
            try:
                obj = next(item for item in state.scene.objects if item.object_id == object_id)
                media = state.object_audio(object_id)
            except (StopIteration, KeyError, ValueError):
                self._text(HTTPStatus.NOT_FOUND, "unknown spatial object\n")
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 1_000_000:
                self._text(HTTPStatus.BAD_REQUEST, "invalid analysis body length\n")
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
                if not isinstance(payload, dict):
                    raise ValueError("analysis body must be an object")
                controls = PsychoacousticControls.from_mapping(payload.get("controls", obj.controls.to_dict()))
                y, sample_rate = load_mono(media)
                transformed, manipulation = apply_controls(y, sample_rate, controls)
                calibration_row = obj.analysis.get("calibration", {}) if isinstance(obj.analysis, dict) else {}
                calibration = _calibration_from_mapping(calibration_row)
                report = analyze_signal(
                    transformed,
                    sample_rate,
                    source_id=f"{obj.object_id}:intervention-preview",
                    calibration=calibration,
                    include_standardized=bool(payload.get("includeStandardized", True)),
                )
            except Exception as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "analysis-failed", "message": str(exc)})
                return
            self._json(
                HTTPStatus.OK,
                {
                    "objectId": obj.object_id,
                    "controls": _camelize(controls.to_dict()),
                    "manipulation": _camelize(manipulation.to_dict()),
                    "report": report.to_dict(),
                },
            )

        def _derive_object(self, object_id: str) -> None:
            if not state.editable:
                self._text(HTTPStatus.FORBIDDEN, "canvas is read-only\n")
                return
            try:
                parent = next(item for item in state.scene.objects if item.object_id == object_id)
                media = state.object_audio(object_id)
            except (StopIteration, KeyError, ValueError):
                self._text(HTTPStatus.NOT_FOUND, "unknown spatial object\n")
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 1_000_000:
                self._text(HTTPStatus.BAD_REQUEST, "invalid derive body length\n")
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
                if not isinstance(payload, dict):
                    raise ValueError("derive body must be an object")
                controls = PsychoacousticControls.from_mapping(payload.get("controls", parent.controls.to_dict()))
                y, sample_rate = load_mono(media, sample_rate=state.scene.sample_rate)
                transformed, manipulation = apply_controls(y, sample_rate, controls)
                import numpy as np
                import soundfile as sf

                identity = sha256()
                identity.update(np.asarray(transformed, dtype="<f4").tobytes())
                identity.update(json.dumps(_camelize(controls.to_dict()), sort_keys=True).encode("utf-8"))
                digest = identity.hexdigest()
                derived_dir = state.root / "derived"
                derived_dir.mkdir(parents=True, exist_ok=True)
                target = derived_dir / f"{digest}.wav"
                if not target.exists():
                    temporary = target.with_suffix(".wav.tmp")
                    sf.write(temporary, transformed, sample_rate, format="WAV", subtype="FLOAT")
                    temporary.replace(target)
                calibration_row = parent.analysis.get("calibration", {}) if isinstance(parent.analysis, dict) else {}
                calibration = _calibration_from_mapping(calibration_row)
                report = analyze_signal(
                    transformed,
                    sample_rate,
                    source_id=f"{parent.object_id}:derived:{digest}",
                    calibration=calibration,
                    include_standardized=bool(payload.get("includeStandardized", True)),
                ).to_dict()
                existing = {item.object_id for item in state.scene.objects}
                child_id = _unique_id(f"{parent.object_id}:derived:{digest[:16]}", existing)
                requested_label = payload.get("label")
                label = str(requested_label).strip() if isinstance(requested_label, str) and requested_label.strip() else f"{parent.label} · variation"
                offset = float(payload.get("spatialOffset", 1.25))
                child = replace(
                    parent,
                    object_id=child_id,
                    label=label,
                    audio=target.relative_to(state.root).as_posix(),
                    position=Position(parent.position.x + offset, parent.position.y, parent.position.z),
                    controls=PsychoacousticControls(),
                    analysis=report,
                    placement_provenance="derived-psychoacoustic-intervention",
                    metadata={
                        **dict(parent.metadata),
                        "derivedFromObjectId": parent.object_id,
                        "derivedAudioSha256": digest,
                        "manipulation": _camelize(manipulation.to_dict()),
                        "appliedControls": _camelize(controls.to_dict()),
                        "originalAnalysisSourceId": parent.analysis.get("sourceId") if isinstance(parent.analysis, dict) else None,
                    },
                )
                scene = replace(
                    state.scene,
                    duration_seconds=max(state.scene.duration_seconds, child.start_seconds + (child.duration_seconds or len(transformed) / sample_rate)),
                    objects=state.scene.objects + (child,),
                )
                saved = state.persist(scene)
            except Exception as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "derive-failed", "message": str(exc)})
                return
            self._json(
                HTTPStatus.CREATED,
                {
                    "addedObjectIds": [child.object_id],
                    "saved": str(saved),
                    "object": child.to_dict() if hasattr(child, "to_dict") else _camelize(asdict(child)),
                    "scene": scene.to_dict(),
                },
            )

        def _ingest_object(self, query: dict[str, list[str]]) -> None:
            if not state.editable:
                self._text(HTTPStatus.FORBIDDEN, "canvas is read-only\n")
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 512_000_000:
                self._text(HTTPStatus.BAD_REQUEST, "audio upload must be between 1 byte and 512 MB\n")
                return
            filename = _safe_filename((query.get("filename") or ["recording.wav"])[0])
            mode = (query.get("mode") or ["whole"])[0]
            if mode not in {"whole", "events", "nmf", "hybrid", "bands", "hpss"}:
                self._text(HTTPStatus.BAD_REQUEST, "mode must be whole, events, nmf, hybrid, bands or hpss\n")
                return
            try:
                start_seconds = float((query.get("startSeconds") or ["0"])[0])
                components = int((query.get("components") or ["4"])[0])
                if not (0.0 <= start_seconds <= 86_400.0):
                    raise ValueError("startSeconds must be between 0 and 86400")
                if not (1 <= components <= 16):
                    raise ValueError("components must be between 1 and 16")
            except (TypeError, ValueError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid-ingest-options", "message": str(exc)})
                return
            incoming = state.root / "imports"
            incoming.mkdir(parents=True, exist_ok=True)
            temporary = incoming / f".upload-{os.getpid()}-{id(self)}.part"
            digest = sha256()
            remaining = length
            try:
                with temporary.open("wb") as handle:
                    while remaining:
                        chunk = self.rfile.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ValueError("upload ended before Content-Length")
                        handle.write(chunk); digest.update(chunk); remaining -= len(chunk)
                suffix = Path(filename).suffix.lower() or ".audio"
                source = incoming / f"{digest.hexdigest()}{suffix}"
                if source.exists():
                    temporary.unlink()
                else:
                    temporary.replace(source)
                y, sample_rate = load_mono(source, sample_rate=state.scene.sample_rate)
                scene, added = _add_uploaded_audio(
                    state.scene,
                    state.root,
                    y,
                    sample_rate,
                    filename=filename,
                    digest=digest.hexdigest(),
                    mode=mode,
                    start_seconds=start_seconds,
                    components=components,
                )
                saved = state.persist(scene)
            except Exception as exc:
                temporary.unlink(missing_ok=True)
                self._json(HTTPStatus.BAD_REQUEST, {"error": "audio-ingest-failed", "message": str(exc)})
                return
            self._json(HTTPStatus.CREATED, {"addedObjectIds": added, "saved": str(saved), "scene": scene.to_dict()})

        def do_PUT(self) -> None:  # noqa: N802
            if not self._origin_allowed():
                self._text(HTTPStatus.FORBIDDEN, "cross-origin mutation refused\n")
                return
            if urlparse(self.path).path != "/api/scene":
                self._text(HTTPStatus.NOT_FOUND, "not found\n")
                return
            if not state.editable:
                self._text(HTTPStatus.FORBIDDEN, "canvas is read-only\n")
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 8_000_000:
                self._text(HTTPStatus.BAD_REQUEST, "invalid scene body length\n")
                return
            try:
                value = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(value, dict):
                    raise ValueError("scene body must be an object")
                scene = SpatialScene.from_dict(value)
            except Exception as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid-scene", "message": str(exc)})
                return
            saved = state.persist(scene)
            self._json(HTTPStatus.OK, {"saved": str(saved), "sceneId": scene.scene_id})

        def _origin_allowed(self) -> bool:
            origin = self.headers.get("Origin")
            if not origin:
                return True
            host = self.headers.get("Host")
            if not host:
                return False
            return origin.rstrip("/") in {f"http://{host}", f"https://{host}"}

        def log_message(self, format: str, *args: Any) -> None:
            # Keep a concise but useful local server log.
            print(f"[canvas] {self.address_string()} {format % args}")

        def _static(self, name: str, *, head: bool = False) -> None:
            try:
                target = resources.files("mus_analysis").joinpath("spatial_canvas", name)
                data = target.read_bytes()
            except Exception:
                self._text(HTTPStatus.NOT_FOUND, "missing canvas asset\n", head=head)
                return
            media_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", media_type + ("; charset=utf-8" if media_type.startswith("text/") or media_type in {"application/javascript", "application/json"} else ""))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if not head:
                self.wfile.write(data)

        def _file(self, path: Path, *, allow_range: bool, head: bool = False) -> None:
            try:
                size = path.stat().st_size
            except OSError:
                self._text(HTTPStatus.NOT_FOUND, "media file missing\n", head=head)
                return
            media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            start, end = 0, size - 1
            partial = False
            if allow_range:
                header = self.headers.get("Range")
                match = _RANGE.match(header.strip()) if header else None
                if match:
                    first, last = match.groups()
                    if not first and last:
                        count = int(last)
                        start = max(0, size - count)
                    elif first:
                        start = int(first)
                    if last and first:
                        end = min(size - 1, int(last))
                    if start < 0 or end < start or start >= size:
                        self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.end_headers()
                        return
                    partial = True
            self.send_response(HTTPStatus.PARTIAL_CONTENT if partial else HTTPStatus.OK)
            self.send_header("Content-Type", media_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Cache-Control", "no-cache")
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if head:
                return
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = handle.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def _json(self, status: HTTPStatus, value: Any) -> None:
            data = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _text(self, status: HTTPStatus, text: str, *, head: bool = False) -> None:
            data = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if not head:
                self.wfile.write(data)

    return CanvasHandler


def _add_uploaded_audio(
    scene: SpatialScene,
    root: Path,
    y: Any,
    sample_rate: int,
    *,
    filename: str,
    digest: str,
    mode: str,
    start_seconds: float,
    components: int,
) -> tuple[SpatialScene, list[str]]:
    import numpy as np
    import soundfile as sf

    object_root = root / "objects" / digest[:20]
    object_root.mkdir(parents=True, exist_ok=True)
    calibration = CalibrationSpec()
    candidates: list[tuple[Stem, str]] = []
    decomposition_report: str | None = None
    if mode == "whole":
        target = object_root / "source.wav"
        sf.write(target, y, sample_rate, subtype="FLOAT")
        stem = Stem(
            stem_id=f"urn:sophia:mus:upload:sha256:{digest}",
            label=Path(filename).stem,
            audio=np.asarray(y, dtype=float),
            start_seconds=0.0,
            source_region=None,
            kind="whole-recording",
            metadata={"originalFilename": filename, "sourceSha256": digest},
        )
        candidates.append((stem, target.relative_to(root).as_posix()))
        residual = None
    else:
        if mode in {"events", "hybrid"}:
            regions = propose_regions(y, sample_rate)
            if not regions:
                raise ValueError("no event proposals were found; use whole, nmf, bands or hpss mode")
            result = event_soft_mask_decomposition(y, sample_rate, regions) if mode == "events" else hybrid_decomposition(y, sample_rate, regions, components=components)
        elif mode == "nmf":
            result = nmf_decomposition(y, sample_rate, components=components)
        elif mode == "bands":
            result = auditory_band_decomposition(y, sample_rate, bands=components)
        else:
            result = hpss_decomposition(y, sample_rate)
        decomposition_dir = object_root / "decomposition"
        report_path, files = write_decomposition(result, decomposition_dir)
        decomposition_report = report_path.relative_to(root).as_posix()
        for stem in result.stems:
            candidates.append((stem, (decomposition_dir.relative_to(root) / files[stem.stem_id]).as_posix()))
        residual = (result.residual, (decomposition_dir.relative_to(root) / "residual.wav").as_posix())

    existing = {item.object_id for item in scene.objects}
    family_counts: dict[str, int] = {}
    for stem, _ in candidates:
        family = stem.source_region.label if stem.source_region and stem.source_region.label else stem.kind
        family_counts[family] = family_counts.get(family, 0) + 1
    family_index: dict[str, int] = {}
    added: list[SpatialObject] = []
    for stem, relative_audio in candidates:
        report = analyze_signal(
            stem.audio, sample_rate, source_id=stem.stem_id, calibration=calibration, include_standardized=True
        ).to_dict()
        family = stem.source_region.label if stem.source_region and stem.source_region.label else stem.kind
        index = family_index.get(family, 0); family_index[family] = index + 1
        object_id = _unique_id(stem.stem_id, existing)
        existing.add(object_id)
        source_region = asdict(stem.source_region) if stem.source_region else None
        kind = "point" if stem.kind == "event-component" else "extended"
        obj = object_from_analysis(
            object_id=object_id,
            label=stem.label,
            audio=relative_audio,
            start_seconds=start_seconds + stem.start_seconds,
            duration_seconds=len(stem.audio) / sample_rate,
            analysis=report,
            kind=kind,
            source_region=source_region,
            family=family,
            index=index,
            count=family_counts[family],
        )
        added.append(obj)

    if residual is not None:
        stem, relative_audio = residual
        report = analyze_signal(stem.audio, sample_rate, source_id=stem.stem_id, calibration=calibration, include_standardized=True).to_dict()
        object_id = _unique_id(stem.stem_id, existing); existing.add(object_id)
        obj = object_from_analysis(
            object_id=object_id, label=f"{Path(filename).stem} · residual", audio=relative_audio,
            start_seconds=start_seconds, duration_seconds=len(stem.audio) / sample_rate, analysis=report,
            kind="ambient", family=f"{digest}:residual"
        )
        added.append(replace(obj, gain_db=-3.0, spread=max(.88, obj.spread), placement_provenance="composition-authored-from-residual"))

    duration = max(scene.duration_seconds, start_seconds + len(y) / sample_rate)
    imports = list(scene.metadata.get("imports", [])) if isinstance(scene.metadata, dict) else []
    imports.append({
        "filename": filename, "sha256": digest, "mode": mode, "startSeconds": start_seconds,
        "decompositionReport": decomposition_report, "objectIds": [item.object_id for item in added],
    })
    metadata = {**dict(scene.metadata), "imports": imports}
    return replace(scene, duration_seconds=duration, objects=scene.objects + tuple(added), metadata=metadata), [item.object_id for item in added]


def _unique_id(base: str, existing: set[str]) -> str:
    if base not in existing:
        return base
    index = 2
    while f"{base}:copy:{index}" in existing:
        index += 1
    return f"{base}:copy:{index}"


def _safe_filename(value: str) -> str:
    name = Path(value).name
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", ".", " "} else "_" for ch in name).strip()
    return safe[:180] or "recording.wav"


def _camelize(value: Any) -> Any:
    if isinstance(value, dict):
        return {_camel_key(str(key)): _camelize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_camelize(item) for item in value]
    return value


def _camel_key(value: str) -> str:
    pieces = value.split("_")
    return pieces[0] + "".join(piece[:1].upper() + piece[1:] for piece in pieces[1:])


def _calibration_from_mapping(value: Any) -> CalibrationSpec:
    if not isinstance(value, dict) or not value:
        return CalibrationSpec()
    aliases = {
        "pascalPerDigitalUnit": "pascal_per_digital_unit",
        "referenceRmsDbfs": "reference_rms_dbfs",
        "referenceSplDb": "reference_spl_db",
        "referencePressurePa": "reference_pressure_pa",
        "fieldType": "field_type",
    }
    row = {aliases.get(key, key): item for key, item in value.items()}
    allowed = set(CalibrationSpec.__dataclass_fields__)
    return CalibrationSpec(**{key: item for key, item in row.items() if key in allowed})


def serve_canvas(
    scene_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    editable: bool = False,
    save_path: str | Path | None = None,
) -> None:
    scene_path = Path(scene_path)
    state = CanvasState(
        scene_path=scene_path,
        scene=SpatialScene.read(scene_path),
        editable=editable,
        save_path=Path(save_path) if save_path else None,
    )
    server = ThreadingHTTPServer((host, int(port)), make_handler(state))
    print(f"MUS spatial canvas: http://{host}:{server.server_port}/")
    print(f"Scene: {scene_path.resolve()}")
    print(f"Mode: {'editable' if editable else 'read-only'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
