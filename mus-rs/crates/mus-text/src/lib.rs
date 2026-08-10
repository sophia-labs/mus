//! mus-text — parse the most-honored MUS face into a graph-shaped proposal.
//!
//! A proposal has positional events rather than lineage ids. The ingest seam
//! (W-C) will diff those positions into ops; this crate also exposes `adopt`
//! for the W-B round-trip law and tests, where deterministic positional ops
//! are sufficient to obtain a `ScoreGraph` face.

use mus_graph::ScoreGraph;
use mus_notation::{
    expand_pattern_repetitions, parse_token, split_attached_dynamics, tokenize_bar_content,
};
use mus_oplog::{EventKind, EventState, Frac, OpBody, OpLog, Quote, QuoteLayer};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

pub mod ingest;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Diag {
    pub severity: String,
    pub code: String,
    pub message: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProposalInstrument {
    pub abbrev: String,
    pub name: String,
    pub clef: String,
    pub params: BTreeMap<String, String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProposalSection {
    pub name: String,
    pub from_bar: u32,
    pub to_bar: u32,
    pub prose: Option<String>,
}

/// ScoreGraph's shape without lineage identity. `bar_changes` carries the
/// inline `tempo=…`, `time=…`, and other bracket changes that are not fields
/// of an event but must survive text reduction.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Proposal {
    pub title: String,
    pub headers: BTreeMap<String, String>,
    pub performance: BTreeMap<String, String>,
    pub instruments: Vec<ProposalInstrument>,
    pub sections: Vec<ProposalSection>,
    pub texts: BTreeMap<u32, Vec<String>>,
    pub bar_changes: BTreeMap<u32, Vec<String>>,
    pub events: Vec<EventState>,
}

fn diag(code: &str, message: impl Into<String>) -> Diag {
    Diag {
        severity: "error".into(),
        code: code.into(),
        message: message.into(),
    }
}

/// Parse one complete MUS score. Unknown non-comment/non-bar prose is
/// intentionally tolerated, matching `mus.py::parse_mus`.
pub fn parse_score(text: &str) -> Result<Proposal, Vec<Diag>> {
    let (proposal, diagnostics) = parse_score_lossy(text);
    if diagnostics.is_empty() {
        Ok(proposal)
    } else {
        Err(diagnostics)
    }
}

/// Parse a score while retaining the graph-shaped proposal even when one or
/// more tokens are malformed.  The check face is deliberately tolerant: a
/// refused score is a report with `clean: false`, not a process-level error.
pub fn parse_score_lossy(text: &str) -> (Proposal, Vec<Diag>) {
    let mut proposal = Proposal {
        title: "Untitled".into(),
        ..Proposal::default()
    };
    let mut diagnostics = Vec::new();
    let mut in_instruments = false;
    let mut bars: BTreeMap<u32, BTreeMap<String, String>> = BTreeMap::new();
    let mut bar_end = 0u32;
    let mut instrument_lines = Vec::new();

    for raw in text.lines() {
        let line = raw.trim_end();
        if line.trim().is_empty() {
            in_instruments = false;
            continue;
        }
        if line.trim_start().starts_with('#') {
            let body = line.trim_start().trim_start_matches('#').trim();
            if let Some(rest) = body.strip_prefix("text @b") {
                if let Some((bar, prose)) = rest.split_once(':') {
                    if let Ok(bar) = bar.trim().parse() {
                        proposal
                            .texts
                            .entry(bar)
                            .or_default()
                            .push(prose.trim().into());
                    }
                }
                in_instruments = false;
                continue;
            }
            if body.eq_ignore_ascii_case("instruments:") || body.eq_ignore_ascii_case("instruments")
            {
                in_instruments = true;
                continue;
            }
            if let Some(section) = parse_section(body) {
                proposal.sections.push(section);
                continue;
            }
            if in_instruments {
                if body.contains('=') && body.contains('(') {
                    instrument_lines.push(body.to_string());
                }
                continue;
            }
            for piece in split_headers(body) {
                let Some((key, value)) = piece.split_once(':') else {
                    continue;
                };
                let key = key.trim().to_ascii_lowercase();
                let value = value.trim().to_string();
                if key == "score" {
                    proposal.title = value;
                } else {
                    proposal.headers.insert(key, value);
                }
            }
            continue;
        }

        if let Some((from, to, changes, content)) = parse_bar_line(line) {
            bar_end = bar_end.max(to);
            for bar in from..=to {
                bars.insert(
                    bar,
                    split_bar_content(content, &instrument_abbrevs(&instrument_lines)),
                );
                if !changes.is_empty() {
                    proposal.bar_changes.insert(bar, changes.clone());
                }
            }
        }
    }

    for line in instrument_lines {
        match parse_instrument(&line) {
            Some(inst) => proposal.instruments.push(inst),
            None => diagnostics.push(diag(
                "bad-instrument",
                format!("could not parse instrument: {line}"),
            )),
        }
    }
    // Bar content is split again now that all declarations are known. This
    // avoids making declaration order a hidden parser dependency.
    bars.clear();
    for raw in text.lines() {
        if let Some((from, to, changes, content)) = parse_bar_line(raw.trim_end()) {
            for bar in from..=to {
                bars.insert(
                    bar,
                    if content.trim() == "tacet" {
                        proposal
                            .instruments
                            .iter()
                            .map(|i| (i.abbrev.clone(), "-".to_string()))
                            .collect()
                    } else {
                        split_bar_content(
                            content,
                            &proposal
                                .instruments
                                .iter()
                                .map(|i| i.abbrev.clone())
                                .collect::<Vec<_>>(),
                        )
                    },
                );
                if !changes.is_empty() {
                    proposal.bar_changes.insert(bar, changes.clone());
                }
            }
        }
    }
    let declared_bars = proposal
        .headers
        .get("bars")
        .and_then(|v| v.parse().ok())
        .unwrap_or(bar_end);
    let n_bars = declared_bars.max(bar_end);
    if !proposal.headers.contains_key("bars") && n_bars > 0 {
        proposal.headers.insert("bars".into(), n_bars.to_string());
    }

    for inst in &proposal.instruments {
        let mut dynamic = "mf".to_string();
        for bar in 1..=n_bars {
            let Some(track_map) = bars.get(&bar) else {
                continue;
            };
            let Some(content) = track_map.get(&inst.abbrev) else {
                continue;
            };
            if content.trim() == "-" || content.trim().is_empty() {
                continue;
            }
            let tokens = split_attached_dynamics(&expand_pattern_repetitions(
                &tokenize_bar_content(content),
            ));
            let mut onset = Frac::zero();
            for raw_token in tokens {
                let Some(token) = parse_token(&raw_token) else {
                    continue;
                };
                match token.kind.as_str() {
                    "dynamic" => {
                        if let Some(value) = token.dyn_value {
                            dynamic = value;
                        }
                    }
                    "hairpin" => {}
                    "rest" => onset = onset.add(frac_from_f64(token.ql)),
                    "note" | "chord" | "unpitched" => {
                        let mut params = token.params;
                        let quote = quote_from_params(&mut params);
                        let state = EventState {
                            track: inst.abbrev.clone(),
                            bar,
                            onset_ql: onset,
                            dur_ql: frac_from_f64(token.ql),
                            kind: match token.kind.as_str() {
                                "note" => EventKind::Note,
                                "chord" => EventKind::Chord,
                                _ => EventKind::Unpitched,
                            },
                            pitches_midi_cents: token
                                .midis
                                .iter()
                                .map(|m| (m * 100.0).round() as i32)
                                .collect(),
                            gliss_target_midi_cents: token
                                .gliss_midi
                                .map(|m| (m * 100.0).round() as i32),
                            dynamic: Some(dynamic.clone()),
                            params,
                            flags: token.flags.into_iter().collect(),
                            lyric: lyric_from_token(&raw_token),
                            quote,
                        };
                        proposal.events.push(state);
                        onset = onset.add(frac_from_f64(token.ql));
                    }
                    _ => diagnostics.push(diag("unknown-token", raw_token)),
                }
            }
        }
    }
    (proposal, diagnostics)
}

fn split_headers(body: &str) -> Vec<&str> {
    let keys = ["tempo", "time", "key", "bars"];
    let mut cuts = Vec::new();
    for (i, _) in body.char_indices() {
        if i == 0 || !body.as_bytes()[i - 1].is_ascii_whitespace() {
            continue;
        }
        let rest = &body[i..];
        if keys.iter().any(|key| {
            rest.get(..key.len())
                .is_some_and(|head| head.eq_ignore_ascii_case(key))
                && rest
                    .get(key.len()..)
                    .is_some_and(|tail| tail.trim_start().starts_with(':'))
        }) {
            cuts.push(i);
        }
    }
    let mut out = Vec::new();
    let mut start = 0;
    for cut in cuts {
        out.push(body[start..cut].trim());
        start = cut;
    }
    out.push(body[start..].trim());
    out
}

// DIVERGENCE: the Python reference (mus.py parse_mus) accepts a section's
// trailing prose but discards it; this parser PRESERVES it in
// ProposalSection.prose. Rationale: prose is part of the score's rhetoric
// (the check contract carries it too), and reduction must be able to write
// it back — dropping it would break the round-trip law for every score in
// the corpus that annotates its sections.
fn parse_section(body: &str) -> Option<ProposalSection> {
    let body = body.strip_prefix("section")?.strip_prefix(':')?.trim();
    let open = body.rfind('[')?;
    let close = body[open..].find(']')? + open;
    let range = &body[open + 1..close];
    let (from, to) = range.split_once('-')?;
    let from_bar = from.trim().parse().ok()?;
    let to_bar = to.trim().parse().ok()?;
    let name = body[..open].trim().to_string();
    let prose = body[close + 1..]
        .trim()
        .trim_start_matches(['—', '–', '-'])
        .trim()
        .to_string();
    if let Some((head, tail)) = name.split_once('—') {
        let name = head.trim().to_string();
        return Some(ProposalSection {
            name,
            from_bar,
            to_bar,
            prose: Some(format!("{} {}", tail.trim(), prose).trim().into()),
        });
    }
    Some(ProposalSection {
        name,
        from_bar,
        to_bar,
        prose: (!prose.is_empty()).then_some(prose),
    })
}

fn parse_instrument(line: &str) -> Option<ProposalInstrument> {
    let (abbr, rest) = line.split_once('=')?;
    let open = rest.rfind('(')?;
    let close = rest.rfind(')')?;
    let name = rest[..open].trim();
    let inside = &rest[open + 1..close];
    let mut parts = inside.split(',').map(str::trim);
    let clef = parts.next().unwrap_or("treble").to_string();
    let mut params = BTreeMap::new();
    for part in parts {
        if let Some((key, value)) = part.split_once('=') {
            params.insert(key.trim().to_ascii_lowercase(), value.trim().into());
        }
    }
    Some(ProposalInstrument {
        abbrev: abbr.trim().into(),
        name: name.into(),
        clef,
        params,
    })
}

fn instrument_abbrevs(lines: &[String]) -> Vec<String> {
    lines
        .iter()
        .filter_map(|line| line.split_once('=').map(|(a, _)| a.trim().to_string()))
        .collect()
}

fn parse_bar_line(line: &str) -> Option<(u32, u32, Vec<String>, &str)> {
    let body = line.trim();
    let after = body
        .strip_prefix("bar ")
        .or_else(|| body.strip_prefix("bars "))?;
    let (head, rest) = after.split_once(':')?;
    // Inline changes ride the head (`bar 11 [tempo=88]:`, `bars 2-4 [time=3/4]:`).
    // The bracket group must come OFF before endpoint parsing — parsing the
    // endpoint first fed "2 [tempo=88]" to parse() and silently dropped the
    // whole line (Terra finding, run wf_317a71eb).
    let (range_part, changes) = if let Some(open) = head.find('[') {
        let close = head[open..].find(']')? + open;
        (
            head[..open].trim(),
            head[open + 1..close]
                .split(',')
                .map(|s| s.trim().to_string())
                .collect(),
        )
    } else {
        (head.trim(), Vec::new())
    };
    let (from, to) = if let Some((a, b)) = range_part.split_once('-') {
        (a.trim().parse().ok()?, b.trim().parse().ok()?)
    } else {
        (range_part.parse().ok()?, range_part.parse().ok()?)
    };
    let content = rest;
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
    let mut result = BTreeMap::new();
    for (i, (_, value_start, abbr)) in positions.iter().enumerate() {
        let end = positions
            .get(i + 1)
            .map(|(start, _, _)| *start)
            .unwrap_or(content.len());
        result.insert(abbr.clone(), content[*value_start..end].trim().to_string());
    }
    result
}

fn quote_from_params(params: &mut BTreeMap<String, String>) -> Option<Quote> {
    let gest_key = params.remove("gest")?;
    let layer = if params.remove("glayer").as_deref() == Some("octave") {
        QuoteLayer::Octave
    } else {
        QuoteLayer::Resolved
    };
    let gsrc_raw = params.remove("gsrc").as_deref() == Some("raw");
    Some(Quote {
        target_iri: None,
        gest_key,
        layer,
        gsrc_raw,
    })
}

fn lyric_from_token(token: &str) -> Option<String> {
    let start = token.find('"')?;
    let end = token[start + 1..].find('"')? + start + 1;
    Some(token[start + 1..end].into())
}

fn frac_from_f64(value: f64) -> Frac {
    if value == 0.0 {
        return Frac::zero();
    }
    let mut best = (value.round() as i64, 1i64, f64::INFINITY);
    for den in 1..=4096i64 {
        let num = (value * den as f64).round() as i64;
        let error = (num as f64 / den as f64 - value).abs();
        if error < best.2 {
            best = (num, den, error);
        }
    }
    Frac::new(best.0, best.1)
}

/// Deterministically mint positional ops so a proposal can use the existing
/// graph reducer. This is a W-B test/adaptor seam; W-C owns real lineage
/// matching and must not infer identity from this helper.
pub fn adopt(proposal: &Proposal) -> ScoreGraph {
    let mut log = OpLog::new();
    let mut seq = 1u64;
    log.append(
        "mus-text",
        seq,
        OpBody::ScoreInit {
            title: proposal.title.clone(),
        },
    );
    seq += 1;
    for (key, value) in &proposal.headers {
        log.append(
            "mus-text",
            seq,
            OpBody::SetHeader {
                key: key.clone(),
                value: value.clone(),
            },
        );
        seq += 1;
    }
    for (key, value) in &proposal.performance {
        log.append(
            "mus-text",
            seq,
            OpBody::AnnotatePerformance {
                key: key.clone(),
                value: value.clone(),
            },
        );
        seq += 1;
    }
    for inst in &proposal.instruments {
        log.append(
            "mus-text",
            seq,
            OpBody::DeclareInstrument {
                abbrev: inst.abbrev.clone(),
                name: inst.name.clone(),
                clef: inst.clef.clone(),
                params: inst.params.clone(),
            },
        );
        seq += 1;
    }
    for section in &proposal.sections {
        log.append(
            "mus-text",
            seq,
            OpBody::AddSection {
                name: section.name.clone(),
                from_bar: section.from_bar,
                to_bar: section.to_bar,
                prose: section.prose.clone(),
            },
        );
        seq += 1;
    }
    // Add events after declarations, preserving proposal position as the
    // deterministic minting sequence.
    let mut event_log = log;
    for state in &proposal.events {
        event_log.append(
            "mus-text",
            seq,
            OpBody::AddEvent {
                state: state.clone(),
            },
        );
        seq += 1;
    }
    let mut graph = mus_graph::project(&event_log);
    graph.inline_changes = proposal.bar_changes.clone();
    graph.texts = proposal.texts.clone();
    graph
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_dynamic_rest_lyric_quote_and_inline_change() {
        let text = "# score: t\n# bars: 1\n# instruments:\n#   v = voice (treble, voice=bright)\nbar 1 [tempo=88]: v={p} {mf} C4q\"la\" Rq <E4 G4>q[gest=h1,gsrc=raw]\n";
        let p = parse_score(text).unwrap();
        assert_eq!(p.title, "t");
        assert_eq!(p.bar_changes[&1], vec!["tempo=88"]);
        assert_eq!(p.events.len(), 2);
        assert_eq!(p.events[0].dynamic.as_deref(), Some("mf"));
        assert_eq!(p.events[0].lyric.as_deref(), Some("la"));
        assert_eq!(p.events[1].quote.as_ref().unwrap().gest_key, "h1");
        assert_eq!(p.events[1].onset_ql, Frac::new(2, 1));
    }

    #[test]
    fn parser_is_tolerant_of_prose_and_range_bars() {
        let text = "# score: t\n# time: 3/4\n# bars: 2\n# instruments:\n#   v = voice (treble)\n# prose: tempo: not a header\n# section: a [1-2] — words\nbars 1-2: v=C4q\n";
        let p = parse_score(text).unwrap();
        assert_eq!(p.sections[0].prose.as_deref(), Some("words"));
        assert_eq!(p.events.len(), 2);
    }

    #[test]
    fn range_bars_carry_inline_changes() {
        // Regression for the Terra finding (run wf_317a71eb): the endpoint
        // was parsed before the bracket came off, so this exact line form
        // silently vanished.
        let text = "# score: t\n# bars: 3\n# instruments:\n#   v = voice (treble)\nbars 2-3 [tempo=88, time=3/4]: v=C4q\n";
        let p = parse_score(text).unwrap();
        assert_eq!(p.bar_changes[&2], vec!["tempo=88", "time=3/4"]);
        assert_eq!(p.bar_changes[&3], vec!["tempo=88", "time=3/4"]);
        assert_eq!(p.events.iter().filter(|e| e.bar == 2).count(), 1);
        assert_eq!(p.events.iter().filter(|e| e.bar == 3).count(), 1);
    }

    #[test]
    fn parse_score_lossy_preserves_valid_events_around_bad_input() {
        let text = "# score: tolerant\n# summary: keeps going\n# bars: 1\n# instruments:\n#   v = voice (treble)\nbar 1: v=C4q definitely-not-a-token D4q\n";
        let (proposal, diagnostics) = parse_score_lossy(text);
        assert!(
            diagnostics.is_empty(),
            "token lossiness belongs to the check face"
        );
        assert_eq!(proposal.title, "tolerant");
        assert_eq!(proposal.headers["summary"], "keeps going");
        assert_eq!(proposal.events.len(), 2);
        assert_eq!(proposal.events[0].bar, 1);
        assert_eq!(proposal.events[1].pitches_midi_cents, vec![6200]);
    }

    #[test]
    fn tacet_fills_each_declared_track_without_creating_events() {
        let text = "# score: rests\n# bars: 3\n# instruments:\n#   a = voice (treble)\n#   b = percussion (perc)\nbar 1: tacet\nbars 2-3: a=C4q b=Xe\n";
        let (proposal, diagnostics) = parse_score_lossy(text);
        assert!(diagnostics.is_empty());
        assert_eq!(proposal.headers["bars"], "3");
        assert_eq!(proposal.events.len(), 4);
        assert!(proposal.events.iter().all(|event| event.bar >= 2));
        assert_eq!(
            proposal
                .events
                .iter()
                .filter(|event| event.track == "a")
                .count(),
            2
        );
        assert_eq!(
            proposal
                .events
                .iter()
                .filter(|event| event.track == "b")
                .count(),
            2
        );
    }

    #[test]
    fn contested_bodies_refuse_text_reduction() {
        // The text face cannot write >1 head per lineage (mus:Take reserved);
        // it must refuse loudly, never silently pick.
        use mus_oplog::{EventKind, EventState, LineageId, OpBody, OpLog};
        fn state(mc: i32) -> EventState {
            EventState {
                track: "v".into(),
                bar: 1,
                onset_ql: Frac::new(0, 1),
                dur_ql: Frac::new(1, 1),
                kind: EventKind::Note,
                pitches_midi_cents: vec![mc],
                gliss_target_midi_cents: None,
                dynamic: None,
                params: Default::default(),
                flags: Default::default(),
                lyric: None,
                quote: None,
            }
        }
        let mut base = OpLog::new();
        base.append("v", 1, OpBody::ScoreInit { title: "t".into() });
        base.append(
            "v",
            2,
            OpBody::SetHeader {
                key: "bars".into(),
                value: "1".into(),
            },
        );
        base.append(
            "v",
            3,
            OpBody::DeclareInstrument {
                abbrev: "v".into(),
                name: "voice".into(),
                clef: "treble".into(),
                params: Default::default(),
            },
        );
        let minted = base.append("v", 4, OpBody::AddEvent { state: state(6000) });
        let lineage = LineageId(minted.0.clone());
        let basis = state(6000).version_id();
        let mut a = base.clone();
        let mut b = base.clone();
        a.append(
            "agent-a",
            1,
            OpBody::SupersedeEvent {
                lineage: lineage.clone(),
                basis: basis.clone(),
                state: state(6100),
            },
        );
        b.append(
            "agent-b",
            1,
            OpBody::SupersedeEvent {
                lineage,
                basis,
                state: state(6300),
            },
        );
        a.merge(&b);
        let contested = mus_graph::project(&a);
        match mus_graph::reduce_to_text(&contested) {
            Err(mus_graph::ReduceError::Contested(ids)) => assert_eq!(ids.len(), 1),
            other => panic!("expected Contested refusal, got {other:?}"),
        }
    }

    #[test]
    fn round_trip_law() {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../..")
            .join("aigua");
        let mut paths = std::fs::read_dir(root)
            .unwrap()
            .filter_map(|entry| {
                let path = entry.ok()?.path();
                (path.extension().and_then(|s| s.to_str()) == Some("mus")).then_some(path)
            })
            .collect::<Vec<_>>();
        paths.sort();
        assert_eq!(paths.len(), 13);
        for path in paths {
            let source = std::fs::read_to_string(&path).unwrap();
            let p1 = parse_score(&source)
                .unwrap_or_else(|diags| panic!("{}: {diags:?}", path.display()));
            let graph = adopt(&p1);
            let reduced = mus_graph::reduce_to_text(&graph)
                .unwrap_or_else(|err| panic!("{}: {err:?}", path.display()));
            let p2 = parse_score(&reduced)
                .unwrap_or_else(|diags| panic!("reduced {}: {diags:?}\n{reduced}", path.display()));
            assert_eq!(p1.title, p2.title, "{}", path.display());
            assert_eq!(p1.headers, p2.headers, "{}", path.display());
            assert_eq!(p1.performance, p2.performance, "{}", path.display());
            assert_eq!(p1.instruments, p2.instruments, "{}", path.display());
            assert_eq!(p1.sections, p2.sections, "{}", path.display());
            assert_eq!(p1.texts, p2.texts, "{}", path.display());
            assert_eq!(p1.bar_changes, p2.bar_changes, "{}", path.display());
            assert_eq!(p1.events, p2.events, "{}", path.display());
        }
    }
}
