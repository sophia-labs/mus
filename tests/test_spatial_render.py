from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from mus_analysis.spatial_render import render_foa, render_stereo
from mus_analysis.spatial_scene import Position, Room, SpatialObject, SpatialScene, make_scene


def scene_with_tone(tmp_path: Path, position: Position) -> SpatialScene:
    sr = 16000
    t = np.arange(sr) / sr
    y = .1 * np.sin(2 * np.pi * 440 * t)
    sf.write(tmp_path / "tone.wav", y, sr, subtype="FLOAT")
    obj = SpatialObject("tone", "tone", "tone.wav", position=position, duration_seconds=1.0)
    base = make_scene("render", sr, 1, [obj])
    return SpatialScene(base.scene_id, base.title, base.sample_rate, base.duration_seconds, base.objects, room=Room(enabled=False))


def test_right_position_has_more_right_channel_energy(tmp_path: Path) -> None:
    scene = scene_with_tone(tmp_path, Position.spherical(70, 0, 2))
    audio, receipt = render_stereo(scene, tmp_path)
    rms = np.sqrt(np.mean(audio**2, axis=0))
    assert rms[1] > rms[0] * 2
    assert receipt.channel_order == ("left", "right")


def test_foa_is_w_y_z_x_acn_sn3d(tmp_path: Path) -> None:
    scene = scene_with_tone(tmp_path, Position.spherical(45, 0, 2))
    audio, receipt = render_foa(scene, tmp_path)
    assert audio.shape[1] == 4
    assert receipt.channel_order == ("W", "Y", "Z", "X")
    # Horizontal right-front source: positive correlated Y and X; no elevation Z.
    assert np.corrcoef(audio[:, 0], audio[:, 1])[0, 1] > .99
    assert np.corrcoef(audio[:, 0], audio[:, 3])[0, 1] > .99
    assert np.max(np.abs(audio[:, 2])) < 1e-12


def test_offline_renderer_honors_listener_yaw(tmp_path: Path) -> None:
    from dataclasses import replace
    from mus_analysis.spatial_scene import Listener

    scene = scene_with_tone(tmp_path, Position(2, 0, 0))
    # The source is world-right, but directly in front of a listener facing right.
    scene = replace(scene, listener=Listener(forward=Position(1, 0, 0), up=Position(0, 1, 0)))
    audio, receipt = render_stereo(scene, tmp_path)
    rms = np.sqrt(np.mean(audio**2, axis=0))
    assert np.isclose(rms[0], rms[1], rtol=.03)
    assert receipt.metadata["listenerPoseHonored"] is True
