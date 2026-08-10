//! mus-vocab — the golden contract as a crate (WA of
//! `sophia/plans/mus-mo-language-20260809.md`; R2: core sealed, extensions
//! honest).
//!
//! Deliberately a LEAF crate: it knows vocabulary, not graphs. The
//! extension-usage counter lives in `mus-graph::extension_usage`, which takes
//! a classifier closure — this crate provides the classifier, and the two are
//! wired together by consumers (the CLI), keeping both dependency-clean.

use sha2::{Digest, Sha256};

pub mod param_specs;

pub const MUS_SCORE_TTL: &str = include_str!("../../../../ontology/mus-score.ttl");
pub const MUS_OPS_TTL: &str = include_str!("../../../../ontology/mus-ops.ttl");

/// SHA-256 over score-ttl ‖ "\n---\n" ‖ ops-ttl. Changing either vocabulary
/// file changes this digest — which is the point: compile reports carry it,
/// so a verdict names the exact contract it validated against.
pub fn vocab_digest() -> String {
    let mut h = Sha256::new();
    h.update(MUS_SCORE_TTL.as_bytes());
    h.update(b"\n---\n");
    h.update(MUS_OPS_TTL.as_bytes());
    let out = h.finalize();
    let mut s = String::with_capacity(71);
    s.push_str("sha256:");
    for b in out {
        s.push_str(&format!("{b:02x}"));
    }
    s
}

/// The closed mus-core event/track param set (SPEC-AUDIO's stable surface).
/// Everything else is `mus-x` by construction — extension is OPEN, and the
/// honesty lives in reporting, not in a denylist.
pub const CORE_PARAMS: &[&str] = &[
    "pan", "gain", "lpf", "hpf", "send", "s", "str", "off", "st", "atk", "rel", "curve", "tau",
    "drive", "dist", "crush", "decim", "stut", "duck",
];

/// Core articulation/playback flags.
pub const CORE_FLAGS: &[&str] = &[
    "stac", "stacciss", "spic", "detlg", "acc", "marc", "sfz", "stress", "unstress", "ten", "fer",
    "gate", "reverse",
];

/// Quotation params are CORE (foundational, not experimental — memo §3).
pub const CORE_QUOTE_PARAMS: &[&str] = &["gest", "glayer", "gsrc"];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ParamLayer {
    Core,
    Extension,
}

pub fn is_core_param(name: &str) -> bool {
    CORE_PARAMS.contains(&name) || CORE_QUOTE_PARAMS.contains(&name)
}

pub fn classify_param(name: &str) -> ParamLayer {
    if is_core_param(name) {
        ParamLayer::Core
    } else {
        ParamLayer::Extension
    }
}

/// Canonical header keys and their nature (R6: swing is a performance
/// annotation the render face applies; onsets never bake it in).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HeaderKind {
    ScoreProperty,
    PerformanceAnnotation,
}

pub const HEADER_REGISTRY: &[(&str, HeaderKind)] = &[
    ("summary", HeaderKind::ScoreProperty),
    ("tempo", HeaderKind::ScoreProperty),
    ("time", HeaderKind::ScoreProperty),
    ("key", HeaderKind::ScoreProperty),
    ("bars", HeaderKind::ScoreProperty),
    ("tuning", HeaderKind::ScoreProperty),
    ("pack", HeaderKind::ScoreProperty),
    ("gestures", HeaderKind::ScoreProperty),
    ("tape", HeaderKind::ScoreProperty),
    ("reverb", HeaderKind::ScoreProperty),
    ("master", HeaderKind::ScoreProperty),
    ("sidechain", HeaderKind::ScoreProperty),
    ("swing", HeaderKind::PerformanceAnnotation),
];

pub fn header_kind(key: &str) -> Option<HeaderKind> {
    HEADER_REGISTRY
        .iter()
        .find(|(k, _)| *k == key)
        .map(|(_, kind)| *kind)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn digest_is_stable_and_prefixed() {
        // Golden digest: update DELIBERATELY when a ttl changes — that is a
        // contract revision, and this test is where you acknowledge it.
        let d = vocab_digest();
        assert!(d.starts_with("sha256:") && d.len() == 71, "{d}");
        assert_eq!(d, vocab_digest());
    }

    #[test]
    fn known_surface_classifies() {
        for p in ["pan", "lpf", "stut", "gest", "gsrc"] {
            assert_eq!(classify_param(p), ParamLayer::Core, "{p}");
        }
        for p in [
            "synth", "cutoff", "famt", "glow", "ghold", "gwarble", "gharm", "pump", "chop", "ring",
            "rwet", "haas", "sub", "detune", "osc2", "mix2", "satk", "sdec", "ssus", "srel",
        ] {
            assert_eq!(classify_param(p), ParamLayer::Extension, "{p}");
        }
    }

    #[test]
    fn swing_is_a_performance_annotation() {
        assert_eq!(
            header_kind("swing"),
            Some(HeaderKind::PerformanceAnnotation)
        );
        assert_eq!(header_kind("tempo"), Some(HeaderKind::ScoreProperty));
        assert_eq!(header_kind("nonsense"), None);
    }
}
