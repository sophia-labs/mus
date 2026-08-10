mod check;

use mus_engine::{render, sha256_bytes, write_wav, RenderStats, ENGINE_VERSION};
use mus_text::{adopt, parse_score};
use serde::Serialize;
use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::path::PathBuf;
use std::time::Instant;

/// `mus.audio.render-receipt.v1`: peak/RMS/digests (the original WF1
/// surface, kept for `mus-cli/tests/render_receipt.rs`) extended per the
/// WF8 spec with the fields `mus-rs/tools/parity_render.py` (WF9) diffs
/// first — event/skip counts, per-track counts, the bad-token list, and
/// the sidechain hit count.
#[derive(Debug, Serialize)]
struct Receipt {
    schema: &'static str,
    #[serde(rename = "renderDigest")]
    render_digest: String,
    #[serde(rename = "sourceDigest")]
    source_digest: String,
    #[serde(rename = "logDigest")]
    log_digest: Option<String>,
    #[serde(rename = "headSelection")]
    head_selection: serde_json::Value,
    #[serde(rename = "engineVersion")]
    engine_version: &'static str,
    #[serde(rename = "peakDbfs")]
    peak_dbfs: f32,
    #[serde(rename = "rmsDbfs")]
    rms_dbfs: f32,
    #[serde(rename = "wallSeconds")]
    wall_seconds: f64,
    #[serde(rename = "eventCount")]
    event_count: u32,
    #[serde(rename = "skippedCount")]
    skipped_count: u32,
    #[serde(rename = "voiceCount")]
    voice_count: usize,
    #[serde(rename = "durationSeconds")]
    duration_seconds: f64,
    #[serde(rename = "tuningA")]
    tuning_a: f64,
    #[serde(rename = "sidechainHits")]
    sidechain_hits: usize,
    #[serde(rename = "perTrackEvents")]
    per_track_events: BTreeMap<String, u32>,
    #[serde(rename = "badTokens")]
    bad_tokens: Vec<String>,
    #[serde(rename = "warnings")]
    warnings: Vec<String>,
}

impl Receipt {
    fn from_stats(
        stats: &RenderStats,
        render_digest: String,
        source_digest: String,
        head_selection: serde_json::Value,
        peak_dbfs: f32,
        rms_dbfs: f32,
        wall_seconds: f64,
    ) -> Self {
        Receipt {
            schema: "mus.audio.render-receipt.v1",
            render_digest,
            source_digest,
            log_digest: None,
            head_selection,
            engine_version: ENGINE_VERSION,
            peak_dbfs,
            rms_dbfs,
            wall_seconds,
            event_count: stats.notes,
            skipped_count: stats.skipped,
            voice_count: stats.voices,
            duration_seconds: stats.total_seconds,
            tuning_a: stats.tuning_a,
            sidechain_hits: stats.sidechain_hits,
            per_track_events: stats.per_track_events.clone(),
            bad_tokens: stats.bad.clone(),
            warnings: stats.warnings.clone(),
        }
    }
}

fn main() {
    if let Err(error) = run() {
        eprintln!("mus: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), String> {
    let mut args = env::args().skip(1);
    let Some(command) = args.next() else {
        return Err(usage());
    };
    if command == "--help" || command == "-h" {
        println!("{}", usage());
        return Ok(());
    }
    if command == "check" {
        let score = PathBuf::from(args.next().ok_or_else(usage)?);
        let mut base = None;
        let mut json_output = false;
        while let Some(arg) = args.next() {
            match arg.as_str() {
                "--base" => base = Some(PathBuf::from(args.next().ok_or_else(usage)?)),
                "--json" => json_output = true,
                "--help" | "-h" => {
                    println!("{}", usage());
                    return Ok(());
                }
                _ => return Err(format!("unknown argument {arg}\n{}", usage())),
            }
        }
        let report = check::run(&score, base.as_deref())?;
        if json_output {
            println!(
                "{}",
                serde_json::to_string(&report).map_err(|e| e.to_string())?
            );
        } else {
            println!(
                "{}",
                serde_json::to_string_pretty(&report).map_err(|e| e.to_string())?
            );
        }
        return Ok(());
    }
    if command != "render" {
        return Err(usage());
    }
    let score = PathBuf::from(args.next().ok_or_else(usage)?);
    let mut output = None;
    let mut base = None;
    let mut compact = false;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "-o" => output = Some(PathBuf::from(args.next().ok_or_else(usage)?)),
            "--base" => base = Some(PathBuf::from(args.next().ok_or_else(usage)?)),
            "--json" => compact = true,
            "--help" | "-h" => {
                println!("{}", usage());
                return Ok(());
            }
            _ => return Err(format!("unknown argument {arg}\n{}", usage())),
        }
    }
    let output = output.unwrap_or_else(|| score.with_extension("wav"));
    match run_render(&score, &output, base.as_deref()) {
        Ok(receipt) => {
            let text = if compact {
                serde_json::to_string(&receipt)
            } else {
                serde_json::to_string_pretty(&receipt)
            }
            .map_err(|e| e.to_string())?;
            println!("{text}");
            Ok(())
        }
        Err(message) => {
            // "refusals as structured errors" — a render failure still
            // prints a JSON object on stdout (mirroring `check`'s always-
            // JSON contract) rather than only a plain-text line; `main()`'s
            // generic handler still prints the human-readable form to
            // stderr and sets the exit code.
            let error = serde_json::json!({
                "schema": "mus.audio.render-error.v1",
                "error": message,
            });
            println!("{error}");
            Err(message)
        }
    }
}

fn run_render(
    score: &std::path::Path,
    output: &std::path::Path,
    base: Option<&std::path::Path>,
) -> Result<Receipt, String> {
    let started = Instant::now();
    let source = fs::read_to_string(score).map_err(|e| format!("{}: {e}", score.display()))?;
    let score_dir = base
        .or_else(|| score.parent())
        .unwrap_or_else(|| std::path::Path::new("."));

    // Parsed a second time, independently of `mus_engine::render`'s own
    // internal parse: this is the graph-shaped view `head_selection` needs
    // (a CRDT concept the render orchestrator itself has no reason to
    // carry). A freshly-parsed single-source score is never contested, so
    // this is cheap and always resolves to `"sole"` in practice.
    let head_selection = parse_score(&source)
        .map(|proposal| head_selection_of(&adopt(&proposal)))
        .unwrap_or(serde_json::Value::String("sole".into()));

    let outcome = render(&source, score_dir).map_err(|e| e.to_string())?;
    write_wav(&outcome.audio, output).map_err(|e| e.to_string())?;

    let wav = fs::read(output).map_err(|e| format!("{}: {e}", output.display()))?;
    let source_digest = format!("sha256:{}", sha256_bytes(source.as_bytes()));
    Ok(Receipt::from_stats(
        &outcome.stats,
        format!("sha256:{}", sha256_bytes(&wav)),
        source_digest,
        head_selection,
        outcome.audio.peak_dbfs(),
        outcome.audio.rms_dbfs(),
        started.elapsed().as_secs_f64(),
    ))
}

fn head_selection_of(graph: &mus_graph::ScoreGraph) -> serde_json::Value {
    if graph.contested_lineages().is_empty() {
        return serde_json::Value::String("sole".into());
    }
    let mut selected = serde_json::Map::new();
    for (lineage, state) in &graph.lineages {
        if state.contested {
            if let Some(head) = state.chosen_head() {
                selected.insert(
                    lineage.0.clone(),
                    serde_json::Value::String(head.version.0.clone()),
                );
            }
        }
    }
    serde_json::Value::Object(selected)
}

fn usage() -> String {
    "usage:\n  mus check <score.mus> [--base DIR] [--json]\n  mus render <score.mus> [--base DIR] [-o <out.wav>] [--json]\n\nAtril swap:\n  MUS_CHECK_CMD=\"/Users/vera/dev/sophia/mus/mus-rs/target/release/mus check\"".into()
}
