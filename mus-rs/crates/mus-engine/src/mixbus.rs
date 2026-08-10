//! Placement, mixing, sidechain ducking, and the master bus —
//! `mus_audio.py`'s `mix_one` (line 832), the eager/deferred dispatch
//! (lines 862-867, 1120-1148), and the reverb/highpass/master tail (lines
//! 1150-1167).

use mus_dsp::kernels::pan_stereo;
use mus_dsp::SR_F64;

/// One placed note awaiting the bus, before the final gain/duck fold —
/// `mus_audio.render`'s `pending.append([(start, L, R, send), db])`
/// tuple. `db` stays mutable so a hairpin span can adjust it in place
/// after the fact.
pub struct PendingNote {
    pub start: usize,
    pub l: Vec<f32>,
    pub r: Vec<f32>,
    pub send: f64,
    pub db: f64,
}

/// One note held for the deferred (sidechain) mixdown — `placed.append((
/// abbr, ducks, start, L, R, send, g))`.
pub struct PlacedNote {
    pub track: String,
    pub ducks: bool,
    pub start: usize,
    pub l: Vec<f32>,
    pub r: Vec<f32>,
    pub send: f64,
    pub gain: f64,
}

/// `pan_stereo` + the Haas width delay (lines 1106-1112).
pub fn pan_and_haas(x: &[f32], p0: f64, p1: f64, haas_ms: Option<f64>) -> (Vec<f32>, Vec<f32>) {
    let (l, mut r) = pan_stereo(x, p0, p1);
    if let Some(ms) = haas_ms {
        mus_dsp::glow::haas(&mut r, ms);
    }
    (l, r)
}

/// The `dry`/`wet` buses, planar stereo (`np.zeros((2, n_total))`).
pub struct MixBuffers {
    pub dry: [Vec<f32>; 2],
    pub wet: [Vec<f32>; 2],
}

impl MixBuffers {
    pub fn new(n_total: usize) -> Self {
        Self {
            dry: [vec![0.0; n_total], vec![0.0; n_total]],
            wet: [vec![0.0; n_total], vec![0.0; n_total]],
        }
    }

    /// `mus_audio.mix_one` (line 832). `gain`/`send` are the plain Python
    /// floats the oracle carries them as (`db` converted via `10**(db/
    /// 20)`, `send` from `float(ev.params.get("send", ...))`) — each
    /// rounds down to f32 exactly once at the multiply, per this crate's
    /// established weak-scalar rule, rather than promoting `l`/`r` to f64.
    pub fn mix_one(
        &mut self,
        start: usize,
        l: &[f32],
        r: &[f32],
        send: f64,
        gain: f64,
        duck: Option<&[f32]>,
    ) {
        let gain = gain as f32;
        for i in 0..l.len() {
            let mut dl = l[i] * gain;
            let mut dr = r[i] * gain;
            if let Some(d) = duck {
                let dv = d[start + i];
                dl *= dv;
                dr *= dv;
            }
            self.dry[0][start + i] += dl;
            self.dry[1][start + i] += dr;
            if send > 0.0 {
                let send = send as f32;
                self.wet[0][start + i] += dl * send;
                self.wet[1][start + i] += dr * send;
            }
        }
    }
}

/// `10 ** (db / 20.0)`.
pub fn db_to_gain(db: f64) -> f64 {
    10f64.powf(db / 20.0)
}

/// `mus_audio.duck_envelope`'s call site (line 1141-1142): `hold` is never
/// overridden by the caller, so it always runs at the function's own
/// Python default (0.012 s).
const DUCK_HOLD_S: f64 = 0.012;

/// Lines 1140-1148: the deferred mixdown, with the sidechain pump applied
/// to every ducking track except the trigger track itself.
pub fn deferred_mixdown(
    buffers: &mut MixBuffers,
    placed: &[PlacedNote],
    sc_track: Option<&str>,
    sc_onsets: &[f64],
    sc_depth: f64,
    sc_rel: f64,
    n_total: usize,
) -> usize {
    let duck = if sc_track.is_some() && !sc_onsets.is_empty() {
        Some(mus_dsp::kernels::duck_envelope(
            sc_onsets,
            n_total,
            sc_depth,
            sc_rel,
            DUCK_HOLD_S,
        ))
    } else {
        None
    };
    for note in placed {
        let apply_duck = duck.is_some() && note.ducks && Some(note.track.as_str()) != sc_track;
        let d = if apply_duck { duck.as_deref() } else { None };
        buffers.mix_one(note.start, &note.l, &note.r, note.send, note.gain, d);
    }
    sc_onsets.len()
}

/// Lines 1150-1167: reverb send (`make_ir` + `oaconvolve`, truncated to
/// `n_total`), the output high-pass, and the RMS/ceiling master chain.
/// Returns planar stereo, `n_total` samples per channel.
pub fn finish_bus(
    buffers: MixBuffers,
    reverb_s: f64,
    master_rms_db: f64,
    n_total: usize,
) -> [Vec<f32>; 2] {
    let ir = mus_dsp::bus::make_ir(reverb_s);
    let mut out = [vec![0.0f32; n_total], vec![0.0f32; n_total]];
    for c in 0..2 {
        let rev = mus_dsp::bus::oaconvolve(&buffers.wet[c], &ir[c]);
        for (i, dry_sample) in out[c].iter_mut().enumerate() {
            let wet_sample = rev.get(i).copied().unwrap_or(0.0);
            *dry_sample = buffers.dry[c][i] + wet_sample;
        }
    }
    let out = mus_dsp::bus::highpass28(out);
    mus_dsp::bus::master(out, master_rms_db)
}

/// `mus_audio.py` line 1099-1102: onset-sample truncation at `n_total`.
/// Returns `None` when the note starts past the render (a hard skip, no
/// stats change — Python's own `continue` here doesn't touch `stats`
/// either) or when the truncated tail comes in under 32 samples (`stats
/// ["skipped"]`-worthy, but the caller owns that count since this helper
/// is pure).
pub fn truncate_to_render(x: Vec<f32>, start_s: f64, n_total: usize) -> Option<(usize, Vec<f32>)> {
    let start = (start_s * SR_F64) as usize;
    if start >= n_total {
        return None;
    }
    let max_len = n_total - start;
    let mut x = x;
    if x.len() > max_len {
        x.truncate(max_len);
    }
    if x.len() < 32 {
        return None;
    }
    Some((start, x))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mix_one_sums_dry_and_scales_wet_by_send() {
        let mut buffers = MixBuffers::new(8);
        buffers.mix_one(2, &[1.0, 1.0], &[0.5, 0.5], 0.25, db_to_gain(0.0), None);
        assert_eq!(buffers.dry[0][2], 1.0);
        assert_eq!(buffers.dry[1][2], 0.5);
        assert!((buffers.wet[0][2] - 0.25).abs() < 1e-6);
        assert!((buffers.wet[1][2] - 0.125).abs() < 1e-6);
        // untouched samples remain 0
        assert_eq!(buffers.dry[0][0], 0.0);
    }

    #[test]
    fn zero_send_never_touches_wet() {
        let mut buffers = MixBuffers::new(4);
        buffers.mix_one(0, &[1.0], &[1.0], 0.0, 1.0, None);
        assert_eq!(buffers.wet[0][0], 0.0);
        assert_eq!(buffers.dry[0][0], 1.0);
    }

    #[test]
    fn truncate_to_render_drops_notes_past_the_end_or_too_short_after_clipping() {
        // start_s * SR >= n_total: the note starts after the render ends.
        assert!(truncate_to_render(vec![1.0; 100], 1000.0, 48_000).is_none());
        // Starts just inside the render, but only 10 samples fit before the end.
        let n_total = 48_010;
        let start_s = 48_000.0 / SR_F64;
        assert!(truncate_to_render(vec![1.0; 100], start_s, n_total).is_none());
        // Ordinary case: fits with room to spare, untruncated.
        let (start, x) = truncate_to_render(vec![1.0; 100], 0.0, 48_000).unwrap();
        assert_eq!(start, 0);
        assert_eq!(x.len(), 100);
    }

    #[test]
    fn deferred_mixdown_ducks_everyone_but_the_trigger_track() {
        let n_total = 48_000;
        let one_note = |track: &str, ducks: bool| PlacedNote {
            track: track.into(),
            ducks,
            start: 0,
            l: vec![1.0; 100],
            r: vec![1.0; 100],
            send: 0.0,
            gain: 1.0,
        };

        // The trigger track itself is exempt from its own duck.
        let mut trigger_only = MixBuffers::new(n_total);
        deferred_mixdown(
            &mut trigger_only,
            &[one_note("kk", true)],
            Some("kk"),
            &[0.0],
            0.75,
            0.16,
            n_total,
        );
        assert_eq!(trigger_only.dry[0][0], 1.0);

        // A ducking track is pulled down under the hold floor (1 - depth).
        let mut ducked = MixBuffers::new(n_total);
        deferred_mixdown(
            &mut ducked,
            &[one_note("bass", true)],
            Some("kk"),
            &[0.0],
            0.75,
            0.16,
            n_total,
        );
        assert!(
            ducked.dry[0][0] <= 0.25 + 1e-6,
            "bass sample: {}",
            ducked.dry[0][0]
        );

        // `ducks: false` (opt-out) skips the pump even for a non-trigger track.
        let mut opted_out = MixBuffers::new(n_total);
        deferred_mixdown(
            &mut opted_out,
            &[one_note("pad", false)],
            Some("kk"),
            &[0.0],
            0.75,
            0.16,
            n_total,
        );
        assert_eq!(opted_out.dry[0][0], 1.0);
    }
}
