# mus-rs implementation specs — the MO-native line

You are implementing one workstream of the MO-native MUS engine in
`/Users/vera/dev/sophia/mus` on branch `agent/aigua-analysis-foundation`.
Read first, in order: `../../plans/mus-mo-language-20260809.md` (the ratified
design — R1..R8 are law), then the keystone crates `mus-rs/crates/mus-oplog`
and `mus-rs/crates/mus-graph` (their doc headers state the laws your work
must preserve), then your spec.

## House rules (violations are review-rejections)

1. **The keystone laws are frozen**: content-addressed ops; union merge;
   projection order `(lamport, actor, seq, id)`; two-tier identity; forks
   represented-never-resolved; faces name their head choice; reduction is
   canonical and fails LOUDLY on what it cannot write. Extend, don't bend.
2. **The Python implementation is a migration validator, not a definition.**
   Behavioral deltas are allowed only where a spec says so, and are recorded
   in the code as `DIVERGENCE:` comments with rationale.
3. **Oracle material**: `mus-rs/crates/mus-notation/tests/vectors/` (3,604
   token vectors + 40 bar vectors), the corpus `aigua/*.mus` (13 scores),
   `schemas/mus-check-report.schema.json`, and `mus_audio.py --check`
   (spawn via `uv run --script`). Tests may spawn the Python checker for
   parity; mark such tests with a `parity_` name prefix.
4. **No new heavy dependencies without the spec naming them.** serde,
   serde_json, sha2, regex are in. Anything else: only if your spec lists it.
5. **Determinism is a law of the medium (R7).** No wall clocks, no RNG
   without a seed derived from content, no HashMap iteration order leaking
   into output (use BTree*).
6. **Every stage lands green**: `cargo test` in `mus-rs/` plus `cargo fmt
   --check`. Write real tests for your own acceptance criteria — the
   reviewer reads them as claims.
7. Stage everything with `git add -A` when done; do NOT commit (the gate
   commits on green).

## Workstreams

| Spec | What |
|---|---|
| `WA-vocab.md` | mus-vocab crate: embedded ttl, closed core registry, vocab digest, extension detection |
| `WB-textface.md` | mus-text: lexer (vectors as floor), full parse text→ScoreGraph-shaped Proposal, reduce for the full corpus, round-trip law |
| `WC-ingest.md` | diff(graph, proposal) → ops; lineage matching; contested-on-ambiguity |
| `WD-compile-cli.md` | mus-cli: `check` emitting mus.audio.check-report.v1 at full corpus parity with Python; the Atril seam swap |
| `WF1-engine-core.md` | mus-engine first ladder rung: samples, varispeed, envelopes, pan, mix, master; renders smoke.mus |
