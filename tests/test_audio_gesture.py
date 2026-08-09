import tempfile
import unittest

import numpy as np

from mus_analysis.audio_gesture import analyze_gesture, persist_gesture_bundle
from mus_analysis.audio_pitch import PitchExtractionConfig
from mus_analysis.store import ResearchObjectStore


class GestureAnalysisTests(unittest.TestCase):
    def test_continuous_bundle_reports_fm_and_am(self) -> None:
        sr = 16000
        duration = 0.8
        t = np.arange(int(sr * duration)) / sr
        frequency = 900 + 500 * t / duration
        phase = 2 * np.pi * np.cumsum(frequency) / sr
        am = 0.55 + 0.35 * np.sin(2 * np.pi * 30 * t)
        outer = np.sin(np.pi * t / duration) ** 2
        y = outer * am * (np.sin(phase) + 0.35 * np.sin(2 * phase))
        config = PitchExtractionConfig(
            sample_rate=sr,
            n_fft=1024,
            hop_length=128,
            fmin_hz=700,
            fmax_hz=1800,
            energy_gate_fraction=0.1,
        )
        bundle = analyze_gesture(y, sr, config, maximum_pitch_spread_cents=130)
        self.assertEqual(bundle.schema, "mus-gesture-observation-bundle/1")
        self.assertGreater(bundle.summary.resolved_pitch_fraction, 0.2)
        self.assertGreater(bundle.summary.pitch_span_semitones or 0, 3)
        self.assertGreater(bundle.summary.max_absolute_fm_velocity_semitones_per_second or 0, 1)
        rate = bundle.summary.amplitude_modulation.dominant_rate_hz
        self.assertIsNotNone(rate)
        self.assertLess(abs((rate or 0) - 30), 5)
        self.assertGreater(bundle.summary.amplitude_modulation.robust_modulation_index or 0, 0.2)
        property_ids = {trajectory.property_id for trajectory in bundle.trajectories}
        self.assertIn("consensusPitchHz", property_ids)
        self.assertIn("spectralCentroidHz", property_ids)

        with tempfile.TemporaryDirectory() as tmp:
            store = ResearchObjectStore(tmp)
            persisted = persist_gesture_bundle(store, bundle)
            self.assertEqual(persisted.manifest.media_type, "application/json")
            self.assertEqual(len(persisted.arrays), 2 * len(bundle.trajectories))
            self.assertTrue(store.verify()["ok"])


if __name__ == "__main__":
    unittest.main()
