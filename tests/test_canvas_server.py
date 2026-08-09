from __future__ import annotations

from http.server import ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
from threading import Thread
from urllib.parse import quote, urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
import soundfile as sf

from mus_analysis.canvas_server import CanvasState, make_handler
from mus_analysis.spatial_scene import SpatialObject, make_scene


def _wav_bytes(signal: np.ndarray, sample_rate: int) -> bytes:
    stream = BytesIO()
    sf.write(stream, signal, sample_rate, format="WAV", subtype="FLOAT")
    return stream.getvalue()


def _start_server(tmp_path: Path) -> tuple[ThreadingHTTPServer, Thread, str, CanvasState]:
    sf.write(tmp_path / "tone.wav", np.zeros(4000), 8000, subtype="FLOAT")
    scene = make_scene("canvas", 8000, .5, [SpatialObject("tone", "tone", "tone.wav", duration_seconds=.5)])
    scene_path = scene.write(tmp_path / "scene.json")
    state = CanvasState(scene_path, scene, editable=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_port}", state


def test_canvas_serves_scene_range_audio_edit_and_static_assets(tmp_path: Path) -> None:
    server, thread, base, _ = _start_server(tmp_path)
    try:
        with urlopen(base + "/api/scene") as response:
            payload = json.load(response)
        assert payload["title"] == "canvas"
        with urlopen(base + "/api/capabilities") as response:
            capabilities = json.load(response)
        assert capabilities["editable"] is True
        assert "hybrid" in capabilities["ingestModes"]

        request = Request(base + "/media/tone", headers={"Range": "bytes=0-31"})
        with urlopen(request) as response:
            assert response.status == 206
            assert len(response.read()) == 32
        payload["title"] = "edited"
        request = Request(
            base + "/api/scene",
            data=json.dumps(payload).encode(),
            method="PUT",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request) as response:
            saved = json.load(response)
        assert Path(saved["saved"]).is_file()
        with urlopen(base + "/app.js") as response:
            javascript = response.read()
        assert b"createPanner" in javascript
        assert b"/api/objects" in javascript
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_canvas_upload_reanalysis_and_delete(tmp_path: Path) -> None:
    server, thread, base, state = _start_server(tmp_path)
    sample_rate = 8000
    time = np.arange(sample_rate, dtype=float) / sample_rate
    signal = 0.2 * np.sin(2 * np.pi * 660 * time)
    try:
        query = urlencode({"filename": "new tone.wav", "mode": "whole", "startSeconds": ".2", "components": "4"})
        request = Request(
            base + f"/api/objects?{query}",
            data=_wav_bytes(signal, sample_rate),
            method="POST",
            headers={"Content-Type": "audio/wav"},
        )
        with urlopen(request) as response:
            assert response.status == 201
            imported = json.load(response)
        assert len(imported["addedObjectIds"]) == 1
        object_id = imported["addedObjectIds"][0]
        obj = next(row for row in imported["scene"]["objects"] if row["objectId"] == object_id)
        assert obj["startSeconds"] == .2
        assert obj["analysis"]["metrics"]
        assert state.save_path.is_file()
        with urlopen(base + f"/media/{quote(object_id, safe='')}") as response:
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("audio/")

        request = Request(
            base + f"/api/analyze/{quote(object_id, safe='')}",
            data=json.dumps({"controls": {"brightnessDb": 6, "brightnessHz": 1500}}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request) as response:
            preview = json.load(response)
        assert preview["objectId"] == object_id
        assert preview["controls"]["brightnessDb"] == 6
        assert preview["report"]["metrics"]
        assert preview["manipulation"]["operations"]

        request = Request(
            base + f"/api/objects/{quote(object_id, safe='')}/derive",
            data=json.dumps({"controls": {"brightnessDb": 6, "roughnessDepth": .1}}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request) as response:
            assert response.status == 201
            derived = json.load(response)
        child_id = derived["addedObjectIds"][0]
        child = next(row for row in derived["scene"]["objects"] if row["objectId"] == child_id)
        assert child["metadata"]["derivedFromObjectId"] == object_id
        assert child["metadata"]["manipulation"]["operations"]
        assert child["controls"]["brightnessDb"] == 0
        assert (tmp_path / child["audio"]).is_file()

        request = Request(base + f"/api/objects/{quote(object_id, safe='')}", method="DELETE")
        with urlopen(request) as response:
            removed = json.load(response)
        assert removed["removed"] == object_id
        assert all(row["objectId"] != object_id for row in removed["scene"]["objects"])
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_canvas_refuses_cross_origin_mutation(tmp_path: Path) -> None:
    server, thread, base, state = _start_server(tmp_path)
    try:
        payload = state.scene.to_dict()
        request = Request(
            base + "/api/scene",
            data=json.dumps(payload).encode(),
            method="PUT",
            headers={
                "Content-Type": "application/json",
                "Origin": "https://untrusted.example",
            },
        )
        try:
            urlopen(request)
        except HTTPError as exc:
            assert exc.code == 403
            assert b"cross-origin mutation refused" in exc.read()
        else:  # pragma: no cover - a successful cross-origin write is a security regression
            raise AssertionError("cross-origin scene mutation unexpectedly succeeded")
        assert state.scene.title == "canvas"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
