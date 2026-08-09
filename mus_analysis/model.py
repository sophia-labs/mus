"""Typed records for reproducible MUS audio analysis.

The model intentionally distinguishes direct/computed observations, uncertain
estimates, model memberships, human annotations, curation, perceptual reports,
and compositional interpretation.  They may point at the same sound region but
must never be collapsed into one untyped property bag.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Mapping, Sequence

from .canonical import CANONICALIZATION_ID, content_urn

SCHEMA_BASE = "https://sophia-labs.ai/schemas/mus-analysis"


class EvidenceKind(str, Enum):
    DIRECTLY_MEASURED = "directly-measured"
    DETERMINISTICALLY_COMPUTED = "deterministically-computed"
    STATISTICALLY_ESTIMATED = "statistically-estimated"
    MODEL_INFERRED = "model-inferred"
    HUMAN_ANNOTATED = "human-annotated"
    HUMAN_CURATED = "human-curated"
    PERCEPTUALLY_REPORTED = "perceptually-reported"
    COMPOSITIONAL_INTERPRETATION = "compositional-interpretation"
    UNRESOLVED = "unresolved"


class RunStatus(str, Enum):
    SUCCEEDED = "succeeded"
    REFUSED = "refused"
    FAILED = "failed"


class ClaimStatus(str, Enum):
    PROPOSED = "proposed"
    SUPPORTED = "supported"
    CONTESTED = "contested"
    REFUTED = "refuted"
    UNRESOLVED = "unresolved"
    ADOPTED_FOR_COMPOSITION = "adopted-for-composition"


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    uri: str
    sha256: str
    media_type: str
    byte_length: int
    role: str | None = None

    def __post_init__(self) -> None:
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256):
            raise ValueError("artifact sha256 must be a lowercase 64-character digest")
        if self.byte_length < 0:
            raise ValueError("artifact byte_length must be non-negative")
        if not self.media_type:
            raise ValueError("artifact media_type is required")


@dataclass(frozen=True, slots=True)
class MediaRegion:
    asset_uri: str
    start_seconds: float
    end_seconds: float
    channel: str | None = None

    def __post_init__(self) -> None:
        for name, value in (("start_seconds", self.start_seconds), ("end_seconds", self.end_seconds)):
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.start_seconds < 0:
            raise ValueError("start_seconds must be non-negative")
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be greater than start_seconds")

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


@dataclass(frozen=True, slots=True)
class OperatorRef:
    operator_id: str
    version: str
    implementation_digest: str | None = None
    source_url: str | None = None

    def __post_init__(self) -> None:
        if not self.operator_id or not self.version:
            raise ValueError("operator_id and version are required")


@dataclass(frozen=True, slots=True)
class ProfileRef:
    profile_id: str
    version: str
    digest: str | None = None


@dataclass(frozen=True, slots=True)
class Score:
    """A typed score emitted by an estimator or model.

    `semantics` is mandatory: values named merely ``confidence`` are forbidden
    because peak ratios, posterior probabilities, similarities and bootstrap
    frequencies are not interchangeable.
    """

    value: float
    semantics: str
    unit: str | None = None

    def __post_init__(self) -> None:
        if not self.semantics:
            raise ValueError("score semantics are required")
        if not math.isfinite(self.value):
            raise ValueError("score value must be finite")


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    message: str
    severity: str = "error"
    anchor: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RunReceipt:
    run_id: str
    run_type: str
    profile: ProfileRef
    status: RunStatus
    producer: str
    started_at: str
    completed_at: str
    inputs: tuple[ArtifactRef, ...] = ()
    outputs: tuple[ArtifactRef, ...] = ()
    operators: tuple[OperatorRef, ...] = ()
    parameters: Mapping[str, Any] = field(default_factory=dict)
    environment: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: tuple[Diagnostic, ...] = ()
    canonicalization: str = CANONICALIZATION_ID
    schema: str = f"{SCHEMA_BASE}/run-receipt/1"

    @classmethod
    def identified(cls, **kwargs: Any) -> "RunReceipt":
        seed = dict(kwargs)
        seed.pop("run_id", None)
        run_id = content_urn("run", seed)
        return cls(run_id=run_id, **seed)


@dataclass(frozen=True, slots=True)
class EventHypothesis:
    event_id: str
    region: MediaRegion
    segmentation_run_id: str
    evidence_kind: EvidenceKind = EvidenceKind.STATISTICALLY_ESTIMATED
    revision: int = 1
    labels: tuple[str, ...] = ()
    status: str = "proposed"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def identified(
        cls,
        *,
        region: MediaRegion,
        segmentation_run_id: str,
        revision: int = 1,
        **kwargs: Any,
    ) -> "EventHypothesis":
        identity = {
            "region": region,
            "segmentation_run_id": segmentation_run_id,
            "revision": revision,
        }
        return cls(
            event_id=content_urn("event-hypothesis", identity),
            region=region,
            segmentation_run_id=segmentation_run_id,
            revision=revision,
            **kwargs,
        )


@dataclass(frozen=True, slots=True)
class Observation:
    observation_id: str
    target_id: str
    observed_property: str
    evidence_kind: EvidenceKind
    procedure: OperatorRef
    run_id: str
    value: Any
    unit: str | None = None
    score: Score | None = None
    signal_view_uri: str | None = None
    validity: str = "valid"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def identified(cls, **kwargs: Any) -> "Observation":
        seed = dict(kwargs)
        seed.pop("observation_id", None)
        return cls(observation_id=content_urn("observation", seed), **seed)


@dataclass(frozen=True, slots=True)
class MembershipEstimate:
    membership_id: str
    target_id: str
    cluster_model_id: str
    cluster_id: str
    run_id: str
    evidence_kind: EvidenceKind = EvidenceKind.MODEL_INFERRED
    score: Score | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def identified(cls, **kwargs: Any) -> "MembershipEstimate":
        seed = dict(kwargs)
        seed.pop("membership_id", None)
        return cls(membership_id=content_urn("membership", seed), **seed)


@dataclass(frozen=True, slots=True)
class Interpretation:
    interpretation_id: str
    target_id: str
    predicate: str
    value: Any
    evidence_kind: EvidenceKind
    attributed_to: str
    activity_id: str
    supports: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def identified(cls, **kwargs: Any) -> "Interpretation":
        seed = dict(kwargs)
        seed.pop("interpretation_id", None)
        return cls(interpretation_id=content_urn("interpretation", seed), **seed)


@dataclass(frozen=True, slots=True)
class Claim:
    claim_id: str
    text: str
    status: ClaimStatus
    attributed_to: str
    evidence_kind: EvidenceKind
    supports: tuple[str, ...] = ()
    contradicts: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    scope: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def identified(cls, **kwargs: Any) -> "Claim":
        seed = dict(kwargs)
        seed.pop("claim_id", None)
        return cls(claim_id=content_urn("claim", seed), **seed)


@dataclass(frozen=True, slots=True)
class ResearchProjection:
    projection_id: str
    assets: tuple[ArtifactRef, ...] = ()
    runs: tuple[RunReceipt, ...] = ()
    events: tuple[EventHypothesis, ...] = ()
    observations: tuple[Observation, ...] = ()
    memberships: tuple[MembershipEstimate, ...] = ()
    interpretations: tuple[Interpretation, ...] = ()
    claims: tuple[Claim, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema: str = f"{SCHEMA_BASE}/research-projection/1"

    @classmethod
    def identified(cls, **kwargs: Any) -> "ResearchProjection":
        seed = dict(kwargs)
        seed.pop("projection_id", None)
        return cls(projection_id=content_urn("research-projection", seed), **seed)
