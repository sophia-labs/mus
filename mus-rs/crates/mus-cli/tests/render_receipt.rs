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
