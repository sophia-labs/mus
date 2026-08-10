//! scipy-parity IIR filtering: Butterworth design to second-order sections,
//! `sosfilt`, `sosfilt_zi`, and the block-interpolated [`sweep_filter`] of
//! `mus_audio.py` line 385.
//!
//! Owned by stage WF3. Oracle cases: `sos_butter*` (coefficient tables,
//! f64, `max_abs 1e-10`), `sosfilt_low_noise`, `sosfilt_zi_low_1200`,
//! `sweep_static_low`, `sweep_low_fall`, `sweep_high_rise`.
//!
//! `butter_sos`/`sosfilt`/`sosfilt_zi` aren't `mus_audio.py` functions —
//! `mus_audio.py` calls straight into `scipy.signal.{butter,sosfilt,
//! sosfilt_zi}`, so the oracle for this trio is scipy's own source
//! (`_filter_design.py`: `buttap` → pre-warp → `lp2lp_zpk`/`lp2hp_zpk` →
//! `bilinear_zpk` → `zpk2sos`; `_signaltools.py`: `lfilter_zi`,
//! `sosfilt_zi`, and the direct-form-II-transposed `_sosfilt` kernel).
//! `sweep_filter` ports `mus_audio.py` itself, built on the three above.

// ---------------------------------------------------------------- complex
//
// scipy's filter design pipeline is small-degree complex arithmetic
// (Butterworth poles, zpk↔sos). Order stays low (2 or 4 in every call
// site), so a minimal local complex type is cheaper and more legible than
// pulling in a new crate dependency for this one file.

#[derive(Clone, Copy, Debug, PartialEq)]
struct Cx {
    re: f64,
    im: f64,
}

impl Cx {
    const ZERO: Cx = Cx { re: 0.0, im: 0.0 };

    fn new(re: f64, im: f64) -> Self {
        Cx { re, im }
    }

    /// A real value lifted into ℂ (imaginary part exactly 0.0).
    fn re(re: f64) -> Self {
        Cx { re, im: 0.0 }
    }

    fn conj(self) -> Self {
        Cx::new(self.re, -self.im)
    }

    fn abs(self) -> f64 {
        self.re.hypot(self.im)
    }

    /// `np.isreal`: exactly zero imaginary part. Only meaningful for
    /// values that have already passed through [`cplxreal`], which forces
    /// real entries to exactly `im == 0.0`.
    fn is_real(self) -> bool {
        self.im == 0.0
    }
}

impl std::ops::Add for Cx {
    type Output = Cx;
    fn add(self, o: Cx) -> Cx {
        Cx::new(self.re + o.re, self.im + o.im)
    }
}

impl std::ops::Sub for Cx {
    type Output = Cx;
    fn sub(self, o: Cx) -> Cx {
        Cx::new(self.re - o.re, self.im - o.im)
    }
}

impl std::ops::Neg for Cx {
    type Output = Cx;
    fn neg(self) -> Cx {
        Cx::new(-self.re, -self.im)
    }
}

impl std::ops::Mul for Cx {
    type Output = Cx;
    fn mul(self, o: Cx) -> Cx {
        Cx::new(
            self.re * o.re - self.im * o.im,
            self.re * o.im + self.im * o.re,
        )
    }
}

impl std::ops::Mul<f64> for Cx {
    type Output = Cx;
    fn mul(self, s: f64) -> Cx {
        Cx::new(self.re * s, self.im * s)
    }
}

impl std::ops::Div for Cx {
    type Output = Cx;
    fn div(self, o: Cx) -> Cx {
        let d = o.re * o.re + o.im * o.im;
        Cx::new(
            (self.re * o.re + self.im * o.im) / d,
            (self.im * o.re - self.re * o.im) / d,
        )
    }
}

fn prod(vals: &[Cx]) -> Cx {
    vals.iter().fold(Cx::re(1.0), |acc, &v| acc * v)
}

// ------------------------------------------------------- analog prototype

/// `scipy.signal.buttap` (`_filter_design.py`): zeros/poles/gain of the
/// analog-prototype order-`n` Butterworth filter, unity cutoff. Zeros: none
/// (returned as an empty vec, matching scipy). Poles:
/// `p_m = -exp(iπm/2n)` for `m = -n+1, -n+3, …, n-1`. Gain: 1.
fn buttap(n: usize) -> (Vec<Cx>, Vec<Cx>, f64) {
    let nf = n as f64;
    let mut poles = Vec::with_capacity(n);
    let mut m = -(n as i64) + 1;
    while m <= n as i64 - 1 {
        let theta = std::f64::consts::PI * (m as f64) / (2.0 * nf);
        poles.push(-Cx::new(theta.cos(), theta.sin()));
        m += 2;
    }
    (Vec::new(), poles, 1.0)
}

/// `lp2lp_zpk`: analog lowpass-to-lowpass frequency scale, `s → s/wo`.
fn lp2lp_zpk(z: &[Cx], p: &[Cx], k: f64, wo: f64) -> (Vec<Cx>, Vec<Cx>, f64) {
    let degree = p.len() as i32 - z.len() as i32;
    debug_assert!(degree >= 0, "improper transfer function");
    let z2: Vec<Cx> = z.iter().map(|&v| v * wo).collect();
    let p2: Vec<Cx> = p.iter().map(|&v| v * wo).collect();
    (z2, p2, k * wo.powi(degree))
}

/// `lp2hp_zpk`: analog lowpass-to-highpass, `s → wo/s`. Zeros at infinity
/// (the `degree` gap between pole and zero counts) move to the origin.
fn lp2hp_zpk(z: &[Cx], p: &[Cx], k: f64, wo: f64) -> (Vec<Cx>, Vec<Cx>, f64) {
    let degree = p.len() as i32 - z.len() as i32;
    debug_assert!(degree >= 0, "improper transfer function");
    let mut z2: Vec<Cx> = z.iter().map(|&v| Cx::re(wo) / v).collect();
    z2.resize(z2.len() + degree as usize, Cx::ZERO);
    let p2: Vec<Cx> = p.iter().map(|&v| Cx::re(wo) / v).collect();
    let neg_z: Vec<Cx> = z.iter().map(|&v| -v).collect();
    let neg_p: Vec<Cx> = p.iter().map(|&v| -v).collect();
    let k2 = k * (prod(&neg_z) / prod(&neg_p)).re;
    (z2, p2, k2)
}

/// `bilinear_zpk(z, p, k, fs)`: Tustin's transform, `s → fs2·(z-1)/(z+1)`
/// inverted to map analog zpk onto the digital unit circle. Zeros at
/// infinity (the `degree` gap) move to Nyquist (`z = -1`).
fn bilinear_zpk(z: &[Cx], p: &[Cx], k: f64, fs: f64) -> (Vec<Cx>, Vec<Cx>, f64) {
    let degree = p.len() as i32 - z.len() as i32;
    debug_assert!(degree >= 0, "improper transfer function");
    let fs2 = 2.0 * fs;
    let mut z2: Vec<Cx> = z
        .iter()
        .map(|&v| (Cx::re(fs2) + v) / (Cx::re(fs2) - v))
        .collect();
    let p2: Vec<Cx> = p
        .iter()
        .map(|&v| (Cx::re(fs2) + v) / (Cx::re(fs2) - v))
        .collect();
    for _ in 0..degree {
        z2.push(Cx::re(-1.0));
    }
    let num: Vec<Cx> = z.iter().map(|&v| Cx::re(fs2) - v).collect();
    let den: Vec<Cx> = p.iter().map(|&v| Cx::re(fs2) - v).collect();
    let k2 = k * (prod(&num) / prod(&den)).re;
    (z2, p2, k2)
}

// ------------------------------------------------------------- zpk → sos

/// `_cplxreal` (`_filter_design.py`): split a value list into real entries
/// (`zr`, exact-real-cast) and complex-conjugate pairs (`zc`, one
/// positive-imaginary representative per pair, averaged from the pair for
/// precision). Sorted by real part, then by `|imag|`, matching scipy's
/// `lexsort((abs(imag), real))`.
fn cplxreal(vals: &[Cx]) -> (Vec<Cx>, Vec<f64>) {
    if vals.is_empty() {
        return (Vec::new(), Vec::new());
    }
    let tol = 100.0 * f64::EPSILON;

    let mut order: Vec<usize> = (0..vals.len()).collect();
    order.sort_by(|&a, &b| {
        vals[a]
            .re
            .partial_cmp(&vals[b].re)
            .unwrap()
            .then_with(|| vals[a].im.abs().partial_cmp(&vals[b].im.abs()).unwrap())
    });
    let z: Vec<Cx> = order.iter().map(|&i| vals[i]).collect();

    let is_real: Vec<bool> = z.iter().map(|v| v.im.abs() <= tol * v.abs()).collect();
    let zr: Vec<f64> = z
        .iter()
        .zip(&is_real)
        .filter(|(_, &r)| r)
        .map(|(v, _)| v.re)
        .collect();
    if zr.len() == z.len() {
        return (Vec::new(), zr);
    }

    let zc_all: Vec<Cx> = z
        .iter()
        .zip(&is_real)
        .filter(|(_, &r)| !r)
        .map(|(&v, _)| v)
        .collect();
    let mut zp: Vec<Cx> = zc_all.iter().copied().filter(|v| v.im > 0.0).collect();
    let mut zn: Vec<Cx> = zc_all.iter().copied().filter(|v| v.im < 0.0).collect();
    assert_eq!(
        zp.len(),
        zn.len(),
        "cplxreal: complex value with no matching conjugate"
    );

    // Runs of (nearly) equal real part: sort each run's positive- and
    // negative-imaginary halves by |imag| so zp[i] pairs with zn[i].
    if zp.len() > 1 {
        let sort_chunk =
            |c: &mut [Cx]| c.sort_by(|a, b| a.im.abs().partial_cmp(&b.im.abs()).unwrap());
        let mut i = 0usize;
        while i < zp.len() - 1 {
            if (zp[i + 1].re - zp[i].re) <= tol * zp[i].abs() {
                let start = i;
                while i < zp.len() - 1 && (zp[i + 1].re - zp[i].re) <= tol * zp[i].abs() {
                    i += 1;
                }
                sort_chunk(&mut zp[start..=i]);
                sort_chunk(&mut zn[start..=i]);
            }
            i += 1;
        }
    }

    for (&p, &n) in zp.iter().zip(zn.iter()) {
        assert!(
            (p - n.conj()).abs() <= tol * n.abs(),
            "cplxreal: complex value with no matching conjugate"
        );
    }
    let zc: Vec<Cx> = zp
        .iter()
        .zip(zn.iter())
        .map(|(&p, &n)| Cx::new((p.re + n.re) / 2.0, (p.im - n.im) / 2.0))
        .collect();
    (zc, zr)
}

#[derive(Clone, Copy, PartialEq)]
enum Which {
    Real,
    Complex,
    Any,
}

/// `_nearest_real_complex_idx`: index into `fro` of the element closest to
/// `to`, optionally constrained to real or complex entries.
fn nearest_real_complex_idx(fro: &[Cx], to: Cx, which: Which) -> usize {
    let mut order: Vec<usize> = (0..fro.len()).collect();
    order.sort_by(|&a, &b| {
        (fro[a] - to)
            .abs()
            .partial_cmp(&(fro[b] - to).abs())
            .unwrap()
    });
    match which {
        Which::Any => order[0],
        Which::Real => *order.iter().find(|&&i| fro[i].is_real()).unwrap(),
        Which::Complex => *order.iter().find(|&&i| !fro[i].is_real()).unwrap(),
    }
}

/// `np.poly`: monic polynomial coefficients (highest degree first) with
/// the given roots, built the same way numpy does — sequential full
/// convolution with `[1, -root]`. `_single_zpksos`/`zpk2tf` always assign
/// the result into a real `sos` row, which truncates to the real part
/// regardless of scipy's own conjugate-set realness check, so this returns
/// ℂ and callers take `.re`.
fn poly_from_roots(roots: &[Cx]) -> Vec<Cx> {
    let mut a = vec![Cx::re(1.0)];
    for &r in roots {
        let mut next = vec![Cx::ZERO; a.len() + 1];
        for (i, &ai) in a.iter().enumerate() {
            next[i] = next[i] + ai;
            next[i + 1] = next[i + 1] + ai * (-r);
        }
        a = next;
    }
    a
}

/// `_single_zpksos`: one second-order section (up to two zeros, up to two
/// poles), right-aligned into the six-slot `[b0 b1 b2 a0 a1 a2]` row.
fn single_zpksos(z: &[Cx], p: &[Cx], k: f64) -> [f64; 6] {
    let b = poly_from_roots(z);
    let a = poly_from_roots(p);
    let mut sos = [0.0f64; 6];
    for (i, c) in b.iter().enumerate() {
        sos[3 - b.len() + i] = (*c * k).re;
    }
    for (i, c) in a.iter().enumerate() {
        sos[6 - a.len() + i] = c.re;
    }
    sos
}

/// `zpk2sos(z, p, k, pairing='nearest', analog=False)`: the only pairing
/// mode/`analog` value `mus_audio.py`'s filters ever need. Ports the
/// "worst pole first, nearest zero" algorithm verbatim, including the two
/// odd-order special cases — see `_filter_design.py::zpk2sos` for the
/// prose walkthrough this mirrors line-for-line.
fn zpk2sos_nearest(z_in: &[Cx], p_in: &[Cx], k: f64) -> Vec<[f64; 6]> {
    if z_in.is_empty() && p_in.is_empty() {
        return vec![[k, 0.0, 0.0, 1.0, 0.0, 0.0]];
    }

    let target = z_in.len().max(p_in.len());
    let mut p: Vec<Cx> = p_in.to_vec();
    let mut z: Vec<Cx> = z_in.to_vec();
    p.resize(target, Cx::ZERO);
    z.resize(target, Cx::ZERO);
    let n_sections = (target + 1) / 2;
    if p.len() % 2 == 1 {
        p.push(Cx::ZERO);
        z.push(Cx::ZERO);
    }
    assert_eq!(p.len(), z.len());

    let (zc, zr) = cplxreal(&z);
    let (pc, pr) = cplxreal(&p);
    let mut z: Vec<Cx> = zc;
    z.extend(zr.into_iter().map(Cx::re));
    let mut p: Vec<Cx> = pc;
    p.extend(pr.into_iter().map(Cx::re));

    // Digital: "worst" pole is the one closest to the unit circle.
    fn idx_worst(p: &[Cx]) -> usize {
        let mut best = 0usize;
        let mut best_val = f64::INFINITY;
        for (i, v) in p.iter().enumerate() {
            let val = (1.0 - v.abs()).abs();
            if val < best_val {
                best_val = val;
                best = i;
            }
        }
        best
    }

    let mut sos = vec![[0.0f64; 6]; n_sections];

    for si in (0..n_sections).rev() {
        let p1_idx = idx_worst(&p);
        let p1 = p.remove(p1_idx);
        let p_real_count = p.iter().filter(|v| v.is_real()).count();
        let z_real_count = z.iter().filter(|v| v.is_real()).count();

        if p1.is_real() && p_real_count == 0 {
            // Last remaining real pole. scipy's `pairing != "minimal"` arm
            // (covers both "nearest" and "keep_odd") unconditionally
            // synthesizes a second zero/pole pair at the origin —
            // `_single_zpksos([z1, 0], [p1, 0], 1)`, no `len(z) > 0` guard —
            // so the section still spans two root slots per side. Mirrored
            // verbatim; for "nearest" specifically it's unreachable (the
            // padding above keeps the real-pole count even at every pickup,
            // so a pole is never the *sole* remaining real one), but this
            // stays byte-for-byte faithful to what scipy's branch does if it
            // ever were hit, rather than a plausible-looking lookalike.
            let z1_idx = nearest_real_complex_idx(&z, p1, Which::Real);
            let z1 = z.remove(z1_idx);
            sos[si] = single_zpksos(&[z1, Cx::ZERO], &[p1, Cx::ZERO], 1.0);
        } else if p.len() + 1 == z.len() && !p1.is_real() && p_real_count == 1 && z_real_count == 1
        {
            // One real pole and one real zero left, but an odd zero/pole
            // gap forces this complex pole to take a complex zero, so the
            // real zero survives for the final first-order section.
            let z1_idx = nearest_real_complex_idx(&z, p1, Which::Complex);
            let z1 = z.remove(z1_idx);
            sos[si] = single_zpksos(&[z1, z1.conj()], &[p1, p1.conj()], 1.0);
        } else {
            let p2 = if p1.is_real() {
                let real_idxs: Vec<usize> = p
                    .iter()
                    .enumerate()
                    .filter(|(_, v)| v.is_real())
                    .map(|(i, _)| i)
                    .collect();
                let sub: Vec<Cx> = real_idxs.iter().map(|&i| p[i]).collect();
                let local = idx_worst(&sub);
                p.remove(real_idxs[local])
            } else {
                p1.conj()
            };

            if !z.is_empty() {
                let z1_idx = nearest_real_complex_idx(&z, p1, Which::Any);
                let z1 = z.remove(z1_idx);
                if !z1.is_real() {
                    sos[si] = single_zpksos(&[z1, z1.conj()], &[p1, p2], 1.0);
                } else if !z.is_empty() {
                    let z2_idx = nearest_real_complex_idx(&z, p1, Which::Real);
                    let z2 = z.remove(z2_idx);
                    sos[si] = single_zpksos(&[z1, z2], &[p1, p2], 1.0);
                } else {
                    sos[si] = single_zpksos(&[z1], &[p1, p2], 1.0);
                }
            } else {
                sos[si] = single_zpksos(&[], &[p1, p2], 1.0);
            }
        }
    }
    debug_assert!(
        p.is_empty() && z.is_empty(),
        "zpk2sos: leftover poles/zeros"
    );

    sos[0][0] *= k;
    sos[0][1] *= k;
    sos[0][2] *= k;
    sos
}

// -------------------------------------------------------------- public API

/// `scipy.signal.butter(order, wn, btype=btype, output="sos")` for
/// `btype` in `{"low", "high"}` — the only two `mus_audio.py` ever
/// requests. `wn` is the normalized digital frequency scipy itself takes:
/// `0 < wn < 1`, `1` at Nyquist (i.e. `fc_hz / (SR/2)`).
///
/// Pipeline: `buttap` → pre-warp (`2·fs·tan(π·wn/fs)`, `fs=2`) →
/// `lp2lp_zpk`/`lp2hp_zpk` → `bilinear_zpk(fs=2)` → `zpk2sos` (pairing
/// `"nearest"`). Row order and pole/zero pairing match scipy exactly — see
/// `zpk2sos_nearest`.
pub fn butter_sos(order: usize, wn: f64, btype: &str) -> Vec<[f64; 6]> {
    let (z0, p0, k0) = buttap(order);
    let fs = 2.0f64;
    let warped = 2.0 * fs * (std::f64::consts::PI * wn / fs).tan();
    let (z1, p1, k1) = match btype {
        "low" => lp2lp_zpk(&z0, &p0, k0, warped),
        "high" => lp2hp_zpk(&z0, &p0, k0, warped),
        other => panic!("butter_sos: unsupported btype {other:?} (only \"low\"/\"high\")"),
    };
    let (z2, p2, k2) = bilinear_zpk(&z1, &p1, k1, fs);
    zpk2sos_nearest(&z2, &p2, k2)
}

/// `scipy.signal.sosfilt(sos, x, zi=zi)`: cascaded second-order sections,
/// direct-form II transposed per section. `zi = None` is zero state (and
/// scipy's `sosfilt` then returns just `y`; here it's still handed back
/// alongside the final state so callers that don't need it can discard
/// it, as [`sweep_filter`]'s static branch does).
///
/// Computed in f64 throughout — scipy upcasts (`sos` is always f64 here,
/// so `np.result_type(f64, x.dtype)` is f64 regardless of `x`), matching
/// `mus_audio.py`'s own `.astype(np.float32)` cast on the *output* only.
pub fn sosfilt(sos: &[[f64; 6]], x: &[f32], zi: Option<&[[f64; 2]]>) -> (Vec<f32>, Vec<[f64; 2]>) {
    let n_sections = sos.len();
    let mut state: Vec<[f64; 2]> = match zi {
        Some(z) => {
            debug_assert_eq!(
                z.len(),
                n_sections,
                "sosfilt: zi shape must match sos sections"
            );
            z.to_vec()
        }
        None => vec![[0.0; 2]; n_sections],
    };

    let mut y = Vec::with_capacity(x.len());
    for &xn in x {
        let mut xc = xn as f64;
        for (s, row) in sos.iter().enumerate() {
            let [b0, b1, b2, _a0, a1, a2] = *row;
            let x_new = b0 * xc + state[s][0];
            state[s][0] = b1 * xc - a1 * x_new + state[s][1];
            state[s][1] = b2 * xc - a2 * x_new;
            xc = x_new;
        }
        y.push(xc as f32);
    }
    (y, state)
}

/// `scipy.signal.sosfilt_zi(sos)`: steady-state initial conditions for the
/// step response, per section, with the cumulative DC-gain scale factor
/// (`H(1) = sum(b)/sum(a)`) carried across sections.
pub fn sosfilt_zi(sos: &[[f64; 6]]) -> Vec<[f64; 2]> {
    let mut out = Vec::with_capacity(sos.len());
    let mut scale = 1.0f64;
    for row in sos {
        let b = [row[0], row[1], row[2]];
        let a = [row[3], row[4], row[5]];
        let zi = lfilter_zi3(b, a);
        out.push([zi[0] * scale, zi[1] * scale]);
        scale *= (b[0] + b[1] + b[2]) / (a[0] + a[1] + a[2]);
    }
    out
}

/// `scipy.signal.lfilter_zi(b, a)` specialised to the length-3 `(b, a)` a
/// biquad section always has. Matches the closed-form scipy now uses:
/// `flip(cumsum(flip(b - y_inf·a)))[1:]`, which for length 3 reduces to
/// `[d1+d2, d2]` with `d = b - y_inf·a`.
fn lfilter_zi3(b: [f64; 3], a: [f64; 3]) -> [f64; 2] {
    let (b, a) = if a[0] != 1.0 {
        (
            [b[0] / a[0], b[1] / a[0], b[2] / a[0]],
            [1.0, a[1] / a[0], a[2] / a[0]],
        )
    } else {
        (b, a)
    };
    let y_inf = (b[0] + b[1] + b[2]) / (a[0] + a[1] + a[2]);
    let d = [
        b[0] - y_inf * a[0],
        b[1] - y_inf * a[1],
        b[2] - y_inf * a[2],
    ];
    [d[1] + d[2], d[2]]
}

/// `mus_audio.sweep_filter` (line 448): block-wise IIR with an
/// interpolated cutoff, filter state carried across coefficient updates.
///
/// Static path (`|f_start - f_end| < 1`): a single fresh `sosfilt` call,
/// zero state. Swept path: `block`-sample chunks, cutoff geometrically
/// interpolated at each block's *midpoint* fraction, a fresh `butter_sos`
/// per block — but `zi` is seeded once (`sosfilt_zi(first_block_sos) *
/// x[0]`) and then carried across blocks even as the sos changes under it.
/// That mismatch is the Python behavior; this ports it as-is.
pub fn sweep_filter(
    x: &[f32],
    f_start: f64,
    f_end: f64,
    btype: &str,
    order: usize,
    block: usize,
) -> Vec<f32> {
    let nyq = crate::SR_F64 / 2.0;
    let f_start = f_start.clamp(20.0, nyq * 0.97);
    let f_end = f_end.clamp(20.0, nyq * 0.97);

    if (f_start - f_end).abs() < 1.0 {
        let sos = butter_sos(order, f_start / nyq, btype);
        let (y, _zf) = sosfilt(&sos, x, None);
        return y;
    }

    let n = x.len();
    let mut out = vec![0.0f32; n];
    let mut zi: Option<Vec<[f64; 2]>> = None;
    let mut s = 0usize;
    while s < n {
        let e = (s + block).min(n);
        let frac = (s as f64 + (e - s) as f64 / 2.0) / (n.max(1) as f64);
        let f = (f_start.ln() + frac * (f_end.ln() - f_start.ln())).exp();
        let sos = butter_sos(order, f.clamp(20.0, nyq * 0.97) / nyq, btype);

        let block_zi = match &zi {
            Some(z) => z.clone(),
            None => {
                let x0 = x[s] as f64;
                sosfilt_zi(&sos)
                    .into_iter()
                    .map(|r| [r[0] * x0, r[1] * x0])
                    .collect()
            }
        };
        let (y, zf) = sosfilt(&sos, &x[s..e], Some(&block_zi));
        out[s..e].copy_from_slice(&y);
        zi = Some(zf);
        s = e;
    }
    out
}
