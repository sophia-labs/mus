//! Pure per-event kernels: ports of the hand-rolled numpy transforms in
//! `mus_audio.py` (lines 298–415 and the limiter helpers). Everything here
//! is `max_abs`-tier parity — same arithmetic, f32 in, f32 out.
//!
//! Implemented as keystone exemplars: [`ring_mod`], [`soft_clip`],
//! [`hard_clip`]. The rest — [`bitcrush`], [`stutter`], [`chop_shuffle`],
//! [`duck_envelope`], [`pan_stereo`], [`maximum_filter1d`], [`np_hanning`]
//! — are WF2's stage and follow the same pattern: mirror the numpy
//! operation order, keep scalar math in f64 where numpy holds a float64
//! scalar, cast where numpy casts.

/// `mus_audio.ring_mod` (line 320): multiply by a sine carrier —
/// inharmonic sidebands, the classic weird-ifier.
pub fn ring_mod(x: &[f32], f_hz: f32, wet: f32) -> Vec<f32> {
    let w = 2.0 * std::f64::consts::PI * f_hz as f64 / crate::SR_F64;
    x.iter()
        .enumerate()
        .map(|(i, &v)| {
            let car = (w * i as f64).sin() as f32;
            (1.0 - wet) * v + wet * v * car
        })
        .collect()
}

/// `mus_audio.soft_clip` (line 439): `tanh(x*drive)/tanh(drive)`, identity
/// below drive 1.001.
pub fn soft_clip(x: &[f32], drive: f32) -> Vec<f32> {
    if drive <= 1.001 {
        return x.to_vec();
    }
    let norm = (drive as f64).tanh();
    x.iter()
        .map(|&v| ((v * drive).tanh() as f64 / norm) as f32)
        .collect()
}

/// `mus_audio.hard_clip` (line 340): scale to `amount` times over the peak,
/// clip at ±1, scale back. "tanh is polite; this is the other thing."
pub fn hard_clip(x: &[f32], amount: f32) -> Vec<f32> {
    if amount <= 1.0 {
        return x.to_vec();
    }
    let pk = x.iter().fold(0.0f32, |m, &v| m.max(v.abs())) + 1e-9;
    x.iter()
        .map(|&v| (v * amount / pk).clamp(-1.0, 1.0) * pk)
        .collect()
}

/// numpy `np.linspace(start, stop, num)` (`endpoint=True`, the only mode
/// used anywhere in `mus_audio.py`). numpy computes this internally at
/// float64 regardless of a requested output `dtype` — `_core/
/// function_base.py`'s `linspace` derives its working dtype from `start`/
/// `stop` (always float64 here, since every call site passes plain Python
/// floats), builds `y[i] = i*step + start` with `step = (stop-start)/
/// (num-1)`, force-sets the last element to exactly `stop` (numpy's
/// endpoint-exactness fixup), and only casts to a narrower `dtype` — if
/// asked for one — as the very last step. Callers here do that narrowing
/// themselves at whatever point the Python does (see [`chop_shuffle`] vs
/// [`stutter`] for the two different points it happens at). Degenerate
/// `num` matches numpy (`0` empty, `1` == `[start]`); the `step == 0`
/// denormal special-case in numpy's implementation is not reproduced —
/// it's unreachable for the ramp lengths (fade samples, pan samples) this
/// is used for.
fn np_linspace_f64(start: f64, stop: f64, num: usize) -> Vec<f64> {
    match num {
        0 => Vec::new(),
        1 => vec![start],
        _ => {
            let div = (num - 1) as f64;
            let step = (stop - start) / div;
            let mut y: Vec<f64> = (0..num).map(|i| i as f64 * step + start).collect();
            y[num - 1] = stop;
            y
        }
    }
}

/// `mus_audio.bitcrush` (line 389): amplitude quantise then sample-and-
/// hold decimate; either stage may be skipped (`if bits:` / `if decim:`
/// are Python truthiness — `None` *or* a numeric `0` both skip).
///
/// The quantise stage multiplies/divides the f32 array by a Python-float
/// scalar (`levels / 2`); verified against numpy directly (not just
/// inferred from the numeric-discipline note): `f32_array * python_float`
/// rounds the *scalar* down to f32 once and does the whole op at f32
/// precision — it does not widen the array to f64 and round once at the
/// end. So `half` is rounded to f32 up front and every sample stays in
/// f32 arithmetic from there, matching numpy bit-for-bit rather than just
/// within tolerance. `np.round` is round-half-to-even → `round_ties_even`.
pub fn bitcrush(x: &[f32], bits: Option<f64>, decim: Option<u32>) -> Vec<f32> {
    let mut y = x.to_vec();
    if let Some(b) = bits {
        if b != 0.0 {
            let levels = (2.0f64).powf(b).max(2.0);
            let half = (levels / 2.0) as f32;
            for v in y.iter_mut() {
                *v = (*v * half).round_ties_even() / half;
            }
        }
    }
    if let Some(d) = decim {
        if d > 1 {
            let d = d as usize;
            let len = y.len();
            let n = (len / d) * d;
            if n >= d {
                let mut held = Vec::with_capacity(len);
                let mut i = 0;
                while i < n {
                    held.extend(std::iter::repeat_n(y[i], d));
                    i += d;
                }
                held.extend_from_slice(&y[n..]);
                held.truncate(len);
                y = held;
            }
        }
    }
    y
}

/// `mus_audio.stutter` (line 411): retrigger the first slice of a sample
/// `n` times, with 4 ms fades on the (single, pre-tiling) piece so the
/// loop point doesn't click. The Python slice `x[:seg]` clips to `len(x)`
/// rather than panicking when `x` is shorter than `seg`; mirrored here by
/// clamping before slicing. The fade ramp is numpy's *default-dtype*
/// `linspace` (float64, no `dtype=` kwarg) multiplied in place into the f32
/// `piece` — here the *array* (not a weak scalar) carries the f64
/// precision, so the product really is computed at f64 and rounded to f32
/// once on store, unlike the scalar case in [`bitcrush`].
pub fn stutter(x: &[f32], n: usize, slot_samples: usize) -> Vec<f32> {
    if n < 2 || slot_samples < 64 {
        return x.to_vec();
    }
    let seg = (slot_samples / n).max(64);
    let plen = seg.min(x.len());
    let mut piece = x[..plen].to_vec();
    let f = ((0.004_f64 * crate::SR_F64).trunc() as usize).min(plen / 4);
    if f > 1 {
        let up = np_linspace_f64(0.0, 1.0, f);
        let down = np_linspace_f64(1.0, 0.0, f);
        for i in 0..f {
            piece[i] = (piece[i] as f64 * up[i]) as f32;
        }
        for (i, &gain) in down[..f].iter().enumerate() {
            let idx = plen - f + i;
            piece[idx] = (piece[idx] as f64 * gain) as f32;
        }
    }
    let mut out = Vec::with_capacity(plen * n);
    for _ in 0..n {
        out.extend_from_slice(&piece);
    }
    out
}

/// `mus_audio.chop_shuffle` (line 298): deterministic granular resequence
/// — cut `x` into `n_grains` grains, deal evens then odds, reverse every
/// 4th dealt grain. Grain boundaries `x[i*seg:(i+1)*seg]` clip to `len(x)`
/// the way Python slicing does rather than panicking, so with a short `x`
/// and `seg` clamped up to its 64-sample floor, trailing grains may be
/// short or (past the end) empty. Fades use `np.linspace(...,
/// dtype=np.float32)` — the dtype is forced *inside* `linspace` (still
/// computed at f64 internally, per [`np_linspace_f64`]'s doc, just cast to
/// f32 immediately after instead of at the eventual multiply-assign), so
/// unlike [`stutter`]'s fade this multiply is genuine f32-times-f32, not
/// an f64 product rounded once at the end. A grain shorter than the fade
/// length `f` — only reachable via the short/empty-grain path above — is
/// left unfaded rather than following numpy into a shape-mismatch error:
/// the instruction to not panic on the short-slice case is extended to
/// the fade that reads it, since Rust has no broadcasting to fall back on.
pub fn chop_shuffle(x: &[f32], n_grains: usize, slot_samples: usize) -> Vec<f32> {
    let n_grains = n_grains.clamp(2, 64);
    let seg = (x.len() / n_grains).max(64);
    let grains: Vec<Vec<f32>> = (0..n_grains)
        .map(|i| {
            let a = (i * seg).min(x.len());
            let b = ((i + 1) * seg).min(x.len());
            x[a..b].to_vec()
        })
        .collect();
    let order = (0..n_grains).step_by(2).chain((1..n_grains).step_by(2));
    let f = ((0.004_f64 * crate::SR_F64).trunc() as usize).min(seg / 4);
    let mut outs: Vec<f32> = Vec::new();
    for (j, gi) in order.enumerate() {
        let mut g = grains[gi].clone();
        if j % 4 == 3 {
            g.reverse();
        }
        if f > 1 && g.len() >= f {
            let up: Vec<f32> = np_linspace_f64(0.0, 1.0, f)
                .into_iter()
                .map(|v| v as f32)
                .collect();
            let down: Vec<f32> = np_linspace_f64(1.0, 0.0, f)
                .into_iter()
                .map(|v| v as f32)
                .collect();
            for i in 0..f {
                g[i] *= up[i];
            }
            let glen = g.len();
            for i in 0..f {
                g[glen - f + i] *= down[i];
            }
        }
        outs.extend_from_slice(&g);
    }
    let cap = slot_samples.max(seg);
    if outs.len() > cap {
        outs.truncate(cap);
    }
    outs
}

/// `mus_audio.duck_envelope` (line 425): sidechain gain curve derived from
/// known note onsets — a hard floor for `hold` samples, then an
/// exponential recovery, folded across onsets with `min` so overlapping
/// ducks deepen instead of fighting.
///
/// The recovery `shape` is `1.0 - depth*exp(-arange(rel)/(rel/4.0))`:
/// `np.arange(rel)` defaults to an int64 array, and an int array divided
/// by a Python float scalar promotes to float64 (verified directly —
/// unlike a float32-array-times-scalar, there's no dtype for the scalar to
/// "round down to" that the int array could already hold), so `shape` is
/// genuine float64 end to end. The final fold, `np.minimum(f32_slice,
/// shape_f64_slice)`, is array-vs-array with two *different* real dtypes
/// (not a weak scalar), which numpy promotes to the wider one (f64) for
/// the comparison and then truncates back to f32 on assignment into `g`.
/// Onset sample index is `int(o*SR)` — truncation toward zero.
pub fn duck_envelope(onsets: &[f64], n: usize, depth: f64, release: f64, hold: f64) -> Vec<f32> {
    let mut g = vec![1.0f32; n];
    let rel = (((release * crate::SR_F64).trunc()) as i64).max(32) as usize;
    let shape: Vec<f64> = (0..rel)
        .map(|t| 1.0 - depth * (-(t as f64) / (rel as f64 / 4.0)).exp())
        .collect();
    let hd_raw = (hold * crate::SR_F64).trunc();
    let hd = if hd_raw > 0.0 { hd_raw as usize } else { 0 };
    let floor = (1.0 - depth) as f32;
    for &o in onsets {
        let sf = (o * crate::SR_F64).trunc();
        if sf < 0.0 {
            continue;
        }
        let s = sf as usize;
        if s >= n {
            continue;
        }
        if hd > 0 {
            let end = n.min(s + hd);
            for gi in g.iter_mut().take(end).skip(s) {
                *gi = gi.min(floor);
            }
        }
        let a = n.min(s + hd);
        let b = n.min(a + rel);
        if b > a {
            for i in a..b {
                g[i] = (g[i] as f64).min(shape[i - a]) as f32;
            }
        }
    }
    g
}

/// `mus_audio.pan_stereo` (line 473): equal-power pan. `p0`/`p1` are the
/// plain Python-float scalars the caller passes, so they're kept at f64
/// up to the point numpy itself casts: the constant branch (`|p0-p1| <
/// 1e-6`) casts `p0` straight to f32 (`dtype=np.float32`); the sweep
/// branch runs [`np_linspace_f64`] and only casts the whole ramp down
/// afterward (`.astype(np.float32)`). From there `theta = (clip(p,-1,1) +
/// 1) * (pi/4)` runs entirely in f32 — `p` is now a real f32 array, and
/// clip/`+1`/`*(pi/4)` are all f32-array-op-weak-scalar, which rounds each
/// scalar down to f32 once rather than promoting the array back to f64
/// (same rule verified for [`bitcrush`]). `cos`/`sin` then run at f32.
pub fn pan_stereo(x: &[f32], p0: f64, p1: f64) -> (Vec<f32>, Vec<f32>) {
    let n = x.len();
    let p: Vec<f32> = if (p0 - p1).abs() < 1e-6 {
        vec![p0 as f32; n]
    } else {
        np_linspace_f64(p0, p1, n)
            .into_iter()
            .map(|v| v as f32)
            .collect()
    };
    let quarter_pi = (std::f64::consts::PI / 4.0) as f32;
    let mut l = Vec::with_capacity(n);
    let mut r = Vec::with_capacity(n);
    for i in 0..n {
        let theta = (p[i].clamp(-1.0, 1.0) + 1.0) * quarter_pi;
        l.push(x[i] * theta.cos());
        r.push(x[i] * theta.sin());
    }
    (l, r)
}

/// `scipy.ndimage.maximum_filter1d` (`mus_audio.py` lines 514/518, inside
/// `master`'s look-ahead limiter). Sliding max over a centered window
/// (`origin=0`): output index `i` covers input indices `[i - size//2, i +
/// (size-1)//2]`. Boundary mode is scipy's `"reflect"` (confusingly, this
/// is numpy's `"symmetric"` — the edge sample repeats: `d c b a | a b c d
/// | d c b a`), applied by reflecting out-of-range indices back in:
/// `j < 0 -> -j - 1`, `j >= n -> 2*n - 1 - j` (iterated in case a window
/// wider than `n` needs more than one bounce). Verified against scipy's
/// own docstring example (`maximum_filter1d([2,8,0,4,1,9,9,0], size=3) ==
/// [8,8,8,4,9,9,9,9]`) by hand before trusting the formula.
pub fn maximum_filter1d(x: &[f32], size: usize) -> Vec<f32> {
    let n = x.len();
    if n == 0 || size == 0 {
        return x.to_vec();
    }
    let left = (size / 2) as i64;
    let right = (size.saturating_sub(1) / 2) as i64;
    let n_i = n as i64;
    let reflect = |mut j: i64| -> usize {
        while j < 0 || j >= n_i {
            if j < 0 {
                j = -j - 1;
            }
            if j >= n_i {
                j = 2 * n_i - 1 - j;
            }
        }
        j as usize
    };
    (0..n)
        .map(|i| {
            let ii = i as i64;
            let mut m = f32::NEG_INFINITY;
            for j in (ii - left)..=(ii + right) {
                let v = x[reflect(j)];
                if v > m {
                    m = v;
                }
            }
            m
        })
        .collect()
}

/// numpy `np.hanning(M)`, used at `mus_audio.py` line 520
/// (`np.hanning(int(0.03*SR) | 1)`) to build the limiter's smoothing
/// window. Ported bit-for-bit from numpy's actual implementation
/// (`numpy/lib/_function_base_impl.py::hanning`), *not* the textbook
/// `0.5 - 0.5*cos(2*pi*k/(M-1))` form most references quote: numpy first
/// builds the odd-symmetric integer ramp `n = arange(1-M, M, 2)` (exact
/// integer arithmetic — one value per output sample, no float division
/// involved yet) and only then evaluates `0.5 + 0.5*cos(pi*n/(M-1))` in
/// f64. The two forms are algebraically identical but *not* bit-identical
/// — reassociating the `cos` argument changes its rounding — so the
/// textbook form (used by an earlier version of this port) silently
/// diverges from numpy by up to ~2000 ULP at `M=1440`, the scale
/// `mus_audio.py`'s own limiter window runs at. Bit-for-bit agreement with
/// this formula (0 ULP) was checked directly against `np.hanning` for
/// `M in {0, -3, 1, 2, 4, 5, 12, 13, 1440, 1441}` — the last two bracket
/// the real window size — before trusting it. `M < 1` returns empty and
/// `M == 1` returns `[1.0]` — numpy's explicit special cases, since the
/// formula's `M - 1` divides by zero at `M == 1`.
pub fn np_hanning(m: i64) -> Vec<f64> {
    if m < 1 {
        return Vec::new();
    }
    if m == 1 {
        return vec![1.0];
    }
    let mm1 = (m - 1) as f64;
    (0..m)
        .map(|k| {
            let n = (1 - m) + 2 * k;
            0.5 + 0.5 * (std::f64::consts::PI * n as f64 / mm1).cos()
        })
        .collect()
}
