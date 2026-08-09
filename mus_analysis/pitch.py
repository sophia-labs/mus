"""Cross-estimator pitch consensus with explicit refusal states."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from statistics import median
from typing import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class PitchSample:
    time_seconds: float
    frequency_hz: float | None
    score: float | None = None
    score_semantics: str | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.time_seconds) or self.time_seconds < 0:
            raise ValueError("pitch sample time must be finite and non-negative")
        if self.frequency_hz is not None and (
            not math.isfinite(self.frequency_hz) or self.frequency_hz <= 0
        ):
            raise ValueError("frequency_hz must be positive and finite when present")
        if self.score is not None and not math.isfinite(self.score):
            raise ValueError("pitch score must be finite")
        if self.score is not None and not self.score_semantics:
            raise ValueError("score_semantics is required when a score is present")


@dataclass(frozen=True, slots=True)
class PitchTrajectory:
    estimator_id: str
    samples: tuple[PitchSample, ...]

    def __post_init__(self) -> None:
        if not self.estimator_id:
            raise ValueError("estimator_id is required")
        times = [sample.time_seconds for sample in self.samples]
        if times != sorted(times) or len(times) != len(set(times)):
            raise ValueError("pitch trajectory samples must have unique, increasing times")


class ConsensusStatus(str, Enum):
    RESOLVED = "resolved"
    OCTAVE_CONFLICT = "octave-conflict"
    DISAGREEMENT = "disagreement"
    INSUFFICIENT_SUPPORT = "insufficient-support"


@dataclass(frozen=True, slots=True)
class ConsensusPitchFrame:
    time_seconds: float
    status: ConsensusStatus
    frequency_hz: float | None
    octave_equivalent_frequency_hz: float | None
    estimator_frequencies_hz: tuple[tuple[str, float], ...]
    spread_cents: float | None
    octave_folded_spread_cents: float | None


@dataclass(frozen=True, slots=True)
class PitchConsensusSummary:
    resolved_fraction: float
    resolved_frame_count: int
    total_frame_count: int
    median_frequency_hz: float | None
    min_frequency_hz: float | None
    max_frequency_hz: float | None
    span_semitones: float | None
    octave_conflict_count: int
    disagreement_count: int


@dataclass(frozen=True, slots=True)
class PitchConsensus:
    frames: tuple[ConsensusPitchFrame, ...]
    summary: PitchConsensusSummary


def frequency_to_cents(frequency_hz: float) -> float:
    return 1200.0 * math.log2(frequency_hz)


def cents_to_frequency(cents: float) -> float:
    return 2.0 ** (cents / 1200.0)


def build_pitch_consensus(
    trajectories: Sequence[PitchTrajectory],
    *,
    minimum_estimators: int = 2,
    maximum_spread_cents: float = 80.0,
    maximum_time_delta_seconds: float = 0.006,
) -> PitchConsensus:
    if minimum_estimators < 1:
        raise ValueError("minimum_estimators must be positive")
    if maximum_spread_cents <= 0 or maximum_time_delta_seconds < 0:
        raise ValueError("consensus tolerances must be non-negative")
    times = sorted({sample.time_seconds for trajectory in trajectories for sample in trajectory.samples})
    frames: list[ConsensusPitchFrame] = []
    for time in times:
        values: list[tuple[str, float]] = []
        for trajectory in trajectories:
            sample = _nearest_sample(trajectory.samples, time, maximum_time_delta_seconds)
            if sample is not None and sample.frequency_hz is not None:
                values.append((trajectory.estimator_id, sample.frequency_hz))
        frames.append(
            _consensus_frame(
                time,
                values,
                minimum_estimators=minimum_estimators,
                maximum_spread_cents=maximum_spread_cents,
            )
        )
    resolved = [frame.frequency_hz for frame in frames if frame.status is ConsensusStatus.RESOLVED]
    resolved_values = [value for value in resolved if value is not None]
    if resolved_values:
        minimum = min(resolved_values)
        maximum = max(resolved_values)
        summary = PitchConsensusSummary(
            resolved_fraction=len(resolved_values) / max(1, len(frames)),
            resolved_frame_count=len(resolved_values),
            total_frame_count=len(frames),
            median_frequency_hz=float(median(resolved_values)),
            min_frequency_hz=minimum,
            max_frequency_hz=maximum,
            span_semitones=12.0 * math.log2(maximum / minimum),
            octave_conflict_count=sum(frame.status is ConsensusStatus.OCTAVE_CONFLICT for frame in frames),
            disagreement_count=sum(frame.status is ConsensusStatus.DISAGREEMENT for frame in frames),
        )
    else:
        summary = PitchConsensusSummary(
            resolved_fraction=0.0,
            resolved_frame_count=0,
            total_frame_count=len(frames),
            median_frequency_hz=None,
            min_frequency_hz=None,
            max_frequency_hz=None,
            span_semitones=None,
            octave_conflict_count=sum(frame.status is ConsensusStatus.OCTAVE_CONFLICT for frame in frames),
            disagreement_count=sum(frame.status is ConsensusStatus.DISAGREEMENT for frame in frames),
        )
    return PitchConsensus(tuple(frames), summary)


def _nearest_sample(
    samples: Sequence[PitchSample], time: float, maximum_delta: float
) -> PitchSample | None:
    if not samples:
        return None
    candidate = min(samples, key=lambda sample: abs(sample.time_seconds - time))
    return candidate if abs(candidate.time_seconds - time) <= maximum_delta else None


def _consensus_frame(
    time: float,
    values: Sequence[tuple[str, float]],
    *,
    minimum_estimators: int,
    maximum_spread_cents: float,
) -> ConsensusPitchFrame:
    ordered = tuple(sorted(values))
    if len(ordered) < minimum_estimators:
        return ConsensusPitchFrame(
            time,
            ConsensusStatus.INSUFFICIENT_SUPPORT,
            None,
            None,
            ordered,
            None,
            None,
        )
    cents = [frequency_to_cents(value) for _, value in ordered]
    spread = max(cents) - min(cents)
    raw_median = float(median(cents))
    if spread <= maximum_spread_cents:
        return ConsensusPitchFrame(
            time,
            ConsensusStatus.RESOLVED,
            cents_to_frequency(raw_median),
            None,
            ordered,
            spread,
            spread,
        )

    # Try each estimate as an octave anchor and retain the alignment with the
    # smallest folded spread.  Using the raw median directly is ambiguous for
    # an exact 1-octave pair because Python's round-to-even leaves both values
    # on opposite sides of the midpoint.  This remains diagnostic only: an
    # octave conflict is not silently resolved into a pitch.
    folded_candidates = []
    for anchor in cents:
        candidate = [value - 1200.0 * round((value - anchor) / 1200.0) for value in cents]
        folded_candidates.append(candidate)
    folded = min(
        folded_candidates,
        key=lambda candidate: (max(candidate) - min(candidate), abs(median(candidate) - raw_median)),
    )
    folded_spread = max(folded) - min(folded)
    folded_median = float(median(folded))
    if folded_spread <= maximum_spread_cents:
        return ConsensusPitchFrame(
            time,
            ConsensusStatus.OCTAVE_CONFLICT,
            None,
            cents_to_frequency(folded_median),
            ordered,
            spread,
            folded_spread,
        )
    return ConsensusPitchFrame(
        time,
        ConsensusStatus.DISAGREEMENT,
        None,
        None,
        ordered,
        spread,
        folded_spread,
    )
