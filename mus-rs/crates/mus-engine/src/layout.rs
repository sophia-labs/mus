//! Score-level layout: header scalars (tuning/reverb/master/swing/
//! sidechain), and the bar → seconds map (`mus_audio.py` lines 798-826).
//!
//! The bar map is a *direct* port of the Python loop rather than a reuse
//! of `mus_graph::timing::BarMap`: that module's own raw-header tempo/time
//! parser reads `"(bN)"` pairs as *(value-after-paren, bar-number)*, not
//! Python's *(value-before-paren, bar-number)* — correct for the bracket-
//! only inline-change convention its own unit test exercises, but silently
//! wrong (or `Err`) for the header prose form real corpus scores actually
//! use (`# tempo: 80 (b1) → 88 (b11) → …`, confirmed in `aigua.mus` and
//! `aigua_gliss.mus`). `_parse_header_change_list` (`mus.py` line 1362) is
//! the true oracle for that spelling; ported here as [`tempo_change_list`]/
//! [`time_change_list`].

use std::collections::BTreeMap;
use std::sync::OnceLock;

use regex::Regex;

use crate::util::with_context;
use crate::RenderError;

fn re_range_piece() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"^(\S+)\s*\(b(\d+)\)\s*$").unwrap())
}

fn re_tuning() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"A\s*=\s*([\d.]+)").unwrap())
}

fn re_reverb() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"([\d.]+)").unwrap())
}

fn re_master() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"rms\s*=\s*(-?[\d.]+)").unwrap())
}

/// A parsed header tempo value: a valid integer BPM, or — mirroring
/// `_parse_header_change_list`'s `coerce` (`mus.py` line 1368) — a value
/// that failed Python's `int()` and is carried forward *poisoned* rather
/// than dropped. Python's `coerce` never discards a piece it reaches: on
/// a `ValueError` it returns `v` unchanged, so the bar map still gets an
/// entry for that bar. Using it is where the oracle itself blows up
/// (`60.0 / "96.5"` is an uncaught `TypeError`), so [`build_bar_map`]
/// refuses there too — the first bar the poisoned value reaches — instead
/// of silently reverting to whatever tempo preceded it.
#[derive(Debug, Clone, PartialEq)]
pub enum TempoEntry {
    Bpm(f64),
    Poisoned(String),
}

/// `mus.py::_parse_header_change_list(s, to_int=True)` — tempo values.
/// `coerce` (line 1368) tries `int(v)` and, on failure, keeps `v` as a
/// poisoned string rather than dropping the piece — every branch below
/// keeps exactly one entry per piece it reaches, numeric or not, matching
/// that. `int()` (unlike `f64::parse`) rejects a fractional literal like
/// `"96.5"`, so a header tempo must parse as an integer to coerce clean.
pub fn tempo_change_list(raw: &str) -> Vec<(u32, TempoEntry)> {
    let s = raw.trim();
    if s.is_empty() {
        return Vec::new();
    }
    let coerce = |v: &str| match v.trim().parse::<i64>() {
        Ok(n) => TempoEntry::Bpm(n as f64),
        Err(_) => TempoEntry::Poisoned(v.to_string()),
    };
    if s.contains("(initial") {
        let first = s.split(' ').next().unwrap_or("");
        return vec![(1, coerce(first))];
    }
    if !s.contains('→') && !s.contains("(b") {
        return vec![(1, coerce(s))];
    }
    let mut out = Vec::new();
    for piece in s.split('→') {
        let piece = piece.trim();
        if let Some(caps) = re_range_piece().captures(piece) {
            // The bar number itself must parse (Python: `int(m.group(2))`
            // inside the same `try` that appends the tuple) — but only
            // the *value* half is coerce-and-keep; a bar number that
            // fails to parse drops the whole piece, matching Python's
            // `except Exception: pass` around the tuple append.
            if let Ok(b) = caps.get(2).unwrap().as_str().parse::<u32>() {
                out.push((b, coerce(caps.get(1).unwrap().as_str())));
            }
        } else {
            out.push((1, coerce(piece)));
        }
    }
    out
}

/// `mus.py::_parse_header_change_list(s, to_int=False)` — time-signature
/// values. Unlike the numeric variant, `coerce` never fails for a string
/// value, so every branch that reaches a piece keeps it.
pub fn time_change_list(raw: &str) -> Vec<(u32, String)> {
    let s = raw.trim();
    if s.is_empty() {
        return Vec::new();
    }
    if s.contains("(initial") {
        let first = s.split(' ').next().unwrap_or("");
        return vec![(1, first.to_string())];
    }
    if !s.contains('→') && !s.contains("(b") {
        return vec![(1, s.to_string())];
    }
    let mut out = Vec::new();
    for piece in s.split('→') {
        let piece = piece.trim();
        if let Some(caps) = re_range_piece().captures(piece) {
            if let Ok(bar) = caps.get(2).unwrap().as_str().parse::<u32>() {
                out.push((bar, caps.get(1).unwrap().as_str().to_string()));
            }
        } else {
            out.push((1, piece.to_string()));
        }
    }
    out
}

/// `mus_audio.py` lines 721-725: `# tuning: A=445.6` → `a4`, default 440.
/// The oracle's `float(tm.group(1))` has no `try/except`: when the regex
/// finds no `A=` at all, `a4` never leaves its `440.0` default (matched
/// here by a `None` capture); but a match whose captured text still
/// fails `float()` (the `[\d.]+` class allows multiple dots, e.g.
/// `A=1.2.3`) aborts the render there, so it refuses here too rather
/// than quietly falling back to 440 as if `A=` had never been written.
pub fn parse_tuning_a4(raw: Option<&String>) -> Result<f64, RenderError> {
    let Some(raw) = raw else { return Ok(440.0) };
    match re_tuning().captures(raw) {
        None => Ok(440.0),
        Some(caps) => {
            caps.get(1).unwrap().as_str().parse().map_err(|_| {
                RenderError::Invalid(format!("tuning header {raw:?} has a malformed A="))
            })
        }
    }
}

/// Lines 1153-1156: `# reverb: <seconds>`, clamped `[0.3, 12]`, default
/// 2.6. Same unguarded-`float()`-on-a-match shape as [`parse_tuning_a4`].
pub fn parse_reverb_seconds(raw: Option<&String>) -> Result<f64, RenderError> {
    let Some(raw) = raw else { return Ok(2.6) };
    match re_reverb().captures(raw) {
        None => Ok(2.6),
        Some(caps) => caps
            .get(1)
            .unwrap()
            .as_str()
            .parse::<f64>()
            .map(|v| v.clamp(0.3, 12.0))
            .map_err(|_| RenderError::Invalid(format!("reverb header {raw:?} is not a number"))),
    }
}

/// Lines 1163-1166: `# master: rms=<db>`, default -17.0. Same shape again.
pub fn parse_master_rms(raw: Option<&String>) -> Result<f64, RenderError> {
    let Some(raw) = raw else { return Ok(-17.0) };
    match re_master().captures(raw) {
        None => Ok(-17.0),
        Some(caps) => caps.get(1).unwrap().as_str().parse().map_err(|_| {
            RenderError::Invalid(format!("master header {raw:?} has a malformed rms="))
        }),
    }
}

/// Lines 780-788: `# swing: [unit] percent`. Returns `(swing_unit_ql,
/// swing_r)`; `(0.0, 0.5)` means "no swing" (matches [`swung`]'s guard).
pub fn parse_swing(raw: Option<&String>) -> (f64, f64) {
    let Some(raw) = raw else { return (0.0, 0.5) };
    let parts: Vec<&str> = raw.split_whitespace().collect();
    if parts.is_empty() {
        return (0.0, 0.5);
    }
    let parsed: Option<(i64, f64)> = if parts.len() > 1 {
        match (parts[0].parse::<i64>(), parts[1].parse::<f64>()) {
            (Ok(u), Ok(p)) => Some((u, p)),
            _ => None,
        }
    } else {
        parts[0].parse::<f64>().ok().map(|p| (16, p))
    };
    match parsed {
        Some((unit, pct)) if unit != 0 => {
            let swing_unit_ql = 4.0 / unit as f64;
            let swing_r = (pct / 100.0).clamp(0.5, 0.75);
            (swing_unit_ql, swing_r)
        }
        _ => (0.0, 0.5),
    }
}

/// `mus_audio.render`'s `swung()` closure (lines 790-796): shift every
/// second grid position at `swing_unit_ql` so the pair divides
/// `swing_r/(1-swing_r)` instead of 50/50. Onsets shift; notated durations
/// and bar accounting stay on the grid (the caller never feeds this back
/// into `q_off`).
pub fn swung(q_pos: f64, swing_unit_ql: f64, swing_r: f64) -> f64 {
    if swing_unit_ql <= 0.0 || swing_r <= 0.5 {
        return q_pos;
    }
    let k = (q_pos / swing_unit_ql + 1e-6).trunc() as i64;
    if k % 2 == 1 && (q_pos - k as f64 * swing_unit_ql).abs() < 1e-6 {
        q_pos + swing_unit_ql * (2.0 * swing_r - 1.0)
    } else {
        q_pos
    }
}

/// `# sidechain: <track> depth=0.75 rel=0.16` (lines 844-860).
#[derive(Debug, Clone, PartialEq)]
pub struct Sidechain {
    pub track: String,
    pub depth: f64,
    pub rel: f64,
}

pub fn parse_sidechain(raw: Option<&String>) -> Option<Sidechain> {
    let raw = raw?;
    let bits: Vec<&str> = raw.split_whitespace().collect();
    let track = (*bits.first()?).to_string();
    let mut depth = 0.75;
    let mut rel = 0.16;
    for bit in &bits[1..] {
        let Some((k, v)) = bit.split_once('=') else {
            continue;
        };
        match k.trim() {
            "depth" => {
                if let Ok(f) = v.parse::<f64>() {
                    depth = f;
                }
            }
            "rel" | "release" => {
                if let Ok(f) = v.parse::<f64>() {
                    rel = f;
                }
            }
            _ => {}
        }
    }
    Some(Sidechain { track, depth, rel })
}

/// One bar's timing, as `mus_audio.render`'s `bar_start`/`bar_qlen`/
/// `bar_spq` dicts (lines 816-826) carry it per-bar.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct BarTiming {
    pub start_s: f64,
    pub qlen: f64,
    pub spq: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct BarMap {
    pub bars: BTreeMap<u32, BarTiming>,
    pub total_s: f64,
}

/// Direct port of the bar-map loop (`mus_audio.py` lines 798-826).
/// `tempo_str`/`time_str` are the raw header values (`proposal.headers`);
/// `inline_tempo`/`inline_time` are the *range-start-bar-keyed* overrides
/// this module's caller collects from raw `bar`/`bars […]:` lines (never
/// every bar in a range — see [`crate::rawbars`]).
pub fn build_bar_map(
    tempo_str: Option<&String>,
    time_str: Option<&String>,
    inline_tempo: &BTreeMap<u32, f64>,
    inline_time: &BTreeMap<u32, String>,
    n_bars: u32,
) -> Result<BarMap, RenderError> {
    let mut tempo_at: BTreeMap<u32, TempoEntry> = tempo_str
        .map(|s| tempo_change_list(s))
        .unwrap_or_default()
        .into_iter()
        .collect();
    let mut time_at: BTreeMap<u32, String> = time_str
        .map(|s| time_change_list(s))
        .unwrap_or_default()
        .into_iter()
        .collect();
    // Inline `tempo=` (`rawbars::scan`) is already Python's *other* tempo
    // path — `tempo_at[mb.bar_num] = int(v)` inside a bare `try/except:
    // pass` (`mus_audio.py` line 806-810) — which silently drops a
    // malformed value rather than poisoning it, so it only ever produces
    // a clean `Bpm`.
    for (&bar, &v) in inline_tempo {
        tempo_at.insert(bar, TempoEntry::Bpm(v));
    }
    for (bar, v) in inline_time {
        time_at.insert(*bar, v.clone());
    }

    let mut tempo_cur = tempo_at.get(&1).cloned().unwrap_or(TempoEntry::Bpm(96.0));
    let mut tsig = time_at
        .get(&1)
        .cloned()
        .unwrap_or_else(|| "4/4".to_string());
    let mut bars = BTreeMap::new();
    let mut t = 0.0;
    for b in 1..=n_bars {
        if let Some(v) = tempo_at.get(&b) {
            tempo_cur = v.clone();
        }
        if let Some(v) = time_at.get(&b) {
            tsig = v.clone();
        }
        // `spq = 60.0 / tempo` (line 823): the point where a poisoned
        // string tempo raises `TypeError` in Python. Resolve (and refuse)
        // here, at first use, rather than at parse time — a poisoned
        // entry past `n_bars` is never reached by Python's own loop
        // either, so it must not refuse a score that never uses it.
        let tempo = match &tempo_cur {
            TempoEntry::Bpm(v) => *v,
            TempoEntry::Poisoned(raw) => {
                return Err(RenderError::Invalid(format!(
                    "bar {b}: tempo {raw:?} is not an integer"
                )));
            }
        };
        let (num, den) = parse_time_sig(&tsig).map_err(|e| with_context(&format!("bar {b}"), e))?;
        let qlen = num * 4.0 / den;
        let spq = 60.0 / tempo;
        bars.insert(
            b,
            BarTiming {
                start_s: t,
                qlen,
                spq,
            },
        );
        t += qlen * spq;
    }
    let total_s = t + 4.0;
    // `tempo=0` parses as a perfectly good integer — Python's crash there
    // is `60.0 / 0` raising `ZeroDivisionError`, not a poisoned string —
    // so it isn't caught above; unchecked, `spq` becomes `f64::INFINITY`,
    // `total_s` follows, and `(total_s * SR) as usize` at the call site
    // saturates to `usize::MAX` rather than panicking, which is a
    // multi-exabyte buffer allocation attempt, not a refusal. A negative
    // total (a negative time-signature numerator dividing out a negative
    // `qlen`) is the same shape of problem one level down — Python's own
    // `np.zeros((2, n_total))` raises `ValueError: negative dimensions`
    // for it. Catch both here, before the caller ever computes `n_total`.
    if !total_s.is_finite() || total_s <= 0.0 {
        return Err(RenderError::Invalid(format!(
            "computed render duration {total_s}s is not finite and positive \
             (check tempo/time headers for a zero or malformed tempo)"
        )));
    }
    Ok(BarMap { bars, total_s })
}

/// `num, den = (int(x) for x in tsig.split("/"))` (line 821) — unguarded:
/// a time signature that isn't shaped `N/D` with integer parts fails the
/// unpack/`int()` and aborts the render there (Python's `int()` rejects a
/// fractional literal like `"4.5"` outright, unlike a plain float parse);
/// `den == 0` parses fine but then aborts a line later at `qlen = num *
/// 4.0 / den` (Python's `/` on floats raises `ZeroDivisionError`, unlike
/// IEEE-754 `inf`). All three refuse here instead of silently
/// substituting 4/4 or accepting a fractional numerator/denominator.
fn parse_time_sig(tsig: &str) -> Result<(f64, f64), RenderError> {
    let bad = || RenderError::Invalid(format!("time signature {tsig:?} is not N/D"));
    let (n, d) = tsig.split_once('/').ok_or_else(bad)?;
    let n: i64 = n.trim().parse().map_err(|_| bad())?;
    let d: i64 = d.trim().parse().map_err(|_| bad())?;
    if d == 0 {
        return Err(RenderError::Invalid(format!(
            "time signature {tsig:?} has a zero denominator"
        )));
    }
    Ok((n as f64, d as f64))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tempo_change_list_handles_plain_arrow_and_initial_forms() {
        assert_eq!(tempo_change_list("96"), vec![(1, TempoEntry::Bpm(96.0))]);
        assert_eq!(
            tempo_change_list("80 (b1) → 88 (b11) → 104 (b23)"),
            vec![
                (1, TempoEntry::Bpm(80.0)),
                (11, TempoEntry::Bpm(88.0)),
                (23, TempoEntry::Bpm(104.0)),
            ]
        );
        assert_eq!(
            tempo_change_list("80 (initial; 4 changes inline)"),
            vec![(1, TempoEntry::Bpm(80.0))]
        );
        assert_eq!(tempo_change_list(""), Vec::<(u32, TempoEntry)>::new());
    }

    /// `coerce` (`mus.py` line 1368) tries `int(v)` and, on failure,
    /// returns `v` unchanged rather than dropping the piece — a fractional
    /// or non-numeric tempo must survive into the list as a poisoned
    /// entry, not vanish. `int()` also rejects fractional literals that a
    /// plain `f64` parse would happily accept, so `"96.5"` must poison,
    /// not become `96.5` as a float BPM.
    #[test]
    fn tempo_change_list_poisons_a_fractional_or_non_numeric_piece_instead_of_dropping_it() {
        assert_eq!(
            tempo_change_list("96.5"),
            vec![(1, TempoEntry::Poisoned("96.5".to_string()))]
        );
        assert_eq!(
            tempo_change_list("fast"),
            vec![(1, TempoEntry::Poisoned("fast".to_string()))]
        );
        assert_eq!(
            tempo_change_list("80 (b1) → 96.5 (b9) → 104 (b23)"),
            vec![
                (1, TempoEntry::Bpm(80.0)),
                (9, TempoEntry::Poisoned("96.5".to_string())),
                (23, TempoEntry::Bpm(104.0)),
            ]
        );
    }

    #[test]
    fn time_change_list_keeps_string_values() {
        assert_eq!(time_change_list("4/4"), vec![(1, "4/4".to_string())]);
        assert_eq!(
            time_change_list("4/4 (b1) → 3/4 (b9)"),
            vec![(1, "4/4".to_string()), (9, "3/4".to_string())]
        );
    }

    #[test]
    fn swung_shifts_only_odd_grid_positions_past_50_50() {
        let (unit, r) = parse_swing(Some(&"16 56".to_string()));
        assert!((unit - 0.25).abs() < 1e-12);
        assert!((r - 0.56).abs() < 1e-12);
        let shift = unit * (2.0 * r - 1.0); // 0.03
        assert_eq!(swung(0.0, unit, r), 0.0); // k=0 (even): unshifted
        assert!((swung(0.25, unit, r) - (0.25 + shift)).abs() < 1e-12); // k=1 (odd): shifted
        assert_eq!(swung(0.5, unit, r), 0.5); // k=2 (even): unshifted
                                              // Cross-checked against `mus-cli check`'s own reference swing math
                                              // (crates/mus-cli/src/check.rs's `swung` unit test, same "16 56").
        assert!((swung(0.75, unit, r) - 0.78).abs() < 1e-12); // k=3 (odd): shifted
                                                              // Off-grid positions (not exactly on a swing-unit boundary) never shift.
        assert!((swung(0.30, unit, r) - 0.30).abs() < 1e-12);
    }

    #[test]
    fn swing_disabled_at_exactly_50_percent() {
        let (unit, r) = parse_swing(Some(&"16 50".to_string()));
        assert_eq!(swung(0.25, unit, r), 0.25);
    }

    #[test]
    fn bar_map_matches_the_python_loop_with_a_tempo_change() {
        let inline_tempo = BTreeMap::from([(3u32, 120.0)]);
        let map = build_bar_map(
            Some(&"96".to_string()),
            Some(&"4/4".to_string()),
            &inline_tempo,
            &BTreeMap::new(),
            4,
        )
        .unwrap();
        // bar1..2 at 96bpm, 4/4: qlen=4, spq=60/96=0.625, dur=2.5s each
        assert!((map.bars[&1].start_s - 0.0).abs() < 1e-9);
        assert!((map.bars[&2].start_s - 2.5).abs() < 1e-9);
        assert!((map.bars[&3].start_s - 5.0).abs() < 1e-9);
        // bar3 onward at 120bpm: spq=0.5, dur=2.0s
        assert!((map.bars[&3].spq - 0.5).abs() < 1e-9);
        assert!((map.bars[&4].start_s - 7.0).abs() < 1e-9);
        assert!((map.total_s - 9.0 - 4.0).abs() < 1e-9);
    }

    #[test]
    fn malformed_time_signature_refuses_instead_of_defaulting_to_4_4() {
        let err = build_bar_map(
            Some(&"96".to_string()),
            Some(&"four-four".to_string()),
            &BTreeMap::new(),
            &BTreeMap::new(),
            1,
        )
        .unwrap_err();
        assert!(
            matches!(err, RenderError::Invalid(ref m) if m.contains("bar 1") && m.contains("four-four")),
            "{err}"
        );

        // A present-but-zero denominator parses fine as two ints, then
        // aborts at the division a line later — still a refusal, not 4/4.
        let err = build_bar_map(
            Some(&"96".to_string()),
            Some(&"4/0".to_string()),
            &BTreeMap::new(),
            &BTreeMap::new(),
            1,
        )
        .unwrap_err();
        assert!(
            matches!(err, RenderError::Invalid(ref m) if m.contains("zero denominator")),
            "{err}"
        );
    }

    /// `int(x) for x in tsig.split("/")` (line 821) rejects a fractional
    /// component outright — a plain `f64` parse of "4.5" would not.
    #[test]
    fn time_signature_with_a_fractional_component_refuses() {
        let err = build_bar_map(
            Some(&"96".to_string()),
            Some(&"4.5/4".to_string()),
            &BTreeMap::new(),
            &BTreeMap::new(),
            1,
        )
        .unwrap_err();
        assert!(
            matches!(err, RenderError::Invalid(ref m) if m.contains("4.5/4")),
            "{err}"
        );
    }

    /// A header tempo that fails `int()` must poison the bar map — a
    /// refusal the first bar that reaches it, not a silent revert to the
    /// prior tempo (96 default here). Mirrors Python's `60.0 / "96.5"`
    /// `TypeError` crashing `render()` outright.
    #[test]
    fn poisoned_header_tempo_refuses_at_the_first_bar_that_uses_it() {
        let err = build_bar_map(
            Some(&"96.5".to_string()),
            Some(&"4/4".to_string()),
            &BTreeMap::new(),
            &BTreeMap::new(),
            2,
        )
        .unwrap_err();
        assert!(
            matches!(err, RenderError::Invalid(ref m) if m.contains("bar 1") && m.contains("96.5")),
            "{err}"
        );
    }

    /// A poisoned tempo change landing on a bar the score never reaches
    /// (past `n_bars`) is never used — Python's own loop (`for b in
    /// range(1, n_bars + 1)`) never queries that bar either, so a score
    /// that happens to declare a bogus later tempo change must still
    /// render cleanly up to its actual length.
    #[test]
    fn poisoned_header_tempo_past_n_bars_never_refuses() {
        let map = build_bar_map(
            Some(&"80 (b1) → 96.5 (b9)".to_string()),
            Some(&"4/4".to_string()),
            &BTreeMap::new(),
            &BTreeMap::new(),
            4,
        )
        .unwrap();
        assert!((map.bars[&4].spq - 60.0 / 80.0).abs() < 1e-9);
    }

    /// `tempo=0` parses cleanly as an integer (Python's crash there is a
    /// plain `ZeroDivisionError`, not a poisoned string), so it must be
    /// caught by the finite/positive duration guard: unchecked, `spq`
    /// becomes `+inf`, `total_s` follows, and the caller's `(total_s *
    /// SR) as usize` saturates to `usize::MAX` — a refusal here is the
    /// only thing standing between a zero-tempo header and an attempted
    /// multi-exabyte buffer allocation.
    #[test]
    fn zero_tempo_refuses_instead_of_an_infinite_duration() {
        let err = build_bar_map(
            Some(&"0".to_string()),
            Some(&"4/4".to_string()),
            &BTreeMap::new(),
            &BTreeMap::new(),
            2,
        )
        .unwrap_err();
        assert!(
            matches!(err, RenderError::Invalid(ref m) if m.contains("not finite and positive")),
            "{err}"
        );
    }

    /// Same shape, via an inline `tempo=0` (the *other* tempo path —
    /// `rawbars::scan`'s already-parsed `f64`, which skips the poisoning
    /// question entirely since 0 parses fine) — the finite/positive guard
    /// must catch it too, not just the header path.
    #[test]
    fn zero_inline_tempo_also_refuses_instead_of_an_infinite_duration() {
        let inline_tempo = BTreeMap::from([(1u32, 0.0)]);
        let err = build_bar_map(
            Some(&"96".to_string()),
            Some(&"4/4".to_string()),
            &inline_tempo,
            &BTreeMap::new(),
            2,
        )
        .unwrap_err();
        assert!(
            matches!(err, RenderError::Invalid(ref m) if m.contains("not finite and positive")),
            "{err}"
        );
    }

    #[test]
    fn malformed_tuning_reverb_master_headers_refuse_when_the_regex_matches_but_parse_fails() {
        // The `[\d.]+` char class matches a doubled decimal point, which
        // `float()`/`str::parse` both then reject.
        assert!(parse_tuning_a4(Some(&"A=1.2.3".to_string())).is_err());
        assert!(parse_reverb_seconds(Some(&"1.2.3".to_string())).is_err());
        assert!(parse_master_rms(Some(&"rms=1.2.3".to_string())).is_err());
        // No match at all still defaults cleanly (the regex simply never
        // captures, so `float()` is never reached in the oracle either).
        assert_eq!(parse_tuning_a4(Some(&"woo".to_string())).unwrap(), 440.0);
        assert_eq!(parse_reverb_seconds(None).unwrap(), 2.6);
        assert_eq!(parse_master_rms(Some(&"".to_string())).unwrap(), -17.0);
    }
}
