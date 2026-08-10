//! Golden tests for stage WF5 — the subtractive soft synth
//! (`mus-dsp/src/synth.rs`). Same pattern as `golden_kernels.rs`/
//! `golden_filters.rs`: resolve the case by manifest name, run the port,
//! `check` against the oracle's recorded output — no hand-written
//! expectations, no tolerance literals here.
//!
//! `osc_phase` (dtype `<f8`, no `input` file of its own) is the *shared*
//! phase array for the four `osc_*` cases — its own `expected` vector is
//! the input the four wave-shape cases were rendered from, per the
//! manifest note "shared phase array for the four osc cases".
//!
//! `synth_note`'s `patch` argument arrives in the manifest as a JSON
//! object; `patch_from_json` below is test-only glue converting that into
//! a [`Patch`] — production code only needs the `BTreeMap<String,
//! String>` constructor `synth.rs` ships (event params, per the WF5
//! spec), not a JSON one.

use serde_json::Value;

use mus_dsp::fixtures::case;
use mus_dsp::synth::{osc, synth_note, Patch};
use mus_dsp::SR_F64;

fn phase() -> Vec<f64> {
    case("osc_phase").expected
}

#[test]
fn osc_saw() {
    let c = case("osc_saw");
    c.check(&osc("saw", &phase()));
}

#[test]
fn osc_square() {
    let c = case("osc_square");
    c.check(&osc("square", &phase()));
}

#[test]
fn osc_tri() {
    let c = case("osc_tri");
    c.check(&osc("tri", &phase()));
}

#[test]
fn osc_sine() {
    let c = case("osc_sine");
    c.check(&osc("sine", &phase()));
}

/// Builds a [`Patch`] from a fixture's `"patch"` JSON object. Mirrors
/// `synth.rs`'s own `From<&BTreeMap<String, String>>` field-for-field,
/// just reading typed JSON instead of strings.
fn patch_from_json(v: &Value) -> Patch {
    let mut p = Patch::default();
    if let Some(s) = v.get("synth").and_then(Value::as_str) {
        p.wave = s.to_string();
    }
    if let Some(s) = v.get("osc2").and_then(Value::as_str) {
        if !s.is_empty() {
            p.osc2 = Some(s.to_string());
        }
    }
    if let Some(x) = v.get("mix2").and_then(Value::as_f64) {
        p.mix2 = x;
    }
    if let Some(x) = v.get("detune").and_then(Value::as_f64) {
        p.detune = x;
    }
    if let Some(x) = v.get("sub").and_then(Value::as_f64) {
        p.sub = x;
    }
    if let Some(x) = v.get("cutoff").and_then(Value::as_f64) {
        p.cutoff = x;
    }
    if let Some(x) = v.get("famt").and_then(Value::as_f64) {
        p.famt = x;
    }
    if let Some(x) = v.get("satk").and_then(Value::as_f64) {
        p.satk = x;
    }
    if let Some(x) = v.get("sdec").and_then(Value::as_f64) {
        p.sdec = x;
    }
    if let Some(x) = v.get("ssus").and_then(Value::as_f64) {
        p.ssus = x;
    }
    if let Some(x) = v.get("srel").and_then(Value::as_f64) {
        p.srel = x;
    }
    p
}

fn freqs_of(v: &Value) -> Vec<f64> {
    v["freqs_hz"]
        .as_array()
        .expect("freqs_hz is an array")
        .iter()
        .map(|x| x.as_f64().expect("freq is numeric"))
        .collect()
}

/// `gliss_ratio` defaults to 1.0 in this fixture, which routes every
/// fundamental through `synth.rs`'s private `tone_static` scalar/
/// broadcast path — see that function's doc for why the un-glissed
/// render carries no audio-rate oscillation at all. This case is the one
/// golden vector that arbitrates that path.
#[test]
fn synth_note_funk_bass() {
    let c = case("synth_note_funk_bass");
    let patch = patch_from_json(&c.meta.args["patch"]);
    let freqs = freqs_of(&c.meta.args);
    let slot_s = c.arg_f64("slot_s");
    let gliss_ratio = c.arg_f64("gliss_ratio");
    c.check(&synth_note(&patch, &freqs, slot_s, gliss_ratio));
}

/// `gliss_ratio=1.5` routes every fundamental through the genuine
/// per-sample ramp path, and with 3 fundamentals also exercises the
/// `1/sqrt(k)` chord normalization and the `osc2` mix.
#[test]
fn synth_note_chord_gliss() {
    let c = case("synth_note_chord_gliss");
    let patch = patch_from_json(&c.meta.args["patch"]);
    let freqs = freqs_of(&c.meta.args);
    let slot_s = c.arg_f64("slot_s");
    let gliss_ratio = c.arg_f64("gliss_ratio");
    c.check(&synth_note(&patch, &freqs, slot_s, gliss_ratio));
}

/// Spec-required unit test: chord normalization is `1/sqrt(k)`. `k`
/// identical fundamentals must render to exactly `sqrt(k)` times a
/// single fundamental's render — accumulate-then-divide-by-`sqrt(k)` is
/// the only place `k` enters, and both the ADSR envelope multiply and
/// the sweep filter are linear operations, so scaling commutes through
/// them up to float re-association.
///
/// Uses a non-1 `gliss_ratio` so every fundamental takes the genuinely-
/// oscillating ramp path — on the static/broadcast path every fundamental
/// collapses to a flat per-sample constant regardless of `k`, which would
/// make this identity trivially true rather than a real check of the
/// normalization arithmetic.
#[test]
fn chord_normalization_is_one_over_sqrt_k() {
    let patch = Patch::default();
    let single = synth_note(&patch, &[220.0], 0.2, 1.3);
    let k = 3usize;
    let chord = synth_note(&patch, &[220.0; 3], 0.2, 1.3);
    assert_eq!(
        single.len(),
        chord.len(),
        "k identical tones don't change n"
    );

    let scale = (k as f64).sqrt() as f32;
    let (mut worst, mut at) = (0.0f32, 0usize);
    for (i, (&a, &b)) in chord.iter().zip(single.iter()).enumerate() {
        let d = (a - b * scale).abs();
        if d > worst {
            worst = d;
            at = i;
        }
    }
    // Empirically-derived headroom for float re-association through the
    // accumulate/filter pipeline (three additions instead of one scalar
    // multiply, then the same IIR sweep run on differently-scaled input)
    // — not a manifest tolerance, since this identity has no fixture.
    // Measured worst case is ~1.2e-7; this leaves ~80x headroom.
    assert!(
        worst < 1e-5,
        "chord(k={k}) should equal single*sqrt(k) up to float rounding; \
         worst diff {worst:.3e} at [{at}] (chord {}, single*scale {})",
        chord[at],
        single[at] * scale
    );
}

/// Spec-required unit test: `n = max(64, (slot_s+srel)*SR)` floors at 64
/// samples even when `slot_s` and `srel` are both effectively zero, and
/// tracks the formula exactly once their sum clears the floor.
#[test]
fn buffer_length_floors_at_64_samples() {
    let tiny = Patch {
        srel: 0.0,
        ..Patch::default()
    };
    let y = synth_note(&tiny, &[220.0], 0.0, 1.0);
    assert_eq!(
        y.len(),
        64,
        "slot_s=0, srel=0 must floor to the 64-sample minimum"
    );

    let longer = Patch {
        srel: 0.12,
        ..Patch::default()
    };
    let y2 = synth_note(&longer, &[220.0], 0.5, 1.0);
    assert_eq!(
        y2.len(),
        ((0.5 + 0.12) * SR_F64) as usize,
        "once slot_s+srel clears the floor, n tracks it exactly"
    );
    assert!(y2.len() > 64);
}

/// `Patch::from(&BTreeMap<String, String>)`: present-and-parseable
/// overrides the default, an unparseable value falls back to the
/// default instead of panicking, a missing key falls back to the
/// default, and an empty-string `osc2` is treated as absent — matching
/// Python's `if osc2:` truthiness on `patch.get("osc2")`.
#[test]
fn patch_from_btreemap_parses_and_defaults() {
    use std::collections::BTreeMap;
    let mut params = BTreeMap::new();
    params.insert("synth".to_string(), "square".to_string());
    params.insert("cutoff".to_string(), "1500".to_string());
    params.insert("osc2".to_string(), "".to_string());
    params.insert("mix2".to_string(), "not-a-number".to_string());

    let p = Patch::from(&params);
    assert_eq!(p.wave, "square");
    assert_eq!(p.cutoff, 1500.0);
    assert_eq!(
        p.osc2, None,
        "empty-string osc2 is falsy, matching Python's `if osc2:`"
    );
    assert_eq!(
        p.mix2, 0.5,
        "unparseable value falls back to the default, not a panic"
    );
    assert_eq!(p.detune, 0.0, "missing key falls back to the default");
}
