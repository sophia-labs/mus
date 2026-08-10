//! mus-oplog — the mergeable SOURCE of a Score (R1 of
//! `sophia/plans/mus-mo-language-20260809.md`).
//!
//! A Score is a Meaningful Object; this crate is its convergence story. The
//! laws, each load-bearing and each tested here:
//!
//! 1. **Ops are content-addressed.** An op's id is the SHA-256 of its
//!    canonical serialization (actor, seq, lamport, body — id excluded).
//!    Re-appending an op you already hold is a no-op by construction.
//! 2. **Logs merge by union.** No conflicts are possible at the log layer;
//!    all meaning-level conflict is *represented* downstream (contested
//!    lineages, projected by `mus-graph`), never resolved silently (R8).
//! 3. **Projection order is total and merge-invariant**: `(lamport, actor,
//!    seq, id)`. Any two replicas holding the same op-set project the same
//!    ScoreGraph — convergence is a property of the source, and the
//!    projection inherits it (the whitepaper sentence, made executable).
//! 4. **Two-tier identity (R5).** A lineage id is the id of its minting op
//!    (stable forever); a version id is the SHA-256 of the canonical
//!    EventState. A `SupersedeEvent` carries the `basis` version it saw —
//!    two supersedes sharing a basis are a FORK, detected structurally.
//! 5. **Rational time (R6).** Onsets and durations are exact fractions of a
//!    quarter note. Seconds are a face's business; swing is an annotation.
//!
//! Canonical serialization = serde_json over structures whose maps are
//! `BTreeMap`/`BTreeSet` — key order is defined, so hashes are defined.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};

// ---------------------------------------------------------------- fractions

/// An exact quarter-length fraction. Always stored normalized (gcd-reduced,
/// positive denominator).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Frac {
    pub num: i64,
    pub den: i64,
}

// Ord must be NUMERIC, not structural: a derived Ord compares numerators
// lexicographically and silently mis-sorts (5/2 > 4/1 — caught by the
// reduction tests, kept here as a warning to future refactors).
impl PartialOrd for Frac {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for Frac {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        // Denominators are positive by construction.
        (self.num as i128 * other.den as i128).cmp(&(other.num as i128 * self.den as i128))
    }
}

impl Frac {
    pub fn new(num: i64, den: i64) -> Self {
        assert!(den != 0, "Frac denominator must be nonzero");
        let sign = if den < 0 { -1 } else { 1 };
        let (num, den) = (num * sign, den * sign);
        let g = gcd(num.abs(), den).max(1);
        Frac {
            num: num / g,
            den: den / g,
        }
    }

    pub fn zero() -> Self {
        Frac { num: 0, den: 1 }
    }

    pub fn as_f64(self) -> f64 {
        self.num as f64 / self.den as f64
    }
}

impl std::ops::Add for Frac {
    type Output = Frac;

    fn add(self, other: Frac) -> Frac {
        Frac::new(
            self.num * other.den + other.num * self.den,
            self.den * other.den,
        )
    }
}

fn gcd(mut a: i64, mut b: i64) -> i64 {
    while b != 0 {
        let t = a % b;
        a = b;
        b = t;
    }
    a.abs()
}

// -------------------------------------------------------------------- ids

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct OpId(pub String);

/// Stable across every edit of the thing it names: the id of the minting op.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct LineageId(pub String);

/// Content hash of one EventState — a *version*, never an identity.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct VersionId(pub String);

fn sha256_hex(bytes: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(bytes);
    let out = h.finalize();
    let mut s = String::with_capacity(64);
    for b in out {
        s.push_str(&format!("{b:02x}"));
    }
    s
}

pub fn canonical_json<T: Serialize>(value: &T) -> String {
    serde_json::to_string(value).expect("canonical serialization cannot fail")
}

// ------------------------------------------------------------- event state

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum EventKind {
    Note,
    Chord,
    Unpitched,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum QuoteLayer {
    Resolved,
    Octave,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Quote {
    /// The research-object IRI this event cites, when resolved
    /// (`urn:sophia:mus:segment:sha256:…`). The graph edge of R§2.
    pub target_iri: Option<String>,
    /// The score-facing key (`h67`), kept for text reduction.
    pub gest_key: String,
    pub layer: QuoteLayer,
    pub gsrc_raw: bool,
}

/// One complete state of one event lineage. Content-addressed; pitches are
/// `midi*100 + cents` integers so a chord is exact and orderable.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EventState {
    pub track: String,
    pub bar: u32,
    pub onset_ql: Frac,
    pub dur_ql: Frac,
    pub kind: EventKind,
    pub pitches_midi_cents: Vec<i32>,
    pub gliss_target_midi_cents: Option<i32>,
    pub dynamic: Option<String>,
    pub params: BTreeMap<String, String>,
    pub flags: BTreeSet<String>,
    pub lyric: Option<String>,
    pub quote: Option<Quote>,
}

impl EventState {
    pub fn version_id(&self) -> VersionId {
        VersionId(sha256_hex(canonical_json(self).as_bytes()))
    }
}

// -------------------------------------------------------------------- ops

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "op", rename_all = "kebab-case")]
pub enum OpBody {
    ScoreInit {
        title: String,
    },
    SetHeader {
        key: String,
        value: String,
    },
    DeclareInstrument {
        abbrev: String,
        name: String,
        clef: String,
        params: BTreeMap<String, String>,
    },
    AddEvent {
        state: EventState,
    },
    SupersedeEvent {
        lineage: LineageId,
        /// The version this edit SAW. Fork detection lives here (law 4).
        basis: VersionId,
        state: EventState,
    },
    RetractEvent {
        lineage: LineageId,
        basis: VersionId,
    },
    AddSection {
        name: String,
        from_bar: u32,
        to_bar: u32,
        prose: Option<String>,
    },
    /// Inline bar changes (`bar 11 [tempo=88]:`) — text-face data the graph
    /// must carry so ingest→project→reduce is closed without hand-patching.
    SetBarChanges {
        bar: u32,
        changes: Vec<String>,
    },
    /// A `# text @bN:` margin gloss. Appends in log order (deterministic).
    AddText {
        bar: u32,
        prose: String,
    },
    AnnotatePerformance {
        key: String,
        value: String,
    },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Op {
    pub id: OpId,
    pub actor: String,
    pub seq: u64,
    pub lamport: u64,
    pub body: OpBody,
}

#[derive(Serialize)]
struct OpPreimage<'a> {
    actor: &'a str,
    seq: u64,
    lamport: u64,
    body: &'a OpBody,
}

impl Op {
    pub fn compute_id(actor: &str, seq: u64, lamport: u64, body: &OpBody) -> OpId {
        let pre = OpPreimage {
            actor,
            seq,
            lamport,
            body,
        };
        OpId(sha256_hex(canonical_json(&pre).as_bytes()))
    }
}

// -------------------------------------------------------------------- log

/// Append-only, merge-by-union, deterministically orderable.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct OpLog {
    ops: BTreeMap<OpId, Op>,
}

impl OpLog {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn max_lamport(&self) -> u64 {
        self.ops.values().map(|o| o.lamport).max().unwrap_or(0)
    }

    /// Append a new op authored now by `actor`. Lamport = max(observed)+1.
    /// Returns the op id (which is also the lineage id when the body mints one).
    pub fn append(&mut self, actor: &str, seq: u64, body: OpBody) -> OpId {
        let lamport = self.max_lamport() + 1;
        let id = Op::compute_id(actor, seq, lamport, &body);
        let op = Op {
            id: id.clone(),
            actor: actor.to_string(),
            seq,
            lamport,
            body,
        };
        self.ops.insert(id.clone(), op);
        id
    }

    /// Union merge. Same id ⇒ same op by content-addressing; disagreement on
    /// an id's content would mean a hash collision or a bug, and panics.
    pub fn merge(&mut self, other: &OpLog) {
        for (id, op) in &other.ops {
            match self.ops.get(id) {
                None => {
                    self.ops.insert(id.clone(), op.clone());
                }
                Some(existing) => {
                    assert_eq!(existing, op, "op id collision with divergent content");
                }
            }
        }
    }

    /// The total projection order (law 3): (lamport, actor, seq, id).
    pub fn ordered(&self) -> Vec<&Op> {
        let mut v: Vec<&Op> = self.ops.values().collect();
        v.sort_by(|a, b| {
            (a.lamport, &a.actor, a.seq, &a.id).cmp(&(b.lamport, &b.actor, b.seq, &b.id))
        });
        v
    }

    pub fn len(&self) -> usize {
        self.ops.len()
    }

    pub fn is_empty(&self) -> bool {
        self.ops.is_empty()
    }

    /// Digest of the ordered op-id sequence — the log's identity for receipts.
    pub fn digest(&self) -> String {
        let ids: Vec<&str> = self.ordered().iter().map(|o| o.id.0.as_str()).collect();
        sha256_hex(ids.join("\n").as_bytes())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn state(track: &str, bar: u32, onset_num: i64, pitch_mc: i32) -> EventState {
        EventState {
            track: track.into(),
            bar,
            onset_ql: Frac::new(onset_num, 1),
            dur_ql: Frac::new(1, 1),
            kind: EventKind::Note,
            pitches_midi_cents: vec![pitch_mc],
            gliss_target_midi_cents: None,
            dynamic: None,
            params: BTreeMap::new(),
            flags: BTreeSet::new(),
            lyric: None,
            quote: None,
        }
    }

    #[test]
    fn op_ids_are_content_addressed_and_appends_idempotent_under_merge() {
        let mut a = OpLog::new();
        a.append("vera", 1, OpBody::ScoreInit { title: "t".into() });
        let mut b = a.clone();
        b.merge(&a);
        assert_eq!(b.len(), 1);
        assert_eq!(a.digest(), b.digest());
    }

    #[test]
    fn merge_is_commutative_in_projection_order() {
        let mut base = OpLog::new();
        base.append("vera", 1, OpBody::ScoreInit { title: "t".into() });
        let mut a = base.clone();
        let mut b = base.clone();
        a.append(
            "agent-a",
            1,
            OpBody::AddEvent {
                state: state("gl", 1, 0, 8100),
            },
        );
        b.append(
            "agent-b",
            1,
            OpBody::AddEvent {
                state: state("gl", 1, 1, 8300),
            },
        );
        let mut ab = a.clone();
        ab.merge(&b);
        let mut ba = b.clone();
        ba.merge(&a);
        assert_eq!(ab.digest(), ba.digest());
        let order: Vec<&str> = ab.ordered().iter().map(|o| o.actor.as_str()).collect();
        assert_eq!(order, vec!["vera", "agent-a", "agent-b"]);
    }

    #[test]
    fn version_ids_hash_state_not_history() {
        let s1 = state("gl", 1, 0, 8100);
        let s2 = state("gl", 1, 0, 8100);
        assert_eq!(s1.version_id(), s2.version_id());
        let s3 = state("gl", 1, 0, 8101);
        assert_ne!(s1.version_id(), s3.version_id());
    }

    #[test]
    fn fractions_normalize() {
        assert_eq!(Frac::new(2, 4), Frac::new(1, 2));
        assert_eq!(Frac::new(3, 2) + Frac::new(1, 2), Frac::new(2, 1));
        assert_eq!(Frac::new(1, -2), Frac::new(-1, 2));
    }
}
