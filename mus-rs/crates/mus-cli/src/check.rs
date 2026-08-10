//! The effect-free `check` face.  Its output is intentionally shaped like
//! `mus_audio.check_score`: the Python checker is the migration oracle, while
//! the graph and vocabulary crates are the Rust implementation seams.

use mus_engine::sha256_bytes;
use mus_graph::timing::BarMap;
use mus_graph::ScoreGraph;
use mus_notation::{
    expand_pattern_repetitions, parse_token, split_attached_dynamics, tokenize_bar_content,
};
use mus_text::{parse_score_lossy, Diag, Proposal, ProposalInstrument};
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

const ERROR_CODES: &[&str] = &[
    "unparseable-token",
    "unknown-gesture",
    "synth-needs-pitch",
    "bad-header-value",
];
const CHAIN_ORDER: &[&str] = &[
    "gest", "glayer", "gsrc", "chop", "ring", "glow", "ghold", "gwarble", "gharm", "pump", "str",
    "stut", "haas",
];
const SYNTH_KEYS: &[&str] = &[
    "synth", "osc2", "mix2", "detune", "sub", "cutoff", "famt", "fdec", "satk", "sdec", "ssus",
    "srel",
];
const STRUCTURAL_PARAMS: &[&str] = &[
    "voice", "sample", "root", "mode", "gain", "pan", "send", "duck",
];

pub fn run(score_path: &Path, base_dir: Option<&Path>) -> Result<Value, String> {
    let source =
        fs::read_to_string(score_path).map_err(|e| format!("{}: {e}", score_path.display()))?;
    let base = base_dir.unwrap_or_else(|| score_path.parent().unwrap_or_else(|| Path::new(".")));
    let (proposal, parse_diags) = parse_score_lossy(&source);
    let graph = mus_text::adopt(&proposal);
    build_report(&source, &proposal, &graph, score_path, base, parse_diags)
}

fn build_report(
    source: &str,
    proposal: &Proposal,
    graph: &ScoreGraph,
    _score_path: &Path,
    base: &Path,
    parse_diags: Vec<Diag>,
) -> Result<Value, String> {
    let mut diagnostics = Vec::new();
    for diag in parse_diags {
        diagnostics.push(json!({
            "severity": if ERROR_CODES.contains(&diag.code.as_str()) { "error" } else { "warning" },
            "code": diag.code,
            "anchor": {"kind": "score"},
            "message": diag.message,
        }));
    }

    let tuning_a = header_float(
        &proposal.headers,
        "tuning",
        |raw| number_prefix(raw.split_once('=')?.1),
        440.0,
        &mut diagnostics,
    );
    let reverb_s = header_float(
        &proposal.headers,
        "reverb",
        |raw| number_prefix(raw),
        2.6,
        &mut diagnostics,
    );
    let master_rms = header_float(
        &proposal.headers,
        "master",
        |raw| number_prefix(raw.split_once('=')?.1),
        -17.0,
        &mut diagnostics,
    );

    let swing = parse_swing(&proposal.headers, &mut diagnostics);
    let (tempo_at, time_at) = layout_changes(proposal);
    let timing_graph = graph_with_layout_headers(proposal, &tempo_at, &time_at);
    let bar_map = BarMap::for_graph(&timing_graph).map_err(|e| format!("timing error: {e:?}"))?;

    let pack_ref = proposal.headers.get("pack").cloned();
    let pack_path = pack_ref.as_ref().map(|r| base.join(r));
    let pack_digest = artifact_digest(pack_path.as_deref());
    let pack_voices = if let Some(path) = pack_path.as_deref() {
        if pack_digest.is_none() {
            diagnostics.push(json!({
                "severity":"warning", "code":"missing-pack",
                "anchor":{"kind":"header","key":"pack"},
                "message":format!("{} not found", pack_ref.as_deref().unwrap_or_default()),
            }));
            BTreeMap::new()
        } else {
            load_pack_voices(path).map_err(|e| format!("{}: {e}", path.display()))?
        }
    } else {
        BTreeMap::new()
    };

    let gestures_ref = proposal.headers.get("gestures").cloned();
    let gestures_path = gestures_ref.as_ref().map(|r| base.join(r));
    let gestures_digest = artifact_digest(gestures_path.as_deref());
    let gestures = if let Some(path) = gestures_path.as_deref() {
        if gestures_digest.is_none() {
            diagnostics.push(json!({
                "severity":"warning", "code":"missing-gestures",
                "anchor":{"kind":"header","key":"gestures"},
                "message":format!("{} not found", gestures_ref.as_deref().unwrap_or_default()),
            }));
            BTreeMap::new()
        } else {
            load_gestures(path).map_err(|e| format!("{}: {e}", path.display()))?
        }
    } else {
        BTreeMap::new()
    };

    let tape_ref = proposal.headers.get("tape").cloned();
    let tape_path = tape_ref.as_ref().map(|r| base.join(r));
    let tape_digest = artifact_digest(tape_path.as_deref());
    if tape_ref.is_some() && tape_digest.is_none() {
        diagnostics.push(json!({
            "severity":"warning", "code":"missing-tape",
            "anchor":{"kind":"header","key":"tape"},
            "message":format!("{} not found", tape_ref.as_deref().unwrap_or_default()),
        }));
    }

    let instruments = instrument_report(&proposal.instruments, &pack_voices, &mut diagnostics);
    let bar_content = source_bars(source, &proposal.instruments);
    let events = event_report(
        proposal,
        &bar_content,
        &bar_map,
        tuning_a,
        &gestures,
        tape_digest.is_some(),
        &instruments,
        &mut diagnostics,
    );

    let sections = source_sections(source);
    let texts: Vec<Value> = proposal
        .texts
        .iter()
        .flat_map(|(bar, lines)| lines.iter().map(move |p| json!({"bar":bar,"prose":p})))
        .collect();
    let declared_objects = declared_objects(&instruments, &sections, &events);
    let mut tempo_changes = Vec::new();
    for (bar, tempo) in &tempo_at {
        tempo_changes.push(json!([bar, *tempo]));
    }
    let mut time_changes = Vec::new();
    for (bar, time) in &time_at {
        time_changes.push(json!([bar, time]));
    }
    let score = json!({
        "title": proposal.title,
        "summary": proposal.headers.get("summary"),
        "bars": bar_map.bars.len(),
        "durationSeconds": round(bar_map.total_seconds, 3),
        "tuningA": tuning_a,
        "swing": swing,
        "reverbSeconds": reverb_s,
        "masterRmsDb": master_rms,
        "sidechain": proposal.headers.get("sidechain").map(|raw| json!({"raw":raw})),
        "tempoChanges": tempo_changes,
        "timeChanges": time_changes,
        "sections": sections,
        "texts": texts,
    });

    let extension_usage = mus_graph::extension_usage(graph, &mus_vocab::is_core_param);
    Ok(json!({
        "schema": "mus.audio.check-report.v1",
        "producer": "mus-rs",
        "rendererVersion": "mus-rs/0.1.0",
        "clean": !diagnostics.iter().any(|d| d["severity"] == "error"),
        "sourceDigest": format!("sha256:{}", sha256_bytes(source.as_bytes())),
        "packDigest": pack_digest,
        "gesturesDigest": gestures_digest,
        "tapeDigest": tape_digest,
        "score": score,
        "instruments": instruments,
        "events": events,
        "declaredObjects": declared_objects,
        "diagnostics": diagnostics,
        "extensionUsage": extension_usage,
    }))
}

fn graph_with_layout_headers(
    proposal: &Proposal,
    tempo: &BTreeMap<u32, f64>,
    time: &BTreeMap<u32, String>,
) -> ScoreGraph {
    let mut graph = mus_text::adopt(proposal);
    // `BarMap` consumes one initial header value plus explicit inline
    // changes.  This avoids making its header parser responsible for the
    // Python face's prose-like `80 (b1) → 88 (b11)` spelling.
    if let Some((_, value)) = tempo.first_key_value() {
        graph.headers.insert("tempo".into(), format!("{value}"));
    }
    if let Some((_, value)) = time.first_key_value() {
        graph.headers.insert("time".into(), value.clone());
    }
    for (bar, value) in tempo.iter().filter(|(bar, _)| **bar != 1) {
        graph
            .inline_changes
            .entry(*bar)
            .or_default()
            .push(format!("tempo={value}"));
    }
    for (bar, value) in time.iter().filter(|(bar, _)| **bar != 1) {
        graph
            .inline_changes
            .entry(*bar)
            .or_default()
            .push(format!("time={value}"));
    }
    graph
}

fn header_float<F: Fn(&str) -> Option<f64>>(
    headers: &BTreeMap<String, String>,
    key: &str,
    parse: F,
    default: f64,
    diagnostics: &mut Vec<Value>,
) -> f64 {
    let Some(raw) = headers.get(key) else {
        return default;
    };
    match parse(raw) {
        Some(value) => value,
        None => {
            diagnostics.push(json!({
                "severity":"error", "code":"bad-header-value",
                "anchor":{"kind":"header","key":key},
                "message":format!("could not read {key:?} from {raw:?}"),
            }));
            default
        }
    }
}

fn number_prefix(raw: &str) -> Option<f64> {
    let start = raw
        .char_indices()
        .find(|(_, ch)| ch.is_ascii_digit() || *ch == '-')
        .map(|(index, _)| index)?;
    let end = raw[start..]
        .char_indices()
        .find(|(_, ch)| !ch.is_ascii_digit() && *ch != '.' && *ch != '-')
        .map(|(index, _)| start + index)
        .unwrap_or(raw.len());
    raw[start..end].parse().ok()
}

fn python_g(value: f64) -> String {
    if value == 0.0 {
        return "0".into();
    }
    let exponent = value.abs().log10().floor() as i32;
    let decimals = (5 - exponent).max(0);
    let rounded = round(value, decimals);
    let precision = decimals as usize;
    let mut text = format!("{rounded:.precision$}");
    if text.contains('.') {
        while text.ends_with('0') {
            text.pop();
        }
        if text.ends_with('.') {
            text.pop();
        }
    }
    text
}

fn parse_swing(headers: &BTreeMap<String, String>, diagnostics: &mut Vec<Value>) -> Option<Value> {
    let Some(raw) = headers.get("swing") else {
        return None;
    };
    let pieces: Vec<&str> = raw.split_whitespace().collect();
    let parsed = if pieces.len() > 1 {
        pieces[0]
            .parse::<i32>()
            .ok()
            .zip(pieces[1].parse::<f64>().ok())
    } else {
        pieces
            .first()
            .and_then(|value| value.parse::<f64>().ok())
            .map(|percent| (16, percent))
    };
    let Some((unit, percent)) = parsed else {
        diagnostics.push(json!({"severity":"error","code":"bad-header-value","anchor":{"kind":"header","key":"swing"},"message":format!("could not read swing from {raw:?}")}));
        return None;
    };
    if unit == 0 {
        diagnostics.push(json!({"severity":"error","code":"bad-header-value","anchor":{"kind":"header","key":"swing"},"message":format!("could not read swing from {raw:?}")}));
        return None;
    }
    Some(json!({"unit":unit,"percent":percent}))
}

fn layout_changes(proposal: &Proposal) -> (BTreeMap<u32, f64>, BTreeMap<u32, String>) {
    let mut tempo = parse_change_list(proposal.headers.get("tempo"), true);
    let mut time = parse_change_list(proposal.headers.get("time"), false);
    for (bar, changes) in &proposal.bar_changes {
        for change in changes {
            let Some((key, value)) = change.split_once('=') else {
                continue;
            };
            match key.trim().to_ascii_lowercase().as_str() {
                "tempo" => {
                    if let Ok(v) = value.trim().parse() {
                        tempo.insert(*bar, v);
                    }
                }
                "time" => {
                    time.insert(*bar, value.trim().into());
                }
                _ => {}
            }
        }
    }
    (tempo, time)
}

fn parse_change_list<T: std::str::FromStr>(
    raw: Option<&String>,
    integer: bool,
) -> BTreeMap<u32, T> {
    let Some(raw) = raw.map(String::as_str).map(str::trim) else {
        return BTreeMap::new();
    };
    if raw.is_empty() {
        return BTreeMap::new();
    }
    let mut out = BTreeMap::new();
    if raw.contains("(initial") {
        if let Some(value) = raw.split_whitespace().next().and_then(|v| v.parse().ok()) {
            out.insert(1, value);
        }
        return out;
    }
    if !raw.contains('→') && !raw.contains("(b") {
        if let Ok(value) = raw.parse() {
            out.insert(1, value);
        }
        return out;
    }
    for piece in raw.split('→') {
        let piece = piece.trim();
        if let Some(open) = piece.find("(b") {
            let value = piece[..open].trim();
            let rest = &piece[open + 2..];
            let Some(close) = rest.find(')') else {
                continue;
            };
            let Ok(bar) = rest[..close].parse::<u32>() else {
                continue;
            };
            if let Ok(value) = value.parse() {
                out.insert(bar, value);
            }
        } else if let Ok(value) = piece.parse() {
            out.insert(1, value);
        }
    }
    let _ = integer;
    out
}

fn artifact_digest(path: Option<&Path>) -> Option<String> {
    let path = path?;
    Some(format!("sha256:{}", sha256_bytes(&fs::read(path).ok()?)))
}

fn load_pack_voices(path: &Path) -> Result<BTreeMap<String, Vec<f64>>, serde_json::Error> {
    let value: Value = serde_json::from_slice(&fs::read(path).map_err(serde_json::Error::io)?)?;
    let mut voices = BTreeMap::new();
    if let Some(items) = value.get("voices").and_then(Value::as_object) {
        for (name, voice) in items {
            let f0s = voice
                .get("samples")
                .and_then(Value::as_array)
                .map(|samples| {
                    samples
                        .iter()
                        .map(|s| s.get("f0_hz").and_then(Value::as_f64).unwrap_or(0.0))
                        .collect()
                })
                .unwrap_or_default();
            voices.insert(name.clone(), f0s);
        }
    }
    if let Some(items) = value.get("noise").and_then(Value::as_object) {
        for name in items.keys() {
            voices.insert(name.clone(), vec![0.0]);
        }
    }
    Ok(voices)
}

#[derive(Clone)]
struct Gesture {
    resolved: Vec<(f64, f64)>,
    octave: Vec<(f64, f64)>,
    median_hz: f64,
    t0: Option<f64>,
    t1: Option<f64>,
    id: Option<String>,
}

fn load_gestures(path: &Path) -> Result<BTreeMap<String, Gesture>, serde_json::Error> {
    let value: Value = serde_json::from_slice(&fs::read(path).map_err(serde_json::Error::io)?)?;
    let events = value
        .get("events")
        .and_then(Value::as_array)
        .or_else(|| value.as_array())
        .cloned()
        .unwrap_or_default();
    let mut out = BTreeMap::new();
    for (i, event) in events.iter().enumerate() {
        let Some(contour) = event.get("contour").and_then(Value::as_array) else {
            continue;
        };
        let resolved: Vec<(f64, f64)> = contour
            .iter()
            .filter_map(|r| {
                let a = r.as_array()?;
                if a.get(2)?.as_str()? != "r" || !a.get(1)?.as_f64()?.ne(&0.0) {
                    return None;
                }
                Some((a.first()?.as_f64()?, a.get(1)?.as_f64()?))
            })
            .collect();
        let octave: Vec<(f64, f64)> = contour
            .iter()
            .filter_map(|r| {
                let a = r.as_array()?;
                if a.get(2)?.as_str()? != "o" || a.get(3)?.as_f64()?.eq(&0.0) {
                    return None;
                }
                Some((a.first()?.as_f64()?, a.get(3)?.as_f64()?))
            })
            .collect();
        let reference = if !resolved.is_empty() {
            &resolved
        } else {
            &octave
        };
        if reference.len() < 2 {
            continue;
        }
        let mut hz: Vec<f64> = reference.iter().map(|(_, h)| *h).collect();
        hz.sort_by(f64::total_cmp);
        let gesture = Gesture {
            resolved,
            octave,
            median_hz: hz[hz.len() / 2],
            t0: event.get("start_seconds").and_then(Value::as_f64),
            t1: event.get("end_seconds").and_then(Value::as_f64),
            id: Some(
                event
                    .get("hypothesis_id")
                    .and_then(Value::as_str)
                    .map(str::to_string)
                    .unwrap_or_else(|| format!("h{i}")),
            ),
        };
        out.insert(format!("h{i}"), gesture.clone());
        if let Some(id) = gesture.id.clone() {
            out.insert(id.clone(), gesture.clone());
            if let Some(hash) = id.split("sha256:").nth(1) {
                out.entry(hash.to_string()).or_insert(gesture);
            }
        }
    }
    Ok(out)
}

fn lookup_gesture<'a>(gestures: &'a BTreeMap<String, Gesture>, key: &str) -> Option<&'a Gesture> {
    if let Some(value) = gestures.get(key) {
        return Some(value);
    }
    let hits: Vec<&Gesture> = gestures
        .iter()
        .filter(|(k, _)| key.len() >= 6 && k.starts_with(key) && !k.starts_with('h'))
        .map(|(_, v)| v)
        .collect();
    if hits.len() == 1 {
        Some(hits[0])
    } else {
        None
    }
}

fn instrument_report(
    instruments: &[ProposalInstrument],
    voices: &BTreeMap<String, Vec<f64>>,
    diagnostics: &mut Vec<Value>,
) -> Vec<Value> {
    instruments.iter().map(|inst| {
        let p = &inst.params;
        let source = if SYNTH_KEYS.iter().any(|key| p.contains_key(*key)) {
            let patch: Map<String, Value> = SYNTH_KEYS.iter().filter_map(|key| p.get(*key).map(|v| ((*key).into(), json!(v)))).collect();
            json!({"kind":"synth","patch":patch})
        } else if let Some(sample) = p.get("sample") {
            json!({"kind":"sample","path":sample})
        } else if let Some(voice) = p.get("voice").filter(|v| voices.contains_key(*v)) {
            json!({"kind":"voice","voice":voice,"samples":voices[voice].len(),"sampleF0Hz":voices[voice]})
        } else {
            diagnostics.push(json!({"severity":"warning","code":"no-samples-for-track","anchor":{"kind":"instrument","abbrev":inst.abbrev},"message":format!("track '{}' resolves no samples and declares no synth", inst.abbrev)}));
            json!({"kind":"missing"})
        };
        let defaults: Map<String, Value> = p.iter().filter(|(key, _)| !STRUCTURAL_PARAMS.contains(&key.as_str()) && !SYNTH_KEYS.contains(&key.as_str())).map(|(k,v)| (k.clone(), json!(v))).collect();
        let chain: Vec<Value> = CHAIN_ORDER.iter().filter(|key| p.contains_key(**key)).map(|key| json!(key)).collect();
        json!({"abbrev":inst.abbrev,"name":inst.name,"clef":inst.clef,"source":source,"defaults":defaults,"transformChain":chain})
    }).collect()
}

fn source_bars(
    source: &str,
    instruments: &[ProposalInstrument],
) -> BTreeMap<u32, BTreeMap<String, String>> {
    let abbrevs: Vec<String> = instruments.iter().map(|i| i.abbrev.clone()).collect();
    let mut out = BTreeMap::new();
    for line in source.lines() {
        let Some((from, to, _, content)) = parse_bar_line(line) else {
            continue;
        };
        let map = if content.trim() == "tacet" {
            abbrevs.iter().map(|a| (a.clone(), "-".into())).collect()
        } else {
            split_bar_content(content, &abbrevs)
        };
        for bar in from..=to {
            out.insert(bar, map.clone());
        }
    }
    out
}

fn parse_bar_line(line: &str) -> Option<(u32, u32, Vec<String>, &str)> {
    let body = line.trim();
    let after = body
        .strip_prefix("bar ")
        .or_else(|| body.strip_prefix("bars "))?;
    let (head, content) = after.split_once(':')?;
    let (range, changes) = if let Some(open) = head.find('[') {
        let close = head[open..].find(']')? + open;
        (
            head[..open].trim(),
            head[open + 1..close]
                .split(',')
                .map(|s| s.trim().into())
                .collect(),
        )
    } else {
        (head.trim(), Vec::new())
    };
    let (from, to) = range.split_once('-').map_or_else(
        || Some((range.parse().ok()?, range.parse().ok()?)),
        |(a, b)| Some((a.trim().parse().ok()?, b.trim().parse().ok()?)),
    )?;
    Some((from, to, changes, content.trim()))
}

fn split_bar_content(content: &str, abbrevs: &[String]) -> BTreeMap<String, String> {
    let mut positions = Vec::new();
    for (index, _) in content.match_indices('=') {
        let mut start = index;
        while start > 0 && !content.as_bytes()[start - 1].is_ascii_whitespace() {
            start -= 1;
        }
        let candidate = content[start..index].trim();
        if abbrevs.iter().any(|a| a == candidate) {
            positions.push((start, index + 1, candidate.to_string()));
        }
    }
    positions.sort_by_key(|(start, _, _)| *start);
    positions
        .iter()
        .enumerate()
        .map(|(i, (_, value_start, abbr))| {
            let end = positions
                .get(i + 1)
                .map(|(start, _, _)| *start)
                .unwrap_or(content.len());
            (abbr.clone(), content[*value_start..end].trim().into())
        })
        .collect()
}

fn event_report(
    proposal: &Proposal,
    bar_content: &BTreeMap<u32, BTreeMap<String, String>>,
    bar_map: &BarMap,
    tuning_a: f64,
    gestures: &BTreeMap<String, Gesture>,
    tape_exists: bool,
    instruments: &[Value],
    diagnostics: &mut Vec<Value>,
) -> Vec<Value> {
    let mut events = Vec::new();
    let mut proposal_index = 0usize;
    for inst in &proposal.instruments {
        let defaults: BTreeMap<String, String> = inst
            .params
            .iter()
            .filter(|(key, _)| {
                !STRUCTURAL_PARAMS.contains(&key.as_str()) && !SYNTH_KEYS.contains(&key.as_str())
            })
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect();
        let synth = instruments
            .iter()
            .find(|i| i["abbrev"].as_str() == Some(inst.abbrev.as_str()))
            .map(|i| i["source"]["kind"] == "synth")
            .unwrap_or(false);
        let mut dynamic = "mf".to_string();
        for bar in 1..=bar_map.bars.len() as u32 {
            let Some(content) = bar_content.get(&bar).and_then(|m| m.get(&inst.abbrev)) else {
                continue;
            };
            if content.trim().is_empty() || content.trim() == "-" {
                continue;
            }
            let tokens = split_attached_dynamics(&expand_pattern_repetitions(
                &tokenize_bar_content(content),
            ));
            let mut onset = 0.0;
            for (token_index, raw) in tokens.iter().enumerate() {
                let Some(note) = parse_token(raw) else {
                    if raw.trim() != "-" {
                        diagnostics.push(json!({"severity":"error","code":"unparseable-token","anchor":{"kind":"event","bar":bar,"track":inst.abbrev,"tokenIndex":token_index},"message":raw}));
                    }
                    continue;
                };
                match note.kind.as_str() {
                    "dynamic" => {
                        if let Some(value) = note.dyn_value {
                            dynamic = value;
                        }
                        continue;
                    }
                    "hairpin" => continue,
                    "rest" => {
                        onset += note.ql;
                        continue;
                    }
                    _ => {}
                }
                let Some(proposal_event) = proposal.events.get(proposal_index) else {
                    continue;
                };
                proposal_index += 1;
                let bar_timing = &bar_map.bars[&bar];
                let ql = note.ql;
                if ql <= 0.0 && raw.trim() != "R" {
                    diagnostics.push(json!({"severity":"warning","code":"zero-duration","anchor":{"kind":"event","bar":bar,"track":inst.abbrev,"tokenIndex":token_index},"message":raw}));
                }
                if onset >= bar_timing.length_ql.as_f64() - 1e-6 {
                    diagnostics.push(json!({"severity":"warning","code":"overfull-bar","anchor":{"kind":"event","bar":bar,"track":inst.abbrev,"tokenIndex":token_index},"message":format!("onset at {} ql in a {} ql bar", python_g(onset), python_g(bar_timing.length_ql.as_f64()))}));
                }
                let params: BTreeMap<String, String> = note.params.clone().into_iter().collect();
                let mut effective = defaults.clone();
                effective.extend(params.clone());
                let quote = quote_report(
                    &note,
                    &effective,
                    bar,
                    token_index,
                    inst,
                    gestures,
                    tape_exists,
                    tuning_a,
                    diagnostics,
                );
                if synth
                    && note.kind == "unpitched"
                    && quote
                        .as_ref()
                        .and_then(|q| q.get("gsrc"))
                        .and_then(Value::as_str)
                        != Some("raw")
                {
                    diagnostics.push(json!({"severity":"error","code":"synth-needs-pitch","anchor":{"kind":"event","bar":bar,"track":inst.abbrev,"tokenIndex":token_index},"message":raw}));
                }
                let pitches: Vec<Value> = proposal_event
                    .pitches_midi_cents
                    .iter()
                    .map(|p| json!(midi_name(*p as f64 / 100.0)))
                    .collect();
                let pitches_hz: Vec<Value> = proposal_event
                    .pitches_midi_cents
                    .iter()
                    .map(|p| json!(round(midi_to_hz(*p as f64 / 100.0, tuning_a), 3)))
                    .collect();
                let lyric = raw.find('"').and_then(|start| {
                    raw[start + 1..]
                        .find('"')
                        .map(|end| raw[start + 1..start + 1 + end].to_string())
                });
                let sweeps: Vec<Value> = effective
                    .iter()
                    .filter(|(_, v)| v.contains("->"))
                    .map(|(k, _)| json!(k))
                    .collect();
                let mut flags = note.flags.clone();
                flags.sort();
                let kind = match proposal_event.kind {
                    mus_oplog::EventKind::Note => "note",
                    mus_oplog::EventKind::Chord => "chord",
                    mus_oplog::EventKind::Unpitched => "unpitched",
                };
                events.push(json!({
                    "bar":bar,"track":inst.abbrev,"tokenIndex":token_index,"kind":kind,
                    "onsetQl":round(onset,6),"onsetSeconds":round(bar_timing.start_seconds + onset * bar_timing.seconds_per_quarter,6),
                    "swungOnsetSeconds":round(bar_timing.start_seconds + swung(onset, proposal.headers.get("swing")) * bar_timing.seconds_per_quarter,6),
                    "durationQl":round(ql,6),"durationSeconds":round(ql * bar_timing.seconds_per_quarter,6),
                    "pitches":pitches,"pitchesHz":pitches_hz,
                    "glissTargetHz":proposal_event.gliss_target_midi_cents.map(|p| json!(round(midi_to_hz(p as f64 / 100.0,tuning_a),3))).unwrap_or(Value::Null),
                    "dynamic":dynamic,"params":params,"effectiveParams":effective,"flags":flags,"sweeps":sweeps,"lyric":lyric,"quote":quote,
                }));
                onset += ql;
            }
        }
    }
    events
}

fn quote_report(
    note: &mus_notation::Note,
    effective: &BTreeMap<String, String>,
    bar: u32,
    token_index: usize,
    inst: &ProposalInstrument,
    gestures: &BTreeMap<String, Gesture>,
    tape_exists: bool,
    tuning_a: f64,
    diagnostics: &mut Vec<Value>,
) -> Option<Value> {
    let gest = effective.get("gest")?;
    let anchor = json!({"kind":"event","bar":bar,"track":inst.abbrev,"tokenIndex":token_index});
    let layer = effective
        .get("glayer")
        .map(String::as_str)
        .unwrap_or("resolved");
    let Some(gesture) = lookup_gesture(gestures, gest) else {
        diagnostics.push(json!({"severity":"error","code":"unknown-gesture","anchor":anchor,"message":format!("gest={gest}")}));
        return None;
    };
    let points = if layer == "octave" {
        &gesture.octave
    } else {
        &gesture.resolved
    };
    if points.len() < 2 && effective.get("gsrc").map(String::as_str) != Some("raw") {
        diagnostics.push(json!({"severity":"warning","code":"sparse-gesture-layer","anchor":anchor,"message":format!("gest={gest} layer {layer}")}));
    }
    if effective.get("gsrc").map(String::as_str) == Some("raw") && !tape_exists {
        diagnostics.push(json!({"severity":"warning","code":"no-tape-header","anchor":anchor,"message":"gsrc=raw without a # tape: header"}));
    }
    let shift = if note.kind == "note" && !note.midis.is_empty() {
        Some(round(
            12.0 * (midi_to_hz(note.midis[0], tuning_a) / gesture.median_hz).log2(),
            2,
        ))
    } else {
        None
    };
    Some(
        json!({"gest":gest,"layer":layer,"gsrc":effective.get("gsrc"),"hypothesisId":gesture.id,"t0":gesture.t0,"t1":gesture.t1,"medianHz":gesture.median_hz,"shiftSt":shift}),
    )
}

fn swung(q: f64, swing: Option<&String>) -> f64 {
    let Some(raw) = swing else {
        return q;
    };
    let p: Vec<&str> = raw.split_whitespace().collect();
    let (unit, percent) = if p.len() > 1 {
        (
            p[0].parse::<f64>().unwrap_or(0.0),
            p[1].parse::<f64>().unwrap_or(50.0),
        )
    } else {
        (16.0, p.first().and_then(|v| v.parse().ok()).unwrap_or(50.0))
    };
    if unit <= 0.0 {
        return q;
    }
    let unit_ql = 4.0 / unit;
    let ratio = (percent / 100.0).clamp(0.5, 0.75);
    let k = (q / unit_ql + 1e-6).floor() as i64;
    if k % 2 == 1 && (q - k as f64 * unit_ql).abs() < 1e-6 {
        q + unit_ql * (2.0 * ratio - 1.0)
    } else {
        q
    }
}

fn round(value: f64, decimals: i32) -> f64 {
    // Python's round is decimal, ties-to-even rounding.  Formatting first is
    // important: multiplying by 10**n turns values such as 2.675 into an
    // artificial binary tie and would produce 2.68 instead of Python's 2.67.
    if !value.is_finite() {
        return value;
    }
    let precision = usize::try_from(decimals.max(0)).unwrap_or(0);
    format!("{value:.precision$}").parse().unwrap_or(value)
}
fn midi_to_hz(midi: f64, a4: f64) -> f64 {
    a4 * 2f64.powf((midi - 69.0) / 12.0)
}

fn midi_name(midi: f64) -> String {
    const NAMES: &[&str] = &[
        "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
    ];
    let n = round(midi, 0) as i32;
    let cents = round((midi - n as f64) * 100.0, 0) as i32;
    let name = format!("{}{}", NAMES[((n % 12 + 12) % 12) as usize], n / 12 - 1);
    if cents == 0 {
        name
    } else {
        format!("{name}{cents:+}")
    }
}

fn source_sections(source: &str) -> Vec<Value> {
    source.lines().filter_map(|line| {
        let body = line.trim().strip_prefix('#')?.trim();
        let rest = body.strip_prefix("section:")?.trim(); let open = rest.rfind('[')?; let close = rest[open..].find(']')? + open;
        let (from,to) = rest[open+1..close].split_once('-')?; let from: u32 = from.trim().parse().ok()?; let to: u32 = to.trim().parse().ok()?;
        let mut name = rest[..open].trim().to_string(); if let Some((head,_)) = name.split_once('—') { name = head.trim().into(); }
        let prose = rest[close+1..].trim().trim_start_matches(['—','–','-']).trim();
        Some(json!({"name":name,"from":from,"to":to,"prose":if prose.is_empty(){Value::Null}else{json!(prose)}}))
    }).collect()
}

fn declared_objects(instruments: &[Value], sections: &[Value], events: &[Value]) -> Vec<Value> {
    let mut out: Vec<Value> = instruments
        .iter()
        .map(|i| json!({"id":i["abbrev"],"kind":"instrument","iri":null}))
        .collect();
    out.extend(
        sections
            .iter()
            .map(|s| json!({"id":s["name"],"kind":"section","iri":null})),
    );
    let mut gestures = BTreeMap::new();
    for event in events {
        if let Some(g) = event["quote"]["gest"].as_str() {
            gestures
                .entry(g.to_string())
                .or_insert_with(|| event["quote"]["hypothesisId"].as_str().map(str::to_string));
        }
    }
    out.extend(
        gestures
            .into_iter()
            .map(|(id, iri)| json!({"id":id,"kind":"gesture","iri":iri})),
    );
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use mus_text::parse_score_lossy;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_file(suffix: &str, bytes: &[u8]) -> std::path::PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = std::env::temp_dir().join(format!("mus-check-{nonce}-{suffix}"));
        fs::write(&path, bytes).unwrap();
        path
    }

    fn instrument(abbrev: &str) -> ProposalInstrument {
        ProposalInstrument {
            abbrev: abbrev.into(),
            name: "voice".into(),
            clef: "treble".into(),
            params: BTreeMap::new(),
        }
    }

    #[test]
    fn parses_headers_and_layout_change_lists() {
        let mut headers = BTreeMap::new();
        headers.insert("tuning".into(), "A = 445.6".into());
        headers.insert("reverb".into(), "seconds 0.6".into());
        headers.insert("master".into(), "rms = -14".into());
        headers.insert("swing".into(), "16 56".into());
        let mut diagnostics = Vec::new();
        assert_eq!(
            header_float(
                &headers,
                "tuning",
                |raw| raw.split_once('=')?.1.trim().parse().ok(),
                440.0,
                &mut diagnostics
            ),
            445.6
        );
        assert_eq!(
            header_float(
                &headers,
                "reverb",
                |raw| raw.split_whitespace().find_map(|part| part.parse().ok()),
                2.6,
                &mut diagnostics
            ),
            0.6
        );
        assert_eq!(
            header_float(
                &headers,
                "master",
                |raw| raw.split_once('=')?.1.trim().parse().ok(),
                -17.0,
                &mut diagnostics
            ),
            -14.0
        );
        assert_eq!(
            parse_swing(&headers, &mut diagnostics),
            Some(json!({"unit":16,"percent":56.0}))
        );
        assert!(diagnostics.is_empty());
        assert_eq!(number_prefix("rms = -14 dB"), Some(-14.0));
        assert_eq!(python_g(1.2345678), "1.23457");
        assert_eq!(python_g(4.0), "4");
        headers.insert("swing".into(), "0 56".into());
        assert!(parse_swing(&headers, &mut diagnostics).is_none());
        assert_eq!(diagnostics.last().unwrap()["code"], "bad-header-value");

        let mut proposal = Proposal {
            headers,
            ..Proposal::default()
        };
        proposal
            .headers
            .insert("tempo".into(), "80 (b1) → 88 (b11) → 104 (b23)".into());
        proposal.headers.insert("time".into(), "4/4".into());
        proposal
            .bar_changes
            .insert(23, vec!["tempo=106".into(), "time=3/4".into()]);
        let (tempo, time) = layout_changes(&proposal);
        assert_eq!(tempo, BTreeMap::from([(1, 80.0), (11, 88.0), (23, 106.0)]));
        assert_eq!(
            time,
            BTreeMap::from([(1, "4/4".into()), (23, "3/4".into())])
        );
        assert_eq!(
            parse_change_list::<f64>(Some(&"80 (initial; 4 changes inline)".into()), true),
            BTreeMap::from([(1, 80.0)])
        );
    }

    #[test]
    fn rounding_swing_and_digest_math_follow_contract() {
        assert_eq!(round(2.5, 0), 2.0);
        assert_eq!(round(3.5, 0), 4.0);
        assert_eq!(round(-2.5, 0), -2.0);
        assert_eq!(round(1.25, 1), 1.2);
        assert_eq!(round(2.675, 2), 2.67);
        assert_eq!(swung(0.5, Some(&"16 56".into())), 0.5);
        assert!((swung(0.75, Some(&"16 56".into())) - 0.78).abs() < 1e-12);
        assert!((midi_to_hz(69.0, 440.0) - 440.0).abs() < 1e-12);
        assert_eq!(midi_name(60.0), "C4");
        assert_eq!(midi_name(60.23), "C4+23");

        let path = temp_file("digest", b"abc");
        assert_eq!(
            artifact_digest(Some(&path)),
            Some("sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad".into())
        );
        fs::remove_file(path).unwrap();
    }

    #[test]
    fn loads_gestures_and_reports_exact_quote_math() {
        let bytes = serde_json::to_vec(&json!({
            "events": [{
                "contour": [[0.0, 0.0, "r"], [0.1, 440.0, "r"], [0.2, 450.0, "r"], [0.3, 7.0, "o", 880.0]]
            }]
        }))
        .unwrap();
        let path = temp_file("gestures.json", &bytes);
        let gestures = load_gestures(&path).unwrap();
        assert_eq!(gestures["h0"].median_hz, 450.0);
        assert_eq!(gestures["h0"].id.as_deref(), Some("h0"));
        assert!(lookup_gesture(&gestures, "h0").is_some());

        let note = parse_token("C4q").unwrap();
        let mut effective = BTreeMap::from([
            ("gest".into(), "h0".into()),
            ("glayer".into(), "octave".into()),
            ("gsrc".into(), "raw".into()),
        ]);
        let mut diagnostics = Vec::new();
        let quote = quote_report(
            &note,
            &effective,
            3,
            2,
            &instrument("v"),
            &gestures,
            false,
            440.0,
            &mut diagnostics,
        )
        .unwrap();
        assert_eq!(quote["layer"], "octave");
        assert_eq!(quote["gsrc"], "raw");
        assert_eq!(quote["hypothesisId"], "h0");
        assert_eq!(quote["t0"], Value::Null);
        assert_eq!(quote["shiftSt"], -9.39);
        assert_eq!(diagnostics[0]["code"], "no-tape-header");

        effective.insert("gest".into(), "missing".into());
        let result = quote_report(
            &note,
            &effective,
            3,
            2,
            &instrument("v"),
            &gestures,
            true,
            440.0,
            &mut diagnostics,
        );
        assert!(result.is_none());
        assert_eq!(diagnostics.last().unwrap()["code"], "unknown-gesture");
        fs::remove_file(path).unwrap();
    }

    #[test]
    fn splits_ranges_tacet_and_track_content_deterministically() {
        assert_eq!(
            parse_bar_line("bars 2-4 [tempo=88, time=3/4]: a=C4q b=Rq"),
            Some((
                2,
                4,
                vec!["tempo=88".into(), "time=3/4".into()],
                "a=C4q b=Rq"
            ))
        );
        let split = split_bar_content("a=C4q Rq b=<E4 G4>h", &["a".into(), "b".into()]);
        assert_eq!(split["a"], "C4q Rq");
        assert_eq!(split["b"], "<E4 G4>h");
        let source = "# bars: 2\nbar 1: tacet\nbar 2: a=C4q\n";
        let bars = source_bars(source, &[instrument("a")]);
        assert_eq!(bars[&1]["a"], "-");
        assert_eq!(bars[&2]["a"], "C4q");
    }

    #[test]
    fn build_report_keeps_diagnostics_anchored_and_clean_false() {
        let source = "# score: diagnostic\n# tuning: A=not-a-number\n# gestures: missing.json\n# bars: 1\n# instruments:\n#   s = synth (perc, synth=saw)\nbar 1: s=Xq[gest=missing] bogus\n";
        let (proposal, parse_diags) = parse_score_lossy(source);
        let graph = mus_text::adopt(&proposal);
        let base = std::env::temp_dir();
        let report = build_report(
            source,
            &proposal,
            &graph,
            Path::new("diagnostic.mus"),
            &base,
            parse_diags,
        )
        .unwrap();
        assert!(!report["clean"].as_bool().unwrap());
        let diagnostics = report["diagnostics"].as_array().unwrap();
        assert!(diagnostics
            .iter()
            .any(|d| d["code"] == "bad-header-value" && d["anchor"]["key"] == "tuning"));
        assert!(diagnostics.iter().any(|d| d["code"] == "missing-gestures"));
        assert!(diagnostics
            .iter()
            .any(|d| d["code"] == "unknown-gesture" && d["anchor"]["bar"] == 1));
        assert!(diagnostics
            .iter()
            .any(|d| d["code"] == "synth-needs-pitch" && d["anchor"]["track"] == "s"));
        assert!(diagnostics
            .iter()
            .any(|d| d["code"] == "unparseable-token" && d["anchor"]["tokenIndex"] == 1));
    }
}
