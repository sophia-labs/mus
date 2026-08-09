"""Command-line interface for the MUS analysis research-object layer."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from .aigua_v1 import import_aigua_v1
from .audio_gesture import analyze_gesture, persist_gesture_bundle
from .audio_pitch import PitchExtractionConfig, extract_reference_ensemble, load_audio_region
from .audio_segmentation import SegmentationConfig, aigua_hysteresis_segmentation, pcen_segmentation
from .canonical import canonical_text, normalize
from .clustering import coassignment_matrix, consensus_components, item_stability
from .pitch import PitchSample, PitchTrajectory, build_pitch_consensus
from .segmentation import Segment, reconcile_segmentations
from .model import OperatorRef, ProfileRef, RunReceipt, RunStatus
from .run import utc_now
from .store import ResearchObjectStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mus-analysis")
    sub = parser.add_subparsers(dest="command", required=True)

    import_v1 = sub.add_parser("import-aigua-v1", help="preserve Aigua v1 as an immutable research object")
    import_v1.add_argument("--project-root", type=Path, default=Path.cwd())
    import_v1.add_argument("--store", type=Path, default=Path("aigua/research-object"))
    import_v1.add_argument("--config", type=Path)

    verify = sub.add_parser("verify", help="verify object digests and run references")
    verify.add_argument("--store", type=Path, required=True)

    manifest = sub.add_parser("manifest", help="print the current store index")
    manifest.add_argument("--store", type=Path, required=True)

    segment_audio = sub.add_parser("segment-audio", help="run independent Aigua and PCEN proposal lanes and reconcile them")
    segment_audio.add_argument("audio", type=Path)
    segment_audio.add_argument("--output", type=Path)
    segment_audio.add_argument("--store", type=Path)
    segment_audio.add_argument("--start-seconds", type=float)
    segment_audio.add_argument("--end-seconds", type=float)
    segment_audio.add_argument("--sample-rate", type=int, default=48000)
    segment_audio.add_argument("--n-fft", type=int, default=1024)
    segment_audio.add_argument("--hop-length", type=int, default=128)
    segment_audio.add_argument("--band-low-hz", type=float, default=900.0)
    segment_audio.add_argument("--band-high-hz", type=float, default=11000.0)
    segment_audio.add_argument("--noise-block-seconds", type=float, default=2.0)
    segment_audio.add_argument("--minimum-link-iou", type=float, default=0.15)

    gesture = sub.add_parser("analyze-gesture", help="extract continuous spectral, modulation and consensus-pitch trajectories")
    gesture.add_argument("audio", type=Path)
    gesture.add_argument("--output", type=Path)
    gesture.add_argument("--store", type=Path)
    gesture.add_argument("--start-seconds", type=float)
    gesture.add_argument("--end-seconds", type=float)
    gesture.add_argument("--sample-rate", type=int, default=48000)
    gesture.add_argument("--n-fft", type=int, default=2048)
    gesture.add_argument("--hop-length", type=int, default=128)
    gesture.add_argument("--fmin-hz", type=float, default=500.0)
    gesture.add_argument("--fmax-hz", type=float, default=8000.0)
    gesture.add_argument("--maximum-spread-cents", type=float, default=100.0)

    extract = sub.add_parser("extract-pitch", help="run the Aigua reference pitch ensemble over an audio region")
    extract.add_argument("audio", type=Path)
    extract.add_argument("--output", type=Path)
    extract.add_argument("--store", type=Path)
    extract.add_argument("--start-seconds", type=float)
    extract.add_argument("--end-seconds", type=float)
    extract.add_argument("--sample-rate", type=int, default=48000)
    extract.add_argument("--n-fft", type=int, default=2048)
    extract.add_argument("--hop-length", type=int, default=128)
    extract.add_argument("--fmin-hz", type=float, default=500.0)
    extract.add_argument("--fmax-hz", type=float, default=8000.0)
    extract.add_argument("--maximum-spread-cents", type=float, default=80.0)

    pitch = sub.add_parser("pitch-consensus", help="reconcile several pitch trajectories without hiding disagreement")
    pitch.add_argument("input", type=Path)
    pitch.add_argument("--output", type=Path)
    pitch.add_argument("--minimum-estimators", type=int, default=2)
    pitch.add_argument("--maximum-spread-cents", type=float, default=80.0)
    pitch.add_argument("--maximum-time-delta-seconds", type=float, default=0.006)

    segments = sub.add_parser("reconcile-segments", help="build a segmentation lattice across detector runs")
    segments.add_argument("input", type=Path)
    segments.add_argument("--output", type=Path)
    segments.add_argument("--minimum-link-iou", type=float, default=0.15)
    segments.add_argument("--boundary-tolerance-seconds", type=float, default=0.02)

    clusters = sub.add_parser("cluster-stability", help="summarize co-assignment across model/bootstrap runs")
    clusters.add_argument("input", type=Path)
    clusters.add_argument("--output", type=Path)
    clusters.add_argument("--threshold", type=float, default=0.8)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "import-aigua-v1":
        config = None
        if args.config:
            config = json.loads(args.config.read_text("utf-8"))
        projection = import_aigua_v1(args.project_root, args.store, config=config)
        _emit({"projectionId": projection.projection_id, "store": str(args.store)}, None)
        return 0
    if args.command == "segment-audio":
        y, sr = load_audio_region(
            args.audio,
            sample_rate=args.sample_rate,
            start_seconds=args.start_seconds,
            end_seconds=args.end_seconds,
        )
        config = SegmentationConfig(
            sample_rate=sr,
            n_fft=args.n_fft,
            hop_length=args.hop_length,
            band_low_hz=args.band_low_hz,
            band_high_hz=args.band_high_hz,
            noise_block_seconds=args.noise_block_seconds,
        )
        historical = aigua_hysteresis_segmentation(y, sr, config)
        pcen = pcen_segmentation(y, sr, config)
        hypotheses, relations = reconcile_segmentations(
            {historical.run_id: historical.segments, pcen.run_id: pcen.segments},
            minimum_link_iou=args.minimum_link_iou,
        )
        payload = {
            "schema": "mus-audio-segmentation-analysis/1",
            "audio": str(args.audio),
            "region": {"startSeconds": args.start_seconds, "endSeconds": args.end_seconds},
            "config": config,
            "proposalRuns": [historical, pcen],
            "reconciledHypotheses": hypotheses,
            "relations": relations,
        }
        _emit(payload, args.output)
        _capture_internal_run(
            args.store,
            args.audio,
            payload,
            run_type="segmentation-lattice",
            profile_id="aigua.segmentation-lattice",
            producer="mus-analysis.segment-audio/1",
            operators=(
                OperatorRef("aigua.local-floor-hysteresis", "2"),
                OperatorRef("aigua.pcen-activity-hysteresis", "1"),
                OperatorRef("mus.segmentation-reconciliation", "1"),
            ),
            parameters={"config": config, "minimumLinkIou": args.minimum_link_iou},
        )
        return 0
    if args.command == "analyze-gesture":
        y, sr = load_audio_region(
            args.audio,
            sample_rate=args.sample_rate,
            start_seconds=args.start_seconds,
            end_seconds=args.end_seconds,
        )
        config = PitchExtractionConfig(
            sample_rate=sr,
            n_fft=args.n_fft,
            hop_length=args.hop_length,
            fmin_hz=args.fmin_hz,
            fmax_hz=args.fmax_hz,
        )
        bundle = analyze_gesture(
            y,
            sr,
            config,
            maximum_pitch_spread_cents=args.maximum_spread_cents,
        )
        payload = {
            "schema": "mus-audio-gesture-analysis/1",
            "audio": str(args.audio),
            "region": {"startSeconds": args.start_seconds, "endSeconds": args.end_seconds},
            "bundle": bundle,
        }
        _emit(payload, args.output)
        _capture_gesture_run(
            args.store,
            args.audio,
            bundle,
            parameters={"config": config, "maximumSpreadCents": args.maximum_spread_cents},
        )
        return 0
    if args.command == "extract-pitch":
        y, sr = load_audio_region(
            args.audio,
            sample_rate=args.sample_rate,
            start_seconds=args.start_seconds,
            end_seconds=args.end_seconds,
        )
        config = PitchExtractionConfig(
            sample_rate=sr,
            n_fft=args.n_fft,
            hop_length=args.hop_length,
            fmin_hz=args.fmin_hz,
            fmax_hz=args.fmax_hz,
        )
        trajectories = extract_reference_ensemble(y, sr, config)
        consensus = build_pitch_consensus(
            trajectories,
            minimum_estimators=2,
            maximum_spread_cents=args.maximum_spread_cents,
            maximum_time_delta_seconds=0.5 * args.hop_length / sr,
        )
        payload = {
            "schema": "mus-pitch-ensemble/1",
            "audio": str(args.audio),
            "region": {"startSeconds": args.start_seconds, "endSeconds": args.end_seconds},
            "config": config,
            "trajectories": trajectories,
            "consensus": consensus,
        }
        _emit(payload, args.output)
        if args.store:
            store = ResearchObjectStore(args.store)
            input_ref = store.put_file(args.audio, role="pitch-analysis-input")
            output_ref = store.put_json(payload, role="pitch-ensemble-result")
            started = completed = utc_now()
            receipt = RunReceipt.identified(
                run_type="pitch-consensus",
                profile=ProfileRef("aigua.pitch-consensus", "1"),
                status=RunStatus.SUCCEEDED,
                producer="mus-analysis.extract-pitch/1",
                started_at=started,
                completed_at=completed,
                inputs=(input_ref,),
                outputs=(output_ref,),
                operators=(
                    OperatorRef("aigua.shs-log-cents", "2"),
                    OperatorRef("librosa.pyin", "0.11"),
                    OperatorRef("aigua.dominant-spectral-ridge", "1"),
                    OperatorRef("mus.pitch-consensus", "1"),
                ),
                parameters={
                    "region": {"startSeconds": args.start_seconds, "endSeconds": args.end_seconds},
                    "config": config,
                    "maximumSpreadCents": args.maximum_spread_cents,
                },
                environment={"sampleRate": sr},
            )
            store.write_run(receipt)
            store.write_manifest()
            print(json.dumps({"runId": receipt.run_id, "resultArtifact": output_ref.uri}, indent=2))
        return 0
    if args.command == "pitch-consensus":
        payload = _read_object(args.input)
        trajectories = tuple(
            PitchTrajectory(
                str(item["estimatorId"]),
                tuple(
                    PitchSample(
                        float(sample["timeSeconds"]),
                        None if sample.get("frequencyHz") is None else float(sample["frequencyHz"]),
                        None if sample.get("score") is None else float(sample["score"]),
                        sample.get("scoreSemantics"),
                    )
                    for sample in item.get("samples", [])
                ),
            )
            for item in payload.get("trajectories", [])
        )
        result = build_pitch_consensus(
            trajectories,
            minimum_estimators=args.minimum_estimators,
            maximum_spread_cents=args.maximum_spread_cents,
            maximum_time_delta_seconds=args.maximum_time_delta_seconds,
        )
        _emit({"schema": "mus-pitch-consensus/1", "result": result}, args.output)
        return 0
    if args.command == "reconcile-segments":
        payload = _read_object(args.input)
        segmentations = {
            str(run_id): tuple(
                Segment(
                    str(item["segmentId"]),
                    str(run_id),
                    float(item["startSeconds"]),
                    float(item["endSeconds"]),
                )
                for item in rows
            )
            for run_id, rows in payload.get("segmentations", {}).items()
        }
        hypotheses, relations = reconcile_segmentations(
            segmentations,
            minimum_link_iou=args.minimum_link_iou,
            boundary_tolerance_seconds=args.boundary_tolerance_seconds,
        )
        _emit(
            {"schema": "mus-segmentation-lattice/1", "hypotheses": hypotheses, "relations": relations},
            args.output,
        )
        return 0
    if args.command == "cluster-stability":
        payload = _read_object(args.input)
        label_runs = payload.get("labelRuns", [])
        result = coassignment_matrix(label_runs)
        _emit(
            {
                "schema": "mus-cluster-stability/1",
                "coassignment": result,
                "itemStability": item_stability(result),
                "consensusComponents": consensus_components(result, threshold=args.threshold),
                "threshold": args.threshold,
            },
            args.output,
        )
        return 0

    store = ResearchObjectStore(args.store)
    if args.command == "verify":
        _emit(store.verify(), None)
        return 0
    if args.command == "manifest":
        _emit(store.manifest(), None)
        return 0
    raise AssertionError(args.command)


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _capture_gesture_run(
    store_path: Path | None,
    input_path: Path,
    bundle: Any,
    *,
    parameters: dict[str, Any],
) -> None:
    if store_path is None:
        return
    store = ResearchObjectStore(store_path)
    input_ref = store.put_file(input_path, role="vocal-gesture-input")
    persisted = persist_gesture_bundle(store, bundle)
    outputs = (persisted.manifest,) + tuple(ref.artifact for ref in persisted.arrays)
    started = completed = utc_now()
    receipt = RunReceipt.identified(
        run_type="vocal-gesture",
        profile=ProfileRef("aigua.vocal-gesture", "1"),
        status=RunStatus.SUCCEEDED,
        producer="mus-analysis.analyze-gesture/1",
        started_at=started,
        completed_at=completed,
        inputs=(input_ref,),
        outputs=outputs,
        operators=(
            OperatorRef("aigua.shs-log-cents", "2"),
            OperatorRef("librosa.pyin", "0.11"),
            OperatorRef("aigua.dominant-spectral-ridge", "1"),
            OperatorRef("mus.gesture-observation-bundle", "1"),
        ),
        parameters=parameters,
        environment={},
    )
    store.write_run(receipt)
    store.write_manifest()
    print(json.dumps({"runId": receipt.run_id, "resultArtifact": persisted.manifest.uri}, indent=2))


def _capture_internal_run(
    store_path: Path | None,
    input_path: Path,
    payload: Any,
    *,
    run_type: str,
    profile_id: str,
    producer: str,
    operators: tuple[OperatorRef, ...],
    parameters: dict[str, Any],
) -> None:
    if store_path is None:
        return
    store = ResearchObjectStore(store_path)
    input_ref = store.put_file(input_path, role=f"{run_type}-input")
    output_ref = store.put_json(payload, role=f"{run_type}-result")
    started = completed = utc_now()
    receipt = RunReceipt.identified(
        run_type=run_type,
        profile=ProfileRef(profile_id, "1"),
        status=RunStatus.SUCCEEDED,
        producer=producer,
        started_at=started,
        completed_at=completed,
        inputs=(input_ref,),
        outputs=(output_ref,),
        operators=operators,
        parameters=parameters,
        environment={},
    )
    store.write_run(receipt)
    store.write_manifest()
    print(json.dumps({"runId": receipt.run_id, "resultArtifact": output_ref.uri}, indent=2))


def _emit(value: Any, output: Path | None) -> None:
    text = canonical_text(value) + "\n"
    if output is None:
        print(json.dumps(normalize(value), indent=2, ensure_ascii=False, sort_keys=True))
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, "utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
