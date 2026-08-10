#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = [
#   "numpy>=1.24", "scipy>=1.10", "soundfile>=0.12",
#   "librosa>=0.10,<0.11", "numba<0.61", "music21>=9.0",
# ]
# ///
# The upper bound matters, not just style: `numba<0.61` (a librosa/mus_audio.py
# dependency) fails to build past Python 3.12, and an unpinned `uv run --script`
# is free to resolve whatever interpreter it finds newest — see
# `mus-cli/tests/check_report.rs`'s `run_python_checker` for where this exact
# failure was hit and fixed the same way (`--python 3.12`) for the oracle's own
# unpinned header, which is left alone on purpose (WF9 never edits the oracle).
"""mus-rs/tools/parity_render.py — WF9's gate.

Renders every corpus score (`aigua/*.mus`) through both implementations —
the Python oracle (`mus_audio.render`, in-process) and the Rust engine
(`mus-cli render`, subprocess) — decodes both WAVs, and measures. The
report is the artifact: divergence is recorded, never hidden or silently
capped (see `SPECS/audio/README.md` / `SPECS/audio/WF9-corpus-parity.md`).

Usage (from the repo root):
    uv run --script mus-rs/tools/parity_render.py --build
    uv run --script mus-rs/tools/parity_render.py smoke.mus aigua_states.mus
    uv run --script mus-rs/tools/parity_render.py --write-expectations

...or with any interpreter that already has the deps above (e.g. a
sibling checkout's `.venv`):
    /path/to/.venv/bin/python3 mus-rs/tools/parity_render.py --build

Exit code is 0 iff every attempted score's verdict is "ok"; the full
report is written before the process ever exits, on every path (a
`SystemExit`/return happens only after the write).

Two corpus assets are derived, gitignored, and NOT carried into a fresh
`git worktree` (see `.gitignore`'s `aigua/v2/*.json` and `aigua/*.wav`
rules): `aigua/v2/sweep-events.json` and `aigua/aigua_raw.wav`. Without
them, `aigua_1547.mus`, `aigua_1568.mus`, `aigua_states.mus`, and
`motet.mus` cannot render on either side (a `FileNotFoundError` from the
oracle, a matching refusal from the engine) — regenerate them via the
pipeline in `aigua/README.md`, or copy them from a checkout that already
has them. This tool preflights every score's referenced assets and
reports a clear `missing asset(s): ...` verdict rather than surfacing a
raw traceback when they are absent.

Those same two assets are why the `cargo test`-only fast subset
(`mus-cli/tests/parity_expectations.rs`) does NOT use the real
`aigua_states.mus` as its second score, even though `--scores`/the full
corpus run below still exercises it (gated by the same preflight, exactly
like every other corpus score): see `WF9_OFFLINE_FIXTURE` and
`FAST_SUBSET` below.
"""

import argparse
import contextlib
import datetime as dt
import io
import json
import math
import re
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import mus  # noqa: E402 — the shared parser, for the asset preflight
import mus_audio  # noqa: E402 — the oracle

MUS_RS = ROOT / "mus-rs"
AIGUA_DIR = ROOT / "aigua"
DEFAULT_RUST_BIN = MUS_RS / "target" / "release" / "mus"
DEFAULT_REPORT = MUS_RS / "parity" / "parity-report.json"
EXPECTATIONS_PATH = MUS_RS / "crates" / "mus-cli" / "tests" / "fixtures" / "parity_expectations.json"

# A small, fully self-contained stand-in for `aigua_states.mus` in the
# `cargo test`-only fast subset: same two feature families (`gest=`
# pack-sample polyline quotation, tape-style `off=`/`gate`/`lpf=` sample
# playback) but backed by committed assets under this fixture's own
# directory instead of `aigua/v2/sweep-events.json` / `aigua/aigua_raw.wav`
# (gitignored, absent from a clean checkout — see this module's docstring
# and `mus-rs/crates/mus-cli/tests/parity_expectations.rs`). Rendered
# through this very tool (`run_one_score`, same as every corpus score) at
# `max_abs` ~2e-7 / `rel_rms` ~4e-7 against the oracle before its
# expectation digest was frozen — real cross-language parity, not just a
# Rust snapshot.
WF9_OFFLINE_FIXTURE = MUS_RS / "crates" / "mus-cli" / "tests" / "fixtures" / "wf9_offline" / "wf9_offline.mus"

# `mus-cli/tests/` (WF9) asserts the Rust engine's receipt against these
# two, without Python, on every `cargo test` — see WF9-corpus-parity.md
# point 3. Keep small: they are rendered on every `cargo test` run.
# `FAST_SUBSET` holds the basenames `write_expectations` keys the frozen
# JSON by (and filters `results` against); `FAST_SUBSET_RENDER_ARGS` holds
# what actually gets passed as score arguments — bare names resolve under
# `AIGUA_DIR` (see `run_one_score`), so the fixture (which does not live
# there) is passed as an absolute path.
FAST_SUBSET = ["smoke.mus", WF9_OFFLINE_FIXTURE.name]
FAST_SUBSET_RENDER_ARGS = ["smoke.mus", str(WF9_OFFLINE_FIXTURE)]

# WF9-corpus-parity.md point 2: scores whose transform set avoids the
# vocode family get the tight bound; a score touching any of the four
# markers below gets the loose, provisional one. The mapping to markers
# is grep-level (matching "Determine each score's transform set by
# grepping its params"), not a re-simulation of the renderer — see
# `classify_transforms`'s docstring for why each marker was chosen.
STRICT_REL_RMS = 1e-3
VOCODE_REL_RMS = 3e-2

EVENTS_RE = re.compile(
    r"^(?P<name>.+?): (?P<notes>\d+) events, (?P<voices>\d+) voices, "
    r"(?P<secs>[0-9.]+)s, A=(?P<a4>[0-9.]+) Hz\s*$",
    re.MULTILINE,
)
SIDECHAIN_RE = re.compile(
    r"sidechain: (?P<hits>\d+) hits from '(?P<track>[^']*)' "
    r"depth (?P<depth>[0-9.]+) rel (?P<rel>[0-9.]+)s"
)
BAD_HEADER_RE = re.compile(r"!\s*(?P<count>\d+) unparseable token\(s\):")
OVERFLOW_RE = re.compile(r"\.\.\. and \d+ more")

MODE_VOCODER_RE = re.compile(r"mode\s*=\s*vocoder")
GLOW_RE = re.compile(r"\bglow\s*=")
GEST_RE = re.compile(r"\bgest\s*=")
GSRC_RAW_RE = re.compile(r"gsrc\s*=\s*raw")
STR_RE = re.compile(r"\bstr\s*=")


# ------------------------------------------------------------- best-effort timeout


class _TimeLimit:
    """POSIX `SIGALRM`-based wall-clock budget for the in-process Python
    render call. Best-effort, not a hard guarantee: a signal can only be
    serviced at a bytecode/C-API boundary, so a single long-running numpy/
    scipy/librosa C call can run past the deadline before Python notices.
    `render_via_rust`'s `subprocess.run(..., timeout=...)` is the reliable
    half of `--timeout-s`; this is the best that is possible in-process
    without threads, which is not worth the complexity here — every real
    corpus score renders in under a minute (see `mus-rs/parity/README.md`).
    """

    def __init__(self, seconds: float | None):
        self.seconds = seconds
        self._previous = None

    def __enter__(self):
        if self.seconds:
            self._previous = signal.signal(signal.SIGALRM, self._on_alarm)
            signal.setitimer(signal.ITIMER_REAL, self.seconds)
        return self

    def _on_alarm(self, signum, frame):
        raise TimeoutError(f"exceeded {self.seconds}s wall-clock budget")

    def __exit__(self, *exc):
        if self.seconds:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self._previous)
        return False


# ------------------------------------------------------------------- oracle side


@dataclass
class PyRenderResult:
    notes: int = 0
    voices: int = 0
    total_seconds: float = 0.0
    tuning_a: float = 0.0
    sidechain_hits: int = 0
    sidechain_track: str | None = None
    bad_count: int = 0
    bad_lines: list = field(default_factory=list)
    bad_truncated: bool = False
    wall_seconds: float = 0.0
    error: str | None = None
    timed_out: bool = False
    py_traceback: str | None = None


def _parse_bad_tokens(stderr_text: str) -> tuple[list[str], int, bool]:
    """`stats["bad"]` itself is never exposed by `mus_audio.render` — this
    reads it back off the oracle's own stderr print (lines 1170-1175),
    which is the ONLY thing rendered by an in-process, unmodified call.
    That print caps the *detail* lines at 12 (`stats["bad"][:12]`) but the
    header always states the true total count first — so the count
    returned here is always exact; only the line-by-line content degrades
    to a 12-line prefix when a score has more than 12 bad tokens. None of
    the 13 corpus scores currently do (verified empirically), so this
    degrades gracefully rather than actually losing information today —
    see `compare_receipts` for how a truncated prefix is compared.
    """
    header = BAD_HEADER_RE.search(stderr_text)
    if not header:
        return [], 0, False
    count = int(header.group("count"))
    lines: list[str] = []
    truncated = False
    in_block = False
    for line in stderr_text.splitlines():
        if BAD_HEADER_RE.search(line):
            in_block = True
            continue
        if not in_block:
            continue
        if OVERFLOW_RE.search(line):
            truncated = True
            break
        if line.startswith("      "):
            lines.append(line.strip())
        else:
            break
    return lines, count, truncated


def render_via_python(score_path: Path, out_wav: Path, timeout_s: float | None) -> PyRenderResult:
    """`render(score, tmp/py.wav)`, in-process, per the spec. Stats are
    recovered from the oracle's own verbose stdout/stderr text (see
    `_parse_bad_tokens`) rather than by instrumenting or modifying
    `mus_audio.py` — the oracle stays exactly what ships, unmodified."""
    result = PyRenderResult()
    stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
    t0 = time.perf_counter()
    try:
        with _TimeLimit(timeout_s):
            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                mus_audio.render(score_path, out_wav, verbose=True)
    except TimeoutError as e:
        result.timed_out = True
        result.error = str(e)
    except Exception as e:  # a render failure is a per-score result, not a tool crash
        result.error = f"{type(e).__name__}: {e}"
        result.py_traceback = traceback.format_exc()
    result.wall_seconds = time.perf_counter() - t0

    stdout_text, stderr_text = stdout_buf.getvalue(), stderr_buf.getvalue()
    m = EVENTS_RE.search(stdout_text)
    if m:
        result.notes = int(m.group("notes"))
        result.voices = int(m.group("voices"))
        result.total_seconds = float(m.group("secs"))
        result.tuning_a = float(m.group("a4"))
    elif result.error is None:
        result.error = "could not parse the oracle's own 'N events, M voices...' stdout line"

    sm = SIDECHAIN_RE.search(stdout_text)
    if sm:
        result.sidechain_hits = int(sm.group("hits"))
        result.sidechain_track = sm.group("track")

    result.bad_lines, result.bad_count, result.bad_truncated = _parse_bad_tokens(stderr_text)
    return result


# -------------------------------------------------------------------- rust side


@dataclass
class RustRenderResult:
    receipt: dict | None = None
    wall_seconds: float = 0.0
    error: str | None = None
    timed_out: bool = False
    stderr: str = ""


def render_via_rust(
    rust_bin: Path, score_path: Path, out_wav: Path, timeout_s: float | None
) -> RustRenderResult:
    """`cargo run -p mus-cli --release -- render <score> -o tmp/rs.wav`,
    except invoking the already-built binary directly, per the spec
    ("build once, then invoke the binary directly")."""
    result = RustRenderResult()
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            [str(rust_bin), "render", str(score_path), "-o", str(out_wav), "--json"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        result.timed_out = True
        result.error = f"exceeded {timeout_s}s wall-clock budget"
        result.wall_seconds = time.perf_counter() - t0
        return result
    result.wall_seconds = time.perf_counter() - t0
    result.stderr = proc.stderr

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = None

    if proc.returncode != 0:
        if isinstance(payload, dict) and "error" in payload:
            result.error = payload["error"]
        else:
            result.error = f"mus-cli exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()}"
        return result
    if not isinstance(payload, dict):
        result.error = f"mus-cli produced non-JSON stdout: {proc.stdout[:200]!r}"
        return result
    result.receipt = payload
    return result


# ------------------------------------------------------------------- comparators


def classify_transforms(text: str) -> list[str]:
    """Grep-level transform classification (WF9-corpus-parity.md point 2:
    "Determine each score's transform set by grepping its params"), not a
    re-simulation of the renderer. Each marker maps to a *specific* code
    path in `mus_audio.py` that is loose-tier in `gen_dsp_fixtures.py`'s
    own tolerance tiers (`rel_rms` 5e-3, reimplemented-algorithm) rather
    than tight-tier (`max_abs` ~1e-5/1e-6, pure-numpy port):

    - `mode=vocoder` — chord layering / transposition takes the
      `vocode()` branch instead of `varispeed()`.
    - `glow=` — `glow_chain` vocodes internally for `gharm`/`gwarble`
      (see `gen_dsp_fixtures.py`'s `glow_full_chain` note).
    - `gest=` **together with** `gsrc=raw` — the tape-slice quotation
      path that can call `vocode()` when the notated pitch differs from
      the gesture's median by >0.05 st (mus_audio.py:983-987). A bare
      `gest=` *without* `gsrc=raw` takes the pack-sample `pitch_polyline`
      path instead, which is non-uniform resampling, not a phase
      vocoder — `gen_dsp_fixtures.py`'s own `pitch_polyline` case is
      tight-tier (`max_abs` 1e-5), so it is deliberately excluded here.
    - `str=` — `stretch()` (`librosa.effects.time_stretch`), also
      loose-tier per `gen_dsp_fixtures.py`'s `stretch_140`/`stretch_060`.
    """
    used = []
    if MODE_VOCODER_RE.search(text):
        used.append("mode=vocoder")
    if GLOW_RE.search(text):
        used.append("glow")
    if GEST_RE.search(text) and GSRC_RAW_RE.search(text):
        used.append("gest+gsrc=raw")
    if STR_RE.search(text):
        used.append("str")
    return used


def compute_metrics(py_wav: Path, rs_wav: Path) -> dict:
    """`max_abs`; `rel_rms` joint over channels; per-channel RMS delta in
    dB. `expected` is always the Python (oracle) array and `actual` is
    always the Rust array — matching `mus_dsp::fixtures::Case::check`'s
    own convention (`rel = sqrt(sum((a-e)^2) / max(sum(e^2), 1e-30))`) so
    the two languages' notion of "relative" agrees exactly. Accumulates in
    float64 regardless of the on-disk dtype — bolero alone is ~89M scalar
    samples, too many to sum accurately in float32.

    Every numeric metric is gated on THREE independent structural checks
    — `sample_rate_match`, `length_match` (frame count), `channels_match`
    (channel count) — each reported in the returned dict. A bare
    `len(py) == len(rs)` frame-count check is not enough on its own:
    `always_2d=True` gives mono files shape `(N, 1)` and stereo files
    `(N, 2)`, and numpy freely broadcasts `(N, 1) - (N, 2)` into `(N, 2)`
    rather than raising — so a mono Python render diffed against a
    stereo Rust render at the same frame count would silently produce a
    numeric verdict for audio that isn't even the same shape. Two WAVs
    can likewise share a frame count while their declared sample rates
    differ, representing different durations compared sample-for-sample
    as if they were aligned. If any of the three checks fails, no numeric
    metric is computed (all three stay `None`) — exactly like a bare
    length mismatch already did (README.md: "output length is part of
    the contract")."""
    py, sr_py = sf.read(str(py_wav), dtype="float32", always_2d=True)
    rs, sr_rs = sf.read(str(rs_wav), dtype="float32", always_2d=True)
    n_py, n_rs = len(py), len(rs)
    ch_py, ch_rs = py.shape[1], rs.shape[1]
    sample_rate_match = int(sr_py) == int(sr_rs)
    length_match = n_py == n_rs
    channels_match = ch_py == ch_rs
    comparable = sample_rate_match and length_match and channels_match
    metrics = {
        "n_samples_py": n_py,
        "n_samples_rs": n_rs,
        "channels_py": int(ch_py),
        "channels_rs": int(ch_rs),
        "sample_rate_py": int(sr_py),
        "sample_rate_rs": int(sr_rs),
        "sample_rate_match": sample_rate_match,
        "length_match": length_match,
        "channels_match": channels_match,
        "max_abs": None,
        "rel_rms": None,
        "rms_delta_db": None,
    }
    if not comparable:
        # A sample-rate, frame-count, or channel-count mismatch is a hard
        # failure under every metric (README.md) — no metric is computed
        # at all rather than let numpy broadcast e.g. an (N,1) array
        # against an (N,2) one and report a number for audio that isn't
        # structurally comparable in the first place.
        return metrics

    py64 = py.astype(np.float64)
    rs64 = rs.astype(np.float64)
    diff = rs64 - py64
    metrics["max_abs"] = float(np.max(np.abs(diff))) if diff.size else 0.0
    denom = float(np.sum(py64 * py64))
    metrics["rel_rms"] = math.sqrt(float(np.sum(diff * diff)) / max(denom, 1e-30))

    deltas = []
    for ch in range(py64.shape[1]):
        rms_py = math.sqrt(float(np.mean(py64[:, ch] ** 2)))
        rms_rs = math.sqrt(float(np.mean(rs64[:, ch] ** 2)))
        deltas.append(20 * math.log10(max(rms_rs, 1e-12)) - 20 * math.log10(max(rms_py, 1e-12)))
    metrics["rms_delta_db"] = deltas
    return metrics


def compare_receipts(py: PyRenderResult, rs_receipt: dict) -> tuple[bool, list[str]]:
    """The three fields WF9-corpus-parity.md names ("event counts,
    sidechain hits, bad tokens") plus voice count — every one of these is
    an *exact integer* on both sides (no `.1f`-rounded print to launder
    through), so this is a zero-tolerance comparison, no fuzzing.

    `durationSeconds`/`tuningA` are deliberately NOT gated here even
    though the Rust receipt carries them at full precision: the only
    Python-side source for them is the oracle's own console line, printed
    at `.1f` — comparing a rounded-to-one-decimal parse against a
    full-precision float would manufacture false "mismatches" out of
    print rounding, not real divergence. They are still recorded (see
    `run_one_score`) for a human to eyeball.

    `badTokens` is required to be *present on* and *a list* — never
    defaulted. `rs_receipt.get("badTokens", [])` would treat an absent
    field exactly like a genuinely-empty list; since every current
    corpus score has zero bad tokens, that silently compares `0 == 0`
    and reports `receipt_match: true` even though the required field
    never showed up in the receipt at all. A missing or wrong-typed
    field is therefore reported as its own mismatch reason rather than
    coerced into an empty list.
    """
    reasons = []
    rs_events = rs_receipt.get("eventCount")
    if py.notes != rs_events:
        reasons.append(f"eventCount: py={py.notes} rs={rs_events}")

    rs_sc = rs_receipt.get("sidechainHits")
    if py.sidechain_hits != rs_sc:
        reasons.append(f"sidechainHits: py={py.sidechain_hits} rs={rs_sc}")

    if "badTokens" not in rs_receipt:
        reasons.append("badTokens: field missing from rust receipt (required, not defaulted)")
    elif not isinstance(rs_receipt["badTokens"], list):
        got = type(rs_receipt["badTokens"]).__name__
        reasons.append(f"badTokens: expected a list, rust receipt has {got}")
    else:
        rs_bad = rs_receipt["badTokens"]
        if py.bad_count != len(rs_bad):
            reasons.append(f"badTokens count: py={py.bad_count} rs={len(rs_bad)}")
        else:
            prefix = rs_bad[: len(py.bad_lines)]
            if py.bad_lines != prefix:
                note = " (py stderr print truncates detail at 12 — prefix-only compare)" if py.bad_truncated else ""
                reasons.append(f"badTokens content differs{note}: py={py.bad_lines} rs_prefix={prefix}")

    rs_voices = rs_receipt.get("voiceCount")
    if py.voices != rs_voices:
        reasons.append(f"voiceCount: py={py.voices} rs={rs_voices}")

    return (len(reasons) == 0, reasons)


# --------------------------------------------------------------- asset preflight


def _missing_assets(score_path: Path, text: str) -> list[str]:
    """Every `pack`/`gestures`/`tape`/`sample=` reference this score
    makes, checked for existence up front. `mus_audio.render` itself would
    fail at the *first* missing one with a bare `FileNotFoundError`
    traceback; this reports all of them at once with a clear message —
    notably including the two derived, gitignored corpus assets
    (`aigua/v2/*.json`, `aigua/*.wav`) that a fresh worktree never
    receives (see this module's docstring)."""
    parsed = mus.parse_mus(text)
    missing = []
    for key in ("pack", "gestures", "tape"):
        rel = parsed.extra.get(key)
        if rel:
            p = (score_path.parent / rel).resolve()
            if not p.exists():
                missing.append(f"{key}={rel} -> {p}")
    for inst in parsed.instruments:
        rel = inst.params.get("sample")
        if rel:
            p = (score_path.parent / rel).resolve()
            if not p.exists():
                missing.append(f"sample={rel} -> {p}")
    return missing


# ------------------------------------------------------------------ orchestration


def run_one_score(
    name: str, rust_bin: Path, work_dir: Path, timeout_s: float | None, keep_wavs: bool
) -> dict:
    score_path = Path(name)
    if not score_path.is_absolute():
        score_path = AIGUA_DIR / score_path
    if score_path.suffix != ".mus":
        score_path = score_path.with_suffix(".mus")

    entry: dict = {
        "score": score_path.name,
        "n_samples_py": None,
        "n_samples_rs": None,
        "channels_py": None,
        "channels_rs": None,
        "sample_rate_py": None,
        "sample_rate_rs": None,
        "max_abs": None,
        "rel_rms": None,
        "rms_delta_db": None,
        "length_match": None,
        "channels_match": None,
        "sample_rate_match": None,
        "receipt_match": None,
        "transforms_used": [],
        "vocode_touching": False,
        "bound_rel_rms": STRICT_REL_RMS,
        "verdict": "error",
        "reasons": [],
        "python": {},
        "rust": {},
        "error": None,
    }

    if not score_path.exists():
        entry["error"] = f"score not found: {score_path}"
        entry["reasons"] = [entry["error"]]
        return entry

    text = score_path.read_text()
    transforms = classify_transforms(text)
    entry["transforms_used"] = transforms
    entry["vocode_touching"] = bool(transforms)
    entry["bound_rel_rms"] = VOCODE_REL_RMS if transforms else STRICT_REL_RMS

    missing = _missing_assets(score_path, text)
    if missing:
        entry["error"] = "missing asset(s): " + "; ".join(missing)
        entry["reasons"] = [entry["error"]]
        return entry

    py_wav = work_dir / f"{score_path.stem}.py.wav"
    rs_wav = work_dir / f"{score_path.stem}.rs.wav"

    py_res = render_via_python(score_path, py_wav, timeout_s)
    rs_res = render_via_rust(rust_bin, score_path, rs_wav, timeout_s)

    entry["python"] = {
        "events": py_res.notes,
        "voices": py_res.voices,
        "durationSeconds": py_res.total_seconds,
        "tuningA": py_res.tuning_a,
        "sidechainHits": py_res.sidechain_hits,
        "sidechainTrack": py_res.sidechain_track,
        "badTokenCount": py_res.bad_count,
        "badTokenSample": py_res.bad_lines,
        "badTokenListTruncated": py_res.bad_truncated,
        "wallSeconds": py_res.wall_seconds,
        "error": py_res.error,
        "timedOut": py_res.timed_out,
    }
    rs_fields = {}
    if rs_res.receipt:
        for k in (
            "eventCount", "skippedCount", "sidechainHits", "perTrackEvents", "badTokens",
            "voiceCount", "durationSeconds", "tuningA", "peakDbfs", "rmsDbfs",
            "renderDigest", "sourceDigest", "engineVersion", "warnings",
        ):
            if k in rs_res.receipt:
                rs_fields[k] = rs_res.receipt[k]
    entry["rust"] = {
        "wallSeconds": rs_res.wall_seconds,
        "error": rs_res.error,
        "timedOut": rs_res.timed_out,
        **rs_fields,
    }

    if py_res.error or rs_res.error:
        parts = []
        if py_res.error:
            parts.append(f"python: {py_res.error}")
        if rs_res.error:
            parts.append(f"rust: {rs_res.error}")
        entry["error"] = "; ".join(parts)
        entry["reasons"] = [entry["error"]]
        entry["verdict"] = "timeout" if (py_res.timed_out or rs_res.timed_out) else "error"
        return entry

    metrics = compute_metrics(py_wav, rs_wav)
    entry["n_samples_py"] = metrics["n_samples_py"]
    entry["n_samples_rs"] = metrics["n_samples_rs"]
    entry["channels_py"] = metrics["channels_py"]
    entry["channels_rs"] = metrics["channels_rs"]
    entry["sample_rate_py"] = metrics["sample_rate_py"]
    entry["sample_rate_rs"] = metrics["sample_rate_rs"]
    entry["max_abs"] = metrics["max_abs"]
    entry["rel_rms"] = metrics["rel_rms"]
    entry["rms_delta_db"] = metrics["rms_delta_db"]
    entry["length_match"] = metrics["length_match"]
    entry["channels_match"] = metrics["channels_match"]
    entry["sample_rate_match"] = metrics["sample_rate_match"]

    reasons = []
    if not metrics["sample_rate_match"]:
        reasons.append(
            f"sample rate mismatch: sr_py={metrics['sample_rate_py']} sr_rs={metrics['sample_rate_rs']}"
        )
    if not metrics["length_match"]:
        reasons.append(f"length mismatch: n_py={metrics['n_samples_py']} n_rs={metrics['n_samples_rs']}")
    if not metrics["channels_match"]:
        reasons.append(
            f"channel count mismatch: ch_py={metrics['channels_py']} ch_rs={metrics['channels_rs']}"
        )

    match, mismatch_reasons = compare_receipts(py_res, rs_res.receipt)
    entry["receipt_match"] = match
    reasons.extend(mismatch_reasons)

    comparable = metrics["sample_rate_match"] and metrics["length_match"] and metrics["channels_match"]
    if comparable and metrics["rel_rms"] is not None and metrics["rel_rms"] > entry["bound_rel_rms"]:
        reasons.append(f"rel_rms {metrics['rel_rms']:.3e} > bound {entry['bound_rel_rms']:.1e}")

    entry["reasons"] = reasons
    entry["verdict"] = "ok" if not reasons else "diverged"

    if keep_wavs:
        entry["python"]["wavPath"] = str(py_wav)
        entry["rust"]["wavPath"] = str(rs_wav)
    else:
        py_wav.unlink(missing_ok=True)
        rs_wav.unlink(missing_ok=True)

    return entry


def write_expectations(fast_entries: list[dict]) -> None:
    payload = {
        "schema": "mus.audio.parity-expectations.v1",
        "note": "Generated by parity_render.py --write-expectations. Regenerate with:\n"
        "  uv run --script mus-rs/tools/parity_render.py --build --write-expectations",
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scores": {
            e["score"]: {
                k: e["rust"][k]
                for k in (
                    "renderDigest", "sourceDigest", "eventCount", "skippedCount",
                    "sidechainHits", "perTrackEvents", "badTokens", "voiceCount",
                    "durationSeconds", "tuningA", "peakDbfs", "rmsDbfs", "engineVersion",
                )
                if k in e["rust"]
            }
            for e in fast_entries
        },
    }
    EXPECTATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXPECTATIONS_PATH.write_text(json.dumps(payload, indent=1) + "\n")


# ------------------------------------------------------------------------ selftest


def run_selftests() -> None:
    """The spec's own words: "the tool self-tests its comparators"
    (WF9-corpus-parity.md, "Tests") — synthetic wavs with hand-worked
    expected `max_abs`/`rel_rms`/dB values, kept independent of any oracle
    or engine output. This is the lesson `mus-engine/src/lib.rs`'s
    `f32_to_pcm24` doc comment names from the rejected WF8 attempt: an
    unsound self-test round-trips its expectation through the function
    under test, which "proves" nothing. Every expected value below is
    worked by hand from the array construction, never by calling
    `compute_metrics` (or any Rust helper) and trusting the result.
    """
    with tempfile.TemporaryDirectory(prefix="mus-parity-selftest-") as td_str:
        td = Path(td_str)

        # 1) Bit-identical arrays -> ~zero divergence, zero dB delta.
        n = 4000
        base = (0.2 * np.sin(2 * np.pi * 220 * np.arange(n) / 48000)).astype(np.float32)
        stereo = np.stack([base, base * 0.8], axis=1)
        p_a, p_b = td / "a.wav", td / "b.wav"
        sf.write(str(p_a), stereo, 48000, subtype="PCM_24")
        sf.write(str(p_b), stereo, 48000, subtype="PCM_24")
        m = compute_metrics(p_a, p_b)
        assert m["length_match"]
        assert m["max_abs"] < 1e-6, m["max_abs"]
        assert m["rel_rms"] < 1e-6, m["rel_rms"]
        assert abs(m["rms_delta_db"][0]) < 1e-3, m["rms_delta_db"]
        assert abs(m["rms_delta_db"][1]) < 1e-3, m["rms_delta_db"]

        # 2) A single sample offset by exactly 0.02 on a constant-0.1
        # signal (2000 frames x 2ch = 4000 scalar samples): max_abs must
        # be exactly that offset; rel_rms is hand-solved from the same
        # construction parameters (not a magic literal).
        n2 = 2000
        const = np.full((n2, 2), 0.1, dtype=np.float32)
        py2, rs2 = const.copy(), const.copy()
        rs2[500, 0] = 0.12
        p_py2, p_rs2 = td / "py2.wav", td / "rs2.wav"
        sf.write(str(p_py2), py2, 48000, subtype="PCM_24")
        sf.write(str(p_rs2), rs2, 48000, subtype="PCM_24")
        m2 = compute_metrics(p_py2, p_rs2)
        expected_max_abs = 0.02
        expected_rel_rms = math.sqrt((0.02**2) / (n2 * 2 * (0.1**2)))
        assert abs(m2["max_abs"] - expected_max_abs) < 2e-6, (m2["max_abs"], expected_max_abs)
        assert abs(m2["rel_rms"] - expected_rel_rms) < 2e-6, (m2["rel_rms"], expected_rel_rms)

        # 3) Length mismatch: a hard failure, never a truncated compare.
        short = const[:-10]
        p_short = td / "short.wav"
        sf.write(str(p_short), short, 48000, subtype="PCM_24")
        m3 = compute_metrics(p_py2, p_short)
        assert not m3["length_match"]
        assert m3["max_abs"] is None and m3["rel_rms"] is None

        # 4) Per-channel RMS delta in dB: pure amplitude scale, hand-solved
        # (20*log10(2) and 20*log10(0.5)).
        amp_py = np.full((1000, 2), 0.1, dtype=np.float32)
        amp_rs = amp_py.copy()
        amp_rs[:, 0] *= 2.0
        amp_rs[:, 1] *= 0.5
        p_amp_py, p_amp_rs = td / "amp_py.wav", td / "amp_rs.wav"
        sf.write(str(p_amp_py), amp_py, 48000, subtype="PCM_24")
        sf.write(str(p_amp_rs), amp_rs, 48000, subtype="PCM_24")
        m4 = compute_metrics(p_amp_py, p_amp_rs)
        assert abs(m4["rms_delta_db"][0] - 20 * math.log10(2.0)) < 1e-2, m4["rms_delta_db"]
        assert abs(m4["rms_delta_db"][1] - 20 * math.log10(0.5)) < 1e-2, m4["rms_delta_db"]

        # 5) Differing channel shapes at an EQUAL frame count: `len()`
        # alone (frame count) cannot see this — a mono (N,1) py array and
        # a stereo (N,2) rs array both report n=n5, so a bare
        # `len(py) == len(rs)` gate would proceed straight to `rs64 -
        # py64`, which numpy silently broadcasts to (N,2) instead of
        # raising. Regression for the finding that only frame count was
        # checked, never full array shape.
        n5 = 1000
        mono_py = np.full((n5, 1), 0.1, dtype=np.float32)
        stereo_rs = np.full((n5, 2), 0.1, dtype=np.float32)
        p_mono, p_stereo = td / "mono.wav", td / "stereo.wav"
        sf.write(str(p_mono), mono_py, 48000, subtype="PCM_24")
        sf.write(str(p_stereo), stereo_rs, 48000, subtype="PCM_24")
        m5 = compute_metrics(p_mono, p_stereo)
        assert m5["length_match"], "frame counts (n5 == n5) must still agree"
        assert m5["channels_py"] == 1 and m5["channels_rs"] == 2, m5
        assert not m5["channels_match"], m5
        assert m5["max_abs"] is None and m5["rel_rms"] is None and m5["rms_delta_db"] is None, (
            "a channel-count mismatch must never be silently numpy-broadcast into a numeric verdict",
            m5,
        )

        # 6) Differing sample rates at an identical shape: max_abs/rel_rms
        # would otherwise "compute" a number straight off the raw sample
        # arrays, comparing frame k of a 48kHz file against frame k of a
        # 44.1kHz file as if they were the same instant. Regression for
        # the finding that sr_py/sr_rs were captured but never compared.
        n6 = 1000
        same_shape = np.full((n6, 1), 0.1, dtype=np.float32)
        p_sr_a, p_sr_b = td / "sr_a.wav", td / "sr_b.wav"
        sf.write(str(p_sr_a), same_shape, 48000, subtype="PCM_24")
        sf.write(str(p_sr_b), same_shape, 44100, subtype="PCM_24")
        m6 = compute_metrics(p_sr_a, p_sr_b)
        assert m6["length_match"] and m6["channels_match"], "shape must agree; only the rate differs"
        assert m6["sample_rate_py"] == 48000 and m6["sample_rate_rs"] == 44100, m6
        assert not m6["sample_rate_match"], m6
        assert m6["max_abs"] is None and m6["rel_rms"] is None and m6["rms_delta_db"] is None, (
            "a sample-rate mismatch must never be silently compared sample-for-sample",
            m6,
        )

    # classify_transforms: pure regex over hand-picked text, no engine/oracle.
    assert classify_transforms("bar 1: x=A4q[mode=vocoder]") == ["mode=vocoder"]
    assert classify_transforms("bar 1: x=A4q[glow=5]") == ["glow"]
    assert classify_transforms("bar 1: x=A4q[str=fit]") == ["str"]
    assert classify_transforms("bar 1: x=A4q[gest=h1,gsrc=raw]") == ["gest+gsrc=raw"]
    assert classify_transforms("bar 1: x=A4q[gest=h1]") == [], "bare gest= (no gsrc=raw) is the tight-tier polyline path"
    assert classify_transforms("bar 1: x=A4q") == []

    # compare_receipts: exact-integer gating fields, hand-constructed.
    py_ok = PyRenderResult(notes=10, sidechain_hits=2, bad_count=0, bad_lines=[], voices=3)
    ok, reasons = compare_receipts(py_ok, {"eventCount": 10, "sidechainHits": 2, "badTokens": [], "voiceCount": 3})
    assert ok and not reasons, reasons
    py_bad = PyRenderResult(notes=10, sidechain_hits=2, bad_count=1, bad_lines=["b1 x: bogus"], voices=3)
    ok2, reasons2 = compare_receipts(
        py_bad, {"eventCount": 11, "sidechainHits": 2, "badTokens": [], "voiceCount": 3}
    )
    assert not ok2 and len(reasons2) == 2, reasons2  # eventCount AND badTokens count both differ

    # compare_receipts: a `badTokens` field ABSENT from the rust receipt
    # must never silently pass as "zero bad tokens". Every real corpus
    # score currently has zero bad tokens, so `rs_receipt.get("badTokens",
    # [])` used to compare `0 == len([])` and report a clean match even
    # though the required field never showed up at all — regression for
    # that finding.
    py_zero_bad = PyRenderResult(notes=5, sidechain_hits=0, bad_count=0, bad_lines=[], voices=1)
    ok3, reasons3 = compare_receipts(py_zero_bad, {"eventCount": 5, "sidechainHits": 0, "voiceCount": 1})
    assert not ok3, "a missing badTokens field must be reported, never defaulted to an empty list"
    assert len(reasons3) == 1 and "badTokens" in reasons3[0], reasons3

    # compare_receipts: badTokens present but the wrong type (not a list)
    # must also be reported, not silently coerced or len()'d into a crash.
    ok4, reasons4 = compare_receipts(
        py_zero_bad, {"eventCount": 5, "sidechainHits": 0, "voiceCount": 1, "badTokens": None}
    )
    assert not ok4, "a non-list badTokens must be reported as a mismatch"
    assert len(reasons4) == 1 and "badTokens" in reasons4[0], reasons4

    # _parse_bad_tokens: header count is exact even past the 12-line cap;
    # content is the printed prefix, flagged truncated.
    stderr_text = (
        "  ! 14 unparseable token(s):\n"
        + "".join(f"      b{i} x: bogus{i}\n" for i in range(12))
        + "      ... and 2 more\n"
    )
    lines, count, truncated = _parse_bad_tokens(stderr_text)
    assert count == 14, count
    assert len(lines) == 12, lines
    assert truncated is True


# ----------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(
        description="WF9: render the aigua corpus through the Python oracle and the "
        "Rust engine and measure sample-level parity.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "scores", nargs="*",
        help="score names (default: the full aigua/*.mus corpus, 13 scores). "
        "Bare names resolve under aigua/ and get a .mus suffix if missing.",
    )
    ap.add_argument("--rust-bin", type=Path, default=DEFAULT_RUST_BIN, help="path to the built mus-cli binary")
    ap.add_argument("--build", action="store_true", help="`cargo build --release -p mus-cli` before rendering")
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORT, help="report path")
    ap.add_argument(
        "--write-expectations", action="store_true",
        help="also (re)write the committed Rust fast-subset expectation digests "
        f"({EXPECTATIONS_PATH.relative_to(ROOT)}) that mus-cli/tests/ asserts against without "
        "Python. Defaults the score set to the fast subset; refuses to write if any "
        "fast-subset score isn't verdict 'ok'.",
    )
    ap.add_argument(
        "--timeout-s", type=float, default=None,
        help="best-effort per-side, per-score wall-clock budget. On expiry that score's "
        "verdict is 'timeout', explicitly recorded in the report, and the run continues "
        "(no silent caps) — see WF9-corpus-parity.md point 1's bolero note. Unset by "
        "default: the whole corpus renders in well under ten minutes (see "
        "mus-rs/parity/README.md), so there is nothing to bound in practice.",
    )
    ap.add_argument("--tmp-dir", type=Path, default=None, help="working dir for rendered wavs (default: a fresh temp dir)")
    ap.add_argument("--keep-wavs", action="store_true", help="don't delete rendered wavs after comparing")
    ap.add_argument("--skip-selftest", action="store_true", help="skip the built-in comparator self-tests")
    args = ap.parse_args()

    if not args.skip_selftest:
        run_selftests()
        print("selftest: comparator self-tests passed", file=sys.stderr)

    if args.build:
        subprocess.run(["cargo", "build", "--release", "-p", "mus-cli"], cwd=MUS_RS, check=True)

    rust_bin = args.rust_bin
    if not rust_bin.exists():
        print(f"error: rust binary not found at {rust_bin} (pass --build or --rust-bin)", file=sys.stderr)
        return 2

    if args.scores:
        score_names = args.scores
    elif args.write_expectations:
        score_names = list(FAST_SUBSET_RENDER_ARGS)
    else:
        score_names = []
        for p in sorted(AIGUA_DIR.glob("*.mus")):
            # Post-parity voices (synth=pluck/weave) have no oracle line to
            # compare against; skipping is the correct result, and it must
            # be loud — a silently shrunk corpus would read as coverage.
            if re.search(r"synth\s*=\s*(pluck|weave)", p.read_text()):
                print(f"skipping {p.name}: post-parity voice, no oracle", file=sys.stderr)
                continue
            score_names.append(p.name)

    work_dir = args.tmp_dir or Path(tempfile.mkdtemp(prefix="mus-parity-"))
    work_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for name in score_names:
        print(f"rendering {name} ...", file=sys.stderr)
        entry = run_one_score(name, rust_bin, work_dir, args.timeout_s, args.keep_wavs)
        results.append(entry)
        rel_rms_txt = f" rel_rms={entry['rel_rms']:.3e}" if entry.get("rel_rms") is not None else ""
        error_txt = f" ({entry['error']})" if entry.get("error") else ""
        print(f"  {entry['score']}: {entry['verdict']}{rel_rms_txt}{error_txt}", file=sys.stderr)

    engine_version = next((e["rust"].get("engineVersion") for e in results if e["rust"].get("engineVersion")), None)
    renderer_version = getattr(mus_audio, "RENDERER_VERSION", None)

    by_verdict: dict = {}
    for e in results:
        by_verdict[e["verdict"]] = by_verdict.get(e["verdict"], 0) + 1
    # Non-comparable entries (rel_rms=None: sample-rate/frame/channel
    # mismatch - the hardest failures) rank FIRST: an empty offender list
    # beside a diverged verdict would hide exactly what this report exists
    # to show.
    ranked = sorted(results, key=lambda e: (e.get("rel_rms") is not None, -(e.get("rel_rms") or 0.0)))
    worst = [
        {"score": e["score"], "rel_rms": e["rel_rms"], "max_abs": e["max_abs"], "verdict": e["verdict"]}
        for e in ranked[:5]
    ]

    report = {
        "schema": "mus.audio.parity-report.v1",
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "pythonInterpreter": sys.executable,
        "pythonRendererVersion": renderer_version,
        "rustBinary": str(rust_bin),
        "engineVersion": engine_version,
        "bounds": {"strict_rel_rms": STRICT_REL_RMS, "vocode_rel_rms": VOCODE_REL_RMS},
        "scores": results,
        "summary": {
            "total": len(results),
            "byVerdict": by_verdict,
            "worstOffenders": worst,
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1) + "\n")
    print(f"\nwrote {args.out}", file=sys.stderr)
    print(json.dumps(report["summary"], indent=1))

    exit_ok = bool(results) and all(e["verdict"] == "ok" for e in results)

    if args.write_expectations:
        fast_entries = [e for e in results if e["score"] in FAST_SUBSET]
        all_fast_ok = len(fast_entries) == len(FAST_SUBSET) and all(e["verdict"] == "ok" for e in fast_entries)
        if not all_fast_ok:
            print(
                f"refusing to write expectations: the fast-subset scores {FAST_SUBSET} are "
                "not all 'ok' (rerun with no --scores so the fast subset renders, and fix "
                "parity first — never freeze a known-diverging baseline)",
                file=sys.stderr,
            )
            return 1
        write_expectations(fast_entries)
        print(f"wrote {EXPECTATIONS_PATH}", file=sys.stderr)

    return 0 if exit_ok else 1


if __name__ == "__main__":
    sys.exit(main())
