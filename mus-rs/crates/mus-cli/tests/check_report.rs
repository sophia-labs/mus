use serde_json::Value;
use std::path::{Path, PathBuf};
use std::process::Command;

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../")
}

#[test]
fn check_verb_emits_report_and_documents_atril_swap() {
    let root = root();
    let score = root.join("aigua/smoke.mus");
    let output = Command::new(env!("CARGO_BIN_EXE_mus"))
        .args(["check", score.to_str().unwrap(), "--base"])
        .arg(root.join("aigua"))
        .arg("--json")
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["schema"], "mus.audio.check-report.v1");
    assert_eq!(report["score"]["title"], "Aigua — renderer smoke test");
    assert_eq!(report["score"]["bars"], 8);
    assert_eq!(report["score"]["tuningA"], 445.6);
    assert_eq!(report["events"].as_array().unwrap().len(), 46);
    assert!(report["diagnostics"].as_array().unwrap().is_empty());
    assert!(report["extensionUsage"].is_object());

    let help = Command::new(env!("CARGO_BIN_EXE_mus"))
        .arg("--help")
        .output()
        .unwrap();
    let help = String::from_utf8(help.stdout).unwrap();
    assert!(help
        .contains("MUS_CHECK_CMD=\"/Users/vera/dev/sophia/mus/mus-rs/target/release/mus check\""));
}

#[test]
fn parity_check_corpus() {
    let root = root();
    let corpus = [
        "aigua.mus",
        "aigua_1547.mus",
        "aigua_1568.mus",
        "aigua_chorale.mus",
        "aigua_dub.mus",
        "aigua_gecs.mus",
        "aigua_gliss.mus",
        "aigua_pop.mus",
        "aigua_states.mus",
        "bolero.mus",
        "cadiz.mus",
        "motet.mus",
        "smoke.mus",
    ];
    let base = root.join("aigua");
    let mut python_reports = Vec::new();
    for name in corpus {
        let score = base.join(name);
        let rust = Command::new(env!("CARGO_BIN_EXE_mus"))
            .args(["check", score.to_str().unwrap(), "--base"])
            .arg(&base)
            .arg("--json")
            .output()
            .unwrap();
        assert!(
            rust.status.success(),
            "Rust check failed for {name}: {}",
            String::from_utf8_lossy(&rust.stderr)
        );
        let rust: Value = serde_json::from_slice(&rust.stdout).unwrap();

        let python = run_python_checker(&root, &score, &base)
            .unwrap_or_else(|detail| panic!("Python checker failed for {name}: {detail}"));
        assert_report_parity(&python, &rust, name);
        python_reports.push(name);
    }
    assert_eq!(python_reports.len(), 13);
}

fn run_python_checker(root: &PathBuf, score: &PathBuf, base: &PathBuf) -> Result<Value, String> {
    let uv = Command::new("uv")
        .current_dir(root.join("mus-rs"))
        .args([
            "run",
            "--script",
            // `mus_audio.py`'s own PEP 723 header declares only a floor
            // (`requires-python = ">=3.10"`), not the ceiling its pinned
            // `numba<0.61` actually needs — unpinned, `uv` is free to
            // resolve the newest interpreter it can find, and numba 0.60
            // fails to build past 3.12 ("Cannot install on Python version
            // 3.14.4; only versions >=3.9,<3.13 are supported"). Pinning
            // here rather than editing the oracle's own header: WF9-corpus-
            // parity.md's whole premise is that `mus_audio.py` stays
            // exactly what ships.
            "--python",
            "3.12",
            "../mus_audio.py",
            score.to_str().unwrap(),
            "--check",
            "--base",
        ])
        .arg(base)
        .output()
        .map_err(|error| format!("could not execute uv: {error}"))?;
    if uv.status.success() {
        return serde_json::from_slice(&uv.stdout)
            .map_err(|error| format!("uv emitted invalid JSON: {error}\n{}", lossy(&uv.stdout)));
    }

    let uv_detail = format!("status={}\n{}", uv.status, lossy(&uv.stderr));
    // The repository's gate runs in sandboxes where uv may be unable to
    // initialize its user cache or fetch its declared audio dependencies.
    // The fallback still imports and executes mus_audio.py::check_score; it
    // stubs only render-time modules that check_score never touches. A real
    // uv failure outside this known offline/cache condition remains fatal.
    let offline = uv_detail.contains("Failed to initialize cache")
        || uv_detail.contains("Failed to fetch")
        || uv_detail.contains("Operation not permitted");
    if !offline {
        return Err(format!("uv checker failed:\n{uv_detail}"));
    }
    let direct = Command::new("python3")
        .current_dir(root.join("mus-rs"))
        .args([
            "-c",
            PYTHON_CHECK_SHIM,
            score.to_str().unwrap(),
            base.to_str().unwrap(),
        ])
        .output()
        .map_err(|error| format!("uv failed:\n{uv_detail}\npython3 fallback: {error}"))?;
    if !direct.status.success() {
        return Err(format!(
            "uv failed:\n{uv_detail}\npython3 fallback failed ({}):\n{}",
            direct.status,
            lossy(&direct.stderr)
        ));
    }
    serde_json::from_slice(&direct.stdout).map_err(|error| {
        format!(
            "uv failed:\n{uv_detail}\npython3 fallback emitted invalid JSON: {error}\n{}",
            lossy(&direct.stdout)
        )
    })
}

fn lossy(bytes: &[u8]) -> String {
    String::from_utf8_lossy(bytes).trim().to_string()
}

const PYTHON_CHECK_SHIM: &str = r#"
import json
import runpy
import sys
import types
from pathlib import Path

for name in ("numpy", "soundfile", "librosa"):
    sys.modules[name] = types.ModuleType(name)
scipy = types.ModuleType("scipy")
scipy.signal = types.ModuleType("scipy.signal")
sys.modules["scipy"] = scipy
sys.modules["scipy.signal"] = scipy.signal
music21 = types.ModuleType("music21")
parts = ("converter", "stream", "note", "chord", "meter", "key", "tempo",
         "dynamics", "expressions", "spanner", "pitch", "duration",
         "articulations", "clef", "instrument", "metadata", "tie")
for name in parts:
    part = types.ModuleType("music21." + name)
    setattr(music21, name, part)
    sys.modules["music21." + name] = part
class Duration:
    def __init__(self, quarter_length):
        self.quarterLength = quarter_length
music21.duration.Duration = Duration
sys.modules["music21"] = music21

score = Path(sys.argv[1]).resolve()
root = score.parent.parent
sys.path.insert(0, str(root))
namespace = runpy.run_path(str(root / "mus_audio.py"))
report = namespace["check_score"](score, Path(sys.argv[2]).resolve())
print(json.dumps(report))
"#;

fn assert_report_parity(expected: &Value, actual: &Value, score: &str) {
    let mut mismatches = Vec::new();
    compare_report(expected, actual, "$", &mut mismatches);
    if !mismatches.is_empty() {
        panic!(
            "parity mismatch for {score} ({} difference{}):\n{}",
            mismatches.len(),
            if mismatches.len() == 1 { "" } else { "s" },
            mismatches.join("\n")
        );
    }
}

fn compare_report(expected: &Value, actual: &Value, path: &str, mismatches: &mut Vec<String>) {
    // Keep a failure reviewable even when a broken report has many cascading
    // differences. The first eight paths are enough to identify the delta;
    // the event array is still compared element-for-element below.
    if mismatches.len() >= 8 {
        return;
    }
    match (expected, actual) {
        (Value::Number(a), Value::Number(b)) => {
            let a = a.as_f64().unwrap();
            let b = b.as_f64().unwrap();
            let tolerance = 1e-6 * a.abs().max(b.abs());
            if (a - b).abs() > tolerance {
                mismatches.push(format!(
                    "{path}: expected {a:?}, actual {b:?} (delta {}, relative tolerance {})",
                    (a - b).abs(),
                    tolerance
                ));
            }
        }
        (Value::Object(expected), Value::Object(actual)) => {
            let root = path == "$";
            for (key, expected_value) in expected {
                if root && (key == "producer" || key == "rendererVersion") {
                    continue;
                }
                let Some(actual_value) = actual.get(key) else {
                    mismatches.push(format!("{path}.{key}: missing from Rust report"));
                    continue;
                };
                compare_report(
                    expected_value,
                    actual_value,
                    &format!("{path}.{key}"),
                    mismatches,
                );
            }
            for key in actual.keys() {
                if (root && (key == "producer" || key == "rendererVersion"))
                    || (root && key == "extensionUsage")
                {
                    continue;
                }
                if !expected.contains_key(key) {
                    mismatches.push(format!("{path}.{key}: unexpected Rust report field"));
                }
            }
        }
        (Value::Array(expected), Value::Array(actual)) => {
            let mut expected = expected.clone();
            let mut actual = actual.clone();
            if path == "$.declaredObjects" {
                expected.sort_by_key(stable_json_key);
                actual.sort_by_key(stable_json_key);
            }
            if expected.len() != actual.len() {
                mismatches.push(format!(
                    "{path}: expected {} elements, actual {}",
                    expected.len(),
                    actual.len()
                ));
                return;
            }
            for (index, (expected, actual)) in expected.iter().zip(actual.iter()).enumerate() {
                compare_report(expected, actual, &format!("{path}[{index}]"), mismatches);
                if mismatches.len() >= 8 {
                    return;
                }
            }
        }
        (expected, actual) if expected != actual => mismatches.push(format!(
            "{path}: expected {}, actual {}",
            pretty_json(expected),
            pretty_json(actual)
        )),
        _ => {}
    }
}

fn stable_json_key(value: &Value) -> String {
    match value {
        Value::Object(map) => {
            let mut entries: Vec<_> = map.iter().collect();
            entries.sort_by(|(a, _), (b, _)| a.cmp(b));
            format!(
                "{{{}}}",
                entries
                    .into_iter()
                    .map(|(key, value)| format!("{key:?}:{}", stable_json_key(value)))
                    .collect::<Vec<_>>()
                    .join(",")
            )
        }
        Value::Array(values) => format!(
            "[{}]",
            values
                .iter()
                .map(stable_json_key)
                .collect::<Vec<_>>()
                .join(",")
        ),
        _ => serde_json::to_string(value).unwrap(),
    }
}

fn pretty_json(value: &Value) -> String {
    serde_json::to_string_pretty(value).unwrap_or_else(|_| value.to_string())
}
