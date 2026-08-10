mod check;

use mus_engine::{render, sha256_bytes, write_wav, ENGINE_VERSION};
use mus_text::{adopt, parse_score};
use serde::Serialize;
use std::env;
use std::fs;
use std::path::PathBuf;
use std::time::Instant;

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
    let mut json = false;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "-o" => output = Some(PathBuf::from(args.next().ok_or_else(usage)?)),
            "--json" => json = true,
            _ => return Err(format!("unknown argument {arg}\n{}", usage())),
        }
    }
    let output = output.ok_or_else(usage)?;
    let started = Instant::now();
    let source = fs::read_to_string(&score).map_err(|e| format!("{}: {e}", score.display()))?;
    let proposal = parse_score(&source).map_err(|diagnostics| {
        diagnostics
            .into_iter()
            .map(|diag| format!("{}: {}", diag.code, diag.message))
            .collect::<Vec<_>>()
            .join("; ")
    })?;
    let graph = adopt(&proposal);
    let audio = render(
        &graph,
        score.parent().unwrap_or_else(|| std::path::Path::new(".")),
    )
    .map_err(|e| e.to_string())?;
    write_wav(&audio, &output).map_err(|e| e.to_string())?;
    if json {
        let wav = fs::read(&output).map_err(|e| format!("{}: {e}", output.display()))?;
        let source_digest = format!("sha256:{}", sha256_bytes(source.as_bytes()));
        let receipt = Receipt {
            schema: "mus.audio.render-receipt.v1",
            render_digest: format!("sha256:{}", sha256_bytes(&wav)),
            source_digest,
            log_digest: None,
            head_selection: head_selection(&graph),
            engine_version: ENGINE_VERSION,
            peak_dbfs: audio.peak_dbfs(),
            rms_dbfs: audio.rms_dbfs(),
            wall_seconds: started.elapsed().as_secs_f64(),
        };
        println!(
            "{}",
            serde_json::to_string(&receipt).map_err(|e| e.to_string())?
        );
    } else {
        println!(
            "wrote {} ({:.3}s)",
            output.display(),
            audio.frames() as f64 / audio.sample_rate as f64
        );
    }
    Ok(())
}

fn head_selection(graph: &mus_graph::ScoreGraph) -> serde_json::Value {
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
    "usage:\n  mus check <score.mus> [--base DIR] [--json]\n  mus render <score.mus> -o <out.wav> [--json]\n\nAtril swap:\n  MUS_CHECK_CMD=\"/Users/vera/dev/sophia/mus/mus-rs/target/release/mus check\"".into()
}
