from __future__ import annotations

from pathlib import Path

from mus_analysis.spatial_scene import Position, SpatialObject, SpatialScene, make_scene, object_from_analysis


def analysis(centroid: float, rms: float, roughness: float) -> dict:
    return {
        "metrics": [
            {"metric_id": "spectrum.centroid-hz", "value": centroid},
            {"metric_id": "digital.rms-dbfs", "value": rms},
            {"metric_id": "auditory.roughness-proxy", "value": roughness},
        ]
    }


def test_spherical_coordinate_convention() -> None:
    front = Position.spherical(0, 0, 3)
    right = Position.spherical(90, 0, 3)
    assert abs(front.x) < 1e-8 and front.z < 0
    assert right.x > 2.9 and abs(right.z) < 1e-8


def test_analysis_seeded_layout_is_explicit_and_roundtrips(tmp_path: Path) -> None:
    obj = object_from_analysis(
        object_id="bird-1", label="bright bird", audio="bird.wav", start_seconds=.3,
        duration_seconds=.5, analysis=analysis(5000, -24, .4), family="bright"
    )
    scene = make_scene("test", 24000, 2.0, [obj])
    path = scene.write(tmp_path / "scene.json")
    loaded = SpatialScene.read(path)
    assert loaded.objects[0].metadata["layoutStrategy"] == "psychoacoustic-constellation-v1"
    assert loaded.objects[0].position.y > 0
    assert loaded.to_dict()["objects"][0]["controls"]["brightnessDb"] == 0


def test_scene_rejects_duplicate_ids() -> None:
    obj = SpatialObject("same", "a", "a.wav")
    try:
        make_scene("bad", 24000, 1, [obj, obj])
    except ValueError as exc:
        assert "unique" in str(exc)
    else:
        raise AssertionError("duplicate object ids were accepted")
