//! `vocab` + `renderWeaveProbe` service methods: registry dump matches the
//! crate digest; a probe returns mono PCM plus a telemetry file whose
//! shape matches its own metadata; identical probes memoize to identical
//! entries; a non-string-network synth is a typed refusal.

use std::io::{BufRead, BufReader, Write};
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

#[test]
fn vocab_and_weave_probe_protocol() {
    let mut service = ServiceHandle::spawn();

    let ping = service.call(1, "ping", serde_json::json!({}));
    let tmp_dir = ping["result"]["tmpDir"]
        .as_str()
        .expect("tmpDir")
        .to_string();

    // The service's vocabulary IS the CLI registry — same digest.
    let vocab = service.call(2, "vocab", serde_json::json!({}));
    assert_eq!(vocab["result"]["schema"], serde_json::json!("mus.vocab.v1"));
    assert_eq!(
        vocab["result"]["digest"].as_str().expect("digest"),
        mus_vocab::vocab_digest()
    );

    let probe_params = serde_json::json!({
        "params": {"synth": "weave", "courses": 9, "couple": 0.16, "chirality": 0.7,
                   "body": 0.5, "sus": 1.2},
        "midis": [45, 52, 57],
        "slotSeconds": 0.6,
    });
    let first = service.call(3, "renderWeaveProbe", probe_params.clone());
    let result = &first["result"];
    assert!(result["probeKey"].is_string(), "{first}");

    let pcm_path = result["pcm"]["path"].as_str().expect("pcm path");
    assert!(
        pcm_path.starts_with(&tmp_dir),
        "pcm inside announced tmpdir"
    );
    let pcm_frames = result["pcm"]["frames"].as_u64().expect("frames") as usize;
    assert_eq!(result["pcm"]["channels"], serde_json::json!(1));
    let pcm_bytes = std::fs::read(pcm_path).expect("pcm file");
    assert_eq!(pcm_bytes.len(), pcm_frames * 4, "mono f32le sizing");

    let trace = &result["trace"];
    let courses = trace["courses"].as_u64().expect("courses") as usize;
    let frames = trace["frames"].as_u64().expect("trace frames") as usize;
    let stride = trace["stride"].as_u64().expect("stride") as usize;
    assert_eq!(courses, 9, "courses target honored");
    assert_eq!(trace["played"], serde_json::json!(3));
    assert_eq!(frames, pcm_frames.div_ceil(stride));
    assert_eq!(
        trace["courseFreqs"].as_array().expect("freqs").len(),
        courses
    );
    let trace_path = trace["path"].as_str().expect("trace path");
    assert!(trace_path.starts_with(&tmp_dir), "trace inside tmpdir");
    let trace_bytes = std::fs::read(trace_path).expect("trace file");
    assert_eq!(
        trace_bytes.len(),
        frames * (2 * courses + 1) * 4,
        "frame-major sizing matches metadata"
    );

    // Memoization: the identical request returns the identical entry.
    let second = service.call(4, "renderWeaveProbe", probe_params);
    assert_eq!(first["result"], second["result"]);

    // A non-string-network synth refuses with a typed code.
    let refusal = service.call(
        5,
        "renderWeaveProbe",
        serde_json::json!({"params": {"synth": "saw"}, "midis": [60]}),
    );
    assert_eq!(
        refusal["error"]["code"],
        serde_json::json!("unsupported-synth")
    );
}
