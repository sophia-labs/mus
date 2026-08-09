# WC — the ingest seam: diff(graph, proposal) → ops

GOAL. The ONE place text-editing reconciliation lives (R1): turn an edited
text's Proposal into ops against the current ScoreGraph, preserving lineage
where the edit plausibly preserved identity, and REPRESENTING ambiguity
instead of guessing.

DELIVERABLE (`mus-rs/crates/mus-text`, module `ingest`):
`diff_to_ops(graph: &ScoreGraph, proposal: &Proposal, actor, seq_start)
 -> IngestPlan { ops: Vec<OpBody>, matches: Vec<MatchRecord>, ambiguous: Vec<Ambiguity> }`

MATCHING (per track): current chosen-head events vs proposal events.
1. Exact state match (version id equal) → no op, lineage continues.
2. Unique best match by affinity — score = weighted agreement on (bar,
   onset, pitches, kind) with (params, flags, dyn, lyric) as tiebreakers;
   thresholds documented as consts — → SupersedeEvent {basis = matched
   head's version}.
3. Proposal event with no plausible match → AddEvent.
4. Graph event with no plausible match → RetractEvent {basis}.
5. AMBIGUITY (two proposal events tie for one lineage, or one proposal
   event ties for two lineages) → do NOT choose: emit the conservative
   ops (retract + add) AND record an `Ambiguity` entry naming both sides.
   The CALLER (Atril's commit gesture, later) surfaces it. Header/
   instrument/section diffs are simple set/replace ops (SetHeader etc.);
   instruments match by abbrev.

LAWS TO TEST:
- idempotence: diff(g, proposal_of(g)) emits zero ops.
- a pitch edit to one token yields exactly one SupersedeEvent whose basis
  is the old version and preserves the lineage id.
- moving an event across bars with identical content yields ONE supersede
  (lineage preserved) when unambiguous.
- two identical events where one gets edited: the unedited one keeps its
  lineage; no cross-matching (order-stability tiebreaker documented).
- a genuinely ambiguous swap of two identical-but-for-pitch events is
  reported in `ambiguous`, and applying the emitted ops then re-diffing
  the same proposal is idempotent (convergence of the conservative path).
- END-TO-END: for every corpus score — adopt via parse, apply one scripted
  edit (append a param to the first event of bar 2 textually), ingest,
  project, reduce: the round-trip law still holds and exactly one lineage
  superseded.
