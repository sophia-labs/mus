from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from jsonschema import Draft202012Validator

from mus_analysis.decomposition import Region, event_soft_mask_decomposition
from mus_analysis.psychoacoustic_controls import PsychoacousticControls, apply_controls
from mus_analysis.psychoacoustics import analyze_signal
from mus_analysis.spatial_render import RenderReceipt
from mus_analysis.spatial_scene import SpatialObject, make_scene


ROOT = Path(__file__).resolve().parents[1]


def schema(name: str) -> dict:
    value = json.loads((ROOT / "schemas" / name).read_text())
    Draft202012Validator.check_schema(value)
    return value


def test_generated_contracts_validate() -> None:
    sr = 16000
    t = np.arange(sr) / sr
    y = .1 * np.sin(2 * np.pi * 600 * t)
    report = analyze_signal(y, sr, include_standardized=True).to_dict()
    Draft202012Validator(schema("psychoacoustic-report.schema.json")).validate(report)

    _, manipulation = apply_controls(
        y,
        sr,
        PsychoacousticControls(
            brightness_db=3.0,
            roughness_depth=0.2,
            fluctuation_depth=0.1,
            attack_seconds=0.02,
        ),
    )
    Draft202012Validator(schema("psychoacoustic-manipulation.schema.json")).validate(
        manipulation.to_dict()
    )

    obj = SpatialObject("one", "one", "one.wav", duration_seconds=1)
    scene = make_scene("scene", sr, 1, [obj]).to_dict()
    Draft202012Validator(schema("spatial-scene.schema.json")).validate(scene)

    decomposition = event_soft_mask_decomposition(y, sr, [Region("one", .1, .9)], n_fft=512, hop_length=64)
    Draft202012Validator(schema("decomposition-report.schema.json")).validate(
        decomposition.report_dict(stem_files={decomposition.stems[0].stem_id: "one.wav"}, residual_file="residual.wav")
    )

    receipt = RenderReceipt(
        scene_id="scene", target="stereo", sample_rate=sr, channels=2, duration_seconds=1,
        peak_before_safety=.1, safety_gain_db=0, output_peak=.1, channel_order=("left", "right"),
        renderer="test", object_receipts=(), metadata={}
    ).to_dict()
    Draft202012Validator(schema("spatial-render-receipt.schema.json")).validate(receipt)
