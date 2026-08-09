"""The check verb is the binary interface Atril builds against.

Three locks: (1) every corpus score emits a schema-valid report; (2) event
counts equal the renderer's placed-event counts for the five scores whose
render counts are known facts; (3) a deliberately broken score refuses with
the right codes on the right semantic anchors.
"""
import json
import sys
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

mus_audio = pytest.importorskip("mus_audio")

SCHEMA = json.loads((ROOT / "schemas" / "mus-check-report.schema.json").read_text())
CORPUS = sorted((ROOT / "aigua").glob("*.mus"))

RENDER_COUNTS = {
    "aigua_states.mus": 147,
    "motet.mus": 546,
    "aigua_1547.mus": 1281,
    "aigua_1568.mus": 2628,
    "aigua_gliss.mus": 512,
}


@pytest.mark.parametrize("score", CORPUS, ids=lambda p: p.name)
def test_corpus_reports_validate_and_are_clean(score):
    report = mus_audio.check_score(score)
    jsonschema.validate(report, SCHEMA)
    assert report["clean"] is True
    assert report["diagnostics"] == []
    expected = RENDER_COUNTS.get(score.name)
    if expected is not None:
        assert len(report["events"]) == expected


def test_broken_score_refuses_with_semantic_anchors(tmp_path):
    bad = tmp_path / "bad.mus"
    bad.write_text(
        "# score: broken\n# tempo: 60\n# time: 4/4\n# bars: 2\n"
        "# gestures: nowhere.json\n\n"
        "# instruments:\n#   xx = ghost (treble, voice=nope)\n\n"
        "bar 1: xx=A4q[gest=h99] Wat Rq Rq\n"
        "bar 2: xx=A4q A4q A4q A4q A4q\n"
    )
    report = mus_audio.check_score(bad)
    jsonschema.validate(report, SCHEMA)
    assert report["clean"] is False
    codes = {d["code"] for d in report["diagnostics"]}
    assert {"missing-gestures", "no-samples-for-track",
            "unknown-gesture", "unparseable-token", "overfull-bar"} <= codes
    unparseable = next(d for d in report["diagnostics"] if d["code"] == "unparseable-token")
    assert unparseable["anchor"] == {"kind": "event", "bar": 1, "track": "xx", "tokenIndex": 1}
    overfull = next(d for d in report["diagnostics"] if d["code"] == "overfull-bar")
    assert overfull["anchor"]["bar"] == 2


def test_swing_and_quotes_are_reported():
    report = mus_audio.check_score(ROOT / "aigua" / "aigua_1568.mus")
    assert report["score"]["swing"] == {"unit": 16, "percent": 55.0}
    swungs = [e for e in report["events"] if e["swungOnsetSeconds"] > e["onsetSeconds"]]
    assert swungs, "swing must displace off-grid sixteenths"
    quotes = [e for e in report["events"] if e["quote"]]
    assert quotes and all(q["quote"]["hypothesisId"] for q in quotes)
    raw = [e for e in quotes if e["quote"]["gsrc"] == "raw"]
    assert raw and raw[0]["quote"]["t0"] is not None
