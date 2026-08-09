"""Command-line surface for the MUS psychoacoustic spatial canvas.

The CLI turns a mono recording into an editable object scene while keeping the
material, analysis, intervention, decomposition and rendering layers explicit.
It is intentionally useful without a model service: event masks, NMF texture
components, psychoacoustic proxies, calibrated MoSQITo metrics when available,
and Web Audio/offline render contracts all share one scene format.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
import math
from pathlib import Path
import shutil
from typing import Any, Mapping, Sequence

from .canvas_server import serve_canvas
from .decomposition import (
    DecompositionResult,
    Stem,
    auditory_band_decomposition,
    event_soft_mask_decomposition,
    hpss_decomposition,
    hybrid_decomposition,
    nmf_decomposition,
    propose_regions,
    read_regions,
    write_decomposition,
)
from .psychoacoustic_controls import PsychoacousticControls, apply_controls
from .psychoacoustics import CalibrationSpec, analyze_file, analyze_signal, load_mono
from .spatial_render import render_to_file
from .spatial_scene import Room, SpatialObject, SpatialScene, make_scene, object_from_analysis


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mus-spatial",
        description="Psychoacoustic analysis, mono objectization and spatial-scene authoring for MUS.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    new = commands.add_parser("new", help="create an empty editable spatial canvas project")
    new.add_argument("--output-dir", type=Path, required=True)
    new.add_argument("--title", default="MUS psychoacoustic spatial canvas")
    new.add_argument("--sample-rate", type=int, default=48000)
    new.add_argument("--duration-seconds", type=float, default=1.0)
    new.add_argument("--room-wet", type=float, default=0.16)
    new.add_argument("--room-decay", type=float, default=1.6)

    analyze = commands.add_parser("analyze", help="produce a psychoacoustic report for one sound")
    analyze.add_argument("audio", type=Path)
    analyze.add_argument("--output", type=Path)
    analyze.add_argument("--sample-rate", type=int)
    analyze.add_argument("--no-standardized", action="store_true")
    _add_calibration_arguments(analyze)

    manipulate = commands.add_parser("manipulate", help="apply cue-targeted psychoacoustic interventions")
    manipulate.add_argument("audio", type=Path)
    manipulate.add_argument("output", type=Path)
    _add_control_arguments(manipulate)

    decompose = commands.add_parser("decompose", help="turn mono audio into additive object candidates")
    decompose.add_argument("audio", type=Path)
    decompose.add_argument("--output-dir", type=Path, required=True)
    decompose.add_argument("--method", choices=("events", "nmf", "hybrid", "bands", "hpss"), default="events")
    decompose.add_argument("--regions", type=Path, help="event/segment JSON; otherwise generic proposals are generated")
    decompose.add_argument("--components", type=int, default=4)
    decompose.add_argument("--top-db", type=float, default=32.0)
    decompose.add_argument("--minimum-seconds", type=float, default=0.04)
    decompose.add_argument("--sample-rate", type=int)

    scene = commands.add_parser("scene", help="create an analyzed, editable spatial scene from mono audio")
    scene.add_argument("audio", type=Path)
    scene.add_argument("--output-dir", type=Path, required=True)
    scene.add_argument("--title")
    scene.add_argument("--mode", choices=("whole", "events", "nmf", "hybrid", "bands", "hpss"), default="events")
    scene.add_argument("--regions", type=Path)
    scene.add_argument("--components", type=int, default=4)
    scene.add_argument("--top-db", type=float, default=32.0)
    scene.add_argument("--minimum-seconds", type=float, default=0.04)
    scene.add_argument("--sample-rate", type=int)
    scene.add_argument("--include-residual", action=argparse.BooleanOptionalAction, default=True)
    scene.add_argument("--room-wet", type=float, default=0.16)
    scene.add_argument("--room-decay", type=float, default=1.6)
    scene.add_argument("--no-standardized", action="store_true")
    _add_calibration_arguments(scene)

    render = commands.add_parser("render", help="render a scene to deterministic stereo or FOA AmbiX")
    render.add_argument("scene", type=Path)
    render.add_argument("output", type=Path)
    render.add_argument("--target", choices=("stereo", "foa"), default="stereo")
    render.add_argument("--block-size", type=int, default=256)

    serve = commands.add_parser("serve", help="open the Web Audio HRTF spatial canvas")
    serve.add_argument("scene", type=Path)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--editable", action="store_true")
    serve.add_argument("--save-path", type=Path)

    validate = commands.add_parser("validate", help="parse and validate a scene contract")
    validate.add_argument("scene", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "new":
        if args.sample_rate < 8000:
            raise ValueError("sample rate must be at least 8000 Hz")
        if args.duration_seconds <= 0:
            raise ValueError("duration must be positive")
        root = args.output_dir
        root.mkdir(parents=True, exist_ok=True)
        scene = make_scene(
            args.title,
            args.sample_rate,
            args.duration_seconds,
            [],
            metadata={
                "constructionMode": "empty-canvas",
                "epistemicPosture": "Uploaded components are editable canvas material; spatial placement is authored, not reconstructed.",
            },
        )
        scene = replace(
            scene,
            room=Room(enabled=args.room_wet > 0, wet=args.room_wet, decay_seconds=args.room_decay),
        )
        scene_path = scene.write(root / "scene.json")
        _emit(
            {
                "scene": str(scene_path),
                "canvas": f"mus-spatial serve {scene_path} --editable",
                "next": "Open the canvas and use Add sound to ingest recordings.",
            },
            None,
        )
        return 0
    if args.command == "analyze":
        report = analyze_file(
            args.audio,
            calibration=_calibration_from_args(args),
            sample_rate=args.sample_rate,
            include_standardized=not args.no_standardized,
        )
        _emit(report.to_dict(), args.output)
        return 0

    if args.command == "manipulate":
        y, sr = load_mono(args.audio)
        controls = _controls_from_args(args)
        result, receipt = apply_controls(y, sr, controls)
        _, _, _, sf = _audio_dependencies()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        sf.write(args.output, result, sr, subtype="FLOAT")
        receipt_path = args.output.with_suffix(args.output.suffix + ".receipt.json")
        receipt_path.write_text(json.dumps(receipt.to_dict(), indent=2, sort_keys=True) + "\n", "utf-8")
        _emit({"output": str(args.output), "receipt": str(receipt_path), "details": receipt.to_dict()}, None)
        return 0

    if args.command == "decompose":
        y, sr = load_mono(args.audio, sample_rate=args.sample_rate)
        result = _decompose(
            y,
            sr,
            method=args.method,
            regions_path=args.regions,
            components=args.components,
            top_db=args.top_db,
            minimum_seconds=args.minimum_seconds,
        )
        report, files = write_decomposition(result, args.output_dir)
        _emit({"report": str(report), "stems": files, "closureRmsError": result.closure_rms_error}, None)
        return 0

    if args.command == "scene":
        scene_path = build_scene_from_audio(
            args.audio,
            args.output_dir,
            title=args.title,
            mode=args.mode,
            regions_path=args.regions,
            components=args.components,
            top_db=args.top_db,
            minimum_seconds=args.minimum_seconds,
            sample_rate=args.sample_rate,
            include_residual=args.include_residual,
            room_wet=args.room_wet,
            room_decay=args.room_decay,
            calibration=_calibration_from_args(args),
            include_standardized=not args.no_standardized,
        )
        _emit({"scene": str(scene_path), "canvas": f"mus-spatial serve {scene_path} --editable"}, None)
        return 0

    if args.command == "render":
        receipt = render_to_file(args.scene, args.output, target=args.target, block_size=args.block_size)
        _emit(receipt.to_dict(), None)
        return 0

    if args.command == "serve":
        serve_canvas(
            args.scene,
            host=args.host,
            port=args.port,
            editable=args.editable,
            save_path=args.save_path,
        )
        return 0

    if args.command == "validate":
        scene = SpatialScene.read(args.scene)
        missing = []
        for obj in scene.objects:
            target = (args.scene.parent / obj.audio).resolve()
            if not target.is_file():
                missing.append({"objectId": obj.object_id, "audio": obj.audio})
        _emit(
            {
                "ok": not missing,
                "sceneId": scene.scene_id,
                "objects": len(scene.objects),
                "durationSeconds": scene.duration_seconds,
                "missingAudio": missing,
            },
            None,
        )
        return 0 if not missing else 2
    raise AssertionError(args.command)


def build_scene_from_audio(
    audio_path: str | Path,
    output_dir: str | Path,
    *,
    title: str | None = None,
    mode: str = "events",
    regions_path: str | Path | None = None,
    components: int = 4,
    top_db: float = 32.0,
    minimum_seconds: float = 0.04,
    sample_rate: int | None = None,
    include_residual: bool = True,
    room_wet: float = 0.16,
    room_decay: float = 1.6,
    calibration: CalibrationSpec | None = None,
    include_standardized: bool = True,
) -> Path:
    """Build a complete scene directory from one mono recording."""
    np, _, _, sf = _audio_dependencies()
    source = Path(audio_path)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    y, sr = load_mono(source, sample_rate=sample_rate)
    scene_title = title or source.stem
    analyses_dir = root / "analysis"
    analyses_dir.mkdir(parents=True, exist_ok=True)

    if mode == "whole":
        objects_dir = root / "objects"
        objects_dir.mkdir(parents=True, exist_ok=True)
        target = objects_dir / "source.wav"
        sf.write(target, y, sr, subtype="FLOAT")
        report = analyze_signal(
            y,
            sr,
            source_id=_source_id(source),
            calibration=calibration,
            include_standardized=include_standardized,
        ).to_dict()
        analysis_path = analyses_dir / "source.json"
        analysis_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
        obj = object_from_analysis(
            object_id="source",
            label=source.stem,
            audio=target.relative_to(root).as_posix(),
            start_seconds=0.0,
            duration_seconds=len(y) / sr,
            analysis=report,
            kind="extended",
        )
        scene = make_scene(
            scene_title,
            sr,
            len(y) / sr,
            (obj,),
            metadata={
                "sourceAudio": str(source),
                "constructionMode": "whole",
                "analysisFile": analysis_path.relative_to(root).as_posix(),
            },
        )
    else:
        result = _decompose(
            y,
            sr,
            method=mode,
            regions_path=Path(regions_path) if regions_path else None,
            components=components,
            top_db=top_db,
            minimum_seconds=minimum_seconds,
        )
        decomposition_path, files = write_decomposition(result, root / "decomposition")
        objects: list[SpatialObject] = []
        family_counts: dict[str, int] = {}
        for stem in result.stems:
            family = _family_for_stem(stem)
            family_counts[family] = family_counts.get(family, 0) + 1
        family_indices: dict[str, int] = {}
        for stem in result.stems:
            relative_from_decomposition = files[stem.stem_id]
            audio_relative = (Path("decomposition") / relative_from_decomposition).as_posix()
            report = analyze_signal(
                stem.audio,
                sr,
                source_id=stem.stem_id,
                calibration=calibration,
                include_standardized=include_standardized,
            ).to_dict()
            safe_name = _slug(stem.label) + "-" + stem.stem_id[-10:]
            analysis_path = analyses_dir / f"{safe_name}.json"
            analysis_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
            family = _family_for_stem(stem)
            index = family_indices.get(family, 0)
            family_indices[family] = index + 1
            kind = "point" if stem.kind == "event-component" else "extended"
            source_region = asdict(stem.source_region) if stem.source_region else None
            obj = object_from_analysis(
                object_id=stem.stem_id,
                label=stem.label,
                audio=audio_relative,
                start_seconds=stem.start_seconds,
                duration_seconds=len(stem.audio) / sr,
                analysis=report,
                kind=kind,
                source_region=source_region,
                family=family,
                index=index,
                count=family_counts[family],
            )
            objects.append(obj)

        if include_residual:
            residual_relative = Path("decomposition") / "residual.wav"
            residual_report = analyze_signal(
                result.residual.audio,
                sr,
                source_id=result.residual.stem_id,
                calibration=calibration,
                include_standardized=include_standardized,
            ).to_dict()
            residual_analysis = analyses_dir / "residual.json"
            residual_analysis.write_text(json.dumps(residual_report, indent=2, sort_keys=True) + "\n", "utf-8")
            residual_obj = object_from_analysis(
                object_id=result.residual.stem_id,
                label=result.residual.label,
                audio=residual_relative.as_posix(),
                start_seconds=0.0,
                duration_seconds=len(result.residual.audio) / sr,
                analysis=residual_report,
                kind="ambient",
                family="residual-field",
            )
            residual_obj = replace(
                residual_obj,
                gain_db=-3.0,
                spread=max(0.88, residual_obj.spread),
                reverb_send=max(0.18, residual_obj.reverb_send),
                placement_provenance="composition-authored-from-residual",
            )
            objects.append(residual_obj)

        scene = make_scene(
            scene_title,
            sr,
            len(y) / sr,
            objects,
            metadata={
                "sourceAudio": str(source),
                "constructionMode": mode,
                "decompositionReport": decomposition_path.relative_to(root).as_posix(),
                "closureRmsError": result.closure_rms_error,
                "closurePeakError": result.closure_peak_error,
                "epistemicPosture": "Components are editable acoustic hypotheses and canvas material, not recovered historical source positions.",
            },
        )

    # Room parameters are authored scene defaults, not analysis inferences.
    scene = SpatialScene(
        scene_id=scene.scene_id,
        title=scene.title,
        sample_rate=scene.sample_rate,
        duration_seconds=scene.duration_seconds,
        objects=scene.objects,
        listener=scene.listener,
        room=Room(enabled=room_wet > 0.0, wet=room_wet, decay_seconds=room_decay),
        coordinate_system=scene.coordinate_system,
        metadata=scene.metadata,
    )
    scene_path = root / "scene.json"
    scene.write(scene_path)
    return scene_path


def _decompose(
    y: Any,
    sr: int,
    *,
    method: str,
    regions_path: Path | None,
    components: int,
    top_db: float,
    minimum_seconds: float,
) -> DecompositionResult:
    if method == "nmf":
        return nmf_decomposition(y, sr, components=components)
    if method == "bands":
        return auditory_band_decomposition(y, sr, bands=components)
    if method == "hpss":
        return hpss_decomposition(y, sr)
    regions = read_regions(regions_path) if regions_path else propose_regions(
        y,
        sr,
        top_db=top_db,
        minimum_seconds=minimum_seconds,
    )
    if method == "events":
        return event_soft_mask_decomposition(y, sr, regions)
    if method == "hybrid":
        return hybrid_decomposition(y, sr, regions, components=components)
    raise ValueError(f"unknown decomposition method: {method}")


def _family_for_stem(stem: Stem) -> str:
    if stem.source_region:
        metadata = stem.source_region.metadata
        for key in ("family", "voice", "cluster", "shape"):
            value = metadata.get(key)
            if value is not None:
                return str(value)
        if stem.source_region.label:
            return stem.source_region.label
    return stem.kind


def _source_id(path: Path) -> str:
    from hashlib import sha256

    return f"urn:sophia:mus:audio:sha256:{sha256(path.read_bytes()).hexdigest()}"


def _add_calibration_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("pressure calibration")
    group.add_argument("--pa-per-unit", type=float)
    group.add_argument("--reference-rms-dbfs", type=float)
    group.add_argument("--reference-spl-db", type=float)
    group.add_argument("--field-type", choices=("free", "diffuse"), default="free")
    group.add_argument("--calibration-note")


def _calibration_from_args(args: argparse.Namespace) -> CalibrationSpec:
    if getattr(args, "pa_per_unit", None) is not None:
        return CalibrationSpec(
            kind="pascal-per-digital-unit",
            pascal_per_digital_unit=args.pa_per_unit,
            field_type=args.field_type,
            note=args.calibration_note,
        )
    rms = getattr(args, "reference_rms_dbfs", None)
    spl = getattr(args, "reference_spl_db", None)
    if rms is not None or spl is not None:
        if rms is None or spl is None:
            raise ValueError("reference calibration requires both --reference-rms-dbfs and --reference-spl-db")
        return CalibrationSpec(
            kind="reference-rms",
            reference_rms_dbfs=rms,
            reference_spl_db=spl,
            field_type=args.field_type,
            note=args.calibration_note,
        )
    return CalibrationSpec(kind="relative", field_type=getattr(args, "field_type", "free"), note=getattr(args, "calibration_note", None))


def _add_control_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--gain-db", type=float, default=0.0)
    parser.add_argument("--target-lufs", type=float)
    parser.add_argument("--brightness-db", type=float, default=0.0)
    parser.add_argument("--brightness-hz", type=float, default=2500.0)
    parser.add_argument("--roughness-depth", type=float, default=0.0)
    parser.add_argument("--roughness-rate-hz", type=float, default=70.0)
    parser.add_argument("--fluctuation-depth", type=float, default=0.0)
    parser.add_argument("--fluctuation-rate-hz", type=float, default=4.0)
    parser.add_argument("--attack-seconds", type=float)
    parser.add_argument("--pitch-semitones", type=float, default=0.0)
    parser.add_argument("--tonal-focus", type=float, default=0.0)
    parser.add_argument("--safety-peak", type=float, default=0.98)


def _controls_from_args(args: argparse.Namespace) -> PsychoacousticControls:
    return PsychoacousticControls(
        gain_db=args.gain_db,
        target_lufs=args.target_lufs,
        brightness_db=args.brightness_db,
        brightness_hz=args.brightness_hz,
        roughness_depth=args.roughness_depth,
        roughness_rate_hz=args.roughness_rate_hz,
        fluctuation_depth=args.fluctuation_depth,
        fluctuation_rate_hz=args.fluctuation_rate_hz,
        attack_seconds=args.attack_seconds,
        pitch_semitones=args.pitch_semitones,
        tonal_focus=args.tonal_focus,
        safety_peak=args.safety_peak,
    )


def _emit(value: Any, output: Path | None) -> None:
    text = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if output is None:
        print(text, end="")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, "utf-8")


def _slug(value: str) -> str:
    text = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    return "-".join(piece for piece in text.split("-") if piece)[:56] or "sound"


def _audio_dependencies() -> tuple[Any, Any, Any, Any]:
    try:
        import numpy as np
        from scipy import signal as scipy_signal
        import librosa
        import soundfile as sf
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("mus-spatial requires the 'spatial' optional dependencies") from exc
    return np, scipy_signal, librosa, sf


if __name__ == "__main__":
    raise SystemExit(main())
