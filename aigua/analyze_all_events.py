#!/usr/bin/env python3
"""Sweep the pitch ensemble and gesture bundle over every reconciled event.

Implements ANALYSIS-V2.md §9 item 5: run the pitch ensemble over all
historical events and replace the old span distribution with a
method-sensitive report.

Reads the reconciled hypotheses produced by `mus-analysis segment-audio`,
runs the three-estimator pitch ensemble plus the gesture bundle on each
region, and writes:

  aigua/v2/sweep-events.json   one compact record per hypothesis, including
                               the consensus contour as (t, hz, state) rows
  aigua/v2/sweep-report.json   the aggregate method-sensitive span report

plus one sweep-level run receipt in the research object. Full frame
trajectories are deliberately not persisted per event: the array-artifact
policy (§9 item 2) is not ratified, so dense series stay out of durable
storage and the compact contour is the honest middle ground.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mus_analysis.audio_gesture import analyze_gesture
from mus_analysis.audio_pitch import (
    PitchExtractionConfig,
    extract_reference_ensemble,
    load_audio_region,
)
from mus_analysis.canonical import normalize
from mus_analysis.model import OperatorRef, ProfileRef, RunReceipt, RunStatus
from mus_analysis.pitch import build_pitch_consensus
from mus_analysis.run import utc_now
from mus_analysis.store import ResearchObjectStore

STATE_CODES = {"resolved": "r", "octave-conflict": "o", "disagreement": "d"}


def interval_iou(a0: float, a1: float, b0: float, b1: float) -> float:
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    return inter / union if union > 0 else 0.0


def match_v1_event(h: dict, v1_events: list[dict]) -> dict | None:
    best, best_iou = None, 0.0
    for e in v1_events:
        iou = interval_iou(h["start_seconds"], h["end_seconds"], e["t0"], e["t1"])
        if iou > best_iou:
            best, best_iou = e, iou
    if best is not None and best_iou >= 0.3:
        return {"v1_id": best["id"], "iou": round(best_iou, 3),
                "v1_span_st": best.get("span_st"), "v1_f0_med": best.get("f0_med"),
                "v1_cluster": best.get("cluster")}
    return None


def compact_contour(frames: list[dict]) -> list[list]:
    rows = []
    for f in frames:
        state = STATE_CODES.get(f.get("status"), "?")
        hz = f.get("frequency_hz")
        octave_hz = f.get("octave_equivalent_frequency_hz")
        rows.append([
            round(float(f["time_seconds"]), 4),
            None if hz is None else round(float(hz), 1),
            state,
            None if octave_hz is None else round(float(octave_hz), 1),
        ])
    return rows


def resolved_span_st(frames: list[dict]) -> tuple[float | None, int]:
    freqs = [f["frequency_hz"] for f in frames if f.get("frequency_hz")]
    if len(freqs) < 5:
        return None, len(freqs)
    return 12.0 * math.log2(max(freqs) / min(freqs)), len(freqs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", type=Path, default=ROOT / "aigua" / "aigua_raw.wav")
    ap.add_argument("--segmentation", type=Path, default=ROOT / "aigua" / "v2" / "segmentation.json")
    ap.add_argument("--v1-events", type=Path, default=ROOT / "aigua" / "events.json")
    ap.add_argument("--store", type=Path, default=ROOT / "aigua" / "research-object")
    ap.add_argument("--out-events", type=Path, default=ROOT / "aigua" / "v2" / "sweep-events.json")
    ap.add_argument("--out-report", type=Path, default=ROOT / "aigua" / "v2" / "sweep-report.json")
    ap.add_argument("--sample-rate", type=int, default=48000)
    ap.add_argument("--n-fft", type=int, default=2048)
    ap.add_argument("--hop-length", type=int, default=128)
    ap.add_argument("--fmin-hz", type=float, default=500.0)
    ap.add_argument("--fmax-hz", type=float, default=8000.0)
    ap.add_argument("--consensus-spread-cents", type=float, default=80.0)
    ap.add_argument("--gesture-spread-cents", type=float, default=100.0)
    args = ap.parse_args()

    started = utc_now()
    seg = json.loads(args.segmentation.read_text("utf-8"))
    hypotheses = seg["reconciledHypotheses"]
    v1_events = json.loads(args.v1_events.read_text("utf-8"))
    if isinstance(v1_events, dict):
        v1_events = v1_events.get("events", [])

    y_full, sr = load_audio_region(args.audio, sample_rate=args.sample_rate)
    config = PitchExtractionConfig(
        sample_rate=sr, n_fft=args.n_fft, hop_length=args.hop_length,
        fmin_hz=args.fmin_hz, fmax_hz=args.fmax_hz,
    )

    records, failures = [], []
    for i, h in enumerate(hypotheses):
        t0, t1 = h["start_seconds"], h["end_seconds"]
        y = y_full[int(t0 * sr): int(t1 * sr)]
        record = {
            "hypothesis_id": h["hypothesis_id"],
            "start_seconds": t0,
            "end_seconds": t1,
            "support_fraction": h["support_fraction"],
            "ambiguous_split_or_merge": h["ambiguous_split_or_merge"],
            "v1_match": match_v1_event(h, v1_events),
        }
        try:
            trajectories = extract_reference_ensemble(y, sr, config)
            consensus = normalize(build_pitch_consensus(
                trajectories,
                minimum_estimators=2,
                maximum_spread_cents=args.consensus_spread_cents,
                maximum_time_delta_seconds=0.5 * args.hop_length / sr,
            ))
            bundle = normalize(analyze_gesture(
                y, sr, config, maximum_pitch_spread_cents=args.gesture_spread_cents,
            ))
            frames = consensus["frames"]
            span, n_resolved = resolved_span_st(frames)
            record.update({
                "consensus_summary": consensus["summary"],
                "resolved_span_st": None if span is None else round(span, 2),
                "resolved_frame_count": n_resolved,
                "gesture_summary": bundle.get("summary", {}),
                "contour": compact_contour(frames),
            })
        except Exception as exc:  # a refused event is a result, not a crash
            record["error"] = f"{type(exc).__name__}: {exc}"
            failures.append(record["hypothesis_id"])
        records.append(record)
        if (i + 1) % 10 == 0:
            print(f"  {i + 1}/{len(hypotheses)} events analysed", file=sys.stderr)

    # ---- aggregate: the method-sensitive span report -----------------------
    analysed = [r for r in records if "error" not in r]
    spans = [r["resolved_span_st"] for r in analysed if r["resolved_span_st"] is not None]
    spans_sorted = sorted(spans)

    def pct(p: float) -> float:
        return spans_sorted[min(len(spans_sorted) - 1, int(p * len(spans_sorted)))]

    state_totals = {"resolved": 0, "octave-conflict": 0, "disagreement": 0}
    for r in analysed:
        s = r["consensus_summary"]
        state_totals["resolved"] += s["resolved_frame_count"]
        state_totals["octave-conflict"] += s["octave_conflict_count"]
        state_totals["disagreement"] += s["disagreement_count"]

    paired = [
        {"hypothesis_id": r["hypothesis_id"], "v1_id": r["v1_match"]["v1_id"],
         "v1_span_st": r["v1_match"]["v1_span_st"], "v2_span_st": r["resolved_span_st"],
         "iou": r["v1_match"]["iou"]}
        for r in analysed
        if r["v1_match"] is not None and r["resolved_span_st"] is not None
        and r["v1_match"]["v1_span_st"] is not None
    ]

    # consensus pitch field: fold every resolved frame to cents-vs-A440
    bins = [0] * 120  # 10-cent bins across one octave
    for r in analysed:
        for _, hz, state, _ in r["contour"]:
            if state == "r" and hz:
                cents = (1200.0 * math.log2(hz / 440.0)) % 1200.0
                bins[int(cents // 10) % 120] += 1
    peak_bin = max(range(120), key=lambda b: bins[b])

    report = {
        "schema": "aigua-sweep-report/1",
        "profile": {
            "fminHz": args.fmin_hz, "fmaxHz": args.fmax_hz,
            "consensusSpreadCents": args.consensus_spread_cents,
            "minimumEstimators": 2,
        },
        "event_counts": {
            "hypotheses": len(records),
            "analysed": len(analysed),
            "failed": len(failures),
            "span_defined": len(spans),
            "span_undefined": len(analysed) - len(spans),
        },
        "resolved_span_st": {
            "median": round(pct(0.5), 2), "p90": round(pct(0.9), 2),
            "min": round(min(spans), 2), "max": round(max(spans), 2),
        } if spans else None,
        "v1_span_st_reference": {"median": 18.67, "p90": 26.9, "max": 31.86},
        "frame_state_totals": state_totals,
        "paired_span_comparison": paired,
        "consensus_pitch_field": {
            "bins_10_cents_vs_a440": bins,
            "peak_cents_vs_a440": peak_bin * 10 + 5,
        },
        "failures": failures,
    }

    args.out_events.write_text(json.dumps({
        "schema": "aigua-sweep-events/1",
        "segmentation": str(args.segmentation),
        "events": records,
    }, indent=1), "utf-8")
    args.out_report.write_text(json.dumps(report, indent=1), "utf-8")

    store = ResearchObjectStore(args.store)
    input_audio = store.put_file(args.audio, role="sweep-audio-input")
    input_seg = store.put_json(seg, role="sweep-segmentation-input")
    out_events_ref = store.put_json(json.loads(args.out_events.read_text("utf-8")), role="sweep-events-result")
    out_report_ref = store.put_json(report, role="sweep-report-result")
    receipt = RunReceipt.identified(
        run_type="pitch-gesture-sweep",
        profile=ProfileRef("aigua.pitch-gesture-sweep", "1"),
        status=RunStatus.SUCCEEDED,
        producer="aigua.analyze_all_events/1",
        started_at=started,
        completed_at=utc_now(),
        inputs=(input_audio, input_seg),
        outputs=(out_events_ref, out_report_ref),
        operators=(
            OperatorRef("aigua.shs-log-cents", "2"),
            OperatorRef("librosa.pyin", "0.11"),
            OperatorRef("aigua.dominant-spectral-ridge", "1"),
            OperatorRef("mus.pitch-consensus", "1"),
            OperatorRef("mus.gesture-bundle", "1"),
        ),
        parameters={
            "config": config,
            "consensusSpreadCents": args.consensus_spread_cents,
            "gestureSpreadCents": args.gesture_spread_cents,
        },
        environment={"sampleRate": sr},
    )
    store.write_run(receipt)
    store.write_manifest()
    print(json.dumps({
        "runId": receipt.run_id,
        "events": len(records),
        "failed": len(failures),
        "report": str(args.out_report),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
