//! Golden tests for stage WF4 (`mus_dsp::pitch`): resampling, the phase
//! vocoder, pitch geometry, and the sample load path. Follows the
//! `golden_kernels.rs` pattern — resolve the case by manifest name, run
//! the port, `check` against the oracle's tolerance. Also covers the
//! contract properties the spec calls out by name (output length, and
//! determinism) and the two `load_decode` branches the real corpus never
//! exercises (stereo averaging, resampling a non-native rate).

use std::path::{Path, PathBuf};

use mus_dsp::fixtures::case;
use mus_dsp::pitch::{load_decode, pitch_polyline, pitch_ramp, stretch, varispeed, vocode};

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

fn f64_array_arg(args: &serde_json::Value, key: &str) -> Vec<f64> {
    args[key]
        .as_array()
        .unwrap_or_else(|| panic!("arg {key:?} missing/not an array"))
        .iter()
        .map(|v| v.as_f64().expect("array element not numeric"))
        .collect()
}

// ------------------------------------------------------------- 1. varispeed

#[test]
fn varispeed_up5() {
    let c = case("varispeed_up5");
    c.check(&varispeed(&c.input_f32(), c.arg_f64("semitones")));
}

#[test]
fn varispeed_down12() {
    let c = case("varispeed_down12");
    c.check(&varispeed(&c.input_f32(), c.arg_f64("semitones")));
}

// ------------------------------------------------------ 2. vocode / stretch

#[test]
fn vocode_up35() {
    let c = case("vocode_up35");
    c.check(&vocode(&c.input_f32(), c.arg_f64("semitones")));
}

#[test]
fn vocode_down7() {
    let c = case("vocode_down7");
    c.check(&vocode(&c.input_f32(), c.arg_f64("semitones")));
}

#[test]
fn stretch_140() {
    let c = case("stretch_140");
    c.check(&stretch(&c.input_f32(), c.arg_f64("factor")));
}

#[test]
fn stretch_060() {
    let c = case("stretch_060");
    c.check(&stretch(&c.input_f32(), c.arg_f64("factor")));
}

// -------------------------------------------- 3. pitch_ramp / pitch_polyline

#[test]
fn pitch_ramp_lin() {
    let c = case("pitch_ramp_lin");
    let curve = c.meta.args["curve"].as_str().unwrap();
    let out = pitch_ramp(
        &c.input_f32(),
        c.arg_f64("st0"),
        c.arg_f64("st1"),
        curve,
        c.arg_f64("tau"),
    );
    c.check(&out);
}

#[test]
fn pitch_ramp_exp_kick() {
    let c = case("pitch_ramp_exp_kick");
    let curve = c.meta.args["curve"].as_str().unwrap();
    let out = pitch_ramp(
        &c.input_f32(),
        c.arg_f64("st0"),
        c.arg_f64("st1"),
        curve,
        c.arg_f64("tau"),
    );
    c.check(&out);
}

#[test]
fn pitch_polyline_gesture() {
    let c = case("pitch_polyline");
    let t_anchor = f64_array_arg(&c.meta.args, "t_anchor");
    let st_anchor = f64_array_arg(&c.meta.args, "st_anchor");
    let out = pitch_polyline(&c.input_f32(), &t_anchor, &st_anchor);
    c.check(&out);
}

// ------------------------------------------------------------- 4. load_decode

#[test]
fn load_buzz01_native() {
    let c = case("load_buzz01_native");
    let rel_path = c.meta.args["path"].as_str().unwrap();
    let out = load_decode(repo_root().join(rel_path)).expect("load_decode: buzz_01.wav");
    c.check(&out);
}

// ---------------------------------------------------------- contract tests
//
// "a `fix_length`-style unit test that `vocode` output length always
// equals input length; a determinism test (same input twice -> identical
// output)" — WF4-pitch.md's DoD, by name.

#[test]
fn vocode_output_length_always_equals_input_length() {
    let c = case("vocode_up35");
    let x = c.input_f32();
    for &st in &[-11.5f64, -7.0, -3.25, -0.5, 0.5, 3.5, 11.5] {
        let y = vocode(&x, st);
        assert_eq!(
            y.len(),
            x.len(),
            "vocode(st={st}) length {} != input length {}",
            y.len(),
            x.len()
        );
    }
    // The passthrough branches are part of the same length contract.
    assert_eq!(vocode(&x, 0.0).len(), x.len());
    let short = vec![0.0f32; 100];
    assert_eq!(vocode(&short, 5.0).len(), short.len());
}

#[test]
fn vocode_and_pitch_ramp_are_deterministic() {
    let c = case("vocode_up35");
    let x = c.input_f32();
    assert_eq!(
        vocode(&x, 3.5),
        vocode(&x, 3.5),
        "vocode must be deterministic for identical input"
    );

    let r = case("pitch_ramp_exp_kick");
    let y = r.input_f32();
    let a = pitch_ramp(&y, 0.0, -40.0, "exp", 0.045);
    let b = pitch_ramp(&y, 0.0, -40.0, "exp", 0.045);
    assert_eq!(
        a, b,
        "pitch_ramp must be deterministic across its 3-round length solve"
    );
}

#[test]
fn passthrough_guards_return_input_unchanged() {
    // Below every function's minimum-length floor (8 samples).
    let short = vec![0.1f32, 0.2, -0.3, 0.4];
    assert_eq!(varispeed(&short, 5.0), short, "varispeed: len < 8");
    assert_eq!(
        pitch_ramp(&short, 8.0, -4.0, "lin", 0.045),
        short,
        "pitch_ramp: len < 8"
    );
    assert_eq!(
        pitch_polyline(&short, &[0.0, 0.1], &[0.0, 1.0]),
        short,
        "pitch_polyline: len < 8"
    );

    // At/above the length floor, but below the semitone epsilon (1e-4).
    let eight = vec![0.1f32, 0.2, -0.3, 0.4, 0.0, -0.1, 0.25, 0.5];
    assert_eq!(
        varispeed(&eight, 0.00005),
        eight,
        "varispeed: |semitones| < 1e-4"
    );
    assert_eq!(
        pitch_ramp(&eight, 5.0, 5.0002, "lin", 0.045),
        varispeed(&eight, 5.0),
        "pitch_ramp: |st0 - st1| < 1e-3 collapses to varispeed(st0)"
    );

    // Below the STFT length floor (2048 samples).
    let below_stft_floor = vec![0.0f32; 2000];
    assert_eq!(
        vocode(&below_stft_floor, 5.0),
        below_stft_floor,
        "vocode: len < 2048"
    );
    assert_eq!(
        stretch(&below_stft_floor, 1.5),
        below_stft_floor,
        "stretch: len < 2048"
    );

    // At/above the STFT floor, but below the near-identity epsilons.
    let long_enough = vec![0.0f32; 4096];
    assert_eq!(
        vocode(&long_enough, 0.00005),
        long_enough,
        "vocode: |semitones| < 1e-4"
    );
    assert_eq!(
        stretch(&long_enough, 1.0002),
        long_enough,
        "stretch: |factor - 1| < 1e-3"
    );
}

// --------------------------------------------------- load_decode: synthetic

fn write_pcm16_wav(path: &Path, channels: u16, sample_rate: u32, interleaved: &[i16]) {
    let spec = hound::WavSpec {
        channels,
        sample_rate,
        bits_per_sample: 16,
        sample_format: hound::SampleFormat::Int,
    };
    let mut w = hound::WavWriter::create(path, spec).expect("create synthetic wav");
    for &s in interleaved {
        w.write_sample(s).expect("write sample");
    }
    w.finalize().expect("finalize synthetic wav");
}

/// Real corpus assets are mono and SR-native, so neither the stereo
/// averaging nor the resample branch of `load_decode` is exercised by a
/// fixture — the spec calls for synthetic-wav coverage instead.
#[test]
fn load_decode_averages_stereo_to_mono() {
    let path = std::env::temp_dir().join("mus_dsp_wf4_test_stereo.wav");
    // Frames chosen so the mean is exact in f32: (L/32768 + R/32768) / 2.
    let interleaved: [i16; 8] = [10_000, -10_000, 0, 0, 20_000, 0, -32768, 32767];
    write_pcm16_wav(&path, 2, mus_dsp::SR as u32, &interleaved);

    let y = load_decode(&path).expect("load_decode: synthetic stereo wav");
    let _ = std::fs::remove_file(&path);

    assert_eq!(y.len(), 4, "4 stereo frames must decode to 4 mono samples");
    // `load_decode`'s averaging is `(scale(l) + scale(r)) / channels as f32`
    // (see `interleaved_to_mono`) — the same f32 ops, in the same order, as
    // `expect` below, so the two are bit-exact, not merely close. An
    // approximate comparison here would hide a real regression (e.g. a
    // summation-order change) behind a tolerance instead of catching it.
    let expect = |l: i16, r: i16| ((l as f32 / 32768.0) + (r as f32 / 32768.0)) / 2.0;
    let expected: Vec<f32> = vec![
        expect(10_000, -10_000),
        expect(0, 0),
        expect(20_000, 0),
        expect(-32768, 32767),
    ];
    assert_eq!(
        y, expected,
        "stereo-to-mono averaging must match f32 arithmetic exactly"
    );
}

/// The resample branch: a source file whose native rate isn't `SR` must
/// come back soxr-HQ resampled to `SR`, at librosa's exact length
/// contract (`ceil(n * target_sr / orig_sr)`).
#[test]
fn load_decode_resamples_non_native_rate() {
    let path = std::env::temp_dir().join("mus_dsp_wf4_test_resample.wav");
    let native_sr = 24_000u32;
    let n = native_sr as usize / 5; // 0.2 s of a simple tone
    let samples: Vec<i16> = (0..n)
        .map(|i| {
            let t = i as f32 / native_sr as f32;
            (0.5 * (2.0 * std::f32::consts::PI * 440.0 * t).sin() * i16::MAX as f32) as i16
        })
        .collect();
    write_pcm16_wav(&path, 1, native_sr, &samples);

    let y = load_decode(&path).expect("load_decode: synthetic 24kHz wav");
    let _ = std::fs::remove_file(&path);

    let expected_len = ((n as f64) * (mus_dsp::SR as f64) / (native_sr as f64)).ceil() as usize;
    assert_eq!(
        y.len(),
        expected_len,
        "resample must hit librosa's exact length contract"
    );

    let rms = (y.iter().map(|&v| v * v).sum::<f32>() / y.len() as f32).sqrt();
    assert!(
        rms > 0.1,
        "resampled 440 Hz tone should carry real energy, got rms={rms}"
    );
}
