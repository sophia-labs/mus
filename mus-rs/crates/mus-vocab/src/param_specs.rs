//! Typed parameter specifications — the vocabulary describing itself.
//!
//! The interaction grammar's Stack derives its controls from this table
//! (`plans/atril-interaction-grammar-20260810.md` §2.2: "the vocabulary IS
//! the UI schema... nothing hand-maintained, nothing that can drift from
//! the language"). Every entry carries the widget-relevant truth about a
//! parameter: its kind (which control family renders it), its range and
//! default (from `mus_audio.py`'s own defaults — the oracle the engine is
//! parity-locked to), and a one-line doc.
//!
//! Layering follows ruling R2 (mus-core sealed + mus-x): entries for
//! names in [`crate::CORE_PARAMS`]/[`crate::CORE_QUOTE_PARAMS`] are
//! `ParamLayer::Core`; the renderer's experimental transform surface
//! (synth voice, glow chain, chop/ring/stutter family) is typed here too
//! but as `ParamLayer::Extension` — the Stack renders those with the same
//! derived widgets, visibly marked as extensions. A param absent from
//! this table entirely gets the Stack's honest generic control.
//!
//! `mus-cli vocab --json` serializes this table (plus flags, quote
//! params, and the header registry) as `mus.vocab.v1` for the TS side.

use crate::ParamLayer;

/// What kind of control a parameter wants, with its numeric truth.
/// `sweep: true` means the textual form accepts `a->b` (a param-pair
/// sweep across the event) wherever a single value is legal.
#[derive(Debug, Clone, PartialEq)]
pub enum ParamKind {
    /// Time in seconds (attack/decay/release/tau…).
    Seconds {
        min: f64,
        max: f64,
        default: Option<f64>,
    },
    /// Time in milliseconds (`off=`, `haas=`).
    Milliseconds {
        min: f64,
        max: f64,
        default: Option<f64>,
    },
    /// Level trim in dB.
    Db {
        min: f64,
        max: f64,
        default: Option<f64>,
    },
    /// Frequency in Hz.
    Hz {
        min: f64,
        max: f64,
        default: Option<f64>,
        sweep: bool,
    },
    /// Pitch offset in semitones.
    Semitones {
        min: f64,
        max: f64,
        default: Option<f64>,
        sweep: bool,
    },
    /// Detune in cents.
    Cents {
        min: f64,
        max: f64,
        default: Option<f64>,
    },
    /// Equal-power pan position, −1..1.
    Pan { sweep: bool },
    /// A unitless 0..1-ish mix/amount ratio.
    Ratio {
        min: f64,
        max: f64,
        default: Option<f64>,
    },
    /// A small positive integer count.
    Count {
        min: u32,
        max: u32,
        default: Option<u32>,
    },
    /// One of a closed set of words.
    Enum {
        values: &'static [&'static str],
        default: Option<&'static str>,
    },
    /// Boolean-ish: absent/`0`/`off` = false, anything else = true.
    Toggle { default: bool },
    /// `0+4+7+12`-style interval stack (`|` also accepted as separator).
    IntervalStack { default: &'static str },
    /// A time-stretch factor, with `fit` as a literal meaning
    /// "stretch to the slot".
    Stretch {
        min: f64,
        max: f64,
        literals: &'static [&'static str],
    },
    /// A note name (`C4`, `A#3`…).
    NoteName,
    /// Free text (ids, hash prefixes).
    Text,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ParamSpec {
    pub name: &'static str,
    pub layer: ParamLayer,
    pub kind: ParamKind,
    pub doc: &'static str,
}

#[derive(Debug, Clone, PartialEq)]
pub struct FlagSpec {
    pub name: &'static str,
    pub doc: &'static str,
}

/// Every typed parameter, core first, then the known mus-x surface.
/// Ranges are widget ranges (sane control travel), not hard validation —
/// the engine clamps where the oracle clamps and nowhere else.
pub fn param_specs() -> Vec<ParamSpec> {
    use ParamKind::*;
    use ParamLayer::{Core, Extension};
    vec![
        // ------------------------------------------------ core params
        ParamSpec { name: "pan", layer: Core, kind: Pan { sweep: true }, doc: "equal-power position, -1..1; a->b sweeps across the event" },
        ParamSpec { name: "gain", layer: Core, kind: Db { min: -24.0, max: 24.0, default: Some(0.0) }, doc: "event gain trim in dB, on top of dynamics and voice gain" },
        ParamSpec { name: "lpf", layer: Core, kind: Hz { min: 20.0, max: 20_000.0, default: Some(20_000.0), sweep: true }, doc: "low-pass cutoff; a->b sweeps geometrically across the event" },
        ParamSpec { name: "hpf", layer: Core, kind: Hz { min: 20.0, max: 20_000.0, default: Some(20.0), sweep: true }, doc: "high-pass cutoff; a->b sweeps geometrically across the event" },
        ParamSpec { name: "send", layer: Core, kind: Ratio { min: 0.0, max: 1.0, default: Some(0.12) }, doc: "reverb send amount (voice default 0.12)" },
        ParamSpec { name: "s", layer: Core, kind: Count { min: 1, max: 64, default: Some(1) }, doc: "sample index within the voice, 1-based, clamped to the pack" },
        ParamSpec { name: "str", layer: Core, kind: Stretch { min: 0.25, max: 4.0, literals: &["fit"] }, doc: "time-stretch factor (>1 longer); `fit` stretches to the notated slot" },
        ParamSpec { name: "off", layer: Core, kind: Milliseconds { min: -2000.0, max: 10_000.0, default: Some(0.0) }, doc: "sample start offset in ms; negative offsets take the tail (Python slicing semantics)" },
        ParamSpec { name: "st", layer: Core, kind: Semitones { min: -48.0, max: 48.0, default: Some(0.0), sweep: true }, doc: "transposition for unpitched (X) events; a->b rides a pitch ramp" },
        ParamSpec { name: "atk", layer: Core, kind: Seconds { min: 0.0015, max: 0.5, default: Some(0.003) }, doc: "attack fade (power 0.7 ramp)" },
        ParamSpec { name: "rel", layer: Core, kind: Seconds { min: 0.004, max: 2.0, default: Some(0.035) }, doc: "release fade (power 1.5 ramp)" },
        ParamSpec { name: "curve", layer: Core, kind: Enum { values: &["lin", "exp"], default: Some("lin") }, doc: "pitch-ramp shape; exp falls fast then flattens (the 808 shape)" },
        ParamSpec { name: "tau", layer: Core, kind: Seconds { min: 0.005, max: 0.5, default: Some(0.045) }, doc: "exp pitch-ramp time constant" },
        ParamSpec { name: "drive", layer: Core, kind: Ratio { min: 1.0, max: 10.0, default: Some(1.0) }, doc: "tanh soft-clip drive (identity at 1)" },
        ParamSpec { name: "dist", layer: Core, kind: Ratio { min: 1.0, max: 20.0, default: Some(1.0) }, doc: "hard-clip amount — clip, don't saturate" },
        ParamSpec { name: "crush", layer: Core, kind: Count { min: 2, max: 16, default: None }, doc: "bitcrush amplitude quantisation, in bits" },
        ParamSpec { name: "decim", layer: Core, kind: Count { min: 1, max: 64, default: None }, doc: "sample-hold decimation factor (aliasing on purpose)" },
        ParamSpec { name: "stut", layer: Core, kind: Count { min: 2, max: 32, default: None }, doc: "retrigger the event N times inside its slot" },
        ParamSpec { name: "duck", layer: Core, kind: Toggle { default: true }, doc: "sidechain participation; 0/off exempts this track's events from the pump" },
        // ------------------------------------------------ quotation (core)
        ParamSpec { name: "gest", layer: Core, kind: Text, doc: "quoted gesture: hypothesis id, hN index, or sha256 prefix from the sweep-events research object" },
        ParamSpec { name: "glayer", layer: Core, kind: Enum { values: &["resolved", "octave"], default: Some("resolved") }, doc: "which consensus layer the quotation follows" },
        ParamSpec { name: "gsrc", layer: Core, kind: Enum { values: &["pack", "raw"], default: Some("pack") }, doc: "quotation material: pack sample bent along the contour, or the tape itself" },
        // ------------------------------------------------ mus-x: mode/gliss
        ParamSpec { name: "mode", layer: Extension, kind: Enum { values: &["varispeed", "vocoder"], default: Some("varispeed") }, doc: "pitch mechanism: tape (duration couples) or phase vocoder (duration held)" },
        ParamSpec { name: "gliss", layer: Extension, kind: NoteName, doc: "glissando target pitch (equivalent to the A6q->C7 arrow form)" },
        // ------------------------------------------------ mus-x: synth voice
        ParamSpec { name: "synth", layer: Extension, kind: Enum { values: &["saw", "square", "tri", "sine"], default: Some("saw") }, doc: "oscillator wave (declaring it makes the track a synth voice)" },
        ParamSpec { name: "osc2", layer: Extension, kind: Enum { values: &["saw", "square", "tri", "sine"], default: None }, doc: "second oscillator, one octave up, mixed at mix2" },
        ParamSpec { name: "mix2", layer: Extension, kind: Ratio { min: 0.0, max: 1.0, default: Some(0.5) }, doc: "osc2 mix (0 = osc1 only)" },
        ParamSpec { name: "detune", layer: Extension, kind: Cents { min: 0.0, max: 100.0, default: Some(0.0) }, doc: "unison detune: adds a ± detuned pair around osc1" },
        ParamSpec { name: "sub", layer: Extension, kind: Ratio { min: 0.0, max: 1.0, default: Some(0.0) }, doc: "sine sub-oscillator at half frequency" },
        ParamSpec { name: "cutoff", layer: Extension, kind: Hz { min: 50.0, max: 18_000.0, default: Some(4200.0), sweep: false }, doc: "filter cutoff (sweep end when famt > 0)" },
        ParamSpec { name: "famt", layer: Extension, kind: Hz { min: 0.0, max: 12_000.0, default: Some(0.0), sweep: false }, doc: "filter-envelope amount: sweep starts at cutoff+famt" },
        ParamSpec { name: "satk", layer: Extension, kind: Seconds { min: 0.001, max: 1.0, default: Some(0.004) }, doc: "synth ADSR attack" },
        ParamSpec { name: "sdec", layer: Extension, kind: Seconds { min: 0.005, max: 2.0, default: Some(0.05) }, doc: "synth ADSR decay" },
        ParamSpec { name: "ssus", layer: Extension, kind: Ratio { min: 0.0, max: 1.0, default: Some(0.75) }, doc: "synth ADSR sustain level" },
        ParamSpec { name: "srel", layer: Extension, kind: Seconds { min: 0.01, max: 2.0, default: Some(0.12) }, doc: "synth ADSR release (also pads the rendered buffer)" },
        // ------------------------------------------------ mus-x: treatments
        ParamSpec { name: "chop", layer: Extension, kind: Count { min: 2, max: 64, default: None }, doc: "granular re-deal: evens first, every 4th grain reversed" },
        ParamSpec { name: "ring", layer: Extension, kind: Hz { min: 5.0, max: 8000.0, default: None, sweep: false }, doc: "ring-mod carrier — inharmonic sidebands, the classic weird-ifier" },
        ParamSpec { name: "rwet", layer: Extension, kind: Ratio { min: 0.0, max: 1.0, default: Some(1.0) }, doc: "ring-mod wet mix" },
        ParamSpec { name: "glow", layer: Extension, kind: Semitones { min: 0.0, max: 36.0, default: None, sweep: false }, doc: "hyperpop chain base shift — the un-birding treatment" },
        ParamSpec { name: "ghold", layer: Extension, kind: Toggle { default: false }, doc: "loop the loudest 70ms to the notated slot (birds cannot hold a note; this holds one)" },
        ParamSpec { name: "gwarble", layer: Extension, kind: Hz { min: 0.5, max: 16.0, default: None, sweep: false }, doc: "square-LFO semitone trill — autotune artifact, robots only" },
        ParamSpec { name: "gharm", layer: Extension, kind: IntervalStack { default: "0" }, doc: "harmonizer stack (0+4+7+12): every note a parallel chord of itself, weights falling 0.85 per layer" },
        ParamSpec { name: "pump", layer: Extension, kind: Hz { min: 0.25, max: 8.0, default: Some(0.0), sweep: false }, doc: "beat-synced duck inside the glow chain" },
        ParamSpec { name: "haas", layer: Extension, kind: Milliseconds { min: 0.0, max: 40.0, default: Some(0.0) }, doc: "interaural delay on the right channel — width without a pan move" },
    ]
}

/// Articulation and playback flags (all core).
pub fn flag_specs() -> Vec<FlagSpec> {
    vec![
        FlagSpec {
            name: "stac",
            doc: "staccato — shortens the sounding length within the slot",
        },
        FlagSpec {
            name: "stacciss",
            doc: "staccatissimo — shortest articulation",
        },
        FlagSpec {
            name: "spic",
            doc: "spiccato — short, bouncing",
        },
        FlagSpec {
            name: "detlg",
            doc: "détaché large — broad separation",
        },
        FlagSpec {
            name: "acc",
            doc: "accent — louder attack",
        },
        FlagSpec {
            name: "marc",
            doc: "marcato — strong accent",
        },
        FlagSpec {
            name: "sfz",
            doc: "sforzando — sudden force",
        },
        FlagSpec {
            name: "stress",
            doc: "agogic stress — slight emphasis",
        },
        FlagSpec {
            name: "unstress",
            doc: "de-emphasis",
        },
        FlagSpec {
            name: "ten",
            doc: "tenuto — held full value",
        },
        FlagSpec {
            name: "fer",
            doc: "fermata — stretched ~1.75x beyond the slot",
        },
        FlagSpec {
            name: "gate",
            doc: "cut hard at the slot boundary",
        },
        FlagSpec {
            name: "reverse",
            doc: "play the sample backwards",
        },
    ]
}
