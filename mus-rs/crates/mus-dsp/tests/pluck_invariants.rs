//! Invariants for the post-Karplus string network.
//!
//! There is no external golden vector for original synthesis work, so the
//! tests assert the promises that matter: deterministic identity, tuning,
//! T60, spatial pluck physics, dispersion, tension relaxation, physical
//! bends, block/stream parity, audible topology, and boundedness.

use std::collections::BTreeMap;

use mus_dsp::pluck::{pluck_note, weave_note, StringNetworkVoice};
use mus_dsp::SR_F64;

fn params(pairs: &[(&str, &str)]) -> BTreeMap<String, String> {
    pairs
        .iter()
        .map(|(key, value)| (key.to_string(), value.to_string()))
        .collect()
}

fn isolated(extra: &[(&str, &str)]) -> BTreeMap<String, String> {
    let mut patch = params(&[
        ("synth", "pluck"),
        ("body", "0"),
        ("symp", "0"),
        ("stiff", "0"),
        ("tension", "0"),
        ("buzz", "0"),
        ("detune", "0"),
        ("strum", "0"),
    ]);
    for (key, value) in extra {
        patch.insert((*key).to_string(), (*value).to_string());
    }
    patch
}

fn rms(values: &[f32]) -> f64 {
    (values
        .iter()
        .map(|&value| (value as f64) * (value as f64))
        .sum::<f64>()
        / values.len().max(1) as f64)
        .sqrt()
}

fn autocorrelation_f0(values: &[f32], lo_hz: f64, hi_hz: f64) -> f64 {
    let min_lag = (SR_F64 / hi_hz) as usize;
    let max_lag = (SR_F64 / lo_hz) as usize;
    let mut best = (f64::NEG_INFINITY, min_lag);
    for lag in min_lag..=max_lag.min(values.len() / 2) {
        let correlation = values[..values.len() - lag]
            .iter()
            .zip(values[lag..].iter())
            .map(|(&left, &right)| left as f64 * right as f64)
            .sum::<f64>();
        if correlation > best.0 {
            best = (correlation, lag);
        }
    }
    let correlation = |lag: usize| -> f64 {
        values[..values.len() - lag]
            .iter()
            .zip(values[lag..].iter())
            .map(|(&left, &right)| left as f64 * right as f64)
            .sum()
    };
    let lag = best.1;
    if lag <= min_lag || lag + 1 >= max_lag {
        return SR_F64 / lag as f64;
    }
    let (a, b, c) = (correlation(lag - 1), correlation(lag), correlation(lag + 1));
    let denominator = a - 2.0 * b + c;
    let refinement = if denominator.abs() > 1e-12 {
        0.5 * (a - c) / denominator
    } else {
        0.0
    };
    SR_F64 / (lag as f64 + refinement)
}

fn estimate_f0(values: &[f32], start_s: f64, end_s: f64, lo_hz: f64, hi_hz: f64) -> f64 {
    let start = (start_s * SR_F64) as usize;
    let end = ((end_s * SR_F64) as usize).min(values.len());
    autocorrelation_f0(&values[start..end], lo_hz, hi_hz)
}

fn goertzel(values: &[f32], frequency: f64) -> f64 {
    let omega = 2.0 * std::f64::consts::PI * frequency / SR_F64;
    let coefficient = 2.0 * omega.cos();
    let (mut state_1, mut state_2) = (0.0_f64, 0.0_f64);
    for &value in values {
        let state_0 = value as f64 + coefficient * state_1 - state_2;
        state_2 = state_1;
        state_1 = state_0;
    }
    state_1 * state_1 + state_2 * state_2 - coefficient * state_1 * state_2
}

fn spectral_peak(values: &[f32], center_hz: f64, fractional_span: f64) -> f64 {
    let steps = 120;
    let mut best = (f64::NEG_INFINITY, center_hz);
    for step in 0..=steps {
        let position = step as f64 / steps as f64;
        let frequency = center_hz * (1.0 - fractional_span + 2.0 * fractional_span * position);
        let power = goertzel(values, frequency);
        if power > best.0 {
            best = (power, frequency);
        }
    }
    best.1
}

#[test]
fn deterministic_and_content_keyed() {
    let patch = isolated(&[]);
    let a = pluck_note(&patch, &[110.0], 1.0, 1.0);
    let b = pluck_note(&patch, &[110.0], 1.0, 1.0);
    assert_eq!(a, b, "same note renders byte-identically");
    let c = pluck_note(&patch, &[110.5], 1.0, 1.0);
    assert_ne!(
        a, c,
        "different note content gets a different contact state"
    );
}

#[test]
fn streaming_blocks_equal_offline_render() {
    let patch = params(&[
        ("synth", "pluck"),
        ("sus", "1.2"),
        ("body", "0.45"),
        ("symp", "0.2"),
        ("stiff", "0.13"),
        ("tension", "8"),
    ]);
    let expected = pluck_note(&patch, &[110.0, 164.8138], 0.7, 1.0);
    let mut voice = StringNetworkVoice::guitar(&patch, &[110.0, 164.8138], 0.7, 1.0);
    let mut actual = Vec::new();
    for block_len in [1, 31, 64, 127, 509] {
        while !voice.is_finished() && actual.len() % 1_023 < 800 {
            let mut block = vec![0.0; block_len];
            let written = voice.render_block(&mut block);
            actual.extend_from_slice(&block[..written]);
        }
    }
    while !voice.is_finished() {
        let mut block = [0.0_f32; 113];
        let written = voice.render_block(&mut block);
        actual.extend_from_slice(&block[..written]);
    }
    assert_eq!(expected, actual, "the DSP kernel is host-block invariant");
}

#[test]
fn in_tune_across_the_guitar_neck() {
    let patch = isolated(&[("sus", "3.0"), ("damp", "0.2")]);
    for target in [82.4069, 110.0, 220.0, 440.0, 880.0, 1318.51] {
        let audio = pluck_note(&patch, &[target], 1.2, 1.0);
        let estimate = estimate_f0(&audio, 0.16, 0.56, target * 0.80, target * 1.25);
        let cents = 1200.0 * (estimate / target).log2().abs();
        assert!(
            cents < 8.0,
            "{target} Hz estimated {estimate:.3} Hz: {cents:.2} cents"
        );
    }
}

#[test]
fn sus_remains_an_honest_fundamental_t60() {
    let patch = isolated(&[("sus", "0.8"), ("damp", "0")]);
    let audio = pluck_note(&patch, &[196.0], 1.6, 1.0);
    let early = rms(&audio[(0.06 * SR_F64) as usize..(0.16 * SR_F64) as usize]);
    let at_t60 = rms(&audio[(0.78 * SR_F64) as usize..(0.88 * SR_F64) as usize]);
    let decibels = 20.0 * (at_t60 / early).log10();
    assert!(
        (-76.0..=-40.0).contains(&decibels),
        "T60=0.8s measured {decibels:.1} dB relative to early"
    );
}

#[test]
fn midpoint_pluck_suppresses_the_second_harmonic() {
    let f0 = 220.0;
    let near_bridge = pluck_note(
        &isolated(&[("pos", "0.07"), ("pick", "0")]),
        &[f0],
        1.0,
        1.0,
    );
    let midpoint = pluck_note(&isolated(&[("pos", "0.5"), ("pick", "0")]), &[f0], 1.0, 1.0);
    let start = (0.04 * SR_F64) as usize;
    let end = (0.55 * SR_F64) as usize;
    let ratio_bridge = goertzel(&near_bridge[start..end], 2.0 * f0)
        / goertzel(&near_bridge[start..end], f0).max(1e-12);
    let ratio_midpoint =
        goertzel(&midpoint[start..end], 2.0 * f0) / goertzel(&midpoint[start..end], f0).max(1e-12);
    assert!(
        ratio_midpoint < ratio_bridge * 0.12,
        "2nd/1st power: midpoint {ratio_midpoint:.5}, bridge {ratio_bridge:.5}"
    );
}

#[test]
fn stiff_string_spreads_upper_partials_without_detuning_the_fundamental() {
    let plain = pluck_note(
        &isolated(&[("sus", "3"), ("damp", "0.12"), ("stiff", "0")]),
        &[110.0],
        1.4,
        1.0,
    );
    let stiff = pluck_note(
        &isolated(&[("sus", "3"), ("damp", "0.12"), ("stiff", "0.75")]),
        &[110.0],
        1.4,
        1.0,
    );
    let start = (0.12 * SR_F64) as usize;
    let end = (0.95 * SR_F64) as usize;
    let plain_window = &plain[start..end];
    let stiff_window = &stiff[start..end];
    let plain_1 = spectral_peak(plain_window, 110.0, 0.02);
    let plain_5 = spectral_peak(plain_window, 550.0, 0.025);
    let stiff_1 = spectral_peak(stiff_window, 110.0, 0.02);
    let stiff_5 = spectral_peak(stiff_window, 550.0, 0.04);
    let plain_ratio = plain_5 / (5.0 * plain_1);
    let stiff_ratio = stiff_5 / (5.0 * stiff_1);
    assert!(
        stiff_ratio > plain_ratio + 0.00035,
        "upper-partial ratio plain={plain_ratio:.6}, stiff={stiff_ratio:.6}"
    );
    let fundamental_cents = 1200.0 * (stiff_1 / 110.0).log2().abs();
    assert!(
        fundamental_cents < 10.0,
        "fundamental moved {fundamental_cents:.2} cents"
    );
}

#[test]
fn nonlinear_tension_glide_relaxes_toward_nominal_pitch() {
    let patch = isolated(&[("sus", "3.0"), ("damp", "0.18"), ("tension", "32")]);
    let audio = pluck_note(&patch, &[110.0], 1.5, 1.0);
    let early = estimate_f0(&audio, 0.035, 0.19, 105.0, 116.0);
    let late = estimate_f0(&audio, 0.85, 1.25, 105.0, 116.0);
    let glide_cents = 1200.0 * (early / late).log2();
    let late_error = 1200.0 * (late / 110.0).log2().abs();
    assert!(
        glide_cents > 5.0,
        "early={early:.3}, late={late:.3}, glide={glide_cents:.2}c"
    );
    assert!(
        late_error < 9.0,
        "late pitch remains {late_error:.2} cents from nominal"
    );
}

#[test]
fn body_is_feedback_coupling_not_a_post_eq_alias() {
    let dry = pluck_note(
        &isolated(&[("body", "0"), ("sus", "2.5"), ("pos", "0.19")]),
        &[137.0],
        1.0,
        1.0,
    );
    let coupled = pluck_note(
        &isolated(&[
            ("body", "0.9"),
            ("body_size", "1.0"),
            ("sus", "2.5"),
            ("pos", "0.19"),
        ]),
        &[137.0],
        1.0,
        1.0,
    );
    assert_ne!(dry, coupled);
    let start = (0.04 * SR_F64) as usize;
    let end = (0.55 * SR_F64) as usize;
    let dry_body_mode = goertzel(&dry[start..end], 186.0);
    let coupled_body_mode = goertzel(&coupled[start..end], 186.0);
    assert!(
        coupled_body_mode > dry_body_mode * 1.15,
        "186 Hz body mode dry={dry_body_mode:.3e}, coupled={coupled_body_mode:.3e}"
    );
}

#[test]
fn bends_retime_the_waveguide_and_land_on_the_target() {
    let patch = isolated(&[("sus", "4"), ("damp", "0.18")]);
    let audio = pluck_note(&patch, &[220.0], 1.3, 1.5);
    let estimate = estimate_f0(&audio, 1.42, 1.82, 260.0, 380.0);
    let cents = 1200.0 * (estimate / 330.0).log2().abs();
    assert!(
        cents < 45.0,
        "tail={estimate:.2} Hz, target=330 Hz, error={cents:.1}c"
    );
}

#[test]
fn weave_is_path_sensitive_but_deterministic() {
    let clockwise_patch = params(&[
        ("synth", "weave"),
        ("sus", "2.2"),
        ("courses", "9"),
        ("couple", "0.16"),
        ("chirality", "0.9"),
        ("orbit", "0.47"),
        ("orbit_depth", "0.7"),
        ("curvature", "0.55"),
        ("body", "0.55"),
    ]);
    let counter_patch = {
        let mut patch = clockwise_patch.clone();
        patch.insert("chirality".to_string(), "-0.9".to_string());
        patch
    };
    let a = weave_note(&clockwise_patch, &[110.0, 165.0], 1.1, 1.0);
    let b = weave_note(&clockwise_patch, &[110.0, 165.0], 1.1, 1.0);
    let reversed = weave_note(&counter_patch, &[110.0, 165.0], 1.1, 1.0);
    assert_eq!(a, b);
    assert_ne!(
        a, reversed,
        "reversing the ordered coupling path changes the state"
    );
    let difference = a
        .iter()
        .zip(reversed.iter())
        .map(|(&left, &right)| (left as f64 - right as f64).powi(2))
        .sum::<f64>()
        .sqrt();
    assert!(difference > 0.05, "path difference norm={difference}");
}

#[test]
fn bounded_and_finite_over_extreme_controls() {
    let cases = [
        params(&[
            ("synth", "pluck"),
            ("sus", "0.05"),
            ("damp", "0"),
            ("pos", "0.02"),
            ("pick", "1"),
            ("stiff", "1"),
            ("tension", "80"),
            ("buzz", "1"),
            ("body", "1"),
            ("symp", "1"),
            ("detune", "60"),
        ]),
        params(&[
            ("synth", "weave"),
            ("sus", "5"),
            ("damp", "0.9"),
            ("courses", "24"),
            ("couple", "0.45"),
            ("chirality", "1"),
            ("orbit", "20"),
            ("orbit_depth", "1"),
            ("curvature", "1"),
            ("body", "1"),
        ]),
    ];
    for patch in &cases {
        let audio = if patch.get("synth").map(String::as_str) == Some("weave") {
            weave_note(patch, &[82.4069, 110.0, 146.832], 0.45, 1.0)
        } else {
            pluck_note(patch, &[82.4069, 110.0, 146.832], 0.45, 1.0)
        };
        assert!(audio.iter().all(|sample| sample.is_finite()));
        let peak = audio
            .iter()
            .fold(0.0_f32, |maximum, sample| maximum.max(sample.abs()));
        assert!(peak <= 4.0, "network peak {peak} is bounded");
        let bent = if patch.get("synth").map(String::as_str) == Some("weave") {
            weave_note(patch, &[82.4069, 110.0, 146.832], 0.45, 1.5)
        } else {
            pluck_note(patch, &[82.4069, 110.0, 146.832], 0.45, 1.5)
        };
        assert!(bent.iter().all(|sample| sample.is_finite()));
        let bent_peak = bent
            .iter()
            .fold(0.0_f32, |maximum, sample| maximum.max(sample.abs()));
        // Delay-line retuning during a bend performs work on the state —
        // the predicted gap in the rotation proof, measured: this exact
        // weave patch peaks 3.24 unbent and 5.38 during an upward-fifth
        // bend (a bounded ~0.3 s transient that then decays to silence;
        // the fretting hand doing work on a shortening string is real
        // physics). Bound is measurement + headroom, not a passivity
        // claim; energy-compensated retuning is the P0 follow-up.
        assert!(bent_peak <= 8.0, "bent network peak {bent_peak} is bounded");
    }
}

#[test]
fn zero_limit_laws_decouple_the_network() {
    // couple=0 with body=0: every scattering-path control is inert — the
    // decoupled network is nothing but independent courses.
    let base = params(&[
        ("synth", "weave"),
        ("body", "0"),
        ("couple", "0"),
        ("courses", "9"),
        ("sus", "1.0"),
    ]);
    let reference = weave_note(&base, &[110.0, 165.0], 0.5, 1.0);
    for (key, value) in [
        ("chirality", "-0.9"),
        ("orbit", "7.0"),
        ("orbit_depth", "0.9"),
        ("curvature", "0.9"),
        ("dimension", "2.4"),
    ] {
        let mut patch = base.clone();
        patch.insert(key.to_string(), value.to_string());
        let altered = weave_note(&patch, &[110.0, 165.0], 0.5, 1.0);
        assert_eq!(
            reference, altered,
            "{key} must be inert when couple=0 and body=0"
        );
    }

    // orbit_depth=0: the travelling field's rate is inert even while the
    // network is coupled and the body is live.
    let still = params(&[
        ("synth", "weave"),
        ("body", "0.4"),
        ("couple", "0.2"),
        ("orbit_depth", "0"),
        ("orbit", "0.1"),
        ("courses", "9"),
        ("sus", "1.0"),
    ]);
    let mut spinning = still.clone();
    spinning.insert("orbit".to_string(), "19.0".to_string());
    assert_eq!(
        weave_note(&still, &[110.0, 165.0], 0.5, 1.0),
        weave_note(&spinning, &[110.0, 165.0], 0.5, 1.0),
        "orbit must be inert when orbit_depth=0"
    );
}
