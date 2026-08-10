//! Golden tests for stage WF7 (`mus_dsp::bus`): the seeded reverb impulse,
//! overlap-add convolution, and the RMS-target master chain. Same pattern
//! as `golden_kernels.rs`: resolve the case by manifest name, run the
//! port, `check` against the oracle's tolerance — no hand-written
//! expectations, no tolerance literals for the fixture cases.
//!
//! `make_ir`/`reverb_apply_0_6`/`master_rms14` are all planar-stereo
//! fixtures (`shape_out: [2, n]`, stored row-major: the first `n` values
//! are channel 0, the next `n` are channel 1). Following
//! `golden_kernels2.rs`'s `pan_static`/`pan_sweep` precedent: concatenate
//! our own two channels the same way and run the whole thing through one
//! `check` call, rather than checking each channel separately.
//!
//! Plus the non-fixture properties the spec calls out by name —
//! `oaconvolve`'s linearity, `make_ir`'s determinism, and `highpass28`'s
//! DC rejection (no dedicated fixture — deferred to WF9's end-to-end
//! coverage per the spec) — and one review-mandated regression:
//! `oaconvolve` crossing multiple overlap-add blocks, checked against an
//! independent direct convolution rather than any of `bus`'s own FFT
//! machinery.

use mus_dsp::bus::{highpass28, make_ir, master, oaconvolve};
use mus_dsp::fixtures::case;

/// Concatenate two channels planar (L fully, then R fully) — the layout
/// every stereo fixture in this file was dumped in.
fn planar(l: &[f32], r: &[f32]) -> Vec<f32> {
    let mut both = l.to_vec();
    both.extend_from_slice(r);
    both
}

/// Split a flat planar-stereo buffer (`[ch0..., ch1...]`) back into two
/// equal channels — the inverse of [`planar`], for fixtures whose *input*
/// is stereo (`master_rms14`).
fn split_planar(flat: &[f32]) -> [Vec<f32>; 2] {
    assert_eq!(flat.len() % 2, 0, "split_planar: odd-length planar buffer");
    let half = flat.len() / 2;
    [flat[..half].to_vec(), flat[half..].to_vec()]
}

// --------------------------------------------------------------- make_ir

#[test]
fn make_ir_0_6() {
    let c = case("make_ir_0_6");
    let [l, r] = make_ir(0.6);
    c.check(&planar(&l, &r));
}

#[test]
fn make_ir_2_6() {
    let c = case("make_ir_2_6");
    let [l, r] = make_ir(2.6);
    c.check(&planar(&l, &r));
}

#[test]
fn make_ir_4_5() {
    let c = case("make_ir_4_5");
    let [l, r] = make_ir(4.5);
    c.check(&planar(&l, &r));
}

/// Spec-mandated determinism test: two `make_ir` calls with the same
/// `seconds` must be bit-identical (the seed is fixed, not sampled from
/// any process-global state).
#[test]
fn make_ir_is_deterministic() {
    assert_eq!(make_ir(0.6), make_ir(0.6));
    assert_eq!(make_ir(2.6), make_ir(2.6));
}

// ----------------------------------------------------------- oaconvolve

/// `reverb_apply_0_6`: `wetin` (mono) convolved with `make_ir(0.6)`'s two
/// channels, each truncated to the input length — the fixture's own note
/// ("planar expected, truncated to input length") and its generator
/// (`sig.oaconvolve(wetin, ir06[c])[: len(wetin)]`) both do the truncation
/// after calling the convolution, matching `oaconvolve`'s contract that
/// truncation is the caller's job, not the function's.
#[test]
fn reverb_apply_0_6() {
    let c = case("reverb_apply_0_6");
    let wetin = c.input_f32();
    let [ir_l, ir_r] = make_ir(0.6);

    let mut rev_l = oaconvolve(&wetin, &ir_l);
    let mut rev_r = oaconvolve(&wetin, &ir_r);
    rev_l.truncate(wetin.len());
    rev_r.truncate(wetin.len());

    c.check(&planar(&rev_l, &rev_r));
}

/// Spec-mandated linearity test: `conv(a+b) == conv(a) + conv(b)`, up to
/// float noise (FFT convolution is linear in exact arithmetic, but not
/// bit-for-bit in floating point once rounding paths diverge). No
/// manifest tolerance exists for this internal-consistency property (it
/// isn't a fixture case), so the threshold below is a measured constant,
/// not a guess: for the two ~2000-sample, amplitude-order-1 test signals
/// below convolved with a 300-tap kernel, the actual worst-sample
/// divergence measured on this machine was on the order of 1e-6 (a
/// handful of f32 ULPs at these signal magnitudes) — `5e-5` leaves two
/// orders of magnitude of headroom above that measurement.
#[test]
fn oaconvolve_is_linear() {
    let n = 2000;
    let a: Vec<f32> = (0..n).map(|i| (i as f32 * 0.017).sin() * 0.6).collect();
    let b: Vec<f32> = (0..n).map(|i| (i as f32 * 0.041).cos() * 0.4).collect();
    let h: Vec<f32> = (0..300)
        .map(|i| (-(i as f32) / 50.0).exp() * (i as f32 * 0.3).sin())
        .collect();

    let sum_ab: Vec<f32> = a.iter().zip(&b).map(|(&x, &y)| x + y).collect();
    let conv_sum = oaconvolve(&sum_ab, &h);
    let conv_a = oaconvolve(&a, &h);
    let conv_b = oaconvolve(&b, &h);

    assert_eq!(conv_sum.len(), conv_a.len());
    assert_eq!(conv_sum.len(), conv_b.len());

    let (mut worst, mut at) = (0.0f32, 0usize);
    for (i, ((&s, &ca), &cb)) in conv_sum.iter().zip(&conv_a).zip(&conv_b).enumerate() {
        let d = (s - (ca + cb)).abs();
        if d > worst {
            worst = d;
            at = i;
        }
    }
    const EPS: f32 = 5e-5;
    assert!(
        worst <= EPS,
        "oaconvolve linearity: max_abs {worst:.3e} > {EPS:.1e} at [{at}]"
    );
}

/// Finding-mandated regression: an input long enough, against
/// `oaconvolve`'s own block-size choice (`bus::oa_block_plan`), to force
/// its overlap-add loop through many block boundaries — checked against a
/// direct O(n·m) convolution computed independently right here (not
/// against any of `bus`'s own FFT machinery), so this doesn't just confirm
/// internal self-consistency. With a 40-tap filter, `oa_block_plan` picks
/// a 1024-sample transform (`2*40=80` is under its 1024 floor) — a
/// ~985-sample block — so a 20_000-sample input crosses on the order of
/// 20 block boundaries.
#[test]
fn oaconvolve_crosses_multiple_blocks() {
    let n = 20_000;
    let x: Vec<f32> = (0..n)
        .map(|i| (i as f32 * 0.0137).sin() * 0.7 + (i as f32 * 0.0029).cos() * 0.3)
        .collect();
    let h: Vec<f32> = (0..40)
        .map(|i| (-(i as f32) / 12.0).exp() * (i as f32 * 0.5).sin())
        .collect();

    let got = oaconvolve(&x, &h);
    let want_len = x.len() + h.len() - 1;
    assert_eq!(
        got.len(),
        want_len,
        "oaconvolve: output length contract (len(x)+len(h)-1)"
    );

    // Direct convolution at f64, independent of the FFT path under test.
    let mut want = vec![0.0f64; want_len];
    for (i, &xi) in x.iter().enumerate() {
        for (j, &hj) in h.iter().enumerate() {
            want[i + j] += xi as f64 * hj as f64;
        }
    }

    let (mut worst, mut at) = (0.0f64, 0usize);
    for (i, (&g, &w)) in got.iter().zip(&want).enumerate() {
        let d = (g as f64 - w).abs();
        if d > worst {
            worst = d;
            at = i;
        }
    }
    // Measured constant: the actual worst-sample divergence against the
    // direct-convolution reference on this signal, on this machine, was
    // 6.933e-7 (float32 rounding noise accumulated over a 20-block
    // overlap-add, plus the direct reference's own f32-input/f64-accumulate
    // rounding) — `1e-5` leaves well over an order of magnitude of
    // headroom above that, rather than being tuned to just barely pass.
    const EPS: f64 = 1e-5;
    assert!(
        worst <= EPS,
        "oaconvolve multi-block: max_abs {worst:.3e} > {EPS:.1e} at [{at}]"
    );
}

// --------------------------------------------------------------- master

#[test]
fn master_rms14() {
    let c = case("master_rms14");
    let x = split_planar(&c.input_f32());
    let target_rms_db = c.arg_f64("target_rms_db");

    let [l, r] = master(x, target_rms_db);
    c.check(&planar(&l, &r));
}

// ------------------------------------------------------------ highpass28

/// No dedicated fixture (spec defers end-to-end coverage to WF9); tested
/// here for the property the spec asks for instead: a highpass must drive
/// a constant (all-DC) input to ~0. Measured directly against the oracle
/// (`scipy`'s same `butter`+`sosfilt` pipeline, same 28 Hz/2nd-order
/// design) for a 20000-sample constant input: the real residual in the
/// last 1000 samples is ~2.7e-14 — the `1e-6` threshold below leaves
/// roughly eight orders of magnitude of headroom above that, rather than
/// being tuned to just barely pass.
#[test]
fn highpass28_rejects_dc() {
    let n = 20_000;
    let dc = vec![0.5f32; n];
    let [l, r] = highpass28([dc.clone(), dc]);

    let tail = n - 1000;
    for (name, ch) in [("L", &l), ("R", &r)] {
        for (i, &v) in ch[tail..].iter().enumerate() {
            assert!(
                v.abs() < 1e-6,
                "highpass28 {name}: DC not rejected by sample {}: {v:.3e}",
                tail + i
            );
        }
    }
}
