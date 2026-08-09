# WA — mus-vocab: the golden contract as a crate

GOAL. A `mus-vocab` crate making the vocabulary layers (R2) executable:
the closed mus-core registry, the mus-x extension posture, and digests.

DELIVERABLES (new crate `mus-rs/crates/mus-vocab`, workspace member):
1. Embed `ontology/mus-score.ttl` and `ontology/mus-ops.ttl` via
   `include_str!`; expose `vocab_digest()` = sha256 of both, concatenated
   in that order with a `\n---\n` separator (documented).
2. `CoreParams`: the closed set from mus-score.ttl's comment (pan gain lpf
   hpf send s str off st atk rel curve tau drive dist crush decim stut
   duck) as a `&'static [&'static str]` + `is_core_param(name)`.
3. `CoreFlags`: stac stacciss spic detlg acc marc sfz stress unstress ten
   fer gate reverse.
4. `classify_param(name) -> ParamLayer { Core, Extension }` — anything
   non-core is Extension (musx:), including the current synth patch keys
   and glow/chop/ring/haas chain. NO denylist: extension is open by design,
   the report just counts it honestly.
5. `extension_usage(graph: &ScoreGraph) -> BTreeMap<String, u32>` counting
   events-per-extension-param across current_events + instrument defaults.
   (Depends on mus-graph; add it as a dependency of mus-vocab? NO —
   dependency direction: mus-graph must not depend on vocab yet, and vocab
   should stay leaf. Put `extension_usage` in mus-graph behind a function
   that takes a `&dyn Fn(&str) -> bool` core-classifier, and have mus-vocab
   provide the classifier. Keep both crates leaf-clean; wire them in the
   CLI (WD). State this shape in doc comments.)
6. Header registry: the canonical header keys + which are performance
   annotations (swing) vs score properties (R6) — one table, consumed
   later by WD.

TESTS: digest stability (golden hex, updated deliberately when ttl
changes — the test comment says how); every param used across the corpus
classifies (spawn nothing — hardcode the known list from SPEC-AUDIO);
`swing` classified as performance annotation.
