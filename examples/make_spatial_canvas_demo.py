#!/usr/bin/env python3
"""Generate a self-contained MUS psychoacoustic spatial-canvas demo."""
from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import sys

# Permit direct execution from a source checkout before editable installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from scipy import signal as scipy_signal
import soundfile as sf

from mus_analysis.psychoacoustics import analyze_signal
from mus_analysis.spatial_render import render_to_file
from mus_analysis.spatial_scene import Position, Room, make_scene, object_from_analysis


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--output-dir", type=Path, default=Path("examples/generated-spatial-canvas"))
    result.add_argument("--sample-rate", type=int, default=24000)
    result.add_argument("--render", action="store_true", help="also render deterministic stereo")
    return result


def main() -> int:
    args = parser().parse_args()
    root = args.output_dir
    audio_dir = root / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    sr = int(args.sample_rate)
    duration = 4.0
    t = np.arange(int(sr * duration), dtype=float) / sr

    glide_phase = 2 * np.pi * (650 * t + 0.5 * (3100 - 650) / duration * t**2)
    glide_env = np.sin(np.pi * np.clip(t / duration, 0, 1)) ** 1.4
    glide = .17 * np.sin(glide_phase) * glide_env

    rough_carrier = np.sin(2 * np.pi * 1250 * t) + .38 * np.sin(2 * np.pi * 2500 * t)
    rough_mod = 1 - .58 * .5 * (1 + np.sin(2 * np.pi * 70 * t))
    rough_env = np.exp(-2.4 * t) * (1 - np.exp(-55 * t))
    rough = .12 * rough_carrier * rough_mod * rough_env

    rng = np.random.default_rng(11)
    white = rng.standard_normal(t.size)
    sos = scipy_signal.butter(3, [80 / (sr / 2), min(.95, 4200 / (sr / 2))], btype="band", output="sos")
    wind = scipy_signal.sosfilt(sos, white)
    wind /= max(np.max(np.abs(wind)), 1e-12)
    slow = .42 + .34 * (1 + np.sin(2 * np.pi * .35 * t + .4)) / 2
    wind = .08 * wind * slow

    rows = [
        ("glide", "tonal glide", glide, "point", Position.spherical(-42, 36, 5.5), .08),
        ("rough", "rough call", rough, "point", Position.spherical(52, 8, 4.0), .12),
        ("wind", "diffuse wind texture", wind, "ambient", Position.spherical(145, -8, 11), .72),
    ]
    objects = []
    for index, (object_id, label, audio, kind, position, spread) in enumerate(rows):
        path = audio_dir / f"{object_id}.wav"
        sf.write(path, audio, sr, subtype="FLOAT")
        report = analyze_signal(audio, sr, source_id=f"urn:sophia:mus:demo:{object_id}", include_standardized=True).to_dict()
        obj = object_from_analysis(
            object_id=f"urn:sophia:mus:demo:{object_id}",
            label=label,
            audio=path.relative_to(root).as_posix(),
            start_seconds=0,
            duration_seconds=duration,
            analysis=report,
            kind=kind,
            family=object_id,
            index=index,
            count=len(rows),
        )
        objects.append(replace(obj, position=position, spread=max(spread, obj.spread), reverb_send=.1 + .1 * index))

    scene = make_scene(
        "MUS psychoacoustic spatial demo",
        sr,
        duration,
        objects,
        metadata={
            "constructionMode": "generated-demonstration",
            "purpose": "Exercise HRTF placement, per-object psychoacoustic analysis, intervention reanalysis, and variation materialization.",
        },
    )
    scene = replace(scene, room=Room(wet=.18, decay_seconds=1.7, damping=.5, seed=31))
    scene_path = scene.write(root / "scene.json")
    print(scene_path)
    print(f"mus-spatial serve {scene_path} --editable")
    if args.render:
        render_to_file(scene_path, root / "demo-stereo.wav", target="stereo")
        print(root / "demo-stereo.wav")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
