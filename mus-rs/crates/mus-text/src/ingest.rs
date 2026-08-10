//! Reconcile a positional text proposal with the current graph.
//!
//! This is the only seam that recovers lineage from the text face. A tie is
//! represented as a conservative retract-plus-add plan and is reported to the
//! caller; it is never resolved by an arbitrary sort.

use crate::{Proposal, ProposalInstrument, ProposalSection};
use mus_graph::ScoreGraph;
use mus_oplog::{EventState, LineageId, OpBody, VersionId};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

/// Primary affinity weights. Metadata is deliberately weaker than the
/// sounding identity fields so a pitch edit and a bar move remain plausible.
pub const BAR_WEIGHT: i32 = 25;
pub const ONSET_WEIGHT: i32 = 30;
pub const PITCH_WEIGHT: i32 = 30;
pub const KIND_WEIGHT: i32 = 15;
pub const PARAM_WEIGHT: i32 = 5;
pub const FLAG_WEIGHT: i32 = 3;
pub const DYNAMIC_WEIGHT: i32 = 1;
pub const LYRIC_WEIGHT: i32 = 1;
pub const MIN_AFFINITY: i32 = 60;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum MatchKind {
    Exact,
    Affinity,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MatchRecord {
    pub proposal_index: usize,
    pub lineage: LineageId,
    pub score: i32,
    pub kind: MatchKind,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Ambiguity {
    pub track: String,
    pub proposal_indices: Vec<usize>,
    pub lineages: Vec<LineageId>,
    pub score: i32,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct IngestPlan {
    pub ops: Vec<OpBody>,
    pub matches: Vec<MatchRecord>,
    pub ambiguous: Vec<Ambiguity>,
}

#[derive(Debug, Clone)]
struct CurrentEvent {
    lineage: LineageId,
    version: VersionId,
    state: EventState,
    order: usize,
}

#[derive(Debug, Clone, Copy)]
struct Candidate {
    proposal: usize,
    current: usize,
    score: i32,
}

/// Diff a proposal against the chosen head of every current lineage.
/// `actor` and `seq_start` belong to the caller because operation identity is
/// minted by `OpLog::append`, not by this pure planning function.
pub fn diff_to_ops(
    graph: &ScoreGraph,
    proposal: &Proposal,
    actor: &str,
    seq_start: u64,
) -> IngestPlan {
    let _ = (actor, seq_start);
    let mut plan = IngestPlan::default();
    reconcile_metadata(graph, proposal, &mut plan.ops);

    let current = current_events(graph);
    let proposal_by_track = track_indices(&proposal.events);
    let current_by_track = current.iter().enumerate().fold(
        BTreeMap::<&str, Vec<usize>>::new(),
        |mut result, (index, event)| {
            result
                .entry(event.state.track.as_str())
                .or_default()
                .push(index);
            result
        },
    );
    let mut matched_proposals = BTreeSet::new();
    let mut matched_current = BTreeSet::new();

    // First pair exact states at the same per-track position. This is the
    // documented order-stability tiebreaker: with two truly identical
    // siblings, an edit at position 0 cannot steal position 1's lineage.
    for (proposal_index, state) in proposal.events.iter().enumerate() {
        let Some(proposal_positions) = proposal_by_track.get(state.track.as_str()) else {
            continue;
        };
        let ordinal = proposal_positions
            .iter()
            .position(|index| *index == proposal_index)
            .expect("proposal index must be present in its track index");
        let Some(current_indices) = current_by_track.get(state.track.as_str()) else {
            continue;
        };
        let same_position = current_indices.get(ordinal).copied();
        let exact = same_position
            .filter(|index| {
                !matched_current.contains(index) && current[*index].version == state.version_id()
            })
            .or_else(|| {
                current_indices.iter().copied().find(|index| {
                    !matched_current.contains(index)
                        && current[*index].version == state.version_id()
                })
            });
        if let Some(current_index) = exact {
            matched_proposals.insert(proposal_index);
            matched_current.insert(current_index);
            plan.matches.push(MatchRecord {
                proposal_index,
                lineage: current[current_index].lineage.clone(),
                score: affinity_score(&current[current_index].state, state),
                kind: MatchKind::Exact,
            });
        }
    }

    let mut candidates = Vec::new();
    for (track, proposal_indices) in &proposal_by_track {
        let Some(current_indices) = current_by_track.get(track) else {
            continue;
        };
        for proposal_index in proposal_indices {
            if matched_proposals.contains(proposal_index) {
                continue;
            }
            for current_index in current_indices {
                if matched_current.contains(current_index) {
                    continue;
                }
                let score = affinity_score(
                    &current[*current_index].state,
                    &proposal.events[*proposal_index],
                );
                if score >= MIN_AFFINITY {
                    candidates.push(Candidate {
                        proposal: *proposal_index,
                        current: *current_index,
                        score,
                    });
                }
            }
        }
    }

    let (ambiguous_proposals, ambiguous_current, ambiguities) =
        find_ambiguities(&candidates, &current);
    plan.ambiguous = ambiguities;

    let mut eligible: Vec<_> = candidates
        .into_iter()
        .filter(|candidate| {
            !ambiguous_proposals.contains(&candidate.proposal)
                && !ambiguous_current.contains(&candidate.current)
        })
        .collect();
    eligible.sort_by(|a, b| {
        b.score
            .cmp(&a.score)
            .then_with(|| a.proposal.cmp(&b.proposal))
            .then_with(|| current[a.current].order.cmp(&current[b.current].order))
    });
    for candidate in eligible {
        if matched_proposals.contains(&candidate.proposal)
            || matched_current.contains(&candidate.current)
        {
            continue;
        }
        matched_proposals.insert(candidate.proposal);
        matched_current.insert(candidate.current);
        plan.matches.push(MatchRecord {
            proposal_index: candidate.proposal,
            lineage: current[candidate.current].lineage.clone(),
            score: candidate.score,
            kind: MatchKind::Affinity,
        });
        plan.ops.push(OpBody::SupersedeEvent {
            lineage: current[candidate.current].lineage.clone(),
            basis: current[candidate.current].version.clone(),
            state: proposal.events[candidate.proposal].clone(),
        });
    }

    let mut retractions = Vec::new();
    for (index, event) in current.iter().enumerate() {
        if !matched_current.contains(&index) {
            retractions.push(OpBody::RetractEvent {
                lineage: event.lineage.clone(),
                basis: event.version.clone(),
            });
        }
    }
    let additions = proposal
        .events
        .iter()
        .enumerate()
        .filter(|(index, _)| !matched_proposals.contains(index))
        .map(|(_, state)| OpBody::AddEvent {
            state: state.clone(),
        })
        .collect::<Vec<_>>();

    let (metadata, supersedes): (Vec<_>, Vec<_>) = std::mem::take(&mut plan.ops)
        .into_iter()
        .partition(|op| !matches!(op, OpBody::SupersedeEvent { .. }));
    plan.ops.extend(metadata);
    plan.ops.extend(retractions);
    plan.ops.extend(supersedes);
    plan.ops.extend(additions);
    plan.matches.sort_by_key(|record| record.proposal_index);
    plan
}

fn reconcile_metadata(graph: &ScoreGraph, proposal: &Proposal, ops: &mut Vec<OpBody>) {
    if graph.title != proposal.title {
        ops.push(OpBody::ScoreInit {
            title: proposal.title.clone(),
        });
    }
    for (key, value) in &proposal.headers {
        if graph.headers.get(key) != Some(value) {
            ops.push(OpBody::SetHeader {
                key: key.clone(),
                value: value.clone(),
            });
        }
    }
    for (key, value) in &proposal.performance {
        if graph.performance.get(key) != Some(value) {
            ops.push(OpBody::AnnotatePerformance {
                key: key.clone(),
                value: value.clone(),
            });
        }
    }
    reconcile_instruments(graph, proposal, ops);
    reconcile_sections(graph, proposal, ops);

    for (bar, changes) in &proposal.bar_changes {
        if graph.inline_changes.get(bar) != Some(changes) {
            ops.push(OpBody::SetBarChanges {
                bar: *bar,
                changes: changes.clone(),
            });
        }
    }
    for (bar, texts) in &proposal.texts {
        let existing = graph.texts.get(bar).map(Vec::as_slice).unwrap_or(&[]);
        if existing == texts.as_slice() {
            continue;
        }
        // AddText is append-only in the frozen v0 vocabulary. Emit the
        // missing suffix when the existing margin is a prefix; for a
        // non-prefix edit, emit the proposal text as conservative testimony.
        let prefix = existing.len() <= texts.len() && existing == &texts[..existing.len()];
        let values = if prefix {
            &texts[existing.len()..]
        } else {
            texts.as_slice()
        };
        for prose in values {
            ops.push(OpBody::AddText {
                bar: *bar,
                prose: prose.clone(),
            });
        }
    }
}

fn current_events(graph: &ScoreGraph) -> Vec<CurrentEvent> {
    graph
        .current_events()
        .into_iter()
        .enumerate()
        .map(|(order, (lineage, state, head))| CurrentEvent {
            lineage: lineage.clone(),
            version: head.version.clone(),
            state: state.clone(),
            order,
        })
        .collect()
}

fn track_indices<'a>(events: &'a [EventState]) -> BTreeMap<&'a str, Vec<usize>> {
    let mut result: BTreeMap<&'a str, Vec<usize>> = BTreeMap::new();
    for (index, event) in events.iter().enumerate() {
        result.entry(event.track.as_str()).or_default().push(index);
    }
    result
}

fn find_ambiguities(
    candidates: &[Candidate],
    current: &[CurrentEvent],
) -> (BTreeSet<usize>, BTreeSet<usize>, Vec<Ambiguity>) {
    let mut by_proposal = BTreeMap::<usize, Vec<Candidate>>::new();
    for candidate in candidates {
        by_proposal
            .entry(candidate.proposal)
            .or_default()
            .push(*candidate);
    }
    let mut groups = BTreeMap::<(String, i32), (BTreeSet<usize>, BTreeSet<usize>)>::new();
    for (proposal, edges) in &by_proposal {
        let best = edges.iter().map(|edge| edge.score).max().unwrap();
        let tied = edges
            .iter()
            .filter(|edge| edge.score == best)
            .collect::<Vec<_>>();
        if tied.len() > 1 {
            let key = (current[tied[0].current].state.track.clone(), best);
            let group = groups.entry(key).or_default();
            group.0.insert(*proposal);
            group.1.extend(tied.iter().map(|edge| edge.current));
        }
    }
    let mut best_by_current = BTreeMap::<usize, Vec<(usize, i32)>>::new();
    for (proposal, edges) in &by_proposal {
        let best = edges.iter().map(|edge| edge.score).max().unwrap();
        for edge in edges.iter().filter(|edge| edge.score == best) {
            best_by_current
                .entry(edge.current)
                .or_default()
                .push((*proposal, edge.score));
        }
    }
    for (current_index, edges) in best_by_current {
        let best = edges.iter().map(|(_, score)| *score).max().unwrap();
        let tied = edges
            .into_iter()
            .filter(|(_, score)| *score == best)
            .map(|(proposal, _)| proposal)
            .collect::<Vec<_>>();
        if tied.len() > 1 {
            let key = (current[current_index].state.track.clone(), best);
            let group = groups.entry(key).or_default();
            group.1.insert(current_index);
            group.0.extend(tied);
        }
    }
    let mut ambiguous_proposals = BTreeSet::new();
    let mut ambiguous_current = BTreeSet::new();
    let mut ambiguities = Vec::new();
    for ((track, score), (proposals, currents)) in groups {
        ambiguous_proposals.extend(&proposals);
        ambiguous_current.extend(&currents);
        ambiguities.push(Ambiguity {
            track,
            proposal_indices: proposals.into_iter().collect(),
            lineages: currents
                .into_iter()
                .map(|index| current[index].lineage.clone())
                .collect(),
            score,
        });
    }
    (ambiguous_proposals, ambiguous_current, ambiguities)
}

/// Agreement score used by matching and exposed for receipts/tests.
pub fn affinity_score(current: &EventState, proposal: &EventState) -> i32 {
    let mut score = 0;
    if current.bar == proposal.bar {
        score += BAR_WEIGHT;
    }
    if current.onset_ql == proposal.onset_ql {
        score += ONSET_WEIGHT;
    }
    if current.pitches_midi_cents == proposal.pitches_midi_cents {
        score += PITCH_WEIGHT;
    }
    if current.kind == proposal.kind {
        score += KIND_WEIGHT;
    }
    if current.params == proposal.params {
        score += PARAM_WEIGHT;
    }
    if current.flags == proposal.flags {
        score += FLAG_WEIGHT;
    }
    if current.dynamic == proposal.dynamic {
        score += DYNAMIC_WEIGHT;
    }
    if current.lyric == proposal.lyric {
        score += LYRIC_WEIGHT;
    }
    score
}

fn reconcile_instruments(graph: &ScoreGraph, proposal: &Proposal, ops: &mut Vec<OpBody>) {
    for instrument in &proposal.instruments {
        let existing = graph
            .instruments
            .iter()
            .find(|candidate| candidate.abbrev == instrument.abbrev);
        if existing.is_none_or(|candidate| !instrument_matches(candidate, instrument)) {
            ops.push(OpBody::DeclareInstrument {
                abbrev: instrument.abbrev.clone(),
                name: instrument.name.clone(),
                clef: instrument.clef.clone(),
                params: instrument.params.clone(),
            });
        }
    }
}

fn instrument_matches(current: &mus_graph::InstrumentDecl, proposal: &ProposalInstrument) -> bool {
    current.abbrev == proposal.abbrev
        && current.name == proposal.name
        && current.clef == proposal.clef
        && current.params == proposal.params
}

fn reconcile_sections(graph: &ScoreGraph, proposal: &Proposal, ops: &mut Vec<OpBody>) {
    // Sections are an ordered list. In particular, equal names are not keys:
    // recurring "chorus" sections remain distinct. AddSection can only append
    // in v0, so emit the proposal suffix when the current list is its prefix.
    let prefix = graph.sections.len() <= proposal.sections.len()
        && graph
            .sections
            .iter()
            .zip(&proposal.sections)
            .all(|(current, target)| section_matches(current, target));
    if prefix {
        for section in &proposal.sections[graph.sections.len()..] {
            ops.push(add_section(section));
        }
    } else if graph.sections.is_empty() {
        for section in &proposal.sections {
            ops.push(add_section(section));
        }
    }
}

fn section_matches(current: &mus_graph::Section, proposal: &ProposalSection) -> bool {
    current.name == proposal.name
        && current.from_bar == proposal.from_bar
        && current.to_bar == proposal.to_bar
        && current.prose == proposal.prose
}

fn add_section(section: &ProposalSection) -> OpBody {
    OpBody::AddSection {
        name: section.name.clone(),
        from_bar: section.from_bar,
        to_bar: section.to_bar,
        prose: section.prose.clone(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use mus_graph::project;
    use mus_oplog::{EventKind, Frac, OpLog};
    use std::collections::{BTreeMap, BTreeSet};

    fn state(track: &str, bar: u32, onset: i64, pitch: i32) -> EventState {
        EventState {
            track: track.into(),
            bar,
            onset_ql: Frac::new(onset, 1),
            dur_ql: Frac::new(1, 1),
            kind: EventKind::Note,
            pitches_midi_cents: vec![pitch],
            gliss_target_midi_cents: None,
            dynamic: Some("mf".into()),
            params: BTreeMap::new(),
            flags: BTreeSet::new(),
            lyric: None,
            quote: None,
        }
    }

    fn graph(states: &[EventState]) -> ScoreGraph {
        let mut log = OpLog::new();
        log.append("seed", 1, OpBody::ScoreInit { title: "t".into() });
        log.append(
            "seed",
            2,
            OpBody::DeclareInstrument {
                abbrev: "v".into(),
                name: "voice".into(),
                clef: "treble".into(),
                params: BTreeMap::new(),
            },
        );
        for (seq, event) in states.iter().enumerate() {
            log.append(
                "seed",
                seq as u64 + 3,
                OpBody::AddEvent {
                    state: event.clone(),
                },
            );
        }
        project(&log)
    }

    fn proposal(events: Vec<EventState>) -> Proposal {
        Proposal {
            title: "t".into(),
            instruments: vec![ProposalInstrument {
                abbrev: "v".into(),
                name: "voice".into(),
                clef: "treble".into(),
                params: BTreeMap::new(),
            }],
            events,
            ..Proposal::default()
        }
    }

    fn append_plan(mut log: OpLog, plan: &IngestPlan) -> ScoreGraph {
        for (offset, body) in plan.ops.iter().cloned().enumerate() {
            log.append("editor", offset as u64 + 1, body);
        }
        project(&log)
    }

    #[test]
    fn idempotence_and_pitch_edit_preserve_lineage() {
        let old = state("v", 1, 0, 6000);
        let graph = graph(std::slice::from_ref(&old));
        assert!(
            diff_to_ops(&graph, &proposal(vec![old.clone()]), "editor", 1)
                .ops
                .is_empty()
        );
        let mut edited = old.clone();
        edited.pitches_midi_cents = vec![6100];
        let plan = diff_to_ops(&graph, &proposal(vec![edited.clone()]), "editor", 1);
        assert!(matches!(
            plan.ops.as_slice(),
            [OpBody::SupersedeEvent { .. }]
        ));
        let OpBody::SupersedeEvent {
            lineage,
            basis,
            state,
        } = &plan.ops[0]
        else {
            unreachable!()
        };
        assert_eq!(lineage, graph.current_events()[0].0);
        assert_eq!(basis, &old.version_id());
        assert_eq!(state, &edited);
    }

    #[test]
    fn moving_a_note_across_bars_is_one_supersede() {
        let old = state("v", 1, 0, 6000);
        let graph = graph(std::slice::from_ref(&old));
        let mut moved = old.clone();
        moved.bar = 2;
        let plan = diff_to_ops(&graph, &proposal(vec![moved]), "editor", 1);
        assert!(matches!(
            plan.ops.as_slice(),
            [OpBody::SupersedeEvent { .. }]
        ));
    }

    #[test]
    fn truly_identical_siblings_use_order_stability() {
        let first = state("v", 1, 0, 6000);
        let second = first.clone();
        let graph = graph(&[first.clone(), second.clone()]);
        let mut edited = first.clone();
        edited.params.insert("pan".into(), "0.5".into());
        let plan = diff_to_ops(&graph, &proposal(vec![edited.clone(), second]), "editor", 1);
        assert_eq!(plan.matches.len(), 2);
        assert_eq!(plan.matches[0].lineage, graph.current_events()[0].0.clone());
        assert_eq!(plan.matches[1].lineage, graph.current_events()[1].0.clone());
        assert!(
            matches!(plan.ops.as_slice(), [OpBody::SupersedeEvent { lineage, .. }] if lineage == graph.current_events()[0].0)
        );
    }

    #[test]
    fn identical_pitch_swap_is_ambiguous_and_converges() {
        let first = state("v", 1, 0, 6000);
        let second = state("v", 1, 0, 6200);
        let graph = graph(&[first.clone(), second.clone()]);
        let mut swapped_first = first.clone();
        swapped_first.pitches_midi_cents = vec![6100];
        let mut swapped_second = second.clone();
        swapped_second.pitches_midi_cents = vec![6300];
        let target = proposal(vec![swapped_first, swapped_second]);
        let plan = diff_to_ops(&graph, &target, "editor", 1);
        assert_eq!(plan.ambiguous.len(), 1);
        assert_eq!(plan.ambiguous[0].proposal_indices, vec![0, 1]);
        assert_eq!(
            plan.ops
                .iter()
                .filter(|op| matches!(op, OpBody::RetractEvent { .. }))
                .count(),
            2
        );
        assert_eq!(
            plan.ops
                .iter()
                .filter(|op| matches!(op, OpBody::AddEvent { .. }))
                .count(),
            2
        );
        let converged = append_plan(graph_log(&graph), &plan);
        assert!(diff_to_ops(&converged, &target, "editor", 1).ops.is_empty());
    }

    #[test]
    fn metadata_includes_bar_changes_text_and_repeated_sections() {
        let event = state("v", 1, 0, 6000);
        let graph = graph(std::slice::from_ref(&event));
        let mut target = proposal(vec![event]);
        target.bar_changes.insert(1, vec!["tempo=88".into()]);
        target.texts.insert(1, vec!["margin".into()]);
        target.sections = vec![
            ProposalSection {
                name: "chorus".into(),
                from_bar: 1,
                to_bar: 1,
                prose: None,
            },
            ProposalSection {
                name: "chorus".into(),
                from_bar: 2,
                to_bar: 2,
                prose: None,
            },
        ];
        let plan = diff_to_ops(&graph, &target, "editor", 1);
        assert!(plan
            .ops
            .iter()
            .any(|op| matches!(op, OpBody::SetBarChanges { .. })));
        assert!(plan
            .ops
            .iter()
            .any(|op| matches!(op, OpBody::AddText { .. })));
        assert_eq!(
            plan.ops
                .iter()
                .filter(|op| matches!(op, OpBody::AddSection { .. }))
                .count(),
            2
        );
        let projected = append_plan(graph_log(&graph), &plan);
        assert_eq!(
            projected
                .sections
                .iter()
                .map(|s| s.name.as_str())
                .collect::<Vec<_>>(),
            vec!["chorus", "chorus"]
        );
    }

    fn graph_log(graph: &ScoreGraph) -> OpLog {
        let mut log = OpLog::new();
        log.append(
            "seed",
            1,
            OpBody::ScoreInit {
                title: graph.title.clone(),
            },
        );
        for (key, value) in &graph.headers {
            log.append(
                "seed",
                log.len() as u64 + 1,
                OpBody::SetHeader {
                    key: key.clone(),
                    value: value.clone(),
                },
            );
        }
        for instrument in &graph.instruments {
            log.append(
                "seed",
                log.len() as u64 + 1,
                OpBody::DeclareInstrument {
                    abbrev: instrument.abbrev.clone(),
                    name: instrument.name.clone(),
                    clef: instrument.clef.clone(),
                    params: instrument.params.clone(),
                },
            );
        }
        for (_, event, _) in graph.current_events() {
            log.append(
                "seed",
                log.len() as u64 + 1,
                OpBody::AddEvent {
                    state: event.clone(),
                },
            );
        }
        log
    }

    #[test]
    fn corpus_textual_edit_reparse_ingest_project_reduce() {
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
        assert_eq!(paths.len(), 17);
        for path in paths {
            let source = std::fs::read_to_string(&path).unwrap();
            let original =
                crate::parse_score(&source).unwrap_or_else(|d| panic!("{}: {d:?}", path.display()));
            let mut source_log = proposal_log(&original);
            let graph = project(&source_log);
            let edited_text = edit_bar_two_textually(&source);
            let edited = crate::parse_score(&edited_text)
                .unwrap_or_else(|d| panic!("edited {}: {d:?}\n{edited_text}", path.display()));
            let plan = diff_to_ops(&graph, &edited, "wc-test", 100);
            assert_eq!(
                plan.ops
                    .iter()
                    .filter(|op| matches!(op, OpBody::SupersedeEvent { .. }))
                    .count(),
                1,
                "{}: {plan:?}",
                path.display()
            );
            assert_eq!(
                plan.ops
                    .iter()
                    .filter(|op| matches!(
                        op,
                        OpBody::AddEvent { .. } | OpBody::RetractEvent { .. }
                    ))
                    .count(),
                0,
                "{}: {plan:?}",
                path.display()
            );
            assert!(plan.ambiguous.is_empty(), "{}: {plan:?}", path.display());
            for (offset, op) in plan.ops.iter().cloned().enumerate() {
                source_log.append("wc-test", 100 + offset as u64, op);
            }
            let reduced = mus_graph::reduce_to_text(&project(&source_log))
                .unwrap_or_else(|e| panic!("{}: {e:?}", path.display()));
            let round_tripped = crate::parse_score(&reduced)
                .unwrap_or_else(|d| panic!("reduced {}: {d:?}\n{reduced}", path.display()));
            assert_eq!(round_tripped, edited, "{}", path.display());
        }
    }

    fn proposal_log(proposal: &Proposal) -> OpLog {
        let mut log = OpLog::new();
        let mut seq = 1;
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
        for instrument in &proposal.instruments {
            log.append(
                "mus-text",
                seq,
                OpBody::DeclareInstrument {
                    abbrev: instrument.abbrev.clone(),
                    name: instrument.name.clone(),
                    clef: instrument.clef.clone(),
                    params: instrument.params.clone(),
                },
            );
            seq += 1;
        }
        for section in &proposal.sections {
            log.append("mus-text", seq, add_section(section));
            seq += 1;
        }
        for (bar, changes) in &proposal.bar_changes {
            log.append(
                "mus-text",
                seq,
                OpBody::SetBarChanges {
                    bar: *bar,
                    changes: changes.clone(),
                },
            );
            seq += 1;
        }
        for (bar, texts) in &proposal.texts {
            for prose in texts {
                log.append(
                    "mus-text",
                    seq,
                    OpBody::AddText {
                        bar: *bar,
                        prose: prose.clone(),
                    },
                );
                seq += 1;
            }
        }
        for event in &proposal.events {
            log.append(
                "mus-text",
                seq,
                OpBody::AddEvent {
                    state: event.clone(),
                },
            );
            seq += 1;
        }
        log
    }

    fn edit_bar_two_textually(source: &str) -> String {
        let mut output = Vec::new();
        let mut edited = false;
        for line in source.lines() {
            let Some((from, to, suffix)) = bar_range(line) else {
                output.push(line.to_string());
                continue;
            };
            if from > 2 || to < 2 || edited {
                output.push(line.to_string());
                continue;
            }
            let content = line[line.find(':').unwrap() + 1..].trim();
            for bar in from..=to {
                let body = if bar == 2 {
                    edited = true;
                    append_param_to_first_event(content)
                } else {
                    content.to_string()
                };
                output.push(format!("bar {bar}{suffix}: {body}"));
            }
        }
        assert!(edited, "corpus score has no bar 2 text line");
        output.join("\n") + "\n"
    }

    fn bar_range(line: &str) -> Option<(u32, u32, String)> {
        let trimmed = line.trim_start();
        let rest = trimmed
            .strip_prefix("bar ")
            .or_else(|| trimmed.strip_prefix("bars "))?;
        let (head, _) = rest.split_once(':')?;
        let range = head.split_whitespace().next()?;
        let (from, to) = range.split_once('-').map_or_else(
            || Some((range.parse().ok()?, range.parse().ok()?)),
            |(from, to)| Some((from.parse().ok()?, to.parse().ok()?)),
        )?;
        let suffix = head[range.len()..].to_string();
        Some((from, to, suffix))
    }

    fn append_param_to_first_event(content: &str) -> String {
        let mut cursor = 0;
        for token in content.split_whitespace() {
            let start = content[cursor..].find(token).unwrap() + cursor;
            cursor = start + token.len();
            let value = token.split_once('=').map_or(token, |(_, value)| value);
            if value.starts_with('{')
                || value.starts_with('R')
                || value.starts_with('r')
                || value == "-"
            {
                continue;
            }
            let replacement = if let Some(close) = token.rfind(']') {
                format!("{},wc_probe=1]", &token[..close])
            } else {
                format!("{token}[wc_probe=1]")
            };
            return format!(
                "{}{}{}",
                &content[..start],
                replacement,
                &content[start + token.len()..]
            );
        }
        panic!("bar 2 has no sounding event: {content}");
    }
}
