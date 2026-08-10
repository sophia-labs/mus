//! Invariant tests for the pluck — the post-parity discipline: no golden
//! vectors exist (there is no oracle for original work), so the tests
//! assert the PROMISES the module's docs make: bit determinism,
//! content-keyed variation, honest tuning across the neck, honest T60,
//! the pick-position comb physically suppressing its harmonics, physical
//! bends, and boundedness.

use std::collections::BTreeMap;

use mus_dsp::pluck::pluck_note;
use mus_dsp::SR_F64;

fn params(pairs: &[(&str, &str)]) -> BTreeMap<String, String> {
    pairs
        .iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect()
}

/// Fundamental via autocorrelation over a window well past the attack.
fn estimate_f0(x: &[f32], lo_hz: f64, hi_hz: f64) -> f64 {
    let start = (0.15 * SR_F64) as usize;
    let window = &x[start..(start + (0.4 * SR_F64) as usize).min(x.len())];
    let min_lag = (SR_F64 / hi_hz) as usize;
    let max_lag = (SR_F64 / lo_hz) as usize;
    let mut best = (0.0f64, min_lag);
    for lag in min_lag..=max_lag.min(window.len() / 2) {
        let mut acc = 0.0f64;
        for i in 0..window.len() - lag {
            acc += window[i] as f64 * window[i + lag] as f64;
        }
        if acc > best.0 {
            best = (acc, lag);
        }
    }
    // parabolic refinement around the winning lag
    let lag = best.1;
    let corr = |l: usize| -> f64 {
        let mut acc = 0.0;
        for i in 0..window.len() - l {
            acc += window[i] as f64 * window[i + l] as f64;
        }
        acc
    };
    let (a, b, c) = (corr(lag - 1), corr(lag), corr(lag + 1));
    let denom = a - 2.0 * b + c;
    let shift = if denom.abs() > 1e-12 {
        0.5 * (a - c) / denom
    } else {
        0.0
    };
    SR_F64 / (lag as f64 + shift)
}

/// Goertzel power at one frequency.
fn goertzel(x: &[f32], f: f64) -> f64 {
    let w = 2.0 * std::f64::consts::PI * f / SR_F64;
    let coeff = 2.0 * w.cos();
    let (mut s1, mut s2) = (0.0f64, 0.0f64);
    for &v in x {
        let s0 = v as f64 + coeff * s1 - s2;
        s2 = s1;
        s1 = s0;
    }
    s1 * s1 + s2 * s2 - coeff * s1 * s2
}

fn rms(x: &[f32]) -> f64 {
    (x.iter().map(|&v| (v as f64) * (v as f64)).sum::<f64>() / x.len().max(1) as f64).sqrt()
}

#[test]
fn deterministic_and_content_keyed() {
    let p = params(&[("synth", "pluck")]);
    let a = pluck_note(&p, &[110.0], 1.0, 1.0);
    let b = pluck_note(&p, &[110.0], 1.0, 1.0);
    assert_eq!(a, b, "same note renders byte-identically");
    let c = pluck_note(&p, &[110.5], 1.0, 1.0);
    assert_ne!(a, c, "a different note gets a different burst");
}

#[test]
fn in_tune_across_the_neck() {
    let p = params(&[("synth", "pluck"), ("sus", "3.0")]);
    for f0 in [82.41, 110.0, 220.0, 440.0, 880.0] {
        let x = pluck_note(&p, &[f0], 1.2, 1.0);
        let est = estimate_f0(&x, f0 * 0.8, f0 * 1.25);
        let cents = 1200.0 * (est / f0).log2().abs();
        assert!(
            cents < 6.0,
            "{f0} Hz estimated {est:.2} Hz — {cents:.1} cents off (allpass tuning should hold within a few cents)"
        );
    }
}

#[test]
fn sus_is_honest_seconds() {
    let p = params(&[("synth", "pluck"), ("sus", "0.8"), ("body", "0")]);
    let x = pluck_note(&p, &[196.0], 2.0, 1.0);
    let early = rms(&x[(0.05 * SR_F64) as usize..(0.15 * SR_F64) as usize]);
    let at_t60 = rms(&x[(0.78 * SR_F64) as usize..(0.88 * SR_F64) as usize]);
    let db = 20.0 * (at_t60 / early).log10();
    assert!(
        (-72.0..=-42.0).contains(&db),
        "T60=0.8s: level at 0.8s is {db:.1} dB relative to early (want roughly -60, tolerant band)"
    );
}

#[test]
fn pick_position_comb_suppresses_its_harmonic() {
    // pos=0.5 puts the pick at the string's midpoint: the 2nd harmonic has
    // a node there and must be strongly suppressed relative to picking
    // near the bridge.
    let f0 = 220.0;
    let near_bridge = pluck_note(
        &params(&[("synth", "pluck"), ("pos", "0.08")]),
        &[f0],
        1.0,
        1.0,
    );
    let mid_string = pluck_note(
        &params(&[("synth", "pluck"), ("pos", "0.5")]),
        &[f0],
        1.0,
        1.0,
    );
    let win = |x: &[f32]| x[(0.05 * SR_F64) as usize..(0.6 * SR_F64) as usize].to_vec();
    let ratio_bridge =
        goertzel(&win(&near_bridge), 2.0 * f0) / goertzel(&win(&near_bridge), f0).max(1e-12);
    let ratio_mid =
        goertzel(&win(&mid_string), 2.0 * f0) / goertzel(&win(&mid_string), f0).max(1e-12);
    assert!(
        ratio_mid < ratio_bridge * 0.2,
        "2nd/1st harmonic power: mid-string {ratio_mid:.4} should be well under bridge {ratio_bridge:.4}"
    );
}

#[test]
fn bends_are_physical() {
    let p = params(&[("synth", "pluck"), ("sus", "4.0")]);
    let x = pluck_note(&p, &[220.0], 1.5, 1.5);
    // Measure AFTER the slot boundary: the ramp completes at 1.5s and the
    // tail rings at the target.
    let tail_start = (1.6 * SR_F64) as usize;
    let tail = &x[tail_start..(2.0 * SR_F64) as usize];
    let est = estimate_f0(tail, 240.0, 400.0);
    let target = 330.0;
    let cents = 1200.0 * (est / target).log2().abs();
    assert!(
        cents < 40.0,
        "gliss to 1.5x: tail estimated {est:.1} Hz vs target {target} Hz ({cents:.0} cents)"
    );
}

#[test]
fn bounded_and_finite_everywhere() {
    for (sus, damp, pos, pick) in [
        ("0.05", "0.0", "0.02", "1.0"),
        ("20.0", "0.95", "0.5", "0.0"),
        ("2.5", "0.35", "0.13", "0.6"),
    ] {
        let p = params(&[
            ("synth", "pluck"),
            ("sus", sus),
            ("damp", damp),
            ("pos", pos),
            ("pick", pick),
            ("strum", "-40"),
            ("detune", "12"),
        ]);
        let x = pluck_note(&p, &[82.41, 110.0, 146.83, 196.0, 246.94, 329.63], 1.0, 1.0);
        assert!(
            x.iter().all(|v| v.is_finite()),
            "no NaN/inf at {sus}/{damp}/{pos}/{pick}"
        );
        let peak = x.iter().fold(0.0f32, |m, &v| m.max(v.abs()));
        assert!(
            peak <= 2.0,
            "peak {peak} stays bounded (doctrine: non-finite output is silent failure)"
        );
    }
}
