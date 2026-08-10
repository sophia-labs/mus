//! Golden tests for the keystone exemplar kernels. This file is the
//! pattern every stage's tests follow: resolve the case by manifest name,
//! run the port on the case input and args, `check` the result. No
//! hand-written expectations, no tolerance literals in test code.

use mus_dsp::fixtures::case;
use mus_dsp::kernels::{hard_clip, ring_mod, soft_clip};

#[test]
fn ring_mod_sine() {
    let c = case("ring_mod_sine");
    c.check(&ring_mod(
        &c.input_f32(),
        c.arg_f32("f_hz"),
        c.arg_f32("wet"),
    ));
}

#[test]
fn ring_mod_burst_wet() {
    let c = case("ring_mod_burst_wet");
    c.check(&ring_mod(
        &c.input_f32(),
        c.arg_f32("f_hz"),
        c.arg_f32("wet"),
    ));
}

#[test]
fn soft_clip_drive() {
    let c = case("soft_clip_drive");
    c.check(&soft_clip(&c.input_f32(), c.arg_f32("drive")));
}

#[test]
fn hard_clip_noise() {
    let c = case("hard_clip_noise");
    c.check(&hard_clip(&c.input_f32(), c.arg_f32("amount")));
}
