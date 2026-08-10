//! Small pitch/parameter helpers used across the render orchestrator that
//! don't belong to any single stage's `mus-dsp` module: `mus_audio.py`'s
//! own "pitch utils" section (lines 65-80: `note_to_midi`, `midi_to_hz`),
//! `param_pair` (line 698), and the level-lookup tables (`DYN_DB`,
//! `ART_GAIN`, `ART_SHORTEN`, lines 56-62).
//!
//! `note_to_midi` here is deliberately a *second* pitch parser alongside
//! `mus_notation`'s private one: that crate's is used internally by
//! `parse_token` and isn't `pub`, and the only call site here is the
//! `root=` instrument-header fallback (`mus_audio.py` line 760), which
//! parses a bare pitch name the same way event tokens do. Small enough
//! (one regex) to duplicate rather than plumb a new export through a
//! crate this stage doesn't otherwise touch.

use std::collections::BTreeMap;
use std::sync::OnceLock;

use regex::Regex;

use crate::RenderError;

/// `mus_audio.RE_NOTE` (line 52): `A-G`, optional accidental
/// (`bb|b|n|##|#|x`, longest-alternative-first exactly as the Python
/// alternation order requires), a mandatory signed octave, an optional
/// signed cents suffix.
fn re_note() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"^([A-G])(bb|b|n|##|#|x)?(-?\d+)([+-]\d+)?$").unwrap())
}

/// `mus_audio.note_to_midi` (line 67): note token to fractional MIDI
/// (cents folded in as `/100.0`), or `None` on no match.
pub fn note_to_midi(tok: &str) -> Option<f64> {
    let caps = re_note().captures(tok)?;
    let step = caps.get(1)?.as_str().chars().next()?;
    let acc_offset = match caps.get(2).map(|m| m.as_str()) {
        None => 0,
        Some("n") => 0,
        Some("b") => -1,
        Some("bb") => -2,
        Some("#") => 1,
        Some("##") => 2,
        Some("x") => 2,
        Some(_) => 0,
    };
    let octave: i64 = caps.get(3)?.as_str().parse().ok()?;
    let cents: i64 = match caps.get(4) {
        Some(m) => m.as_str().parse().ok()?,
        None => 0,
    };
    let base = match step {
        'C' => 0,
        'D' => 2,
        'E' => 4,
        'F' => 5,
        'G' => 7,
        'A' => 9,
        'B' => 11,
        _ => return None,
    };
    Some((octave as f64 + 1.0) * 12.0 + base as f64 + acc_offset as f64 + cents as f64 / 100.0)
}

/// `mus_audio.midi_to_hz` (line 78).
pub fn midi_to_hz(midi: f64, a4: f64) -> f64 {
    a4 * 2f64.powf((midi - 69.0) / 12.0)
}

/// `mus_audio.param_pair` (line 698): a param may be a scalar or an
/// `"a->b"` sweep string; always returns `(start, end)`, falling back to
/// `(default, default)` on a missing key or an unparseable scalar/side.
pub fn param_pair(params: &BTreeMap<String, String>, key: &str, default: f64) -> (f64, f64) {
    let Some(v) = params.get(key) else {
        return (default, default);
    };
    if let Some((a, b)) = v.split_once("->") {
        return match (a.trim().parse::<f64>(), b.trim().parse::<f64>()) {
            (Ok(a), Ok(b)) => (a, b),
            _ => (default, default),
        };
    }
    match v.trim().parse::<f64>() {
        Ok(f) => (f, f),
        Err(_) => (default, default),
    }
}

/// A `float(params.get(key, default))` read at a site the oracle leaves
/// *unguarded*: `mus_audio.py`'s transform chain reads most event params
/// with a bare `float(...)`, no `try/except` — a malformed-but-present
/// value (`gain=abc`) is an uncaught `ValueError` that aborts the whole
/// render. This port matches that outcome with a `RenderError::Invalid`
/// refusal instead of silently defaulting: an absent key still yields
/// `default` (matching `.get(key, default)`), but a present, unparseable
/// value now refuses rather than pretending the key was absent.
///
/// Reserve this (and [`require_f64_opt`]) for the sites that are
/// genuinely unguarded in the oracle. The sites the oracle itself
/// protects — [`param_pair`]'s own catch-and-default, `swing`/`sidechain`
/// header parsing, and `str=`'s explicit `try/except` — stay lenient on
/// the Rust side too, and must keep using a plain `.and_then(|v|
/// v.parse().ok())` rather than this helper.
pub fn require_f64(
    params: &BTreeMap<String, String>,
    key: &str,
    default: f64,
) -> Result<f64, RenderError> {
    match params.get(key) {
        None => Ok(default),
        Some(v) => v
            .trim()
            .parse::<f64>()
            .map_err(|_| RenderError::Invalid(format!("{key}={v:?} is not a number"))),
    }
}

/// As [`require_f64`], but for the oracle's `if "key" in params:
/// f(float(params["key"]))` shape: `Ok(None)` when the key is absent
/// (skip the transform entirely, exactly like the oracle's own `if`),
/// `Ok(Some(v))` when present and numeric, `Err` when present but
/// malformed — the oracle's uncaught `ValueError` there, ported as a
/// refusal.
pub fn require_f64_opt(
    params: &BTreeMap<String, String>,
    key: &str,
) -> Result<Option<f64>, RenderError> {
    match params.get(key) {
        None => Ok(None),
        Some(v) => v
            .trim()
            .parse::<f64>()
            .map(Some)
            .map_err(|_| RenderError::Invalid(format!("{key}={v:?} is not a number"))),
    }
}

/// `crush=`/`decim=` alone: `mus_audio.bitcrush(x, ev.params.get("crush"),
/// ev.params.get("decim"))` gates each with Python *truthiness*
/// (`if bits:` / `if decim:`), not mere presence — unlike every other
/// site in the transform chain, an explicitly empty value (`crush=`) is
/// falsy and silently skipped, `float`/`int` never even called, so it
/// must not refuse here the way an empty `chop=`/`drive=`/... does.
pub fn require_f64_truthy(
    params: &BTreeMap<String, String>,
    key: &str,
) -> Result<Option<f64>, RenderError> {
    match params.get(key).map(|v| v.trim()) {
        None | Some("") => Ok(None),
        Some(v) => v
            .parse::<f64>()
            .map(Some)
            .map_err(|_| RenderError::Invalid(format!("{key}={v:?} is not a number"))),
    }
}

/// [`require_f64_truthy`]'s `int(decim)` counterpart.
pub fn require_i64_truthy(
    params: &BTreeMap<String, String>,
    key: &str,
) -> Result<Option<i64>, RenderError> {
    match params.get(key).map(|v| v.trim()) {
        None | Some("") => Ok(None),
        Some(v) => v
            .parse::<i64>()
            .map(Some)
            .map_err(|_| RenderError::Invalid(format!("{key}={v:?} is not an integer"))),
    }
}

/// Prefixes a [`RenderError::Invalid`]'s message with `prefix` (other
/// variants pass through unchanged) — attaches bar/track (or instrument,
/// or header) context to a numeric-parse refusal, matching `stats.bad`'s
/// own `"b{b} {abbr}: ..."` convention.
pub fn with_context(prefix: &str, err: RenderError) -> RenderError {
    match err {
        RenderError::Invalid(msg) => RenderError::Invalid(format!("{prefix}: {msg}")),
        other => other,
    }
}

/// Dynamic marking to dB trim relative to unity. `mus_audio.DYN_DB` (line 57).
pub const DYN_DB: &[(&str, f64)] = &[
    ("ppp", -30.0),
    ("pp", -25.0),
    ("p", -20.0),
    ("mp", -15.0),
    ("mf", -11.0),
    ("f", -7.0),
    ("ff", -3.5),
    ("fff", 0.0),
    ("sfz", -2.0),
    ("sf", -3.0),
];

/// `mus_audio.ART_GAIN` (line 61): articulation flags that add dB.
pub const ART_GAIN: &[(&str, f64)] = &[
    ("acc", 4.0),
    ("marc", 6.0),
    ("sfz", 7.0),
    ("stress", 2.5),
    ("unstress", -4.0),
];

/// `mus_audio.ART_SHORTEN` (line 62): articulation flags that cut the
/// tail to `slot * fraction`.
pub const ART_SHORTEN: &[(&str, f64)] = &[
    ("stac", 0.40),
    ("stacciss", 0.25),
    ("spic", 0.35),
    ("detlg", 0.75),
];

pub fn dyn_db(dynamic: &str) -> f64 {
    DYN_DB
        .iter()
        .find(|(name, _)| *name == dynamic)
        .map(|(_, db)| *db)
        .unwrap_or(-11.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn note_to_midi_matches_python_regex_semantics() {
        assert_eq!(note_to_midi("A4"), Some(69.0));
        assert_eq!(note_to_midi("C4"), Some(60.0));
        assert_eq!(note_to_midi("A6+22"), Some(93.22));
        assert_eq!(note_to_midi("A6-5"), Some(92.95));
        assert_eq!(note_to_midi("Cbb4"), Some(58.0));
        assert_eq!(note_to_midi("Cx4"), Some(62.0));
        assert_eq!(note_to_midi("C##4"), Some(62.0));
        assert_eq!(note_to_midi("Cn4"), Some(60.0));
        assert_eq!(note_to_midi("H4"), None);
        assert_eq!(note_to_midi("C"), None);
        assert_eq!(note_to_midi("Cbn4"), None);
    }

    #[test]
    fn midi_to_hz_a440() {
        assert!((midi_to_hz(69.0, 440.0) - 440.0).abs() < 1e-9);
        assert!((midi_to_hz(81.0, 440.0) - 880.0).abs() < 1e-9);
    }

    #[test]
    fn param_pair_scalar_sweep_and_fallback() {
        let mut p = BTreeMap::new();
        p.insert("pan".to_string(), "0.5".to_string());
        assert_eq!(param_pair(&p, "pan", 0.0), (0.5, 0.5));
        p.insert("lpf".to_string(), "70->900".to_string());
        assert_eq!(param_pair(&p, "lpf", 20000.0), (70.0, 900.0));
        assert_eq!(param_pair(&p, "hpf", 20.0), (20.0, 20.0));
        p.insert("bad".to_string(), "nope".to_string());
        assert_eq!(param_pair(&p, "bad", 5.0), (5.0, 5.0));
    }

    #[test]
    fn require_f64_defaults_on_absence_and_refuses_on_malformed_presence() {
        let mut p = BTreeMap::new();
        assert_eq!(require_f64(&p, "gain", 0.0).unwrap(), 0.0);
        p.insert("gain".to_string(), "3.5".to_string());
        assert_eq!(require_f64(&p, "gain", 0.0).unwrap(), 3.5);
        p.insert("gain".to_string(), "loud".to_string());
        let err = require_f64(&p, "gain", 0.0).unwrap_err();
        assert!(matches!(err, RenderError::Invalid(ref m) if m.contains("gain")));
        // Present-but-empty is still "present" for this shape (matches
        // Python's `float(params.get(key, default))`, which never
        // substitutes the default once the key exists).
        p.insert("gain".to_string(), "".to_string());
        assert!(require_f64(&p, "gain", 0.0).is_err());
    }

    #[test]
    fn require_f64_opt_is_none_on_absence_and_refuses_on_malformed_presence() {
        let mut p = BTreeMap::new();
        assert_eq!(require_f64_opt(&p, "chop").unwrap(), None);
        p.insert("chop".to_string(), "8".to_string());
        assert_eq!(require_f64_opt(&p, "chop").unwrap(), Some(8.0));
        p.insert("chop".to_string(), "many".to_string());
        assert!(require_f64_opt(&p, "chop").is_err());
        // Empty is still "present" for this shape too — chop/ring/drive/
        // dist/stut/haas/off/glow all guard on presence, not truthiness.
        p.insert("chop".to_string(), "".to_string());
        assert!(require_f64_opt(&p, "chop").is_err());
    }

    #[test]
    fn require_f64_truthy_treats_an_empty_value_as_absent() {
        let mut p = BTreeMap::new();
        assert_eq!(require_f64_truthy(&p, "crush").unwrap(), None);
        p.insert("crush".to_string(), "".to_string());
        assert_eq!(
            require_f64_truthy(&p, "crush").unwrap(),
            None,
            "crush= (empty) is falsy in Python, not a refusal"
        );
        p.insert("crush".to_string(), "6".to_string());
        assert_eq!(require_f64_truthy(&p, "crush").unwrap(), Some(6.0));
        p.insert("crush".to_string(), "lots".to_string());
        assert!(require_f64_truthy(&p, "crush").is_err());
    }

    #[test]
    fn require_i64_truthy_matches_pythons_int_not_float() {
        let mut p = BTreeMap::new();
        p.insert("decim".to_string(), "4".to_string());
        assert_eq!(require_i64_truthy(&p, "decim").unwrap(), Some(4));
        // Python's `int("3.5")` raises (not a valid int literal) — so does
        // this, unlike the f64 sites.
        p.insert("decim".to_string(), "3.5".to_string());
        assert!(require_i64_truthy(&p, "decim").is_err());
    }

    #[test]
    fn with_context_prefixes_invalid_and_passes_other_variants_through() {
        let err = with_context(
            "b3 kk",
            RenderError::Invalid("gain=x is not a number".into()),
        );
        assert!(matches!(err, RenderError::Invalid(ref m) if m == "b3 kk: gain=x is not a number"));
    }
}
