//! WF9 fast-subset regression test: asserts the Rust engine's render
//! receipt for the fast subset against digests committed by
//! `mus-rs/tools/parity_render.py --write-expectations` — so `cargo test`
//! catches an engine regression without needing Python/numpy/scipy/
//! librosa at all (WF9-corpus-parity.md point 3).
//!
//! The fast subset is `smoke.mus` (the real corpus score, under `aigua/`)
//! and `wf9_offline.mus` (`tests/fixtures/wf9_offline/`, owned by this
//! crate) — NOT the real `aigua/aigua_states.mus`. That score's `#
//! gestures:` header and its `tp` instrument's `sample=` both point at
//! files that are gitignored and absent from a clean checkout
//! (`aigua/v2/sweep-events.json`, `aigua/aigua_raw.wav` — see
//! `mus-rs/parity/README.md`'s "Two assets a fresh worktree doesn't
//! have"), so a test that rendered `aigua_states.mus` directly only ever
//! passed when a developer had manually copied those two files in —
//! exactly the gap this file closes. `wf9_offline.mus` exercises the same
//! two feature families `aigua_states.mus` would have covered here —
//! `gest=` gesture-quotation (the pack-sample polyline path,
//! SPEC-AUDIO.md §8) and tape-style `off=`/`gate`/`lpf=` sample playback
//! (§4/§7) — against committed, self-contained assets, cross-checked
//! against the Python oracle at `max_abs` ~2e-7 before being frozen (see
//! `mus-rs/tools/parity_render.py`'s `WF9_OFFLINE_FIXTURE`). The real
//! `aigua_states.mus` stays covered by the full 13-score corpus report
//! (`uv run --script mus-rs/tools/parity_render.py`), gated on those two
//! assets exactly like the rest of the corpus.
//!
//! `clean_checkout_copy_renders_the_fast_subset` below is the literal
//! proof that the fast subset needs nothing beyond what git ships: it
//! stages only the git-tracked fast-subset inputs into a bare temp
//! directory (no `aigua/v2/`, no `aigua/aigua_raw.wav`, nothing else this
//! worktree might happen to have lying around) and renders both scores
//! from that isolated copy. The two tests above run against the real
//! checkout in place, which could mask a hidden missing-asset dependency
//! on a machine that happens to already have one lying around; this one
//! can't.
//!
//! Regenerate the fixture (only after confirming full parity — the tool
//! itself refuses to freeze a diverging baseline):
//!   uv run --script mus-rs/tools/parity_render.py --build --write-expectations

use std::path::{Path, PathBuf};
use std::process::Command;

/// Mirrors `mus-dsp/src/fixtures.rs`'s `manifest()` convention: a runtime
/// read with a panic message that names the regeneration command, rather
/// than `include_str!` — so unrelated tests in this crate still compile
/// if the fixture is ever absent.
fn expectations() -> serde_json::Value {
    let path =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/parity_expectations.json");
    let text = std::fs::read_to_string(&path).unwrap_or_else(|e| {
        panic!(
            "read {}: {e} — run `uv run --script mus-rs/tools/parity_render.py \
             --build --write-expectations`",
            path.display()
        )
    });
    serde_json::from_str(&text).expect("parity_expectations.json parses")
}

/// The receipt fields `mus-rs/tools/parity_render.py` (WF9) freezes:
/// content digests (byte-exact WAV reproduction), the WF8 stats fields,
/// and the legacy WF1 peak/RMS pair. Deliberately excludes `wallSeconds`
/// (never deterministic) and `sourceDigest`'s sibling `logDigest` (always
/// null, not informative here).
const CHECKED_FIELDS: &[&str] = &[
    "renderDigest",
    "sourceDigest",
    "eventCount",
    "skippedCount",
    "sidechainHits",
    "perTrackEvents",
    "badTokens",
    "voiceCount",
    "durationSeconds",
    "tuningA",
    "peakDbfs",
    "rmsDbfs",
    "engineVersion",
];

fn aigua_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../aigua")
}

fn wf9_offline_fixture_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/wf9_offline")
}

/// Renders `score` with `mus-cli` (resolving `pack`/`gestures`/`tape`/
/// `sample=` references against `score`'s own parent directory, exactly
/// as `mus render` does with no `--base` override) and asserts every
/// `CHECKED_FIELDS` entry of the resulting receipt against
/// `expectations["scores"][expected_key]`.
fn render_and_assert(score: &Path, expected_key: &str) {
    let expectations = expectations();
    let expected = &expectations["scores"][expected_key];
    assert!(
        !expected.is_null(),
        "no committed expectation for {expected_key:?} in parity_expectations.json — \
         run --write-expectations"
    );

    let dir = std::env::temp_dir().join(format!(
        "mus-wf9-parity-{}-{}-{}",
        expected_key.replace('.', "_"),
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&dir).unwrap();
    let output = dir.join("out.wav");

    let result = Command::new(env!("CARGO_BIN_EXE_mus"))
        .args(["render", score.to_str().unwrap(), "-o"])
        .arg(&output)
        .arg("--json")
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    let receipt: serde_json::Value = serde_json::from_slice(&result.stdout).unwrap();

    for field in CHECKED_FIELDS {
        let got = receipt.get(*field);
        let want = expected.get(*field);
        assert_eq!(
            got,
            want,
            "{expected_key}: field {field:?} regressed from the committed expectation\n  \
             got:      {}\n  expected: {}",
            got.map(|v| v.to_string())
                .unwrap_or_else(|| "<missing>".into()),
            want.map(|v| v.to_string())
                .unwrap_or_else(|| "<missing>".into()),
        );
    }

    std::fs::remove_dir_all(&dir).unwrap();
}

#[test]
fn smoke_matches_committed_expectation() {
    render_and_assert(&aigua_dir().join("smoke.mus"), "smoke.mus");
}

/// `aigua_states.mus`'s self-contained replacement in the always-green
/// fast subset — see this file's top doc comment for why.
#[test]
fn wf9_offline_matches_committed_expectation() {
    render_and_assert(
        &wf9_offline_fixture_dir().join("wf9_offline.mus"),
        "wf9_offline.mus",
    );
}

fn copy_file(from: &Path, to: &Path) {
    std::fs::copy(from, to)
        .unwrap_or_else(|e| panic!("copy {} -> {}: {e}", from.display(), to.display()));
}

/// Copies every regular file directly inside `from` into `to` (both must
/// already exist) — `aigua/samples/` is flat, so this is all `smoke.mus`'s
/// pack needs, without hand-tracing which `s=<N>` sample indices the
/// score's notes actually pick.
fn copy_dir_flat(from: &Path, to: &Path) {
    for entry in std::fs::read_dir(from).unwrap() {
        let entry = entry.unwrap();
        if entry.file_type().unwrap().is_file() {
            copy_file(&entry.path(), &to.join(entry.file_name()));
        }
    }
}

/// The clean-checkout proof: stage only the git-tracked fast-subset
/// inputs into a bare temp directory, then render both scores from that
/// isolated copy. See this file's top doc comment.
#[test]
fn clean_checkout_copy_renders_the_fast_subset() {
    let staging = std::env::temp_dir().join(format!(
        "mus-wf9-clean-checkout-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));

    // smoke.mus's world: the score, its pack manifest, and every packed
    // sample — nothing from `aigua/v2/` or `aigua/aigua_raw.wav`.
    let smoke_dir = staging.join("aigua");
    std::fs::create_dir_all(smoke_dir.join("samples")).unwrap();
    let aigua = aigua_dir();
    copy_file(&aigua.join("smoke.mus"), &smoke_dir.join("smoke.mus"));
    copy_file(
        &aigua.join("instrument.json"),
        &smoke_dir.join("instrument.json"),
    );
    copy_dir_flat(&aigua.join("samples"), &smoke_dir.join("samples"));

    // wf9_offline.mus's world: its own fixture directory, verbatim.
    let fixture_dir = staging.join("wf9_offline");
    std::fs::create_dir_all(fixture_dir.join("v2")).unwrap();
    let src = wf9_offline_fixture_dir();
    copy_file(
        &src.join("wf9_offline.mus"),
        &fixture_dir.join("wf9_offline.mus"),
    );
    copy_file(&src.join("bird.wav"), &fixture_dir.join("bird.wav"));
    copy_file(
        &src.join("v2/sweep-events.json"),
        &fixture_dir.join("v2/sweep-events.json"),
    );

    render_and_assert(&smoke_dir.join("smoke.mus"), "smoke.mus");
    render_and_assert(&fixture_dir.join("wf9_offline.mus"), "wf9_offline.mus");

    std::fs::remove_dir_all(&staging).unwrap();
}
