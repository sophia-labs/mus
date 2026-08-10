#!/usr/bin/env python3
"""Golden vectors for the Rust scene renderer (PW7).

Oracle: mus_analysis.spatial_render.{render_stereo, render_foa} — the
offline half of the shared Web Audio/offline scene contract. Same
discipline as gen_dsp_fixtures.py: outputs dumped verbatim, manifest
owns metric+tolerance, tests never re-derive the oracle.

Run:  .venv/bin/python mus-rs/tools/gen_scene_fixtures.py
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mus_analysis.spatial_scene import (  # noqa: E402
    Listener, Position, PositionKeyframe, Room, SpatialObject, SpatialScene,
)
from mus_analysis import spatial_render  # noqa: E402

OUT = ROOT / "mus-rs" / "fixtures" / "scene"
STEMS = OUT / "stems"
STEMS.mkdir(parents=True, exist_ok=True)
SR = 48_000
manifest = []


def stem(name, y):
    sf.write(STEMS / name, y.astype(np.float32), SR)
    return f"stems/{name}"


t = np.arange(int(0.8 * SR)) / SR
sine = stem("sine220.wav", 0.5 * np.sin(2 * np.pi * 220 * t) * np.minimum(t / 0.01, 1) * np.minimum((0.8 - t) / 0.05, 1))
tb = np.arange(int(0.4 * SR)) / SR
burst = stem("burst.wav", 0.6 * np.sin(2 * np.pi * (900 + 2200 * tb) * tb) * np.exp(-6 * tb))
rng = np.random.default_rng(23)
noise = stem("noise.wav", (0.25 * rng.standard_normal(int(0.5 * SR))).astype(np.float32))


def case(name, scene, foa=False):
    (OUT / f"{name}.scene.json").write_text(json.dumps(scene.to_dict(), indent=1))
    mix, receipt = spatial_render.render_stereo(scene, OUT)
    planar = np.ascontiguousarray(mix.T, dtype=np.float32)
    (OUT / f"{name}.stereo.bin").write_bytes(planar.tobytes())
    entry = {
        "name": name, "scene": f"{name}.scene.json",
        "stereo": f"{name}.stereo.bin", "channels": 2,
        "frames": int(planar.shape[1]), "layout": "planar-f32le",
        "metric": "max_abs", "tol": 2e-5,
        "safetyGainDb": receipt.safety_gain_db,
        "renderer": receipt.renderer,
    }
    if foa:
        w, r = spatial_render.render_foa(scene, OUT)
        pf = np.ascontiguousarray(w.T, dtype=np.float32)
        (OUT / f"{name}.foa.bin").write_bytes(pf.tobytes())
        entry["foa"] = f"{name}.foa.bin"
        entry["foaChannels"] = int(pf.shape[0])
        entry["foaRenderer"] = r.renderer
    manifest.append(entry)
    print(f"  {name}: {planar.shape[1]} frames" + (" +foa" if foa else ""))


case("static_room", SpatialScene(
    scene_id="fx-static", title="static trio with seeded room",
    sample_rate=SR, duration_seconds=2.0,
    objects=(
        SpatialObject(object_id="a", label="left sine", audio=sine,
                      position=Position.spherical(-50, 0, 1.4),
                      gain_db=-2.0, reverb_send=0.5),
        SpatialObject(object_id="b", label="right burst", audio=burst,
                      start_seconds=0.35,
                      position=Position.spherical(65, 10, 2.2),
                      reverb_send=0.3),
        SpatialObject(object_id="c", label="behind noise", audio=noise,
                      start_seconds=0.9,
                      position=Position.spherical(170, -5, 3.0),
                      gain_db=-6.0, reverb_send=0.8),
    ),
    room=Room(enabled=True, decay_seconds=1.1, wet=0.22, damping=0.5, seed=17),
), foa=True)

case("orbit", SpatialScene(
    scene_id="fx-orbit", title="one object orbiting, room off",
    sample_rate=SR, duration_seconds=1.6,
    objects=(
        SpatialObject(object_id="o", label="orbiter", audio=sine,
                      position=Position.spherical(-90, 0, 1.5),
                      trajectory=tuple(
                          PositionKeyframe(time_seconds=ts,
                                           position=Position.spherical(-90 + 360 * ts / 1.5, 0, 1.5))
                          for ts in (0.0, 0.375, 0.75, 1.125, 1.5)
                      ),
                      reverb_send=0.0),
    ),
    room=Room(enabled=False),
))

case("spread_duo", SpatialScene(
    scene_id="fx-spread", title="spread pair, listener honored",
    sample_rate=SR, duration_seconds=1.4,
    objects=(
        SpatialObject(object_id="w", label="wide", audio=noise,
                      position=Position.spherical(0, 0, 1.0),
                      spread=0.8, reverb_send=0.1),
        SpatialObject(object_id="n", label="narrow near", audio=burst,
                      start_seconds=0.2,
                      position=Position.spherical(25, 0, 0.6),
                      spread=0.0, reverb_send=0.2),
    ),
    room=Room(enabled=True, decay_seconds=0.8, wet=0.15, damping=0.4, seed=17),
))

(OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
print(f"{len(manifest)} scenes -> {OUT}/manifest.json")
