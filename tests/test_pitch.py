import unittest

from mus_analysis.pitch import (
    ConsensusStatus,
    PitchSample,
    PitchTrajectory,
    build_pitch_consensus,
)


class PitchConsensusTests(unittest.TestCase):
    def test_resolves_close_estimators(self) -> None:
        result = build_pitch_consensus(
            [
                PitchTrajectory("a", (PitchSample(0.0, 1000.0), PitchSample(0.01, 1100.0))),
                PitchTrajectory("b", (PitchSample(0.0, 1005.0), PitchSample(0.01, 1095.0))),
            ],
            maximum_spread_cents=20,
        )
        self.assertTrue(all(frame.status is ConsensusStatus.RESOLVED for frame in result.frames))
        self.assertEqual(result.summary.resolved_frame_count, 2)
        self.assertGreater(result.summary.span_semitones or 0, 1)

    def test_octave_conflict_is_not_silently_resolved(self) -> None:
        result = build_pitch_consensus(
            [
                PitchTrajectory("a", (PitchSample(0.0, 1000.0),)),
                PitchTrajectory("b", (PitchSample(0.0, 2000.0),)),
            ],
            maximum_spread_cents=30,
        )
        frame = result.frames[0]
        self.assertIs(frame.status, ConsensusStatus.OCTAVE_CONFLICT)
        self.assertIsNone(frame.frequency_hz)
        self.assertIsNotNone(frame.octave_equivalent_frequency_hz)

    def test_non_octave_disagreement_refuses(self) -> None:
        result = build_pitch_consensus(
            [
                PitchTrajectory("a", (PitchSample(0.0, 1000.0),)),
                PitchTrajectory("b", (PitchSample(0.0, 1300.0),)),
            ],
            maximum_spread_cents=30,
        )
        self.assertIs(result.frames[0].status, ConsensusStatus.DISAGREEMENT)
        self.assertEqual(result.summary.resolved_fraction, 0.0)


if __name__ == "__main__":
    unittest.main()
