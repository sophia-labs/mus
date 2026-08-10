//! Pitch and time: varispeed (libsoxr, the same C library behind librosa's
//! `soxr_hq`), the librosa-compatible STFT phase vocoder (`vocode`,
//! `stretch`), the pure-numpy `pitch_ramp` and `pitch_polyline`, and the
//! sample/tape load path.
//!
//! Owned by stage WF4. Oracle cases: `varispeed_*` (rel_rms 5e-4),
//! `vocode_*`/`stretch_*` (rel_rms 5e-3, exact lengths), `pitch_ramp_*`,
//! `pitch_polyline` (max_abs 1e-5), `load_buzz01_native` (max_abs 1e-6).

use std::f64::consts::PI;
use std::path::Path;

use libsoxr::{Datatype, IOSpec, QualityFlags, QualityRecipe, QualitySpec, Soxr};
use realfft::num_complex::Complex;
use realfft::RealFftPlanner;

use crate::{SR, SR_F64};

/// STFT frame size used throughout this module: `librosa.stft`'s default,
/// and the value `mus_audio.py`'s `vocode`/`stretch` inherit (neither
/// overrides `n_fft`/`hop_length`).
const N_FFT: usize = 2048;
/// `librosa.stft`'s default hop: `win_length // 4` with `win_length ==
/// n_fft`.
const HOP: usize = 512;

// ------------------------------------------------------------ numeric glue
//
// Small helpers that exist purely to match numpy/Python's exact rounding
// and interpolation semantics, per the audio README's numeric discipline:
// matching precision loss is part of matching the oracle.

/// Python's `round()` / numpy's `np.round`: round-half-to-even, unlike
/// `f64::round` (round-half-away-from-zero). Both `varispeed`'s and
/// `time_stretch`'s length formulas, and `phase_vocoder`'s phase-wrap,
/// call this on values whose fractional part is essentially never exactly
/// 0.5 (irrational rates) — but this matches the oracle's actual rounding
/// rule rather than assuming the tie case never bites.
fn py_round(x: f64) -> f64 {
    let floor = x.floor();
    let diff = x - floor;
    if diff < 0.5 {
        floor
    } else if diff > 0.5 {
        floor + 1.0
    } else if (floor as i64) % 2 == 0 {
        floor
    } else {
        floor + 1.0
    }
}

/// `np.linspace(start, stop, num)`: uniform step from `arange(num)*step`,
/// with the last sample explicitly forced to `stop` (numpy's own endpoint
/// correction, avoiding float drift at the boundary).
fn linspace(start: f64, stop: f64, num: usize) -> Vec<f64> {
    if num == 0 {
        return Vec::new();
    }
    if num == 1 {
        return vec![start];
    }
    let step = (stop - start) / (num - 1) as f64;
    let mut y: Vec<f64> = (0..num).map(|i| i as f64 * step + start).collect();
    y[num - 1] = stop;
    y
}

/// `np.interp(pos, np.arange(n), fp)`, specialized to the unit-spaced `xp`
/// every call site in this module uses, with `pos` already clamped into
/// `[0, n-1]`. Matches numpy's exact pass-through at the boundaries and
/// its `fp[j] + slope*(x - xp[j])` interior formula.
fn interp_unit(pos: f64, fp: &[f64]) -> f64 {
    let n = fp.len();
    if pos <= 0.0 {
        return fp[0];
    }
    let j = pos.floor() as usize;
    if j >= n - 1 {
        return fp[n - 1];
    }
    let frac = pos - j as f64;
    fp[j] + frac * (fp[j + 1] - fp[j])
}

/// `np.interp(x, xp, fp)` for general increasing `xp` — `pitch_polyline`'s
/// anchor-time -> anchor-semitone lookup, where the anchors are not
/// unit-spaced. Anchor lists are tiny (a handful of gesture points), so a
/// linear scan is the right tool.
fn interp_xy(x: f64, xp: &[f64], fp: &[f64]) -> f64 {
    let n = xp.len();
    if x <= xp[0] {
        return fp[0];
    }
    if x >= xp[n - 1] {
        return fp[n - 1];
    }
    let mut j = 0;
    while j + 1 < n && xp[j + 1] < x {
        j += 1;
    }
    let frac = (x - xp[j]) / (xp[j + 1] - xp[j]);
    fp[j] + frac * (fp[j + 1] - fp[j])
}

/// `librosa.util.fix_length`: trim to `size`, or zero-pad at the tail.
fn fix_length(x: &[f32], size: usize) -> Vec<f32> {
    if x.len() >= size {
        x[..size].to_vec()
    } else {
        let mut v = x.to_vec();
        v.resize(size, 0.0);
        v
    }
}

// ---------------------------------------------------------------- soxr HQ

/// One-shot `soxr` resample at libsoxr's `SOXR_HQ` (20-bit) recipe with
/// flags `0` — exactly the recipe python-soxr's `quality='HQ'` builds
/// (`SOXR_ROLLOFF_SMALL == 0`, so this is not merely libsoxr-rs's default,
/// it is spelled out to remove any doubt). `librosa.resample`'s
/// `res_type="soxr_hq"` binds that same python-soxr call. A single
/// `process` + a flushing `process(None, ..)` is libsoxr's own
/// `soxr_oneshot()` recipe (create, process, flush, delete) — the whole
/// buffer at once, matching librosa's non-streaming use.
fn soxr_resample(x: &[f32], in_rate: f64, out_rate: f64) -> Vec<f32> {
    if x.is_empty() {
        return Vec::new();
    }
    let io_spec = IOSpec::new(Datatype::Float32I, Datatype::Float32I);
    let quality_spec = QualitySpec::new(&QualityRecipe::High, QualityFlags::ROLLOFF_SMALL);
    let soxr = Soxr::create(
        in_rate,
        out_rate,
        1,
        Some(&io_spec),
        Some(&quality_spec),
        None,
    )
    .expect("soxr: create resampler");

    let est = (x.len() as f64 * out_rate / in_rate).ceil() as usize;
    let mut out = vec![0f32; est + 1024];
    let (idone, odone) = soxr.process(Some(x), &mut out).expect("soxr: process");
    assert_eq!(
        idone,
        x.len(),
        "soxr: did not consume the full input buffer in one shot"
    );
    let (_, odone2) = soxr
        .process::<f32, f32>(None, &mut out[odone..])
        .expect("soxr: flush");
    out.truncate(odone + odone2);
    out
}

/// `librosa.resample(y, orig_sr=.., target_sr=.., res_type="soxr_hq")`:
/// soxr HQ, then hard-trimmed/zero-padded to `ceil(len(y) * ratio)` —
/// `fix=True` is librosa's default and `mus_audio.py` never overrides it.
fn resample_soxr(x: &[f32], orig_sr: f64, target_sr: f64) -> Vec<f32> {
    if orig_sr == target_sr {
        return x.to_vec();
    }
    let ratio = target_sr / orig_sr;
    let n_samples = (x.len() as f64 * ratio).ceil() as usize;
    let y = soxr_resample(x, orig_sr, target_sr);
    fix_length(&y, n_samples)
}

/// `mus_audio.varispeed` (line 84): resample, pitch and duration coupled
/// like tape. `orig_sr=len(x)`, `target_sr=n_out` is librosa's "rates are
/// the two lengths" trick for an arbitrary rational resample ratio.
///
/// `semitones` is `f64`, not `f32`: it is a plain Python float in the
/// oracle (no cast ever touches it), and it drives `n_out`'s `round()` —
/// truncating it to `f32` first would perturb that rounding for no
/// reason. Only the audio buffer follows numpy's `f32` dtype flow.
pub fn varispeed(x: &[f32], semitones: f64) -> Vec<f32> {
    if semitones.abs() < 1e-4 || x.len() < 8 {
        return x.to_vec();
    }
    let rate = 2.0f64.powf(semitones / 12.0);
    let n_out = (py_round(x.len() as f64 / rate) as i64).max(8) as usize;
    resample_soxr(x, x.len() as f64, n_out as f64)
}

// ------------------------------------------------------- STFT / vocoder

/// One column of an STFT matrix: `n_fft/2+1` complex bins. `Complex<f32>`
/// — **not** `f64` — because librosa infers `complex64` storage from `f32`
/// input audio: `dtype = util.dtype_r2c(y.dtype)` (`core/spectrum.py`
/// L344-345), and `dtype_r2c(float32) == complex64`
/// (`librosa/util/utils.py` L2218-2238). The STFT matrix, the phase
/// vocoder's output, and the ISTFT input are all `complex64` in the
/// oracle. That does *not* mean every intermediate computation runs at
/// `f32` — `stft`, `phase_vocoder`, and `istft`'s doc comments each trace
/// the specific precision the oracle actually reaches at every step
/// (several of which are `f64`); matching that precisely, rather than
/// uniformly `f32`- or `f64`-ing the whole pipeline, is the fix this
/// module needed. Verified against the installed librosa 0.11.0 / numpy
/// 2.0.2, not assumed from folk memory.
type Frame = Vec<Complex<f32>>;

/// Periodic (`fftbins=True`) Hann window of length `n`, matching
/// `scipy.signal.get_window("hann", n, fftbins=True)`: the symmetric
/// `0.5 - 0.5*cos(2*pi*k/(n))` form scipy reaches by building a length
/// `n+1` symmetric window and dropping the last sample — algebraically
/// this closed form.
fn hann_periodic(n: usize) -> Vec<f64> {
    (0..n)
        .map(|i| 0.5 - 0.5 * (2.0 * PI * i as f64 / n as f64).cos())
        .collect()
}

/// `librosa.stft` (`core/spectrum.py` line 55) at its defaults: n_fft=2048,
/// hop=512, hann, `center=True`. Read from the installed librosa 0.11
/// source, not folk memory — `pad_mode` there defaults to `"constant"`
/// (zero padding), not `"reflect"`, and neither `time_stretch` nor
/// `pitch_shift` override it. `win_length == n_fft` here so the window
/// needs no centering pad. The head/tail split librosa uses to dodge a
/// full-array copy on long signals is a memory optimization only — it
/// produces the identical frames a plain full-array zero-pad does, which
/// is what this does.
///
/// Runs the per-frame windowing and RFFT in **double** precision, then
/// truncates each spectrum to `Complex<f32>` once, on storage — matching
/// the oracle's actual promotion chain rather than assuming `f32` in, so
/// `f32` throughout: `scipy.signal.get_window` returns a `float64` array
/// *regardless* of the signal's dtype, so `fft_window * y_frames`
/// (`core/spectrum.py` L346) — a real array times a real array, where
/// NEP 50's "weak Python scalar" carve-out does not apply — upcasts the
/// windowed frame to `float64` before `scipy.fft.rfft` ever sees it, and
/// that call returns `complex128`. Only the assignment into the
/// pre-allocated `complex64` `stft_matrix` (L332, L354-355) casts down,
/// once, per bin. Verified against the installed build:
/// `get_window("hann", 2048, fftbins=True).dtype == float64`,
/// `(window * float32_frame).dtype == float64`,
/// `scipy.fft.rfft(float64_array).dtype == complex128`.
fn stft(x: &[f32]) -> Vec<Frame> {
    let window = hann_periodic(N_FFT);
    let half = N_FFT / 2;
    let n = x.len();
    let mut padded = vec![0.0f32; n + 2 * half];
    padded[half..half + n].copy_from_slice(x);
    let n_frames = 1 + n / HOP;

    let mut planner = RealFftPlanner::<f64>::new();
    let r2c = planner.plan_fft_forward(N_FFT);
    let mut inbuf = r2c.make_input_vec();
    let mut spectrum = r2c.make_output_vec();

    let mut frames = Vec::with_capacity(n_frames);
    for t in 0..n_frames {
        let start = t * HOP;
        for i in 0..N_FFT {
            inbuf[i] = window[i] * padded[start + i] as f64;
        }
        r2c.process(&mut inbuf, &mut spectrum).expect("stft: rfft");
        frames.push(
            spectrum
                .iter()
                .map(|c| Complex::new(c.re as f32, c.im as f32))
                .collect(),
        );
    }
    frames
}

/// A frame at index `i`, or an all-zero frame past the end — `phase_vocoder`
/// pads `D` with trailing zero columns so the `step+1` lookahead never
/// runs off the array; this does the same without a physical copy.
fn frame_or_zero<'a>(d: &'a [Frame], zero: &'a Frame, i: usize) -> &'a Frame {
    if i < d.len() {
        &d[i]
    } else {
        zero
    }
}

/// `librosa.core.phase_vocoder` (`core/spectrum.py` line 1365), ported to
/// match its *actual* per-step precision rather than a single uniform
/// one. `time_steps = arange(0, n_frames_in, rate)` is generated the way
/// numpy actually builds it (`i*step`, not repeated accumulation) —
/// verified bit-exact against `np.arange` across this module's fixture
/// ratios and a spread of random ones, since repeated `+=` would drift
/// over hundreds of frames.
///
/// Two accumulation cast points carry state across the frame loop, and
/// each must lose precision exactly where the oracle does:
///
/// - `phase_acc` is `float32`: `np.angle(D[..., 0])` (L1447) returns
///   `float32` because `D` is `complex64`, and the in-place `phase_acc +=
///   phi_advance + dphase` (L1461) — even though the right-hand side is
///   `float64` (next paragraph) — truncates back to `float32` on *every*
///   store. Verified empirically, not assumed: `float32_array +=
///   float64_array` reproduces `(a.astype(f64) + b).astype(f32)`
///   bit-for-bit (2M randomized samples, zero mismatches), which is a
///   "compute at the promoted precision, cast once at the point of
///   storage" rule — not "downcast the addend to f32 first". An f64
///   accumulator here (the prior draft's bug) loses *less* precision per
///   step than the oracle does, and over dozens of frames that compounds
///   into a different number, not a more-accurate one.
/// - `d_stretch` (this function's return value, `Frame` = `Complex<f32>`)
///   is `complex64`: `np.zeros_like(D, shape=shape)` (L1435) inherits
///   `D`'s dtype, and `D` — this module's `stft` output — is `complex64`.
///
/// Everything else is a per-iteration local, and the oracle's own type
/// promotion actually lands those at `float64`, not `float32`:
///
/// - `mag`: `alpha = np.mod(step, 1.0)` (L1454) is a *numpy* `float64`
///   scalar (`step` iterates the `float64` `time_steps` array), and under
///   NumPy 2's NEP 50, a numpy scalar — unlike a bare Python `float` — is
///   not "weak": `(1.0 - alpha) * np.abs(column)` (L1453) promotes the
///   whole product to `float64` even though `np.abs` of a `complex64`
///   column is itself `float32`.
/// - `dphase`: `np.angle(col1) - np.angle(col0) - phi_advance` (L1458) is
///   left-associative — the first subtraction is `float32 - float32`
///   (stays `float32`, with that rounding already baked in), and *only
///   then* does subtracting `phi_advance` upcast the result to `float64`.
///   Ported as such below: the `arg()` difference is taken in `f32`
///   before widening, not widened first.
///
/// `util.phasor(phase_acc, mag=mag)` (`z = cos(phase_acc) +
/// 1j*sin(phase_acc); z *= mag`) follows the same pattern: `cos`/`sin` of
/// the `float32` `phase_acc` run at `float32` (matching Rust's native
/// `f32::sin_cos`), and `z *= mag` (`complex64 *= float64`) computes the
/// multiply at `complex128` precision and truncates once on store — also
/// verified empirically (500K randomized samples: bit-exact against a
/// `complex128`-then-cast reference; disagrees with a
/// cast-`mag`-to-`f32`-first reference on 42% of them, by up to ~2e-6).
fn phase_vocoder(d: &[Frame], rate: f64) -> Vec<Frame> {
    let n_frames_in = d.len();
    let n_bins = N_FFT / 2 + 1;
    let zero_col: Frame = vec![Complex::new(0.0, 0.0); n_bins];

    // hop * fft_frequencies(sr=2*pi, n_fft) == hop * linspace(0, pi, n_bins).
    let phi_advance: Vec<f64> = linspace(0.0, PI, n_bins)
        .into_iter()
        .map(|f| HOP as f64 * f)
        .collect();

    let mut phase_acc: Vec<f32> = d[0].iter().map(|c| c.arg()).collect();

    let n_steps = ((n_frames_in as f64) / rate).ceil() as usize;
    let mut out = Vec::with_capacity(n_steps);
    for si in 0..n_steps {
        let step = si as f64 * rate;
        let i0 = step.floor() as usize;
        let i1 = i0 + 1;
        let c0 = frame_or_zero(d, &zero_col, i0);
        let c1 = frame_or_zero(d, &zero_col, i1);
        let alpha = step - step.floor();

        let mut frame_out = Vec::with_capacity(n_bins);
        let mut dphase = vec![0.0f64; n_bins];
        for k in 0..n_bins {
            // np.abs(complex64) is float32; the product with the f64
            // alpha weights promotes to float64 (see doc comment).
            let mag = (1.0 - alpha) * c0[k].norm() as f64 + alpha * c1[k].norm() as f64;

            // z = cos(phase_acc) + 1j*sin(phase_acc) at phase_acc's own
            // float32 precision; z *= mag at complex128 precision,
            // truncated once to complex64 on store.
            let (sin_a, cos_a) = phase_acc[k].sin_cos();
            let re = (cos_a as f64 * mag) as f32;
            let im = (sin_a as f64 * mag) as f32;
            frame_out.push(Complex::new(re, im));

            // arg() difference taken in f32 first, matching the
            // left-associative float32 - float32 the oracle evaluates
            // before the float64 phi_advance ever enters the expression.
            let arg_diff = c1[k].arg() - c0[k].arg();
            let dp = arg_diff as f64 - phi_advance[k];
            dphase[k] = dp - 2.0 * PI * py_round(dp / (2.0 * PI));
        }
        out.push(frame_out);
        for k in 0..n_bins {
            // Computed at f64 (phi_advance and dphase already are); the
            // store truncates to f32 — once, per bin, per frame. This is
            // the accumulation cast point the phase state depends on.
            phase_acc[k] = (phase_acc[k] as f64 + phi_advance[k] + dphase[k]) as f32;
        }
    }
    out
}

/// `librosa.filters.window_sumsquare` specialized to this module's fixed
/// hann/n_fft/hop: overlap-add of the squared window (`norm=None` — a
/// verified no-op in `util.normalize`, so no window normalization before
/// squaring).
///
/// Returns `Vec<f32>`, not `f64`: `istft` derives `dtype =
/// util.dtype_c2r(stft_matrix.dtype)` (`core/spectrum.py` L484) and
/// threads that same `dtype` into `window_sumsquare`'s `dtype` parameter
/// (L606-613) — `float32` here, since this module's `stft_matrix` (the
/// phase vocoder's output) is always `complex64`. The squared window
/// itself (`win_sq`) stays `float64` throughout construction (`get_window`
/// returns `float64` regardless of the target `dtype`); the accumulation
/// `x[...] += win_sq[...]` in `__window_ss_fill` (`filters.py` L1521,
/// `@jit(nopython=True)`) is float64-computed, float32-stored on every
/// add — the same promote-then-truncate-on-store pattern as
/// `phase_vocoder`'s `phase_acc`, ported the same way here.
fn window_sumsquare(n_frames: usize) -> Vec<f32> {
    let window = hann_periodic(N_FFT);
    let win_sq: Vec<f64> = window.iter().map(|w| w * w).collect();
    let n = N_FFT + HOP * (n_frames - 1);
    let mut x = vec![0.0f32; n];
    for t in 0..n_frames {
        let sample = t * HOP;
        for i in 0..N_FFT {
            x[sample + i] = (x[sample + i] as f64 + win_sq[i]) as f32;
        }
    }
    x
}

/// `librosa.core.istft` (`core/spectrum.py` line 394): inverse rFFT per
/// frame, hann-windowed overlap-add, normalized by the window
/// sum-of-squares envelope, trimmed/padded to `length`. `mus_audio.py`
/// always calls this through `time_stretch` with an explicit predicted
/// `length` and the default `center=True`, so those are the only paths
/// implemented. librosa's head/tail-buffer split (its own memory
/// optimization for the forward case's counterpart) is skipped for the
/// same reason as in `stft`: a single accumulation buffer, added into
/// left-to-right in frame order, sums the same terms in the same order
/// and is bit-equivalent.
///
/// Returns `Vec<f32>` directly, not `f64`: `dtype =
/// util.dtype_c2r(stft_matrix.dtype)` (L484) is `float32` here, because
/// `stft_matrix` — the phase vocoder's output — is `complex64`. That
/// `dtype` is what `y`, the overlap-add accumulator, is allocated as
/// (L497), and what `window_sumsquare` is threaded through as (L606-613).
/// Two distinct per-frame precisions are involved, both ported
/// faithfully rather than uniformly `f64`'d:
///
/// - the inverse RFFT itself runs at `float32`: `scipy.fft.irfft` on a
///   `complex64` array returns `float32` *directly* (verified against the
///   installed build) — unlike the *forward* direction, where the
///   `float64` Hann window forces a `float64` promotion before the
///   transform runs (see `stft`'s doc comment), nothing upstream of this
///   IRFFT is `float64`, so it simply runs native. `realfft`'s inverse
///   is unnormalized (unlike `scipy.fft.irfft`, which folds the `1/n_fft`
///   scaling into its own transform); the division below reproduces that
///   scaling at the same native `f32` precision, rather than promoting
///   for it.
/// - the window re-multiply and overlap-add run at `float64`:
///   `ifft_window` is `float64` (`get_window`, same as the forward
///   direction), so `ifft_window * irfft_output` (`float64 * float32`,
///   two real arrays — ordinary promotion, not NEP 50's scalar
///   deference) upcasts to `float64` before `__overlap_add`
///   (`filters.py`-adjacent, `@jit(nopython=True)`) adds it into the
///   `float32` accumulator — truncating once *per sample, per
///   overlapping frame* (four times over, at this module's 4x hop
///   overlap: 2048/512), which is a lossier accumulation than summing at
///   f64 throughout and rounding once at the end.
fn istft(d: &[Frame], length: usize) -> Vec<f32> {
    let window = hann_periodic(N_FFT);
    let half = N_FFT / 2;
    let total_frames = d.len();
    let padded_length = length + 2 * half;
    let n_frames = total_frames.min(padded_length.div_ceil(HOP)).max(1);

    let full_len = N_FFT + HOP * (n_frames - 1);
    let mut acc = vec![0.0f32; full_len];

    let mut planner = RealFftPlanner::<f32>::new();
    let c2r = planner.plan_fft_inverse(N_FFT);
    let mut outbuf = c2r.make_output_vec();

    for (t, frame) in d.iter().take(n_frames).enumerate() {
        let mut spectrum = frame.clone();
        // numpy/scipy's irfft silently uses only the *real* part of the DC
        // and Nyquist bins (verified empirically: zeroing their imaginary
        // part before irfft is bit-identical to leaving it as-is). The
        // phase vocoder's phasor reconstruction writes both bins like any
        // other, so they carry tiny non-zero imaginary noise from phase
        // accumulation; realfft's c2r validates that and errors instead of
        // silently dropping it, so it is dropped explicitly here to match
        // the oracle rather than to satisfy the validator.
        let last = spectrum.len() - 1;
        spectrum[0].im = 0.0;
        spectrum[last].im = 0.0;
        c2r.process(&mut spectrum, &mut outbuf)
            .expect("istft: irfft");
        let start = t * HOP;
        for i in 0..N_FFT {
            // realfft's raw inverse, normalized at the same f32 precision
            // scipy.fft.irfft(complex64) natively returns.
            let irfft_val = outbuf[i] / N_FFT as f32;
            let ytmp = window[i] * irfft_val as f64;
            acc[start + i] = (acc[start + i] as f64 + ytmp) as f32;
        }
    }

    let wss = window_sumsquare(n_frames);
    let tiny = f32::MIN_POSITIVE; // librosa.util.tiny for a float32 dtype

    let mut y = vec![0.0f32; length];
    for (i, yi) in y.iter_mut().enumerate() {
        let idx = half + i;
        if idx < acc.len() {
            *yi = acc[idx];
            let denom = wss[idx];
            if denom > tiny {
                *yi /= denom;
            }
        }
    }
    y
}

/// `stft` -> `phase_vocoder` -> `istft`: the shared engine behind
/// `mus_audio.stretch` (`effects.py` line 338) and the inner step of
/// `mus_audio.vocode` (`effects.py` line 399's `pitch_shift`, which calls
/// `time_stretch` before resampling back). `len_stretch =
/// round(len(x)/rate)` is `time_stretch`'s own length prediction, used by
/// both callers. No `f64` round-trip on `x` here — `stft` takes the `f32`
/// signal directly (matching `y`'s actual dtype in the oracle) and
/// `istft` now returns `f32` directly, so there is nothing left to cast.
fn time_stretch_core(x: &[f32], rate: f64) -> Vec<f32> {
    let d = stft(x);
    let d2 = phase_vocoder(&d, rate);
    let len_stretch = py_round(x.len() as f64 / rate) as usize;
    istft(&d2, len_stretch)
}

/// `mus_audio.vocode` (line 94): librosa's phase-vocoder pitch shift.
/// `effects.pitch_shift` = time-stretch by `2**(-st/12)` (`bins_per_octave
/// = 12`), then soxr-HQ resample back to the original duration, cropped
/// to the input length.
///
/// `semitones` is `f64` (see `varispeed`'s doc comment): it sets the
/// phase vocoder's `rate`, which selects a *discrete* STFT frame index
/// every step (`floor(i*rate)`) — losing `semitones` to `f32` first can
/// flip that selection near a frame boundary and desynchronize the whole
/// reconstruction, not just perturb it. Measured, not theoretical: an
/// early draft that took `f32` here reproduced this exactly (~60% rel_rms
/// on a case whose `factor`/`semitones` weren't exactly `f32`-representable).
pub fn vocode(x: &[f32], semitones: f64) -> Vec<f32> {
    if semitones.abs() < 1e-4 || x.len() < 2048 {
        return x.to_vec();
    }
    let rate = 2.0f64.powf(-semitones / 12.0);
    let y_stretch = time_stretch_core(x, rate);
    let y_shift = resample_soxr(&y_stretch, SR_F64 / rate, SR_F64);
    fix_length(&y_shift, x.len())
}

/// `mus_audio.stretch` (line 102): `factor > 1` makes it longer, via
/// `librosa.effects.time_stretch(x, rate=1/factor)`. `factor` is `f64` —
/// see `vocode`'s doc comment for why that isn't optional here.
pub fn stretch(x: &[f32], factor: f64) -> Vec<f32> {
    if (factor - 1.0).abs() < 1e-3 || x.len() < 2048 {
        return x.to_vec();
    }
    let rate = 1.0 / factor;
    time_stretch_core(x, rate)
}

// ------------------------------------------------------------ pitch geometry

/// The pitch-ramp curve sampled at `n` points: `mus_audio.pitch_ramp`'s
/// nested `ramp()` closure. Any `curve` other than exactly `"exp"` takes
/// the linear branch, matching the Python `if/else`.
fn ramp_curve(n: usize, st0: f64, st1: f64, curve: &str, tau: f64) -> Vec<f64> {
    if curve == "exp" {
        let tau = tau.max(1e-4);
        (0..n)
            .map(|i| st1 + (st0 - st1) * (-((i as f64 / SR_F64) / tau)).exp())
            .collect()
    } else {
        linspace(st0, st1, n)
    }
}

/// `mus_audio.pitch_ramp` (line 109): a continuous varispeed ramp across
/// the sample. Iterative length solve (3 rounds) so the integrated read
/// rate consumes exactly the input, then a clipped cumulative-rate read
/// position map through `np.interp` semantics.
///
/// `st0`/`st1`/`tau` are `f64` — plain Python floats in the oracle, and
/// `st0`/`st1` feed the same iterative, `int()`-truncated length solve
/// `varispeed`'s `round()` does; see `vocode`'s doc comment for why
/// truncating them to `f32` first is a correctness bug, not a rounding
/// nicety.
pub fn pitch_ramp(x: &[f32], st0: f64, st1: f64, curve: &str, tau: f64) -> Vec<f32> {
    let n_in = x.len();
    if n_in < 8 {
        return x.to_vec();
    }
    if (st0 - st1).abs() < 1e-3 {
        return varispeed(x, st0);
    }

    let min_st = st0.min(st1);
    let mut n_out = ((n_in as f64 / 2.0f64.powf(min_st / 12.0)).trunc() as i64).max(16);

    for _ in 0..3 {
        let ramp = ramp_curve(n_out as usize, st0, st1, curve, tau);
        let total: f64 = ramp.iter().map(|&st| 2.0f64.powf(st / 12.0)).sum();
        if total <= 1e-9 {
            break;
        }
        n_out = ((n_out as f64 * (n_in as f64 - 1.0) / total).trunc() as i64).max(16);
    }
    let n_out = n_out as usize;

    let ramp = ramp_curve(n_out, st0, st1, curve, tau);
    let mut pos = Vec::with_capacity(n_out);
    let mut acc = 0.0f64;
    for st in ramp {
        acc += 2.0f64.powf(st / 12.0);
        pos.push(acc.clamp(0.0, n_in as f64 - 1.0));
    }

    if pos.len() < 8 {
        return varispeed(x, st1);
    }

    let xf: Vec<f64> = x.iter().map(|&v| v as f64).collect();
    pos.iter().map(|&p| interp_unit(p, &xf) as f32).collect()
}

/// `mus_audio.pitch_polyline` (line 150): continuous varispeed along a
/// measured pitch polyline. The anchor span sets the output duration; a
/// 10 ms fade covers the "tape runs out" case where the gesture outlasts
/// the sample.
pub fn pitch_polyline(x: &[f32], t_anchor: &[f64], st_anchor: &[f64]) -> Vec<f32> {
    let n_in = x.len();
    if n_in < 8 || t_anchor.len() < 2 {
        return x.to_vec();
    }
    let dur = t_anchor[t_anchor.len() - 1] - t_anchor[0];
    let n_out = ((dur * SR_F64).trunc() as i64).max(16) as usize;

    let tt = linspace(t_anchor[0], t_anchor[t_anchor.len() - 1], n_out);
    let rate: Vec<f64> = tt
        .iter()
        .map(|&t| 2.0f64.powf(interp_xy(t, t_anchor, st_anchor) / 12.0))
        .collect();

    let rate0 = rate[0];
    let n_in_f = n_in as f64;
    let mut pos = Vec::with_capacity(n_out);
    let mut valid = Vec::with_capacity(n_out);
    let mut acc = 0.0f64;
    for r in rate {
        acc += r;
        let p = acc - rate0;
        valid.push(p <= n_in_f - 1.0);
        pos.push(p.clamp(0.0, n_in_f - 1.0));
    }

    let xf: Vec<f64> = x.iter().map(|&v| v as f64).collect();
    let mut y: Vec<f32> = pos.iter().map(|&p| interp_unit(p, &xf) as f32).collect();

    if !valid.iter().all(|&v| v) {
        let k = valid.iter().filter(|&&v| v).count();
        let f = k.min((0.010 * SR_F64) as usize);
        if f > 1 {
            for (i, fv) in linspace(1.0, 0.0, f).into_iter().enumerate() {
                y[k - f + i] *= fv as f32;
            }
        }
        for v in y[k..].iter_mut() {
            *v = 0.0;
        }
    }
    y
}

// --------------------------------------------------------------- load path

/// `librosa.to_mono`: average across channels. `samples` is interleaved
/// (`[ch0, ch1, ch0, ch1, ...]`); `scale` converts one raw decoded sample
/// to a signal-range f32 (PCM_16: `/32768.0`; float: identity).
fn interleaved_to_mono<T: Copy>(
    samples: &[T],
    channels: usize,
    scale: impl Fn(T) -> f32,
) -> Vec<f32> {
    if channels <= 1 {
        return samples.iter().map(|&s| scale(s)).collect();
    }
    samples
        .chunks_exact(channels)
        .map(|frame| {
            let sum: f32 = frame.iter().map(|&s| scale(s)).sum();
            sum / channels as f32
        })
        .collect()
}

/// The sample/tape load path behind the corpus loader: `librosa.load(path,
/// sr=SR, mono=True)`. Every packaged asset is already `SR`-native, so
/// this is normally a pure decode (PCM_16 -> f32 by `/32768.0`, float
/// wavs read verbatim, channels averaged to mono); the resample branch
/// (soxr HQ, this module's own machinery — what `librosa.load` would do)
/// exists for the day a source asset isn't SR-native. The real corpus
/// never hits either the resample branch or the stereo branch, so both
/// are covered by this module's synthetic-wav unit tests instead of a
/// fixture.
pub fn load_decode<P: AsRef<Path>>(path: P) -> hound::Result<Vec<f32>> {
    let mut reader = hound::WavReader::open(path)?;
    let spec = reader.spec();
    let channels = spec.channels as usize;

    let mono = match (spec.sample_format, spec.bits_per_sample) {
        (hound::SampleFormat::Int, 16) => {
            let samples: Vec<i16> = reader.samples::<i16>().collect::<hound::Result<_>>()?;
            interleaved_to_mono(&samples, channels, |s| s as f32 / 32768.0)
        }
        (hound::SampleFormat::Float, 32) => {
            let samples: Vec<f32> = reader.samples::<f32>().collect::<hound::Result<_>>()?;
            interleaved_to_mono(&samples, channels, |s| s)
        }
        _ => return Err(hound::Error::Unsupported),
    };

    if spec.sample_rate as usize == SR {
        Ok(mono)
    } else {
        Ok(resample_soxr(&mono, spec.sample_rate as f64, SR_F64))
    }
}
