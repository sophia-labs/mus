//! The sample pack and voice table — `mus_audio.py`'s `Sample`/`Voice`
//! dataclasses, `load_pack` (line 572), and the render-time voice-building
//! loop (lines 745-774).

use std::cell::RefCell;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::rc::Rc;

use mus_text::ProposalInstrument;
use serde_json::Value;

use crate::util::{midi_to_hz, note_to_midi, require_f64, with_context};
use crate::RenderError;

/// `STRUCTURAL_PARAMS` (line 568): instrument params that shape the
/// `Voice` itself rather than becoming a per-event default.
pub const STRUCTURAL_PARAMS: &[&str] = &[
    "voice", "sample", "root", "mode", "gain", "pan", "send", "duck",
];

/// `SYNTH_KEYS` (line 228): synth-patch params. `"fdec"` is listed here
/// (classification only) but read by nothing downstream — `mus_dsp::synth
/// ::Patch` doesn't have a field for it either, matching the oracle, which
/// never reads `patch["fdec"]` inside `synth_note`.
pub const SYNTH_KEYS: &[&str] = &[
    "synth", "osc2", "mix2", "detune", "sub", "cutoff", "famt", "fdec", "satk", "sdec", "ssus",
    "srel", "sus", "damp", "pos", "pick", "body", "strum", "pm",
];

#[derive(Debug, Clone)]
pub struct SampleRef {
    pub path: PathBuf,
    pub f0_hz: f64,
}

#[derive(Debug, Clone)]
pub struct Voice {
    pub abbrev: String,
    pub samples: Vec<SampleRef>,
    pub mode: String,
    pub gain_db: f64,
    pub pan: f64,
    pub send: f64,
    pub defaults: BTreeMap<String, String>,
    /// `Some` for a `synth=`-declared instrument: the instrument-level
    /// synth-key subset of its params (`synth_patch`, line 755), merged
    /// with event-level overrides at render time.
    pub synth: Option<BTreeMap<String, String>>,
    /// Sidechain opt-out (`duck=0|no|off` on the instrument declaration;
    /// `mus_audio.py` line 1131-1133). Read from the raw instrument
    /// params, not `defaults` — `"duck"` is in `STRUCTURAL_PARAMS`, so it
    /// never lands there.
    pub ducks: bool,
}

/// `mus_audio.load_pack` (line 572): `voices` + `noise` merged into one
/// abbrev → sample-list table. Loading resolves each `Voice`'s sample list
/// once at build time; decoding the audio itself is [`SampleCache`]'s job
/// (shared with `sample=` overrides, which never go through a pack at
/// all).
pub struct Pack {
    voices: BTreeMap<String, Vec<SampleRef>>,
}

/// Decode-and-cache audio by path, shared by every sample-backed voice
/// (pack-voice *and* `sample=` override alike) and the `# tape:` header —
/// `librosa.load(path, sr=SR, mono=True)` runs once per distinct file
/// regardless of how many events replay it (`Sample.load`'s own `if
/// self.audio is None` cache, `mus_audio.py` lines 545-549).
pub struct SampleCache {
    cache: RefCell<BTreeMap<PathBuf, Rc<Vec<f32>>>>,
}

impl Default for SampleCache {
    fn default() -> Self {
        Self::new()
    }
}

impl SampleCache {
    pub fn new() -> Self {
        Self {
            cache: RefCell::new(BTreeMap::new()),
        }
    }

    pub fn load(&self, path: &Path) -> Result<Rc<Vec<f32>>, RenderError> {
        if let Some(hit) = self.cache.borrow().get(path) {
            return Ok(hit.clone());
        }
        let audio = mus_dsp::pitch::load_decode(path)
            .map_err(|e| RenderError::Wav(format!("{}: {e}", path.display())))?;
        let rc = Rc::new(audio);
        self.cache
            .borrow_mut()
            .insert(path.to_path_buf(), rc.clone());
        Ok(rc)
    }
}

impl Pack {
    pub fn load(path: &Path) -> Result<Self, RenderError> {
        let bytes = std::fs::read(path)?;
        let data: Value = serde_json::from_slice(&bytes)?;
        let base = path.parent().ok_or_else(|| {
            RenderError::Invalid(format!("pack {} has no parent dir", path.display()))
        })?;
        let mut voices = BTreeMap::new();
        if let Some(vmap) = data.get("voices").and_then(Value::as_object) {
            for (name, v) in vmap {
                let samples = v
                    .get("samples")
                    .and_then(Value::as_array)
                    .map(|arr| {
                        arr.iter()
                            .filter_map(|s| {
                                let file = s.get("file")?.as_str()?;
                                let f0 = s.get("f0_hz").and_then(Value::as_f64).unwrap_or(0.0);
                                Some(SampleRef {
                                    path: base.join(file),
                                    f0_hz: f0,
                                })
                            })
                            .collect()
                    })
                    .unwrap_or_default();
                voices.insert(name.clone(), samples);
            }
        }
        if let Some(nmap) = data.get("noise").and_then(Value::as_object) {
            for (name, n) in nmap {
                if let Some(file) = n.get("file").and_then(Value::as_str) {
                    voices.insert(
                        name.clone(),
                        vec![SampleRef {
                            path: base.join(file),
                            f0_hz: 0.0,
                        }],
                    );
                }
            }
        }
        Ok(Self { voices })
    }

    pub fn voice(&self, key: &str) -> Option<Vec<SampleRef>> {
        self.voices.get(key).cloned()
    }
}

/// The render-time voice table (`mus_audio.py` lines 745-774). Returns the
/// built voices in instrument-declaration order (matching Python dict
/// insertion order, which the render loop then iterates) plus one warning
/// string per skipped track (line 757's stderr print — kept out of
/// `stats.bad` since Python never folds it into that list either).
///
/// `gain=`/`pan=`/`send=` (lines 768-770) are each a bare `float(p.get(k,
/// default))` in the oracle, no `try/except` — a malformed-but-present
/// value aborts the whole render there, so a refusal here (rather than
/// silently falling back to the default) is the matching behavior.
pub fn build_voices(
    instruments: &[ProposalInstrument],
    pack: Option<&Pack>,
    score_dir: &Path,
    a4: f64,
) -> Result<(Vec<Voice>, Vec<String>), RenderError> {
    let mut voices = Vec::new();
    let mut warnings = Vec::new();
    for inst in instruments {
        let p = &inst.params;
        let mut samples: Vec<SampleRef> = match p.get("voice") {
            Some(vkey) => pack.and_then(|pk| pk.voice(vkey)).unwrap_or_default(),
            None => Vec::new(),
        };
        if let Some(sample_path) = p.get("sample") {
            samples = vec![SampleRef {
                path: score_dir.join(sample_path),
                f0_hz: 0.0,
            }];
        }
        let synth_patch: Option<BTreeMap<String, String>> = if p.contains_key("synth") {
            Some(
                SYNTH_KEYS
                    .iter()
                    .filter_map(|k| p.get(*k).map(|v| (k.to_string(), v.clone())))
                    .collect(),
            )
        } else {
            None
        };
        if samples.is_empty() && synth_patch.is_none() {
            warnings.push(format!("no samples for track '{}' — skipped", inst.abbrev));
            continue;
        }
        if let Some(root) = p.get("root") {
            // `midi_to_hz(rm, a4) if rm else 0.0` (line 761): Python's `if
            // rm` is falsy for `None` *and* for a fractional MIDI value of
            // exactly `0.0` (`root=C-1`) alike — `note_to_midi` returning
            // `Some(0.0)` must fall to the `0.0` literal too, not through
            // `midi_to_hz`.
            let root_hz = note_to_midi(root)
                .filter(|&m| m != 0.0)
                .map(|m| midi_to_hz(m, a4))
                .unwrap_or(0.0);
            for s in samples.iter_mut() {
                if s.f0_hz <= 0.0 {
                    s.f0_hz = root_hz;
                }
            }
        }
        let defaults: BTreeMap<String, String> = p
            .iter()
            .filter(|(k, _)| {
                !STRUCTURAL_PARAMS.contains(&k.as_str()) && !SYNTH_KEYS.contains(&k.as_str())
            })
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect();
        let duck_raw = p.get("duck").cloned().unwrap_or_else(|| "1".to_string());
        let ctx = || format!("instrument '{}'", inst.abbrev);
        voices.push(Voice {
            abbrev: inst.abbrev.clone(),
            samples,
            mode: p
                .get("mode")
                .cloned()
                .unwrap_or_else(|| "varispeed".to_string()),
            gain_db: require_f64(p, "gain", 0.0).map_err(|e| with_context(&ctx(), e))?,
            pan: require_f64(p, "pan", 0.0).map_err(|e| with_context(&ctx(), e))?,
            send: require_f64(p, "send", 0.12).map_err(|e| with_context(&ctx(), e))?,
            defaults,
            synth: synth_patch,
            ducks: !matches!(duck_raw.as_str(), "0" | "no" | "off"),
        });
    }
    Ok((voices, warnings))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn inst(abbrev: &str, params: &[(&str, &str)]) -> ProposalInstrument {
        ProposalInstrument {
            abbrev: abbrev.into(),
            name: abbrev.into(),
            clef: "treble".into(),
            params: params
                .iter()
                .map(|(k, v)| (k.to_string(), v.to_string()))
                .collect(),
        }
    }

    #[test]
    fn synth_track_needs_no_pack_and_carries_synth_keys_only_in_patch() {
        let (voices, warnings) = build_voices(
            &[inst(
                "s",
                &[
                    ("synth", "saw"),
                    ("cutoff", "800"),
                    ("gain", "3"),
                    ("lpf", "500"),
                ],
            )],
            None,
            Path::new("."),
            440.0,
        )
        .unwrap();
        assert!(warnings.is_empty());
        assert_eq!(voices.len(), 1);
        let v = &voices[0];
        assert!(v.samples.is_empty());
        let synth = v.synth.as_ref().unwrap();
        assert_eq!(synth.get("synth").map(String::as_str), Some("saw"));
        assert_eq!(synth.get("cutoff").map(String::as_str), Some("800"));
        assert!(!synth.contains_key("gain"));
        assert_eq!(v.gain_db, 3.0);
        // "lpf" is neither structural nor a synth key -> becomes a default.
        assert_eq!(v.defaults.get("lpf").map(String::as_str), Some("500"));
    }

    #[test]
    fn missing_source_track_is_skipped_with_a_warning() {
        let (voices, warnings) =
            build_voices(&[inst("x", &[])], None, Path::new("."), 440.0).unwrap();
        assert!(voices.is_empty());
        assert_eq!(warnings.len(), 1);
        assert!(warnings[0].contains("'x'"));
    }

    #[test]
    fn root_at_exactly_midi_zero_falls_back_to_0_hz_like_pythons_falsy_check() {
        // `root=C-1` is `note_to_midi` = 0.0 exactly — Python's `midi_to_hz(rm,
        // a4) if rm else 0.0` treats that `0.0` as falsy just like `None`, so
        // the fallback sample f0 must be the literal `0.0`, not
        // `midi_to_hz(0.0, a4)` (~8.18 Hz at A440).
        let (voices, _) = build_voices(
            &[inst("x", &[("sample", "a.wav"), ("root", "C-1")])],
            None,
            Path::new("."),
            440.0,
        )
        .unwrap();
        assert_eq!(voices[0].samples[0].f0_hz, 0.0);

        // A genuine, non-zero root still resolves normally.
        let (voices, _) = build_voices(
            &[inst("x", &[("sample", "a.wav"), ("root", "A4")])],
            None,
            Path::new("."),
            440.0,
        )
        .unwrap();
        assert!((voices[0].samples[0].f0_hz - 440.0).abs() < 1e-9);
    }

    /// `gain=`/`pan=`/`send=` are bare `float(...)` in the oracle, no
    /// `try/except` — a malformed-but-present value must refuse the whole
    /// render, not silently fall back to the instrument default (the
    /// prior port's bug: `p.get("gain").and_then(|v| v.parse().ok()).
    /// unwrap_or(0.0)` treated a typo the same as an absent key).
    #[test]
    fn malformed_instrument_level_gain_pan_or_send_refuses_rather_than_defaulting() {
        let err = build_voices(
            &[inst("x", &[("sample", "a.wav"), ("gain", "loud")])],
            None,
            Path::new("."),
            440.0,
        )
        .unwrap_err();
        assert!(
            matches!(err, RenderError::Invalid(ref m) if m.contains("'x'") && m.contains("gain")),
            "{err}"
        );

        let err = build_voices(
            &[inst("x", &[("sample", "a.wav"), ("pan", "left")])],
            None,
            Path::new("."),
            440.0,
        )
        .unwrap_err();
        assert!(
            matches!(err, RenderError::Invalid(ref m) if m.contains("pan")),
            "{err}"
        );

        let err = build_voices(
            &[inst("x", &[("sample", "a.wav"), ("send", "lots")])],
            None,
            Path::new("."),
            440.0,
        )
        .unwrap_err();
        assert!(
            matches!(err, RenderError::Invalid(ref m) if m.contains("send")),
            "{err}"
        );

        // An absent key is unaffected — still defaults.
        let (voices, _) = build_voices(
            &[inst("x", &[("sample", "a.wav")])],
            None,
            Path::new("."),
            440.0,
        )
        .unwrap();
        assert_eq!(voices[0].gain_db, 0.0);
        assert_eq!(voices[0].send, 0.12);
    }
}
