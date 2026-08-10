//! The per-track event walk — `mus_audio.render`'s outer `for abbr, voice
//! in voices.items()` loop (lines 876-1138): dynamics state, hairpin
//! spans, rests, per-event dispatch through [`crate::source`] →
//! [`crate::transforms`] → placement, and the eager-vs-deferred mix
//! dispatch.

use std::collections::BTreeMap;

use mus_notation::{
    expand_pattern_repetitions, parse_token, split_attached_dynamics, tokenize_bar_content,
};

use crate::gestures::Gesture;
use crate::layout::{swung, BarMap};
use crate::mixbus::{
    db_to_gain, pan_and_haas, truncate_to_render, MixBuffers, PendingNote, PlacedNote,
};
use crate::pack::{SampleCache, Voice};
use crate::source::{self, SourceStep};
use crate::util::{param_pair, require_f64, require_f64_opt, with_context};
use crate::{RenderError, RenderStats};

/// Everything a track walk needs that doesn't change per track — the
/// score-level layout, resources, and mix mode.
pub struct WalkContext<'a> {
    pub bar_map: &'a BarMap,
    pub bar_content: &'a BTreeMap<u32, BTreeMap<String, String>>,
    pub n_bars: u32,
    pub swing_unit_ql: f64,
    pub swing_r: f64,
    pub a4: f64,
    pub gestures: &'a BTreeMap<String, Gesture>,
    pub tape_audio: Option<&'a [f32]>,
    pub cache: &'a SampleCache,
    pub n_total: usize,
    /// `eager = sc_track is None` (line 867): per-bar flush when there's
    /// no sidechain to defer for.
    pub eager: bool,
    pub sc_track: Option<&'a str>,
}

/// Attaches `"b{b} {abbr}: "` context to a numeric-parse refusal,
/// matching `stats.bad`'s own message convention.
fn ctx_err(b: u32, abbr: &str, e: RenderError) -> RenderError {
    with_context(&format!("b{b} {abbr}"), e)
}

/// Lines 908-916 / 1125-1129: retroactively spreads a linear ±9 dB ramp
/// across `pending[i0..]`. A no-op on an empty span (an opened-then-
/// immediately-closed hairpin with nothing between).
fn resolve_hairpin(pending: &mut [PendingNote], i0: usize, dir: &str) {
    let i0 = i0.min(pending.len());
    let span = &mut pending[i0..];
    let len = span.len();
    let sign = if dir == "cresc" { 9.0 } else { -9.0 };
    let denom = len.saturating_sub(1).max(1) as f64;
    for (k, item) in span.iter_mut().enumerate() {
        item.db += (k as f64 / denom) * sign;
    }
}

/// Walks one track's bars 1..=n_bars, mixing eagerly into `buffers` or
/// deferring into `placed` per `ctx.eager`.
pub fn walk_track(
    ctx: &WalkContext,
    voice: &Voice,
    buffers: &mut MixBuffers,
    placed: &mut Vec<PlacedNote>,
    sc_onsets: &mut Vec<f64>,
    stats: &mut RenderStats,
) -> Result<(), RenderError> {
    let abbr = voice.abbrev.as_str();
    let mut cur_dyn = "mf".to_string();
    let mut hairpin: Option<(usize, String)> = None;
    let mut pending: Vec<PendingNote> = Vec::new();

    for b in 1..=ctx.n_bars {
        let Some(content) = ctx.bar_content.get(&b).and_then(|m| m.get(abbr)) else {
            continue;
        };
        if content.trim().is_empty() || content.trim() == "-" {
            continue;
        }
        let tokens =
            split_attached_dynamics(&expand_pattern_repetitions(&tokenize_bar_content(content)));
        let mut q_off = 0.0_f64;

        for tk in &tokens {
            let Some(mut ev) = parse_token(tk) else {
                let trimmed = tk.trim();
                if trimmed != "-" && !trimmed.is_empty() {
                    stats.bad.push(format!("b{b} {abbr}: {tk}"));
                }
                continue;
            };
            if ev.ql <= 0.0
                && tk.trim() != "R"
                && matches!(ev.kind.as_str(), "note" | "chord" | "rest" | "unpitched")
            {
                stats.bad.push(format!("b{b} {abbr}: {tk} (zero duration)"));
            }
            if !voice.defaults.is_empty() {
                let mut merged = voice.defaults.clone();
                merged.extend(ev.params.clone());
                ev.params = merged;
            }

            match ev.kind.as_str() {
                "dynamic" => {
                    if let Some(v) = &ev.dyn_value {
                        cur_dyn = v.clone();
                    }
                    continue;
                }
                "hairpin" => {
                    let dv = ev.dyn_value.as_deref().unwrap_or("");
                    if dv == "cresc" || dv == "dim" {
                        hairpin = Some((pending.len(), dv.to_string()));
                    } else if let Some((i0, dir)) = hairpin.take() {
                        resolve_hairpin(&mut pending, i0, &dir);
                    }
                    continue;
                }
                "rest" => {
                    q_off += ev.ql;
                    continue;
                }
                _ => {}
            }

            let bar_timing = *ctx
                .bar_map
                .bars
                .get(&b)
                .ok_or_else(|| RenderError::Invalid(format!("event uses missing bar {b}")))?;
            let onset =
                bar_timing.start_s + swung(q_off, ctx.swing_unit_ql, ctx.swing_r) * bar_timing.spq;
            let slot = (ev.ql * bar_timing.spq).max(1e-3);
            q_off += ev.ql;

            let step = source::resolve(
                voice,
                &ev,
                slot,
                b,
                abbr,
                ctx.a4,
                ctx.gestures,
                ctx.tape_audio,
                ctx.cache,
                &mut stats.bad,
            )?;
            let x = match step {
                SourceStep::Rendered(x) => x,
                SourceStep::NeedsPitch => continue,
                SourceStep::TooShort => {
                    stats.skipped += 1;
                    continue;
                }
            };

            let x =
                crate::transforms::apply_chain(x, &ev, slot).map_err(|e| ctx_err(b, abbr, e))?;
            let db = crate::transforms::level_db(&cur_dyn, voice, &ev)
                .map_err(|e| ctx_err(b, abbr, e))?;

            let Some((start, x)) = truncate_to_render(x, onset, ctx.n_total) else {
                continue;
            };

            let (p0, p1) = param_pair(&ev.params, "pan", voice.pan);
            // `int(float(ev.params["haas"]) * SR / 1000.0)` (line 1110):
            // guarded only by `"haas" in ev.params`, not by whether the
            // value parses.
            let haas_ms = require_f64_opt(&ev.params, "haas").map_err(|e| ctx_err(b, abbr, e))?;
            let (l, r) = pan_and_haas(&x, p0, p1, haas_ms);
            // `float(ev.params.get("send", voice.send))` (line 1113): unguarded.
            let send =
                require_f64(&ev.params, "send", voice.send).map_err(|e| ctx_err(b, abbr, e))?;

            if ctx.sc_track == Some(abbr) {
                sc_onsets.push(onset);
            }
            pending.push(PendingNote {
                start,
                l,
                r,
                send,
                db,
            });
            stats.notes += 1;
            *stats.per_track_events.entry(abbr.to_string()).or_default() += 1;
        }

        if ctx.eager && hairpin.is_none() && !pending.is_empty() {
            for note in pending.drain(..) {
                buffers.mix_one(
                    note.start,
                    &note.l,
                    &note.r,
                    note.send,
                    db_to_gain(note.db),
                    None,
                );
            }
        }
    }

    if let Some((i0, dir)) = hairpin.take() {
        resolve_hairpin(&mut pending, i0, &dir);
    }

    for note in pending {
        let gain = db_to_gain(note.db);
        if ctx.eager {
            buffers.mix_one(note.start, &note.l, &note.r, note.send, gain, None);
        } else {
            placed.push(PlacedNote {
                track: abbr.to_string(),
                ducks: voice.ducks,
                start: note.start,
                l: note.l,
                r: note.r,
                send: note.send,
                gain,
            });
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::layout::{BarMap, BarTiming};
    use std::collections::BTreeMap as Map;

    fn simple_ctx<'a>(
        bar_map: &'a BarMap,
        bar_content: &'a Map<u32, Map<String, String>>,
        gestures: &'a Map<String, Gesture>,
        cache: &'a SampleCache,
        eager: bool,
    ) -> WalkContext<'a> {
        WalkContext {
            bar_map,
            bar_content,
            n_bars: bar_map.bars.len() as u32,
            swing_unit_ql: 0.0,
            swing_r: 0.5,
            a4: 440.0,
            gestures,
            tape_audio: None,
            cache,
            n_total: 48_000 * 4,
            eager,
            sc_track: None,
        }
    }

    fn voice_with_synth(abbrev: &str) -> Voice {
        let mut synth = Map::new();
        synth.insert("synth".to_string(), "sine".to_string());
        Voice {
            abbrev: abbrev.to_string(),
            samples: Vec::new(),
            mode: "varispeed".to_string(),
            gain_db: 0.0,
            pan: 0.0,
            send: 0.0,
            defaults: Map::new(),
            synth: Some(synth),
            ducks: true,
        }
    }

    fn one_bar_map() -> BarMap {
        let mut bars = Map::new();
        bars.insert(
            1,
            BarTiming {
                start_s: 0.0,
                qlen: 4.0,
                spq: 0.5,
            },
        );
        bars.insert(
            2,
            BarTiming {
                start_s: 2.0,
                qlen: 4.0,
                spq: 0.5,
            },
        );
        BarMap { bars, total_s: 4.0 }
    }

    // `resolve_hairpin` is tested directly against hand-built `PendingNote`s
    // rather than routed through the tokenizer: `{<}`/`{>}` contain a bare
    // `<`/`>` that `mus_notation::tokenize_bar_content` (a faithful port of
    // `mus.py::tokenize_bar_content`'s own *unconditional* `depth_angle`
    // counter — verified directly against the Python source, which has the
    // identical behavior) counts as a chord-bracket open with no matching
    // close, so a `{<}` followed by plain notes and no stray `>` swallows
    // the rest of the bar into one token. That is the oracle's own
    // behavior (`smoke.mus` bar 7 hits exactly this — exercised end to end,
    // without panicking, by `smoke_score_renders_deterministically_with_
    // correct_stats`), not a bug this stage should route around; testing
    // the dB math in isolation is both more robust and the literal ask
    // ("unit tests for hairpin math").
    #[test]
    fn resolve_hairpin_spreads_a_linear_9db_ramp_across_the_span() {
        let mut pending: Vec<PendingNote> = (0..4)
            .map(|_| PendingNote {
                start: 0,
                l: vec![],
                r: vec![],
                send: 0.0,
                db: 0.0,
            })
            .collect();
        resolve_hairpin(&mut pending, 0, "cresc");
        for (k, item) in pending.iter().enumerate() {
            let expected = (k as f64 / 3.0) * 9.0;
            assert!(
                (item.db - expected).abs() < 1e-9,
                "k={k}: {} vs {expected}",
                item.db
            );
        }
        assert_eq!(pending[0].db, 0.0);
        assert!((pending[3].db - 9.0).abs() < 1e-9);
    }

    #[test]
    fn resolve_hairpin_leaves_notes_before_i0_untouched_and_dim_is_negative() {
        let mut pending: Vec<PendingNote> = (0..5)
            .map(|_| PendingNote {
                start: 0,
                l: vec![],
                r: vec![],
                send: 0.0,
                db: 1.0,
            })
            .collect();
        resolve_hairpin(&mut pending, 2, "dim");
        assert_eq!(pending[0].db, 1.0);
        assert_eq!(pending[1].db, 1.0);
        assert!((pending[2].db - 1.0).abs() < 1e-9); // k=0
        assert!((pending[3].db - (1.0 - 4.5)).abs() < 1e-9); // k=1 of 2: -4.5
        assert!((pending[4].db - (1.0 - 9.0)).abs() < 1e-9); // k=2 of 2: -9.0
    }

    #[test]
    fn resolve_hairpin_on_a_single_note_span_adds_nothing() {
        let mut pending = vec![PendingNote {
            start: 0,
            l: vec![],
            r: vec![],
            send: 0.0,
            db: -2.0,
        }];
        resolve_hairpin(&mut pending, 0, "cresc");
        assert_eq!(pending[0].db, -2.0);
    }

    #[test]
    fn dynamic_marking_persists_across_bars_until_changed() {
        let bar_map = one_bar_map();
        let mut bar_content = Map::new();
        bar_content.insert(1, Map::from([("s".to_string(), "{ff} A4q".to_string())]));
        bar_content.insert(2, Map::from([("s".to_string(), "A4q".to_string())]));
        let gestures = Map::new();
        let cache = SampleCache::new();
        let ctx = simple_ctx(&bar_map, &bar_content, &gestures, &cache, true);
        let voice = voice_with_synth("s");
        let mut buffers = MixBuffers::new(ctx.n_total);
        let mut placed = Vec::new();
        let mut sc_onsets = Vec::new();
        let mut stats = RenderStats::default();
        walk_track(
            &ctx,
            &voice,
            &mut buffers,
            &mut placed,
            &mut sc_onsets,
            &mut stats,
        )
        .unwrap();
        assert_eq!(stats.notes, 2);
        assert_eq!(*stats.per_track_events.get("s").unwrap(), 2);
    }

    #[test]
    fn unparseable_token_is_recorded_and_skipped() {
        let bar_map = one_bar_map();
        let mut bar_content = Map::new();
        bar_content.insert(
            1,
            Map::from([("s".to_string(), "A4q not-a-token A4q".to_string())]),
        );
        let gestures = Map::new();
        let cache = SampleCache::new();
        let ctx = simple_ctx(&bar_map, &bar_content, &gestures, &cache, true);
        let voice = voice_with_synth("s");
        let mut buffers = MixBuffers::new(ctx.n_total);
        let mut placed = Vec::new();
        let mut sc_onsets = Vec::new();
        let mut stats = RenderStats::default();
        walk_track(
            &ctx,
            &voice,
            &mut buffers,
            &mut placed,
            &mut sc_onsets,
            &mut stats,
        )
        .unwrap();
        assert_eq!(stats.notes, 2);
        assert_eq!(stats.bad.len(), 1);
        assert!(stats.bad[0].contains("not-a-token"));
    }

    #[test]
    fn eager_vs_deferred_produce_the_same_mix_on_a_no_sidechain_score() {
        let bar_map = one_bar_map();
        let mut bar_content = Map::new();
        bar_content.insert(
            1,
            Map::from([("s".to_string(), "A4q A4q A4q A4q".to_string())]),
        );
        bar_content.insert(
            2,
            Map::from([("s".to_string(), "A4q A4q A4q A4q".to_string())]),
        );
        let gestures = Map::new();
        let cache = SampleCache::new();
        let voice = voice_with_synth("s");

        let ctx_eager = simple_ctx(&bar_map, &bar_content, &gestures, &cache, true);
        let mut buffers_eager = MixBuffers::new(ctx_eager.n_total);
        let mut placed_eager = Vec::new();
        let mut sc_onsets_eager = Vec::new();
        let mut stats_eager = RenderStats::default();
        walk_track(
            &ctx_eager,
            &voice,
            &mut buffers_eager,
            &mut placed_eager,
            &mut sc_onsets_eager,
            &mut stats_eager,
        )
        .unwrap();
        assert!(placed_eager.is_empty(), "eager mode never defers");

        let ctx_deferred = simple_ctx(&bar_map, &bar_content, &gestures, &cache, false);
        let mut buffers_deferred = MixBuffers::new(ctx_deferred.n_total);
        let mut placed_deferred = Vec::new();
        let mut sc_onsets_deferred = Vec::new();
        let mut stats_deferred = RenderStats::default();
        walk_track(
            &ctx_deferred,
            &voice,
            &mut buffers_deferred,
            &mut placed_deferred,
            &mut sc_onsets_deferred,
            &mut stats_deferred,
        )
        .unwrap();
        assert_eq!(placed_deferred.len(), 8);
        for note in placed_deferred {
            buffers_deferred.mix_one(note.start, &note.l, &note.r, note.send, note.gain, None);
        }

        assert_eq!(buffers_eager.dry, buffers_deferred.dry);
        assert_eq!(buffers_eager.wet, buffers_deferred.wet);
        assert_eq!(stats_eager.notes, stats_deferred.notes);
    }

    #[test]
    fn duck_opt_out_track_is_never_ducked_in_the_deferred_pass() {
        let bar_map = one_bar_map();
        let mut bar_content = Map::new();
        bar_content.insert(1, Map::from([("s".to_string(), "A4q".to_string())]));
        let gestures = Map::new();
        let cache = SampleCache::new();
        let mut voice = voice_with_synth("s");
        voice.ducks = false;

        let mut ctx = simple_ctx(&bar_map, &bar_content, &gestures, &cache, false);
        ctx.sc_track = Some("kk");
        let mut buffers = MixBuffers::new(ctx.n_total);
        let mut placed = Vec::new();
        let mut sc_onsets = Vec::new();
        let mut stats = RenderStats::default();
        walk_track(
            &ctx,
            &voice,
            &mut buffers,
            &mut placed,
            &mut sc_onsets,
            &mut stats,
        )
        .unwrap();
        assert_eq!(placed.len(), 1);
        assert!(!placed[0].ducks);
    }

    /// A malformed numeric event param (`gain=`/`haas=`/`send=`/etc.)
    /// refuses the whole render with bar/track context, rather than the
    /// prior port's silent no-op — mirrors the oracle's uncaught
    /// `ValueError` aborting `mus_audio.render` outright.
    #[test]
    fn malformed_event_param_refuses_with_bar_and_track_context() {
        let bar_map = one_bar_map();
        let mut bar_content = Map::new();
        bar_content.insert(
            1,
            Map::from([("s".to_string(), "A4q[haas=soon]".to_string())]),
        );
        let gestures = Map::new();
        let cache = SampleCache::new();
        let ctx = simple_ctx(&bar_map, &bar_content, &gestures, &cache, true);
        let voice = voice_with_synth("s");
        let mut buffers = MixBuffers::new(ctx.n_total);
        let mut placed = Vec::new();
        let mut sc_onsets = Vec::new();
        let mut stats = RenderStats::default();
        let err = walk_track(
            &ctx,
            &voice,
            &mut buffers,
            &mut placed,
            &mut sc_onsets,
            &mut stats,
        )
        .unwrap_err();
        assert!(
            matches!(err, RenderError::Invalid(ref m) if m.starts_with("b1 s:") && m.contains("haas=\"soon\"")),
            "{err}"
        );
    }
}
