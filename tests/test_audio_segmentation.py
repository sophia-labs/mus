import unittest

import numpy as np

from mus_analysis.audio_segmentation import (
    SegmentationConfig,
    aigua_hysteresis_segmentation,
    pcen_segmentation,
)
from mus_analysis.segmentation import reconcile_segmentations


class AudioSegmentationTests(unittest.TestCase):
    @staticmethod
    def synthetic_scene(sr: int = 16000) -> np.ndarray:
        rng = np.random.default_rng(7)
        duration = 2.0
        y = 0.003 * rng.standard_normal(int(sr * duration))
        for start, end, f0, f1 in [(0.35, 0.60, 1200, 1800), (1.15, 1.45, 1700, 1000)]:
            i0, i1 = int(start * sr), int(end * sr)
            t = np.arange(i1 - i0) / sr
            frequency = f0 + (f1 - f0) * t / max(t[-1], 1e-9)
            phase = 2 * np.pi * np.cumsum(frequency) / sr
            env = np.sin(np.pi * np.arange(len(t)) / max(1, len(t) - 1)) ** 2
            y[i0:i1] += 0.35 * env * (np.sin(phase) + 0.25 * np.sin(2 * phase))
        return y

    def test_parallel_detectors_and_lattice(self) -> None:
        sr = 16000
        y = self.synthetic_scene(sr)
        config = SegmentationConfig(
            sample_rate=sr,
            n_fft=512,
            hop_length=64,
            band_low_hz=700,
            band_high_hz=3500,
            noise_block_seconds=0.5,
            minimum_duration_seconds=0.04,
            merge_gap_seconds=0.03,
            maximum_duration_seconds=0.8,
        )
        historical = aigua_hysteresis_segmentation(y, sr, config)
        pcen = pcen_segmentation(y, sr, config, mel_bins=32)
        self.assertGreaterEqual(len(historical.segments), 2)
        self.assertGreaterEqual(len(pcen.segments), 2)
        hypotheses, relations = reconcile_segmentations(
            {historical.run_id: historical.segments, pcen.run_id: pcen.segments},
            minimum_link_iou=0.15,
        )
        self.assertTrue(hypotheses)
        self.assertTrue(any(h.support_fraction == 1.0 for h in hypotheses))
        self.assertTrue(relations)


if __name__ == "__main__":
    unittest.main()
