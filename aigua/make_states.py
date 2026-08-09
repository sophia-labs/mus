#!/usr/bin/env python3
"""Generate aigua_states.mus — "Aiguá: Three States of Water".

The first score composed from the v2 analysis rather than the v1 instrument
alone. Every pitched figure is a *gesture quotation* (SPEC-AUDIO §8): the
renderer follows the consensus pitch contour the three-estimator ensemble
actually resolved, so the birds' measured gestures — not approximations of
them — are the melodic material.

The form is the epistemology of the analysis, sounded:

  vapor        frames where the estimators disagreed (45% of the recording).
               No pitch is defensible, so no pitch is played: the raw tape
               itself, pointed into at the disagreement events' timestamps.
  liquid       octave-conflict frames (30%): the ensemble heard the call in
               two octaves at once. Each figure is one event quoted twice —
               its resolved backbone and its octave shadow (glayer=octave) —
               panned apart. The shimmer is not an effect; it is the data.
  ice          resolved frames (25%): consensus quotes, harmonised in open
               fifths. The aria is h67 — 36.1 semitones in 0.19 s, the widest
               defensible gesture in the corpus.
  correction   v1's span claim (median 18.7 st) played as the straight line
               it was, answered by what the ensemble measured (h57, then h60
               ≈ the revised median of 7.0 st). Then two bars of notated
               silence for the 31 events that refused a pitch. Refusal is a
               result.

Tuning: the consensus pitch field over resolved frames peaks 275 cents above
A440 folded to one octave — C, 25 cents flat. A = 433.7 puts that peak
exactly on C. (v1 heard the place at A = 445.6 through unvalidated SHS; the
piece is tuned to the revised place.)

Event indices (h<N>) refer to v2/sweep-events.json in file order.
"""
from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parent / "aigua_states.mus"

# ms offsets into aigua_raw.wav for pure-disagreement (vapor) events and the
# car pass, straight from the sweep records.
VAPOR = {"h1": 350, "h19": 11470, "h41": 19190, "h81": 39500, "h89": 42640, "h110": 55960}
CAR_MS = 9050

TRACKS = ["gl", "ca", "br", "md", "tk", "bz", "sb", "tp"]

bars: dict[int, dict[str, str]] = {b: {} for b in range(1, 49)}


def put(track: str, bar: int, content: str) -> None:
    bars[bar][track] = content


# ---- vapor [1-12] ----------------------------------------------------------
put("tp", 1, f"{{pp}} Xw[off={VAPOR['h81']},gate,lpf=2400,pan=-0.5]")
put("tp", 3, f"Xh[off={VAPOR['h19']},gate,lpf=1800,pan=0.4] Rh")
put("tp", 5, f"Xw[off={VAPOR['h89']},gate,lpf=2800,pan=-0.2->0.3]")
put("tp", 7, f"Xh[off={VAPOR['h110']},gate,lpf=2000,pan=0.6] Rh")
put("tp", 8, f"Xh[off={VAPOR['h1']},gate,lpf=1500,pan=-0.6] Rh")
put("tp", 10, f"Xw[off={VAPOR['h41']},gate,lpf=3200,pan=0.1->-0.4]")

put("sb", 1, "{ppp} Xw[gate,lpf=180->320]")
put("sb", 2, "Xw[gate,lpf=320->180]")
put("sb", 3, "Xw[gate,lpf=200->400]")
put("sb", 4, "Xw[gate,lpf=400->160]")
for b in range(5, 9):
    put("sb", b, ("{pp} " if b == 5 else "") + "Xw[gate,lpf=250->500]")
for b in range(9, 13):
    put("sb", b, "Xw[gate,lpf=500->200]")

for b in range(5, 9):
    put("bz", b, ("{pp} " if b == 5 else "") + "C2w[atk=0.8,rel=1.2]")
put("bz", 9, "C2w[atk=0.8,rel=1.2]")
put("bz", 10, "C2w[atk=0.8,rel=1.2]")
put("bz", 11, "G1w[atk=0.9,rel=1.4]")
put("bz", 12, "G1w[atk=0.9,rel=1.4]")

put("tk", 9, "{pp} Re Xe[st=14] Rh Rq")
put("tk", 11, "Rq Xe[st=17] Re Rh")
put("tk", 12, "Rh Xe[st=12] Re Rq")

# ---- liquid [13-24] --------------------------------------------------------
put("ca", 13, "{mp} C5q[gest=h71,pan=-0.35] Rq Rh")
put("ca", 15, "G4h[gest=h96,pan=-0.3] Rh")
put("ca", 17, "C5q[gest=h71,pan=-0.35] Rq G4q[gest=h96,pan=-0.25] Rq")
put("ca", 19, "{mf} C5q[gest=h71,pan=-0.4] Rq Rh")
put("ca", 21, "G4h[gest=h96,pan=-0.3] Rh")
put("ca", 23, "C5q[gest=h71,pan=-0.35] Rq G4q[gest=h96,pan=-0.3] Rq")

put("br", 13, "{mp} C5q[gest=h71,glayer=octave,pan=0.35] Rq Rh")
put("br", 15, "Rq C5q[gest=h71,glayer=octave,pan=0.45] Rh")
put("br", 17, "C5q[gest=h71,glayer=octave,pan=0.4] Rq Rh")
put("br", 19, "{mf} C5q[gest=h71,glayer=octave,pan=0.45] Rq Rh")
put("br", 21, "Rq C5q[gest=h71,glayer=octave,pan=0.5] Rh")
put("br", 23, "C5q[gest=h71,glayer=octave,pan=0.4] Rq Rh")

put("md", 15, "{p} Rq D5q[gest=h91,glayer=octave,pan=0.2] Rh")
put("md", 18, "Rh G5q[gest=h101,glayer=octave,pan=-0.2] Rq")
put("md", 20, "Rq D5q[gest=h91,glayer=octave,pan=0.25] Rh")
put("md", 22, "Rh G5q[gest=h101,glayer=octave,pan=-0.25] Rq")

for b in range(13, 21):
    put("bz", b, ("{pp} " if b == 13 else "") + "C2h[atk=0.3,rel=0.8] Rh")
put("bz", 21, "C2h[atk=0.3,rel=0.8] Rh")
put("bz", 22, "C2h[atk=0.3,rel=0.8] Rh")
put("bz", 23, "G1h[atk=0.3,rel=0.9] Rh")
put("bz", 24, "G1h[atk=0.3,rel=0.9] Rh")

for b in range(13, 25):
    put("sb", b, ("{ppp} " if b == 13 else "") + "Xw[gate,lpf=220->380]")

# ---- ice [25-38] -----------------------------------------------------------
for b in (25, 26):
    put("ca", b, ("{mf} " if b == 25 else "") + "G4w[gest=h54,str=fit,pan=-0.2]")
for b in (27, 28):
    put("ca", b, "G4w[gest=h60,str=fit,pan=-0.2]")
for b in (29, 30):
    put("ca", b, "C5w[gest=h54,str=fit,pan=-0.15]")
for b in (31, 32):
    put("ca", b, "G4w[gest=h60,str=fit,pan=-0.2]")
for b in (36, 37, 38):
    put("ca", b, ("{mp} " if b == 36 else "") + "G4w[gest=h54,str=fit,pan=-0.2]")

for b in (25, 26):
    put("br", b, ("{mf} " if b == 25 else "") + "C5w[gest=h44,str=fit,pan=0.2]")
for b in (27, 28):
    put("br", b, "D5w[gest=h44,str=fit,pan=0.25]")
for b in (29, 30):
    put("br", b, "G5w[gest=h44,str=fit,pan=0.2]")
for b in (31, 32):
    put("br", b, "C5w[gest=h44,str=fit,pan=0.25]")
for b in (36, 37, 38):
    put("br", b, ("{mp} " if b == 36 else "") + "C5w[gest=h44,str=fit,pan=0.2]")

for b in range(25, 29):
    put("gl", b, ("{mf} " if b == 25 else "") + "C6h[gest=h70,str=fit] Rh")
put("gl", 29, "G6h[gest=h70,str=fit] Rh")
put("gl", 30, "G6h[gest=h70,str=fit] Rh")
put("gl", 31, "C6h[gest=h70,str=fit] Rh")
put("gl", 32, "C6h[gest=h70,str=fit] Rh")
put("gl", 33, "{fff} C6q[gest=h67] Rq Rh")
put("gl", 34, "Rq E6q[gest=h52] Rh")
put("gl", 35, "{ff} G6q[gest=h34] Rq C6q[gest=h67] Rq")
for b in (36, 37, 38):
    put("gl", b, ("{mp} " if b == 36 else "") + "C6h[gest=h70,str=fit] Rh")

put("tk", 33, "{ff} Rh C5q[gest=h68] Rq")
put("tk", 34, "Rh Rq C5q[gest=h68]")

for b in range(25, 33):
    put("bz", b, ("{p} " if b == 25 else "") + "C2w[atk=0.5,rel=1.0]")
for b in (33, 34, 35):
    put("bz", b, ("{mf} " if b == 33 else "") + "C2h[atk=0.1,rel=0.6] G1h[atk=0.1,rel=0.6]")
for b in (36, 37, 38):
    put("bz", b, ("{p} " if b == 36 else "") + "C2w[atk=0.5,rel=1.0]")

# ---- correction [39-46] ----------------------------------------------------
put("gl", 39, "{mf} C5h->F#6+67 Rh")
put("ca", 41, "{mp} C5h[gest=h57] Rh")
put("gl", 43, "G5h[gest=h60] Rh")
put("ca", 43, "Rh C5q[gest=h50] Rq")
for b in range(39, 45):
    put("bz", b, ("{pp} " if b == 39 else "") + "C2w[atk=0.6,rel=1.2]")
    put("sb", b, ("{ppp} " if b == 39 else "") + "Xw[gate,lpf=200->300]")
put("gl", 45, "Rw[fer]")
put("gl", 46, "Rw[fer]")
put("ca", 45, "Rw[fer]")
put("ca", 46, "Rw[fer]")

# ---- release [47-48] -------------------------------------------------------
put("tp", 47, f"{{pp}} Xw[off={CAR_MS},gate,lpf=4000,pan=-1->1]")
put("tp", 48, "Xw[off=0,gate,lpf=1200,gain=-6]")
put("sb", 47, "{ppp} Xw[gate,lpf=300->120]")
put("sb", 48, "Xw[gate,lpf=120->60]")

SECTIONS = {
    1: ("vapor [1-12]", "45% of all frames: no defensible pitch, so the tape itself, "
        "pointed into at the pure-disagreement events."),
    13: ("liquid [13-24]", "octave-conflict: one event, two hearings. Resolved backbone "
         "left, octave shadow right. h91/h101 resolved nothing and exist only as shadows."),
    25: ("ice [25-38]", "resolved frames only. Chorale = the stable call/bright core "
         "(h54, h60, h44) frozen with str=fit; soprano = h70, the cleanest event (74% "
         "resolved). Bar 33: h67, 36.1 semitones in 0.19 s — the aria."),
    39: ("correction [39-46]", "v1's median-span claim (18.7 st) as the straight line it "
         "was; the ensemble answers with h57, then h60 — the shape of the revised median "
         "(7.0 st). Bars 45-46: silence for the 31 events that refused a pitch."),
    47: ("release [47-48]", "the one non-bird protagonist passes once, unclustered, and "
         "the place is itself again."),
}

TEXTS = {
    1: "nothing in this section has a pitch. that is a finding, not a failure.",
    13: "the ensemble heard every one of these calls in two octaves at once.",
    25: "only what all three estimators agreed on. a quarter of the recording.",
    33: "three octaves in a fifth of a second. the widest gesture that survived.",
    39: "first the claim, then the evidence.",
    45: "thirty-one events refused a pitch. this is their notation.",
}

HEADER = """\
# score: Aiguá: Three States of Water
# summary: 48 bars / 8 voices / 3:12 — the v2 analysis of the Aigua field recording, sounded
# tempo: 60
# time: 4/4
# key: C
# bars: 48
# tuning: A=433.7
# pack: instrument.json
# gestures: v2/sweep-events.json
# master: rms=-16

# Every gest=hN figure quotes the consensus pitch contour of reconciled event
# N in v2/sweep-events.json (SPEC-AUDIO §8). The three sections are the three
# consensus states: disagreement (45% of frames) -> vapor, octave-conflict
# (30%) -> liquid, resolved (25%) -> ice. Tuned to A=433.7: the consensus
# pitch field peaks at C-25c re A440, and this tuning puts that peak on C.

# instruments:
#   gl = glide ice (treble, voice=glide, send=0.30)
#   ca = call choir (treble, voice=call, send=0.24)
#   br = bright shadow (treble, voice=bright, send=0.26)
#   md = mid liquid (treble, voice=mid, send=0.22)
#   tk = tick (perc, voice=tick, send=0.10)
#   bz = buzz bass (bass, voice=buzz, gain=3, send=0.08)
#   sb = sub bed (bass, sample=samples/sub_bed.wav, gain=-4, send=0.20)
#   tp = tape (perc, sample=aigua_raw.wav, gain=-2, send=0.35)
"""


def main() -> None:
    lines = [HEADER]
    for b in range(1, 49):
        if b in SECTIONS:
            name, blurb = SECTIONS[b]
            lines.append("")
            lines.append(f"# section: {name} — {blurb}")
        if b in TEXTS:
            lines.append(f"# text @b{b}: {TEXTS[b]}")
        content = bars[b]
        if not content:
            lines.append(f"bar {b}: tacet")
        else:
            joined = "  ".join(f"{t}={content[t]}" for t in TRACKS if t in content)
            lines.append(f"bar {b}: {joined}")
    OUT.write_text("\n".join(lines) + "\n", "utf-8")
    print(f"wrote {OUT} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
