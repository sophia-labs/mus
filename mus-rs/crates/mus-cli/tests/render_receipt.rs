use std::path::PathBuf;
use std::process::Command;

#[test]
fn render_receipt_names_schema_and_content_digests() {
    let score = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../aigua/smoke.mus");
    let root = std::env::temp_dir().join(format!("mus-wf1-receipt-{}", std::process::id()));
    let output = root.with_extension("wav");
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
    assert_eq!(receipt["schema"], "mus.audio.render-receipt.v1");
    assert_eq!(receipt["headSelection"], "sole");
    assert!(receipt["renderDigest"]
        .as_str()
        .unwrap()
        .starts_with("sha256:"));
    assert!(receipt["sourceDigest"]
        .as_str()
        .unwrap()
        .starts_with("sha256:"));
    assert!(receipt["logDigest"].is_null());
    assert!(receipt["wallSeconds"].as_f64().unwrap() >= 0.0);
    std::fs::remove_file(output).unwrap();
}

/// The WF8 receipt fields `mus-rs/tools/parity_render.py` (WF9) diffs
/// first: event/skip counts, per-track counts, the bad-token list, and
/// the sidechain hit count. `render_receipt_names_schema_and_content_
/// digests` (above) only exercises the legacy WF1 fields on a score with
/// none of these — zero bad tokens, no sidechain, uniform per-track
/// counts — so it can't tell an exact count from an off-by-one, nor a
/// present-but-empty list from a genuinely-populated one. This fixture
/// deliberately exercises all five at once, with counts small enough to
/// verify by hand from the score text:
///
/// - `kk` (sidechain trigger): 4 synth notes, one per beat.
/// - `sb`: 2 valid notes either side of one deliberately unparseable
///   token (`notatoken`), which must land in `badTokens` and must not
///   advance the beat position (matching `parse_token` returning `None`
///   before the oracle's own `q_off += ev.ql`).
/// - `ss`: a real (10-sample) `sample=` source, under the 32-sample
///   floor, so its one note is a `skippedCount` hit and never reaches
///   `perTrackEvents` at all.
#[test]
fn render_receipt_reports_exact_wf8_event_skip_sidechain_per_track_and_bad_token_fields() {
    let dir = std::env::temp_dir().join(format!(
        "mus-wf8-receipt-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&dir).unwrap();
    write_tiny_wav(&dir.join("tiny.wav"), &[0i16; 10]);

    let score = "# score: WF8 receipt fixture\n\
# tempo: 120\n\
# time: 4/4\n\
# bars: 1\n\
# sidechain: kk depth=0.5 rel=0.1\n\
# instruments:\n\
#   kk = kick (perc, synth=sine)\n\
#   sb = sub (bass, synth=sine)\n\
#   ss = shorty (perc, sample=tiny.wav)\n\
\n\
bar 1: kk=A2q A2q A2q A2q  sb=A1h notatoken A1h  ss=A4q\n";
    let score_path = dir.join("score.mus");
    std::fs::write(&score_path, score).unwrap();
    let output = dir.join("out.wav");

    let result = Command::new(env!("CARGO_BIN_EXE_mus"))
        .args(["render", score_path.to_str().unwrap(), "-o"])
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

    assert_eq!(receipt["eventCount"], 6, "{receipt}");
    assert_eq!(receipt["skippedCount"], 1, "{receipt}");
    assert_eq!(receipt["sidechainHits"], 4, "{receipt}");
    assert_eq!(
        receipt["warnings"].as_array().unwrap().len(),
        0,
        "{receipt}"
    );

    let per_track = receipt["perTrackEvents"].as_object().unwrap();
    assert_eq!(per_track.len(), 2, "{per_track:?}");
    assert_eq!(per_track["kk"], 4);
    assert_eq!(per_track["sb"], 2);
    assert!(
        !per_track.contains_key("ss"),
        "a skipped (too-short) note must never reach perTrackEvents: {per_track:?}"
    );

    let bad = receipt["badTokens"].as_array().unwrap();
    assert_eq!(bad.len(), 1, "{bad:?}");
    let bad0 = bad[0].as_str().unwrap();
    assert!(bad0.contains("notatoken") && bad0.contains("sb"), "{bad0}");

    std::fs::remove_file(&output).unwrap();
    std::fs::remove_dir_all(&dir).unwrap();
}

/// A minimal mono 16-bit PCM WAV, written by hand (no extra crate
/// dependency) purely to give `mus_dsp::pitch::load_decode` a real,
/// deliberately-under-32-sample source file.
fn write_tiny_wav(path: &std::path::Path, samples: &[i16]) {
    let data_bytes = samples.len() * 2;
    let mut buf = Vec::with_capacity(44 + data_bytes);
    buf.extend_from_slice(b"RIFF");
    buf.extend_from_slice(&((36 + data_bytes) as u32).to_le_bytes());
    buf.extend_from_slice(b"WAVE");
    buf.extend_from_slice(b"fmt ");
    buf.extend_from_slice(&16u32.to_le_bytes()); // PCM subchunk size
    buf.extend_from_slice(&1u16.to_le_bytes()); // audio format: PCM
    buf.extend_from_slice(&1u16.to_le_bytes()); // channels: mono
    buf.extend_from_slice(&48_000u32.to_le_bytes()); // sample rate (== SR: no resample)
    buf.extend_from_slice(&(48_000u32 * 2).to_le_bytes()); // byte rate
    buf.extend_from_slice(&2u16.to_le_bytes()); // block align
    buf.extend_from_slice(&16u16.to_le_bytes()); // bits per sample
    buf.extend_from_slice(b"data");
    buf.extend_from_slice(&(data_bytes as u32).to_le_bytes());
    for &s in samples {
        buf.extend_from_slice(&s.to_le_bytes());
    }
    std::fs::write(path, buf).unwrap();
}
