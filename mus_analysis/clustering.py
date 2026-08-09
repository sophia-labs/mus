"""Representation-agnostic cluster stability summaries."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from typing import Hashable, Mapping, Sequence

Label = Hashable


@dataclass(frozen=True, slots=True)
class CoassignmentResult:
    item_ids: tuple[str, ...]
    matrix: tuple[tuple[float | None, ...], ...]
    comparable_run_counts: tuple[tuple[int, ...], ...]


@dataclass(frozen=True, slots=True)
class ItemStability:
    item_id: str
    mean_pairwise_coassignment: float | None
    strongest_neighbor_id: str | None
    strongest_neighbor_probability: float | None


def coassignment_matrix(
    label_runs: Sequence[Mapping[str, Label]],
    *,
    noise_labels: frozenset[Label] = frozenset({-1, None}),
) -> CoassignmentResult:
    """Estimate pairwise co-assignment across bootstrap/model runs.

    A pair is comparable in a run only when both items are present and neither
    carries a declared noise label.  Missing/noise memberships do not become
    false evidence that two items belong apart.
    """
    items = tuple(sorted({item for run in label_runs for item in run}))
    matrix: list[list[float | None]] = []
    counts_matrix: list[list[int]] = []
    for left in items:
        row: list[float | None] = []
        count_row: list[int] = []
        for right in items:
            comparable = 0
            together = 0
            for run in label_runs:
                if left not in run or right not in run:
                    continue
                l, r = run[left], run[right]
                if l in noise_labels or r in noise_labels:
                    continue
                comparable += 1
                together += int(l == r)
            row.append(together / comparable if comparable else None)
            count_row.append(comparable)
        matrix.append(row)
        counts_matrix.append(count_row)
    return CoassignmentResult(
        items,
        tuple(tuple(row) for row in matrix),
        tuple(tuple(row) for row in counts_matrix),
    )


def item_stability(result: CoassignmentResult) -> tuple[ItemStability, ...]:
    out: list[ItemStability] = []
    for i, item in enumerate(result.item_ids):
        values = [
            (result.item_ids[j], value)
            for j, value in enumerate(result.matrix[i])
            if j != i and value is not None
        ]
        if not values:
            out.append(ItemStability(item, None, None, None))
            continue
        strongest = max(values, key=lambda pair: (pair[1], pair[0]))
        out.append(
            ItemStability(
                item,
                sum(value for _, value in values) / len(values),
                strongest[0],
                strongest[1],
            )
        )
    return tuple(out)


def variation_of_information(left: Mapping[str, Label], right: Mapping[str, Label]) -> float:
    """Variation of information over items shared by two hard partitions."""
    items = sorted(set(left) & set(right))
    if not items:
        raise ValueError("partitions have no shared items")
    n = len(items)
    left_counts = Counter(left[item] for item in items)
    right_counts = Counter(right[item] for item in items)
    joint_counts = Counter((left[item], right[item]) for item in items)

    def entropy(counts: Counter[Hashable]) -> float:
        return -sum((count / n) * math.log2(count / n) for count in counts.values())

    mutual = 0.0
    for (l, r), count in joint_counts.items():
        p_lr = count / n
        p_l = left_counts[l] / n
        p_r = right_counts[r] / n
        mutual += p_lr * math.log2(p_lr / (p_l * p_r))
    return entropy(left_counts) + entropy(right_counts) - 2.0 * mutual


def consensus_components(result: CoassignmentResult, *, threshold: float = 0.8) -> tuple[tuple[str, ...], ...]:
    if not 0 <= threshold <= 1:
        raise ValueError("threshold must lie in [0, 1]")
    parent = {item: item for item in result.item_ids}

    def find(item: str) -> str:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for i, left in enumerate(result.item_ids):
        for j in range(i + 1, len(result.item_ids)):
            probability = result.matrix[i][j]
            if probability is not None and probability >= threshold:
                union(left, result.item_ids[j])
    groups: dict[str, list[str]] = {}
    for item in result.item_ids:
        groups.setdefault(find(item), []).append(item)
    return tuple(tuple(sorted(group)) for _, group in sorted(groups.items()))
