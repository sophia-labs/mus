"""Segmentation-lattice primitives.

No detector owns the event ontology.  This module compares interval proposals,
records split/merge/containment relations and can produce a *reconciled event
hypothesis* with explicit support.  It never calls that hypothesis ground truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from statistics import median
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class Segment:
    segment_id: str
    run_id: str
    start_seconds: float
    end_seconds: float

    def __post_init__(self) -> None:
        if self.start_seconds < 0 or self.end_seconds <= self.start_seconds:
            raise ValueError("invalid segment interval")

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


class RelationType(str, Enum):
    APPROXIMATELY_CORRESPONDS = "approximately-corresponds-to"
    CONTAINS = "contains"
    CONTAINED_BY = "contained-by"
    OVERLAPS = "overlaps"
    DISJOINT = "disjoint"


@dataclass(frozen=True, slots=True)
class SegmentRelation:
    source_id: str
    target_id: str
    relation: RelationType
    intersection_over_union: float
    boundary_error_seconds: float


@dataclass(frozen=True, slots=True)
class ReconciledEventHypothesis:
    hypothesis_id: str
    start_seconds: float
    end_seconds: float
    supporting_segment_ids: tuple[str, ...]
    supporting_run_ids: tuple[str, ...]
    support_fraction: float
    ambiguous_split_or_merge: bool


def intersection_seconds(a: Segment, b: Segment) -> float:
    return max(0.0, min(a.end_seconds, b.end_seconds) - max(a.start_seconds, b.start_seconds))


def interval_iou(a: Segment, b: Segment) -> float:
    intersection = intersection_seconds(a, b)
    if intersection <= 0:
        return 0.0
    union = a.duration_seconds + b.duration_seconds - intersection
    return intersection / union


def relate(a: Segment, b: Segment, *, boundary_tolerance_seconds: float = 0.02) -> SegmentRelation:
    iou = interval_iou(a, b)
    boundary_error = max(abs(a.start_seconds - b.start_seconds), abs(a.end_seconds - b.end_seconds))
    if boundary_error <= boundary_tolerance_seconds:
        relation = RelationType.APPROXIMATELY_CORRESPONDS
    elif a.start_seconds <= b.start_seconds and a.end_seconds >= b.end_seconds and iou > 0:
        relation = RelationType.CONTAINS
    elif b.start_seconds <= a.start_seconds and b.end_seconds >= a.end_seconds and iou > 0:
        relation = RelationType.CONTAINED_BY
    elif iou > 0:
        relation = RelationType.OVERLAPS
    else:
        relation = RelationType.DISJOINT
    return SegmentRelation(a.segment_id, b.segment_id, relation, iou, boundary_error)


def reconcile_segmentations(
    segmentations: Mapping[str, Sequence[Segment]],
    *,
    minimum_link_iou: float = 0.15,
    boundary_tolerance_seconds: float = 0.02,
) -> tuple[tuple[ReconciledEventHypothesis, ...], tuple[SegmentRelation, ...]]:
    """Build overlap components across detector runs.

    Segments from the same run do not directly link one another.  Components
    are connected by cross-run IoU, preserving cases where one detector splits
    what another merges.  The resulting median boundary is a review aid, not a
    canonical event boundary.
    """
    runs = sorted(segmentations)
    all_segments = [segment for run in runs for segment in segmentations[run]]
    by_id = {segment.segment_id: segment for segment in all_segments}
    if len(by_id) != len(all_segments):
        raise ValueError("segment ids must be globally unique")
    parent = {segment.segment_id: segment.segment_id for segment in all_segments}

    def find(item: str) -> str:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    relations: list[SegmentRelation] = []
    for i, run_a in enumerate(runs):
        for run_b in runs[i + 1 :]:
            for a in segmentations[run_a]:
                for b in segmentations[run_b]:
                    relation = relate(a, b, boundary_tolerance_seconds=boundary_tolerance_seconds)
                    if relation.relation is not RelationType.DISJOINT:
                        relations.append(relation)
                    if relation.intersection_over_union >= minimum_link_iou:
                        union(a.segment_id, b.segment_id)

    components: dict[str, list[Segment]] = {}
    for segment in all_segments:
        components.setdefault(find(segment.segment_id), []).append(segment)

    hypotheses: list[ReconciledEventHypothesis] = []
    run_count = max(1, len(runs))
    for root, members in sorted(components.items(), key=lambda item: min(s.start_seconds for s in item[1])):
        member_runs = tuple(sorted({member.run_id for member in members}))
        counts_by_run: dict[str, int] = {}
        for member in members:
            counts_by_run[member.run_id] = counts_by_run.get(member.run_id, 0) + 1
        ambiguous = any(count > 1 for count in counts_by_run.values())
        hypotheses.append(
            ReconciledEventHypothesis(
                hypothesis_id=f"reconciled:{root}",
                start_seconds=float(median(member.start_seconds for member in members)),
                end_seconds=float(median(member.end_seconds for member in members)),
                supporting_segment_ids=tuple(sorted(member.segment_id for member in members)),
                supporting_run_ids=member_runs,
                support_fraction=len(member_runs) / run_count,
                ambiguous_split_or_merge=ambiguous,
            )
        )
    return tuple(hypotheses), tuple(sorted(relations, key=lambda r: (r.source_id, r.target_id)))
