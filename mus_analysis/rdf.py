"""Deterministic RDF projection for MUS analysis records.

Dense arrays remain content-addressed artifacts.  RDF carries identity,
provenance, method, evidence kind, relationships and compact results.
"""
from __future__ import annotations

from dataclasses import is_dataclass
import json
import math
from typing import Any, Iterable

from .canonical import canonical_text, normalize
from .model import (
    ArtifactRef,
    Claim,
    EventHypothesis,
    Interpretation,
    MembershipEstimate,
    Observation,
    ResearchProjection,
    RunReceipt,
)

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
XSD = "http://www.w3.org/2001/XMLSchema#"
PROV = "http://www.w3.org/ns/prov#"
SOSA = "http://www.w3.org/ns/sosa/"
MUSA = "https://sophia-labs.ai/ontology/mus-audio#"


class Graph:
    def __init__(self) -> None:
        self._triples: set[tuple[str, str, str]] = set()

    def iri(self, subject: str, predicate: str, obj: str) -> None:
        self._triples.add((_iri(subject), _iri(predicate), _iri(obj)))

    def literal(self, subject: str, predicate: str, value: Any, datatype: str | None = None) -> None:
        self._triples.add((_iri(subject), _iri(predicate), _literal(value, datatype)))

    def type(self, subject: str, class_iri: str) -> None:
        self.iri(subject, RDF + "type", class_iri)

    def ntriples(self) -> str:
        return "".join(f"{s} {p} {o} .\n" for s, p, o in sorted(self._triples))


def projection_to_ntriples(projection: ResearchProjection) -> str:
    graph = Graph()
    graph.type(projection.projection_id, MUSA + "ResearchProjection")
    graph.literal(projection.projection_id, MUSA + "schema", projection.schema)
    for artifact in projection.assets:
        _artifact(graph, artifact)
        graph.iri(projection.projection_id, MUSA + "hasArtifact", artifact.uri)
    for run in projection.runs:
        _run(graph, run)
        graph.iri(projection.projection_id, MUSA + "hasRun", run.run_id)
    for event in projection.events:
        _event(graph, event)
        graph.iri(projection.projection_id, MUSA + "hasEventHypothesis", event.event_id)
    for observation in projection.observations:
        _observation(graph, observation)
        graph.iri(projection.projection_id, MUSA + "hasObservation", observation.observation_id)
    for membership in projection.memberships:
        _membership(graph, membership)
        graph.iri(projection.projection_id, MUSA + "hasMembershipEstimate", membership.membership_id)
    for interpretation in projection.interpretations:
        _interpretation(graph, interpretation)
        graph.iri(projection.projection_id, MUSA + "hasInterpretation", interpretation.interpretation_id)
    for claim in projection.claims:
        _claim(graph, claim)
        graph.iri(projection.projection_id, MUSA + "hasClaim", claim.claim_id)
    if projection.metadata:
        graph.literal(projection.projection_id, MUSA + "metadataJson", projection.metadata, RDF + "JSON")
    return graph.ntriples()


def _artifact(graph: Graph, value: ArtifactRef) -> None:
    graph.type(value.uri, MUSA + "Artifact")
    graph.literal(value.uri, MUSA + "sha256", value.sha256)
    graph.literal(value.uri, MUSA + "mediaType", value.media_type)
    graph.literal(value.uri, MUSA + "byteLength", value.byte_length, XSD + "integer")
    if value.role:
        graph.literal(value.uri, MUSA + "artifactRole", value.role)


def _run(graph: Graph, value: RunReceipt) -> None:
    graph.type(value.run_id, PROV + "Activity")
    graph.type(value.run_id, MUSA + "AnalysisRun")
    graph.literal(value.run_id, MUSA + "runType", value.run_type)
    graph.literal(value.run_id, MUSA + "runStatus", value.status.value)
    graph.literal(value.run_id, PROV + "startedAtTime", value.started_at, XSD + "dateTime")
    graph.literal(value.run_id, PROV + "endedAtTime", value.completed_at, XSD + "dateTime")
    graph.literal(value.run_id, MUSA + "profileId", value.profile.profile_id)
    graph.literal(value.run_id, MUSA + "profileVersion", value.profile.version)
    graph.literal(value.run_id, MUSA + "producer", value.producer)
    for artifact in value.inputs:
        _artifact(graph, artifact)
        graph.iri(value.run_id, PROV + "used", artifact.uri)
    for artifact in value.outputs:
        _artifact(graph, artifact)
        graph.iri(artifact.uri, PROV + "wasGeneratedBy", value.run_id)
    for operator in value.operators:
        operator_iri = f"urn:sophia:mus:operator:{_token(operator.operator_id)}:{_token(operator.version)}"
        graph.type(operator_iri, MUSA + "OperatorBinding")
        graph.literal(operator_iri, MUSA + "operatorId", operator.operator_id)
        graph.literal(operator_iri, MUSA + "operatorVersion", operator.version)
        if operator.implementation_digest:
            graph.literal(operator_iri, MUSA + "implementationDigest", operator.implementation_digest)
        graph.iri(value.run_id, MUSA + "usedOperator", operator_iri)
    if value.parameters:
        graph.literal(value.run_id, MUSA + "parametersJson", value.parameters, RDF + "JSON")
    if value.environment:
        graph.literal(value.run_id, MUSA + "environmentJson", value.environment, RDF + "JSON")


def _event(graph: Graph, value: EventHypothesis) -> None:
    graph.type(value.event_id, MUSA + "EventHypothesis")
    graph.iri(value.event_id, PROV + "wasGeneratedBy", value.segmentation_run_id)
    graph.iri(value.event_id, MUSA + "evidenceKind", MUSA + _evidence_local(value.evidence_kind.value))
    graph.iri(value.event_id, MUSA + "targetsAsset", value.region.asset_uri)
    graph.literal(value.event_id, MUSA + "startSeconds", value.region.start_seconds, XSD + "double")
    graph.literal(value.event_id, MUSA + "endSeconds", value.region.end_seconds, XSD + "double")
    graph.literal(value.event_id, MUSA + "revision", value.revision, XSD + "integer")
    graph.literal(value.event_id, MUSA + "hypothesisStatus", value.status)
    for label in value.labels:
        graph.literal(value.event_id, MUSA + "provisionalLabel", label)
    if value.metadata:
        graph.literal(value.event_id, MUSA + "metadataJson", value.metadata, RDF + "JSON")


def _observation(graph: Graph, value: Observation) -> None:
    graph.type(value.observation_id, SOSA + "Observation")
    graph.type(value.observation_id, MUSA + "Observation")
    graph.iri(value.observation_id, SOSA + "hasFeatureOfInterest", value.target_id)
    graph.iri(value.observation_id, PROV + "wasGeneratedBy", value.run_id)
    graph.iri(value.observation_id, MUSA + "evidenceKind", MUSA + _evidence_local(value.evidence_kind.value))
    graph.literal(value.observation_id, MUSA + "observedPropertyId", value.observed_property)
    graph.literal(value.observation_id, MUSA + "procedureId", value.procedure.operator_id)
    graph.literal(value.observation_id, MUSA + "procedureVersion", value.procedure.version)
    _result_literal(graph, value.observation_id, value.value, value.unit)
    if value.score:
        graph.literal(value.observation_id, MUSA + "scoreValue", value.score.value, XSD + "double")
        graph.literal(value.observation_id, MUSA + "scoreSemantics", value.score.semantics)
        if value.score.unit:
            graph.literal(value.observation_id, MUSA + "scoreUnit", value.score.unit)
    if value.signal_view_uri:
        graph.iri(value.observation_id, MUSA + "computedOnSignalView", value.signal_view_uri)
    graph.literal(value.observation_id, MUSA + "validity", value.validity)
    if value.metadata:
        graph.literal(value.observation_id, MUSA + "metadataJson", value.metadata, RDF + "JSON")


def _membership(graph: Graph, value: MembershipEstimate) -> None:
    graph.type(value.membership_id, MUSA + "MembershipEstimate")
    graph.iri(value.membership_id, MUSA + "forTarget", value.target_id)
    graph.iri(value.membership_id, MUSA + "forClusterModel", value.cluster_model_id)
    graph.iri(value.membership_id, MUSA + "memberOfModelCluster", value.cluster_id)
    graph.iri(value.membership_id, PROV + "wasGeneratedBy", value.run_id)
    graph.iri(value.membership_id, MUSA + "evidenceKind", MUSA + _evidence_local(value.evidence_kind.value))
    if value.score:
        graph.literal(value.membership_id, MUSA + "scoreValue", value.score.value, XSD + "double")
        graph.literal(value.membership_id, MUSA + "scoreSemantics", value.score.semantics)
    if value.metadata:
        graph.literal(value.membership_id, MUSA + "metadataJson", value.metadata, RDF + "JSON")


def _interpretation(graph: Graph, value: Interpretation) -> None:
    graph.type(value.interpretation_id, MUSA + "Interpretation")
    graph.iri(value.interpretation_id, MUSA + "forTarget", value.target_id)
    graph.literal(value.interpretation_id, MUSA + "interpretivePredicate", value.predicate)
    graph.literal(value.interpretation_id, MUSA + "interpretiveValueJson", value.value, RDF + "JSON")
    graph.iri(value.interpretation_id, MUSA + "evidenceKind", MUSA + _evidence_local(value.evidence_kind.value))
    graph.literal(value.interpretation_id, PROV + "wasAttributedTo", value.attributed_to)
    graph.iri(value.interpretation_id, PROV + "wasGeneratedBy", value.activity_id)
    for support in value.supports:
        graph.iri(value.interpretation_id, MUSA + "supportedBy", support)


def _claim(graph: Graph, value: Claim) -> None:
    graph.type(value.claim_id, MUSA + "Claim")
    graph.literal(value.claim_id, MUSA + "claimText", value.text)
    graph.literal(value.claim_id, MUSA + "claimStatus", value.status.value)
    graph.iri(value.claim_id, MUSA + "evidenceKind", MUSA + _evidence_local(value.evidence_kind.value))
    graph.literal(value.claim_id, PROV + "wasAttributedTo", value.attributed_to)
    if value.scope:
        graph.literal(value.claim_id, MUSA + "claimScope", value.scope)
    for support in value.supports:
        graph.iri(value.claim_id, MUSA + "supportedBy", support)
    for contradiction in value.contradicts:
        graph.iri(value.claim_id, MUSA + "contradictedBy", contradiction)
    for assumption in value.assumptions:
        graph.literal(value.claim_id, MUSA + "dependsOnAssumption", assumption)
    if value.metadata:
        graph.literal(value.claim_id, MUSA + "metadataJson", value.metadata, RDF + "JSON")


def _result_literal(graph: Graph, subject: str, value: Any, unit: str | None) -> None:
    if isinstance(value, bool):
        graph.literal(subject, SOSA + "hasSimpleResult", value, XSD + "boolean")
    elif isinstance(value, int):
        graph.literal(subject, SOSA + "hasSimpleResult", value, XSD + "integer")
    elif isinstance(value, float) and math.isfinite(value):
        graph.literal(subject, SOSA + "hasSimpleResult", value, XSD + "double")
    elif isinstance(value, str):
        graph.literal(subject, SOSA + "hasSimpleResult", value)
    else:
        graph.literal(subject, MUSA + "resultJson", value, RDF + "JSON")
    if unit:
        graph.literal(subject, MUSA + "unitId", unit)


def _iri(value: str) -> str:
    if not value or any(ch in value for ch in "<>\"{}|\\^`") or any(ch.isspace() for ch in value):
        raise ValueError(f"invalid IRI for compact MUS projector: {value!r}")
    return f"<{value}>"


def _literal(value: Any, datatype: str | None) -> str:
    if datatype == RDF + "JSON":
        text = canonical_text(value)
    elif isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
    escaped = json.dumps(text, ensure_ascii=False)
    return f"{escaped}^^<{datatype}>" if datatype else escaped


def _token(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in value)


def _evidence_local(value: str) -> str:
    return "EvidenceKind-" + "".join(part.capitalize() for part in value.split("-"))
