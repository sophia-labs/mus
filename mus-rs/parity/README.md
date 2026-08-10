# WF9 — corpus render parity

The audio-parity leg's gate: every score in `aigua/*.mus` rendered through
both implementations — the Python oracle (`mus_audio.render`) and the Rust
engine (`mus-cli render`) — decoded, and measured. The report is the
artifact: divergence is recorded, never hidden or silently capped.

Tool: `mus-rs/tools/parity_render.py`. Full option reference: `--help`.

## Running it

Build the Rust binary once, then invoke the tool (any interpreter with
`mus_audio.py`'s own dependencies works — `uv run --script` provisions one
from the file's own PEP 723 header; a sibling checkout's `.venv` works too
and skips the provisioning step):

```sh
cd mus-rs
cargo build --release -p mus-cli
uv run --script tools/parity_render.py                    # full corpus, 13 scores
uv run --script tools/parity_render.py smoke.mus bolero.mus  # a subset
uv run --script tools/parity_render.py --write-expectations  # refresh the
    # committed fast-subset fixture mus-cli/tests/ asserts against (see below)
```

`--build` folds the `cargo build --release -p mus-cli` step in. The tool
always self-tests its own comparators first (synthetic wavs with
hand-worked expected `max_abs`/`rel_rms`/dB values — see
`run_selftests` in the tool) and aborts loudly before rendering anything
if that fails; `--skip-selftest` skips it for rapid iteration.

Every run writes `mus-rs/parity/parity-report.json`
(`mus.audio.parity-report.v1`) — per-score `{score, n_samples_py,
n_samples_rs, channels_py, channels_rs, sample_rate_py, sample_rate_rs,
max_abs, rel_rms, rms_delta_db, length_match, channels_match,
sample_rate_match, receipt_match, transforms_used, vocode_touching,
bound_rel_rms, verdict, reasons, python: {...}, rust: {...}}` plus a
`summary` block (counts by verdict, the worst offenders by `rel_rms`).
The report is written **before** the process can exit on any path — a
diverging or errored score never prevents the rest of the corpus from
being attempted, or the report from being written.

`max_abs`/`rel_rms`/`rms_delta_db` are gated on all three structural
checks (`sample_rate_match`, `length_match`, `channels_match`) passing —
not just frame count. `always_2d=True` gives a mono file shape `(N, 1)`
and a stereo file `(N, 2)`; numpy silently broadcasts `(N, 1) - (N, 2)`
into `(N, 2)` rather than raising, so a bare frame-count check would let
a mono/stereo mismatch compute (and report) a bogus numeric verdict. Any
of the three failing skips all three numeric metrics entirely, and is
recorded as its own reason in `reasons` (`"sample rate mismatch: ..."`,
`"length mismatch: ..."`, `"channel count mismatch: ..."`).

Exit code is 0 iff every attempted score's verdict is `"ok"`.

## Bounds

| transform set | bound (`rel_rms`) |
|---|---|
| avoids the vocode family | ≤ `1e-3` (`STRICT_REL_RMS`) |
| touches the vocode family | ≤ `3e-2` (`VOCODE_REL_RMS`), **provisional** |

A score's transform set is determined by grepping its params (not
re-simulating the renderer) for four markers, each mapped to a specific
loose-tier DSP path (`gen_dsp_fixtures.py`'s own `rel_rms`-tier cases, not
the tight `max_abs`-tier pure-numpy ports) — see `classify_transforms`'s
docstring in the tool for the full reasoning per marker:

- `mode=vocoder` — chord/transposition takes the phase-vocoder branch.
- `glow=` — `glow_chain` vocodes internally for `gharm`/`gwarble`.
- `gest=` **together with** `gsrc=raw` — the tape-quotation path that can
  call the phase vocoder. A bare `gest=` *without* `gsrc=raw` (the
  pack-sample polyline path) is deliberately excluded — it's a
  reimplemented non-uniform resample, tight-tier, not a phase vocoder.
- `str=` — `stretch()` (`librosa.effects.time_stretch`).

`max_abs` and the per-channel RMS delta (dB) are always recorded but are
not gating on their own — `rel_rms` against the bound, exact-length
match, and receipt parity are what set `verdict`.

## Receipt parity

`receipt_match` gates on the fields that are exact integers on both sides
with no rounding in between: `eventCount`, `sidechainHits`, `badTokens`
(count and, subject to the caveat below, content), and `voiceCount`.
`badTokens` must additionally be *present, as a list*, on the rust
receipt — `compare_receipts` never defaults a missing field to an empty
list. Every current corpus score happens to have zero bad tokens, so a
silent `.get("badTokens", [])` default would coincidentally compare
`0 == 0` and report a clean match even when the required field never
showed up in the receipt at all; a missing or wrong-typed field is
reported as its own mismatch reason instead.
`durationSeconds`/`tuningA` are recorded (under `python`/`rust` in each
score's entry) but deliberately not gated — the only Python-side source
for them is the oracle's own console line, printed at one decimal place
(`f"{total_s:.1f}s, A={a4:.1f} Hz"`); gating on that would manufacture
false mismatches out of print rounding, not real divergence.

**Known caveat:** the oracle's own stderr print of `stats["bad"]` caps
the *detail* lines at 12 (`mus_audio.py`'s `stats["bad"][:12]`), though
the header always states the true total count first. Since
`parity_render.py` calls the oracle in-process, unmodified, and recovers
its stats by reading that same console output (see `render_via_python`'s
docstring — this is deliberate: the oracle stays exactly what ships), a
score with more than 12 bad tokens would compare only the printed
12-line prefix, with `badTokenListTruncated: true` recorded in the
report's `python` block for that score. None of the 13 corpus scores
currently exceed 12 (checked empirically), so this has never actually
degraded a real comparison — but it is a real boundary of the method,
not swept under the rug.

## Two assets a fresh worktree doesn't have

`aigua/v2/sweep-events.json` and `aigua/aigua_raw.wav` are derived,
gitignored (`aigua/v2/*.json`, `aigua/*.wav`), and — per `.gitignore`'s
own comment — "regenerated by the pipeline in `aigua/README.md`" rather
than versioned. A fresh `git worktree` therefore does not have them, and
four scores that declare `# gestures: v2/sweep-events.json` and/or
`# tape: aigua_raw.wav` (`aigua_1547.mus`, `aigua_1568.mus`,
`aigua_states.mus`, `motet.mus`) cannot render on **either** side without
them. None of the four are in the committed fast subset (see below) —
only the full 13-score corpus run reaches them.

`parity_render.py` preflights every score's referenced assets before
attempting to render it (`_missing_assets`) and reports a clear
`missing asset(s): ...` verdict rather than a raw `FileNotFoundError`
traceback. If you hit this: regenerate the two files via the pipeline in
`aigua/README.md`, or copy them from a checkout that already has them
(they are pure data, read-only, safe to copy across worktrees — copying
them does not touch git state on either side, since both are gitignored).

## The Rust-side fast subset

`mus-rs/crates/mus-cli/tests/parity_expectations.rs` renders `smoke.mus`
and `wf9_offline.mus` (`mus-cli/tests/fixtures/wf9_offline/`, committed)
through the **Rust engine only** and asserts the receipt against
`mus-rs/crates/mus-cli/tests/fixtures/parity_expectations.json` — a
small, committed digest snapshot (render/source digests, event/skip/
sidechain counts, per-track counts, bad tokens, voice count, duration,
tuning, peak/RMS) written by this tool's `--write-expectations` mode.
This is what lets `cargo test` catch an engine regression with no
Python/numpy/scipy/librosa involved at all.

`wf9_offline.mus` stands in for `aigua_states.mus` here on purpose:
`aigua_states.mus` needs the two gitignored assets described above, so a
fast-subset test that rendered it directly would only pass for a
developer who'd manually copied those files into their worktree — the
opposite of what a `cargo test`-only regression net is for. The fixture
exercises the same two feature families (`gest=` gesture-quotation
pack-sample polyline, tape-style `off=`/`gate`/`lpf=` sample playback)
against its own small assets (a synthetic ~1s WAV, a hand-authored
`v2/sweep-events.json`), and was itself cross-checked against the Python
oracle (`max_abs` ~2e-7) before its expectation digest was frozen — real
parity, not just a Rust snapshot. `aigua_states.mus` stays covered by the
full 13-score corpus run below, gated on its two assets like the rest of
the corpus. `clean_checkout_copy_renders_the_fast_subset`
(`parity_expectations.rs`) is the literal proof: it copies only the
git-tracked fast-subset inputs into a bare temp directory and renders
from there, so a hidden dependency on anything else — `aigua/v2/`
included — would fail it even on a worktree that happens to have those
files lying around.

`--write-expectations` refuses to write if either fast-subset score
isn't verdict `"ok"` against the live oracle first — it will not freeze
a baseline it already knows diverges. Regenerate after any change that
legitimately moves the Rust engine's output (and re-verify parity holds
before trusting the new baseline):

```sh
cd mus-rs
cargo build --release -p mus-cli
uv run --script tools/parity_render.py --write-expectations
```

## Self-tests

`parity_render.py`'s own comparator math (`compute_metrics`,
`classify_transforms`, `compare_receipts`, `_parse_bad_tokens`) is
self-tested with hand-worked synthetic cases — see `run_selftests` in
the tool. Every expected value is worked by hand from the test arrays'
own construction parameters, never by round-tripping through the
function under test (the lesson `mus-engine/src/lib.rs`'s `f32_to_pcm24`
doc comment names from a previous, rejected attempt: a self-test that
compares a function's output to itself proves nothing). Runs
automatically before every corpus render; `--skip-selftest` opts out.
