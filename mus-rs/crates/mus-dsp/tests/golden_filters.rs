//! Golden tests for stage WF3 — scipy-parity IIR filters
//! (`mus-dsp/src/filters.rs`). Same pattern as `golden_kernels.rs`: resolve
//! the case by manifest name, run the port on the case input/args, `check`
//! the result. No hand-written expectations, no tolerance literals here.

use mus_dsp::filters::{butter_sos, sosfilt, sosfilt_zi, sweep_filter};
use mus_dsp::fixtures::{case, Case};
use mus_dsp::SR_F64;

const NYQ: f64 = SR_F64 / 2.0;

fn flatten6(sos: &[[f64; 6]]) -> Vec<f64> {
    sos.iter().flat_map(|row| row.iter().copied()).collect()
}

fn flatten2(zi: &[[f64; 2]]) -> Vec<f64> {
    zi.iter().flat_map(|row| row.iter().copied()).collect()
}

/// `{order, fc_hz, btype}` cases all build their sos the same way.
fn butter_sos_from_case(c: &Case) -> Vec<[f64; 6]> {
    let order = c.arg_f64("order") as usize;
    let fc = c.arg_f64("fc_hz");
    let btype = c.meta.args["btype"]
        .as_str()
        .expect("btype arg is a string");
    butter_sos(order, fc / NYQ, btype)
}

#[test]
fn sos_butter4_low_1200() {
    let c = case("sos_butter4_low_1200");
    c.check_f64(&flatten6(&butter_sos_from_case(&c)));
}

#[test]
fn sos_butter4_high_300() {
    let c = case("sos_butter4_high_300");
    c.check_f64(&flatten6(&butter_sos_from_case(&c)));
}

#[test]
fn sos_butter2_low_5200() {
    let c = case("sos_butter2_low_5200");
    c.check_f64(&flatten6(&butter_sos_from_case(&c)));
}

#[test]
fn sos_butter2_high_28() {
    let c = case("sos_butter2_high_28");
    c.check_f64(&flatten6(&butter_sos_from_case(&c)));
}

#[test]
fn sosfilt_low_noise() {
    let c = case("sosfilt_low_noise");
    let sos = butter_sos_from_case(&c);
    let (y, _zf) = sosfilt(&sos, &c.input_f32(), None);
    c.check(&y);
}

#[test]
fn sosfilt_zi_low_1200() {
    let c = case("sosfilt_zi_low_1200");
    let sos = butter_sos_from_case(&c);
    c.check_f64(&flatten2(&sosfilt_zi(&sos)));
}

#[test]
fn sweep_static_low() {
    let c = case("sweep_static_low");
    let btype = c.meta.args["btype"].as_str().unwrap();
    let y = sweep_filter(
        &c.input_f32(),
        c.arg_f64("f_start"),
        c.arg_f64("f_end"),
        btype,
        4,
        256,
    );
    c.check(&y);
}

#[test]
fn sweep_low_fall() {
    let c = case("sweep_low_fall");
    let btype = c.meta.args["btype"].as_str().unwrap();
    let y = sweep_filter(
        &c.input_f32(),
        c.arg_f64("f_start"),
        c.arg_f64("f_end"),
        btype,
        4,
        256,
    );
    c.check(&y);
}

#[test]
fn sweep_high_rise() {
    let c = case("sweep_high_rise");
    let btype = c.meta.args["btype"].as_str().unwrap();
    let y = sweep_filter(
        &c.input_f32(),
        c.arg_f64("f_start"),
        c.arg_f64("f_end"),
        btype,
        4,
        256,
    );
    c.check(&y);
}

/// Spec-required unit test: splitting a signal in two and carrying
/// `sosfilt`'s `zi` across the split must reproduce filtering it whole —
/// scipy's own carried-state contract (`sosfilt` docs: "these initial
/// conditions are not the same as... `lfiltic`", but *are* the state
/// needed to resume filtering where a previous call left off).
#[test]
fn sosfilt_carried_state_matches_whole_signal() {
    let c = case("sosfilt_low_noise");
    let x = c.input_f32();
    let sos = butter_sos(4, 1200.0 / NYQ, "low");

    let (whole, _) = sosfilt(&sos, &x, None);

    let mid = x.len() / 2;
    let (first_half, zf) = sosfilt(&sos, &x[..mid], None);
    let (second_half, _) = sosfilt(&sos, &x[mid..], Some(&zf));
    let mut split = first_half;
    split.extend(second_half);

    assert_eq!(split.len(), whole.len());
    for (i, (a, b)) in split.iter().zip(whole.iter()).enumerate() {
        assert_eq!(a, b, "sample {i}: split {a} vs whole {b}");
    }
}
