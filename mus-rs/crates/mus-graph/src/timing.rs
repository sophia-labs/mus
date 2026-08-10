//! Shared rational-bar timing for graph faces.
//!
//! The graph remains in musical time (R6); this module is the one place where
//! a face derives seconds from the graph's tempo and meter maps. WD's layout
//! should consume this module instead of growing a second bar map.

use crate::ScoreGraph;
use mus_oplog::Frac;
use std::collections::BTreeMap;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct BarTiming {
    pub start_seconds: f64,
    pub length_ql: Frac,
    pub seconds_per_quarter: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct BarMap {
    pub bars: BTreeMap<u32, BarTiming>,
    pub total_seconds: f64,
}

impl BarMap {
    pub fn for_graph(graph: &ScoreGraph) -> Result<Self, TimingError> {
        let n_bars = graph
            .headers
            .get("bars")
            .map(|value| value.parse::<u32>())
            .transpose()
            .map_err(|_| TimingError::InvalidHeader("bars".into()))?
            .or_else(|| {
                graph
                    .current_events()
                    .iter()
                    .map(|(_, state, _)| state.bar)
                    .max()
            })
            .unwrap_or(0);
        let tempo_changes = tempo_changes(&graph.headers)?;
        let meter_changes = meter_changes(&graph.headers)?;
        let mut tempo_at = tempo_changes;
        let mut meter_at = meter_changes;
        for (bar, items) in &graph.inline_changes {
            for item in items {
                let Some((key, value)) = item.split_once('=') else {
                    continue;
                };
                match key.trim().to_ascii_lowercase().as_str() {
                    "tempo" => {
                        tempo_at.insert(
                            *bar,
                            value
                                .trim()
                                .parse::<f64>()
                                .map_err(|_| TimingError::InvalidChange(item.clone()))?,
                        );
                    }
                    "time" => {
                        meter_at.insert(*bar, parse_meter(value.trim())?);
                    }
                    _ => {}
                }
            }
        }

        let mut bars = BTreeMap::new();
        let mut tempo = *tempo_at.get(&1).unwrap_or(&96.0);
        let mut meter = *meter_at.get(&1).unwrap_or(&Frac::new(4, 1));
        if tempo <= 0.0 {
            return Err(TimingError::InvalidTempo(tempo));
        }
        let mut start_seconds = 0.0;
        for bar in 1..=n_bars {
            if let Some(value) = tempo_at.get(&bar) {
                tempo = *value;
                if tempo <= 0.0 {
                    return Err(TimingError::InvalidTempo(tempo));
                }
            }
            if let Some(value) = meter_at.get(&bar) {
                meter = *value;
            }
            let seconds_per_quarter = 60.0 / tempo;
            bars.insert(
                bar,
                BarTiming {
                    start_seconds,
                    length_ql: meter,
                    seconds_per_quarter,
                },
            );
            start_seconds += meter.as_f64() * seconds_per_quarter;
        }
        Ok(Self {
            bars,
            total_seconds: start_seconds,
        })
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum TimingError {
    InvalidHeader(String),
    InvalidChange(String),
    InvalidTempo(f64),
    InvalidMeter(String),
}

fn tempo_changes(headers: &BTreeMap<String, String>) -> Result<BTreeMap<u32, f64>, TimingError> {
    let mut out = BTreeMap::new();
    let Some(raw) = headers.get("tempo") else {
        return Ok(out);
    };
    let first = raw.split('(').next().unwrap_or(raw).trim();
    if !first.is_empty() {
        out.insert(
            1,
            first
                .parse::<f64>()
                .map_err(|_| TimingError::InvalidChange(raw.clone()))?,
        );
    }
    let mut rest: &str = raw.as_str();
    while let Some(open) = rest.find("(b") {
        let tail = &rest[open + 2..];
        let Some(close) = tail.find(')') else {
            return Err(TimingError::InvalidChange(raw.clone()));
        };
        let bar = tail[..close]
            .parse::<u32>()
            .map_err(|_| TimingError::InvalidChange(raw.clone()))?;
        let value = tail[close + 1..]
            .trim_start_matches([' ', ':', ',', '→', '-'])
            .split_whitespace()
            .next()
            .ok_or_else(|| TimingError::InvalidChange(raw.clone()))?;
        out.insert(
            bar,
            value
                .parse::<f64>()
                .map_err(|_| TimingError::InvalidChange(raw.clone()))?,
        );
        rest = &tail[close + 1..];
    }
    Ok(out)
}

fn meter_changes(headers: &BTreeMap<String, String>) -> Result<BTreeMap<u32, Frac>, TimingError> {
    let mut out = BTreeMap::new();
    let Some(raw) = headers.get("time") else {
        return Ok(out);
    };
    let first = raw.split('(').next().unwrap_or(raw).trim();
    if !first.is_empty() {
        out.insert(1, parse_meter(first)?);
    }
    // Header time changes are rare in the current corpus; parse the same
    // `(bN) value` notation as tempo changes when present.
    let mut rest: &str = raw.as_str();
    while let Some(open) = rest.find("(b") {
        let tail = &rest[open + 2..];
        let Some(close) = tail.find(')') else {
            return Err(TimingError::InvalidChange(raw.clone()));
        };
        let bar = tail[..close]
            .parse::<u32>()
            .map_err(|_| TimingError::InvalidChange(raw.clone()))?;
        let value = tail[close + 1..]
            .trim_start_matches([' ', ':', ',', '→', '-'])
            .split_whitespace()
            .next()
            .ok_or_else(|| TimingError::InvalidChange(raw.clone()))?;
        out.insert(bar, parse_meter(value)?);
        rest = &tail[close + 1..];
    }
    Ok(out)
}

fn parse_meter(value: &str) -> Result<Frac, TimingError> {
    let (num, den) = value
        .split_once('/')
        .ok_or_else(|| TimingError::InvalidMeter(value.into()))?;
    let num = num
        .trim()
        .parse::<i64>()
        .map_err(|_| TimingError::InvalidMeter(value.into()))?;
    let den = den
        .trim()
        .parse::<i64>()
        .map_err(|_| TimingError::InvalidMeter(value.into()))?;
    if num <= 0 || den <= 0 {
        return Err(TimingError::InvalidMeter(value.into()));
    }
    Ok(Frac::new(num * 4, den))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn derives_meter_and_tempo_changes_in_rational_bar_order() {
        let mut graph = ScoreGraph::default();
        graph.headers.insert("bars".into(), "3".into());
        graph.headers.insert("tempo".into(), "120".into());
        graph.headers.insert("time".into(), "4/4".into());
        graph
            .inline_changes
            .insert(2, vec!["tempo=60".into(), "time=3/4".into()]);
        let map = BarMap::for_graph(&graph).unwrap();
        assert_eq!(map.bars[&2].start_seconds, 2.0);
        assert_eq!(map.bars[&2].length_ql, Frac::new(3, 1));
        assert_eq!(map.total_seconds, 8.0);
    }
}
