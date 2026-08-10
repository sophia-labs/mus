//! Pure per-event kernels: ports of the hand-rolled numpy transforms in
//! `mus_audio.py` (lines 298–415 and the limiter helpers). Everything here
//! is `max_abs`-tier parity — same arithmetic, f32 in, f32 out.
//!
//! Implemented as keystone exemplars: [`ring_mod`], [`soft_clip`],
//! [`hard_clip`]. The remaining kernels (bitcrush, stutter, chop_shuffle,
//! duck_envelope, pan_stereo, maximum_filter1d) are WF2's stage and follow
//! the same pattern: mirror the numpy operation order, keep scalar math in
//! f64 where numpy holds a float64 scalar, cast where numpy casts.

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
