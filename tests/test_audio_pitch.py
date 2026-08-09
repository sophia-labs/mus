import math
import unittest

import numpy as np

from mus_analysis.audio_pitch import (
    PitchExtractionConfig,
    dominant_ridge_trajectory,
    extract_reference_ensemble,
    shs_trajectory,
)
from mus_analysis.pitch import ConsensusStatus, build_pitch_consensus


class AudioPitchOperatorTests(unittest.TestCase):
    @staticmethod
    def harmonic_chirp(sr: int = 16000, duration: float = 0.6) -> np.ndarray:
        t = np.arange(int(sr * duration)) / sr
        f0 = 900.0 + 300.0 * t / duration
        phase = 2 * np.pi * np.cumsum(f0) / sr
        envelope = np.sin(np.pi * np.clip(t / duration, 0, 1)) ** 2
        return envelope * (
            np.sin(phase) + 0.45 * np.sin(2 * phase) + 0.2 * np.sin(3 * phase)
        )

    def test_reference_shs_follows_harmonic_chirp(self) -> None:
        sr = 16000
        y = self.harmonic_chirp(sr)
        cfg = PitchExtractionConfig(
            sample_rate=sr,
            n_fft=1024,
            hop_length=128,
            fmin_hz=700,
            fmax_hz=1500,
            energy_gate_fraction=0.1,
        )
        trajectory = shs_trajectory(y, sr, cfg, score_threshold=2.0)
        voiced = [sample.frequency_hz for sample in trajectory.samples if sample.frequency_hz is not None]
        self.assertGreater(len(voiced), 20)
        self.assertGreater(voiced[-1], voiced[0])
        self.assertTrue(800 < np.median(voiced) < 1300)

    def test_ridge_is_explicitly_independent(self) -> None:
        sr = 16000
        y = self.harmonic_chirp(sr)
        cfg = PitchExtractionConfig(
            sample_rate=sr,
            n_fft=1024,
            hop_length=128,
            fmin_hz=700,
            fmax_hz=3000,
            energy_gate_fraction=0.1,
        )
        ridge = dominant_ridge_trajectory(y, sr, cfg, score_threshold=3.0)
        self.assertEqual(ridge.estimator_id, "aigua.dominant-spectral-ridge/1")
        self.assertTrue(any(sample.frequency_hz for sample in ridge.samples))

    def test_ensemble_and_consensus_preserve_refusals(self) -> None:
        sr = 16000
        y = self.harmonic_chirp(sr)
        cfg = PitchExtractionConfig(
            sample_rate=sr,
            n_fft=1024,
            hop_length=128,
            fmin_hz=700,
            fmax_hz=1500,
            energy_gate_fraction=0.1,
        )
        trajectories = extract_reference_ensemble(y, sr, cfg)
        consensus = build_pitch_consensus(
            trajectories,
            minimum_estimators=2,
            maximum_spread_cents=120,
            maximum_time_delta_seconds=0.001,
        )
        self.assertGreater(consensus.summary.resolved_frame_count, 5)
        self.assertTrue(
            any(frame.status in {ConsensusStatus.RESOLVED, ConsensusStatus.INSUFFICIENT_SUPPORT} for frame in consensus.frames)
        )


if __name__ == "__main__":
    unittest.main()
