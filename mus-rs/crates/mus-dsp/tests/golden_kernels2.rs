//! Golden tests for WF2's remaining kernels — bitcrush, stutter,
//! chop_shuffle, duck_envelope, pan_stereo, maximum_filter1d — plus
//! hand-value/edge-case unit tests for the two spots the fixture set
//! doesn't reach: `np_hanning` has no fixture at all, and neither
//! `chop_shuffle` fixture divides unevenly, so the short/empty-grain
//! slicing path goes untested by the manifest. Same pattern as
//! `tests/golden_kernels.rs`: resolve the case by manifest name, run the
//! port, `check` against the oracle's recorded output — no hand-written
//! expectations, no tolerance literals.
//!
//! The two hand-derived cases (`chop_shuffle`'s uneven-length slicing edge
//! and `np_hanning`'s hand values) have no manifest entry to arbitrate
//! them, but that's not license for an arbitrary tolerance either: both
//! compare against the real oracle's output pulled from the venv as raw
//! IEEE-754 bit patterns, checked with exact (`to_bits()`) equality, not
//! an epsilon. See each test's doc comment for provenance.

use mus_dsp::fixtures::{case, Case};
use mus_dsp::kernels::{
    bitcrush, chop_shuffle, duck_envelope, maximum_filter1d, np_hanning, pan_stereo, stutter,
};

/// `bitcrush`'s `bits`/`decim` are `Option`, and the manifest represents
/// "absent" as an explicit JSON `null` rather than omitting the key — the
/// harness's `arg_f64`/`arg_f32` panic on a non-numeric value (including
/// null), so fetch these two directly and let a JSON null fall through to
/// `None` via `as_f64`.
fn opt_f64(c: &Case, key: &str) -> Option<f64> {
    c.meta.args.get(key).and_then(|v| v.as_f64())
}

#[test]
fn bitcrush_bits() {
    let c = case("bitcrush_bits");
    let bits = opt_f64(&c, "bits");
    let decim = opt_f64(&c, "decim").map(|v| v as u32);
    c.check(&bitcrush(&c.input_f32(), bits, decim));
}

#[test]
fn bitcrush_decim() {
    let c = case("bitcrush_decim");
    let bits = opt_f64(&c, "bits");
    let decim = opt_f64(&c, "decim").map(|v| v as u32);
    c.check(&bitcrush(&c.input_f32(), bits, decim));
}

#[test]
fn bitcrush_both() {
    let c = case("bitcrush_both");
    let bits = opt_f64(&c, "bits");
    let decim = opt_f64(&c, "decim").map(|v| v as u32);
    c.check(&bitcrush(&c.input_f32(), bits, decim));
}

#[test]
fn stutter_5() {
    let c = case("stutter_5");
    let n = c.arg_f64("n") as usize;
    let slot_samples = c.arg_f64("slot_samples") as usize;
    c.check(&stutter(&c.input_f32(), n, slot_samples));
}

#[test]
fn chop_shuffle_8() {
    let c = case("chop_shuffle_8");
    let n_grains = c.arg_f64("n_grains") as usize;
    let slot_samples = c.arg_f64("slot_samples") as usize;
    c.check(&chop_shuffle(&c.input_f32(), n_grains, slot_samples));
}

#[test]
fn chop_shuffle_3_tight() {
    let c = case("chop_shuffle_3_tight");
    let n_grains = c.arg_f64("n_grains") as usize;
    let slot_samples = c.arg_f64("slot_samples") as usize;
    c.check(&chop_shuffle(&c.input_f32(), n_grains, slot_samples));
}

#[test]
fn duck_envelope_case() {
    let c = case("duck_envelope");
    let onsets: Vec<f64> = c.meta.args["onsets"]
        .as_array()
        .expect("duck_envelope: onsets is an array")
        .iter()
        .map(|v| v.as_f64().expect("duck_envelope: onset is numeric"))
        .collect();
    let n = c.arg_f64("n") as usize;
    let depth = c.arg_f64("depth");
    let release = c.arg_f64("release");
    let hold = c.arg_f64("hold");
    c.check(&duck_envelope(&onsets, n, depth, release, hold));
}

/// `expected` is stored planar — the first half is L, the second is R
/// (see the fixture's `"planar LR"` note and `shape_out: [2, n]`).
/// Concatenating our `(L, R)` the same way and running it through the one
/// `check` call compares both halves index-for-index against the
/// respective half of `expected`, same as checking them separately would.
#[test]
fn pan_static() {
    let c = case("pan_static");
    let p0 = c.arg_f64("p0");
    let p1 = c.arg_f64("p1");
    let (l, r) = pan_stereo(&c.input_f32(), p0, p1);
    let mut both = l;
    both.extend(r);
    c.check(&both);
}

#[test]
fn pan_sweep() {
    let c = case("pan_sweep");
    let p0 = c.arg_f64("p0");
    let p1 = c.arg_f64("p1");
    let (l, r) = pan_stereo(&c.input_f32(), p0, p1);
    let mut both = l;
    both.extend(r);
    c.check(&both);
}

#[test]
fn maximum_filter1d_case() {
    let c = case("maximum_filter1d");
    let size = c.arg_f64("size") as usize;
    c.check(&maximum_filter1d(&c.input_f32(), size));
}

/// `chop_shuffle` when `len(x)` isn't a multiple of `n_grains`: the last
/// grain comes out genuinely short (Python slicing clips instead of
/// raising), a path neither manifest fixture exercises (both divide
/// evenly). For `x = np.arange(100, dtype=np.float32)`, `n_grains=2,
/// slot_samples=50`: `seg` clamps to 64 (`100 // 2 = 50 < 64`), so grain 0
/// is the full 64 samples and grain 1 is the trailing 36 (`100 - 64`). The
/// final truncation to `max(50, 64) = 64` then lands exactly on the
/// grain-0/grain-1 boundary, so this also happens to check that
/// truncation logic — the output is grain 0 (faded) and none of grain 1
/// survives.
///
/// `expected_bits` is `mus_audio.chop_shuffle`'s real output for that call,
/// pulled from the venv as raw IEEE-754 bit patterns (Python
/// `struct.pack("<f", v)` per element, reassembled here with
/// `f32::from_bits`) rather than printed decimal. That makes the
/// comparison below an exact assertion, not a tolerance: two f32s either
/// have the same bits or they don't, so there is no epsilon to pick and
/// no reassociation slop to leave headroom for.
#[test]
fn chop_shuffle_uneven_length_does_not_panic() {
    let x: Vec<f32> = (0..100).map(|i| i as f32).collect();
    let y = chop_shuffle(&x, 2, 50);
    #[rustfmt::skip]
    let expected_bits: [u32; 64] = [
        0x00000000, 0x3d888889, 0x3e888889, 0x3f19999a, 0x3f888889, 0x3fd55556, 0x4019999a, 0x40511111,
        0x40888889, 0x40accccd, 0x40d55556, 0x41011111, 0x4119999a, 0x41344444, 0x41511111, 0x41700000,
        0x41800000, 0x41880000, 0x41900000, 0x41980000, 0x41a00000, 0x41a80000, 0x41b00000, 0x41b80000,
        0x41c00000, 0x41c80000, 0x41d00000, 0x41d80000, 0x41e00000, 0x41e80000, 0x41f00000, 0x41f80000,
        0x42000000, 0x42040000, 0x42080000, 0x420c0000, 0x42100000, 0x42140000, 0x42180000, 0x421c0000,
        0x42200000, 0x42240000, 0x42280000, 0x422c0000, 0x42300000, 0x42340000, 0x42380000, 0x423c0000,
        0x42400000, 0x4236eeef, 0x422d5555, 0x42233333, 0x42188889, 0x420d5556, 0x4201999a, 0x41eaaaab,
        0x41d11111, 0x41b66667, 0x419aaaab, 0x417bbbbd, 0x41400000, 0x41022223, 0x40844445, 0x00000000,
    ];
    assert_eq!(y.len(), expected_bits.len(), "uneven-length output length");
    for (i, (&a, &bits)) in y.iter().zip(expected_bits.iter()).enumerate() {
        let ab = a.to_bits();
        assert_eq!(
            ab,
            bits,
            "chop_shuffle uneven-length: [{i}] got {a} (bits {ab:#010x}) expected {} (bits {bits:#010x})",
            f32::from_bits(bits)
        );
    }
}

/// A grain shorter than the fade length must not panic either. Rust
/// slices don't clip the way Python's do, so this is the defensive
/// extension documented on `chop_shuffle`: over a 200-sample input with
/// `n_grains=8`, `seg` clamps to 64 (`200 // 8 = 25 < 64`), so the last
/// couple of dealt grains come out far shorter than the 16-sample fade
/// and are left unfaded rather than indexed out of bounds.
#[test]
fn chop_shuffle_grain_shorter_than_fade_does_not_panic() {
    let x: Vec<f32> = (0..200).map(|i| i as f32).collect();
    let y = chop_shuffle(&x, 8, 64);
    assert!(!y.is_empty(), "should still produce output, just unfaded");
}

#[test]
fn np_hanning_endpoints_and_hand_values() {
    assert_eq!(np_hanning(0), Vec::<f64>::new(), "M < 1 is empty");
    assert_eq!(
        np_hanning(-3),
        Vec::<f64>::new(),
        "M < 1 is empty (negative)"
    );
    assert_eq!(np_hanning(1), vec![1.0], "M == 1 special-cases to [1.0]");

    let w = np_hanning(12);
    assert_eq!(w.len(), 12);
    assert_eq!(w[0], 0.0, "endpoint is exactly 0");
    assert_eq!(w[11], 0.0, "endpoint is exactly 0");
    // `np.hanning(12)`'s real output, pulled from the venv as raw f64 bit
    // patterns (Python `struct.pack("<d", v)` per element) rather than the
    // ~8-significant-digit decimal numpy's own docstring prints — an exact
    // assertion, not a tolerance. np_hanning's doc comment records that its
    // formula is checked bit-for-bit (0 ULP) against real numpy across
    // several `M`, including this one, so there's nothing here for an
    // epsilon to paper over.
    #[rustfmt::skip]
    let expected_bits: [u64; 12] = [
        0x0000000000000000, 0x3fb451cde26c3d1c, 0x3fd2b4eb931c76a6,
        0x3fe246ebec81e89b, 0x3fea7a4f3fbbac44, 0x3fef5a154de6a82c,
        0x3fef5a154de6a82c, 0x3fea7a4f3fbbac44, 0x3fe246ebec81e89b,
        0x3fd2b4eb931c76a6, 0x3fb451cde26c3d1c, 0x0000000000000000,
    ];
    for (i, (&a, &bits)) in w.iter().zip(expected_bits.iter()).enumerate() {
        let ab = a.to_bits();
        assert_eq!(
            ab,
            bits,
            "np_hanning(12)[{i}]: got {a} (bits {ab:#018x}) expected {} (bits {bits:#018x})",
            f64::from_bits(bits)
        );
    }

    // Odd M: the true midpoint sample hits exactly 1.0.
    let w13 = np_hanning(13);
    assert_eq!(w13.len(), 13);
    assert_eq!(w13[6], 1.0, "midpoint of an odd-length Hann window is 1.0");
}
