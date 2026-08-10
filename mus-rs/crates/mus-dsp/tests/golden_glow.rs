//! Golden tests for stage WF6 (`mus_dsp::glow`): the glow chain and the
//! two event-level render-path treatments. Same pattern as
//! `golden_kernels.rs` for the two fixture cases — resolve by manifest
//! name, run the port, `check` against the oracle's tolerance, no
//! hand-written expectations or tolerance literals — plus structural unit
//! tests for `haas`/`event_envelope` (no fixtures: both are plain
//! numpy slicing/arithmetic with no scipy/librosa call inside) and a
//! parse test for `gharm_intervals`.

use std::collections::BTreeMap;

use mus_dsp::fixtures::case;
use mus_dsp::glow::{event_envelope, gharm_intervals, glow_chain, haas};

/// `glow_chain`'s `params` argument is a nested JSON object in the
/// manifest, mixing JSON strings (`"ghold": "1"`) and JSON numbers
/// (`"gwarble": 6.0`) — the fixture generator passed the oracle whatever
/// was convenient in Python, not a uniformly-stringified map. `glow_chain`
/// itself takes `&BTreeMap<String, String>` (WF8 always feeds it real
/// parsed-token strings), so every value here is stringified on the way
/// in; which exact digit string a JSON number becomes doesn't matter since
/// every numeric param is re-parsed with `str::parse::<f64>` downstream,
/// and any string that round-trips to the same `f64` is equivalent.
fn params_map(args: &serde_json::Value, key: &str) -> BTreeMap<String, String> {
    args[key]
        .as_object()
        .unwrap_or_else(|| panic!("arg {key:?} missing/not an object"))
        .iter()
        .map(|(k, v)| {
            let s = match v {
                serde_json::Value::String(s) => s.clone(),
                other => other.to_string(),
            };
            (k.clone(), s)
        })
        .collect()
}

// -------------------------------------------------------------- glow_chain

#[test]
fn glow_full_chain() {
    let c = case("glow_full_chain");
    let st_g = c.arg_f64("st_g");
    let slot_samples = c.arg_f64("slot_samples") as usize;
    let params = params_map(&c.meta.args, "params");
    c.check(&glow_chain(&c.input_f32(), st_g, &params, slot_samples));
}

#[test]
fn glow_hold_pump() {
    let c = case("glow_hold_pump");
    let st_g = c.arg_f64("st_g");
    let slot_samples = c.arg_f64("slot_samples") as usize;
    let params = params_map(&c.meta.args, "params");
    c.check(&glow_chain(&c.input_f32(), st_g, &params, slot_samples));
}

// ------------------------------------------------------------------- haas

#[test]
fn haas_shifts_impulse_position() {
    // ms=0.5 -> d = int(0.5 * 48000 / 1000) = 24 samples.
    let n = 100;
    let d = 24usize;
    let mut r = vec![0.0f32; n];
    r[10] = 1.0;
    haas(&mut r, 0.5);
    assert_eq!(r.len(), n, "haas must not change buffer length");
    for (i, &v) in r.iter().enumerate() {
        if i == 10 + d {
            assert_eq!(v, 1.0, "the impulse must land at original_pos + d");
        } else {
            assert_eq!(v, 0.0, "no energy anywhere else (index {i})");
        }
    }
}

#[test]
fn haas_zero_ms_is_noop() {
    let mut r: Vec<f32> = (0..50).map(|i| i as f32 * 0.1).collect();
    let original = r.clone();
    haas(&mut r, 0.0);
    assert_eq!(r, original, "ms=0.0 -> d=0, which must be a no-op");
}

#[test]
fn haas_delay_equal_to_len_is_noop() {
    // ms=1.0 -> d = int(1.0 * 48000 / 1000) = 48, exactly the buffer length:
    // the guard is strict (`0 < d < len`), so d == len must still no-op.
    let n = 48usize;
    let mut r: Vec<f32> = (0..n).map(|i| i as f32 + 1.0).collect();
    let original = r.clone();
    haas(&mut r, 1.0);
    assert_eq!(r, original, "d == len must be a no-op (strict d < len)");
}

#[test]
fn haas_delay_past_len_is_noop() {
    let mut r: Vec<f32> = (0..50).map(|i| i as f32).collect();
    let original = r.clone();
    haas(&mut r, 5_000.0); // d = 240_000, far past len
    assert_eq!(r, original, "d >= len must be a no-op");
}

// ---------------------------------------------------------- event_envelope

#[test]
fn event_envelope_ramps_are_monotone_and_bound_the_sustain_region() {
    // atk_s=0.01 -> 480 samples; rel_s=0.02 -> 960 samples; both well
    // under this buffer's n/3=1600 / n/2=2400 clamps.
    let n = 4800;
    let mut x = vec![1.0f32; n];
    event_envelope(&mut x, 0.01, 0.02);
    assert_eq!(x.len(), n, "event_envelope must not change buffer length");

    for i in 1..480 {
        assert!(
            x[i] >= x[i - 1],
            "attack ramp must be non-decreasing at sample {i} ({} < {})",
            x[i],
            x[i - 1]
        );
    }
    for i in (n - 960 + 1)..n {
        assert!(
            x[i] <= x[i - 1],
            "release ramp must be non-increasing at sample {i} ({} > {})",
            x[i],
            x[i - 1]
        );
    }
    assert_eq!(x[0], 0.0, "attack ramp starts at exactly zero");
    assert_eq!(x[480], 1.0, "first post-attack sample is untouched sustain");
    assert_eq!(
        x[n - 960 - 1],
        1.0,
        "last pre-release sample is untouched sustain"
    );
    assert_eq!(x[n - 1], 0.0, "release ramp fades to exactly zero");
}

#[test]
fn event_envelope_small_buffer_clamps_atk_and_rel_independently() {
    // n=9: n/3=3, n/2=4 — both clamps bite against a 1.0s (huge) request.
    let n = 9;
    let mut x = vec![1.0f32; n];
    event_envelope(&mut x, 1.0, 1.0);

    // attack: 3 samples, indices [0,3) — linspace(0,1,3)**0.7 = [0, .5**0.7, 1].
    assert_eq!(x[0], 0.0, "attack ramp's first sample is exactly zero");
    assert!(
        x[1] > 0.0 && x[1] < 1.0,
        "attack ramp's midpoint is partially attenuated, got {}",
        x[1]
    );
    assert_eq!(
        x[2], 1.0,
        "attack ramp reaches exactly full amplitude at its last (clamped) sample"
    );

    // sustain: indices [3,5) untouched by either clamped ramp.
    assert_eq!(x[3], 1.0, "index 3 sits outside both clamped windows");
    assert_eq!(x[4], 1.0, "index 4 sits outside both clamped windows");

    // release: 4 samples, indices [5,9) — linspace(1,0,4)**1.5.
    assert_eq!(
        x[5], 1.0,
        "release ramp's first (clamped) sample is exactly full amplitude"
    );
    assert!(
        x[6] > x[7],
        "release ramp must strictly fall across its middle"
    );
    assert_eq!(x[8], 0.0, "release ramp's last sample is exactly zero");
}

#[test]
fn event_envelope_tiny_buffer_skips_both_ramps() {
    // n=2: n/3=0, n/2=1 — both clamp to a count that fails the `> 1` gate,
    // so neither ramp applies at all, however large atk_s/rel_s request.
    let mut x = vec![3.0f32, 5.0f32];
    let original = x.clone();
    event_envelope(&mut x, 1.0, 1.0);
    assert_eq!(
        x, original,
        "atk/rel clamp to <=1 sample on a 2-sample buffer, so neither ramp fires"
    );
}

// --------------------------------------------------------- gharm_intervals

#[test]
fn gharm_parses_plus_separated_list() {
    assert_eq!(gharm_intervals("0+4+7+12"), vec![0.0, 4.0, 7.0, 12.0]);
}

#[test]
fn gharm_pipe_folds_into_plus() {
    assert_eq!(gharm_intervals("0|12"), vec![0.0, 12.0]);
}

#[test]
fn gharm_garbage_falls_back_to_root_only() {
    assert_eq!(gharm_intervals("garbage"), vec![0.0]);
}

#[test]
fn gharm_default_string_is_root_only() {
    assert_eq!(gharm_intervals("0"), vec![0.0]);
}

#[test]
fn gharm_partial_failure_discards_the_whole_list() {
    // Python wraps the whole comprehension in one try/except: a single bad
    // token means the entire result is the [0.0] fallback, not the good
    // tokens with the bad one dropped.
    assert_eq!(gharm_intervals("0+abc+7"), vec![0.0]);
}

#[test]
fn gharm_whitespace_only_token_is_not_a_valid_float() {
    assert_eq!(gharm_intervals("0+ +4"), vec![0.0]);
}

#[test]
fn gharm_trims_surrounding_whitespace_on_otherwise_valid_tokens() {
    assert_eq!(gharm_intervals(" 0 + 4 "), vec![0.0, 4.0]);
}

#[test]
fn gharm_empty_string_is_an_empty_list_not_the_fallback() {
    // "".split("+") -> [""], filtered by the falsy check to nothing: no
    // ValueError is ever raised, so this is *not* the [0.0] fallback path.
    assert_eq!(gharm_intervals(""), Vec::<f64>::new());
}
