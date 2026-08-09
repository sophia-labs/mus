#!/usr/bin/env python3
"""Generate the browser showcase for "Aiguá: Three States of Water".

Reads the receipted v2 analysis outputs (sweep-events, sweep-report,
cluster-stability-report), the rendered MP3, and the score, and emits a fully
self-contained aigua/render/showcase.html: no external requests, audio as a
data URI, every figure derived from the same artifacts the run receipts name.

The page is dark-committed (spectrograms live on black). The categorical
palette is the three consensus states, validated for CVD separation and
contrast against the page ground: ice #189FC4, liquid #7D6BF2, vapor #BD7A3E.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "render" / "showcase.html"

SECTIONS = [
    {"name": "vapor", "t0": 0, "t1": 48, "state": "vapor",
     "text": "nothing in this section has a pitch. that is a finding, not a failure."},
    {"name": "liquid", "t0": 48, "t1": 96, "state": "liquid",
     "text": "the ensemble heard every one of these calls in two octaves at once."},
    {"name": "ice", "t0": 96, "t1": 152, "state": "ice",
     "text": "only what all three estimators agreed on. a quarter of the recording."},
    {"name": "correction", "t0": 152, "t1": 184, "state": "vapor",
     "text": "first the claim, then the evidence. then silence for the thirty-one events that refused a pitch."},
    {"name": "release", "t0": 184, "t1": 196, "state": "liquid",
     "text": "the one non-bird protagonist passes once, unclustered, and the place is itself again."},
]

CAST = {
    "h67": "the aria — 36.1 semitones in 0.19 s, the widest gesture the ensemble would stand behind",
    "h70": "the purest ice — 74% of its frames resolved, the cleanest event in the corpus",
    "h71": "the liquid figure — 68% octave-conflict: its backbone and its shadow are both quoted",
    "h57": "the thread — 25 semitones across 0.79 s, but only 14% of it ever resolved",
}


def dominant(rf: float, of: float, df: float) -> str:
    m = max(rf, of, df)
    return "ice" if m == rf else ("liquid" if m == of else "vapor")


def main() -> None:
    sweep = json.loads((HERE / "v2" / "sweep-events.json").read_text("utf-8"))["events"]
    report = json.loads((HERE / "v2" / "sweep-report.json").read_text("utf-8"))
    stab = json.loads((HERE / "v2" / "cluster-stability-report.json").read_text("utf-8"))
    score_text = (HERE / "aigua_states.mus").read_text("utf-8")
    mp3 = base64.b64encode((HERE / "render" / "aigua_states.mp3").read_bytes()).decode()

    fam = {0: "buzz", 1: "chup", 2: "mid", 3: "call", 4: "bright", 5: "glide", 6: "tick"}
    timeline = []
    for e in sweep:
        if "error" in e:
            continue
        cs = e["consensus_summary"]
        rf = cs["resolved_fraction"]
        of = cs["octave_conflict_count"] / max(cs["total_frame_count"], 1)
        df = cs["disagreement_count"] / max(cs["total_frame_count"], 1)
        m = e.get("v1_match") or {}
        timeline.append({
            "t0": round(e["start_seconds"], 3),
            "d": round(e["end_seconds"] - e["start_seconds"], 3),
            "s": dominant(rf, of, df),
            "sup": e["support_fraction"],
            "fam": fam.get(m.get("v1_cluster"), "—"),
            "span": e.get("resolved_span_st"),
        })

    contours = {}
    for key in CAST:
        idx = int(key[1:])
        contours[key] = {"contour": sweep[idx]["contour"],
                         "t0": sweep[idx]["start_seconds"],
                         "note": CAST[key]}

    paired = [[p["v1_span_st"], p["v2_span_st"]] for p in report["paired_span_comparison"]]
    comps = sorted((len(c) for c in stab["consensusComponents"]), reverse=True)
    fs = report["frame_state_totals"]
    total_frames = sum(fs.values())

    data = {
        "sections": SECTIONS,
        "timeline": timeline,
        "contours": contours,
        "paired": paired,
        "components": comps,
        "stats": {
            "resolvedPct": round(100 * fs["resolved"] / total_frames),
            "octavePct": round(100 * fs["octave-conflict"] / total_frames),
            "disagreePct": round(100 * fs["disagreement"] / total_frames),
            "v1Median": report["v1_span_st_reference"]["median"],
            "v2Median": report["resolved_span_st"]["median"],
            "spanDefined": report["event_counts"]["span_defined"],
            "spanUndefined": report["event_counts"]["span_undefined"],
            "hypotheses": report["event_counts"]["hypotheses"],
            "ari": round(stab["v1Comparison"]["adjustedRandIndex_fullWardK7_vs_v1"], 3),
            "nComponents": len(comps),
        },
    }

    html = TEMPLATE
    html = html.replace("__DATA__", json.dumps(data, separators=(",", ":")))
    html = html.replace("__MP3__", mp3)
    html = html.replace("__SCORE__", score_text.replace("&", "&amp;").replace("<", "&lt;"))
    OUT.write_text(html, "utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")


TEMPLATE = r"""<meta charset="utf-8">
<title>Aiguá: Three States of Water</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {
    --ground: #0B141B;
    --well: #0F1B24;
    --line: #1D2E3A;
    --ink: #E8F0F4;
    --ink-2: #9FB4C0;
    --ink-3: #5F7683;
    --ice: #189FC4;
    --liquid: #7D6BF2;
    --vapor: #BD7A3E;
    --ice-hi: #7FD0E3;
    --liquid-hi: #A99BF7;
    --vapor-hi: #D9A76C;
    --serif: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
    --sans: -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--ground); color: var(--ink);
    font-family: var(--sans); font-size: 16px; line-height: 1.65;
    -webkit-font-smoothing: antialiased;
  }
  main { max-width: 860px; margin: 0 auto; padding: 0 24px 96px; }
  .eyebrow {
    font-family: var(--mono); font-size: 11px; letter-spacing: 0.18em;
    text-transform: uppercase; color: var(--ink-3);
  }
  h1 {
    font-family: var(--serif); font-weight: 400; font-size: clamp(38px, 6vw, 58px);
    line-height: 1.08; margin: 10px 0 14px; text-wrap: balance;
  }
  h1 em { font-style: italic; color: var(--ice-hi); }
  h2 {
    font-family: var(--serif); font-weight: 400; font-size: 27px;
    margin: 72px 0 6px; text-wrap: balance;
  }
  h2 .no { font-family: var(--mono); font-size: 12px; color: var(--ink-3); vertical-align: 0.5em; margin-right: 8px; }
  p { max-width: 62ch; color: var(--ink-2); margin: 12px 0; }
  p strong { color: var(--ink); font-weight: 600; }
  .dek { font-size: 18px; max-width: 56ch; }
  a { color: var(--ice-hi); }
  .s-ice { color: var(--ice-hi); } .s-liquid { color: var(--liquid-hi); } .s-vapor { color: var(--vapor-hi); }

  /* ---- player: the scrubber is the form ---- */
  .player {
    margin: 44px 0 8px; background: var(--well); border: 1px solid var(--line);
    border-radius: 10px; padding: 22px;
  }
  .player-row { display: flex; gap: 18px; align-items: center; }
  #play {
    width: 52px; height: 52px; border-radius: 50%; flex: none; cursor: pointer;
    border: 1px solid var(--line); background: var(--ground); color: var(--ink);
    font-size: 18px; display: grid; place-items: center;
  }
  #play:hover { border-color: var(--ice); }
  #play:focus-visible { outline: 2px solid var(--ice-hi); outline-offset: 2px; }
  .scrub { flex: 1; }
  #form-bar {
    position: relative; height: 56px; cursor: pointer; border-radius: 6px; overflow: hidden;
    display: flex; gap: 2px; background: var(--ground);
  }
  #form-bar:focus-visible { outline: 2px solid var(--ice-hi); outline-offset: 2px; }
  .seg { position: relative; height: 100%; }
  .seg .fill { position: absolute; inset: 0; opacity: 0.28; }
  .seg .label {
    position: absolute; left: 8px; bottom: 5px; font-family: var(--mono);
    font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink-2);
  }
  .seg.lit .fill { opacity: 0.55; }
  .seg.lit .label { color: var(--ink); }
  #playhead {
    position: absolute; top: 0; bottom: 0; width: 2px; background: var(--ink);
    pointer-events: none; left: 0;
  }
  .player-meta {
    display: flex; justify-content: space-between; align-items: baseline;
    margin-top: 10px; gap: 16px;
  }
  #section-text { font-family: var(--serif); font-style: italic; font-size: 15px; color: var(--ink-2); }
  #clock { font-family: var(--mono); font-size: 12px; color: var(--ink-3); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .provenote { font-family: var(--mono); font-size: 11px; color: var(--ink-3); margin-top: 6px; }

  /* ---- stat band ---- */
  .states { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin: 28px 0; }
  .state-tile { background: var(--well); border: 1px solid var(--line); border-radius: 10px; padding: 18px; border-top: 3px solid; }
  .state-tile.ice { border-top-color: var(--ice); }
  .state-tile.liquid { border-top-color: var(--liquid); }
  .state-tile.vapor { border-top-color: var(--vapor); }
  .state-tile .pct { font-family: var(--serif); font-size: 40px; line-height: 1; }
  .state-tile .name { font-family: var(--mono); font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; margin-top: 6px; }
  .state-tile .what { font-size: 13px; color: var(--ink-2); margin-top: 8px; line-height: 1.5; }
  @media (max-width: 640px) { .states { grid-template-columns: 1fr; } }

  figure { margin: 26px 0; }
  figcaption { font-size: 13px; color: var(--ink-3); margin-top: 8px; max-width: 70ch; }
  .chart { background: var(--well); border: 1px solid var(--line); border-radius: 10px; padding: 16px; }
  svg { display: block; width: 100%; height: auto; }
  svg text { font-family: var(--mono); font-size: 10.5px; fill: var(--ink-3); }
  svg .axis { stroke: var(--line); stroke-width: 1; }

  .cards { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  @media (max-width: 720px) { .cards { grid-template-columns: 1fr; } }
  .card { background: var(--well); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; }
  .card h3 { font-family: var(--mono); font-size: 12px; letter-spacing: 0.08em; margin: 0 0 2px; color: var(--ink); font-weight: 600; }
  .card .note { font-size: 12.5px; color: var(--ink-3); line-height: 1.5; margin-bottom: 6px; }

  #tip {
    position: fixed; pointer-events: none; background: var(--ground); border: 1px solid var(--line);
    color: var(--ink); font-family: var(--mono); font-size: 11.5px; padding: 6px 9px;
    border-radius: 6px; opacity: 0; transition: opacity 80ms; z-index: 10; max-width: 260px;
  }
  @media (prefers-reduced-motion: reduce) { #tip { transition: none; } }

  details.score { margin: 20px 0; }
  details.score summary { cursor: pointer; font-family: var(--mono); font-size: 13px; color: var(--ice-hi); }
  details.score pre {
    background: var(--well); border: 1px solid var(--line); border-radius: 10px;
    padding: 18px; overflow-x: auto; font-family: var(--mono); font-size: 12px;
    line-height: 1.55; color: var(--ink-2);
  }
  .prov {
    background: var(--well); border: 1px solid var(--line); border-radius: 10px;
    padding: 18px; overflow-x: auto; font-family: var(--mono); font-size: 12px;
    line-height: 1.7; color: var(--ink-2); white-space: pre;
  }
  footer { margin-top: 72px; font-size: 13px; color: var(--ink-3); border-top: 1px solid var(--line); padding-top: 18px; }
</style>

<main>
  <header style="padding-top:64px">
    <div class="eyebrow">Sophia Labs · MUS / Aiguá analysis v2 · 2026-08-09</div>
    <h1>Aiguá: <em>Three States of Water</em></h1>
    <p class="dek">A 56-second field recording from Aiguá, Uruguay, re-analysed by a
    three-estimator pitch ensemble that is allowed to say <strong>"we disagree"</strong> —
    and a piece of music in which what resolved becomes melody, what split into octaves
    becomes shimmer, and what refused becomes the tape itself.</p>
  </header>

  <div class="player">
    <div class="player-row">
      <button id="play" aria-label="Play">&#9654;</button>
      <div class="scrub">
        <div id="form-bar" tabindex="0" role="slider" aria-label="Seek. The bar is the piece's form: vapor, liquid, ice, correction, release." aria-valuemin="0" aria-valuemax="196" aria-valuenow="0">
          <div id="playhead"></div>
        </div>
      </div>
    </div>
    <div class="player-meta">
      <div id="section-text">press play — the seek bar is the score's form</div>
      <div id="clock">0:00 / 3:16</div>
    </div>
    <div class="provenote">48 bars · A = 433.7 Hz — the consensus pitch of the place · every melodic figure is a measured gesture, quoted</div>
  </div>

  <h2><span class="no">§1</span>One recording, three verdicts per frame</h2>
  <p>Ask "what pitch is this bird singing?" and honest instrumentation returns one of
  three answers. Three independent estimators — subharmonic summation, probabilistic
  YIN, and a dominant spectral ridge — vote frame by frame. Where they agree within
  80 cents, the pitch is <strong class="s-ice">resolved</strong>. Where they agree
  only after folding octaves, the call was heard in two registers at once:
  <strong class="s-liquid">octave-conflict</strong>. Where they simply differ, the
  only honest report is <strong class="s-vapor">disagreement</strong>.</p>

  <div class="states">
    <div class="state-tile ice"><div class="pct s-ice" id="pct-ice"></div>
      <div class="name s-ice">resolved · ice</div>
      <div class="what">Consensus pitch, defensible to 80 cents. Becomes the chorale, the aria, every quoted melody.</div></div>
    <div class="state-tile liquid"><div class="pct s-liquid" id="pct-liquid"></div>
      <div class="name s-liquid">octave-conflict · liquid</div>
      <div class="what">Two octaves heard at once. Becomes the shimmer: each figure quoted twice, backbone left, shadow right.</div></div>
    <div class="state-tile vapor"><div class="pct s-vapor" id="pct-vapor"></div>
      <div class="name s-vapor">disagreement · vapor</div>
      <div class="what">No defensible pitch. Becomes the tape itself — the recording pointed into at its own uncertain moments.</div></div>
  </div>

  <figure>
    <div class="chart"><svg id="timeline" viewBox="0 0 900 150" role="img" aria-label="Timeline of 113 reconciled events across the 56-second recording, coloured by dominant consensus state"></svg></div>
    <figcaption>The 56-second recording as the segmentation lattice hears it: 113 reconciled
    event hypotheses, each coloured by its dominant consensus state. Full-height bars were
    proposed by both detectors; half-height bars by only one. Hover for each event's verdict.</figcaption>
  </figure>

  <h2><span class="no">§2</span>The quotations</h2>
  <p>MUS notation gained one verb from all this: <code style="font-family:var(--mono);font-size:14px;color:var(--ice-hi)">gest=</code>,
  which quotes a measured contour the way engraved music quotes a folk tune. The piece's
  cast, drawn as the ensemble measured them — solid where resolved, hollow where the
  octave split, and gaps where nothing survived:</p>

  <div class="cards" id="contour-cards"></div>

  <h2><span class="no">§3</span>The correction, sounded</h2>
  <p>Version 1 of this analysis — one estimator, no cross-examination — claimed the
  birds' median call spans <strong>18.7 semitones</strong>. The ensemble, counting only
  frames all methods stand behind, measures the same events at a median of
  <strong>7.0</strong>. A single unnoticed octave error inflates a span by twelve
  semitones; that is the fog the consensus burns off. The piece plays the old claim as
  the straight synthetic line it always was, then answers with the measured shapes —
  and holds two bars of silence for the <span id="undef-n"></span> events that refused
  a pitch entirely.</p>

  <figure>
    <div class="chart"><svg id="spans" viewBox="0 0 900 420" role="img" aria-label="Scatter of per-event pitch spans, v1 single-estimator versus v2 consensus"></svg></div>
    <figcaption>Each point is one event measured by both analyses. Below the diagonal,
    v1 overstated. The claim didn't survive; the tail did — some calls genuinely
    sweep three octaves.</figcaption>
  </figure>

  <h2><span class="no">§4</span>Do the seven families survive?</h2>
  <p>v1 sorted the birds into seven families and the piece's instruments were built
  from them. 228 re-clusterings — bootstrap resamples, different k, different
  algorithms, dropped features — say the taxonomy was one telling of a looser truth:
  at 80% co-assignment the events form <span id="n-comp"></span> small components,
  and the v2 partition agrees with v1's at an adjusted Rand index of just
  <span id="ari"></span>. One structure is robust: <strong>the big core where v1's
  <em>call</em> and <em>bright</em> families merge</strong> — plausibly one bird's one
  behaviour, heard twice.</p>

  <figure>
    <div class="chart"><svg id="comps" viewBox="0 0 900 170" role="img" aria-label="Consensus component sizes from 228 clustering runs"></svg></div>
    <figcaption>Consensus components at the 0.8 co-assignment threshold, from 228 label
    runs over 82 events. The 26-event core is v1's call+bright, merged; the long tail
    of singletons is structure that exists only under some methods.</figcaption>
  </figure>

  <h2><span class="no">§5</span>The score</h2>
  <p>MUS is a notation designed to be read — by you in engraving, by a language model
  as text. This piece adds one header (<span style="font-family:var(--mono);font-size:14px">gestures:</span>)
  and quotes evidence the way older scores quote scripture.</p>
  <details class="score"><summary>aigua_states.mus — 48 bars, full text</summary>
  <pre>__SCORE__</pre></details>

  <h2><span class="no">§6</span>Provenance</h2>
  <p>Every number on this page traces to a content-addressed research object: write-once
  artifacts, run receipts naming exact input bytes, refusal states preserved. The piece
  is reproducible from the committed repository.</p>
  <div class="prov" id="prov"></div>

  <footer>
    Recorded Aiguá, Uruguay · 2026-08-08 &nbsp;·&nbsp; analysed &amp; composed 2026-08-09 &nbsp;·&nbsp;
    sophia-labs/mus — <span style="font-family:var(--mono)">aigua/aigua_states.mus</span>, rendered by
    <span style="font-family:var(--mono)">mus_audio.py</span> (SPEC-AUDIO §8, gesture quotation).
    No sound source other than the recording.
  </footer>
</main>

<div id="tip"></div>
<audio id="au" preload="auto"></audio>

<script>
const D = __DATA__;
/* A multi-megabyte data: URI in an <audio src> stalls Chrome's media loader;
   decode once to a Blob and hand the element an object URL instead. */
{
  const b64 = "__MP3__";
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  document.querySelector("#au").src =
    URL.createObjectURL(new Blob([bytes], { type: "audio/mpeg" }));
}
const C = { ice: "#189FC4", liquid: "#7D6BF2", vapor: "#BD7A3E" };
const CH = { ice: "#7FD0E3", liquid: "#A99BF7", vapor: "#D9A76C" };
const $ = (s) => document.querySelector(s);
const tip = $("#tip");
function showTip(ev, html) {
  tip.innerHTML = html; tip.style.opacity = 1;
  const pad = 14, w = tip.offsetWidth;
  let x = ev.clientX + pad; if (x + w > innerWidth - 8) x = ev.clientX - w - pad;
  tip.style.left = x + "px"; tip.style.top = (ev.clientY + pad) + "px";
}
function hideTip() { tip.style.opacity = 0; }

/* ---- stat band ---- */
$("#pct-ice").textContent = D.stats.resolvedPct + "%";
$("#pct-liquid").textContent = D.stats.octavePct + "%";
$("#pct-vapor").textContent = D.stats.disagreePct + "%";
$("#undef-n").textContent = D.stats.spanUndefined;
$("#n-comp").textContent = D.stats.nComponents;
$("#ari").textContent = D.stats.ari.toFixed(2);

/* ---- player ---- */
const au = $("#au"), bar = $("#form-bar"), head = $("#playhead"),
      playBtn = $("#play"), clock = $("#clock"), secText = $("#section-text");
const DUR = 196;
for (const s of D.sections) {
  const seg = document.createElement("div");
  seg.className = "seg"; seg.dataset.name = s.name;
  seg.style.width = (100 * (s.t1 - s.t0) / DUR) + "%";
  seg.title = s.name;
  const lbl = (s.t1 - s.t0) / DUR >= 0.08 ? s.name : "";
  seg.innerHTML = `<div class="fill" style="background:${C[s.state]}"></div><div class="label">${lbl}</div>`;
  bar.insertBefore(seg, head);
}
const segs = [...bar.querySelectorAll(".seg")];
function fmt(t) { t = Math.max(0, t|0); return (t/60|0) + ":" + String(t%60).padStart(2,"0"); }
function tick() {
  const t = au.currentTime;
  head.style.left = (100 * t / DUR) + "%";
  clock.textContent = fmt(t) + " / 3:16";
  bar.setAttribute("aria-valuenow", Math.round(t));
  const cur = D.sections.find(s => t >= s.t0 && t < s.t1);
  segs.forEach(sg => sg.classList.toggle("lit", cur && sg.dataset.name === cur.name));
  if (cur) secText.textContent = cur.name + " — " + cur.text;
}
au.addEventListener("timeupdate", tick);
au.addEventListener("ended", () => { playBtn.innerHTML = "&#9654;"; });
playBtn.addEventListener("click", () => {
  if (au.paused) { au.play(); playBtn.innerHTML = "&#10074;&#10074;"; }
  else { au.pause(); playBtn.innerHTML = "&#9654;"; }
});
function seekTo(clientX) {
  const r = bar.getBoundingClientRect();
  au.currentTime = DUR * Math.min(1, Math.max(0, (clientX - r.left) / r.width));
  tick();
}
bar.addEventListener("click", (e) => seekTo(e.clientX));
bar.addEventListener("keydown", (e) => {
  if (e.key === "ArrowRight") { au.currentTime = Math.min(DUR, au.currentTime + 5); tick(); }
  if (e.key === "ArrowLeft") { au.currentTime = Math.max(0, au.currentTime - 5); tick(); }
  if (e.key === " ") { e.preventDefault(); playBtn.click(); }
});

/* ---- svg helpers ---- */
const NS = "http://www.w3.org/2000/svg";
function el(svg, tag, attrs) {
  const n = document.createElementNS(NS, tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  svg.appendChild(n); return n;
}

/* ---- timeline ---- */
(function () {
  const svg = $("#timeline"), W = 900, H = 150, L = 34, R = 8, T = 12, B = 26;
  const x = (t) => L + (W - L - R) * t / 56.32;
  el(svg, "line", { x1: L, x2: W - R, y1: H - B, y2: H - B, class: "axis" });
  for (let s = 0; s <= 55; s += 10) {
    el(svg, "text", { x: x(s), y: H - 9, "text-anchor": "middle" }).textContent = s + "s";
    el(svg, "line", { x1: x(s), x2: x(s), y1: H - B, y2: H - B + 4, class: "axis" });
  }
  for (const e of D.timeline) {
    const hh = (H - T - B) * (e.sup >= 1 ? 1 : 0.5);
    const r = el(svg, "rect", {
      x: x(e.t0), width: Math.max(2.5, x(e.t0 + e.d) - x(e.t0)),
      y: H - B - hh, height: hh, fill: C[e.s], rx: 1.5,
    });
    r.addEventListener("mousemove", (ev) => showTip(ev,
      `${e.t0.toFixed(2)}s · ${(e.d*1000)|0} ms · <b style="color:${CH[e.s]}">${e.s}</b>` +
      `<br>v1 family: ${e.fam} · detectors: ${e.sup >= 1 ? "both" : "one"}` +
      (e.span != null ? `<br>resolved span ${e.span.toFixed(1)} st` : "<br>no defensible span")));
    r.addEventListener("mouseleave", hideTip);
  }
})();

/* ---- contour cards ---- */
(function () {
  const wrap = $("#contour-cards");
  for (const key in D.contours) {
    const c = D.contours[key];
    const card = document.createElement("div"); card.className = "card";
    card.innerHTML = `<h3>${key} <span style="color:var(--ink-3);font-weight:400">· ${c.t0.toFixed(2)}s in the recording</span></h3>
      <div class="note">${c.note}</div>`;
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 380 140");
    const rows = c.contour;
    const ts = rows.map(r => r[0]);
    const freqs = rows.flatMap(r => [r[1], r[3]]).filter(Boolean);
    const lo = Math.log2(Math.min(...freqs)) - 0.15, hi = Math.log2(Math.max(...freqs)) + 0.15;
    const X = t => 8 + 364 * (t - ts[0]) / Math.max(ts[ts.length-1] - ts[0], 1e-6);
    const Y = f => 128 - 118 * (Math.log2(f) - lo) / Math.max(hi - lo, 1e-6);
    for (const g of [500, 1000, 2000, 4000, 8000]) {
      if (Math.log2(g) > lo && Math.log2(g) < hi) {
        el(svg, "line", { x1: 8, x2: 372, y1: Y(g), y2: Y(g), class: "axis", "stroke-dasharray": "2 5" });
        el(svg, "text", { x: 372, y: Y(g) - 3, "text-anchor": "end" }).textContent = g >= 1000 ? (g/1000) + "k" : g;
      }
    }
    let path = "", pen = false;
    for (const r of rows) {
      if (r[2] === "r" && r[1]) { path += (pen ? "L" : "M") + X(r[0]).toFixed(1) + " " + Y(r[1]).toFixed(1); pen = true; }
      else pen = false;
    }
    if (path) el(svg, "path", { d: path, fill: "none", stroke: C.ice, "stroke-width": 2.2, "stroke-linecap": "round" });
    for (const r of rows) if (r[2] === "o" && r[3])
      el(svg, "circle", { cx: X(r[0]), cy: Y(r[3]), r: 2.2, fill: "none", stroke: C.liquid, "stroke-width": 1.4 });
    for (const r of rows) if (r[2] === "d")
      el(svg, "rect", { x: X(r[0]) - 0.8, y: 132, width: 1.6, height: 4, fill: C.vapor, opacity: 0.8 });
    card.appendChild(svg);
    const leg = document.createElement("div");
    leg.className = "note"; leg.style.marginTop = "4px";
    leg.innerHTML = `<span class="s-ice">— resolved</span> &nbsp; <span class="s-liquid">○ octave shadow</span> &nbsp; <span class="s-vapor">▍disagreement (below)</span>`;
    card.appendChild(leg);
    wrap.appendChild(card);
  }
})();

/* ---- span scatter ---- */
(function () {
  const svg = $("#spans"), W = 900, H = 420, L = 56, R = 16, T = 16, B = 44;
  const M = 38;
  const x = v => L + (W - L - R) * v / M, y = v => H - B - (H - T - B) * v / M;
  for (let g = 0; g <= 36; g += 6) {
    el(svg, "line", { x1: x(g), x2: x(g), y1: T, y2: H - B, class: "axis" });
    el(svg, "line", { x1: L, x2: W - R, y1: y(g), y2: y(g), class: "axis" });
    el(svg, "text", { x: x(g), y: H - B + 16, "text-anchor": "middle" }).textContent = g;
    el(svg, "text", { x: L - 8, y: y(g) + 3, "text-anchor": "end" }).textContent = g;
  }
  el(svg, "text", { x: (L + W - R) / 2, y: H - 8, "text-anchor": "middle" }).textContent = "v1 span — one estimator, unvalidated (semitones)";
  const yl = el(svg, "text", { x: 0, y: 0, "text-anchor": "middle" });
  yl.textContent = "v2 span — consensus, resolved frames only";
  yl.setAttribute("transform", `translate(14 ${(T + H - B) / 2}) rotate(-90)`);
  el(svg, "line", { x1: x(0), y1: y(0), x2: x(M), y2: y(M), stroke: "#5F7683", "stroke-width": 1, "stroke-dasharray": "5 5" });
  el(svg, "text", { x: x(31), y: y(31) - 8, "text-anchor": "middle" }).textContent = "v2 = v1";
  el(svg, "line", { x1: x(D.stats.v1Median), x2: x(D.stats.v1Median), y1: T, y2: H - B, stroke: C.vapor, "stroke-width": 1.4, "stroke-dasharray": "2 4" });
  el(svg, "text", { x: x(D.stats.v1Median) + 5, y: T + 12, fill: CH.vapor }).textContent = "v1 median " + D.stats.v1Median;
  el(svg, "line", { x1: L, x2: W - R, y1: y(D.stats.v2Median), y2: y(D.stats.v2Median), stroke: C.ice, "stroke-width": 1.4, "stroke-dasharray": "2 4" });
  el(svg, "text", { x: W - R - 4, y: y(D.stats.v2Median) - 6, "text-anchor": "end", fill: CH.ice }).textContent = "v2 median " + D.stats.v2Median;
  D.paired.forEach((p, i) => {
    const c = el(svg, "circle", { cx: x(Math.min(p[0], M)), cy: y(Math.min(p[1], M)), r: 4.5, fill: C.ice, "fill-opacity": 0.75, stroke: "#0B141B", "stroke-width": 1 });
    c.addEventListener("mousemove", (ev) => showTip(ev, `v1: ${p[0].toFixed(1)} st → v2: ${p[1].toFixed(1)} st`));
    c.addEventListener("mouseleave", hideTip);
  });
})();

/* ---- component sizes ---- */
(function () {
  const svg = $("#comps"), W = 900, H = 170, L = 8, B = 30, T = 14;
  const n = D.components.length, bw = (W - L - 8) / n - 3;
  const maxv = D.components[0];
  D.components.forEach((v, i) => {
    const h = (H - T - B) * v / maxv;
    const xx = L + i * ((W - L - 8) / n);
    const r = el(svg, "rect", { x: xx, y: H - B - h, width: bw, height: Math.max(h, 3), rx: 2,
      fill: i === 0 ? C.ice : "#2C4250" });
    r.addEventListener("mousemove", (ev) => showTip(ev,
      i === 0 ? `<b style="color:${CH.ice}">the core — ${v} events</b><br>v1's call + bright, merged` : `${v} event${v > 1 ? "s" : ""}`));
    r.addEventListener("mouseleave", hideTip);
    if (i === 0 || v > 4) el(svg, "text", { x: xx + bw / 2, y: H - B - h - 5, "text-anchor": "middle" }).textContent = v;
  });
  el(svg, "line", { x1: L, x2: W - 8, y1: H - B, y2: H - B, class: "axis" });
  el(svg, "text", { x: L, y: H - 10 }).textContent = "components, largest → smallest · ice = the call+bright core";
})();

/* ---- provenance ---- */
$("#prov").textContent = [
  "research object   aigua/research-object — content-addressed (SHA-256), write-once",
  "projection        urn:sophia:mus:research-projection:sha256:1b85349b3252fd27…  (29,394 triples)",
  "sweep receipt     urn:sophia:mus:run:sha256:c885315586e7c574…  113 events, 3 estimators, 0 failures",
  "stability receipt urn:sophia:mus:run:sha256:581948027315d8e7…  228 label runs, seed 20260809",
  "",
  "reproduce:",
  "  python aigua/import_research_object.py --config aigua/research/aigua-v1-import.json",
  "  mus-analysis segment-audio aigua/aigua_raw.wav --band-low-hz 900 --band-high-hz 11000 \\",
  "      --output aigua/v2/segmentation.json --store aigua/research-object",
  "  python aigua/analyze_all_events.py && python aigua/cluster_stability_v2.py",
  "  python aigua/make_states.py && ./mus_audio.py aigua/aigua_states.mus",
].join("\n");
</script>
"""


if __name__ == "__main__":
    main()
