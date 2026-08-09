# WB — mus-text: parse and reduce, the full corpus, the round-trip law

GOAL. The text FACE, whole: lexer → parse (text → Proposal) → and the
completion of `reduce_to_text` so the entire committed corpus round-trips.

PART 1 — lexer (in `mus-rs/crates/mus-notation`, replacing the stub lib):
port `tokenize_bar_content` (bracket/quote-balancing splitter),
`expand_pattern_repetitions` (the `(… ×N)` form, unicode ×),
`split_attached_dynamics`, duration parsing (codes w..t/x incl. doubled
`ww`, dots ×(2−2^−n), tie chains `~`, tuplet `{a:n}` and shorthand digit
{3:(3,2),5:(5,4),6:(6,4),7:(7,4),9:(9,8)}), pitch (letters, accidentals
bb b n # ## x, negative octaves, ±cents), and `parse_token` with EXACTLY
the reference semantics (lstrip '(' rstrip ')', lyric strip, hairpins,
dynamics, '-', param/flag split on the [..] group, gliss via '->' and via
gliss=, chords, R/X defaults). ACCEPTANCE: a test deserializing
`tests/vectors/tokens.json` (3,604 cases) and `bars.json` (40 cases) and
matching every field (ql to 1e-9; midis to 1e-6; params/flags/dyn exact;
kind None ⇒ your parser returns None). Field mapping: kinds are
note/chord/rest/unpitched/dynamic/hairpin.

PART 2 — parse (new crate `mus-rs/crates/mus-text`, deps: mus-notation,
mus-oplog, mus-graph): `parse_score(text) -> Result<Proposal, Vec<Diag>>`
where `Proposal` mirrors ScoreGraph's shape but WITHOUT lineage ids
(events are positional: Vec<EventState>). Port the score-level grammar
from `mus.py::parse_mus` + `mus_audio.check_score`: headers (multi-key
lines, change lists `80 (b1) → 88 (b11)` may parse as raw strings v0),
instruments (clef + params), `bar N:`/`bars N-M:` lines with `[inline]`
changes, `tr=tokens` splitting, sections tolerant of trailing prose,
`text @bN`. Dynamics state folds into each EventState.dynamic exactly as
the checker does. Rests advance; they are not events.

PART 3 — reduce, completed (in mus-graph or moved to mus-text — mover's
choice, state it): meter map from time changes (not 4/4-only), dynamics
emission (emit `{dyn}` tokens exactly where state changes per track),
tempo/time inline changes, `(…×N)` is NEVER emitted (canonical form is
expanded), attached lyrics, gliss `->` targets, X st= params, tacet bars,
multi-bar tied events (an event whose dur crosses its bar emits in its
onset bar only — reduction must not re-split it).

THE LAW (the stage's headline test, name it `round_trip_law`):
for every score in `aigua/*.mus`:
  let p1 = parse(text); let g = adopt(p1) (mint lineages positionally);
  let t2 = reduce(g); let p2 = parse(t2);
  assert p1.events == p2.events, p1.headers == p2.headers, etc. —
  i.e. **parse ∘ reduce ∘ parse = parse** (canonicalization is a fixpoint).
Do NOT require t2 == original text (originals are non-canonical).
Corpus constructs the reducer cannot yet express are FAILURES here, not
skips — this stage is done when the law holds for all 13 scores.
