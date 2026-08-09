"""Import the historical Aigua branch as an immutable, semantically separated fossil.

The importer does not rerun DSP. It preserves the existing tables and manifest,
then projects their contents into explicit segmentation hypotheses, observations,
model memberships, human curation, and claims.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .aigua_v1_curate import historical_claims, instrument_interpretations
from .aigua_v1_spec import (
    AIGUA_PROJECT_ID,
    AIGUA_SOURCE_FALLBACK,
    AIGUA_V1_TIME,
    CLAIM_RUN_ID,
    CLUSTER_MODEL_ID,
    CLUSTER_RUN_ID,
    CURATION_RUN_ID,
    DEFAULT_CONFIG,
    OBSERVATION_RUN_ID,
    SEGMENTATION_RUN_ID,
    _PROPERTY_MAP,
)
from .model import (
    ArtifactRef,
    EventHypothesis,
    MediaRegion,
    MembershipEstimate,
    Observation,
    OperatorRef,
    ProfileRef,
    ResearchProjection,
    RunReceipt,
    RunStatus,
    Score,
)
from .rdf import projection_to_ntriples
from .store import ResearchObjectStore

def import_aigua_v1(
    project_root: str | Path,
    store_root: str | Path,
    *,
    config: Mapping[str, Any] | None = None,
) -> ResearchProjection:
    project = Path(project_root)
    merged_config = {**DEFAULT_CONFIG, **dict(config or {})}
    store = ResearchObjectStore(store_root)

    events_path = project / str(merged_config["eventsPath"])
    instrument_path = project / str(merged_config["instrumentPath"])
    if not events_path.is_file():
        raise FileNotFoundError(events_path)
    if not instrument_path.is_file():
        raise FileNotFoundError(instrument_path)

    events_raw = json.loads(events_path.read_text("utf-8"))
    instrument_raw = json.loads(instrument_path.read_text("utf-8"))
    if not isinstance(events_raw, list):
        raise ValueError("Aigua v1 events.json must contain a list")
    if not isinstance(instrument_raw, dict):
        raise ValueError("Aigua v1 instrument.json must contain an object")

    source_path = _first_existing(project, merged_config.get("sourceCandidates", []))
    assets: list[ArtifactRef] = []
    source_ref: ArtifactRef | None = None
    if source_path is not None:
        source_ref = store.put_file(source_path, role="aigua-source-recording")
        assets.append(source_ref)
    source_uri = source_ref.uri if source_ref else AIGUA_SOURCE_FALLBACK

    events_ref = store.put_file(events_path, media_type="application/json", role="aigua-v1-events-table")
    instrument_ref = store.put_file(
        instrument_path, media_type="application/json", role="aigua-v1-instrument-manifest"
    )
    assets.extend((events_ref, instrument_ref))
    events_csv_path = project / str(merged_config.get("eventsCsvPath", ""))
    if events_csv_path.is_file():
        assets.append(store.put_file(events_csv_path, media_type="text/csv", role="aigua-v1-events-csv"))

    vehicle_ids = {int(item) for item in merged_config.get("vehicleEventIds", [])}
    events: list[EventHypothesis] = []
    observations: list[Observation] = []
    memberships: list[MembershipEstimate] = []
    event_by_legacy_id: dict[int, EventHypothesis] = {}

    for row in events_raw:
        if not isinstance(row, dict):
            raise ValueError("every event row must be an object")
        legacy_id = int(row["id"])
        region = MediaRegion(source_uri, float(row["t0"]), float(row["t1"]))
        labels = ("vehicle-dominated",) if legacy_id in vehicle_ids else ()
        event = EventHypothesis.identified(
            region=region,
            segmentation_run_id=SEGMENTATION_RUN_ID,
            labels=labels,
            metadata={
                "legacyEventId": legacy_id,
                "historicalTable": events_ref.uri,
                "vehicleReviewStatus": "human-annotated" if legacy_id in vehicle_ids else "not-reviewed",
            },
        )
        events.append(event)
        event_by_legacy_id[legacy_id] = event
        for field, descriptor in _PROPERTY_MAP.items():
            if field not in row:
                continue
            value = row[field]
            score = None
            score_field = descriptor.get("scoreField")
            if score_field and score_field in row:
                score = Score(float(row[score_field]), "aigua-shs-peak-to-mean-score", "ratio")
            metadata: dict[str, Any] = {"legacyField": field}
            if descriptor.get("legacyMisnomer"):
                metadata["legacyMisnomer"] = descriptor["legacyMisnomer"]
            observation = Observation.identified(
                target_id=event.event_id,
                observed_property=str(descriptor["property"]),
                evidence_kind=descriptor["evidence"],
                procedure=OperatorRef(str(descriptor["operator"]), str(descriptor["version"])),
                run_id=OBSERVATION_RUN_ID,
                value=value,
                unit=descriptor.get("unit"),
                score=score,
                signal_view_uri=descriptor.get("view"),
                metadata=metadata,
            )
            observations.append(observation)
        if "cluster" in row:
            cluster = int(row["cluster"])
            memberships.append(
                MembershipEstimate.identified(
                    target_id=event.event_id,
                    cluster_model_id=CLUSTER_MODEL_ID,
                    cluster_id=f"{CLUSTER_MODEL_ID}:cluster:{cluster}",
                    run_id=CLUSTER_RUN_ID,
                    metadata={
                        "legacyCluster": cluster,
                        "forcedAssignment": True,
                        "requestedClusterCount": 7,
                    },
                )
            )

    interpretations = instrument_interpretations(instrument_raw, event_by_legacy_id, instrument_ref)
    claims = historical_claims(source_uri, events, observations, memberships, source_ref is not None)

    events_collection = store.put_json(
        {"schema": "aigua-v1-event-hypotheses/1", "events": events}, role="event-hypotheses"
    )
    observations_collection = store.put_json(
        {"schema": "aigua-v1-observations/1", "observations": observations}, role="observations"
    )
    memberships_collection = store.put_json(
        {"schema": "aigua-v1-cluster-memberships/1", "memberships": memberships},
        role="cluster-memberships",
    )
    interpretations_collection = store.put_json(
        {"schema": "aigua-v1-interpretations/1", "interpretations": interpretations},
        role="interpretations",
    )
    claims_collection = store.put_json(
        {"schema": "aigua-v1-claim-register/1", "claims": claims}, role="claim-register"
    )
    assets.extend(
        (
            events_collection,
            observations_collection,
            memberships_collection,
            interpretations_collection,
            claims_collection,
        )
    )

    runs = (
        _historical_run(
            SEGMENTATION_RUN_ID,
            "segmentation",
            "aigua.segmentation-v1",
            (events_ref,),
            (events_collection,),
            (
                OperatorRef("aigua.band-separate", "1"),
                OperatorRef("aigua.spectral-gate", "1"),
                OperatorRef("aigua.hysteresis-segment", "1"),
            ),
            merged_config,
        ),
        _historical_run(
            OBSERVATION_RUN_ID,
            "event-observation",
            "aigua.event-observations-v1",
            (events_ref,),
            (observations_collection,),
            tuple(
                sorted(
                    {
                        OperatorRef(str(item["operator"]), str(item["version"]))
                        for item in _PROPERTY_MAP.values()
                    },
                    key=lambda item: (item.operator_id, item.version),
                )
            ),
            merged_config,
        ),
        _historical_run(
            CLUSTER_RUN_ID,
            "clustering",
            "aigua.ward-k7-v1",
            (events_ref,),
            (memberships_collection,),
            (OperatorRef("sklearn.cluster.AgglomerativeClustering", "historical"),),
            {"k": 7, "linkage": "ward", "weights": {"scalar": 1.0, "contour": 0.55, "mel": 0.45}},
        ),
        _historical_run(
            CURATION_RUN_ID,
            "instrument-curation",
            "aigua.instrument-curation-v1",
            (events_ref, instrument_ref),
            (interpretations_collection,),
            (OperatorRef("aigua.build-instrument", "1"),),
            merged_config,
        ),
        _historical_run(
            CLAIM_RUN_ID,
            "claim-register",
            "aigua.claim-register-v1",
            tuple(artifact for artifact in assets if artifact.uri != claims_collection.uri),
            (claims_collection,),
            (OperatorRef("mus-analysis.aigua-v1-import", "1"),),
            merged_config,
        ),
    )
    for run in runs:
        store.write_run(run)

    projection = ResearchProjection.identified(
        assets=tuple(_unique_artifacts(assets)),
        runs=runs,
        events=tuple(events),
        observations=tuple(observations),
        memberships=tuple(memberships),
        interpretations=tuple(interpretations),
        claims=tuple(claims),
        metadata={
            "projectId": AIGUA_PROJECT_ID,
            "sourcePresent": source_ref is not None,
            "historicalBranch": "aigua-concrete",
            "importSemantics": "historical-fossil; no DSP rerun",
            "legacyFieldCorrections": {
                "am_depth": "envelopeAutocorrelationPeakStrength",
                "f0_conf": "shsPeakToMeanScore",
                "cluster": "AcousticClusterMembership, not call type or taxon",
            },
        },
    )
    store.write_projection("aigua-v1", projection)
    nt = projection_to_ntriples(projection)
    store.write_named_bytes("projections/aigua-v1.nt", nt.encode("utf-8"))
    store.write_named_json(
        "profile-registry-snapshot.json",
        {
            "schema": "aigua-analysis-profile-registry/1",
            "profiles": [
                "aigua.segmentation-v1",
                "aigua.event-observations-v1",
                "aigua.ward-k7-v1",
                "aigua.instrument-curation-v1",
                "aigua.claim-register-v1",
            ],
        },
    )
    store.write_manifest()
    store.verify()
    return projection


def _historical_run(
    run_id: str,
    run_type: str,
    profile_id: str,
    inputs: tuple[ArtifactRef, ...],
    outputs: tuple[ArtifactRef, ...],
    operators: tuple[OperatorRef, ...],
    parameters: Mapping[str, Any],
) -> RunReceipt:
    return RunReceipt(
        run_id=run_id,
        run_type=run_type,
        profile=ProfileRef(profile_id, "1"),
        status=RunStatus.SUCCEEDED,
        producer="sophia-labs/mus@aigua-concrete (historically imported)",
        started_at=AIGUA_V1_TIME,
        completed_at=AIGUA_V1_TIME,
        inputs=inputs,
        outputs=outputs,
        operators=operators,
        parameters={
            **dict(parameters),
            "historicalTimestampPrecision": "day-only; exact execution time unavailable",
        },
        environment={
            "historical": True,
            "declaredDependencies": [
                "ffmpeg",
                "numpy",
                "scipy",
                "librosa",
                "soundfile",
                "matplotlib",
                "scikit-learn",
                "music21",
            ],
        },
    )



def _first_existing(root: Path, candidates: Iterable[str]) -> Path | None:
    for candidate in candidates:
        path = root / candidate
        if path.is_file():
            return path
    return None



def _unique_artifacts(values: Iterable[ArtifactRef]) -> list[ArtifactRef]:
    by_digest: dict[str, ArtifactRef] = {}
    for value in values:
        by_digest.setdefault(value.sha256, value)
    return [by_digest[key] for key in sorted(by_digest)]
