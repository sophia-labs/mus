//! The glow chain and event-level treatments — `mus_audio.py`'s
//! `glow_chain` (line 326) plus the two inline render-path treatments
//! (the note envelope, lines 1066-1073; the Haas width delay, lines
//! 1108-1112) that never got their own top-level Python function but are
//! self-contained enough to port as one.
//!
//! Owned by stage WF6, built on WF4's [`crate::pitch::vocode`], WF3's
//! [`crate::filters::sweep_filter`], and WF2's [`crate::kernels::bitcrush`].
//! Oracle cases: `glow_full_chain`, `glow_hold_pump` (`rel_rms` 5e-3 —
//! vocode-tier parity, since `vocode` runs inside both the warble and
//! harmonizer stages). `haas`/`event_envelope` have no fixtures — they're
//! plain numpy slicing/arithmetic with no scipy/librosa call inside, so
//! they're covered by structural unit tests instead, same as this crate's
//! other fixture-free helpers (e.g. `kernels::np_hanning`).

use std::collections::BTreeMap;

use crate::filters::sweep_filter;
use crate::kernels::bitcrush;
use crate::pitch::vocode;
use crate::{SR_F, SR_F64};

// ---------------------------------------------------------------- helpers

/// `np.linspace(start, stop, num)`, `endpoint=True`: numpy's own default
/// dtype (float64, regardless of any eventual downstream cast), the
/// `i*step + start` construction, and the endpoint-exactness fixup that
/// force-sets the last sample to exactly `stop` rather than trusting
/// `(num-1)*step + start` to land there bit-exact. Duplicated locally
/// per this crate's established per-module convention (see
/// `pitch::linspace`, `kernels::np_linspace_f64`) rather than shared,
/// since neither of those is `pub`.
fn linspace(start: f64, stop: f64, num: usize) -> Vec<f64> {
    match num {
        0 => Vec::new(),
        1 => vec![start],
        _ => {
            let step = (stop - start) / (num - 1) as f64;
            let mut y: Vec<f64> = (0..num).map(|i| i as f64 * step + start).collect();
            y[num - 1] = stop;
            y
        }
    }
}

/// 70 ms hold-window length and 15 ms raised-edge length (`glow_chain`
/// lines 334/338) — both derived from `SR` alone, never from a caller
/// argument, so they're constants rather than parameters.
const HOLD_WIN_S: f64 = 0.07;
const HOLD_FADE_S: f64 = 0.015;

/// The `ghold` branch of `glow_chain` (lines 333-348), split out for
/// readability: find the loudest `win`-sample window of `x` by moving-
/// average energy, then loop that window out to `n_out =
/// max(slot_samples, win)` samples via overlap-add, trapezoid-windowed
/// (15 ms raised edges) so the loop seam doesn't click.
///
/// The moving average is computed directly (a plain windowed sum per
/// output position, not a running/incremental sum) rather than mirroring
/// `np.convolve`'s own internal summation order — `mode="valid"` uniform
/// convolution is algebraically `e[i] = mean(x[i..i+win])` (verified by
/// hand against `np.convolve([1,2,3,4,5],[1,1,1])` before trusting it),
/// and only the argmax *position* it selects has to agree with the
/// oracle, not `e`'s exact values — direct summation avoids the
/// incremental-subtraction cancellation a running-sum version would carry
/// over ~13k window positions for no accuracy benefit here.
fn hold_loop(x: &[f32], slot_samples: usize) -> Vec<f32> {
    let win = (HOLD_WIN_S * SR_F64).trunc() as usize;
    if x.len() <= 2 * win {
        return x.to_vec();
    }

    let abs_x: Vec<f64> = x.iter().map(|&v| (v as f64).abs()).collect();
    let win_f = win as f64;
    let n_e = abs_x.len() - win + 1;
    let mut best_i = 0usize;
    let mut best_e = f64::NEG_INFINITY;
    for i in 0..n_e {
        let sum: f64 = abs_x[i..i + win].iter().sum();
        let e = sum / win_f;
        // Strict `>`, matching `np.argmax`'s first-occurrence tie-break.
        if e > best_e {
            best_e = e;
            best_i = i;
        }
    }
    let piece = &x[best_i..best_i + win];

    let f = (HOLD_FADE_S * SR_F64).trunc() as usize;
    let mut w = vec![1.0f32; win];
    if f > 0 && f <= win {
        let up = linspace(0.0, 1.0, f);
        let down = linspace(1.0, 0.0, f);
        for i in 0..f {
            w[i] = up[i] as f32;
        }
        for i in 0..f {
            w[win - f + i] = down[i] as f32;
        }
    }
    let shaped: Vec<f32> = piece.iter().zip(&w).map(|(&p, &wi)| p * wi).collect();

    let n_out = slot_samples.max(win);
    let mut held = vec![0.0f32; n_out + win];
    let step = win - f;
    let mut pos = 0usize;
    while pos < n_out {
        for k in 0..win {
            held[pos + k] += shaped[k];
        }
        pos += step;
    }
    held.truncate(n_out);
    held
}

// ---------------------------------------------------------------- public API

/// `glow_chain`'s `gharm` parameter parse (lines 361-365): fold `|` into
/// `+`, split on `+`, drop empty tokens (Python's `if t` on the raw,
/// untrimmed split piece — filters the exact empty string only), parse
/// every survivor as a float. Python wraps the whole list comprehension in
/// one `try/except ValueError`, so a single bad token discards *all* of
/// it, not just the bad entry — mirrored here by returning the `[0.0]`
/// fallback immediately on the first parse failure rather than collecting
/// a partial list. `tok.trim()` before `parse` matches Python's `float()`,
/// which strips surrounding whitespace before parsing (Rust's `f64`
/// `FromStr` does not), including the case of a token that's whitespace
/// only — non-empty so not skipped by the `if t` check, but still not a
/// valid float, so it must fall through to the same `[0.0]` fallback.
pub fn gharm_intervals(raw: &str) -> Vec<f64> {
    let mut out = Vec::new();
    for tok in raw.replace('|', "+").split('+') {
        if tok.is_empty() {
            continue;
        }
        match tok.trim().parse::<f64>() {
            Ok(v) => out.push(v),
            Err(_) => return vec![0.0],
        }
    }
    out
}

/// `mus_audio.glow_chain` (line 326): hold, warble, harmonizer, coating,
/// pump — see the module doc comment for the fixture names this is
/// arbitrated against. The render call site's `len(x) >= 2048` guard is
/// deliberately *not* reproduced here (per the spec: that's the caller's
/// gate, not this function's), so every stage below runs unconditionally
/// off whatever `x` it's handed; the length floors that do belong to this
/// function's own stages (the hold branch's `len(x) > 2*win`, `vocode`'s
/// own internal `len(x) < 2048` no-op) are preserved exactly where the
/// oracle puts them.
///
/// `params` is the string map WF8 feeds from parsed event params;
/// `st_g`/`slot_samples` arrive pre-resolved (`float(ev.params["glow"])`,
/// `int(slot * SR)` in the oracle) since the render call site computes
/// both before calling in.
///
/// `gwarble`/`pump` differ from `gharm` in one respect: the oracle's
/// `float(params["gwarble"])` raises on a malformed value (there is no
/// `try/except` around it, unlike `gharm`'s), which would abort the whole
/// render. Rather than reproduce a panic on a malformed-but-present
/// string, both fall back to `0.0` the same way a *missing* value does
/// (`params.get("pump", 0.0)`'s own default) — key *presence* still gates
/// whether the branch runs at all (matching `"gwarble" in params`
/// exactly), only a bad value inside an active branch is softened.
pub fn glow_chain(
    x: &[f32],
    st_g: f64,
    params: &BTreeMap<String, String>,
    slot_samples: usize,
) -> Vec<f32> {
    // --- hold
    let ghold = params.get("ghold").map(String::as_str).unwrap_or("0");
    let mut x: Vec<f32> = if ghold != "0" && ghold != "off" {
        hold_loop(x, slot_samples)
    } else {
        x.to_vec()
    };

    // --- warble: square-LFO crossfade between x (dry) and vocode(x, 1.0).
    if let Some(wr_s) = params.get("gwarble") {
        let wr = wr_s.parse::<f64>().unwrap_or(0.0) as f32;
        let up = vocode(&x, 1.0);
        // vocode always returns exactly `x.len()` samples (see its own
        // doc comment), so `up.len() == x.len()` here always; `n_w` is
        // computed anyway to mirror the oracle's own defensive `min`.
        let n_w = x.len().min(up.len());
        let mut out = Vec::with_capacity(n_w);
        for i in 0..n_w {
            let t = i as f32 / SR_F;
            let phase = (t * wr).rem_euclid(1.0);
            out.push(if phase < 0.5 { x[i] } else { up[i] });
        }
        x = out;
    }

    // --- harmonizer: parallel detuned chord of vocoded layers, root layer
    // micro-detuned, weights falling 0.85 per layer, RMS-normalized by
    // sqrt(layer count).
    let gharm_raw = params.get("gharm").map(String::as_str).unwrap_or("0");
    let ivs = gharm_intervals(gharm_raw);

    let mut y = vec![0.0f32; x.len()];
    let mut weight = 1.0f64;
    for (j, &iv) in ivs.iter().enumerate() {
        let mut layer = vocode(&x, st_g + iv);
        if j == 0 {
            let up = vocode(&x, st_g + iv + 0.15);
            let down = vocode(&x, st_g + iv - 0.15);
            // All three are `vocode(&x, ..)` calls on the same `x`, so
            // all three are exactly `x.len()` long (vocode's own
            // invariant) — the elementwise combine below never needs a
            // length reconciliation the way `np` would need to.
            for i in 0..layer.len() {
                layer[i] = 0.6 * layer[i] + 0.2 * up[i] + 0.2 * down[i];
            }
        }
        let wf = weight as f32;
        for i in 0..layer.len() {
            y[i] += wf * layer[i];
        }
        weight *= 0.85;
    }
    let norm = (ivs.len().max(1) as f64).sqrt() as f32;
    for v in y.iter_mut() {
        *v /= norm;
    }

    // --- coating: hp600 -> lp7800 -> bitcrush10 -> tanh(2.4)-normalized.
    let mut y = sweep_filter(&y, 600.0, 600.0, "high", 4, 256);
    y = sweep_filter(&y, 7800.0, 7800.0, "low", 4, 256);
    y = bitcrush(&y, Some(10.0), None);
    let tanh_norm = 2.4f64.tanh() as f32;
    for v in y.iter_mut() {
        *v = (*v * 2.4).tanh() / tanh_norm;
    }

    // --- pump: beat-synced sidechain-style amplitude duck.
    let pump = params
        .get("pump")
        .and_then(|s| s.parse::<f64>().ok())
        .unwrap_or(0.0);
    if pump > 0.0 {
        let pump = pump as f32;
        for (i, v) in y.iter_mut().enumerate() {
            let t = i as f32 / SR_F;
            let ph = (t * pump).rem_euclid(1.0);
            let env = 0.45f32 + 0.55f32 * (-3.5f32 * ph).exp();
            *v *= env;
        }
    }

    y
}

/// The interaural-delay width treatment from the render call site
/// (`mus_audio.py` lines 1108-1112): delay the right channel by `d =
/// int(ms * SR / 1000.0)` samples — `d` zeros prepended, the last `d`
/// samples dropped, buffer length unchanged — only when `0 < d <
/// len(right)`. `ms` is `float(ev.params["haas"])`, a plain Python float
/// in the oracle, hence `f64` here.
///
/// `int()` truncates toward zero; `.trunc()` rather than `.floor()`
/// matches that exactly (the two disagree only for a negative `ms`, which
/// the `0 < d` guard already routes to a no-op either way). A `d` past
/// `usize`'s range from a pathological `ms` saturates on the `as usize`
/// cast rather than panicking or wrapping (Rust's float-to-int cast has
/// saturated on out-of-range input since Rust 1.45), and a saturated `d`
/// still fails the `d < len` guard below, so it's still a no-op.
pub fn haas(right: &mut Vec<f32>, ms: f64) {
    let d = (ms * SR_F64 / 1000.0).trunc();
    if d <= 0.0 {
        return;
    }
    let d = d as usize;
    let n = right.len();
    if d >= n {
        return;
    }
    let mut shifted = vec![0.0f32; n];
    shifted[d..].copy_from_slice(&right[..n - d]);
    *right = shifted;
}

/// The note-shaping amplitude envelope from the render call site
/// (`mus_audio.py` lines 1066-1073): a `linspace(0,1)**0.7` attack ramp
/// and a `linspace(1,0)**1.5` release ramp, each clamped so neither can
/// exceed a third (attack) or half (release) of the buffer — independent
/// clamps, not a shared budget, matching the oracle's own two separate
/// `min()` calls — and each applied only when its clamped sample count is
/// `> 1` (a count of `0` or `1` is `x[:0]`/`x[:1]`-style no-op territory
/// in Python; a `linspace(_, _, 1)` ramp would be a single point with no
/// shape to multiply in anyway).
///
/// `atk_s`/`rel_s` are the caller's already-resolved `atk`/`rel` seconds
/// (`float(ev.params.get("atk", 0.003))` / `.get("rel", 0.035)` in the
/// oracle) — plain `f64`, matching the Python floats the oracle's own
/// `max(0.0015, ..)` / `max(0.004, ..)` floor operates on before the
/// `* SR` -> `int()` truncation.
///
/// Ramp values are `linspace`'s native `f64` (numpy's default-dtype
/// `linspace`, matching the oracle exactly — no `dtype=` override at
/// either call site), and the in-place `x[:atk] *= ramp` multiply is
/// truncated to `f32` once per sample on store: `float32_array *=
/// float64_array` promotes for the multiply and casts once, the same
/// promote-then-truncate-on-store rule documented in detail on
/// `pitch::phase_vocoder`'s `phase_acc` accumulation, applied here to a
/// plain elementwise multiply instead of an FFT accumulator.
pub fn event_envelope(x: &mut [f32], atk_s: f64, rel_s: f64) {
    let len = x.len();
    let atk = (atk_s.max(0.0015) * SR_F64).trunc() as usize;
    let rel = (rel_s.max(0.004) * SR_F64).trunc() as usize;
    let atk = atk.min(len / 3);
    let rel = rel.min(len / 2);

    if atk > 1 {
        let ramp = linspace(0.0, 1.0, atk);
        for i in 0..atk {
            let g = ramp[i].powf(0.7);
            x[i] = ((x[i] as f64) * g) as f32;
        }
    }
    if rel > 1 {
        let ramp = linspace(1.0, 0.0, rel);
        let start = len - rel;
        for i in 0..rel {
            let g = ramp[i].powf(1.5);
            x[start + i] = ((x[start + i] as f64) * g) as f32;
        }
    }
}
