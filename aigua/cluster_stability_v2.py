#!/usr/bin/env python3
"""Fit bootstrap/model/feature-perturbation cluster ensembles over the sweep.

Implements ANALYSIS-V2.md §9 item 7: fit model and bootstrap ensembles, then
publish a co-assignment/stability report for the seven-family claim.

Reads aigua/v2/sweep-events.json (gesture + consensus summaries per reconciled
hypothesis), builds a feature matrix over the events with resolved pitch
material, generates label runs four ways:

  bootstrap   Ward k=7 on 200 bootstrap resamples (out-of-bag = missing)
  k-sweep     Ward at k = 4..10 on the full matrix
  algorithm   KMeans k=7 x 10 seeds, HDBSCAN (noise = missing)
  features    Ward k=7 leaving one feature column out at a time

then feeds them through mus_analysis.clustering (co-assignment, item
stability, consensus components) and compares consensus structure against the
historical v1 Ward partition on matched events via adjusted Rand index.

Events without enough resolved pitch are excluded and counted — exclusion is
reported, not hidden. Noise/missing labels are non-evidence by construction.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mus_analysis.clustering import (
    coassignment_matrix,
    consensus_components,
    item_stability,
)
from mus_analysis.canonical import normalize
from mus_analysis.model import OperatorRef, ProfileRef, RunReceipt, RunStatus
from mus_analysis.run import utc_now
from mus_analysis.store import ResearchObjectStore

FEATURES = [
    ("log_duration", lambda g, c: math.log(max(g["duration_seconds"], 1e-3))),
    ("log_median_pitch", lambda g, c: math.log2(g["median_pitch_hz"])),
    ("resolved_span_st", lambda g, c: g["pitch_span_semitones"]),
    ("median_abs_fm_velocity", lambda g, c: g["median_absolute_fm_velocity_semitones_per_second"]),
    ("fm_inflections_per_second", lambda g, c: g["fm_inflection_count"] / max(g["duration_seconds"], 1e-3)),
    ("log_centroid", lambda g, c: math.log2(max(g["median_spectral_centroid_hz"], 50.0))),
    ("centroid_range_octaves", lambda g, c: math.log2(1.0 + g["spectral_centroid_range_hz"] / max(g["median_spectral_centroid_hz"], 50.0))),
    ("attack_fraction", lambda g, c: g["attack_seconds"] / max(g["duration_seconds"], 1e-3)),
    ("resolved_fraction", lambda g, c: c["resolved_fraction"]),
    ("octave_conflict_fraction", lambda g, c: c["octave_conflict_count"] / max(c["total_frame_count"], 1)),
]

RANDOM_SEED = 20260809  # date-derived, recorded in the receipt


def build_matrix(events: list[dict]) -> tuple[np.ndarray, list[str], list[dict]]:
    ids, rows, kept = [], [], []
    for e in events:
        if "error" in e:
            continue
        g, c = e.get("gesture_summary") or {}, e.get("consensus_summary") or {}
        if not g or not c:
            continue
        if e.get("resolved_span_st") is None or not g.get("median_pitch_hz"):
            continue
        try:
            row = [fn(g, c) for _, fn in FEATURES]
        except (KeyError, TypeError, ValueError):
            continue
        if any(not np.isfinite(v) for v in row):
            continue
        ids.append(e["hypothesis_id"])
        rows.append(row)
        kept.append(e)
    return np.asarray(rows, dtype=float), ids, kept


def zscore(m: np.ndarray) -> np.ndarray:
    mu, sd = m.mean(axis=0), m.std(axis=0)
    sd[sd < 1e-9] = 1.0
    return (m - mu) / sd


def adjusted_rand(a: list[int], b: list[int]) -> float:
    from sklearn.metrics import adjusted_rand_score
    return float(adjusted_rand_score(a, b))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep-events", type=Path, default=ROOT / "aigua" / "v2" / "sweep-events.json")
    ap.add_argument("--store", type=Path, default=ROOT / "aigua" / "research-object")
    ap.add_argument("--out", type=Path, default=ROOT / "aigua" / "v2" / "cluster-stability-report.json")
    ap.add_argument("--bootstraps", type=int, default=200)
    ap.add_argument("--k", type=int, default=7)
    ap.add_argument("--threshold", type=float, default=0.8)
    args = ap.parse_args()

    from sklearn.cluster import AgglomerativeClustering, HDBSCAN, KMeans

    started = utc_now()
    payload = json.loads(args.sweep_events.read_text("utf-8"))
    events = payload["events"]
    X_raw, ids, kept = build_matrix(events)
    X = zscore(X_raw)
    n = len(ids)
    rng = np.random.default_rng(RANDOM_SEED)
    print(f"feature matrix: {n} events x {len(FEATURES)} features "
          f"({len(events) - n} excluded)", file=sys.stderr)

    label_runs: list[dict] = []
    run_kinds: list[str] = []

    def add_run(kind: str, labels: dict[str, int]) -> None:
        label_runs.append(labels)
        run_kinds.append(kind)

    ward = AgglomerativeClustering(n_clusters=args.k, linkage="ward")

    # 1. bootstrap Ward k=7 — out-of-bag events are simply absent from the run
    for _ in range(args.bootstraps):
        idx = rng.choice(n, size=n, replace=True)
        uniq = sorted(set(int(i) for i in idx))
        labels = ward.fit_predict(X[uniq])
        add_run("bootstrap-ward", {ids[u]: int(l) for u, l in zip(uniq, labels)})

    # 2. k-sweep on the full matrix
    for k in range(4, 11):
        labels = AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(X)
        add_run(f"ward-k{k}", {ids[i]: int(l) for i, l in enumerate(labels)})

    # 3. algorithm variation
    for seed in range(10):
        labels = KMeans(n_clusters=args.k, n_init=10, random_state=seed).fit_predict(X)
        add_run("kmeans-k7", {ids[i]: int(l) for i, l in enumerate(labels)})
    hdb = HDBSCAN(min_cluster_size=4).fit_predict(X)
    add_run("hdbscan", {ids[i]: int(l) for i, l in enumerate(hdb)})  # -1 = noise

    # 4. leave-one-feature-out
    for f in range(len(FEATURES)):
        Xf = np.delete(X, f, axis=1)
        labels = AgglomerativeClustering(n_clusters=args.k, linkage="ward").fit_predict(Xf)
        add_run(f"ward-k7-drop-{FEATURES[f][0]}", {ids[i]: int(l) for i, l in enumerate(labels)})

    result = coassignment_matrix(label_runs)
    stability = item_stability(result)
    components = consensus_components(result, threshold=args.threshold)

    # ---- against the v1 partition, on events matched to exactly one v1 event
    v1_labels, v2_full = [], []
    full_ward = ward.fit_predict(X)
    for i, e in enumerate(kept):
        m = e.get("v1_match")
        if m is not None and m.get("v1_cluster") is not None:
            v1_labels.append(int(m["v1_cluster"]))
            v2_full.append(int(full_ward[i]))
    ari_v1 = adjusted_rand(v1_labels, v2_full) if len(v1_labels) >= 10 else None

    comp_norm = normalize(components)
    comp_list = comp_norm if isinstance(comp_norm, list) else comp_norm.get("components", comp_norm)
    stab_norm = normalize(stability)

    report = {
        "schema": "aigua-cluster-stability-report/1",
        "featureNames": [name for name, _ in FEATURES],
        "eventCounts": {"analysed": len(events), "included": n, "excluded": len(events) - n},
        "runCounts": {
            "total": len(label_runs),
            "bootstrap": args.bootstraps,
            "kSweep": 7, "kmeans": 10, "hdbscan": 1,
            "leaveOneFeatureOut": len(FEATURES),
        },
        "randomSeed": RANDOM_SEED,
        "threshold": args.threshold,
        "consensusComponents": comp_list,
        "itemStability": stab_norm,
        "v1Comparison": {
            "matchedEvents": len(v1_labels),
            "adjustedRandIndex_fullWardK7_vs_v1": ari_v1,
        },
        "runKinds": sorted(set(run_kinds)),
    }
    args.out.write_text(json.dumps(report, indent=1, default=float), "utf-8")

    store = ResearchObjectStore(args.store)
    input_ref = store.put_json(payload, role="cluster-stability-input")
    out_ref = store.put_json(json.loads(args.out.read_text("utf-8")), role="cluster-stability-result")
    receipt = RunReceipt.identified(
        run_type="cluster-stability-ensemble",
        profile=ProfileRef("aigua.cluster-stability-ensemble", "1"),
        status=RunStatus.SUCCEEDED,
        producer="aigua.cluster_stability_v2/1",
        started_at=started,
        completed_at=utc_now(),
        inputs=(input_ref,),
        outputs=(out_ref,),
        operators=(
            OperatorRef("sklearn.agglomerative-ward", "1.5"),
            OperatorRef("sklearn.kmeans", "1.5"),
            OperatorRef("sklearn.hdbscan", "1.5"),
            OperatorRef("mus.cluster-coassignment", "1"),
        ),
        parameters={
            "bootstraps": args.bootstraps, "k": args.k,
            "threshold": args.threshold, "randomSeed": RANDOM_SEED,
            "features": [name for name, _ in FEATURES],
        },
        environment={},
    )
    store.write_run(receipt)
    store.write_manifest()
    n_comp = len(comp_list) if isinstance(comp_list, list) else None
    print(json.dumps({
        "runId": receipt.run_id,
        "includedEvents": n,
        "labelRuns": len(label_runs),
        "consensusComponents": n_comp,
        "ariVsV1": ari_v1,
        "report": str(args.out),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
