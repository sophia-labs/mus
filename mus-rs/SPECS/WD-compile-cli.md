# WD — mus-cli `check`: the Rust checker at corpus parity, on the Atril seam

GOAL. A `mus` binary whose `check` subcommand emits
`mus.audio.check-report.v1` (schemas/mus-check-report.schema.json) from the
Rust hinge, at full-corpus parity with the Python checker, ready to swap in
via `MUS_CHECK_CMD`.

DELIVERABLE (`mus-rs/crates/mus-cli`, bin name `mus`):
`mus check <score.mus> [--base DIR] [--json]` →
parse (WB) → adopt → per-event layout: replicate the checker's derived
fields — onsetSeconds from the tempo/meter map, swungOnsetSeconds from the
swing annotation (same formula as mus_audio.swung), durationSeconds,
effectiveParams (defaults ∘ params), sweeps, quote resolution against the
`# gestures:` file (load its JSON; median/t0/t1/shift math identical),
digests (source/pack/gestures/tape), diagnostics with the same closed code
set and tagged anchors, declaredObjects, clean flag. Float formatting: emit
numbers that survive the comparison below (round as Python does: onsets to
6dp, shift 2dp — read check_score for every rounding site).
Extension surface: also emit `extensionUsage` (from WA's classifier via the
mus-graph hook) as an ADDITIVE field — the schema allows additions.

PARITY (headline test `parity_check_corpus`, may spawn Python):
for every corpus score: run `uv run --script ../mus_audio.py <score>
--check --base <dir>` and your `mus check`; compare as parsed JSON with
these normalizations ONLY: ignore `producer`/`rendererVersion`; treat
floats equal at 1e-6 relative; sort arrays where the schema does not
promise order (declaredObjects). Event arrays must match element-for-
element INCLUDING order. Any other delta is a failure (or a `DIVERGENCE:`
comment + a normalization entry added HERE in the spec by amendment —
reviewer judges).
ALSO: `hyperfine`-free timing note in the PR text: `mus check` on bolero
should be well under 200ms.

SEAM: document (in the CLI's --help and a README section) the Atril swap:
`MUS_CHECK_CMD="/Users/vera/dev/sophia/mus/mus-rs/target/release/mus check"`
— do not modify the shrubbery repo (a concurrent line owns it).
