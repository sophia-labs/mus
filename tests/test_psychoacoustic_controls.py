from __future__ import annotations

import numpy as np
from scipy import signal

from mus_analysis.psychoacoustic_controls import PsychoacousticControls, apply_controls


def band_energy(y: np.ndarray, sr: int, low: float, high: float) -> float:
    f, p = signal.welch(y, sr, nperseg=min(4096, len(y)))
    mask = (f >= low) & (f < high)
    return float(np.trapezoid(p[mask], f[mask]))


def test_brightness_shelf_increases_high_to_low_ratio() -> None:
    sr = 24000
    rng = np.random.default_rng(4)
    y = rng.standard_normal(sr) * 0.03
    result, receipt = apply_controls(y, sr, PsychoacousticControls(brightness_db=10, brightness_hz=2500))
    before = band_energy(y, sr, 4000, 9000) / band_energy(y, sr, 200, 1200)
    after = band_energy(result, sr, 4000, 9000) / band_energy(result, sr, 200, 1200)
    assert after > before * 3
    assert receipt.operations[0]["targetCue"] == "brightness/sharpness"


def test_modulation_and_attack_are_explicit_operations() -> None:
    sr = 24000
    y = np.ones(sr, dtype=float) * 0.1
    result, receipt = apply_controls(
        y,
        sr,
        PsychoacousticControls(
            roughness_depth=0.4,
            roughness_rate_hz=70,
            fluctuation_depth=0.2,
            fluctuation_rate_hz=4,
            attack_seconds=0.1,
        ),
    )
    assert abs(result[0]) < 1e-12
    assert np.std(result[int(.2 * sr):]) > 0.02
    targets = {row["targetCue"] for row in receipt.operations}
    assert {"attack-time/impulsiveness", "psychoacoustic-roughness", "fluctuation-strength/pulsation"} <= targets


def test_safety_is_linear_and_reported() -> None:
    y = np.ones(1000)
    result, receipt = apply_controls(y, 24000, PsychoacousticControls(gain_db=12, safety_peak=.5))
    assert np.max(np.abs(result)) <= .5000001
    assert receipt.safety_gain_db < 0
    assert receipt.operations[-1]["operator"] == "mus.safety-peak-scale/1"
