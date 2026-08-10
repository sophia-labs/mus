//! `mus service` — the warm render engine as a local process.
//!
//! The Playable Graph's S1 seam (`SPECS/playable/README.md`): a host (the
//! Atril vite dev server, a test harness, any tool) spawns this once and
//! speaks line-delimited JSON-RPC over stdin/stdout. The engine stays hot —
//! parsed graphs, decoded packs, and rendered PCM are cached in-process —
//! so audition requests land in milliseconds instead of process-spawn
//! seconds. Stdout is protocol-pure (one JSON object per line); every
//! diagnostic goes to stderr.
//!
//! Protocol v0 (this file, the keystone): `ping`, `load`, `renderScore`.
//! PW1 extends it with `renderWindow`/`renderEvent`/`renderDiff`/`peaks`
//! and the cache/GC discipline — see `SPECS/playable/PW1-service.md` for
//! the window-exactness law (`window(a,b) == full[a..b]`, bit-exact) that
//! governs every extension.
//!
//! Determinism is the contract that makes this service honest: the same
//! `docKey` always yields byte-identical PCM (the engine is sample-exact
//! and content-keyed), so caching is not an optimization heuristic — it is
//! memoization of a pure function.
//!
//! PCM transfer: responses carry an absolute path to a raw file the
//! service owns — interleaved stereo f32le at the engine rate — plus its
//! frame count. Callers stream the bytes; the service garbage-collects its
//! own tmpdir (v0: everything lives until exit; PW1 adds the LRU budget).
//! Base64-in-JSON was rejected up front: a 33% tax on every audition, paid
//! at the latency-critical edge, for no gain over a loopback file read.

use std::collections::HashMap;
use std::io::{BufRead, Write};
use std::path::PathBuf;
use std::time::Instant;

use mus_engine::{render, sha256_bytes, ENGINE_VERSION};
use serde::Serialize;
use serde_json::{json, Value};

pub const SERVICE_VERSION: &str = "mus-service/0.1.0";

struct LoadedDoc {
    source: String,
    base_dir: PathBuf,
}

struct RenderedEntry {
    pcm_path: PathBuf,
    frames: usize,
    sample_rate: u32,
    peak_dbfs: f32,
    rms_dbfs: f32,
    render_digest: String,
    render_ms: u128,
    event_count: u32,
    skipped_count: u32,
    bad_tokens: Vec<String>,
    warnings: Vec<String>,
    duration_seconds: f64,
}

#[derive(Serialize)]
struct ErrorBody {
    code: &'static str,
    message: String,
}

struct Service {
    docs: HashMap<String, LoadedDoc>,
    renders: HashMap<String, RenderedEntry>,
    tmp_dir: PathBuf,
}

impl Service {
    fn new() -> Result<Self, String> {
        let tmp_dir = std::env::temp_dir().join(format!("mus-service-{}", std::process::id()));
        std::fs::create_dir_all(&tmp_dir)
            .map_err(|e| format!("create tmpdir {}: {e}", tmp_dir.display()))?;
        Ok(Service {
            docs: HashMap::new(),
            renders: HashMap::new(),
            tmp_dir,
        })
    }

    fn handle(&mut self, method: &str, params: &Value) -> Result<Value, ErrorBody> {
        match method {
            "ping" => Ok(json!({
                "ok": true,
                "service": SERVICE_VERSION,
                "engine": ENGINE_VERSION,
                // Announced so hosts can validate that any pcmPath they
                // are asked to stream lives inside the service's own
                // tmpdir — never stream arbitrary filesystem paths.
                "tmpDir": self.tmp_dir.to_string_lossy(),
            })),
            "load" => self.load(params),
            "renderScore" => self.render_score(params),
            other => Err(ErrorBody {
                code: "unknown-method",
                message: format!("no method {other:?} (protocol v0: ping, load, renderScore)"),
            }),
        }
    }

    /// `load {source, baseDir}` → parse + adopt once, cache under the
    /// content-addressed `docKey`. Loading is cheap and idempotent — the
    /// key IS the identity, so re-loading identical content is a no-op
    /// that returns the same key.
    fn load(&mut self, params: &Value) -> Result<Value, ErrorBody> {
        let source = params["source"].as_str().ok_or_else(|| ErrorBody {
            code: "bad-request",
            message: "load: params.source (string) is required".into(),
        })?;
        let base_dir = params["baseDir"].as_str().ok_or_else(|| ErrorBody {
            code: "bad-request",
            message: "load: params.baseDir (string) is required".into(),
        })?;

        let doc_key = sha256_bytes(format!("{source}\u{0}{base_dir}").as_bytes());
        // Parse eagerly so a refused score surfaces at `load`, not as a
        // surprise at first render. Refusal is a result: the diagnostics
        // travel in the response verbatim, structured.
        let (_proposal, diags) = mus_text::parse_score_lossy(source);
        let parse_diagnostics = serde_json::to_value(&diags).unwrap_or(Value::Null);

        self.docs.insert(
            doc_key.clone(),
            LoadedDoc {
                source: source.to_string(),
                base_dir: PathBuf::from(base_dir),
            },
        );
        Ok(json!({
            "docKey": doc_key,
            "engine": ENGINE_VERSION,
            "parseDiagnostics": parse_diagnostics,
        }))
    }

    /// `renderScore {docKey}` → the full piece through the whole pipeline,
    /// memoized. First call renders and writes `<docKey>.f32`; every later
    /// call returns the cached entry instantly.
    fn render_score(&mut self, params: &Value) -> Result<Value, ErrorBody> {
        let doc_key = params["docKey"].as_str().ok_or_else(|| ErrorBody {
            code: "bad-request",
            message: "renderScore: params.docKey (string) is required".into(),
        })?;
        if !self.renders.contains_key(doc_key) {
            let doc = self.docs.get(doc_key).ok_or_else(|| ErrorBody {
                code: "unknown-doc",
                message: format!("renderScore: no loaded doc {doc_key:?} — call load first"),
            })?;
            let started = Instant::now();
            let outcome = render(&doc.source, &doc.base_dir).map_err(|e| ErrorBody {
                code: "render-failed",
                message: e.to_string(),
            })?;
            let render_ms = started.elapsed().as_millis();

            let pcm_path = self.tmp_dir.join(format!("{doc_key}.f32"));
            let mut bytes = Vec::with_capacity(outcome.audio.samples.len() * 4);
            for s in &outcome.audio.samples {
                bytes.extend_from_slice(&s.to_le_bytes());
            }
            let render_digest = sha256_bytes(&bytes);
            std::fs::write(&pcm_path, &bytes).map_err(|e| ErrorBody {
                code: "render-failed",
                message: format!("write {}: {e}", pcm_path.display()),
            })?;

            let entry = RenderedEntry {
                frames: outcome.audio.frames(),
                sample_rate: outcome.audio.sample_rate,
                peak_dbfs: outcome.audio.peak_dbfs(),
                rms_dbfs: outcome.audio.rms_dbfs(),
                render_digest,
                render_ms,
                event_count: outcome.stats.notes,
                skipped_count: outcome.stats.skipped,
                bad_tokens: outcome.stats.bad.clone(),
                warnings: outcome.stats.warnings.clone(),
                duration_seconds: outcome.stats.total_seconds,
                pcm_path,
            };
            self.renders.insert(doc_key.to_string(), entry);
        }
        let e = &self.renders[doc_key];
        Ok(json!({
            "pcmPath": e.pcm_path.to_string_lossy(),
            "frames": e.frames,
            "channels": 2,
            "sampleRate": e.sample_rate,
            "layout": "interleaved-f32le",
            "peakDbfs": e.peak_dbfs,
            "rmsDbfs": e.rms_dbfs,
            "renderDigest": e.render_digest,
            "renderMs": e.render_ms,
            "eventCount": e.event_count,
            "skippedCount": e.skipped_count,
            "badTokens": e.bad_tokens,
            "warnings": e.warnings,
            "durationSeconds": e.duration_seconds,
        }))
    }
}

/// The NDJSON loop. Malformed lines get an `id: null` error response
/// rather than killing the process — a confused client deserves an
/// answer, not a dead engine.
pub fn run_service() -> Result<(), String> {
    let mut service = Service::new()?;
    eprintln!(
        "[mus-service] up: {} / {} (tmp {})",
        SERVICE_VERSION,
        ENGINE_VERSION,
        service.tmp_dir.display()
    );
    let stdin = std::io::stdin();
    let stdout = std::io::stdout();
    let mut out = stdout.lock();
    for line in stdin.lock().lines() {
        let line = line.map_err(|e| format!("stdin: {e}"))?;
        if line.trim().is_empty() {
            continue;
        }
        let response = match serde_json::from_str::<Value>(&line) {
            Ok(request) => {
                let id = request["id"].clone();
                let method = request["method"].as_str().unwrap_or("");
                match service.handle(method, &request["params"]) {
                    Ok(result) => json!({ "id": id, "result": result }),
                    Err(err) => json!({ "id": id, "error": err }),
                }
            }
            Err(e) => json!({
                "id": Value::Null,
                "error": ErrorBody { code: "bad-request", message: format!("unparseable request line: {e}") },
            }),
        };
        serde_json::to_writer(&mut out, &response).map_err(|e| format!("stdout: {e}"))?;
        out.write_all(b"\n").map_err(|e| format!("stdout: {e}"))?;
        out.flush().map_err(|e| format!("stdout: {e}"))?;
    }
    Ok(())
}
