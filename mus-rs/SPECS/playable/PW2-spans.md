# PW2 — source spans in the check report (v1.1), parity-locked

The Roll edits the score by **span replacement**: the checker tells the
face exactly which bytes of the source each event came from, and the face
edits those bytes through the editor's transaction API. The checker is
the single authority on token geography — the face never re-parses.

## 1. The contract change

`mus.audio.check-report.v1` → **v1.1** (bump the `schema` string in BOTH
implementations):

- Every event object gains `"span": [startByte, endByte]` — byte offsets
  into the exact source string the checker received (UTF-8 bytes, not
  code points; end exclusive), covering the event's full token including
  its bracketed params and any attached gliss target (`A6q->C7`), but
  NOT leading/trailing whitespace.
- Every bar content line gains nothing (bars are derivable); but each
  event ALSO gains `"barLineSpan": [startByte, endByte]` — the span of
  the `N: | ... |` line it lives on — so the Roll can fall back to
  line-granular replacement when a token-precise edit is risky.
- `schemas/mus-check-report.schema.json` updated accordingly (spans
  required on every event).

## 2. Both implementations, identical bytes

- Python: `mus_audio.py check_score` — the tokenizer path must carry
  byte offsets through `tokenize_bar_content`/`expand_pattern_repetitions`
  /`split_attached_dynamics`. Note the traps: pattern-repetition
  expansion produces events with NO distinct source text (they share the
  pattern's span — each expanded event carries the span of the source
  token it was expanded from), and detached dynamics (`D2q{mp}` split
  into two tokens) both carry the original combined token's span.
  Choose the rule, document it in the spec text of the schema, and make
  BOTH implementations honor it identically.
- Rust: `crates/mus-cli/src/check.rs` + whatever `mus-notation`/
  `mus-text` plumbing is needed to surface byte positions (the lexer
  sees them; they may need threading through the proposal event shape —
  keep the addition additive and non-breaking for other consumers).
- **The parity corpus is the arbiter**: extend
  `tools/parity_render.py`'s check comparison (or the
  `parity_check_corpus` test in mus-cli) so spans are compared
  element-for-element across all 13 scores. A span mismatch anywhere in
  the corpus is a stage failure.

## 3. Tests

- Unit: a small score exercising every trap — pattern repetition
  (`(...)x4` or the house form), attached dynamics, gliss targets,
  chord tokens, tuplet duration braces, an `X` unpitched event with
  params — assert exact expected byte spans (hand-computed in the test).
- Property: for every event in every corpus score, the source substring
  at `span` re-parses (through the real tokenizer) to an event with the
  same pitch/duration signature — spans point at real tokens, not
  neighborhoods.
- Parity: the corpus lock described above, both implementations.
- The existing oracle-locked event counts (states 147, motet 546, 1547
  1281, 1568 2628, gliss 512) must not change.

## DoD

Both checkers emit v1.1 with identical spans corpus-wide; schema
updated; all existing check/report tests updated and green; fmt clean;
tests in the diff.
