"""Human curation and claim projection for the historical Aigua fossil."""
from __future__ import annotations

from typing import Any, Mapping

from .model import (
    ArtifactRef,
    Claim,
    ClaimStatus,
    EvidenceKind,
    EventHypothesis,
    Interpretation,
    MembershipEstimate,
    Observation,
)
from .aigua_v1_spec import (
    AIGUA_CURATOR,
    AIGUA_PROJECT_ID,
    CLUSTER_MODEL_ID,
    CURATION_RUN_ID,
)

def instrument_interpretations(
    instrument: Mapping[str, Any],
    events: Mapping[int, EventHypothesis],
    instrument_ref: ArtifactRef,
) -> list[Interpretation]:
    out: list[Interpretation] = []
    voices = instrument.get("voices", {})
    if not isinstance(voices, dict):
        return out
    for label, voice in voices.items():
        if not isinstance(voice, dict):
            continue
        cluster = voice.get("cluster")
        family_id = AIGUA_PROJECT_ID + f":curatorial-family:{_token(str(label))}"
        out.append(
            Interpretation.identified(
                target_id=family_id,
                predicate="preferredLabel",
                value=str(label),
                evidence_kind=EvidenceKind.HUMAN_CURATED,
                attributed_to=AIGUA_CURATOR,
                activity_id=CURATION_RUN_ID,
                supports=(instrument_ref.uri,),
                metadata={
                    "description": voice.get("family"),
                    "legacyCluster": cluster,
                    "population": voice.get("population"),
                    "notesAtHand": voice.get("notes_at_hand", []),
                },
            )
        )
        samples = voice.get("samples", [])
        if not isinstance(samples, list):
            continue
        for rank, sample in enumerate(samples, start=1):
            if not isinstance(sample, dict) or "event" not in sample:
                continue
            event = events.get(int(sample["event"]))
            if event is None:
                continue
            out.append(
                Interpretation.identified(
                    target_id=event.event_id,
                    predicate="curatedAsFamily",
                    value=family_id,
                    evidence_kind=EvidenceKind.HUMAN_CURATED,
                    attributed_to=AIGUA_CURATOR,
                    activity_id=CURATION_RUN_ID,
                    supports=(instrument_ref.uri,),
                    metadata={
                        "selectionRank": rank,
                        "sampleFile": sample.get("file"),
                        "legacyVoice": label,
                    },
                )
            )
            if sample.get("note") is not None:
                out.append(
                    Interpretation.identified(
                        target_id=event.event_id,
                        predicate="nominalTranspositionAnchor",
                        value={
                            "note": sample.get("note"),
                            "midi": sample.get("midi"),
                            "centsFromA440Grid": sample.get("cents"),
                            "sourceFrequencyHz": sample.get("f0_hz"),
                        },
                        evidence_kind=EvidenceKind.COMPOSITIONAL_INTERPRETATION,
                        attributed_to=AIGUA_CURATOR,
                        activity_id=CURATION_RUN_ID,
                        supports=(instrument_ref.uri,),
                        metadata={"notIntrinsicStablePitch": True},
                    )
                )
    return out


def historical_claims(
    source_uri: str,
    events: list[EventHypothesis],
    observations: list[Observation],
    memberships: list[MembershipEstimate],
    source_present: bool,
) -> list[Claim]:
    span_observations = [
        item for item in observations if item.observed_property == "shsRangeSemitones" and isinstance(item.value, (int, float))
    ]
    cluster_ids = sorted({item.cluster_id for item in memberships})
    claims = [
        Claim.identified(
            text="The encoded source has an estimated effective upper bandwidth near 9 kHz under the historical reconnaissance profile.",
            status=ClaimStatus.SUPPORTED,
            attributed_to=AIGUA_CURATOR,
            evidence_kind=EvidenceKind.DETERMINISTICALLY_COMPUTED,
            supports=(source_uri,),
            assumptions=("historical visual/quantitative reconnaissance was not recomputed by this importer",),
            scope=AIGUA_PROJECT_ID,
        ),
        Claim.identified(
            text="The historical Ward model produced one forced seven-way acoustic partition; this is not evidence of seven taxa or seven natural call kinds.",
            status=ClaimStatus.SUPPORTED,
            attributed_to=AIGUA_CURATOR,
            evidence_kind=EvidenceKind.MODEL_INFERRED,
            supports=tuple(cluster_ids),
            assumptions=("k=7 was chosen by contact-sheet inspection", "every input event received a hard assignment"),
            scope=CLUSTER_MODEL_ID,
        ),
        Claim.identified(
            text="Continuous gesture representation is more faithful than a note-only representation for many Aigua vocalizations.",
            status=ClaimStatus.SUPPORTED,
            attributed_to=AIGUA_CURATOR,
            evidence_kind=EvidenceKind.COMPOSITIONAL_INTERPRETATION,
            supports=tuple(item.observation_id for item in span_observations),
            assumptions=(
                "historical SHS trajectories may contain bound hits or octave errors",
                "exact span distribution requires estimator-ensemble validation",
            ),
            scope=AIGUA_PROJECT_ID,
        ),
        Claim.identified(
            text="Species and individual identities remain unresolved in Aigua v1.",
            status=ClaimStatus.UNRESOLVED,
            attributed_to=AIGUA_CURATOR,
            evidence_kind=EvidenceKind.UNRESOLVED,
            scope=AIGUA_PROJECT_ID,
        ),
        Claim.identified(
            text="Historical mix and transformation-quality judgments were not established by a controlled critical-listening study.",
            status=ClaimStatus.SUPPORTED,
            attributed_to=AIGUA_CURATOR,
            evidence_kind=EvidenceKind.HUMAN_ANNOTATED,
            scope=AIGUA_PROJECT_ID,
        ),
    ]
    if not source_present:
        claims.append(
            Claim.identified(
                text="The source recording was not present at import time; source-dependent artifact verification is incomplete.",
                status=ClaimStatus.UNRESOLVED,
                attributed_to="mus-analysis.aigua-v1-import/1",
                evidence_kind=EvidenceKind.UNRESOLVED,
                scope=AIGUA_PROJECT_ID,
            )
        )
    return claims



def _token(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in value)

