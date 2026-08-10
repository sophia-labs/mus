//! The subtractive soft synth: `_osc` (naive saw/square/tri/sine on a
//! phase array) and `synth_note` (detuned unison, optional osc2 and sub,
//! ADSR, filter-envelope sweep) — `mus_audio.py` lines 232–295.
//!
//! Owned by stage WF5 (depends on WF3's `sweep_filter`). Oracle cases:
//! `osc_phase` + `osc_{saw,square,tri,sine}`, `synth_note_funk_bass`,
//! `synth_note_chord_gliss` (max_abs 5e-5).

use std::collections::BTreeMap;

use crate::filters::sweep_filter;
use crate::{SR_F, SR_F64};

// ------------------------------------------------------------------- patch

/// `synth_note`'s `patch: dict` argument, with `mus_audio.py`'s own
/// defaults (`patch.get(key, default)`, lines 250–260). Field names
/// follow the Rust-side role (`wave`, not the patch dict's key
/// `"synth"`) except where the dict key already reads naturally.
#[derive(Debug, Clone, PartialEq)]
pub struct Patch {
    /// `patch["synth"]` — oscillator wave shape (`"saw"`, `"square"`,
    /// `"tri"`, `"sine"`; anything else falls through to saw, matching
    /// [`osc`]'s own fallthrough). Default `"saw"`.
    pub wave: String,
    /// `patch["osc2"]` — second oscillator wave shape, mixed in at
    /// `mix2`. Absent (or empty-string) means off, matching Python's
    /// `if osc2:` truthiness check on `patch.get("osc2")`.
    pub osc2: Option<String>,
    /// `patch["mix2"]` — osc2 mix, 0 = osc1 only, 1 = osc2 only. Default
    /// 0.5.
    pub mix2: f64,
    /// `patch["detune"]` — unison detune in cents; `<= 0` disables the
    /// detuned pair. Default 0.
    pub detune: f64,
    /// `patch["sub"]` — sub-oscillator (sine, half frequency) mixed in
    /// on top; `<= 0` disables it. Default 0.
    pub sub: f64,
    /// `patch["cutoff"]` — filter cutoff in Hz (the sweep's *end*
    /// frequency when `famt > 0`, otherwise the static cutoff). Default
    /// 4200.
    pub cutoff: f64,
    /// `patch["famt"]` — filter envelope amount in Hz; `> 0` sweeps the
    /// cutoff down from `cutoff + famt` to `cutoff` over the note.
    /// Default 0 (static filter).
    pub famt: f64,
    /// `patch["satk"]` — attack time, seconds. Default 0.004.
    pub satk: f64,
    /// `patch["sdec"]` — decay time, seconds. Default 0.05.
    pub sdec: f64,
    /// `patch["ssus"]` — sustain level, roughly 0..1. Default 0.75.
    pub ssus: f64,
    /// `patch["srel"]` — release time, seconds; also pads the rendered
    /// buffer length (`n = max(64, (slot_s + srel) * SR)`). Default
    /// 0.12.
    pub srel: f64,
}

impl Default for Patch {
    fn default() -> Self {
        Patch {
            wave: "saw".to_string(),
            osc2: None,
            mix2: 0.5,
            detune: 0.0,
            sub: 0.0,
            cutoff: 4200.0,
            famt: 0.0,
            satk: 0.004,
            sdec: 0.05,
            ssus: 0.75,
            srel: 0.12,
        }
    }
}

/// A patch key read as f64 with a fallback, mirroring Python's forgiving
/// `patch.get(key, default)`: a missing key *or* a value that fails to
/// parse both fall back to `default` rather than erroring — a malformed
/// token is a silently-defaulted parameter in the oracle too, not a
/// crash.
fn parsed_f64(p: &BTreeMap<String, String>, key: &str, default: f64) -> f64 {
    p.get(key)
        .and_then(|v| v.parse::<f64>().ok())
        .unwrap_or(default)
}

/// `WF8` will feed patches from event params — `BTreeMap<String,
/// String>`, the same shape as `mus-notation`'s `Params` — so every field
/// is parsed from a string with `mus_audio.py`'s own default as the
/// fallback, keeping the constructor forgiving of the same malformed or
/// missing keys the Python dict-`.get()` calls silently absorb.
impl From<&BTreeMap<String, String>> for Patch {
    fn from(p: &BTreeMap<String, String>) -> Self {
        Patch {
            wave: p.get("synth").cloned().unwrap_or_else(|| "saw".to_string()),
            osc2: p.get("osc2").cloned().filter(|s| !s.is_empty()),
            mix2: parsed_f64(p, "mix2", 0.5),
            detune: parsed_f64(p, "detune", 0.0),
            sub: parsed_f64(p, "sub", 0.0),
            cutoff: parsed_f64(p, "cutoff", 4200.0),
            famt: parsed_f64(p, "famt", 0.0),
            satk: parsed_f64(p, "satk", 0.004),
            sdec: parsed_f64(p, "sdec", 0.05),
            ssus: parsed_f64(p, "ssus", 0.75),
            srel: parsed_f64(p, "srel", 0.12),
        }
    }
}

// --------------------------------------------------------- numeric helpers

/// `np.linspace(start, stop, num)` (`endpoint=True`), computed in f64
/// exactly like numpy does internally regardless of a requested output
/// dtype — see `kernels::np_linspace_f64`'s doc for the full derivation.
/// Duplicated here rather than imported: this stage owns only
/// `synth.rs`, and each stage's file must stand alone.
fn linspace_f64(start: f64, stop: f64, num: usize) -> Vec<f64> {
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

/// [`linspace_f64`] narrowed to f32 at the very end — `np.linspace(1.0,
/// gliss_ratio, n).astype(np.float32)`, the glissando ramp.
fn linspace_f32(start: f64, stop: f64, num: usize) -> Vec<f32> {
    linspace_f64(start, stop, num)
        .into_iter()
        .map(|v| v as f32)
        .collect()
}

/// `np.cumsum(freq) / SR` where `freq` is an **f32** array: numpy's
/// `cumsum` preserves the input dtype, so the running sum accumulates in
/// f32 — with f32's rounding at every step — before the (also
/// weak-scalar, so still-f32) divide by `SR`. Order matters: the whole
/// cumulative array is built over the raw Hz-scale values first, *then*
/// divided by `SR` elementwise, not divided-then-summed (which would
/// round differently). Reproducing this precision loss, not routing
/// around it, is the point — see [`tone_ramped`]'s doc.
fn cumsum_div_sr_f32(freq: &[f32]) -> Vec<f32> {
    let mut acc = 0.0f32;
    freq.iter()
        .map(|&v| {
            acc += v;
            acc / SR_F
        })
        .collect()
}

// ---------------------------------------------------------------- oscillator

/// `mus_audio._osc` (line 232): a naive (non-band-limited) oscillator —
/// the wave shape is purely a function of the fractional phase, no
/// antialiasing. `frac = phase - floor(phase)` folds any phase
/// (including negative or multi-cycle) into `[0, 1)`.
///
/// Waveforms: `"square"` is `±1` split at `frac < 0.5`; `"tri"` is
/// `2·|2·frac-1|-1`; `"sine"` is `sin(2π·frac)`; anything else —
/// including the default, `"saw"` — is `2·frac-1`.
///
/// Computed in f64 throughout, cast to f32 only at the very end
/// (`.astype(np.float32)`) — matching the dtype of the direct-call sites
/// this function's own fixtures exercise (`osc_phase` is a genuine
/// float64 array). `synth_note`'s glissando path instead calls the same
/// four formulas on a phase array that is genuinely f32 end to end; see
/// [`osc_f32`] for why that's a separate function rather than a
/// widen-then-narrow wrapper around this one.
pub fn osc(wave: &str, phase: &[f64]) -> Vec<f32> {
    match wave {
        "square" => phase
            .iter()
            .map(|&p| {
                let frac = p - p.floor();
                if frac < 0.5 {
                    1.0f32
                } else {
                    -1.0f32
                }
            })
            .collect(),
        "tri" => phase
            .iter()
            .map(|&p| {
                let frac = p - p.floor();
                (2.0 * (2.0 * frac - 1.0).abs() - 1.0) as f32
            })
            .collect(),
        "sine" => phase
            .iter()
            .map(|&p| {
                let frac = p - p.floor();
                (2.0 * std::f64::consts::PI * frac).sin() as f32
            })
            .collect(),
        _ => phase
            .iter()
            .map(|&p| {
                let frac = p - p.floor();
                (2.0 * frac - 1.0) as f32
            })
            .collect(),
    }
}

/// [`osc`]'s four formulas, run in native **f32** arithmetic throughout
/// instead of f64-then-cast. `mus_audio._osc` is dtype-polymorphic
/// (`frac`, and each wave formula, run at whatever dtype `phase` already
/// carries), and inside `synth_note`'s glissando path `phase` really is
/// `float32` end to end — an f32 cumsum over an f32 `freq` — including
/// `np.sin` itself, which numpy dispatches as a native f32 ufunc on an
/// f32 array rather than `f64::sin` rounded down afterward. This mirrors
/// that: floor, subtract, the wave formula, and `sin` all run in f32,
/// matching numpy's dtype-preserving ufuncs rather than [`osc`]'s
/// f64-then-cast path.
fn osc_f32(wave: &str, phase: &[f32]) -> Vec<f32> {
    match wave {
        "square" => phase
            .iter()
            .map(|&p| {
                let frac = p - p.floor();
                if frac < 0.5 {
                    1.0f32
                } else {
                    -1.0f32
                }
            })
            .collect(),
        "tri" => phase
            .iter()
            .map(|&p| {
                let frac = p - p.floor();
                2.0f32 * (2.0f32 * frac - 1.0f32).abs() - 1.0f32
            })
            .collect(),
        "sine" => {
            // `2 * np.pi` is a Python float, rounded to f32 as a single
            // weak-scalar constant (not `2.0f32 * PI_f32` as two
            // separate f32 roundings) before ever touching `frac`.
            let two_pi = (2.0 * std::f64::consts::PI) as f32;
            phase
                .iter()
                .map(|&p| {
                    let frac = p - p.floor();
                    (two_pi * frac).sin()
                })
                .collect()
        }
        _ => phase
            .iter()
            .map(|&p| {
                let frac = p - p.floor();
                2.0f32 * frac - 1.0f32
            })
            .collect(),
    }
}

// ----------------------------------------------------------- per-fundamental

/// One fundamental's tone on the glissando path (`|gliss_ratio - 1| >
/// 1e-6`): `phase` genuinely ramps over `n` samples, and `ramp` / `freq`
/// / `phase` / `tone` are all held in **f32** throughout, cumsum
/// included — matching numpy's dtype-preserving cumsum over an f32
/// `freq` array. Returns a length-`n` tone.
fn tone_ramped(patch: &Patch, f: f64, n: usize, gliss_ratio: f64) -> Vec<f32> {
    let ramp = linspace_f32(1.0, gliss_ratio, n);
    let f32_f = f as f32;
    let freq: Vec<f32> = ramp.iter().map(|&r| f32_f * r).collect();
    let phase = cumsum_div_sr_f32(&freq);
    let mut tone = osc_f32(&patch.wave, &phase);

    if patch.detune > 0.0 {
        let r = 2f64.powf(patch.detune / 1200.0) as f32;
        let freq_r: Vec<f32> = freq.iter().map(|&x| x * r).collect();
        let freq_ir: Vec<f32> = freq.iter().map(|&x| x / r).collect();
        let tone_r = osc_f32(&patch.wave, &cumsum_div_sr_f32(&freq_r));
        let tone_ir = osc_f32(&patch.wave, &cumsum_div_sr_f32(&freq_ir));
        for i in 0..n {
            tone[i] = (tone[i] + tone_r[i] + tone_ir[i]) / 3.0;
        }
    }
    if let Some(o2) = &patch.osc2 {
        // `np.cumsum(freq) / SR * 2.0` recomputes the same array `phase`
        // already holds, then scales by the exact (unrounded) constant
        // 2.0 — reusing `phase` is bit-identical, not an approximation.
        let phase2: Vec<f32> = phase.iter().map(|&p| p * 2.0).collect();
        let tone2 = osc_f32(o2, &phase2);
        let mix2_f32 = patch.mix2 as f32;
        let one_minus_mix2_f32 = (1.0 - patch.mix2) as f32;
        for i in 0..n {
            tone[i] = one_minus_mix2_f32 * tone[i] + mix2_f32 * tone2[i];
        }
    }
    if patch.sub > 0.0 {
        let freq_sub: Vec<f32> = freq.iter().map(|&x| x * 0.5).collect();
        let tone_sub = osc_f32("sine", &cumsum_div_sr_f32(&freq_sub));
        let sub_f32 = patch.sub as f32;
        for i in 0..n {
            tone[i] += sub_f32 * tone_sub[i];
        }
    }
    tone
}

/// One fundamental's tone on the static path (`gliss_ratio ≈ 1`) — and
/// the oracle's own broadcast quirk: `ramp` is a bare Python **scalar**
/// `1.0` there (`np.linspace` is skipped entirely), so `freq = f * ramp`
/// never becomes an array either, and `np.cumsum(freq)` on a scalar
/// promotes it through `np.asanyarray` into a **length-1** float64 array
/// rather than a length-`n` ramp. `_osc` on that length-1 phase returns
/// a length-1 tone, and back in the caller `out += tone` (with `out`
/// length `n`) broadcasts that single sample over the *entire* buffer —
/// so an un-glissed tone carries **zero audio-rate oscillation**: it is
/// one waveform sample (evaluated at phase `f/SR`, i.e. essentially
/// `frac ≈ f/SR`) broadcast flat, and everything that reads as motion in
/// the final render is the ADSR envelope and the sweep filter's own
/// transient response.
///
/// This was confirmed against the running oracle, not inferred from
/// reading alone: `synth_note_funk_bass` calls with the default
/// `gliss_ratio=1.0`, and its sustain region is sample-for-sample
/// constant before the envelope/filter reshape it. Matching this is the
/// job, not a bug to route around.
///
/// Reuses [`osc`] (the f64 variant) directly on length-1 slices rather
/// than a hand-rolled scalar formula — `phase` here really is float64
/// (a bare Python float promoted straight to a float64 array, never
/// touching float32), so this is the same function the fixtures check,
/// called the same way the oracle's own broadcast happens to call it.
fn tone_static(patch: &Patch, f: f64) -> f32 {
    let phase0 = f / SR_F64;
    let mut tone = osc(&patch.wave, &[phase0])[0];

    if patch.detune > 0.0 {
        let r = 2f64.powf(patch.detune / 1200.0);
        let t_r = osc(&patch.wave, &[(f * r) / SR_F64])[0];
        let t_ir = osc(&patch.wave, &[(f / r) / SR_F64])[0];
        tone = (tone + t_r + t_ir) / 3.0;
    }
    if let Some(o2) = &patch.osc2 {
        let t2 = osc(o2, &[phase0 * 2.0])[0];
        let mix2_f32 = patch.mix2 as f32;
        let one_minus_mix2_f32 = (1.0 - patch.mix2) as f32;
        tone = one_minus_mix2_f32 * tone + mix2_f32 * t2;
    }
    if patch.sub > 0.0 {
        let t_sub = osc("sine", &[(f * 0.5) / SR_F64])[0];
        tone += (patch.sub as f32) * t_sub;
    }
    tone
}

// ------------------------------------------------------------------ envelope

/// ADSR-shapes `out` in place (`mus_audio.py` lines 279–288): attack
/// ramps 0→1 over `na` samples, decay ramps 1→`ssus` over the next `nd2`
/// samples, sustain holds `ssus` until the slot ends at sample `ns`, then
/// release falls from *whatever level the envelope was actually at* down
/// to 0 with a `^1.4` curve (so a release triggered mid-decay starts from
/// the decay's current level, not from `ssus`).
///
/// Two deliberate, documented divergences from a literal port, neither
/// reachable by either fixture (both use in-range `satk`/`sdec`/`slot_s`
/// against their buffer length):
/// - If `satk` alone would overflow the buffer (`na > n`), Python's
///   `env[:na] = np.linspace(0, 1, na)` raises (shape mismatch — `na`
///   values into an `n`-slot target). This clamps `na` to `n` instead,
///   so an absurd attack time still yields *a* ramp across the whole
///   buffer rather than a panic.
/// - If `slot_s` is negative, Python's `ns` goes negative and `env[ns]`
///   / `env[ns:]` fall through to Python's negative-index-from-the-end
///   semantics. This clamps `ns` to 0 (release starts immediately)
///   instead of reproducing that wraparound.
fn apply_adsr(patch: &Patch, out: &mut [f32], slot_s: f64) {
    let n = out.len();
    let mut env = vec![patch.ssus as f32; n];

    let na = (((patch.satk * SR_F64).trunc() as i64).max(1) as usize).min(n);
    let attack = linspace_f64(0.0, 1.0, na);
    for (i, &v) in attack.iter().enumerate() {
        env[i] = v as f32;
    }

    if n > na {
        let nd = ((patch.sdec * SR_F64).trunc() as i64).max(1) as usize;
        let nd2 = nd.min(n - na);
        let decay = linspace_f64(1.0, patch.ssus, nd2);
        for (i, &v) in decay.iter().enumerate() {
            env[na + i] = v as f32;
        }
    }

    let ns_signed = (slot_s * SR_F64).trunc() as i64;
    if ns_signed < n as i64 {
        let ns = ns_signed.max(0) as usize;
        // `env[ns]` is a *typed* f32 scalar (single-element index, not a
        // weak Python literal), so multiplying it against the f64 ramp
        // below promotes to f64 rather than rounding the ramp down to
        // f32 — confirmed directly against numpy (`np.float32(x) *
        // f64_array` → f64), not assumed from the weak-scalar rule that
        // governs the rest of this port.
        let level = env[ns] as f64;
        let tail = n - ns;
        let ramp = linspace_f64(1.0, 0.0, tail);
        for (i, &r) in ramp.iter().enumerate() {
            env[ns + i] = (level * r.powf(1.4)) as f32;
        }
    }

    for i in 0..n {
        out[i] *= env[i];
    }
}

// -------------------------------------------------------------- public API

/// `mus_audio.synth_note` (line 243): a small subtractive synth — osc1 +
/// detuned copy + optional osc2 and sub-oscillator, ADSR, and a downward
/// filter sweep standing in for a filter envelope. Chords render every
/// tone in `freqs_hz`, normalized by `1/sqrt(k)`; a `gliss_ratio` sweeps
/// every tone by the same ratio (see [`tone_ramped`] vs [`tone_static`]
/// for why *whether* a gliss is requested changes far more than the
/// ramp shape — it changes the phase array's dtype and even its length).
///
/// Buffer length `n = max(64, (slot_s + srel) * SR)`, truncated like
/// Python's `int()`.
pub fn synth_note(patch: &Patch, freqs_hz: &[f64], slot_s: f64, gliss_ratio: f64) -> Vec<f32> {
    let n = (((slot_s + patch.srel) * SR_F64).trunc() as i64).max(64) as usize;
    let mut out = vec![0.0f32; n];
    let use_ramp = (gliss_ratio - 1.0).abs() > 1e-6;

    for &f in freqs_hz {
        if use_ramp {
            let tone = tone_ramped(patch, f, n, gliss_ratio);
            for i in 0..n {
                out[i] += tone[i];
            }
        } else {
            let tone = tone_static(patch, f);
            for v in out.iter_mut() {
                *v += tone;
            }
        }
    }
    let norm = (freqs_hz.len().max(1) as f64).sqrt() as f32;
    for v in out.iter_mut() {
        *v /= norm;
    }

    apply_adsr(patch, &mut out, slot_s);

    let filtered = if patch.famt > 0.0 {
        sweep_filter(&out, patch.cutoff + patch.famt, patch.cutoff, "low", 4, 256)
    } else {
        sweep_filter(&out, patch.cutoff, patch.cutoff, "low", 4, 256)
    };
    filtered.into_iter().map(|v| v * 0.5).collect()
}
