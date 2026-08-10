//! The per-event transform chain, in exact oracle order — `mus_audio.py`
//! lines 1034-1096: `chop` → `ring` → `glow` (guarded `len(x) >= 2048`) →
//! `str` (`fit` = stretch-to-slot, else a literal factor) → articulation
//! cuts (`ART_SHORTEN` flags, `gate`, `fer` = stretch 1.75) → envelope
//! (`atk`/`rel`) → `lpf`/`hpf` sweeps → `drive` → `dist` → `crush`/`decim`
//! → `stut`; then the level (dB) an event places at.
//!
//! **Numeric parses match the oracle's own guardedness, site by site.**
//! Most direct `float(ev.params[k])` reads in this chain have no
//! `try/except` in the oracle at all — a malformed value (`chop=abc`) is
//! an uncaught `ValueError` that aborts the *entire render*. This port
//! matches that: [`require_f64`]/[`require_f64_opt`] refuse
//! (`RenderError::Invalid`) on a present-but-unparseable value, the same
//! outcome as the oracle's crash, just structured. Only the sites the
//! oracle itself protects stay lenient here too — `lpf=`/`hpf=` (via
//! [`param_pair`]'s own catch-and-default) and `str=` (an explicit
//! `try/except` at that one call, ported unchanged in
//! [`apply_time_and_cuts`]). `crush=`/`decim=` are their own third shape:
//! `bitcrush`'s Python truthiness check (`if bits:`) treats an
//! *explicitly empty* value the same as absent, so they use
//! [`require_f64_truthy`]/[`require_i64_truthy`] rather than refusing on
//! an empty string the way every other site here does.

use mus_dsp::kernels::{bitcrush, chop_shuffle, hard_clip, ring_mod, soft_clip, stutter};
use mus_dsp::pitch::stretch;
use mus_dsp::SR_F64;
use mus_notation::Note;

use crate::pack::Voice;
use crate::util::{
    dyn_db, param_pair, require_f64, require_f64_opt, require_f64_truthy, require_i64_truthy,
    ART_GAIN, ART_SHORTEN,
};
use crate::RenderError;

/// Lines 1035-1042: chop → ring → glow. Every parse here is unguarded in
/// the oracle (`"key" in ev.params` gates the branch, but the `float()`
/// inside runs unconditionally once that's true) — see this module's doc
/// comment.
pub fn apply_scatter_chain(
    mut x: Vec<f32>,
    ev: &Note,
    slot_s: f64,
) -> Result<Vec<f32>, RenderError> {
    if let Some(n) = require_f64_opt(&ev.params, "chop")? {
        let n_grains = n.max(0.0) as usize;
        let slot_samples = (slot_s * SR_F64).max(0.0) as usize;
        x = chop_shuffle(&x, n_grains, slot_samples);
    }
    if let Some(f_hz) = require_f64_opt(&ev.params, "ring")? {
        // `ring_mod(x, float(ev.params["ring"]), float(ev.params.get(
        // "rwet", 1.0)))` (line 1038-1039) is one unguarded statement —
        // `rwet` aborts on a malformed value exactly like `ring` does,
        // unlike every other site with a `.get(key, default)` shape.
        let wet = require_f64(&ev.params, "rwet", 1.0)?;
        x = ring_mod(&x, f_hz as f32, wet as f32);
    }
    // `"glow" in ev.params and len(x) >= 2048` (line 1040) short-circuits
    // on length before ever touching `float(ev.params["glow"])`, so a
    // malformed `glow=` on a short buffer never even gets parsed, let
    // alone refuses.
    if x.len() >= 2048 {
        if let Some(st_g) = require_f64_opt(&ev.params, "glow")? {
            let slot_samples = (slot_s * SR_F64).max(0.0) as usize;
            x = mus_dsp::glow::glow_chain(&x, st_g, &ev.params, slot_samples);
        }
    }
    Ok(x)
}

/// Lines 1045-1064: time treatment (`str=`) and articulation cuts.
pub fn apply_time_and_cuts(mut x: Vec<f32>, ev: &Note, slot_s: f64) -> Vec<f32> {
    if ev.params.get("str").map(String::as_str) == Some("fit") {
        let cur_s = (x.len() as f64 / SR_F64).max(1e-4);
        x = stretch(&x, slot_s / cur_s);
    } else if let Some(v) = ev.params.get("str") {
        if let Ok(factor) = v.trim().parse::<f64>() {
            x = stretch(&x, factor);
        }
    }

    let mut cut: Option<f64> = None;
    for (name, frac) in ART_SHORTEN {
        if ev.flags.iter().any(|f| f == name) {
            cut = Some(slot_s * frac);
        }
    }
    if ev.flags.iter().any(|f| f == "gate") {
        cut = Some(cut.unwrap_or(slot_s).min(slot_s));
    }
    if ev.flags.iter().any(|f| f == "fer") {
        x = stretch(&x, 1.75);
    }
    if let Some(cut) = cut {
        let nkeep = ((cut * SR_F64) as i64).max(64) as usize;
        if x.len() > nkeep {
            x.truncate(nkeep);
        }
    }
    x
}

/// Lines 1066-1073: attack/release amplitude envelope, via
/// `mus_dsp::glow::event_envelope` (which itself applies the `max(0.0015,
/// ..)`/`max(0.004, ..)` floors and the len/3, len/2 clamps). `atk`/`rel`
/// are each a bare `float(ev.params.get(k, default))` (lines 1067-1068),
/// unguarded.
pub fn apply_envelope(mut x: Vec<f32>, ev: &Note) -> Result<Vec<f32>, RenderError> {
    let atk_s = require_f64(&ev.params, "atk", 0.003)?;
    let rel_s = require_f64(&ev.params, "rel", 0.035)?;
    mus_dsp::glow::event_envelope(&mut x, atk_s, rel_s);
    Ok(x)
}

/// Lines 1076-1089: filter sweeps, drive/dist, crush/decim, stut.
/// `lpf=`/`hpf=` go through [`param_pair`], which the oracle itself
/// guards — stays lenient. `drive=`/`dist=`/`stut=` are each unguarded
/// `"key" in params` + bare `float()`, like [`apply_scatter_chain`]'s
/// sites. `crush=`/`decim=` are bitcrush's own truthiness-gated pair —
/// see this module's doc comment.
pub fn apply_filters_and_grit(
    mut x: Vec<f32>,
    ev: &Note,
    slot_s: f64,
) -> Result<Vec<f32>, RenderError> {
    if ev.params.contains_key("lpf") {
        let (f0, f1) = param_pair(&ev.params, "lpf", 20_000.0);
        x = mus_dsp::filters::sweep_filter(&x, f0, f1, "low", 4, 256);
    }
    if ev.params.contains_key("hpf") {
        let (f0, f1) = param_pair(&ev.params, "hpf", 20.0);
        x = mus_dsp::filters::sweep_filter(&x, f0, f1, "high", 4, 256);
    }
    if let Some(drive) = require_f64_opt(&ev.params, "drive")? {
        x = soft_clip(&x, drive as f32);
    }
    if let Some(amount) = require_f64_opt(&ev.params, "dist")? {
        x = hard_clip(&x, amount as f32);
    }
    if ev.params.contains_key("crush") || ev.params.contains_key("decim") {
        let bits = require_f64_truthy(&ev.params, "crush")?;
        let decim = require_i64_truthy(&ev.params, "decim")?.and_then(|d| u32::try_from(d).ok());
        x = bitcrush(&x, bits, decim);
    }
    if let Some(n) = require_f64_opt(&ev.params, "stut")? {
        let slot_samples = (slot_s * SR_F64).max(0.0) as usize;
        x = stutter(&x, n.max(0.0) as usize, slot_samples);
    }
    Ok(x)
}

/// Runs the whole chain (scatter → time/cuts → envelope → filters/grit),
/// in oracle order.
pub fn apply_chain(x: Vec<f32>, ev: &Note, slot_s: f64) -> Result<Vec<f32>, RenderError> {
    let x = apply_scatter_chain(x, ev, slot_s)?;
    let x = apply_time_and_cuts(x, ev, slot_s);
    let x = apply_envelope(x, ev)?;
    apply_filters_and_grit(x, ev, slot_s)
}

/// Lines 1091-1096: the event's placement gain, in dB. `gain=` is a bare
/// `float(ev.params.get("gain", 0.0))` (line 1096), unguarded.
pub fn level_db(cur_dyn: &str, voice: &Voice, ev: &Note) -> Result<f64, RenderError> {
    let mut db = dyn_db(cur_dyn) + voice.gain_db;
    for (name, g) in ART_GAIN {
        if ev.flags.iter().any(|f| f == name) {
            db += g;
        }
    }
    db += require_f64(&ev.params, "gain", 0.0)?;
    Ok(db)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    fn note_with(params: &[(&str, &str)], flags: &[&str]) -> Note {
        Note {
            kind: "note".into(),
            midis: vec![69.0],
            ql: 1.0,
            params: params
                .iter()
                .map(|(k, v)| (k.to_string(), v.to_string()))
                .collect(),
            flags: flags.iter().map(|s| s.to_string()).collect(),
            dyn_value: None,
            gliss_midi: None,
        }
    }

    #[test]
    fn art_shorten_flags_take_last_match_and_gate_clamps() {
        let n = note_with(&[], &["stac", "detlg"]);
        let x = vec![1.0f32; 48_000];
        // detlg (0.75) is listed after stac (0.40) in ART_SHORTEN, so it
        // wins per the oracle's dict-iteration overwrite.
        let out = apply_time_and_cuts(x, &n, 1.0);
        assert_eq!(out.len(), (0.75 * SR_F64) as usize);
    }

    #[test]
    fn gate_alone_keeps_the_full_slot() {
        let n = note_with(&[], &["gate"]);
        let x = vec![1.0f32; 48_000];
        let out = apply_time_and_cuts(x, &n, 0.5);
        assert_eq!(out.len(), (0.5 * SR_F64) as usize);
    }

    /// The oracle's own uncaught `ValueError` for a malformed-but-present
    /// `chop=` — this port refuses (structured), not "the render succeeds
    /// with one quietly-unmodified note" (the prior port's bug).
    #[test]
    fn malformed_numeric_param_refuses_rather_than_no_opping() {
        let n = note_with(&[("chop", "not-a-number")], &[]);
        let x = vec![0.5f32; 4096];
        let err = apply_scatter_chain(x, &n, 0.1).unwrap_err();
        assert!(
            matches!(err, RenderError::Invalid(ref m) if m.contains("chop=\"not-a-number\"")),
            "{err}"
        );
    }

    #[test]
    fn malformed_ring_or_rwet_both_refuse_since_the_oracle_reads_them_in_one_unguarded_statement() {
        let bad_ring = note_with(&[("ring", "buzz")], &[]);
        assert!(apply_scatter_chain(vec![0.5f32; 64], &bad_ring, 0.1).is_err());

        let bad_rwet = note_with(&[("ring", "440"), ("rwet", "wet")], &[]);
        assert!(apply_scatter_chain(vec![0.5f32; 64], &bad_rwet, 0.1).is_err());
    }

    #[test]
    fn glow_trigger_only_refuses_when_the_buffer_is_long_enough_to_be_attempted() {
        // Short-circuit: Python's `"glow" in params and len(x) >= 2048`
        // never even reaches `float(ev.params["glow"])` when the buffer
        // is short, so a malformed value there is never inspected.
        let n = note_with(&[("glow", "nope")], &[]);
        let short = apply_scatter_chain(vec![0.1f32; 100], &n, 0.5).unwrap();
        assert_eq!(short.len(), 100);

        let err = apply_scatter_chain(vec![0.1f32; 4096], &n, 0.5).unwrap_err();
        assert!(
            matches!(err, RenderError::Invalid(ref m) if m.contains("glow")),
            "{err}"
        );
    }

    #[test]
    fn drive_dist_stut_atk_rel_all_refuse_on_a_malformed_present_value() {
        let x = || vec![0.3f32; 48_000];
        assert!(apply_filters_and_grit(x(), &note_with(&[("drive", "hot")], &[]), 1.0).is_err());
        assert!(apply_filters_and_grit(x(), &note_with(&[("dist", "hot")], &[]), 1.0).is_err());
        assert!(apply_filters_and_grit(x(), &note_with(&[("stut", "many")], &[]), 1.0).is_err());
        assert!(apply_envelope(x(), &note_with(&[("atk", "slow")], &[])).is_err());
        assert!(apply_envelope(x(), &note_with(&[("rel", "slow")], &[])).is_err());
    }

    /// `bitcrush`'s own Python truthiness gate: an explicitly empty
    /// `crush=`/`decim=` is falsy and silently skipped (never even
    /// reaches `float`/`int`), unlike every other site in this chain —
    /// but a non-empty malformed value still refuses.
    #[test]
    fn crush_and_decim_treat_an_empty_value_as_absent_but_still_refuse_when_malformed() {
        let x = vec![0.3f32; 4096];
        let empty_crush = note_with(&[("crush", "")], &[]);
        let out = apply_filters_and_grit(x.clone(), &empty_crush, 1.0).unwrap();
        assert_eq!(out, x, "crush= (empty) must no-op, not refuse");

        let empty_decim = note_with(&[("decim", "")], &[]);
        let out = apply_filters_and_grit(x.clone(), &empty_decim, 1.0).unwrap();
        assert_eq!(out, x, "decim= (empty) must no-op, not refuse");

        let bad_crush = note_with(&[("crush", "lots")], &[]);
        assert!(apply_filters_and_grit(x.clone(), &bad_crush, 1.0).is_err());

        // `int("3.5")` is not a valid Python int literal — refuses, unlike
        // the f64 sites, which would happily accept "3.5".
        let fractional_decim = note_with(&[("decim", "3.5")], &[]);
        assert!(apply_filters_and_grit(x, &fractional_decim, 1.0).is_err());
    }

    #[test]
    fn level_db_sums_dynamic_voice_gain_articulation_and_param() {
        let voice = Voice {
            abbrev: "v".into(),
            samples: Vec::new(),
            mode: "varispeed".into(),
            gain_db: 2.0,
            pan: 0.0,
            send: 0.12,
            defaults: BTreeMap::new(),
            synth: None,
            ducks: true,
        };
        let n = note_with(&[("gain", "1.5")], &["acc"]);
        // mf (-11.0) + voice gain (2.0) + acc (4.0) + event gain (1.5)
        assert!((level_db("mf", &voice, &n).unwrap() - (-11.0 + 2.0 + 4.0 + 1.5)).abs() < 1e-9);
    }

    #[test]
    fn level_db_refuses_on_a_malformed_gain_param() {
        let voice = Voice {
            abbrev: "v".into(),
            samples: Vec::new(),
            mode: "varispeed".into(),
            gain_db: 0.0,
            pan: 0.0,
            send: 0.12,
            defaults: BTreeMap::new(),
            synth: None,
            ducks: true,
        };
        let n = note_with(&[("gain", "loud")], &[]);
        assert!(level_db("mf", &voice, &n).is_err());
    }
}
