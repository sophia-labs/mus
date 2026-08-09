from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from mus_analysis.spatial_cli import build_scene_from_audio
from mus_analysis.spatial_scene import SpatialScene


def test_whole_scene_builder_creates_analyzed_canvas(tmp_path: Path) -> None:
    sr = 16000
    t = np.arange(sr) / sr
    source = tmp_path / "source.wav"
    sf.write(source, .1 * np.sin(2 * np.pi * 800 * t), sr, subtype="FLOAT")
    scene_path = build_scene_from_audio(source, tmp_path / "canvas", mode="whole", include_standardized=True)
    scene = SpatialScene.read(scene_path)
    assert len(scene.objects) == 1
    assert scene.objects[0].analysis["metrics"]
    assert (scene_path.parent / scene.objects[0].audio).is_file()


def test_new_command_creates_empty_editable_canvas(tmp_path: Path, capsys) -> None:
    from mus_analysis.spatial_cli import main

    output = tmp_path / "blank"
    assert main(["new", "--output-dir", str(output), "--title", "blank canvas", "--sample-rate", "16000"]) == 0
    scene = SpatialScene.read(output / "scene.json")
    assert scene.title == "blank canvas"
    assert scene.objects == ()
    assert scene.metadata["constructionMode"] == "empty-canvas"
    assert "mus-spatial serve" in capsys.readouterr().out
