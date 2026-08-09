from __future__ import annotations

import math

import numpy as np

from mus_analysis.psychoacoustics import CalibrationSpec, analyze_signal, metric_map


def tone(frequency: float, *, sample_rate: int = 24000, seconds: float = 1.0) -> np.ndarray:
    t = np.arange(int(sample_rate * seconds)) / sample_rate
    return 0.1 * np.sin(2 * np.pi * frequency * t)


def test_relative_analysis_refuses_pressure_metrics_without_fabricating_pascals() -> None:
    report = analyze_signal(tone(1000), 24000, calibration=CalibrationSpec(), include_standardized=True)
    rows = {row.metric_id: row for row in report.metrics}
    assert rows["psychoacoustic.loudness-zwicker"].status == "refused"
    assert rows["psychoacoustic.sharpness-din"].status == "refused"
    assert rows["psychoacoustic.roughness-daniel-weber"].status == "refused"
    assert any(item["code"] == "MUSP-CALIBRATION-REQUIRED" for item in report.diagnostics)


def test_spectral_analysis_orders_low_and_high_tones() -> None:
    low = metric_map(analyze_signal(tone(300), 24000, include_standardized=False))
    high = metric_map(analyze_signal(tone(5000), 24000, include_standardized=False))
    assert high["spectrum.centroid-hz"] > low["spectrum.centroid-hz"] * 5
    assert math.isfinite(high["auditory.relative-sharpness"])


def test_report_contains_distinct_programme_and_psychoacoustic_semantics() -> None:
    report = analyze_signal(tone(1000, seconds=2), 24000, include_standardized=True)
    rows = {row.metric_id: row for row in report.metrics}
    assert rows["programme.integrated-loudness"].unit == "LUFS"
    assert rows["programme.integrated-loudness"].construct == "ProgrammeLoudness"
    assert rows["psychoacoustic.loudness-zwicker"].construct == "PsychoacousticLoudness"
    assert rows["spectrum.centroid-hz"].construct == "PhysicalSpectralDistribution"


def test_calibrated_standardized_adapter_has_typed_units(monkeypatch) -> None:
    import sys
    import types

    sq_metrics = types.ModuleType("mosqito.sq_metrics")
    sq_metrics.loudness_zwtv = lambda signal, fs, field_type="free": (
        np.asarray([1.0, 2.0]), np.ones((4, 2)), np.asarray([1, 2, 3, 4]), np.asarray([0.0, 0.1])
    )
    sq_metrics.sharpness_din_tv = lambda signal, fs, weighting="din", field_type="free": (
        np.asarray([.8, 1.2]), np.asarray([0.0, 0.1])
    )
    sq_metrics.roughness_dw = lambda signal, fs: (
        np.asarray([.1, .2]), np.ones((4, 2)), np.asarray([1, 2, 3, 4]), np.asarray([0.0, 0.1])
    )
    sq_metrics.loudness_ecma = lambda signal, fs: (
        2.5, np.asarray([1.8, 2.5]), np.ones((4, 2)), np.asarray([1, 2, 3, 4]), np.asarray([[0.0, 0.1]] * 4)
    )
    sq_metrics.roughness_ecma = lambda signal, fs: (
        .35, np.asarray([.2, .35]), np.ones((4, 2)), np.asarray([1, 2, 3, 4]), np.asarray([0.0, 0.1])
    )
    sq_metrics.pr_ecma_st = lambda signal, fs, prominence=True: (
        np.asarray([12.0]), np.asarray([10.0, 8.0]), np.asarray([True, True]), np.asarray([1000.0, 3000.0])
    )
    sq_metrics.tnr_ecma_st = lambda signal, fs, prominence=True: (
        np.asarray([14.0]), np.asarray([13.0]), np.asarray([True]), np.asarray([1000.0])
    )
    mosqito = types.ModuleType("mosqito")
    mosqito.sq_metrics = sq_metrics
    monkeypatch.setitem(sys.modules, "mosqito", mosqito)
    monkeypatch.setitem(sys.modules, "mosqito.sq_metrics", sq_metrics)

    report = analyze_signal(
        tone(1000), 24000,
        calibration=CalibrationSpec(kind="pascal-per-digital-unit", pascal_per_digital_unit=.2),
        include_standardized=True,
    )
    rows = {row.metric_id: row for row in report.metrics}
    assert rows["psychoacoustic.loudness-zwicker"].status == "available"
    assert rows["psychoacoustic.loudness-zwicker"].unit == "sone"
    assert rows["psychoacoustic.sharpness-din"].unit == "acum"
    assert rows["psychoacoustic.roughness-daniel-weber"].unit == "asper"
    assert rows["psychoacoustic.loudness-ecma-hms"].value == 2.5
    assert rows["psychoacoustic.roughness-ecma-hms"].value == .35
    assert rows["tonality.prominence-ratio-ecma"].value == 12.0
    assert rows["tonality.tone-to-noise-ratio-ecma"].value == 14.0


def test_load_mono_falls_back_to_ffmpeg_for_aac_m4a(tmp_path):
    import shutil
    import subprocess
    import soundfile as sf
    from mus_analysis.psychoacoustics import load_mono

    if shutil.which("ffmpeg") is None:
        import pytest
        pytest.skip("ffmpeg unavailable")
    sr = 16000
    t = np.arange(sr, dtype=float) / sr
    wav = tmp_path / "source.wav"
    m4a = tmp_path / "source.m4a"
    sf.write(wav, .1 * np.sin(2 * np.pi * 440 * t), sr, subtype="PCM_16")
    process = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(wav), "-c:a", "aac", "-b:a", "64k", str(m4a)],
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        import pytest
        pytest.skip("ffmpeg AAC encoder unavailable")
    y, decoded_sr = load_mono(m4a, sample_rate=12000)
    assert decoded_sr == 12000
    assert len(y) > 10000
    assert np.max(np.abs(y)) > .01
