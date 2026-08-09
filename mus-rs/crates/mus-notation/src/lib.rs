//! mus-notation — the lexical layer of the MUS text face.
//!
//! The Python implementation remains the migration validator for this crate.
//! The committed token and bar vectors are the compatibility floor; this
//! module deliberately keeps the small, effect-free token grammar independent
//! from score layout and graph projection.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

pub const VECTORS_NOTE: &str =
    "tests/vectors/{tokens,bars}.json — oracle-generated lexical floor (3,604 tokens)";

/// The value returned by `parse_token`, shaped like the Python reference's
/// `mus_audio.Note`. `None` is used for an empty token, `-`, and malformed
/// pitched tokens, exactly as in the reference.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Note {
    pub kind: String,
    pub midis: Vec<f64>,
    pub ql: f64,
    pub params: BTreeMap<String, String>,
    pub flags: Vec<String>,
    #[serde(rename = "dyn")]
    pub dyn_value: Option<String>,
    pub gliss_midi: Option<f64>,
}

fn note(kind: &str) -> Note {
    Note {
        kind: kind.to_string(),
        midis: Vec::new(),
        ql: 0.0,
        params: BTreeMap::new(),
        flags: Vec::new(),
        dyn_value: None,
        gliss_midi: None,
    }
}

/// Whitespace splitting that preserves angle-bracket chords, brace groups,
/// and quoted lyrics as one token.
pub fn tokenize_bar_content(content: &str) -> Vec<String> {
    let mut tokens = Vec::new();
    let chars: Vec<char> = content.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        if chars[i].is_whitespace() {
            i += 1;
            continue;
        }
        let start = i;
        let mut angle = 0usize;
        let mut brace = 0usize;
        let mut quote = false;
        while i < chars.len() {
            let c = chars[i];
            if quote {
                if c == '"' {
                    quote = false;
                }
                i += 1;
                continue;
            }
            match c {
                '"' => quote = true,
                '<' => angle += 1,
                '>' if angle > 0 => angle -= 1,
                '{' => brace += 1,
                '}' if brace > 0 => brace -= 1,
                _ => {}
            }
            if c.is_whitespace() && angle == 0 && brace == 0 {
                break;
            }
            i += 1;
        }
        tokens.push(chars[start..i].iter().collect());
    }
    tokens
}

/// Expand `(… ×N)` groups, including nested groups, then tokenize again.
pub fn expand_pattern_repetitions(tokens: &[String]) -> Vec<String> {
    let mut text = tokens.join(" ");
    loop {
        let Some((start, end, pattern, count)) = repetition(&text) else {
            break;
        };
        let replacement = std::iter::repeat(pattern)
            .take(count)
            .collect::<Vec<_>>()
            .join(" ");
        text.replace_range(start..end, &replacement);
    }
    tokenize_bar_content(&text)
}

fn repetition(text: &str) -> Option<(usize, usize, String, usize)> {
    let mut close = None;
    for (i, c) in text.char_indices().rev() {
        if c == ')' {
            close = Some(i);
            break;
        }
    }
    let close = close?;
    let open = text[..close].rfind('(')?;
    let inside = &text[open + 1..close];
    let (pattern, n) = inside.rsplit_once('×')?;
    let count = n.trim().parse().ok()?;
    Some((open, close + 1, pattern.trim().to_string(), count))
}

/// Detach the dynamic suffix used by the score grammar (`A4q{mf}`) into its
/// own preceding token. Tuplet brace groups are explicitly excluded.
pub fn split_attached_dynamics(tokens: &[String]) -> Vec<String> {
    let mut out = Vec::new();
    for token in tokens {
        if token.starts_with('{') || token.starts_with('(') {
            out.push(token.clone());
            continue;
        }
        let Some(start) = token.rfind('{') else {
            out.push(token.clone());
            continue;
        };
        if !token.ends_with('}') || start == 0 {
            out.push(token.clone());
            continue;
        }
        let body = &token[start + 1..token.len() - 1];
        if body.chars().all(|c| c.is_ascii_digit() || c == ':') {
            out.push(token.clone());
        } else {
            out.push(format!("{{{}}}", body.trim()));
            out.push(token[..start].to_string());
        }
    }
    out
}

/// Parse one MUS duration code into quarter lengths. Dots use the reference
/// rule `2 - 2^-n`; tuplets scale the base value by normal/actual.
pub fn parse_duration_code(code: &str) -> Option<f64> {
    let code = code.trim();
    let direct = match code {
        "ww" => Some(8.0),
        "w." => Some(6.0),
        "w" => Some(4.0),
        "h." => Some(3.0),
        "h" => Some(2.0),
        "q." => Some(1.5),
        "q" => Some(1.0),
        "e." => Some(0.75),
        "e" => Some(0.5),
        "s." => Some(0.375),
        "s" => Some(0.25),
        "t" => Some(0.125),
        _ => None,
    };
    if let Some(value) = direct {
        return Some(value);
    }

    let chars: Vec<char> = code.chars().collect();
    if chars.is_empty()
        || !matches!(
            chars[0].to_ascii_lowercase(),
            'w' | 'h' | 'q' | 'e' | 's' | 't' | 'x'
        )
    {
        return None;
    }
    let mut index = 1;
    let mut base = chars[0].to_ascii_lowercase().to_string();
    if index < chars.len() && chars[index].to_ascii_lowercase() == chars[0].to_ascii_lowercase() {
        base.push(chars[index].to_ascii_lowercase());
        index += 1;
    }
    let base_ql = match base.as_str() {
        "ww" => 8.0,
        "w" => 4.0,
        "h" => 2.0,
        "q" => 1.0,
        "e" => 0.5,
        "s" => 0.25,
        "t" => 0.125,
        "x" => 0.0625,
        _ => return None,
    };
    let mut dots = 0u32;
    while index < chars.len() && chars[index] == '.' {
        dots += 1;
        index += 1;
    }
    let suffix: String = chars[index..].iter().collect();
    let mut value = base_ql * (2.0 - 2f64.powi(-(dots as i32)));
    if !suffix.is_empty() {
        let (actual, normal) = if suffix.starts_with('{') && suffix.ends_with('}') {
            let body = &suffix[1..suffix.len() - 1];
            let (a, n) = body.split_once(':')?;
            (a.parse::<f64>().ok()?, n.parse::<f64>().ok()?)
        } else {
            match suffix.as_str() {
                "3" => (3.0, 2.0),
                "5" => (5.0, 4.0),
                "6" => (6.0, 4.0),
                "7" => (7.0, 4.0),
                "9" => (9.0, 8.0),
                _ => return None,
            }
        };
        if actual == 0.0 {
            return None;
        }
        value *= normal / actual;
    }
    Some(value)
}

fn duration_ql(codes: &str) -> f64 {
    codes.split('~').filter_map(parse_duration_code).sum()
}

fn parse_pitch(token: &str) -> Option<f64> {
    let chars: Vec<char> = token.chars().collect();
    if chars.len() < 2 || !matches!(chars[0], 'A'..='G') {
        return None;
    }
    let mut i = 1;
    let accidental =
        if i + 1 < chars.len() && matches!((chars[i], chars[i + 1]), ('b', 'b') | ('#', '#')) {
            let a = if chars[i] == 'b' { -2.0 } else { 2.0 };
            i += 2;
            a
        } else if i < chars.len() {
            match chars[i] {
                'b' => {
                    i += 1;
                    -1.0
                }
                'n' => {
                    i += 1;
                    0.0
                }
                '#' => {
                    i += 1;
                    1.0
                }
                'x' => {
                    i += 1;
                    2.0
                }
                _ => 0.0,
            }
        } else {
            0.0
        };
    let oct_start = i;
    if i < chars.len() && chars[i] == '-' {
        i += 1;
    }
    while i < chars.len() && chars[i].is_ascii_digit() {
        i += 1;
    }
    if i == oct_start || (i == oct_start + 1 && chars[oct_start] == '-') {
        return None;
    }
    let octave: i32 = chars[oct_start..i]
        .iter()
        .collect::<String>()
        .parse()
        .ok()?;
    let cents = if i < chars.len() && matches!(chars[i], '+' | '-') {
        let start = i;
        i += 1;
        while i < chars.len() && chars[i].is_ascii_digit() {
            i += 1;
        }
        if i == start + 1 {
            return None;
        }
        chars[start..i]
            .iter()
            .collect::<String>()
            .parse::<i32>()
            .ok()? as f64
            / 100.0
    } else {
        0.0
    };
    if i != chars.len() {
        return None;
    }
    let base = match chars[0] {
        'C' => 0,
        'D' => 2,
        'E' => 4,
        'F' => 5,
        'G' => 7,
        'A' => 9,
        'B' => 11,
        _ => return None,
    };
    Some((octave + 1) as f64 * 12.0 + base as f64 + accidental + cents)
}

fn pitch_prefix(token: &str) -> Option<(&str, &str)> {
    let bytes = token.as_bytes();
    if bytes.first().is_none_or(|b| !matches!(b, b'A'..=b'G')) {
        return None;
    }
    let mut i = 1;
    if i + 1 < bytes.len() && matches!((bytes[i], bytes[i + 1]), (b'b', b'b') | (b'#', b'#')) {
        i += 2;
    } else if i < bytes.len() && matches!(bytes[i], b'b' | b'n' | b'#' | b'x') {
        i += 1;
    }
    if i < bytes.len() && bytes[i] == b'-' {
        i += 1;
    }
    let oct_start = i;
    while i < bytes.len() && bytes[i].is_ascii_digit() {
        i += 1;
    }
    if i == oct_start {
        return None;
    }
    if i < bytes.len() && matches!(bytes[i], b'+' | b'-') {
        i += 1;
        let cents_start = i;
        while i < bytes.len() && bytes[i].is_ascii_digit() {
            i += 1;
        }
        if i == cents_start {
            return None;
        }
    }
    Some((&token[..i], &token[i..]))
}

fn lyricless(token: &str) -> String {
    let mut result = String::with_capacity(token.len());
    let chars: Vec<char> = token.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        if chars[i] == '"' {
            i += 1;
            while i < chars.len() && chars[i] != '"' {
                i += 1;
            }
            if i < chars.len() {
                i += 1;
            }
        } else {
            result.push(chars[i]);
            i += 1;
        }
    }
    result
}

/// Parse one extended MUS token with the reference semantics.
pub fn parse_token(raw: &str) -> Option<Note> {
    let mut token = raw
        .trim()
        .trim_start_matches('(')
        .trim_end_matches(')')
        .to_string();
    if token.is_empty() {
        return None;
    }
    token = lyricless(&token);
    if matches!(token.as_str(), "{<}" | "{>}" | "{|}") {
        let mut out = note("hairpin");
        out.dyn_value = Some(
            match token.as_str() {
                "{<}" => "cresc",
                "{>}" => "dim",
                _ => "end",
            }
            .into(),
        );
        return Some(out);
    }
    if token.starts_with('{') && token.ends_with('}') {
        let mut out = note("dynamic");
        out.dyn_value = Some(token[1..token.len() - 1].trim().into());
        return Some(out);
    }
    if token == "-" {
        return None;
    }

    let mut params = BTreeMap::new();
    let mut flags = Vec::new();
    if let (Some(start), Some(end)) = (token.find('['), token.find(']')) {
        if end > start {
            for item in token[start + 1..end]
                .split(',')
                .map(str::trim)
                .filter(|s| !s.is_empty())
            {
                if let Some((key, value)) = item.split_once('=') {
                    params.insert(key.trim().to_ascii_lowercase(), value.trim().to_string());
                } else {
                    flags.push(item.to_ascii_lowercase());
                }
            }
            token.replace_range(start..=end, "");
        }
    }

    let mut gliss = None;
    if let Some((head, target)) = token
        .split_once("->")
        .map(|(h, t)| (h.to_string(), t.to_string()))
    {
        token = head;
        if let Some((pitch, _)) = pitch_prefix(target.trim()) {
            gliss = parse_pitch(pitch);
        }
    }
    if let Some(target) = params.remove("gliss") {
        gliss = parse_pitch(&target);
    }

    if token.starts_with('<') {
        let close = token.find('>')?;
        let pitches = token[1..close]
            .split_whitespace()
            .filter_map(parse_pitch)
            .collect();
        let mut out = note("chord");
        out.midis = pitches;
        out.ql = duration_ql(&token[close + 1..].replace('~', "~"));
        out.params = params;
        out.flags = flags;
        out.gliss_midi = gliss;
        return Some(out);
    }
    if let Some(rest) = token.strip_prefix('R') {
        let mut out = note("rest");
        out.ql = if rest.is_empty() {
            0.0
        } else {
            duration_ql(rest)
        };
        out.params = params;
        out.flags = flags;
        return Some(out);
    }
    if let Some(rest) = token.strip_prefix('X') {
        let mut out = note("unpitched");
        out.ql = if rest.is_empty() {
            1.0
        } else {
            duration_ql(rest)
        };
        out.params = params;
        out.flags = flags;
        out.gliss_midi = gliss;
        return Some(out);
    }
    let (pitch, durations) = pitch_prefix(&token)?;
    let mut out = note("note");
    out.midis.push(parse_pitch(pitch)?);
    out.ql = duration_ql(durations);
    if out.ql == 0.0 {
        out.ql = 1.0;
    }
    out.params = params;
    out.flags = flags;
    out.gliss_midi = gliss;
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::Deserialize;

    #[derive(Deserialize)]
    struct Vector {
        raw: String,
        kind: String,
        midis: Vec<f64>,
        ql: f64,
        params: BTreeMap<String, String>,
        flags: Vec<String>,
        #[serde(rename = "dyn")]
        dyn_value: Option<String>,
        gliss_midi: Option<f64>,
    }

    #[test]
    fn token_vectors_match_reference() {
        let vectors: Vec<Vector> =
            serde_json::from_str(include_str!("../tests/vectors/tokens.json")).unwrap();
        assert_eq!(vectors.len(), 3604);
        for v in vectors {
            let got = parse_token(&v.raw).unwrap_or_else(|| panic!("{} returned None", v.raw));
            assert_eq!(got.kind, v.kind, "{}", v.raw);
            assert_eq!(got.midis.len(), v.midis.len(), "{}", v.raw);
            for (a, b) in got.midis.iter().zip(v.midis) {
                assert!((a - b).abs() < 1e-6, "{}: {a} != {b}", v.raw);
            }
            assert!(
                (got.ql - v.ql).abs() < 1e-9,
                "{}: {} != {}",
                v.raw,
                got.ql,
                v.ql
            );
            assert_eq!(got.params, v.params, "{}", v.raw);
            assert_eq!(got.flags, v.flags, "{}", v.raw);
            assert_eq!(got.dyn_value, v.dyn_value, "{}", v.raw);
            assert_eq!(got.gliss_midi, v.gliss_midi, "{}", v.raw);
        }
    }

    #[derive(Deserialize)]
    struct BarVector {
        content: String,
        tokens: Vec<String>,
    }

    #[test]
    fn bar_vectors_match_reference() {
        let vectors: Vec<BarVector> =
            serde_json::from_str(include_str!("../tests/vectors/bars.json")).unwrap();
        assert_eq!(vectors.len(), 40);
        for v in vectors {
            let tokens = expand_pattern_repetitions(&tokenize_bar_content(&v.content));
            assert_eq!(tokens, v.tokens, "{}", v.content);
        }
    }
}
