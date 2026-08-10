//! mus-graph — the HINGE: project(op-log) → ScoreGraph, the operative
//! in-memory body of a Score, plus the first face (canonical text reduction).
//! Design: `sophia/plans/mus-mo-language-20260809.md` §2.
//!
//! Laws enforced and tested here:
//!
//! - **Projection is a pure fold over the log's total order.** Two merged
//!   replicas project identical bodies (inherited convergence — the
//!   disposability-oracle stance).
//! - **Forks are represented, never resolved (R4/R8).** A `SupersedeEvent`
//!   whose `basis` is not among a lineage's current heads does not lose or
//!   win; it ADDS a head and marks the lineage contested. Resolution is a
//!   future op whose basis names the head it supersedes — explicit
//!   testimony.
//! - **A face must name its choice.** `chosen_head` picks the head latest
//!   in the log's own total order ((lamport, actor, seq, id)) — and every face
//!   that uses it (the render receipt above all) is expected to SAY so.
//! - **Reduction is canonical.** One formatter, one spacing, sorted params —
//!   so `reduce ∘ project` is stable and text diffs are semantic diffs.
//!   v0 reduces the structures the smoke corpus needs; unformattable
//!   constructs fail LOUDLY (never silently dropped — the repo's oldest
//!   lesson).

use mus_oplog::{EventKind, EventState, Frac, LineageId, Op, OpBody, OpId, OpLog, VersionId};
use std::collections::BTreeMap;

pub mod timing;

// ------------------------------------------------------------------- body

#[derive(Debug, Clone, PartialEq)]
pub struct VersionRec {
    pub version: VersionId,
    /// None = retracted (a tombstone head).
    pub state: Option<EventState>,
    pub op: OpId,
    pub lamport: u64,
    pub actor: String,
    pub seq: u64,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct Lineage {
    pub heads: Vec<VersionRec>,
    pub contested: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct InstrumentDecl {
    pub abbrev: String,
    pub name: String,
    pub clef: String,
    pub params: BTreeMap<String, String>,
    pub declared_by: OpId,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Section {
    pub name: String,
    pub from_bar: u32,
    pub to_bar: u32,
    pub prose: Option<String>,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct ScoreGraph {
    pub title: String,
    pub headers: BTreeMap<String, String>,
    pub performance: BTreeMap<String, String>,
    /// Inline bar changes belong to the text face rather than an event, but
    /// are retained by the graph-shaped proposal so reduction can reproduce
    /// tempo/meter changes exactly.
    pub inline_changes: BTreeMap<u32, Vec<String>>,
    pub texts: BTreeMap<u32, Vec<String>>,
    pub instruments: Vec<InstrumentDecl>,
    pub sections: Vec<Section>,
    pub lineages: BTreeMap<LineageId, Lineage>,
}

impl Lineage {
    /// The deterministic head a face may perform: latest in the log's own
    /// total order. A face using this on a contested lineage must
    /// depict/record that it chose.
    pub fn chosen_head(&self) -> Option<&VersionRec> {
        // The SAME total order as log projection: (lamport, actor, seq, id).
        // "Causally latest" = latest in the one order every replica already
        // agrees on — deterministic and explainable, never hash-arbitrary.
        self.heads.iter().max_by(|a, b| {
            (a.lamport, &a.actor, a.seq, &a.op).cmp(&(b.lamport, &b.actor, b.seq, &b.op))
        })
    }
}

impl ScoreGraph {
    pub fn contested_lineages(&self) -> Vec<&LineageId> {
        self.lineages
            .iter()
            .filter(|(_, l)| l.contested)
            .map(|(id, _)| id)
            .collect()
    }

    /// Current sounding events: chosen head per lineage, retractions absent.
    pub fn current_events(&self) -> Vec<(&LineageId, &EventState, &VersionRec)> {
        let mut out: Vec<(&LineageId, &EventState, &VersionRec)> = self
            .lineages
            .iter()
            .filter_map(|(id, l)| {
                l.chosen_head()
                    .and_then(|h| h.state.as_ref().map(|s| (id, s, h)))
            })
            .collect();
        out.sort_by(|a, b| {
            (a.1.bar, &a.1.track, a.1.onset_ql, &a.0).cmp(&(
                b.1.bar,
                &b.1.track,
                b.1.onset_ql,
                &b.0,
            ))
        });
        out
    }
}

/// Count events-per-extension-param across current events and instrument
/// declarations, given a core-classifier (provided by `mus-vocab`; the
/// closure keeps both crates leaf-clean — WA's dependency-direction rule).
pub fn extension_usage(g: &ScoreGraph, is_core: &dyn Fn(&str) -> bool) -> BTreeMap<String, u32> {
    let mut out: BTreeMap<String, u32> = BTreeMap::new();
    for (_, state, _) in g.current_events() {
        for key in state.params.keys() {
            if !is_core(key) {
                *out.entry(key.clone()).or_default() += 1;
            }
        }
    }
    for inst in &g.instruments {
        for key in inst.params.keys() {
            if key != "voice" && key != "sample" && key != "mode" && !is_core(key) {
                *out.entry(key.clone()).or_default() += 1;
            }
        }
    }
    out
}

// -------------------------------------------------------------- projection

pub fn project(log: &OpLog) -> ScoreGraph {
    let mut g = ScoreGraph::default();
    for op in log.ordered() {
        fold_op(&mut g, op);
    }
    g
}

fn fold_op(g: &mut ScoreGraph, op: &Op) {
    match &op.body {
        OpBody::ScoreInit { title } => g.title = title.clone(),
        OpBody::SetHeader { key, value } => {
            g.headers.insert(key.clone(), value.clone());
        }
        OpBody::AnnotatePerformance { key, value } => {
            g.performance.insert(key.clone(), value.clone());
        }
        OpBody::DeclareInstrument {
            abbrev,
            name,
            clef,
            params,
        } => {
            let declaration = InstrumentDecl {
                abbrev: abbrev.clone(),
                name: name.clone(),
                clef: clef.clone(),
                params: params.clone(),
                declared_by: op.id.clone(),
            };
            // Instruments are set/replace declarations keyed by abbreviation;
            // unlike sections, they are not an ordered repeated list.
            if let Some(existing) = g.instruments.iter_mut().find(|i| i.abbrev == *abbrev) {
                *existing = declaration;
            } else {
                g.instruments.push(declaration);
            }
        }
        OpBody::AddSection {
            name,
            from_bar,
            to_bar,
            prose,
        } => {
            g.sections.push(Section {
                name: name.clone(),
                from_bar: *from_bar,
                to_bar: *to_bar,
                prose: prose.clone(),
            });
        }
        OpBody::AddEvent { state } => {
            let lineage = LineageId(op.id.0.clone());
            let rec = VersionRec {
                version: state.version_id(),
                state: Some(state.clone()),
                op: op.id.clone(),
                lamport: op.lamport,
                actor: op.actor.clone(),
                seq: op.seq,
            };
            g.lineages.insert(
                lineage,
                Lineage {
                    heads: vec![rec],
                    contested: false,
                },
            );
        }
        OpBody::SetBarChanges { bar, changes } => {
            g.inline_changes.insert(*bar, changes.clone());
        }
        OpBody::AddText { bar, prose } => {
            g.texts.entry(*bar).or_default().push(prose.clone());
        }
        OpBody::SupersedeEvent {
            lineage,
            basis,
            state,
        } => {
            supersede(g, op, lineage, basis, Some(state.clone()));
        }
        OpBody::RetractEvent { lineage, basis } => {
            supersede(g, op, lineage, basis, None);
        }
    }
}

fn supersede(
    g: &mut ScoreGraph,
    op: &Op,
    lineage: &LineageId,
    basis: &VersionId,
    state: Option<EventState>,
) {
    let entry = g.lineages.entry(lineage.clone()).or_default();
    let rec = VersionRec {
        version: state
            .as_ref()
            .map(|s| s.version_id())
            .unwrap_or_else(|| VersionId(format!("retracted:{}", op.id.0))),
        state,
        op: op.id.clone(),
        lamport: op.lamport,
        actor: op.actor.clone(),
        seq: op.seq,
    };
    if let Some(pos) = entry.heads.iter().position(|h| &h.version == basis) {
        // The edit saw a current head: replace it. Head count unchanged.
        entry.heads[pos] = rec;
    } else {
        // The edit's basis is no longer (or never was) a head — a concurrent
        // edit got there first. REPRESENT the fork (R4): add a head, flag it.
        entry.heads.push(rec);
        entry.contested = true;
    }
}

// ------------------------------------------------ face: canonical reduction

/// Canonical header emission order; extras follow alphabetically.
const HEADER_ORDER: &[&str] = &[
    "summary",
    "tempo",
    "time",
    "key",
    "bars",
    "tuning",
    "pack",
    "gestures",
    "tape",
    "swing",
    "reverb",
    "master",
    "sidechain",
];

#[derive(Debug)]
pub enum ReduceError {
    /// v0 formatter met a construct it cannot yet write. LOUD by design.
    Unformattable(String),
    /// The TEXT face refuses contested bodies: mus syntax has no way to
    /// write >1 head per lineage yet (mus:Take is reserved, unimplemented —
    /// R4). Faces that CAN choose a head must name their choice; this one
    /// cannot, so it fails loudly with every contested lineage listed.
    Contested(Vec<String>),
}

pub fn reduce_to_text(g: &ScoreGraph) -> Result<String, ReduceError> {
    let contested = g.contested_lineages();
    if !contested.is_empty() {
        return Err(ReduceError::Contested(
            contested.iter().map(|l| l.0.clone()).collect(),
        ));
    }
    let mut out = String::new();
    out.push_str(&format!("# score: {}\n", g.title));
    let mut emitted: Vec<&str> = Vec::new();
    for key in HEADER_ORDER {
        if let Some(v) = g.headers.get(*key) {
            out.push_str(&format!("# {key}: {v}\n"));
            emitted.push(key);
        }
    }
    for (key, v) in &g.headers {
        if !emitted.contains(&key.as_str()) {
            out.push_str(&format!("# {key}: {v}\n"));
        }
    }
    for (key, v) in &g.performance {
        out.push_str(&format!("# {key}: {v}\n"));
    }
    if !g.instruments.is_empty() {
        out.push_str("\n# instruments:\n");
        for inst in &g.instruments {
            let mut items = vec![inst.clef.clone()];
            for (k, v) in &inst.params {
                items.push(format!("{k}={v}"));
            }
            out.push_str(&format!(
                "#   {} = {} ({})\n",
                inst.abbrev,
                inst.name,
                items.join(", ")
            ));
        }
    }
    for s in &g.sections {
        let prose = s
            .prose
            .as_deref()
            .map(|p| format!(" — {p}"))
            .unwrap_or_default();
        out.push_str(&format!(
            "\n# section: {} [{}-{}]{}\n",
            s.name, s.from_bar, s.to_bar, prose
        ));
    }
    for (bar, texts) in &g.texts {
        for prose in texts {
            out.push_str(&format!("# text @b{bar}: {prose}\n"));
        }
    }

    let bars: u32 = g
        .headers
        .get("bars")
        .and_then(|b| b.parse().ok())
        .unwrap_or_else(|| {
            g.current_events()
                .iter()
                .map(|(_, s, _)| s.bar)
                .max()
                .unwrap_or(0)
        });

    let meter = meter_map(g);
    let mut bar_lengths = BTreeMap::new();
    let mut current_meter = Frac::new(4, 1);
    for bar in 1..=bars {
        if let Some(value) = meter.get(&bar) {
            current_meter = *value;
        }
        bar_lengths.insert(bar, current_meter);
    }

    let mut by_track: BTreeMap<String, BTreeMap<u32, Vec<&EventState>>> = BTreeMap::new();
    for (_, state, _) in g.current_events() {
        by_track
            .entry(state.track.clone())
            .or_default()
            .entry(state.bar)
            .or_default()
            .push(state);
    }
    // Every event's track must be declared: reduction iterates instruments,
    // so an undeclared track would be SILENTLY dropped — the exact failure
    // mode canonical reduction exists to rule out (Terra finding).
    for track in by_track.keys() {
        if !g.instruments.iter().any(|i| &i.abbrev == track) {
            return Err(ReduceError::Unformattable(format!(
                "events on undeclared track '{track}'"
            )));
        }
    }
    let mut cells_by_bar: BTreeMap<u32, Vec<(usize, String)>> = BTreeMap::new();
    for (idx, instrument) in g.instruments.iter().enumerate() {
        let Some(events_by_bar) = by_track.get(&instrument.abbrev) else {
            continue;
        };
        let mut dynamic = "mf".to_string();
        for bar in 1..=bars {
            let Some(events) = events_by_bar.get(&bar) else {
                continue;
            };
            let content = format_track_bar(
                events,
                *bar_lengths.get(&bar).unwrap_or(&Frac::new(4, 1)),
                &mut dynamic,
            )?;
            cells_by_bar.entry(bar).or_default().push((idx, content));
        }
    }

    out.push('\n');
    for bar in 1..=bars {
        let Some(cells) = cells_by_bar.get(&bar) else {
            let changes = format_bar_changes(g.inline_changes.get(&bar));
            out.push_str(&format!("bar {bar}{changes}: tacet\n"));
            continue;
        };
        let cells = cells
            .iter()
            .map(|(idx, content)| format!("{}={content}", g.instruments[*idx].abbrev))
            .collect::<Vec<_>>();
        let changes = format_bar_changes(g.inline_changes.get(&bar));
        out.push_str(&format!("bar {bar}{changes}: {}\n", cells.join("  ")));
    }
    Ok(out)
}

fn format_bar_changes(changes: Option<&Vec<String>>) -> String {
    changes
        .map(|items| format!(" [{}]", items.join(", ")))
        .unwrap_or_default()
}

fn format_track_bar(
    events: &[&EventState],
    bar_qlen: Frac,
    dynamic: &mut String,
) -> Result<String, ReduceError> {
    let mut toks: Vec<String> = Vec::new();
    let mut cursor = Frac::zero();
    for ev in events {
        if ev.onset_ql < cursor {
            return Err(ReduceError::Unformattable(
                "overlapping events in one track-bar".into(),
            ));
        }
        if ev.onset_ql > cursor {
            toks.push(format!("R{}", duration_code(sub(ev.onset_ql, cursor))?));
        }
        if let Some(value) = &ev.dynamic {
            if value != dynamic {
                toks.push(format!("{{{value}}}"));
                *dynamic = value.clone();
            }
        }
        toks.push(event_token(ev)?);
        cursor = ev.onset_ql.add(ev.dur_ql);
    }
    if cursor < bar_qlen {
        toks.push(format!("R{}", duration_code(sub(bar_qlen, cursor))?));
    }
    Ok(toks.join(" "))
}

fn sub(a: Frac, b: Frac) -> Frac {
    a.add(Frac::new(-b.num, b.den))
}

fn event_token(ev: &EventState) -> Result<String, ReduceError> {
    let head = match ev.kind {
        EventKind::Unpitched => "X".to_string(),
        EventKind::Note => pitch_name(
            *ev.pitches_midi_cents
                .first()
                .ok_or_else(|| ReduceError::Unformattable("note has no pitch".into()))?,
        ),
        EventKind::Chord => format!(
            "<{}>",
            ev.pitches_midi_cents
                .iter()
                .map(|p| pitch_name(*p))
                .collect::<Vec<_>>()
                .join(" ")
        ),
    };
    let mut tok = format!("{head}{}", duration_code(ev.dur_ql)?);
    if let Some(g) = ev.gliss_target_midi_cents {
        tok.push_str(&format!("->{}", pitch_name(g)));
    }
    let mut items: Vec<String> = Vec::new();
    if let Some(q) = &ev.quote {
        items.push(format!("gest={}", q.gest_key));
        if matches!(q.layer, mus_oplog::QuoteLayer::Octave) {
            items.push("glayer=octave".into());
        }
        if q.gsrc_raw {
            items.push("gsrc=raw".into());
        }
    }
    for (k, v) in &ev.params {
        items.push(format!("{k}={v}"));
    }
    for f in &ev.flags {
        items.push(f.clone());
    }
    if !items.is_empty() {
        tok.push_str(&format!("[{}]", items.join(",")));
    }
    if let Some(l) = &ev.lyric {
        tok.push_str(&format!("\"{l}\""));
    }
    Ok(tok)
}

const NOTE_NAMES: [&str; 12] = [
    "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
];

fn pitch_name(midi_cents: i32) -> String {
    let midi = midi_cents.div_euclid(100);
    let cents = midi_cents.rem_euclid(100);
    // Canonical form keeps cents in [-49, +50] around the nearest semitone.
    let (midi, cents) = if cents > 50 {
        (midi + 1, cents - 100)
    } else {
        (midi, cents)
    };
    let name = NOTE_NAMES[(midi.rem_euclid(12)) as usize];
    let octave = midi.div_euclid(12) - 1;
    if cents == 0 {
        format!("{name}{octave}")
    } else {
        format!("{name}{octave}{cents:+}")
    }
}

fn duration_code(ql: Frac) -> Result<String, ReduceError> {
    let table: &[(i64, i64, &str)] = &[
        (8, 1, "ww"),
        (6, 1, "w."),
        (4, 1, "w"),
        (3, 1, "h."),
        (2, 1, "h"),
        (3, 2, "q."),
        (1, 1, "q"),
        (3, 4, "e."),
        (1, 2, "e"),
        (3, 8, "s."),
        (1, 4, "s"),
        (1, 8, "t"),
        (4, 3, "h3"),
        (2, 3, "q3"),
        (1, 3, "e3"),
        (1, 6, "s3"),
        (1, 12, "t3"),
        (1, 24, "x3"),
    ];
    for (n, d, code) in table {
        if ql == Frac::new(*n, *d) {
            return Ok((*code).to_string());
        }
    }
    // Tied composites: greedy decomposition, longest first (canonical).
    for (n, d, code) in table {
        let piece = Frac::new(*n, *d);
        if piece < ql {
            let rest = sub(ql, piece);
            if let Ok(rest_code) = duration_code(rest) {
                return Ok(format!("{code}~{rest_code}"));
            }
        }
    }
    Err(ReduceError::Unformattable(format!(
        "duration {}/{} ql",
        ql.num, ql.den
    )))
}

/// Read the score's time-signature change list and inline time changes. The
/// old reducer's fixed 4/4 assumption was a silent semantic loss; an absent
/// map still has the reference default of 4/4.
fn meter_map(g: &ScoreGraph) -> BTreeMap<u32, Frac> {
    let mut out = BTreeMap::new();
    if let Some(raw) = g.headers.get("time") {
        for piece in raw.split('→') {
            let value = piece.split('(').next().unwrap_or(piece).trim();
            if let Some(meter) = parse_meter(value) {
                let bar = piece
                    .find("(b")
                    .and_then(|i| piece[i + 2..].split(')').next())
                    .and_then(|s| s.parse().ok())
                    .unwrap_or(1);
                out.insert(bar, meter);
            }
        }
    }
    for (bar, changes) in &g.inline_changes {
        for change in changes {
            if let Some(value) = change
                .strip_prefix("time=")
                .or_else(|| change.strip_prefix("time ="))
            {
                if let Some(meter) = parse_meter(value.trim()) {
                    out.insert(*bar, meter);
                }
            }
        }
    }
    out
}

fn parse_meter(value: &str) -> Option<Frac> {
    let (num, den) = value.trim().split_once('/')?;
    let num: i64 = num.trim().parse().ok()?;
    let den: i64 = den.trim().parse().ok()?;
    if num > 0 && den > 0 {
        Some(Frac::new(num * 4, den))
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use mus_oplog::{OpBody, QuoteLayer};
    use std::collections::{BTreeMap, BTreeSet};

    fn ev(track: &str, bar: u32, onset: (i64, i64), dur: (i64, i64), mc: i32) -> EventState {
        EventState {
            track: track.into(),
            bar,
            onset_ql: Frac::new(onset.0, onset.1),
            dur_ql: Frac::new(dur.0, dur.1),
            kind: EventKind::Note,
            pitches_midi_cents: vec![mc],
            gliss_target_midi_cents: None,
            dynamic: None,
            params: BTreeMap::new(),
            flags: BTreeSet::new(),
            lyric: None,
            quote: None,
        }
    }

    fn smoke_log() -> (OpLog, OpId) {
        let mut log = OpLog::new();
        log.append(
            "vera",
            1,
            OpBody::ScoreInit {
                title: "smoke".into(),
            },
        );
        log.append(
            "vera",
            2,
            OpBody::SetHeader {
                key: "tempo".into(),
                value: "60".into(),
            },
        );
        log.append(
            "vera",
            3,
            OpBody::SetHeader {
                key: "time".into(),
                value: "4/4".into(),
            },
        );
        log.append(
            "vera",
            4,
            OpBody::SetHeader {
                key: "bars".into(),
                value: "2".into(),
            },
        );
        let mut params = BTreeMap::new();
        params.insert("voice".into(), "glide".into());
        log.append(
            "vera",
            5,
            OpBody::DeclareInstrument {
                abbrev: "gl".into(),
                name: "glide".into(),
                clef: "treble".into(),
                params,
            },
        );
        // A5 = midi 81, B5 = 83, D6+22 = 86.22
        let a = log.append(
            "vera",
            6,
            OpBody::AddEvent {
                state: ev("gl", 1, (0, 1), (1, 1), 8100),
            },
        );
        log.append(
            "vera",
            7,
            OpBody::AddEvent {
                state: ev("gl", 1, (1, 1), (1, 1), 8300),
            },
        );
        log.append(
            "vera",
            8,
            OpBody::AddEvent {
                state: ev("gl", 2, (0, 1), (2, 1), 8622),
            },
        );
        (log, a)
    }

    #[test]
    fn end_to_end_project_and_reduce() {
        let (log, _) = smoke_log();
        let g = project(&log);
        assert_eq!(g.title, "smoke");
        assert_eq!(g.current_events().len(), 3);
        assert!(g.contested_lineages().is_empty());
        let text = reduce_to_text(&g).unwrap();
        let expected = "\
# score: smoke
# tempo: 60
# time: 4/4
# bars: 2

# instruments:
#   gl = glide (treble, voice=glide)

bar 1: gl=A5q B5q Rh
bar 2: gl=D6+22h Rh
";
        assert_eq!(text, expected);
    }

    #[test]
    fn supersede_replaces_head_and_reduction_follows() {
        let (mut log, lineage_op) = smoke_log();
        let lineage = LineageId(lineage_op.0.clone());
        let basis = ev("gl", 1, (0, 1), (1, 1), 8100).version_id();
        log.append(
            "vera",
            9,
            OpBody::SupersedeEvent {
                lineage: lineage.clone(),
                basis,
                state: ev("gl", 1, (0, 1), (1, 1), 8600), // A5 → G#5? no: 8600 = midi 86 = D6
            },
        );
        let g = project(&log);
        assert!(!g.lineages[&lineage].contested);
        assert_eq!(g.lineages[&lineage].heads.len(), 1);
        let text = reduce_to_text(&g).unwrap();
        assert!(text.contains("bar 1: gl=D6q B5q Rh"));
    }

    #[test]
    fn concurrent_supersedes_fork_and_are_represented_not_resolved() {
        let (base, lineage_op) = smoke_log();
        let lineage = LineageId(lineage_op.0.clone());
        let basis = ev("gl", 1, (0, 1), (1, 1), 8100).version_id();
        let mut a = base.clone();
        let mut b = base.clone();
        a.append(
            "agent-a",
            1,
            OpBody::SupersedeEvent {
                lineage: lineage.clone(),
                basis: basis.clone(),
                state: ev("gl", 1, (0, 1), (1, 1), 8500),
            },
        );
        b.append(
            "agent-b",
            1,
            OpBody::SupersedeEvent {
                lineage: lineage.clone(),
                basis,
                state: ev("gl", 1, (0, 1), (1, 1), 8700),
            },
        );
        a.merge(&b);
        let g = project(&a);
        let l = &g.lineages[&lineage];
        assert!(l.contested, "a shared basis must fork loudly");
        assert_eq!(l.heads.len(), 2);
        // The chosen head is deterministic and named — agent-b's op sorts
        // after agent-a's at equal lamport, so it is the causal-latest pick.
        let chosen = l.chosen_head().unwrap();
        assert_eq!(chosen.state.as_ref().unwrap().pitches_midi_cents[0], 8700);
        // Merge order must not matter (projection inherits convergence).
        let mut b2 = base.clone();
        let mut a2 = base.clone();
        b2.append(
            "agent-b",
            1,
            OpBody::SupersedeEvent {
                lineage: lineage.clone(),
                basis: ev("gl", 1, (0, 1), (1, 1), 8100).version_id(),
                state: ev("gl", 1, (0, 1), (1, 1), 8700),
            },
        );
        a2.append(
            "agent-a",
            1,
            OpBody::SupersedeEvent {
                lineage: lineage.clone(),
                basis: ev("gl", 1, (0, 1), (1, 1), 8100).version_id(),
                state: ev("gl", 1, (0, 1), (1, 1), 8500),
            },
        );
        b2.merge(&a2);
        assert_eq!(project(&b2), g);
    }

    #[test]
    fn retraction_is_a_tombstone_head() {
        let (mut log, lineage_op) = smoke_log();
        let lineage = LineageId(lineage_op.0.clone());
        let basis = ev("gl", 1, (0, 1), (1, 1), 8100).version_id();
        log.append(
            "vera",
            9,
            OpBody::RetractEvent {
                lineage: lineage.clone(),
                basis,
            },
        );
        let g = project(&log);
        assert_eq!(g.current_events().len(), 2);
        let text = reduce_to_text(&g).unwrap();
        assert!(text.contains("bar 1: gl=Rq B5q Rh"));
    }

    #[test]
    fn quotes_and_ties_reduce_canonically() {
        let mut log = OpLog::new();
        log.append("vera", 1, OpBody::ScoreInit { title: "q".into() });
        log.append(
            "vera",
            2,
            OpBody::SetHeader {
                key: "bars".into(),
                value: "1".into(),
            },
        );
        log.append(
            "vera",
            3,
            OpBody::DeclareInstrument {
                abbrev: "te".into(),
                name: "tenor".into(),
                clef: "treble".into(),
                params: BTreeMap::new(),
            },
        );
        let mut st = ev("te", 1, (0, 1), (5, 2), 7900); // 2.5 ql → h~e
        st.quote = Some(mus_oplog::Quote {
            target_iri: Some("urn:sophia:mus:segment:sha256:abc".into()),
            gest_key: "h67".into(),
            layer: QuoteLayer::Resolved,
            gsrc_raw: true,
        });
        log.append("vera", 4, OpBody::AddEvent { state: st });
        let text = reduce_to_text(&project(&log)).unwrap();
        assert!(
            text.contains("te=G5h~e[gest=h67,gsrc=raw] Rq."),
            "got: {text}"
        );
    }

    #[test]
    fn reduction_uses_meter_changes_dynamic_state_and_cross_bar_events() {
        let mut log = OpLog::new();
        log.append(
            "vera",
            1,
            OpBody::ScoreInit {
                title: "meter".into(),
            },
        );
        log.append(
            "vera",
            2,
            OpBody::SetHeader {
                key: "bars".into(),
                value: "2".into(),
            },
        );
        log.append(
            "vera",
            3,
            OpBody::SetHeader {
                key: "time".into(),
                value: "3/4".into(),
            },
        );
        log.append(
            "vera",
            4,
            OpBody::DeclareInstrument {
                abbrev: "v".into(),
                name: "voice".into(),
                clef: "treble".into(),
                params: BTreeMap::new(),
            },
        );
        let mut first = ev("v", 1, (0, 1), (5, 1), 6000);
        first.dynamic = Some("p".into());
        first.gliss_target_midi_cents = Some(6200);
        first.lyric = Some("hold".into());
        log.append("vera", 5, OpBody::AddEvent { state: first });
        let mut second = ev("v", 2, (0, 1), (3, 1), 6200);
        second.dynamic = Some("f".into());
        log.append("vera", 6, OpBody::AddEvent { state: second });
        let mut graph = project(&log);
        graph.inline_changes.insert(2, vec!["time=2/4".into()]);
        let text = reduce_to_text(&graph).unwrap();
        assert!(
            text.contains("bar 1: v={p} C4w~q->D4\"hold\""),
            "got: {text}"
        );
        assert!(text.contains("bar 2 [time=2/4]: v={f} D4h."), "got: {text}");
    }
}
