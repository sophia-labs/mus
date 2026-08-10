//! Per-event source resolution: synth patch vs. sample, `off=`/`reverse`,
//! transposition (varispeed/vocode/pitch-ramp), gesture quotation (raw
//! tape slice or pack-sample polyline), and chord layering —
//! `mus_audio.render`'s lines 926-1032, verbatim in order.
//!
//! Returns the fully-transposed mono buffer, ready for
//! [`crate::transforms`]'s DSP chain. Everything through here is *source
//! selection*; nothing here reads `ev.flags` for articulation (that starts
//! the transform chain).

use std::collections::BTreeMap;

use mus_dsp::pitch::{pitch_polyline, varispeed, vocode};
use mus_dsp::pluck::{pluck_note, weave_note};
use mus_dsp::synth::{synth_note, Patch};
use mus_notation::Note;

use crate::gestures::{lookup_gesture, Gesture};
use crate::pack::{SampleCache, Voice, SYNTH_KEYS};
use crate::util::{midi_to_hz, require_f64, require_f64_opt, with_context};
use crate::RenderError;

#[derive(Debug)]
pub enum SourceStep {
    Rendered(Vec<f32>),
    /// A synth-track event with no pitch (line 929): `stats["bad"]` gets
    /// the message but `stats["skipped"]` does not move — Python's
    /// `continue` here skips straight past the `len(x) < 32` check.
    NeedsPitch,
    /// The resolved (or off/reverse-trimmed) source came in under 32
    /// samples (line 950): `stats["skipped"] += 1`.
    TooShort,
}

#[allow(clippy::too_many_arguments)]
pub fn resolve(
    voice: &Voice,
    ev: &Note,
    slot_s: f64,
    bar: u32,
    abbr: &str,
    a4: f64,
    gestures: &BTreeMap<String, Gesture>,
    tape_audio: Option<&[f32]>,
    cache: &SampleCache,
    bad: &mut Vec<String>,
) -> Result<SourceStep, RenderError> {
    // Attaches `"b{bar} {abbr}: "` context to a numeric-parse refusal,
    // matching `stats.bad`'s own message convention.
    let ctx = |e: RenderError| with_context(&format!("b{bar} {abbr}"), e);

    // --- source: synth patch or sample (lines 927-944)
    let mut x: Vec<f32>;
    let mut smp_f0_hz: Option<f64> = None;
    if let Some(synth_defaults) = &voice.synth {
        if ev.midis.is_empty() {
            bad.push(format!("b{bar} {abbr}: synth track needs a pitch"));
            return Ok(SourceStep::NeedsPitch);
        }
        let mut patch_map = synth_defaults.clone();
        for k in SYNTH_KEYS {
            if let Some(v) = ev.params.get(*k) {
                patch_map.insert((*k).to_string(), v.clone());
            }
        }
        let ratio = match ev.gliss_midi {
            Some(g) => midi_to_hz(g, a4) / midi_to_hz(ev.midis[0], a4),
            None => 1.0,
        };
        let freqs: Vec<f64> = ev.midis.iter().map(|&m| midi_to_hz(m, a4)).collect();
        // The pluck and weave voices are POST-PARITY (mus-x): no oracle
        // line to cite. Everything else about the event pipeline treats
        // them exactly like the subtractive synth output.
        match patch_map.get("synth").map(String::as_str) {
            Some("pluck") => x = pluck_note(&patch_map, &freqs, slot_s, ratio),
            Some("weave") => x = weave_note(&patch_map, &freqs, slot_s, ratio),
            _ => {
                let patch = Patch::from(&patch_map);
                x = synth_note(&patch, &freqs, slot_s, ratio);
            }
        }
    } else {
        // `int(float(ev.params.get("s", 1))) - 1` (line 941): unguarded —
        // a malformed `s=` aborts the render there, so a present-but-bad
        // value refuses here too rather than quietly picking sample 1.
        let s_val = require_f64(&ev.params, "s", 1.0).map_err(ctx)?;
        let max_index = (voice.samples.len() as i64 - 1).max(0);
        let si = ((s_val as i64) - 1).clamp(0, max_index) as usize;
        let sample_ref = voice
            .samples
            .get(si)
            .ok_or_else(|| RenderError::Invalid(format!("track '{abbr}' has no samples")))?;
        let audio = cache.load(&sample_ref.path)?;
        x = (*audio).clone();
        smp_f0_hz = Some(sample_ref.f0_hz);
    }

    // off=/reverse (lines 945-949) apply regardless of synth vs. sample.
    // `int(float(ev.params["off"]) * SR / 1000.0)` (line 946) is guarded
    // only by `"off" in ev.params`, not by whether the value parses — a
    // malformed-but-present `off=` aborts the render there.
    if let Some(off_ms) = require_f64_opt(&ev.params, "off").map_err(ctx)? {
        // `x = x[min(o, max(len(x) - 64, 0)):]` (line 947): `o` keeps
        // whatever sign `int(...)` produced. The `min` only ever pulls a
        // large *positive* `o` back down so at least 64 samples survive;
        // it is a no-op once `o` is negative (negative always wins the
        // `min` against a non-negative bound). A negative slice-start is
        // then a *Python negative index* — count back from the end of
        // `x`, clamped to 0 rather than clamped to the length — not a
        // value to floor at zero before slicing.
        let o = (off_ms * mus_dsp::SR_F64 / 1000.0) as i64;
        let clamp_bound = (x.len() as i64 - 64).max(0);
        let idx = o.min(clamp_bound);
        let start = if idx < 0 {
            (x.len() as i64 + idx).max(0) as usize
        } else {
            (idx as usize).min(x.len())
        };
        x = x[start..].to_vec();
    }
    if ev.flags.iter().any(|f| f == "reverse") {
        x.reverse();
    }
    if x.len() < 32 {
        return Ok(SourceStep::TooShort);
    }

    // --- transposition (lines 954-965)
    let mode = ev
        .params
        .get("mode")
        .map(String::as_str)
        .unwrap_or(&voice.mode);
    let is_pitched_source =
        smp_f0_hz.is_some_and(|f0| f0 > 0.0) && matches!(ev.kind.as_str(), "note" | "chord");
    let mut st = 0.0_f64;
    let mut st_end: Option<f64> = None;
    if is_pitched_source {
        let f0 = smp_f0_hz.unwrap();
        st = 12.0 * (midi_to_hz(ev.midis[0], a4) / f0).log2();
        if let Some(g) = ev.gliss_midi {
            st_end = Some(12.0 * (midi_to_hz(g, a4) / f0).log2());
        }
    } else if ev.kind == "unpitched" {
        let (s0, s1) = crate::util::param_pair(&ev.params, "st", 0.0);
        st = s0;
        st_end = if (s1 - s0).abs() > 1e-6 {
            Some(s1)
        } else {
            None
        };
    }

    let curve = ev
        .params
        .get("curve")
        .cloned()
        .unwrap_or_else(|| "lin".to_string());
    // `float(ev.params.get("tau", 0.045))` (line 968): unguarded.
    let tau = require_f64(&ev.params, "tau", 0.045).map_err(ctx)?;

    // --- quotation (lines 969-1010)
    let mut quoted = false;
    let gest_raw_active = ev.params.contains_key("gest")
        && ev.params.get("gsrc").map(String::as_str) == Some("raw")
        && matches!(ev.kind.as_str(), "note" | "unpitched");
    if gest_raw_active {
        let gest_key = ev.params.get("gest").unwrap();
        let g = lookup_gesture(gestures, gest_key);
        let resolved = g
            .zip(tape_audio)
            .and_then(|(g, tape)| Some((g, tape, g.t0?)));
        match resolved {
            None => {
                let reason = if tape_audio.is_none() {
                    "no tape header"
                } else {
                    "unknown gesture"
                };
                bad.push(format!("b{bar} {abbr}: gest={gest_key} ({reason})"));
            }
            Some((g, tape, t0)) => {
                let t1 = g.t1.unwrap_or(t0);
                let start = ((t0 * mus_dsp::SR_F64) as i64).clamp(0, tape.len() as i64) as usize;
                let end =
                    ((t1 * mus_dsp::SR_F64) as i64).clamp(start as i64, tape.len() as i64) as usize;
                let mut slice = tape[start..end].to_vec();
                if ev.kind == "note" && !ev.midis.is_empty() {
                    let shift = 12.0 * (midi_to_hz(ev.midis[0], a4) / g.median_hz).log2();
                    if shift.abs() > 0.05 {
                        slice = vocode(&slice, shift);
                    }
                }
                x = slice;
                quoted = true;
            }
        }
    } else if ev.params.contains_key("gest") && ev.kind == "note" && is_pitched_source {
        let f0 = smp_f0_hz.unwrap();
        let gest_key = ev.params.get("gest").unwrap();
        let g = lookup_gesture(gestures, gest_key);
        let layer = ev
            .params
            .get("glayer")
            .map(String::as_str)
            .unwrap_or("resolved");
        // `g.get(layer, [])` (line 993): any `glayer=` other than exactly
        // "octave" or "resolved" is an unknown dict key, so Python's
        // `.get` falls through to `[]` — it does NOT treat an arbitrary
        // layer name as "resolved". A wildcard `Some(g) => &g.resolved`
        // arm here would quote off of `resolved` anchors for a typo'd
        // `glayer=`, silently succeeding where the oracle reports the
        // layer too sparse and falls back to ordinary transposition.
        let anchors: &[(f64, f64)] = match g {
            Some(g) if layer == "octave" => &g.octave,
            Some(g) if layer == "resolved" => &g.resolved,
            _ => &[],
        };
        match g.filter(|_| anchors.len() >= 2) {
            None => {
                let reason = if g.is_none() {
                    "unknown gesture".to_string()
                } else {
                    format!("layer {layer} too sparse")
                };
                bad.push(format!("b{bar} {abbr}: gest={gest_key} ({reason})"));
            }
            Some(g) => {
                let base_st = 12.0 * (midi_to_hz(ev.midis[0], a4) / f0).log2();
                let med = g.median_hz;
                let t_arr: Vec<f64> = anchors.iter().map(|(t, _)| *t).collect();
                let st_arr: Vec<f64> = anchors
                    .iter()
                    .map(|(_, hz)| base_st + 12.0 * (hz / med).log2())
                    .collect();
                x = pitch_polyline(&x, &t_arr, &st_arr);
                quoted = true;
            }
        }
    }

    // --- chords, else pitch-ramp/vocoder/varispeed (lines 1010-1032)
    if quoted {
        // x already set above.
    } else if ev.kind == "chord" && ev.midis.len() > 1 && is_pitched_source {
        let f0 = smp_f0_hz.unwrap();
        let parts: Vec<Vec<f32>> = ev
            .midis
            .iter()
            .map(|&m| {
                let st_i = 12.0 * (midi_to_hz(m, a4) / f0).log2();
                if mode == "vocoder" {
                    vocode(&x, st_i)
                } else {
                    varispeed(&x, st_i)
                }
            })
            .collect();
        let max_len = parts.iter().map(Vec::len).max().unwrap_or(0);
        let mut acc = vec![0.0f32; max_len];
        for p in &parts {
            for (i, &v) in p.iter().enumerate() {
                acc[i] += v;
            }
        }
        let norm = (parts.len() as f32).sqrt();
        for v in acc.iter_mut() {
            *v /= norm;
        }
        x = acc;
    } else if let Some(end) = st_end {
        x = mus_dsp::pitch::pitch_ramp(&x, st, end, &curve, tau);
    } else {
        x = if mode == "vocoder" {
            vocode(&x, st)
        } else {
            varispeed(&x, st)
        };
    }

    Ok(SourceStep::Rendered(x))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pack::SampleRef;
    use std::collections::BTreeMap as Map;

    fn synth_voice() -> Voice {
        let mut synth = Map::new();
        synth.insert("synth".to_string(), "sine".to_string());
        Voice {
            abbrev: "s".into(),
            samples: Vec::new(),
            mode: "varispeed".into(),
            gain_db: 0.0,
            pan: 0.0,
            send: 0.0,
            defaults: Map::new(),
            synth: Some(synth),
            ducks: true,
        }
    }

    fn note(kind: &str, midis: Vec<f64>, flags: &[&str]) -> Note {
        Note {
            kind: kind.into(),
            midis,
            ql: 1.0,
            params: Map::new(),
            flags: flags.iter().map(|s| s.to_string()).collect(),
            dyn_value: None,
            gliss_midi: None,
        }
    }

    fn small_gesture(median_hz: f64, t0: f64, t1: f64) -> Gesture {
        Gesture {
            resolved: Vec::new(),
            octave: Vec::new(),
            median_hz,
            t0: Some(t0),
            t1: Some(t1),
        }
    }

    fn write_wav16(samples: &[i16]) -> std::path::PathBuf {
        // A nanosecond timestamp alone is not a reliable unique-path
        // source under `cargo test`'s default thread parallelism: two
        // threads can call this within the same clock tick when the
        // platform's `SystemTime` resolution is coarser than a
        // nanosecond, and two tests racing on the same temp path (one's
        // `WavWriter::create` truncating the other's file mid-read) is
        // exactly the kind of nondeterministic failure a regression suite
        // must not have. The atomic counter guarantees a distinct path
        // per call regardless of clock granularity.
        use std::sync::atomic::{AtomicU64, Ordering};
        static SEQ: AtomicU64 = AtomicU64::new(0);
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let seq = SEQ.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!("mus-engine-source-{nonce}-{seq}.wav"));
        let spec = hound::WavSpec {
            channels: 1,
            sample_rate: 48_000,
            bits_per_sample: 16,
            sample_format: hound::SampleFormat::Int,
        };
        let mut writer = hound::WavWriter::create(&path, spec).unwrap();
        for &s in samples {
            writer.write_sample(s).unwrap();
        }
        writer.finalize().unwrap();
        path
    }

    #[test]
    fn synth_track_with_no_pitch_reports_needs_pitch_and_does_not_render() {
        let voice = synth_voice();
        let ev = note("unpitched", vec![], &[]);
        let cache = SampleCache::new();
        let gestures = Map::new();
        let mut bad = Vec::new();
        let step = resolve(
            &voice, &ev, 0.5, 3, "s", 440.0, &gestures, None, &cache, &mut bad,
        )
        .unwrap();
        assert!(matches!(step, SourceStep::NeedsPitch));
        assert_eq!(bad.len(), 1);
        assert!(bad[0].contains("needs a pitch"), "{}", bad[0]);
    }

    #[test]
    fn synth_note_renders_a_real_buffer_with_no_bad_stats() {
        let voice = synth_voice();
        let ev = note("note", vec![69.0], &[]);
        let cache = SampleCache::new();
        let gestures = Map::new();
        let mut bad = Vec::new();
        let step = resolve(
            &voice, &ev, 0.2, 1, "s", 440.0, &gestures, None, &cache, &mut bad,
        )
        .unwrap();
        match step {
            SourceStep::Rendered(x) => assert!(x.len() > 32),
            _ => panic!("expected a rendered synth buffer"),
        }
        assert!(bad.is_empty());
    }

    #[test]
    fn sample_source_under_32_samples_is_reported_too_short() {
        let path = write_wav16(&[1000i16; 20]); // under the 32-sample floor
        let mut voice = synth_voice();
        voice.synth = None;
        voice.samples = vec![SampleRef {
            path: path.clone(),
            f0_hz: 440.0,
        }];
        let ev = note("note", vec![69.0], &[]);
        let cache = SampleCache::new();
        let gestures = Map::new();
        let mut bad = Vec::new();
        let step = resolve(
            &voice, &ev, 0.2, 1, "s", 440.0, &gestures, None, &cache, &mut bad,
        )
        .unwrap();
        assert!(matches!(step, SourceStep::TooShort));
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn reverse_flag_flips_the_source_before_transposition() {
        let ramp: Vec<i16> = (0..2000).map(|i| i * 10).collect();
        let path = write_wav16(&ramp);
        let mut voice = synth_voice();
        voice.synth = None;
        // f0_hz = 0.0 -> unpitched, no `st=` param -> transposition is a
        // no-op varispeed(x, 0.0), so any reversal survives unmodified
        // into the returned buffer.
        voice.samples = vec![SampleRef {
            path: path.clone(),
            f0_hz: 0.0,
        }];
        let ev = note("unpitched", vec![], &["reverse"]);
        let cache = SampleCache::new();
        let gestures = Map::new();
        let mut bad = Vec::new();
        let step = resolve(
            &voice, &ev, 0.2, 1, "s", 440.0, &gestures, None, &cache, &mut bad,
        )
        .unwrap();
        let SourceStep::Rendered(x) = step else {
            panic!("expected a rendered buffer")
        };
        assert!(
            x[0] > x[x.len() - 1],
            "expected a descending (reversed) ramp"
        );
        std::fs::remove_file(path).unwrap();
    }

    /// `off=` a negative value: Python's `x[min(o, max(len(x)-64, 0)):]`
    /// keeps `o`'s sign, so `off=-1` (ms) at 48 kHz is `x[-48:]` — a
    /// *negative Python slice index*, i.e. the final 48 samples — not a
    /// value clamped up to 0 before slicing (which would return the
    /// entire 2000-sample source instead).
    #[test]
    fn negative_off_slices_the_final_samples_like_python_negative_indexing() {
        let ramp: Vec<i16> = (0..2000).map(|i| i as i16).collect();
        let path = write_wav16(&ramp);
        let mut voice = synth_voice();
        voice.synth = None;
        // f0_hz = 0.0 -> unpitched, no `st=` param -> transposition is a
        // no-op, so the off= trim is the only thing that can change length.
        voice.samples = vec![SampleRef {
            path: path.clone(),
            f0_hz: 0.0,
        }];
        let mut ev = note("unpitched", vec![], &[]);
        ev.params.insert("off".to_string(), "-1".to_string()); // ms
        let cache = SampleCache::new();
        let gestures = Map::new();
        let mut bad = Vec::new();
        let step = resolve(
            &voice, &ev, 0.2, 1, "s", 440.0, &gestures, None, &cache, &mut bad,
        )
        .unwrap();
        let SourceStep::Rendered(x) = step else {
            panic!("expected a rendered buffer")
        };
        // -1ms * 48kHz = -48 samples -> x[-48:] -> the final 48 samples,
        // i.e. the ramp's last 48 values (1952..2000).
        assert_eq!(
            x.len(),
            48,
            "off=-1ms should keep only the source's final 48 samples"
        );
        // `write_wav16` stores raw i16 values; `load_decode` normalizes by
        // `/ 32768.0` on the way in.
        assert!((x[0] - 1952.0 / 32768.0).abs() < 1e-6, "x[0] = {}", x[0]);
        assert!((x[47] - 1999.0 / 32768.0).abs() < 1e-6, "x[47] = {}", x[47]);
        std::fs::remove_file(path).unwrap();
    }

    /// A negative `off=` whose magnitude exceeds the source length clamps
    /// to the start of the array (Python: a negative index more negative
    /// than `-len(x)` clamps to 0), returning the whole source rather than
    /// an empty or out-of-range slice.
    #[test]
    fn negative_off_beyond_the_source_length_clamps_to_the_whole_buffer() {
        let ramp: Vec<i16> = (0..200).map(|i| i as i16).collect();
        let path = write_wav16(&ramp);
        let mut voice = synth_voice();
        voice.synth = None;
        voice.samples = vec![SampleRef {
            path: path.clone(),
            f0_hz: 0.0,
        }];
        let mut ev = note("unpitched", vec![], &[]);
        // -1000ms * 48kHz = -48000 samples, far beyond -200.
        ev.params.insert("off".to_string(), "-1000".to_string());
        let cache = SampleCache::new();
        let gestures = Map::new();
        let mut bad = Vec::new();
        let step = resolve(
            &voice, &ev, 0.2, 1, "s", 440.0, &gestures, None, &cache, &mut bad,
        )
        .unwrap();
        let SourceStep::Rendered(x) = step else {
            panic!("expected a rendered buffer")
        };
        assert_eq!(x.len(), 200);
        std::fs::remove_file(path).unwrap();
    }

    /// `gest=` + `gsrc=raw`: the event replaces its (otherwise ordinary)
    /// sample source with a slice of the tape, vocoded to the notated
    /// pitch when the shift from the gesture's median exceeds 0.05 st.
    #[test]
    fn gest_gsrc_raw_slices_the_tape_and_vocodes_to_the_notated_pitch() {
        let path = write_wav16(&[500i16; 200]); // discarded once quoting succeeds
        let mut voice = synth_voice();
        voice.synth = None;
        voice.samples = vec![SampleRef {
            path: path.clone(),
            f0_hz: 440.0,
        }];

        let mut ev = note("note", vec![81.0], &[]); // A5 = 880 Hz
        ev.params.insert("gest".to_string(), "h0".to_string());
        ev.params.insert("gsrc".to_string(), "raw".to_string());

        let mut gestures = Map::new();
        // median 440 Hz vs. notated 880 Hz -> a 12 st shift, well past the
        // 0.05 st vocode threshold.
        gestures.insert("h0".to_string(), small_gesture(440.0, 0.5, 0.6));
        let tape: Vec<f32> = (0..48_000)
            .map(|i| ((i as f32) * 0.05).sin() * 0.3)
            .collect();

        let cache = SampleCache::new();
        let mut bad = Vec::new();
        let step = resolve(
            &voice,
            &ev,
            0.1,
            5,
            "s",
            440.0,
            &gestures,
            Some(&tape),
            &cache,
            &mut bad,
        )
        .unwrap();
        let SourceStep::Rendered(x) = step else {
            panic!("expected a rendered buffer")
        };
        // vocode preserves length: the tape slice is (0.6-0.5)s = 4800 samples.
        assert_eq!(x.len(), 4_800);
        assert!(bad.is_empty(), "{bad:?}");
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn gest_gsrc_raw_with_unknown_gesture_reports_bad_and_falls_back_to_the_plain_source() {
        let ramp: Vec<i16> = (0..2000).map(|i| (i % 300) * 50).collect();
        let path = write_wav16(&ramp);
        let mut voice = synth_voice();
        voice.synth = None;
        voice.samples = vec![SampleRef {
            path: path.clone(),
            f0_hz: 440.0,
        }];

        let mut ev = note("note", vec![69.0], &[]);
        ev.params.insert("gest".to_string(), "missing".to_string());
        ev.params.insert("gsrc".to_string(), "raw".to_string());

        let gestures: Map<String, Gesture> = Map::new();
        let tape: Vec<f32> = vec![0.1; 48_000];
        let cache = SampleCache::new();
        let mut bad = Vec::new();
        let step = resolve(
            &voice,
            &ev,
            0.1,
            5,
            "s",
            440.0,
            &gestures,
            Some(&tape),
            &cache,
            &mut bad,
        )
        .unwrap();
        // Resolution failure never skips the event — it just falls back to
        // rendering the plain (varispeed-transposed) source.
        assert!(matches!(step, SourceStep::Rendered(_)));
        assert_eq!(bad.len(), 1);
        assert!(bad[0].contains("unknown gesture"), "{}", bad[0]);
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn gest_gsrc_raw_without_a_tape_header_reports_no_tape_header() {
        let path = write_wav16(&[500i16; 200]);
        let mut voice = synth_voice();
        voice.synth = None;
        voice.samples = vec![SampleRef {
            path: path.clone(),
            f0_hz: 440.0,
        }];

        let mut ev = note("note", vec![69.0], &[]);
        ev.params.insert("gest".to_string(), "h0".to_string());
        ev.params.insert("gsrc".to_string(), "raw".to_string());

        let mut gestures = Map::new();
        gestures.insert("h0".to_string(), small_gesture(440.0, 0.0, 0.1));

        let cache = SampleCache::new();
        let mut bad = Vec::new();
        let step = resolve(
            &voice, &ev, 0.1, 5, "s", 440.0, &gestures, None, &cache, &mut bad,
        )
        .unwrap();
        assert!(matches!(step, SourceStep::Rendered(_)));
        assert_eq!(bad.len(), 1);
        assert!(bad[0].contains("no tape header"), "{}", bad[0]);
        std::fs::remove_file(path).unwrap();
    }

    /// `gest=` without `gsrc=raw`: the pack-sample-polyline path anchors
    /// on `glayer=` (default `"resolved"`). Python does `g.get(layer,
    /// [])` — any value that isn't exactly `"resolved"` or `"octave"` is
    /// an unknown dict key, so it must fall through to `[]` (too sparse)
    /// rather than a wildcard match silently borrowing the `resolved`
    /// anchors. The gesture here carries plenty of `resolved` anchors —
    /// if an unknown `glayer=` were ever treated as "resolved", this
    /// would quote successfully instead of reporting bad and falling
    /// back to plain transposition.
    #[test]
    fn gest_polyline_with_an_unknown_glayer_reports_too_sparse_and_falls_back() {
        let path = write_wav16(&[500i16; 200]);
        let mut voice = synth_voice();
        voice.synth = None;
        voice.samples = vec![SampleRef {
            path: path.clone(),
            f0_hz: 440.0,
        }];

        let mut ev = note("note", vec![69.0], &[]); // A4 = 440 Hz = smp.f0_hz -> st = 0
        ev.params.insert("gest".to_string(), "h0".to_string());
        ev.params.insert("glayer".to_string(), "bogus".to_string());

        let mut g = small_gesture(440.0, 0.0, 1.0);
        g.resolved = vec![(0.0, 440.0), (0.5, 460.0), (1.0, 440.0)];
        let mut gestures = Map::new();
        gestures.insert("h0".to_string(), g);

        let cache = SampleCache::new();
        let mut bad = Vec::new();
        let step = resolve(
            &voice, &ev, 0.1, 7, "s", 440.0, &gestures, None, &cache, &mut bad,
        )
        .unwrap();
        let SourceStep::Rendered(x) = step else {
            panic!("expected a rendered buffer")
        };
        // st = 12*log2(440/440) = 0 -> varispeed(x, 0.0) is a no-op, so a
        // correct fallback returns the untouched 200-sample source, not a
        // pitch_polyline reshape (which would resample to the gesture's
        // 1.0s span, i.e. 48_000 samples).
        assert_eq!(x.len(), 200, "expected the plain (untransposed) source");
        assert_eq!(bad.len(), 1, "{bad:?}");
        assert!(bad[0].contains("layer bogus too sparse"), "{}", bad[0]);
        std::fs::remove_file(path).unwrap();
    }

    /// `s=`/`off=`/`tau=` are each a bare `float(...)` in the oracle, no
    /// `try/except` — a malformed-but-present value must refuse the
    /// whole event rather than silently picking sample 1 / skipping the
    /// trim / falling back to the default tau.
    #[test]
    fn malformed_s_off_or_tau_refuses_instead_of_defaulting() {
        let path = write_wav16(&[500i16; 200]);
        let mut voice = synth_voice();
        voice.synth = None;
        voice.samples = vec![SampleRef {
            path: path.clone(),
            f0_hz: 0.0,
        }];
        let cache = SampleCache::new();
        let gestures = Map::new();

        let mut ev = note("note", vec![69.0], &[]);
        ev.params.insert("s".to_string(), "second".to_string());
        let mut bad = Vec::new();
        let err = resolve(
            &voice, &ev, 0.2, 3, "s", 440.0, &gestures, None, &cache, &mut bad,
        )
        .unwrap_err();
        assert!(
            matches!(err, RenderError::Invalid(ref m) if m.starts_with("b3 s:") && m.contains("s=\"second\"")),
            "{err}"
        );

        let mut ev = note("note", vec![69.0], &[]);
        ev.params.insert("off".to_string(), "soon".to_string());
        let err = resolve(
            &voice, &ev, 0.2, 3, "s", 440.0, &gestures, None, &cache, &mut bad,
        )
        .unwrap_err();
        assert!(
            matches!(err, RenderError::Invalid(ref m) if m.contains("off=\"soon\"")),
            "{err}"
        );

        let mut ev = note("note", vec![69.0], &[]);
        ev.params.insert("tau".to_string(), "slow".to_string());
        let err = resolve(
            &voice, &ev, 0.2, 3, "s", 440.0, &gestures, None, &cache, &mut bad,
        )
        .unwrap_err();
        assert!(
            matches!(err, RenderError::Invalid(ref m) if m.contains("tau=\"slow\"")),
            "{err}"
        );

        std::fs::remove_file(path).unwrap();
    }
}
