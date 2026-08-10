//! `mus-engine` — WF1's deterministic sampler face.
//!
//! The engine accepts the already-projected `ScoreGraph`; it does not invent
//! lineages or resolve forks. A render chooses each graph head exactly as the
//! graph contract specifies, and the CLI records that choice in its receipt.
//!
//! Resampling uses rubato's high-quality sinc profile: 256 taps, Blackman-
//! Harris window, linear sinc interpolation, and 160× oversampling. The
//! profile is intentionally fixed here so changing a library default cannot
//! change a render silently.

use hound::{SampleFormat, WavReader};
use mus_graph::timing::{BarMap, TimingError};
use mus_graph::ScoreGraph;
use mus_oplog::{EventKind, EventState};
use rubato::{
    Resampler, SincFixedIn, SincInterpolationParameters, SincInterpolationType, WindowFunction,
};
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, VecDeque};
use std::fmt::{Display, Formatter};
use std::path::{Path, PathBuf};

pub const SAMPLE_RATE: u32 = 48_000;
pub const ENGINE_VERSION: &str = "mus-engine/0.1.0-wf1";

const DYN_DB: &[(&str, f32)] = &[
    ("ppp", -30.0),
    ("pp", -25.0),
    ("p", -20.0),
    ("mp", -15.0),
    ("mf", -11.0),
    ("f", -7.0),
    ("ff", -3.5),
    ("fff", 0.0),
    ("sfz", -2.0),
    ("sf", -3.0),
];
const ART_GAIN: &[(&str, f32)] = &[
    ("acc", 4.0),
    ("marc", 6.0),
    ("sfz", 7.0),
    ("stress", 2.5),
    ("unstress", -4.0),
];
const ART_SHORTEN: &[(&str, f32)] = &[
    ("stac", 0.40),
    ("stacciss", 0.25),
    ("spic", 0.35),
    ("detlg", 0.75),
];

#[derive(Debug)]
pub enum RenderError {
    Io(std::io::Error),
    Json(serde_json::Error),
    Wav(hound::Error),
    Timing(TimingError),
    Unsupported(UnsupportedConstruct),
    Invalid(String),
}

impl Display for RenderError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(e) => write!(f, "I/O error: {e}"),
            Self::Json(e) => write!(f, "manifest error: {e}"),
            Self::Wav(e) => write!(f, "WAV error: {e}"),
            Self::Timing(e) => write!(f, "timing error: {e:?}"),
            Self::Unsupported(e) => write!(f, "unsupported construct: {e}"),
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
impl From<hound::Error> for RenderError {
    fn from(value: hound::Error) -> Self {
        Self::Wav(value)
    }
}
impl From<TimingError> for RenderError {
    fn from(value: TimingError) -> Self {
        Self::Timing(value)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UnsupportedConstruct {
    pub construct: String,
    pub location: String,
}

impl Display for UnsupportedConstruct {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        write!(f, "{} at {}", self.construct, self.location)
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

#[derive(Debug, Clone, Deserialize)]
struct Manifest {
    #[serde(default)]
    voices: BTreeMap<String, ManifestVoice>,
    #[serde(default)]
    noise: BTreeMap<String, ManifestNoise>,
}

#[derive(Debug, Clone, Deserialize)]
struct ManifestVoice {
    samples: Vec<ManifestSample>,
}

#[derive(Debug, Clone, Deserialize)]
struct ManifestNoise {
    file: String,
}

#[derive(Debug, Clone, Deserialize)]
struct ManifestSample {
    file: String,
    #[serde(default)]
    f0_hz: Option<f32>,
}

#[derive(Debug, Clone)]
struct SampleRef {
    path: PathBuf,
    f0_hz: f32,
}

#[derive(Debug)]
struct Pack {
    voices: BTreeMap<String, Vec<SampleRef>>,
    cache: BTreeMap<PathBuf, Vec<f32>>,
}

impl Pack {
    fn load(path: &Path) -> Result<Self, RenderError> {
        let data: Manifest = serde_json::from_slice(&std::fs::read(path)?)?;
        let base = path
            .parent()
            .ok_or_else(|| RenderError::Invalid("pack has no parent directory".into()))?;
        let mut voices = BTreeMap::new();
        for (name, voice) in data.voices {
            voices.insert(
                name,
                voice
                    .samples
                    .into_iter()
                    .map(|sample| SampleRef {
                        path: base.join(sample.file),
                        f0_hz: sample.f0_hz.unwrap_or(0.0),
                    })
                    .collect(),
            );
        }
        for (name, noise) in data.noise {
            voices.insert(
                name,
                vec![SampleRef {
                    path: base.join(noise.file),
                    f0_hz: 0.0,
                }],
            );
        }
        Ok(Self {
            voices,
            cache: BTreeMap::new(),
        })
    }

    fn load_sample(&mut self, sample: &SampleRef) -> Result<Vec<f32>, RenderError> {
        if let Some(audio) = self.cache.get(&sample.path) {
            return Ok(audio.clone());
        }
        let mut reader = WavReader::open(&sample.path)?;
        let spec = reader.spec();
        let channels = usize::from(spec.channels);
        if channels == 0 {
            return Err(RenderError::Invalid(format!(
                "sample {} has zero channels",
                sample.path.display()
            )));
        }
        let mut mono = Vec::new();
        match spec.sample_format {
            SampleFormat::Float => {
                let mut frame = 0.0_f32;
                for (index, value) in reader.samples::<f32>().enumerate() {
                    frame += value?;
                    if index % channels == channels - 1 {
                        mono.push(frame / channels as f32);
                        frame = 0.0;
                    }
                }
            }
            SampleFormat::Int => {
                let scale = (1_i64 << (spec.bits_per_sample.saturating_sub(1))) as f32;
                let mut frame = 0.0_f32;
                for (index, value) in reader.samples::<i32>().enumerate() {
                    frame += value? as f32 / scale;
                    if index % channels == channels - 1 {
                        mono.push(frame / channels as f32);
                        frame = 0.0;
                    }
                }
            }
        }
        if spec.sample_rate != SAMPLE_RATE {
            mono = resample(&mono, SAMPLE_RATE as f64 / spec.sample_rate as f64)?;
        }
        self.cache.insert(sample.path.clone(), mono.clone());
        Ok(mono)
    }
}

/// Render the graph using resources relative to `score_dir`.
pub fn render(graph: &ScoreGraph, score_dir: &Path) -> Result<RenderedAudio, RenderError> {
    validate_supported(graph)?;
    let timing = BarMap::for_graph(graph)?;
    let pack = graph
        .headers
        .get("pack")
        .map(|path| Pack::load(&score_dir.join(path)))
        .transpose()?;
    let mut pack = pack;
    let a4 = parse_tuning(graph.headers.get("tuning"))?;
    let target_rms_db = graph
        .headers
        .get("master")
        .and_then(|raw| raw.split("rms=").nth(1))
        .and_then(|v| v.split_whitespace().next())
        .and_then(|v| v.parse::<f32>().ok())
        .unwrap_or(-17.0);
    let total_frames = ((timing.total_seconds + 4.0) * SAMPLE_RATE as f64).ceil() as usize;
    let mut mix = vec![0.0_f32; total_frames * 2];

    for (lineage, state, _) in graph.current_events() {
        let instrument = graph
            .instruments
            .iter()
            .find(|instrument| instrument.abbrev == state.track)
            .ok_or_else(|| {
                RenderError::Invalid(format!("event track {} is undeclared", state.track))
            })?;
        let params = effective_params(instrument.params.clone(), &state.params);
        let bar = timing.bars.get(&state.bar).ok_or_else(|| {
            RenderError::Invalid(format!(
                "event {} uses missing bar {}",
                lineage.0, state.bar
            ))
        })?;
        let onset = bar.start_seconds + state.onset_ql.as_f64() * bar.seconds_per_quarter;
        let slot_seconds = (state.dur_ql.as_f64() * bar.seconds_per_quarter).max(0.001);
        let mut source = sample_for(&params, pack.as_mut(), score_dir, a4)?;
        let offset = params
            .get("off")
            .and_then(|v| v.parse::<f32>().ok())
            .unwrap_or(0.0)
            .max(0.0);
        let skip = (offset * SAMPLE_RATE as f32 / 1000.0) as usize;
        if skip < source.audio.len() {
            source.audio = source.audio[skip..].to_vec();
        } else {
            source.audio.clear();
        }
        if state.flags.contains("reverse") {
            source.audio.reverse();
        }
        if source.audio.len() < 8 {
            continue;
        }
        let mut rendered = render_source(&source.audio, &source.f0_hz, state, &params, a4)?;
        if params.get("str").map(String::as_str) == Some("fit") {
            rendered = resample(
                &rendered,
                slot_seconds * SAMPLE_RATE as f64 / rendered.len() as f64,
            )?;
        }
        let slot_frames = (slot_seconds * SAMPLE_RATE as f64).round().max(1.0) as usize;
        if state.flags.contains("gate") {
            rendered.truncate(slot_frames);
        }
        for (name, fraction) in ART_SHORTEN {
            if state.flags.contains(*name) {
                rendered.truncate((slot_frames as f32 * fraction).round().max(64.0) as usize);
            }
        }
        if state.flags.contains("fer") {
            rendered = resample(&rendered, 1.75)?;
        }
        apply_envelope(&mut rendered, &params)?;
        apply_filters(&mut rendered, &params);
        let gain_db = dynamic_db(state.dynamic.as_deref())
            + params
                .get("gain")
                .and_then(|v| v.parse::<f32>().ok())
                .unwrap_or(0.0)
            + state
                .flags
                .iter()
                .filter_map(|flag| {
                    ART_GAIN
                        .iter()
                        .find(|(name, _)| *name == flag)
                        .map(|(_, db)| *db)
                })
                .sum::<f32>();
        let gain = 10.0_f32.powf(gain_db / 20.0);
        let (pan_start, pan_end) = parameter_pair(&params, "pan", 0.0);
        let start = (onset * SAMPLE_RATE as f64).round() as usize;
        place(&mut mix, start, &rendered, gain, pan_start, pan_end);
    }
    master(&mut mix, target_rms_db, 0.89);
    Ok(RenderedAudio {
        samples: mix,
        sample_rate: SAMPLE_RATE,
    })
}

fn validate_supported(graph: &ScoreGraph) -> Result<(), RenderError> {
    for instrument in &graph.instruments {
        if instrument.params.contains_key("synth") {
            return Err(RenderError::Unsupported(UnsupportedConstruct {
                construct: "synth".into(),
                location: format!("instrument {}", instrument.abbrev),
            }));
        }
        if instrument.params.get("mode").map(String::as_str) == Some("vocoder") {
            return Err(RenderError::Unsupported(UnsupportedConstruct {
                construct: "vocoder transposition".into(),
                location: format!("instrument {}", instrument.abbrev),
            }));
        }
    }
    for (lineage, state, _) in graph.current_events() {
        if state.quote.is_some() {
            return Err(RenderError::Unsupported(UnsupportedConstruct {
                construct: "gesture quotation".into(),
                location: format!("event {}", lineage.0),
            }));
        }
        for key in state.params.keys() {
            if matches!(
                key.as_str(),
                "chop"
                    | "ring"
                    | "rwet"
                    | "glow"
                    | "ghold"
                    | "gwarble"
                    | "gharm"
                    | "pump"
                    | "drive"
                    | "dist"
                    | "crush"
                    | "decim"
                    | "stut"
                    | "duck"
                    | "haas"
                    | "send"
            ) {
                return Err(RenderError::Unsupported(UnsupportedConstruct {
                    construct: key.clone(),
                    location: format!("event {}", lineage.0),
                }));
            }
            if key == "mode" && state.params.get(key).map(String::as_str) == Some("vocoder") {
                return Err(RenderError::Unsupported(UnsupportedConstruct {
                    construct: "vocoder transposition".into(),
                    location: format!("event {}", lineage.0),
                }));
            }
            if key == "str"
                && state
                    .params
                    .get(key)
                    .map(String::as_str)
                    .is_some_and(|value| value != "fit")
            {
                return Err(RenderError::Unsupported(UnsupportedConstruct {
                    construct: "arbitrary time stretch".into(),
                    location: format!("event {}", lineage.0),
                }));
            }
        }
    }
    if graph.headers.contains_key("sidechain") {
        return Err(RenderError::Unsupported(UnsupportedConstruct {
            construct: "sidechain".into(),
            location: "score header".into(),
        }));
    }
    if graph.headers.contains_key("reverb") {
        return Err(RenderError::Unsupported(UnsupportedConstruct {
            construct: "reverb room".into(),
            location: "score header".into(),
        }));
    }
    // Swing is a performance annotation in the graph (R6). WF1 intentionally
    // leaves onsets straight; the annotation must not alter stored timing.
    Ok(())
}

#[derive(Debug)]
struct Source {
    audio: Vec<f32>,
    f0_hz: f32,
}

fn sample_for(
    params: &BTreeMap<String, String>,
    pack: Option<&mut Pack>,
    score_dir: &Path,
    a4: f32,
) -> Result<Source, RenderError> {
    if let Some(path) = params.get("sample") {
        let reference = SampleRef {
            path: score_dir.join(path),
            f0_hz: params
                .get("root")
                .and_then(|root| pitch_to_hz(root, a4))
                .unwrap_or(0.0),
        };
        let audio = load_direct(&reference)?;
        return Ok(Source {
            audio,
            f0_hz: reference.f0_hz,
        });
    }
    let pack = pack.ok_or_else(|| RenderError::Invalid("sample event has no pack".into()))?;
    let voice = params
        .get("voice")
        .ok_or_else(|| RenderError::Invalid("instrument has no voice or sample".into()))?;
    let samples = pack
        .voices
        .get(voice)
        .ok_or_else(|| RenderError::Invalid(format!("pack has no voice {voice}")))?;
    if samples.is_empty() {
        return Err(RenderError::Invalid(format!(
            "voice {voice} has no samples"
        )));
    }
    let index = params
        .get("s")
        .and_then(|v| v.parse::<usize>().ok())
        .unwrap_or(1)
        .saturating_sub(1)
        .min(samples.len() - 1);
    let sample = samples[index].clone();
    let audio = pack.load_sample(&sample)?;
    let f0_hz = if sample.f0_hz > 0.0 {
        sample.f0_hz
    } else {
        params
            .get("root")
            .and_then(|root| pitch_to_hz(root, a4))
            .unwrap_or(0.0)
    };
    Ok(Source { audio, f0_hz })
}

fn load_direct(sample: &SampleRef) -> Result<Vec<f32>, RenderError> {
    let mut reader = WavReader::open(&sample.path)?;
    let spec = reader.spec();
    let channels = usize::from(spec.channels.max(1));
    let mut out = Vec::new();
    let scale = (1_i64 << (spec.bits_per_sample.saturating_sub(1))) as f32;
    let mut frame = 0.0;
    match spec.sample_format {
        SampleFormat::Float => {
            for (i, value) in reader.samples::<f32>().enumerate() {
                frame += value?;
                if i % channels == channels - 1 {
                    out.push(frame / channels as f32);
                    frame = 0.0;
                }
            }
        }
        SampleFormat::Int => {
            for (i, value) in reader.samples::<i32>().enumerate() {
                frame += value? as f32 / scale;
                if i % channels == channels - 1 {
                    out.push(frame / channels as f32);
                    frame = 0.0;
                }
            }
        }
    }
    if spec.sample_rate != SAMPLE_RATE {
        resample(&out, SAMPLE_RATE as f64 / spec.sample_rate as f64)
    } else {
        Ok(out)
    }
}

fn render_source(
    source: &[f32],
    f0_hz: &f32,
    state: &EventState,
    params: &BTreeMap<String, String>,
    a4: f32,
) -> Result<Vec<f32>, RenderError> {
    if *f0_hz <= 0.0 || state.kind == EventKind::Unpitched {
        let (start, end) = parameter_pair(params, "st", 0.0);
        if (start - end).abs() > f32::EPSILON {
            return Ok(ramp_resample(source, start, end));
        }
        return resample(source, 1.0 / 2.0_f64.powf(start as f64 / 12.0));
    }
    let first = state
        .pitches_midi_cents
        .first()
        .copied()
        .ok_or_else(|| RenderError::Invalid("pitched sampler event has no pitch".into()))?;
    let start = 12.0 * (pitch_cents_to_hz(first, a4) / *f0_hz).log2();
    let end = state
        .gliss_target_midi_cents
        .map(|target| 12.0 * (pitch_cents_to_hz(target, a4) / *f0_hz).log2())
        .unwrap_or(start);
    if state.kind == EventKind::Chord && state.pitches_midi_cents.len() > 1 {
        let mut voices = Vec::new();
        for pitch in &state.pitches_midi_cents {
            let semitones = 12.0 * (pitch_cents_to_hz(*pitch, a4) / *f0_hz).log2();
            voices.push(resample(
                source,
                1.0 / 2.0_f64.powf(semitones as f64 / 12.0),
            )?);
        }
        let len = voices.iter().map(Vec::len).max().unwrap_or(0);
        let mut out = vec![0.0; len];
        for voice in voices {
            for (index, value) in voice.into_iter().enumerate() {
                out[index] += value;
            }
        }
        let scale = (state.pitches_midi_cents.len() as f32).sqrt();
        for value in &mut out {
            *value /= scale;
        }
        Ok(out)
    } else if (start - end).abs() > 0.001 {
        Ok(ramp_resample(source, start, end))
    } else {
        resample(source, 1.0 / 2.0_f64.powf(start as f64 / 12.0))
    }
}

fn ramp_resample(source: &[f32], start: f32, end: f32) -> Vec<f32> {
    let rate0 = 2.0_f64.powf(start as f64 / 12.0);
    let rate1 = 2.0_f64.powf(end as f64 / 12.0);
    let n = (source.len() as f64 / ((rate0 + rate1) * 0.5))
        .round()
        .max(8.0) as usize;
    let mut out = Vec::with_capacity(n);
    for index in 0..n {
        let t = index as f64 / n.max(1) as f64;
        let rate = rate0 * (rate1 / rate0).powf(t);
        let position = (index as f64 * rate).min((source.len() - 1) as f64);
        let left = position.floor() as usize;
        let frac = position - left as f64;
        let right = (left + 1).min(source.len() - 1);
        out.push((source[left] as f64 * (1.0 - frac) + source[right] as f64 * frac) as f32);
    }
    out
}

fn resample(source: &[f32], ratio: f64) -> Result<Vec<f32>, RenderError> {
    if source.len() < 8 || (ratio - 1.0).abs() < 1e-6 {
        return Ok(source.to_vec());
    }
    let params = SincInterpolationParameters {
        sinc_len: 256,
        f_cutoff: 0.95,
        interpolation: SincInterpolationType::Linear,
        oversampling_factor: 160,
        window: WindowFunction::BlackmanHarris2,
    };
    let mut resampler = SincFixedIn::<f32>::new(ratio, 64.0, params, source.len(), 1)
        .map_err(|e| RenderError::Invalid(format!("rubato setup: {e}")))?;
    let output = resampler
        .process(&[source.to_vec()], None)
        .map_err(|e| RenderError::Invalid(format!("rubato process: {e}")))?;
    Ok(output.into_iter().next().unwrap_or_default())
}

fn apply_envelope(audio: &mut [f32], params: &BTreeMap<String, String>) -> Result<(), RenderError> {
    let attack = params
        .get("atk")
        .and_then(|v| v.parse::<f32>().ok())
        .unwrap_or(0.003)
        .max(0.0015);
    let release = params
        .get("rel")
        .and_then(|v| v.parse::<f32>().ok())
        .unwrap_or(0.035)
        .max(0.004);
    let attack = ((attack * SAMPLE_RATE as f32) as usize).min(audio.len() / 3);
    let release = ((release * SAMPLE_RATE as f32) as usize).min(audio.len() / 2);
    for (index, sample) in audio.iter_mut().take(attack).enumerate() {
        *sample *= (index as f32 / attack.max(1) as f32).powf(0.7);
    }
    for (index, sample) in audio.iter_mut().rev().take(release).enumerate() {
        *sample *= (1.0 - index as f32 / release.max(1) as f32).powf(1.5);
    }
    Ok(())
}

fn place(mix: &mut [f32], start: usize, source: &[f32], gain: f32, p0: f32, p1: f32) {
    if start >= mix.len() / 2 {
        return;
    }
    let max_frames = (mix.len() / 2 - start).min(source.len());
    for index in 0..max_frames {
        let t = index as f32 / max_frames.saturating_sub(1).max(1) as f32;
        let pan = (p0 + (p1 - p0) * t).clamp(-1.0, 1.0);
        let theta = (pan + 1.0) * std::f32::consts::FRAC_PI_4;
        let value = source[index] * gain;
        mix[(start + index) * 2] += value * theta.cos();
        mix[(start + index) * 2 + 1] += value * theta.sin();
    }
}

/// Master chain: RMS pre-gain establishes the requested body level; a
/// windowed maximum limiter catches the transient crest that this material
/// has; tanh rounds the residual edge; final RMS/ceiling landing honors both
/// the user's RMS target and a hard -1 dBFS ceiling.
fn master(mix: &mut [f32], target_rms_db: f32, ceiling: f32) {
    let rms = (mix.iter().map(|v| v * v).sum::<f32>() / mix.len().max(1) as f32).sqrt();
    if rms > 0.0 {
        let gain = 10.0_f32.powf((target_rms_db - dbfs(rms)) / 20.0);
        for value in mix.iter_mut() {
            *value *= gain;
        }
    }
    let window = ((0.02 * SAMPLE_RATE as f32) as usize) | 1;
    let envelope = centered_max(mix, window);
    let mut smoothed = vec![0.0_f32; envelope.len()];
    hann_smooth(
        &envelope,
        &mut smoothed,
        ((0.03 * SAMPLE_RATE as f32) as usize) | 1,
    );
    let mut gains = vec![1.0_f32; smoothed.len()];
    for (gain, peak) in gains.iter_mut().zip(smoothed) {
        *gain = (ceiling / (peak + 1e-9)).min(1.0);
    }
    let mut gain_smooth = vec![0.0_f32; gains.len()];
    hann_smooth(
        &gains,
        &mut gain_smooth,
        ((0.03 * SAMPLE_RATE as f32) as usize) | 1,
    );
    for frame in 0..gain_smooth.len() {
        mix[frame * 2] *= gain_smooth[frame];
        mix[frame * 2 + 1] *= gain_smooth[frame];
        mix[frame * 2] = (mix[frame * 2] * 1.08).tanh() * 0.95;
        mix[frame * 2 + 1] = (mix[frame * 2 + 1] * 1.08).tanh() * 0.95;
    }
    let cur = (mix.iter().map(|v| v * v).sum::<f32>() / mix.len().max(1) as f32).sqrt();
    if cur > 0.0 {
        let want = 10.0_f32.powf((target_rms_db - dbfs(cur)) / 20.0);
        let peak = mix.iter().map(|v| v.abs()).fold(0.0, f32::max);
        let allowed = 10.0_f32.powf(-1.0 / 20.0) / (peak + 1e-9);
        for value in mix.iter_mut() {
            *value *= want.min(allowed);
        }
    }
}

fn centered_max(mix: &[f32], width: usize) -> Vec<f32> {
    let frames = mix.len() / 2;
    let half = width / 2;
    let mut values = Vec::with_capacity(frames + 2 * half);
    let first = if frames == 0 {
        0.0
    } else {
        mix[0].abs().max(mix[1].abs())
    };
    let last = if frames == 0 {
        0.0
    } else {
        mix[(frames - 1) * 2]
            .abs()
            .max(mix[(frames - 1) * 2 + 1].abs())
    };
    values.extend(std::iter::repeat(first).take(half));
    for frame in 0..frames {
        values.push(mix[frame * 2].abs().max(mix[frame * 2 + 1].abs()));
    }
    values.extend(std::iter::repeat(last).take(half));
    let mut queue = VecDeque::<(usize, f32)>::new();
    let mut out = vec![0.0; frames];
    for index in 0..values.len() {
        let value = values[index];
        while queue.back().is_some_and(|(_, old)| *old <= value) {
            queue.pop_back();
        }
        queue.push_back((index, value));
        while queue.front().is_some_and(|(old, _)| *old + width <= index) {
            queue.pop_front();
        }
        if index >= width - 1 {
            let center = index - (width - 1);
            if center < frames {
                out[center] = queue.front().map(|(_, v)| *v).unwrap_or(0.0);
            }
        }
    }
    out
}

fn hann_smooth(input: &[f32], output: &mut [f32], width: usize) {
    let width = width.max(3) | 1;
    let omega = 2.0_f64 * std::f64::consts::PI / (width - 1) as f64;
    let mut sum = vec![0.0_f64; input.len() + 1];
    let mut cos_sum = vec![0.0_f64; input.len() + 1];
    let mut sin_sum = vec![0.0_f64; input.len() + 1];
    for (index, value) in input.iter().enumerate() {
        let phase = index as f64 * omega;
        sum[index + 1] = sum[index] + *value as f64;
        cos_sum[index + 1] = cos_sum[index] + *value as f64 * phase.cos();
        sin_sum[index + 1] = sin_sum[index] + *value as f64 * phase.sin();
    }
    let half = width / 2;
    let norm = width as f64 * 0.5;
    for center in 0..input.len() {
        let start = center.saturating_sub(half);
        let end = (center + half + 1).min(input.len());
        let plain = sum[end] - sum[start];
        let c = cos_sum[end] - cos_sum[start];
        let s = sin_sum[end] - sin_sum[start];
        let phase = start as f64 * omega;
        let weighted = 0.5 * plain - 0.5 * (c * phase.cos() + s * phase.sin());
        output[center] = (weighted / norm) as f32;
    }
}

fn apply_filters(audio: &mut [f32], params: &BTreeMap<String, String>) {
    let (low_start, low_end) = parameter_pair(params, "lpf", 20_000.0);
    let (high_start, high_end) = parameter_pair(params, "hpf", 20.0);
    if params.contains_key("lpf") {
        one_pole_filter(audio, low_start, low_end, false);
    }
    if params.contains_key("hpf") {
        one_pole_filter(audio, high_start, high_end, true);
    }
}

fn one_pole_filter(audio: &mut [f32], start_hz: f32, end_hz: f32, high_pass: bool) {
    let mut state = 0.0_f32;
    let n = audio.len().max(1);
    for (index, sample) in audio.iter_mut().enumerate() {
        let t = index as f32 / n as f32;
        let cutoff = (start_hz.max(20.0).ln()
            + t * (end_hz.max(20.0).ln() - start_hz.max(20.0).ln()))
        .exp()
        .min(SAMPLE_RATE as f32 * 0.47);
        let alpha = 1.0 - (-2.0 * std::f32::consts::PI * cutoff / SAMPLE_RATE as f32).exp();
        let input = *sample;
        state += alpha * (input - state);
        *sample = if high_pass { input - state } else { state };
    }
}

fn effective_params(
    defaults: BTreeMap<String, String>,
    event: &BTreeMap<String, String>,
) -> BTreeMap<String, String> {
    let mut params = defaults;
    // DIVERGENCE: WF1 has no room/reverb bus. Instrument declarations in the
    // smoke corpus retain `send=` for graph/text parity, but it is inert until
    // the room face lands; per-event sends are refused above.
    params.extend(event.clone());
    params
}

fn parameter_pair(params: &BTreeMap<String, String>, key: &str, default: f32) -> (f32, f32) {
    let Some(value) = params.get(key) else {
        return (default, default);
    };
    if let Some((a, b)) = value.split_once("->") {
        return (
            a.parse::<f32>().unwrap_or(default),
            b.parse::<f32>().unwrap_or(default),
        );
    }
    let scalar = value.parse::<f32>().unwrap_or(default);
    (scalar, scalar)
}

fn dynamic_db(dynamic: Option<&str>) -> f32 {
    dynamic
        .and_then(|value| {
            DYN_DB
                .iter()
                .find(|(name, _)| *name == value)
                .map(|(_, db)| *db)
        })
        .unwrap_or(-11.0)
}

fn parse_tuning(value: Option<&String>) -> Result<f32, RenderError> {
    let Some(value) = value else { return Ok(440.0) };
    let value = value
        .split_once('=')
        .map(|(_, value)| value)
        .unwrap_or(value);
    value
        .trim()
        .parse::<f32>()
        .map_err(|_| RenderError::Invalid(format!("invalid tuning {value}")))
}

fn pitch_to_hz(value: &str, a4: f32) -> Option<f32> {
    let midi = parse_pitch(value)?;
    Some(pitch_cents_to_hz((midi * 100.0).round() as i32, a4))
}

fn parse_pitch(value: &str) -> Option<f32> {
    let mut chars = value.chars();
    let note = chars.next()?.to_ascii_uppercase();
    let mut accidental = 0.0;
    let next = chars.next();
    let octave_start = match next {
        Some('#') => {
            accidental = 1.0;
            2
        }
        Some('b') => {
            accidental = -1.0;
            2
        }
        Some('n') => 2,
        Some(_) => 1,
        None => return None,
    };
    let rest = &value[octave_start..];
    let split = rest.find(['+', '-']).unwrap_or(rest.len());
    let octave = rest[..split].parse::<i32>().ok()?;
    let cents = if split < rest.len() {
        rest[split..].parse::<f32>().ok()?
    } else {
        0.0
    };
    let base = match note {
        'C' => 0.0,
        'D' => 2.0,
        'E' => 4.0,
        'F' => 5.0,
        'G' => 7.0,
        'A' => 9.0,
        'B' => 11.0,
        _ => return None,
    };
    Some((octave + 1) as f32 * 12.0 + base + accidental + cents / 100.0)
}

fn pitch_cents_to_hz(pitch: i32, a4: f32) -> f32 {
    a4 * 2.0_f32.powf((pitch as f32 / 100.0 - 69.0) / 12.0)
}

fn dbfs(value: f32) -> f32 {
    20.0 * value.max(1e-12).log10()
}

pub fn sha256_bytes(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}

pub fn write_wav(audio: &RenderedAudio, path: &Path) -> Result<(), RenderError> {
    let spec = hound::WavSpec {
        channels: 2,
        sample_rate: audio.sample_rate,
        bits_per_sample: 24,
        sample_format: SampleFormat::Int,
    };
    let mut writer = hound::WavWriter::create(path, spec)?;
    for value in &audio.samples {
        let value = (value.clamp(-1.0, 1.0) * 8_388_607.0).round() as i32;
        writer.write_sample(value)?;
    }
    writer.finalize()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn equal_power_pan_preserves_mono_power_at_center() {
        let mut mix = vec![0.0; 2];
        place(&mut mix, 0, &[1.0], 1.0, 0.0, 0.0);
        assert!((mix[0] - 2f32.sqrt() / 2.0).abs() < 1e-6);
        assert!((mix[1] - 2f32.sqrt() / 2.0).abs() < 1e-6);
    }

    #[test]
    fn master_is_deterministic_and_lands_under_ceiling() {
        let mut first = vec![0.0; 48_000 * 2];
        for (i, value) in first.iter_mut().enumerate() {
            *value = ((i % 127) as f32 / 63.0 - 1.0) * 0.2;
        }
        let mut second = first.clone();
        master(&mut first, -17.0, 0.89);
        master(&mut second, -17.0, 0.89);
        assert_eq!(first, second);
        assert!(first.iter().map(|v| v.abs()).fold(0.0, f32::max) <= 10f32.powf(-1.0 / 20.0));
    }

    #[test]
    fn unsupported_synth_names_the_instrument() {
        let mut graph = ScoreGraph::default();
        graph.instruments.push(mus_graph::InstrumentDecl {
            abbrev: "sb".into(),
            name: "synth bass".into(),
            clef: "bass".into(),
            params: BTreeMap::from([("synth".into(), "saw".into())]),
            declared_by: mus_oplog::OpId("test".into()),
        });
        let error = validate_supported(&graph).unwrap_err();
        assert!(error.to_string().contains("synth"));
        assert!(error.to_string().contains("sb"));
    }

    #[test]
    fn aigua_1568_refuses_synth_before_loading_audio() {
        let score = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../aigua/aigua_1568.mus");
        let text = std::fs::read_to_string(score).unwrap();
        let graph = mus_text::adopt(&mus_text::parse_score(&text).unwrap());
        let error =
            render(&graph, Path::new(".")).expect_err("WF1 must refuse the synth construct");
        assert!(matches!(error, RenderError::Unsupported(_)));
        assert!(error.to_string().contains("synth"));
    }

    #[test]
    fn smoke_graph_has_sampler_events_and_renders_deterministically() {
        let score = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../aigua/smoke.mus");
        let text = std::fs::read_to_string(&score).unwrap();
        let proposal = mus_text::parse_score(&text).unwrap();
        let graph = mus_text::adopt(&proposal);
        assert_eq!(graph.current_events().len(), 46);
        let base = score.parent().unwrap();
        let first = render(&graph, base).unwrap();
        let second = render(&graph, base).unwrap();
        assert_eq!(first, second);
        assert!(first.frames() > 8 * SAMPLE_RATE as usize);
        assert!(first.peak() <= 10f32.powf(-1.0 / 20.0) + 1e-5);
    }

    #[test]
    fn parity_smoke_duration_and_envelope_hook() {
        // The opt-in hook keeps ordinary cargo test hermetic while allowing
        // the migration validator to be run in environments with uv's audio
        // dependencies: MUS_RUN_PARITY=1 cargo test parity_smoke -- --nocapture.
        if std::env::var_os("MUS_RUN_PARITY").is_none() {
            return;
        }
        let score = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../aigua/smoke.mus");
        let python_wav = score.parent().unwrap().join("../target/parity-smoke.wav");
        let status = std::process::Command::new("uv")
            .args(["run", "--script"])
            .arg(Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../mus_audio.py"))
            .args([score.to_str().unwrap(), "-o"])
            .arg(&python_wav)
            .status()
            .unwrap();
        assert!(status.success());
        let reference = hound::WavReader::open(python_wav).unwrap();
        let reference_frames = reference.duration() as f64;
        let text = std::fs::read_to_string(&score).unwrap();
        let graph = mus_text::adopt(&mus_text::parse_score(&text).unwrap());
        let rust_frames = render(&graph, score.parent().unwrap()).unwrap().frames() as f64;
        assert!((rust_frames - reference_frames).abs() <= SAMPLE_RATE as f64 * 0.001);
    }
}
