# The Playable Graph — mus-side worker line (PW1, PW2)

Companion to `sophia/plans/atril-interaction-grammar-20260810.md` (the
grammar) and `apps/atril/SPECS/playable/` in the shrubbery repo (the
face-side stages PW3–PW6). This directory holds the two engine-side
stages.

**Keystones already landed (read them first):**
- `crates/mus-cli/src/service.rs` — `mus service`, the warm engine over
  NDJSON JSON-RPC (protocol v0: `ping`, `load`, `renderScore`), with
  `crates/mus-cli/tests/service_smoke.rs` as the protocol-test pattern.
- The audio-parity leg (SPECS/audio/*) — the engine this service exposes
  is at sample parity with `mus_audio.py`; every corpus score's receipts
  match and eleven of thirteen render at float32 noise floor.

**The law that governs every service extension — window exactness:**

> `renderWindow(docKey, a, b)` returns exactly `renderScore(docKey)`'s
> samples `[a×SR .. b×SR)`, bit-identical. Windowing is a *view* of the
> one true render, never a second opinion.

This is achievable because the engine is deterministic and because the
full render can cache what windows need (per-event placement extents, the
master chain's gain trajectory). If an implementation cannot meet
bit-identity for some construct, that is a finding to REPORT with the
measured divergence — never a tolerance to widen silently. Refusal is a
result.

**House rules (same as the audio leg):** own tests in the same diff;
`cargo fmt` clean; leave work uncommitted (gate stages, reviewer
approves, clerk lands); touch only your stage's files; stats/receipt
surfaces stay backward-compatible (mus-cli tests and the WF9 parity tool
consume them).
