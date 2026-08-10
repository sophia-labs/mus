//! An extended Karplus-Strong plucked string — the engine's first
//! POST-PARITY original. No Python oracle exists for this module; the
//! governing law is the VST doctrine instead: deterministic (same note →
//! same bytes), content-keyed randomness (A7 — the noise burst is seeded
//! from the note's own content, never a global stream), declared behavior
//! (every knob below is a typed `mus-vocab` param), and invariant tests
//! (tuning, decay, spectra, boundedness) in place of golden vectors.
//!
//! The design is Jaffe–Smith extended KS with a guitarist's priorities:
//!
//! - **In tune everywhere.** Integer delay lines detune high notes badly
//!   (a 1kHz string at 48kHz has period 48: ±half-sample = ±18 cents).
//!   The loop runs integer delay + first-order ALLPASS fractional delay,
//!   with the damping filter's half-sample phase folded into the length
//!   budget — tuning error stays within a few cents across the neck.
//! - **`sus` is honest seconds.** Loop gain is derived from the requested
//!   T60 (`g_per_sample = 10^(-3 / (t60·SR))` applied per circulation),
//!   so `sus=2.5` decays 60 dB in 2.5s at any pitch.
//! - **`damp` shapes how brightness dies.** The loop's one-zero lowpass
//!   `y = (1-d)·x[n] + d·x[n-1]`: strings lose highs faster than lows,
//!   and `d` is how much faster.
//! - **`pos` is where you pick.** The excitation is comb-filtered at the
//!   pick position (`e[n] -= e[n - pos·P]`) — the bridge-vs-neck sound,
//!   physically: harmonics with a node at the pick point don't speak.
//! - **`pick` is what you pick with.** A one-pole lowpass on the burst:
//!   0 = fingertip felt, 1 = bright plectrum.
//! - **`body` is the box.** Two fixed RBJ peak biquads (low air mode +
//!   top-plate mode) mixed in lightly — enough wood to stop it sounding
//!   like a wire in a vacuum, cheap enough to be free.
//! - **`strum` makes chords play like a hand.** Multiple pitches stagger
//!   by `strum` ms per string; negative strums upward.
//! - **Bends are physical.** A gliss target re-tunes the DELAY LINE per
//!   sample — the same string bending, not a resampled recording of it.
//! - **`pm` palm-mutes** (shorter T60, darker loop, felt-soft burst).
//! - **`detune`** adds a second string a few cents away — the
//!   double-tracked/12-string shimmer.

use std::collections::BTreeMap;

use np_rand::{Pcg64, SeedSequence};

use crate::SR_F64;

/// Everything a pluck reads, with guitar-shaped defaults. All fields are
/// typed in `mus-vocab::param_specs` (mus-x layer).
#[derive(Debug, Clone, PartialEq)]
pub struct PluckPatch {
    /// T60 sustain in seconds (`sus`).
    pub sus: f64,
    /// Loop brightness-decay 0..1 (`damp`).
    pub damp: f64,
    /// Pick position as a fraction of string length (`pos`).
    pub pos: f64,
    /// Pick hardness 0..1 (`pick`).
    pub pick: f64,
    /// Body resonance mix 0..1 (`body`).
    pub body: f64,
    /// Strum stagger per chord tone, ms; negative strums upward (`strum`).
    pub strum_ms: f64,
    /// Palm mute (`pm`).
    pub pm: bool,
    /// Unison detune in cents — a second string when > 0 (`detune`).
    pub detune: f64,
}

impl Default for PluckPatch {
    fn default() -> Self {
        PluckPatch {
            sus: 2.5,
            damp: 0.35,
            pos: 0.13,
            pick: 0.6,
            body: 0.25,
            strum_ms: 10.0,
            pm: false,
            detune: 0.0,
        }
    }
}

fn parsed(map: &BTreeMap<String, String>, key: &str, default: f64) -> f64 {
    map.get(key)
        .and_then(|v| v.parse::<f64>().ok())
        .unwrap_or(default)
}

impl From<&BTreeMap<String, String>> for PluckPatch {
    fn from(map: &BTreeMap<String, String>) -> Self {
        let d = PluckPatch::default();
        PluckPatch {
            sus: parsed(map, "sus", d.sus).clamp(0.05, 20.0),
            damp: parsed(map, "damp", d.damp).clamp(0.0, 0.95),
            pos: parsed(map, "pos", d.pos).clamp(0.02, 0.5),
            pick: parsed(map, "pick", d.pick).clamp(0.0, 1.0),
            body: parsed(map, "body", d.body).clamp(0.0, 1.0),
            strum_ms: parsed(map, "strum", d.strum_ms).clamp(-80.0, 80.0),
            pm: map.get("pm").is_some_and(|v| v != "0" && v != "off"),
            detune: parsed(map, "detune", d.detune).clamp(0.0, 60.0),
        }
    }
}

/// Content-keyed seed (doctrine A7): the burst is a pure function of what
/// the note IS — frequency, duration, and the sounding patch — so a note
/// renders identically every time and anywhere, while two different notes
/// get uncorrelated bursts. FNV-1a over the deciding values.
fn content_seed(f0: f64, dur_s: f64, patch: &PluckPatch, string_index: u64) -> u64 {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    let mut eat = |bits: u64| {
        for byte in bits.to_le_bytes() {
            h ^= byte as u64;
            h = h.wrapping_mul(0x0000_0100_0000_01b3);
        }
    };
    eat(f0.to_bits());
    eat(dur_s.to_bits());
    eat(patch.pos.to_bits());
    eat(patch.pick.to_bits());
    eat(patch.damp.to_bits());
    eat((patch.pm as u64) << 1 | string_index);
    h
}

/// RBJ cookbook peaking EQ, fixed shape — the "wood" of [`body`].
struct Peak {
    b0: f64,
    b1: f64,
    b2: f64,
    a1: f64,
    a2: f64,
    x1: f64,
    x2: f64,
    y1: f64,
    y2: f64,
}

impl Peak {
    fn new(f0: f64, q: f64, gain_db: f64) -> Self {
        let a = 10f64.powf(gain_db / 40.0);
        let w0 = 2.0 * std::f64::consts::PI * f0 / SR_F64;
        let alpha = w0.sin() / (2.0 * q);
        let (cw, a0) = (w0.cos(), 1.0 + alpha / a);
        Peak {
            b0: (1.0 + alpha * a) / a0,
            b1: (-2.0 * cw) / a0,
            b2: (1.0 - alpha * a) / a0,
            a1: (-2.0 * cw) / a0,
            a2: (1.0 - alpha / a) / a0,
            x1: 0.0,
            x2: 0.0,
            y1: 0.0,
            y2: 0.0,
        }
    }

    fn tick(&mut self, x: f64) -> f64 {
        let y = self.b0 * x + self.b1 * self.x1 + self.b2 * self.x2
            - self.a1 * self.y1
            - self.a2 * self.y2;
        self.x2 = self.x1;
        self.x1 = x;
        self.y2 = self.y1;
        self.y1 = y;
        y
    }
}

/// One string: extended KS into `out[start..]`, additive.
#[allow(clippy::too_many_arguments)]
fn pluck_string(
    out: &mut [f32],
    start: usize,
    f0: f64,
    f1: f64,
    n_samples: usize,
    slot_samples: usize,
    patch: &PluckPatch,
    string_index: u64,
    level: f64,
) {
    if f0 < 20.0 || start >= out.len() {
        return;
    }
    let (sus, damp, pick) = if patch.pm {
        (
            patch.sus * 0.12,
            (patch.damp + 0.35).min(0.95),
            patch.pick * 0.45,
        )
    } else {
        (patch.sus, patch.damp, patch.pick)
    };

    // Delay-line budget at the LOWEST frequency the bend will visit, so a
    // downward bend never outgrows the buffer.
    let f_min = f0.min(f1).max(20.0);
    let max_period = (SR_F64 / f_min).ceil() as usize + 4;
    let mut line = vec![0f64; max_period];

    // --- the burst: content-keyed noise, pick-hardness lowpass, position comb.
    let mut ss = SeedSequence::new(content_seed(
        f0,
        n_samples as f64 / SR_F64,
        patch,
        string_index,
    ));
    let mut rng = Pcg64::from_seed_sequence(&mut ss);
    let period0 = SR_F64 / f0;
    let burst_len = period0.ceil() as usize;
    let mut burst: Vec<f64> = (0..burst_len)
        .map(|_| (rng.next_u64() >> 11) as f64 / (1u64 << 53) as f64 * 2.0 - 1.0)
        .collect();
    // pick hardness: one-pole LPF, cutoff rising with hardness.
    let pick_coeff = 0.05 + 0.93 * (1.0 - pick);
    let mut lp = 0.0;
    for v in burst.iter_mut() {
        lp = pick_coeff * lp + (1.0 - pick_coeff) * *v;
        *v = lp;
    }
    // position comb: e[n] -= e[(n - pos·P) mod P], CIRCULAR over the
    // period. The loop sustains the burst's periodic extension, so the
    // comb must shape the period's spectrum as a cyclic filter — a linear
    // comb leaves the pre-comb half of the buffer intact and the "nodal"
    // harmonics leak straight through it (first version's bug; the
    // spectral invariant test caught it).
    let comb = ((patch.pos * period0).round() as usize).clamp(1, burst_len.saturating_sub(1));
    let pre = burst.clone();
    for i in 0..burst_len {
        burst[i] = pre[i] - pre[(i + burst_len - comb) % burst_len];
    }
    // normalize burst energy so `pos`/`pick` change color, not loudness.
    let energy: f64 = burst.iter().map(|v| v * v).sum::<f64>().max(1e-12);
    let norm = (burst_len as f64 / energy).sqrt();
    for v in burst.iter_mut() {
        *v *= norm;
    }

    // --- loop constants.
    // T60 gain is PER CIRCULATION: the multiplier sits inside the loop, so
    // a sample meets it once per period (SR/f samples), not once per
    // sample. g = 10^(-3/(sus*f)) gives amplitude 10^(-3) = -60 dB after
    // sus seconds at any pitch. (First version divided by SR here — the
    // string rang ~200x too long. The invariant test caught it.)
    let mut body_low = Peak::new(105.0, 1.1, 6.5);
    let mut body_top = Peak::new(215.0, 1.4, 4.5);

    let n_out = n_samples.min(out.len() - start);
    let bend = (f1 - f0).abs() > 1e-9;
    let ramp_len = slot_samples.max(1) as f64;
    let g_static = 10f64.powf(-3.0 / (sus * f0));

    // ring-buffer state
    let mut write = 0usize;
    let mut ap_state = 0.0f64; // allpass y[n-1]
    let mut ap_x1 = 0.0f64; // allpass x[n-1]
    let mut lp_state = 0.0f64; // damping one-zero x[n-1]

    for n in 0..n_out {
        // instantaneous frequency: linear ramp COMPLETING AT THE SLOT
        // BOUNDARY (matching synth_note's gliss), then held — the bend
        // arrives, the tail rings at the target.
        let f = if bend {
            let progress = (n as f64 / ramp_len).min(1.0);
            f0 + (f1 - f0) * progress
        } else {
            f0
        };
        let g = if bend {
            10f64.powf(-3.0 / (sus * f))
        } else {
            g_static
        };
        // total loop must delay exactly SR/f samples: integer line + 0.5
        // (damping filter) + allpass fraction.
        let total = SR_F64 / f - 0.5;
        let int_delay = (total - 0.2).floor().max(2.0) as usize;
        let frac = total - int_delay as f64; // in (0.2, 1.2)
        let ap_a = (1.0 - frac) / (1.0 + frac); // first-order allpass coeff

        let read = (write + max_period - int_delay) % max_period;
        let delayed = line[read];

        // damping one-zero (half-sample phase, folded into `total` above)
        let filtered = (1.0 - damp) * delayed + damp * lp_state;
        lp_state = delayed;

        // allpass fractional delay
        let ap_out = ap_a * (filtered - ap_state) + ap_x1;
        ap_x1 = filtered;
        ap_state = ap_out;

        let excitation = if n < burst_len { burst[n] } else { 0.0 };
        let circulating = ap_out * g + excitation;
        line[write] = circulating;
        write = (write + 1) % max_period;

        let wood = 0.5 * body_low.tick(circulating) + 0.35 * body_top.tick(circulating);
        let sample = circulating + patch.body * wood;
        out[start + n] += (sample * level * 0.32) as f32;
    }
}

/// Render a pluck event: one or more strings (chord tones), strummed,
/// optionally doubled by `detune`. Mono; the engine's placement stage
/// pans/sends it like any other source. `gliss_ratio` bends every string
/// by the same ratio across the slot, physically (delay-line re-tuning).
pub fn pluck_note(
    params: &BTreeMap<String, String>,
    freqs_hz: &[f64],
    slot_s: f64,
    gliss_ratio: f64,
) -> Vec<f32> {
    let patch = PluckPatch::from(params);
    // Let the string ring past the slot by its own tail (up to a bound):
    // a pluck is not a gate — the engine's articulation cuts still apply.
    let tail = (patch.sus * 0.6).min(3.0);
    let n = ((slot_s + tail) * SR_F64).max(64.0) as usize;
    let mut out = vec![0f32; n];

    let strum_samples = (patch.strum_ms.abs() / 1000.0 * SR_F64) as usize;
    let count = freqs_hz.len().max(1);
    let level = 1.0 / (count as f64).sqrt();

    let order: Vec<usize> = if patch.strum_ms >= 0.0 {
        (0..freqs_hz.len()).collect()
    } else {
        (0..freqs_hz.len()).rev().collect()
    };
    for (slot_index, &fi) in order.iter().enumerate() {
        let f0 = freqs_hz[fi];
        let f1 = f0 * gliss_ratio;
        let start = slot_index * strum_samples;
        let remaining = n.saturating_sub(start);
        let slot_samples = (slot_s * SR_F64) as usize;
        pluck_string(
            &mut out,
            start,
            f0,
            f1,
            remaining,
            slot_samples,
            &patch,
            fi as u64,
            level,
        );
        if patch.detune > 0.0 {
            let r = 2f64.powf(patch.detune / 1200.0);
            pluck_string(
                &mut out,
                start,
                f0 * r,
                f1 * r,
                remaining,
                slot_samples,
                &patch,
                fi as u64 + 101,
                level * 0.5,
            );
        }
    }
    out
}
