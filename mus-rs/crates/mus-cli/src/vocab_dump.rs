//! `mus vocab` — serialize the vocabulary's self-description as
//! `mus.vocab.v1` JSON. The Stack (Atril's inspector) consumes this dump
//! at build time; the single source of truth stays in `mus-vocab`, so the
//! UI cannot drift from the language.

use mus_vocab::param_specs::{flag_specs, param_specs, ParamKind, ParamSpec};
use mus_vocab::{vocab_digest, HeaderKind, ParamLayer, CORE_QUOTE_PARAMS, HEADER_REGISTRY};
use serde_json::{json, Value};

fn kind_json(kind: &ParamKind) -> Value {
    match kind {
        ParamKind::Seconds { min, max, default } => {
            json!({"kind": "seconds", "min": min, "max": max, "default": default})
        }
        ParamKind::Milliseconds { min, max, default } => {
            json!({"kind": "milliseconds", "min": min, "max": max, "default": default})
        }
        ParamKind::Db { min, max, default } => {
            json!({"kind": "db", "min": min, "max": max, "default": default})
        }
        ParamKind::Hz {
            min,
            max,
            default,
            sweep,
        } => json!({"kind": "hz", "min": min, "max": max, "default": default, "sweep": sweep}),
        ParamKind::Semitones {
            min,
            max,
            default,
            sweep,
        } => {
            json!({"kind": "semitones", "min": min, "max": max, "default": default, "sweep": sweep})
        }
        ParamKind::Cents { min, max, default } => {
            json!({"kind": "cents", "min": min, "max": max, "default": default})
        }
        ParamKind::Pan { sweep } => json!({"kind": "pan", "min": -1.0, "max": 1.0, "sweep": sweep}),
        ParamKind::Ratio { min, max, default } => {
            json!({"kind": "ratio", "min": min, "max": max, "default": default})
        }
        ParamKind::Count { min, max, default } => {
            json!({"kind": "count", "min": min, "max": max, "default": default})
        }
        ParamKind::Enum { values, default } => {
            json!({"kind": "enum", "values": values, "default": default})
        }
        ParamKind::Toggle { default } => json!({"kind": "toggle", "default": default}),
        ParamKind::IntervalStack { default } => {
            json!({"kind": "interval-stack", "default": default})
        }
        ParamKind::Stretch { min, max, literals } => {
            json!({"kind": "stretch", "min": min, "max": max, "literals": literals})
        }
        ParamKind::NoteName => json!({"kind": "note-name"}),
        ParamKind::Text => json!({"kind": "text"}),
    }
}

fn spec_json(spec: &ParamSpec) -> Value {
    json!({
        "name": spec.name,
        "layer": match spec.layer { ParamLayer::Core => "core", ParamLayer::Extension => "extension" },
        "quote": CORE_QUOTE_PARAMS.contains(&spec.name),
        "doc": spec.doc,
        "control": kind_json(&spec.kind),
    })
}

pub fn dump() -> Value {
    json!({
        "schema": "mus.vocab.v1",
        "digest": vocab_digest(),
        "params": param_specs().iter().map(spec_json).collect::<Vec<_>>(),
        "flags": flag_specs().iter().map(|f| json!({"name": f.name, "doc": f.doc})).collect::<Vec<_>>(),
        "headers": HEADER_REGISTRY.iter().map(|(key, kind)| json!({
            "key": key,
            "kind": match kind { HeaderKind::ScoreProperty => "score-property", HeaderKind::PerformanceAnnotation => "performance-annotation" },
        })).collect::<Vec<_>>(),
    })
}
