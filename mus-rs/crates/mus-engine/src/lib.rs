//! `mus-engine` — the render orchestrator, at full semantic parity with
//! `mus_audio.render()`: headers, voices (sample or synth), the bar map,
//! the per-track event walk (dynamics, hairpins, pattern repetition,
//! gesture quotation, chords), the transform chain, sidechain-aware
//! mixing, and the reverb/highpass/master bus. Every DSP primitive is
//! `mus-dsp`'s (sample-parity-tested against the Python oracle); this
//! crate's own job is the glue that calls them in the oracle's order.
//!
//! WF1's reduced-scope engine (rubato resampling, refusing synth/vocoder/
//! sidechain/reverb/chop/ring/glow rather than rendering them) is
//! superseded here — this stage's whole point is to stop refusing those
//! constructs and render them instead.

mod events;
mod gestures;
mod layout;
mod mixbus;
mod pack;
mod rawbars;
mod source;
mod transforms;
mod util;

use std::collections::BTreeMap;
use std::fmt::{Display, Formatter};
use std::path::Path;

use sha2::{Digest, Sha256};

pub const SAMPLE_RATE: u32 = 48_000;
pub const ENGINE_VERSION: &str = "mus-engine/0.2.0-wf8";

#[derive(Debug)]
pub enum RenderError {
    Io(std::io::Error),
    Json(serde_json::Error),
    Wav(String),
    Invalid(String),
}

impl Display for RenderError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(e) => write!(f, "I/O error: {e}"),
            Self::Json(e) => write!(f, "manifest error: {e}"),
            Self::Wav(e) => write!(f, "audio file error: {e}"),
            Self::Invalid(e) => write!(f, "invalid score: {e}"),
        }
    }
}

impl std::error::Error for RenderError {}
impl From<std::io::Error> for RenderError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value)
    }
}
impl From<serde_json::Error> for RenderError {
    fn from(value: serde_json::Error) -> Self {
        Self::Json(value)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct RenderedAudio {
    /// Interleaved stereo frames, left then right.
    pub samples: Vec<f32>,
    pub sample_rate: u32,
}

impl RenderedAudio {
    pub fn frames(&self) -> usize {
        self.samples.len() / 2
    }

    pub fn peak(&self) -> f32 {
        self.samples.iter().map(|v| v.abs()).fold(0.0_f32, f32::max)
    }

    pub fn rms(&self) -> f32 {
        if self.samples.is_empty() {
            return 0.0;
        }
        (self.samples.iter().map(|v| v * v).sum::<f32>() / self.samples.len() as f32).sqrt()
    }

    pub fn peak_dbfs(&self) -> f32 {
        dbfs(self.peak())
    }

    pub fn rms_dbfs(&self) -> f32 {
        dbfs(self.rms())
    }
}

fn dbfs(value: f32) -> f32 {
    20.0 * value.max(1e-12).log10()
}

/// Everything the render receipt wants beyond peak/RMS: `mus_audio.py`'s
/// own `stats` dict (notes/skipped/bad, lines 874-1179) extended with the
/// per-track and sidechain counts the WF8 spec asks for.
#[derive(Debug, Clone, Default)]
pub struct RenderStats {
    pub notes: u32,
    pub skipped: u32,
    pub bad: Vec<String>,
    /// Missing-source track warnings (`mus_audio.py` line 757) — kept
    /// separate from `bad`, matching the oracle's own separate stderr
    /// stream for these.
    pub warnings: Vec<String>,
    pub per_track_events: BTreeMap<String, u32>,
    pub sidechain_hits: usize,
    pub voices: usize,
    pub total_seconds: f64,
    pub tuning_a: f64,
}

#[derive(Debug, Clone)]
pub struct RenderOutcome {
    pub audio: RenderedAudio,
    pub stats: RenderStats,
}

pub fn sha256_bytes(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}

/// Render a score to full sample parity with `mus_audio.render()`
/// (`mus_audio.py` lines 717-1181). `source` is the score text; assets
/// (`pack`, `gestures`, `tape`, `sample=`) resolve relative to
/// `score_dir`.
pub fn render(source: &str, score_dir: &Path) -> Result<RenderOutcome, RenderError> {
    let (proposal, _diags) = mus_text::parse_score_lossy(source);
    let headers = &proposal.headers;

    // ---- headers (lines 721-733, 776-788, 844-860, 1153-1166)
    let a4 = layout::parse_tuning_a4(headers.get("tuning"))?;
    let (swing_unit_ql, swing_r) = layout::parse_swing(headers.get("swing"));
    let sidechain = layout::parse_sidechain(headers.get("sidechain"));
    let reverb_s = layout::parse_reverb_seconds(headers.get("reverb"))?;
    let master_rms_db = layout::parse_master_rms(headers.get("master"))?;

    // ---- pack / gestures / tape (lines 727-743)
    let pack = match headers.get("pack") {
        Some(rel) => Some(pack::Pack::load(&score_dir.join(rel))?),
        None => None,
    };
    let gestures = match headers.get("gestures") {
        Some(rel) => gestures::load_gestures(&score_dir.join(rel))?,
        None => BTreeMap::new(),
    };
    let cache = pack::SampleCache::new();
    let tape_audio: Option<Vec<f32>> = match headers.get("tape") {
        Some(rel) => Some((*cache.load(&score_dir.join(rel))?).clone()),
        None => None,
    };

    // ---- voices (lines 745-774)
    let (voices, warnings) =
        pack::build_voices(&proposal.instruments, pack.as_ref(), score_dir, a4)?;

    // ---- bar map (lines 798-826). The inline tempo/time overrides come
    // from a fresh raw-text bar scan, not `proposal.bar_changes` — see
    // `rawbars`'s module doc for why.
    let abbrevs: Vec<String> = proposal
        .instruments
        .iter()
        .map(|i| i.abbrev.clone())
        .collect();
    let raw = rawbars::scan(source, &abbrevs);
    // `if not bar_count and bars: bar_count = max(...)` (mus.py line
    // 1326-1327): Python's `not bar_count` is also true for an explicit
    // `# bars: 0`, so a literal `0` header falls through to the bar-lines
    // count exactly like a missing/unparseable header does.
    let n_bars = headers
        .get("bars")
        .and_then(|v| v.trim().parse::<u32>().ok())
        .filter(|&n| n != 0)
        .unwrap_or(raw.max_bar);
    let bar_map = layout::build_bar_map(
        headers.get("tempo"),
        headers.get("time"),
        &raw.inline_tempo,
        &raw.inline_time,
        n_bars,
    )?;
    let n_total = (bar_map.total_s * mus_dsp::SR_F64) as usize;

    // ---- the event walk, track by track (lines 862-1138)
    let eager = sidechain.is_none();
    let mut buffers = mixbus::MixBuffers::new(n_total);
    let mut placed = Vec::new();
    let mut sc_onsets = Vec::new();
    let mut stats = RenderStats {
        voices: voices.len(),
        total_seconds: bar_map.total_s,
        tuning_a: a4,
        warnings,
        ..Default::default()
    };

    for voice in &voices {
        let ctx = events::WalkContext {
            bar_map: &bar_map,
            bar_content: &raw.bar_content,
            n_bars,
            swing_unit_ql,
            swing_r,
            a4,
            gestures: &gestures,
            tape_audio: tape_audio.as_deref(),
            cache: &cache,
            n_total,
            eager,
            sc_track: sidechain.as_ref().map(|s| s.track.as_str()),
        };
        events::walk_track(
            &ctx,
            voice,
            &mut buffers,
            &mut placed,
            &mut sc_onsets,
            &mut stats,
        )?;
    }

    // ---- deferred mixdown + sidechain (lines 1140-1148)
    let sidechain_hits = mixbus::deferred_mixdown(
        &mut buffers,
        &placed,
        sidechain.as_ref().map(|s| s.track.as_str()),
        &sc_onsets,
        sidechain.as_ref().map(|s| s.depth).unwrap_or(0.75),
        sidechain.as_ref().map(|s| s.rel).unwrap_or(0.16),
        n_total,
    );
    stats.sidechain_hits = sidechain_hits;

    // ---- reverb + highpass + master (lines 1150-1167)
    let out = mixbus::finish_bus(buffers, reverb_s, master_rms_db, n_total);

    let mut samples = Vec::with_capacity(n_total * 2);
    for (&l, &r) in out[0].iter().zip(out[1].iter()) {
        samples.push(l);
        samples.push(r);
    }
    Ok(RenderOutcome {
        audio: RenderedAudio {
            samples,
            sample_rate: SAMPLE_RATE,
        },
        stats,
    })
}

/// `float × 2²³`, floored, clipped to the 24-bit signed range —
/// `soundfile`'s (`libsndfile`) actual `PCM_24` write conversion.
///
/// **This is `floor`, not the round-to-nearest-even
/// `SPECS/audio/WF8-orchestrator.md`'s Output section describes.** That
/// prose turned out not to match the executable oracle, which
/// `SPECS/audio/README.md` names as the actual arbiter ("the oracle is
/// executable"); flagging the discrepancy here rather than silently
/// picking a side. The previous attempt at this function also produced
/// `floor` and was rejected for it, but on inspection its supporting
/// test was unsound, not just circular: several of its per-fraction
/// cases (`0.1`, `0.25`, `0.4`, …) were built as `(target as f64 + frac)
/// as f32` at `target ≈ 1_000_000`, a magnitude where f32 has only ~3-4
/// fractional mantissa bits left — most of those fractions silently
/// round to a *different* value during that cast, before the conversion
/// under test ever sees them, so the table wasn't the evidence it
/// claimed to be. Redone here with values constructed to be *exactly*
/// representable in f32 (see `tests::half_boundary`/`tests::
/// sixteenth_above`), verified against real `soundfile` 0.14.0 /
/// `libsndfile` 1.2.2 output (both mono and interleaved-stereo array
/// shapes, matching `write_wav`'s actual layout):
///
/// - Every `m + 0.5` boundary floors to `m` on the positive side —
///   *regardless* of whether `m` or `m+1` is even, which rules out both
///   round-half-to-even and round-half-up (either would round at least
///   one of `1_000_000.5`/`1_000_001.5` up; neither does).
/// - The negative side floors toward `-infinity` (`-(m+0.5)` → `-(m+1)`),
///   not toward zero, which rules out a truncating cast.
/// - A dense sweep of every sixteenth across a whole unit interval floors
///   uniformly across the *entire* interval — not just near either end —
///   which no rounding rule, whatever its tie-breaking policy, could
///   produce.
///
/// See `tests::pcm24_matches_soundfile_oracle_bit_exact` for the pinned
/// values (hardcoded literals, not round-tripped through this function —
/// the previous attempt's circularity complaint) and the regeneration
/// command.
fn f32_to_pcm24(sample: f32) -> i32 {
    let scaled = (sample as f64 * 8_388_608.0).floor();
    scaled.clamp(-8_388_608.0, 8_388_607.0) as i32
}

/// `sf.write(str(out_path), out.T, SR, subtype="PCM_24")` (`mus_audio.py`
/// line 1169).
pub fn write_wav(audio: &RenderedAudio, path: &Path) -> Result<(), RenderError> {
    let spec = hound::WavSpec {
        channels: 2,
        sample_rate: audio.sample_rate,
        bits_per_sample: 24,
        sample_format: hound::SampleFormat::Int,
    };
    let mut writer = hound::WavWriter::create(path, spec)
        .map_err(|e| RenderError::Wav(format!("{}: {e}", path.display())))?;
    for &value in &audio.samples {
        writer
            .write_sample(f32_to_pcm24(value))
            .map_err(|e| RenderError::Wav(e.to_string()))?;
    }
    writer
        .finalize()
        .map_err(|e| RenderError::Wav(e.to_string()))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A float32 exactly `(2m + 1) / 2**24` — chosen so `value * 2**23`
    /// equals `m + 0.5` with no float rounding anywhere in its
    /// construction: `2m + 1` fits f32's 24-bit mantissa exactly for
    /// every `m` used below (`2*8_000_001 + 1 = 16_000_003 <
    /// 16_777_216 = 2**24`), and dividing by a power of two only shifts
    /// the exponent. This is the fix over the previous attempt's
    /// `(target as f64 + frac) as f32` construction, which is *not*
    /// exact at these magnitudes (see `f32_to_pcm24`'s doc comment).
    fn half_boundary(m: i64) -> f32 {
        (2 * m + 1) as f32 / 16_777_216.0
    }

    /// A float32 exactly `k / (16 * 2**23)`, i.e. `value * 2**23 == k /
    /// 16` — sweeps every sixteenth of the unit interval above `base`
    /// with the same exactness guarantee as [`half_boundary`] (`base *
    /// 16 + sixteenths` stays well under `2**24` for every value used
    /// below).
    fn sixteenth_above(base: i64, sixteenths: i64) -> f32 {
        (base * 16 + sixteenths) as f32 / 134_217_728.0
    }

    /// Pinned against real `soundfile`/`libsndfile` output — see
    /// `f32_to_pcm24`'s doc comment for the full finding. Every expected
    /// value below is a hardcoded literal; none are computed by calling
    /// [`f32_to_pcm24`] or any other Rust helper (the previous attempt's
    /// circularity complaint — its second test compared `write_wav`'s
    /// output back to `f32_to_pcm24` itself, which is `pcm24_write_
    /// round_trips_byte_exact`'s job below, *not* oracle evidence).
    ///
    /// Regenerate/verify with:
    /// ```text
    /// uv run --with soundfile --with numpy python3 -c '
    /// import struct, numpy as np, soundfile as sf
    /// def half(m): return np.float32((2*m+1) / (2.0**24))
    /// ms = (1_000_000, 1_000_001, 2, 3, 0, 6, 7, 8_000_000, 8_000_001)
    /// vals = [half(m) for m in ms] + [np.float32(-float(half(m))) for m in ms]
    /// sf.write("/tmp/t.wav", np.array(vals, dtype=np.float32), 48000, subtype="PCM_24")
    /// data = open("/tmp/t.wav","rb").read()
    /// i = data.find(b"data"); n = struct.unpack("<I", data[i+4:i+8])[0]
    /// raw = data[i+8:i+8+n]
    /// print([int.from_bytes(raw[k*3:k*3+3], "little", signed=True) for k in range(n//3)])'
    /// ```
    #[test]
    fn pcm24_matches_soundfile_oracle_bit_exact() {
        let cases: &[(f32, i32)] = &[
            (0.0, 0),
            (1.0, 8_388_607),                       // clips: floor(8388608.0) > max
            (-1.0, -8_388_608), // exact: floor(-8388608.0) == min, no clip needed
            (2.0, 8_388_607),   // far over: clips
            (-2.0, -8_388_608), // far under: clips
            (1_000_000.0 / 8_388_608.0, 1_000_000), // exact integer, sanity check
            (-1_000_000.0 / 8_388_608.0, -1_000_000),
        ];
        for &(input, expected) in cases {
            assert_eq!(f32_to_pcm24(input), expected, "input {input}");
        }

        // Half-integer boundaries: floors to `m` on the positive side for
        // BOTH an even and an odd `m` (rules out round-half-to-even,
        // which would round `1_000_001.5` up to the even `1_000_002`,
        // and round-half-up, which would round `1_000_000.5` up to
        // `1_000_001` — neither happens). The negative side floors
        // toward -infinity, not zero.
        for &m in &[1_000_000i64, 1_000_001, 2, 3, 0, 6, 7, 8_000_000, 8_000_001] {
            assert_eq!(
                f32_to_pcm24(half_boundary(m)),
                m as i32,
                "+({m}+0.5) should floor to {m}"
            );
            assert_eq!(
                f32_to_pcm24(-half_boundary(m)),
                -(m as i32) - 1,
                "-({m}+0.5) should floor to -({m}+1)"
            );
        }

        // Every sixteenth across a whole unit interval floors to the
        // same base integer, not just the values near either end — no
        // rounding rule (whatever its tie-breaking policy) could
        // produce that.
        for s in 1..=15i64 {
            assert_eq!(
                f32_to_pcm24(sixteenth_above(1_000_000, s)),
                1_000_000,
                "1_000_000 + {s}/16 should floor to 1_000_000"
            );
        }
    }

    /// Byte-level round-trip: write via [`write_wav`], read the 24-bit PCM
    /// bytes straight back with `hound` (bypassing float rescaling), and
    /// confirm they match [`f32_to_pcm24`]'s own conversion sample-for-
    /// sample. This proves `write_wav`'s byte packing/interleaving is
    /// faithful to whatever `f32_to_pcm24` computes — it is deliberately
    /// *not* oracle evidence (that's `pcm24_matches_soundfile_oracle_
    /// bit_exact`'s job, against literal pinned values, above), since
    /// comparing the writer to the same helper it calls internally proves
    /// only self-consistency.
    #[test]
    fn pcm24_write_round_trips_byte_exact() {
        let samples: Vec<f32> = (0..2000)
            .map(|i| ((i as f32 / 317.0).sin()) * 0.9)
            .collect();
        let audio = RenderedAudio {
            samples: samples.clone(),
            sample_rate: 48_000,
        };
        let path = std::env::temp_dir().join(format!(
            "mus-engine-pcm24-roundtrip-{}.wav",
            std::process::id()
        ));
        write_wav(&audio, &path).unwrap();
        let mut reader = hound::WavReader::open(&path).unwrap();
        let spec = reader.spec();
        assert_eq!(spec.bits_per_sample, 24);
        assert_eq!(spec.channels, 2);
        let ints: Vec<i32> = reader.samples::<i32>().map(|s| s.unwrap()).collect();
        assert_eq!(ints.len(), samples.len());
        for (got, &input) in ints.iter().zip(&samples) {
            assert_eq!(*got, f32_to_pcm24(input));
        }
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn explicit_bars_zero_header_falls_back_to_the_bar_lines_count() {
        // `if not bar_count and bars: bar_count = max(...)` (mus.py line
        // 1326-1327) treats an explicit `# bars: 0` the same as a missing
        // header — Python's `not 0` is `True`. Before the fix this rendered
        // zero bars (an empty `1..=0` walk range) and produced no events at
        // all; now both notated bars render.
        let text = "# score: bars header zero\n# tempo: 120\n# time: 4/4\n\
                     # bars: 0\n# instruments:\n#   s = synth (perc, synth=sine)\n\
                     bar 1: s=A4q\nbar 2: s=A4q\n";
        let out = render(text, Path::new(".")).unwrap();
        assert_eq!(out.stats.notes, 2, "{:?}", out.stats);
        // 2 bars @ 120bpm 4/4 = 4s of notated material + the 4s render tail.
        assert!((out.stats.total_seconds - 8.0).abs() < 1e-9);
    }

    #[test]
    fn smoke_score_renders_deterministically_with_correct_stats() {
        let score = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../aigua/smoke.mus");
        let text = std::fs::read_to_string(&score).unwrap();
        let base = score.parent().unwrap();
        let first = render(&text, base).unwrap();
        let second = render(&text, base).unwrap();
        assert_eq!(first.audio, second.audio, "render must be deterministic");
        assert_eq!(first.stats.notes, second.stats.notes);
        assert!(first.stats.bad.is_empty(), "{:?}", first.stats.bad);
        assert!(
            first.stats.warnings.is_empty(),
            "{:?}",
            first.stats.warnings
        );
        assert_eq!(first.stats.voices, 5);
        assert!((first.stats.tuning_a - 445.6).abs() < 1e-9);
        assert!(first.audio.frames() > 8 * SAMPLE_RATE as usize);
        assert!(first.audio.peak() <= 10f32.powf(-1.0 / 20.0) + 1e-4);
        // smoke.mus has no `# sidechain:` header.
        assert_eq!(first.stats.sidechain_hits, 0);
    }

    /// End-to-end: a malformed numeric event param refuses the whole
    /// render with a structured `RenderError`, matching the oracle's own
    /// uncaught `ValueError` there — not a silently-defaulted note
    /// wearing a "success" receipt. Exercises the wiring through
    /// `render()` → `events::walk_track` → `transforms::apply_chain`
    /// end to end, on top of `events.rs`/`transforms.rs`'s own unit
    /// coverage of the individual sites.
    #[test]
    fn malformed_event_param_refuses_the_whole_render() {
        let text = "# score: malformed param\n# tempo: 120\n# time: 4/4\n\
                     # instruments:\n#   s = synth (perc, synth=sine)\n\
                     bar 1: s=A4q[drive=hot]\n";
        let err = render(text, Path::new(".")).unwrap_err();
        let RenderError::Invalid(msg) = err else {
            panic!("expected RenderError::Invalid, got {err:?}");
        };
        assert!(msg.contains("drive=\"hot\""), "{msg}");
    }

    /// Same end-to-end shape, for a malformed *header* value: `# time:`
    /// that isn't `N/D` aborts the oracle at the bar-map division just
    /// like a malformed event param does.
    #[test]
    fn malformed_time_signature_header_refuses_the_whole_render() {
        let text = "# score: malformed time\n# tempo: 120\n# time: five-four\n\
                     # instruments:\n#   s = synth (perc, synth=sine)\n\
                     bar 1: s=A4q\n";
        let err = render(text, Path::new(".")).unwrap_err();
        let RenderError::Invalid(msg) = err else {
            panic!("expected RenderError::Invalid, got {err:?}");
        };
        assert!(msg.contains("five-four"), "{msg}");
    }

    /// `# tempo: 96.5` reaches the header tempo-change list, where
    /// Python's `int("96.5")` fails and `coerce` keeps it poisoned rather
    /// than dropping it — using it (bar 1's `spq = 60.0 / tempo`) is where
    /// the oracle itself raises. End to end through `render()`, not just
    /// `layout::build_bar_map` in isolation.
    #[test]
    fn fractional_tempo_header_refuses_the_whole_render() {
        let text = "# score: fractional tempo\n# tempo: 96.5\n# time: 4/4\n\
                     # instruments:\n#   s = synth (perc, synth=sine)\n\
                     bar 1: s=A4q\n";
        let err = render(text, Path::new(".")).unwrap_err();
        let RenderError::Invalid(msg) = err else {
            panic!("expected RenderError::Invalid, got {err:?}");
        };
        assert!(msg.contains("96.5"), "{msg}");
    }

    /// The `lib.rs:190` allocation site this fix targets: `# tempo: 0`
    /// reaches the bar map as a perfectly valid *integer* (Python's own
    /// crash there is `ZeroDivisionError`, not a poisoned string), so
    /// unchecked it makes `total_s` infinite and `n_total = (total_s *
    /// SR) as usize` saturates to `usize::MAX` — an attempted
    /// multi-exabyte allocation rather than a refusal. `render()` must
    /// surface a structured `RenderError` promptly instead.
    #[test]
    fn zero_tempo_header_refuses_the_whole_render_instead_of_a_huge_allocation() {
        let text = "# score: zero tempo\n# tempo: 0\n# time: 4/4\n\
                     # instruments:\n#   s = synth (perc, synth=sine)\n\
                     bar 1: s=A4q\n";
        let err = render(text, Path::new(".")).unwrap_err();
        let RenderError::Invalid(msg) = err else {
            panic!("expected RenderError::Invalid, got {err:?}");
        };
        assert!(msg.contains("not finite and positive"), "{msg}");
    }
}
