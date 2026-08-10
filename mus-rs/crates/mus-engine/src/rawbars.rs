//! Raw per-bar, per-track token text — `mus.py::parse_mus`'s bar-line walk
//! (lines 1294-1320) and `mus_audio.render`'s own flatten of it into
//! `bar_content[b]` (lines 869-872).
//!
//! `mus_text::parse_score_lossy` already turns a score into headers +
//! instruments + fully-resolved `EventState`s, but resolving events erases
//! exactly what this stage needs back: the raw token stream (for hairpin
//! spans and unparseable-token stats) and which bar starts an inline-change
//! range (`mus_text`'s own `Proposal::bar_changes` duplicates a range's
//! changes onto *every* bar in it, which happens to be harmless for
//! [`crate::layout`]'s tempo/time folding — the overridden value is
//! constant across the range either way — but would be wrong if a header
//! arrow-chain tempo change ever landed on a bar strictly inside a bracket
//! range). So this module re-walks the source text directly, using the
//! same bar-line grammar `mus-cli check` already established as the Rust
//! reference (`crates/mus-cli/src/check.rs::parse_bar_line`/
//! `split_bar_content`).

use std::collections::BTreeMap;

/// One `bar N [...]:` / `bars N-M [...]:` line.
pub struct RawBar<'a> {
    pub bar_num: u32,
    pub end_bar: u32,
    pub inline_changes: Vec<String>,
    pub content: &'a str,
}

pub fn parse_bar_line(line: &str) -> Option<RawBar<'_>> {
    let body = line.trim();
    let after = body
        .strip_prefix("bar ")
        .or_else(|| body.strip_prefix("bars "))?;
    let (head, content) = after.split_once(':')?;
    let (range, changes) = if let Some(open) = head.find('[') {
        let close = head[open..].find(']')? + open;
        (
            head[..open].trim(),
            head[open + 1..close]
                .split(',')
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .collect(),
        )
    } else {
        (head.trim(), Vec::new())
    };
    let (bar_num, end_bar) = if let Some((a, b)) = range.split_once('-') {
        (a.trim().parse().ok()?, b.trim().parse().ok()?)
    } else {
        let n = range.parse().ok()?;
        (n, n)
    };
    Some(RawBar {
        bar_num,
        end_bar,
        inline_changes: changes,
        content: content.trim(),
    })
}

/// `mus.py::_split_bar_content` / `check.rs::split_bar_content`: split
/// `"a=C4q b=Rq"`-style content into `{abbrev: substring}` by scanning for
/// `<abbrev>=` at a token boundary.
pub fn split_bar_content(content: &str, abbrevs: &[String]) -> BTreeMap<String, String> {
    let mut positions = Vec::new();
    for (index, _) in content.match_indices('=') {
        let mut start = index;
        while start > 0 && !content.as_bytes()[start - 1].is_ascii_whitespace() {
            start -= 1;
        }
        let candidate = content[start..index].trim();
        if abbrevs.iter().any(|a| a == candidate) {
            positions.push((start, index + 1, candidate.to_string()));
        }
    }
    positions.sort_by_key(|(start, _, _)| *start);
    positions
        .iter()
        .enumerate()
        .map(|(i, (_, value_start, abbr))| {
            let end = positions
                .get(i + 1)
                .map(|(start, _, _)| *start)
                .unwrap_or(content.len());
            (abbr.clone(), content[*value_start..end].trim().to_string())
        })
        .collect()
}

/// The flattened result of walking every bar line in the source.
pub struct RawScore {
    /// `bar_content[b][abbrev]` — raw token text for one track's bar.
    pub bar_content: BTreeMap<u32, BTreeMap<String, String>>,
    /// Inline `tempo=`/`time=` changes, keyed by the range's *start* bar
    /// only (`mus_audio.py` line 1309: `inline_changes_at[mb.bar_num]`,
    /// never every bar `mb.bar_num..=mb.end_bar`).
    pub inline_tempo: BTreeMap<u32, f64>,
    pub inline_time: BTreeMap<u32, String>,
    /// The highest bar number any bar line declared — the `bar_count`
    /// fallback when the score has no `# bars:` header.
    pub max_bar: u32,
}

pub fn scan(source: &str, abbrevs: &[String]) -> RawScore {
    let mut bar_content = BTreeMap::new();
    let mut inline_tempo = BTreeMap::new();
    let mut inline_time = BTreeMap::new();
    let mut max_bar = 0u32;
    for line in source.lines() {
        let Some(bar) = parse_bar_line(line.trim_end()) else {
            continue;
        };
        max_bar = max_bar.max(bar.end_bar);
        let content_map = if bar.content == "tacet" {
            abbrevs
                .iter()
                .map(|a| (a.clone(), "-".to_string()))
                .collect()
        } else {
            split_bar_content(bar.content, abbrevs)
        };
        for b in bar.bar_num..=bar.end_bar {
            bar_content.insert(b, content_map.clone());
        }
        for c in &bar.inline_changes {
            let Some((k, v)) = c.split_once('=') else {
                continue;
            };
            let key = k.trim().to_ascii_lowercase();
            let v = v.trim();
            if key == "tempo" {
                if let Ok(t) = v.parse::<i64>() {
                    inline_tempo.insert(bar.bar_num, t as f64);
                }
            } else if key == "time" {
                inline_time.insert(bar.bar_num, v.to_string());
            }
        }
    }
    RawScore {
        bar_content,
        inline_tempo,
        inline_time,
        max_bar,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_ranges_tacet_and_inline_changes_at_range_start_only() {
        let bar = parse_bar_line("bars 2-4 [tempo=88, time=3/4]: a=C4q b=Rq").unwrap();
        assert_eq!(bar.bar_num, 2);
        assert_eq!(bar.end_bar, 4);
        assert_eq!(bar.inline_changes, vec!["tempo=88", "time=3/4"]);
        assert_eq!(bar.content, "a=C4q b=Rq");

        let split = split_bar_content("a=C4q Rq b=<E4 G4>h", &["a".into(), "b".into()]);
        assert_eq!(split["a"], "C4q Rq");
        assert_eq!(split["b"], "<E4 G4>h");

        let source = "bar 1: tacet\nbars 2-4 [tempo=88]: a=C4q\n";
        let scan = scan(source, &["a".to_string()]);
        assert_eq!(scan.bar_content[&1]["a"], "-");
        assert_eq!(scan.bar_content[&2]["a"], "C4q");
        assert_eq!(scan.bar_content[&3]["a"], "C4q");
        assert_eq!(scan.inline_tempo, BTreeMap::from([(2, 88.0)]));
        assert!(!scan.inline_tempo.contains_key(&3));
        assert!(!scan.inline_tempo.contains_key(&4));
        assert_eq!(scan.max_bar, 4);
    }
}
