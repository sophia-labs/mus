//! Protocol smoke for `mus service` v0: spawn the real binary, speak the
//! NDJSON protocol end to end, and hold it to the determinism contract —
//! the same docKey must yield the same renderDigest, and the PCM file on
//! disk must be exactly frames × channels × 4 bytes.

use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};

struct ServiceHandle {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
}

impl ServiceHandle {
    fn spawn() -> Self {
        let mut child = Command::new(env!("CARGO_BIN_EXE_mus"))
            .arg("service")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .expect("spawn mus service");
        let stdin = child.stdin.take().expect("service stdin");
        let stdout = BufReader::new(child.stdout.take().expect("service stdout"));
        ServiceHandle {
            child,
            stdin,
            stdout,
        }
    }

    fn call(&mut self, id: u64, method: &str, params: serde_json::Value) -> serde_json::Value {
        let request = serde_json::json!({ "id": id, "method": method, "params": params });
        writeln!(self.stdin, "{request}").expect("write request");
        let mut line = String::new();
        self.stdout.read_line(&mut line).expect("read response");
        let response: serde_json::Value = serde_json::from_str(&line).expect("response parses");
        assert_eq!(response["id"], serde_json::json!(id), "response id echoes");
        response
    }
}

impl Drop for ServiceHandle {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

#[test]
fn ping_load_render_roundtrip_is_deterministic() {
    let aigua = repo_root().join("aigua");
    let source = std::fs::read_to_string(aigua.join("smoke.mus")).expect("read smoke.mus");

    let mut service = ServiceHandle::spawn();

    let pong = service.call(1, "ping", serde_json::json!({}));
    assert_eq!(pong["result"]["ok"], serde_json::json!(true));
    assert!(pong["result"]["service"]
        .as_str()
        .expect("service version string")
        .starts_with("mus-service/"));

    let loaded = service.call(
        2,
        "load",
        serde_json::json!({ "source": source, "baseDir": aigua.to_string_lossy() }),
    );
    let doc_key = loaded["result"]["docKey"]
        .as_str()
        .expect("docKey string")
        .to_string();
    assert_eq!(doc_key.len(), 64, "docKey is a sha256 hex digest");

    let rendered = service.call(3, "renderScore", serde_json::json!({ "docKey": doc_key }));
    let result = &rendered["result"];
    let frames = result["frames"].as_u64().expect("frames") as usize;
    let sample_rate = result["sampleRate"].as_u64().expect("sampleRate");
    let pcm_path = PathBuf::from(result["pcmPath"].as_str().expect("pcmPath"));
    assert_eq!(sample_rate, 48_000);
    assert!(frames > 48_000, "smoke.mus renders more than a second");
    let bytes = std::fs::metadata(&pcm_path).expect("pcm file exists").len() as usize;
    assert_eq!(bytes, frames * 2 * 4, "interleaved stereo f32le sizing");

    // Determinism: the second call must be a cache hit with the identical
    // digest — memoization of a pure function, not a re-render.
    let digest_a = result["renderDigest"].as_str().expect("digest").to_string();
    let again = service.call(4, "renderScore", serde_json::json!({ "docKey": doc_key }));
    assert_eq!(
        again["result"]["renderDigest"].as_str().expect("digest"),
        digest_a
    );

    // Unknown doc is a structured refusal, not a crash.
    let missing = service.call(
        5,
        "renderScore",
        serde_json::json!({ "docKey": "feedbeef" }),
    );
    assert_eq!(missing["error"]["code"], serde_json::json!("unknown-doc"));
}
