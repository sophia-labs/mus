//! Gesture-quotation consensus contours — `mus_audio.load_gestures` (line
//! 181) and `lookup_gesture` (line 218). `# gestures: <path>` header;
//! quoted by `gest=` event params (`gsrc=raw` tape slices, or the
//! pack-sample polyline path — see [`crate::source`]).

use std::collections::BTreeMap;
use std::path::Path;
use std::sync::OnceLock;

use regex::Regex;
use serde_json::Value;

use crate::RenderError;

#[derive(Debug, Clone)]
pub struct Gesture {
    pub resolved: Vec<(f64, f64)>,
    pub octave: Vec<(f64, f64)>,
    pub median_hz: f64,
    pub t0: Option<f64>,
    pub t1: Option<f64>,
}

fn re_sha256() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"sha256:([0-9a-f]+)").unwrap())
}

/// `mus_audio.load_gestures` (line 181): keyed three ways — `h<index>` in
/// file order, the full `hypothesis_id`, and (first-wins) its sha256
/// segment-hash suffix.
pub fn load_gestures(path: &Path) -> Result<BTreeMap<String, Gesture>, RenderError> {
    let bytes = std::fs::read(path)?;
    let data: Value = serde_json::from_slice(&bytes)?;
    let events: Vec<Value> = if let Some(v) = data.get("events") {
        v.as_array().cloned().unwrap_or_default()
    } else {
        data.as_array().cloned().unwrap_or_default()
    };

    let mut out = BTreeMap::new();
    for (i, e) in events.iter().enumerate() {
        let Some(contour) = e.get("contour").and_then(Value::as_array) else {
            continue;
        };
        if contour.is_empty() {
            continue;
        }
        let resolved: Vec<(f64, f64)> = contour
            .iter()
            .filter_map(|r| {
                let a = r.as_array()?;
                if a.get(2)?.as_str()? != "r" {
                    return None;
                }
                let hz = a.get(1)?.as_f64()?;
                if hz == 0.0 {
                    return None;
                }
                Some((a.first()?.as_f64()?, hz))
            })
            .collect();
        let octave: Vec<(f64, f64)> = contour
            .iter()
            .filter_map(|r| {
                let a = r.as_array()?;
                if a.get(2)?.as_str()? != "o" || a.len() <= 3 {
                    return None;
                }
                let hz = a.get(3)?.as_f64()?;
                if hz == 0.0 {
                    return None;
                }
                Some((a.first()?.as_f64()?, hz))
            })
            .collect();
        let reference: &Vec<(f64, f64)> = if !resolved.is_empty() {
            &resolved
        } else {
            &octave
        };
        if reference.len() < 2 {
            continue;
        }
        let mut hz_sorted: Vec<f64> = reference.iter().map(|(_, h)| *h).collect();
        hz_sorted.sort_by(f64::total_cmp);
        let median_hz = hz_sorted[hz_sorted.len() / 2];
        let gesture = Gesture {
            resolved,
            octave,
            median_hz,
            t0: e.get("start_seconds").and_then(Value::as_f64),
            t1: e.get("end_seconds").and_then(Value::as_f64),
        };
        out.insert(format!("h{i}"), gesture.clone());
        if let Some(hid) = e.get("hypothesis_id").and_then(Value::as_str) {
            if !hid.is_empty() {
                out.insert(hid.to_string(), gesture.clone());
                if let Some(caps) = re_sha256().captures(hid) {
                    let hash = caps.get(1).unwrap().as_str().to_string();
                    out.entry(hash).or_insert(gesture);
                }
            }
        }
    }
    Ok(out)
}

/// `mus_audio.lookup_gesture` (line 218): exact key, else the unique
/// non-index (`h<i>`) key with `key` as a prefix (only tried for `key`
/// at least 6 chars, matching the oracle's guard against a trivial/short
/// prefix fanning out to many hits).
pub fn lookup_gesture<'a>(
    gestures: &'a BTreeMap<String, Gesture>,
    key: &str,
) -> Option<&'a Gesture> {
    if let Some(g) = gestures.get(key) {
        return Some(g);
    }
    if key.len() < 6 {
        return None;
    }
    let mut hits = gestures
        .iter()
        .filter(|(k, _)| k.starts_with(key) && !k.starts_with('h'));
    let first = hits.next()?;
    if hits.next().is_some() {
        None
    } else {
        Some(first.1)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write_tmp(name: &str, bytes: &[u8]) -> std::path::PathBuf {
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = std::env::temp_dir().join(format!("mus-engine-gest-{nonce}-{name}"));
        std::fs::write(&path, bytes).unwrap();
        path
    }

    #[test]
    fn loads_median_and_three_key_forms_with_sha_prefix_lookup() {
        let bytes = serde_json::to_vec(&serde_json::json!({
            "events": [{
                "hypothesis_id": "sha256:abc123def",
                "start_seconds": 1.0,
                "end_seconds": 1.5,
                "contour": [[0.0, 440.0, "r"], [0.1, 450.0, "r"], [0.2, 460.0, "r"], [0.3, 7.0, "o", 880.0]]
            }]
        }))
        .unwrap();
        let path = write_tmp("gestures.json", &bytes);
        let gestures = load_gestures(&path).unwrap();
        assert_eq!(gestures.len(), 3); // h0, sha256:abc123def, abc123def
        assert_eq!(gestures["h0"].median_hz, 450.0);
        assert_eq!(gestures["h0"].resolved.len(), 3);
        assert_eq!(gestures["h0"].octave.len(), 1);
        assert_eq!(gestures["h0"].t0, Some(1.0));

        assert!(lookup_gesture(&gestures, "h0").is_some());
        assert!(lookup_gesture(&gestures, "sha256:abc123def").is_some());
        // "abc123" is 6+ chars and prefixes the sha-hash key uniquely.
        assert!(lookup_gesture(&gestures, "abc123").is_some());
        // Too short to try prefix matching at all.
        assert!(lookup_gesture(&gestures, "abc").is_none());
        assert!(lookup_gesture(&gestures, "missing").is_none());
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn sparse_or_zero_only_layers_are_skipped() {
        let bytes = serde_json::to_vec(&serde_json::json!({
            "events": [
                {"contour": [[0.0, 440.0, "r"]]},
                {"contour": []},
                {"contour": [[0.0, 0.0, "r"], [0.1, 0.0, "r"]]}
            ]
        }))
        .unwrap();
        let path = write_tmp("sparse.json", &bytes);
        let gestures = load_gestures(&path).unwrap();
        assert!(gestures.is_empty());
        std::fs::remove_file(path).unwrap();
    }
}
