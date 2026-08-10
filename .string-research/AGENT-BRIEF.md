# Implementation agent brief: review and land Ariadne sprint one

You are the implementation/review agent for the first Ariadne sprint.

The user explicitly wants a **complete but rough, working handoff**, not a polished speculative report. You are empowered to revise the staged DSP, reject bad premises, adjust architecture, and implement the missing integration. Preserve the research intent while preferring compiled evidence over prose.

## Read first

1. `.string-research/HANDOFF.md`
2. `.string-research/ARIADNE-MATHEMATICS.md`
3. `.string-research/PARAMETERS.md`
4. `.string-research/EXPERIMENTS.md`
5. `.string-research/LITERATURE.md`
6. `.string-research/GUITAR-AND-ARIADNE-DESIGN.md`

Then inspect the payload chunks and the current operative `pluck.rs`.

## Mission

Produce one reviewable branch where:

- the staged replacement is assembled into the real Rust source tree;
- structural and numerical defects are fixed;
- the deepened guitar renders through `synth=pluck`;
- Ariadne renders through `synth=weave`;
- all parameters propagate through the engine and typed vocabulary;
- the research scores parse and render;
- existing non-pluck parity remains intact;
- failures and weakened claims are reported rather than hidden.

## Commands to begin

```bash
bash .string-research/assemble.sh
bash .string-research/assemble.sh --apply

cd mus-rs
cargo fmt --all
cargo check --workspace
cargo test -p mus-dsp --test pluck_invariants -- --nocapture
```

Expect failures. Triage them individually.

## Required integration files

At minimum review or modify:

```text
mus-rs/crates/mus-dsp/src/pluck.rs
mus-rs/crates/mus-dsp/tests/pluck_invariants.rs
mus-rs/crates/mus-engine/src/source.rs
mus-rs/crates/mus-engine/src/pack.rs
mus-rs/crates/mus-vocab/src/param_specs.rs
mus-rs/crates/mus-cli/tests/vocab_dump.rs
aigua/pluck_demo.mus
```

Land adapted copies of:

```text
.string-research/scores/guitar_upgrade_demo.mus
.string-research/scores/ariadne_demo.mus
```

No `lib.rs` change should be needed merely to expose the replacement because `pub mod pluck` already exists, but verify rather than assume.

## Highest-priority review questions

### 1. Is the delay/filter retuning stable and musically smooth?

The current whole-network passivity language is conditional. Variable delay and changing allpass coefficients are not covered by the Givens norm proof. Measure energy injection and zipper artifacts. Prefer a known energy-compensated method if feasible.

### 2. Does the energy norm correspond to the coupled coordinates?

Givens rotations preserve Euclidean norm. Confirm body/string coordinates are normalized accordingly or implement weighted scattering.

### 3. Does the new excitation really improve guitar sound?

The triangular component plus rough contact is a hypothesis. Compare it to the old position-combed noise burst in isolation and in phrases. Keep whichever sounds better, including hybrids.

### 4. Is body coupling internally coherent?

Check modal-coordinate update order, coupling normalization, T60, direct/radiated mix, and zero-body identity. Treat the current ten modes as a profile stub, not sacred constants.

### 5. Does Weave do more than produce dense modulation?

Verify same-input path/order differences at controlled pitch and loudness. The moderate preset must sound playable before the extreme preset is celebrated.

## Review permissions

You may:

- split `pluck.rs` into focused modules if one 1,181-line file is the wrong shape;
- rename internal types while preserving public score vocabulary;
- introduce body/topology profile structs;
- replace test estimators that are demonstrably wrong;
- narrow or rewrite claims;
- reduce defaults or safe ranges;
- add diagnostic tools and receipts;
- defer a mathematically stronger feature behind an explicit issue if the rough implementation is unsafe.

Do not:

- silently widen a failing tolerance;
- add output limiting to conceal an unstable feedback loop;
- call ordinary order dependence a Berry phase;
- call the power-law course list a realized fractal topology;
- regress the existing corpus to make the new voice pass;
- fork the vocabulary into plugin-only hidden parameters;
- replace deterministic content identity with global randomness.

## Suggested module split

The payload is deliberately monolithic for handoff. A maintainable landing might become:

```text
mus-dsp/src/string_network/mod.rs
mus-dsp/src/string_network/patch.rs
mus-dsp/src/string_network/excitation.rs
mus-dsp/src/string_network/delay_string.rs
mus-dsp/src/string_network/body.rs
mus-dsp/src/string_network/scatter.rs
mus-dsp/src/string_network/contact.rs
mus-dsp/src/string_network/voice.rs
mus-dsp/src/pluck.rs              # compatibility exports
```

Do this only if it helps review and testing; compilation is more important than aesthetic churn.

## Minimum report

Finish with a committed report, issue, or PR body that states:

```text
branch / commit
what was implemented
what was changed from the handoff and why
cargo fmt/check/test status
parity status
guitar render artifacts and listening assessment
Ariadne render artifacts and path/order assessment
measured tuning/T60/boundedness/block results
CPU/allocation status
remaining P0 gaps
claims that are proved, tested, conjectural, or rejected
recommendation: merge / continue experiment / redesign
```

A finding that a proposed mechanism is unsound is a successful review result if it is demonstrated and replaced or clearly parked.
