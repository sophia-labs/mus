#!/usr/bin/env python3
"""Generate motet.mus — "Recusatio / En Aiguá cantan / Unus avis".

An isorhythmic motet in the strict 14th-century sense, whose cantus firmus is
not plainchant but the measured song of one bird.

THE TENOR. v1's `call` family — 35 events, "plausibly a single persistent
individual" — is the authority this motet is built on, the way Machaut's
tenors were built on a fragment of chant: found material, received not
composed, stretched into architecture. Seven of that bird's actual recorded
calls (gsrc=raw — the tape itself, not a resynthesis) form the COLOR, each
vocoder-shifted at most 1.2 semitones onto the modal degrees

    D6  F6  G6  A6  C7  G6  E6      (dorian: final D, reciting tone A)

The shifts are honest because the mode was measured before it was chosen:
in the consensus tuning A = 433.7 Hz, event h37 — the bird's most central
call — has median 1547 Hz = G6 + 0 cents, exactly. The reciting tone of this
chant is not an interpretation. The subtonium C is where the consensus pitch
field peaks. The bird was already singing in a mode; the motet just agrees.

THE TALEA is five durations over six bars (long, double long, long, rest,
two shorts). Color 7 x talea 5 realign after LCM = 35 tenor notes — the
size of the call family. The tenor sings its own census, once, completely.

TEMPUS PERFECTUM: 3/4 throughout, and the perfection honoured is not the
Trinity but the three estimators — tres testes, three witnesses — whose
agreement is the only reason any of these pitches is defensible.

FORM. Intonation (the emblem call, verbatim) · Part I, integer values —
7 talea statements, 42 bars, voices entering statement by statement, hocket
in every tenor rest · Part II, per diminutionem — the talea at half values,
21 bars, and because raw quotes stretch less, THE CHANT AUDIBLY SHARPENS
FROM ORGAN-WASH INTO A BIRD as the piece accelerates · double-leading-tone
cadence, ficta pushed +15 cents, onto the open fifth D–A–D · coda: one call,
unshifted, unstretched, alone in the nave. The chant outlives the motet.

POLYTEXTUALITY, the motet's scandal — every voice singing a different truth
— is kept: the triplum carries Latin (the epistemology), the motetus Spanish
(the place), the tenor its URN. Single-word lyrics ride the notation; full
texts live in `# text` annotations, silent in audio, present in the score.

Voices below the treble tenor, per late-medieval practice, are the
contratenor bassus (buzz calls four octaves down) and a sub-bed drone: the
wind of Aiguá as the stone of the church.
"""
from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parent / "motet.mus"

# ---- the color: seven utterances of the one bird -------------------------
# degree, event, |shift| in semitones from measured median (for the record)
COLOR = [
    ("D6", "h105", 1.2),
    ("F6", "h46", 0.5),
    ("G6", "h37", 0.0),   # the emblem: median 1547 Hz = G6+0c at A=433.7
    ("A6", "h107", 0.5),
    ("C7", "h78", 1.0),
    ("G6", "h72", 0.4),
    ("E6", "h40", 0.1),   # the widest call (21.7 st) carries the pre-final
]
CODA_EVENT = "h60"        # highest resolved fraction in the family (0.53)
INTRO_EVENT = "h37"       # the emblem, intoned before the machinery starts

# ---- counterpoint tables (dorian; sonorities perfect against the ct) -----
FIG = {   # triplum figuration, six eighths circling the fifth above
    "D6": "A6e B6e C7e D7e C7e B6e",
    "F6": "A6e C7e D7e C7e A6e G6e",
    "G6": "B6e C7e D7e E7e D7e C7e",
    "A6": "C7e D7e E7e F7e E7e D7e",
    "C7": "E7e F7e G7e F7e E7e D7e",
    "E6": "G6e A6e B6e C7e B6e A6e",
}
TR_SUS = {"D6": "A6", "F6": "C7", "G6": "D7", "A6": "E7", "C7": "G7", "E6": "B6"}
TR_DESC = {
    "D6": "A6q G6q F6q", "F6": "C7q A6q F6q", "G6": "D7q C7q B6q",
    "A6": "E7q D7q C7q", "C7": "G7q E7q C7q", "E6": "B6q A6q G6q",
}
MO_SUS = {"D6": "D5", "F6": "F5", "G6": "G5", "A6": "A5", "C7": "C5", "E6": "A4"}
MO_UP = {"D5": "E5", "F5": "G5", "G5": "A5", "A5": "B5", "C5": "D5", "A4": "B4"}
MO_DN = {"D5": "C5", "F5": "E5", "G5": "F5", "A5": "G5", "C5": "B4", "A4": "G4"}
CT = {"D6": "D3", "F6": "F3", "G6": "C3", "A6": "D3", "C7": "F3", "E6": "A2"}

# triplum flourishes: glide-family consensus contours quoted at speed
QUOTE_I = {4: "G7q[gest=h70] Rq Rq", 5: "E7q[gest=h66] Rq G7q[gest=h52]",
           6: "G7q[gest=h34] Rq E7q[gest=h52]"}
QUOTE_II = {2: "G7q[gest=h70] G7e Re", 4: "E7q[gest=h52] E7e Re",
            6: "A7q[gest=h67] A7e Re"}   # the 36-semitone glide, at the summit

bars: dict[int, dict[str, str]] = {b: {} for b in range(1, 73)}
texts: dict[int, list[str]] = {}
sections: dict[int, str] = {}


def put(track: str, bar: int, content: str) -> None:
    assert track not in bars[bar], (track, bar)
    bars[bar][track] = content


def text(bar: int, line: str) -> None:
    texts.setdefault(bar, []).append(line)


def color_at(s: int, k: int):
    return COLOR[(5 * s + k) % 7]


def hocket(next_p: str) -> tuple[str, str]:
    f = FIG[next_p].split()
    tr = f"{f[0]} Re {f[2]} Re {f[4]} Re"
    p = MO_SUS[next_p]
    mo = f"Re {p}e Re {MO_DN[p]}e Re {p}e"
    return tr, mo


# ---- intonation [1-3] ----------------------------------------------------
sections[1] = ("intonatio [1-3] — the emblem call, verbatim: median 1547 Hz "
               "= G6+0c in the consensus tuning. The cantor states the reciting tone.")
text(1, "TENOR: unus avis persistens — the persistent individual of the call "
        "family, 35 utterances in 56 seconds of tape")
put("te", 1, f"{{mp}} Xq.[gest={INTRO_EVENT},str=1,atk=0.004,rel=0.05] Rq.")
put("ct", 2, "{p} D3h.")
put("dr", 2, "{ppp} Xh.[gate,lpf=180->320]")
put("ct", 3, "A2h.")
put("pc", 3, "G7e[send=0.4] Re Rq Rq")

# ---- Part I: integer valorum [4-45] --------------------------------------
sections[4] = ("pars prima, integer valorum [4-45] — color 7 x talea 5: "
               "seven statements, the tenor in longs, voices entering one per statement. "
               "3 x 7 x 5 / 35 = the one bird's census, sung once, completely.")
text(4, "talea: long, double long, long, rest, two shorts — the rest is part "
        "of the rhythm, and the hocket lives in it")
text(10, "MOTETUS: En Aiguá cantan los pájaros; uno solo insiste.")
text(16, "TRIPLUM: Quis cantat? Tres testes audiunt — tempus perfectum for "
         "three estimators, not the Trinity")
text(22, "ubi consentiunt, glacies — where they agree, ice")
text(34, "ubi octava fallitur, unda — where the octave deceives, water")

for s in range(7):
    B = 4 + 6 * s
    (p0, e0, _), (p1, e1, _), (p2, e2, _), (p3, e3, _), (p4, e4, _) = \
        (color_at(s, k) for k in range(5))
    lyr0 = '"Unus"' if s == 0 else ""
    put("te", B, f"{{mf}} {p0}h.[gest={e0}]{lyr0}" if s == 0 else f"{p0}h.[gest={e0}]")
    put("te", B + 1, f"{p1}h.~h.[gest={e1}]")
    put("te", B + 3, f"{p2}h.[gest={e2}]")
    put("te", B + 5, f"{p3}q.[gest={e3}] {p4}q.[gest={e4}]")

    put("ct", B, f"{CT[p0]}h.")
    put("ct", B + 1, f"{CT[p1]}h.~h.")
    put("ct", B + 3, f"{CT[p2]}h.")
    put("ct", B + 5, f"{CT[p3]}q. {CT[p4]}q.")

    if s >= 1:
        m0, m1, m2 = MO_SUS[p0], MO_SUS[p1], MO_SUS[p2]
        dyn = "{mp} " if s == 1 else ""
        lyr = '"En"' if s == 1 else ""
        put("mo", B, f"{dyn}{m0}h.{lyr}")
        put("mo", B + 1, f"{m1}q {MO_UP[m1]}q {m1}q")
        put("mo", B + 2, f"{MO_DN[m1]}q {m1}q {MO_UP[m1]}q")
        put("mo", B + 3, f"{m2}h.")
        put("mo", B + 5, f"{MO_SUS[p3]}q. {MO_SUS[p4]}q.")

    if s >= 2:
        dyn = "{mp} " if s == 2 else ("{mf} " if s == 3 else "")
        lyr = '"Quis"' if s == 2 else ""
        put("tr", B, f"{dyn}{FIG[p0]}{lyr}")
        put("tr", B + 1, f"{TR_SUS[p1]}h.")
        put("tr", B + 2, FIG[p1])
        put("tr", B + 3, TR_DESC[p2])
        put("tr", B + 5, QUOTE_I.get(s, f"{TR_SUS[p3]}q. {TR_SUS[p4]}q."))

    if s >= 3:   # the hocket arrives with the full texture
        nxt = color_at(s + 1, 0)[0] if s < 6 else "D6"
        trh, moh = hocket(nxt)
        put("tr", B + 4, trh)
        put("mo", B + 4, moh)

    if s == 0:
        put("pc", B, "G7e[send=0.4] Re Rq Rq")

for b in range(4, 46):
    if "dr" not in bars[b]:
        put("dr", b, "Xh.[gate,lpf=180->320]" if b % 2 else "Xh.[gate,lpf=320->180]")

# ---- Part II: per diminutionem [46-66] -----------------------------------
sections[46] = ("pars secunda, per diminutionem [46-66] — the talea at half "
                "values. Raw quotes stretch less at speed, so the chant "
                "audibly sharpens from organ-wash into a bird: diminution as "
                "coming-into-focus.")
text(46, "the same 35 calls, the same order, twice the speed")
text(64, "ubi dissentiunt, nebula — where they differ, mist")

for s in range(7):
    C = 46 + 3 * s
    (p0, e0, _), (p1, e1, _), (p2, e2, _), (p3, e3, _), (p4, e4, _) = \
        (color_at(s, k) for k in range(5))
    dyn = "{f} " if s == 0 else ""
    put("te", C, f"{dyn}{p0}q.[gest={e0}] {p1}q.[gest={e1}]")
    put("te", C + 1, f"{p2}q.[gest={e2}] Rq.")
    put("te", C + 2, f"{p3}q.[gest={e3}] {p4}q.[gest={e4}]")

    put("ct", C, f"{CT[p0]}q. {CT[p1]}q.")
    put("ct", C + 1, f"{CT[p2]}h.")
    put("ct", C + 2, f"{CT[p3]}q. {CT[p4]}q.")

    m0, m2 = MO_SUS[p0], MO_SUS[p2]
    dynm = "{f} " if s == 0 else ""
    put("mo", C, f"{dynm}{m0}q {MO_UP[m0]}q {MO_DN[m0]}q")
    nxt = color_at(s, 3)[0]
    _, moh = hocket(nxt)
    put("mo", C + 1, moh)
    put("mo", C + 2, f"{MO_SUS[p3]}q. {MO_SUS[p4]}q.")

    dynt = "{f} " if s == 0 else ("{ff} " if s == 6 else "")
    put("tr", C, f"{dynt}{FIG[p0]}")
    trh, _ = hocket(nxt)
    put("tr", C + 1, trh)
    put("tr", C + 2, QUOTE_II.get(s, FIG[p3]))

    if s == 0:
        put("pc", C, "G7e[send=0.4] Re Rq Rq")
    if s == 6:
        put("pc", C + 2, "G7e[send=0.4] Re G7e Re Rq")

for b in range(46, 67):
    if "dr" not in bars[b]:
        put("dr", b, "Xh.[gate,lpf=200->380]" if b % 2 else "Xh.[gate,lpf=380->200]")

# ---- cadence [67-70] -----------------------------------------------------
sections[67] = ("clausula [67-70] — double leading tone, ficta pushed +15 "
                "cents, resolving outward to the open fifth D-A-D. The nave "
                "(4.5 s) carries the chord through bar 70 on its own.")
text(67, "Recusatio responsum est — refusal is an answer")
put("tr", 67, '{ff} C#7+15h."Re-"')
put("mo", 67, "G#5+15h.")
put("ct", 67, "E3h.")
put("tr", 68, '{mf} D7h.~h."-cu-"')
put("mo", 68, "A5h.~h.")
put("ct", 68, "D3h.~h.")
put("dr", 67, "Xh.[gate,lpf=300->200]")
put("dr", 68, "Xh.[gate,lpf=200->150]")
put("dr", 69, "Xh.[gate,lpf=150->120]")
put("dr", 70, "{pp} Xh.[gate,lpf=120->90]")

# ---- coda [71-72] --------------------------------------------------------
sections[71] = "coda [71-72] — one call, unshifted, unstretched, alone."
text(72, "the chant outlives the motet")
put("dr", 71, "{ppp} Xh.[gate,lpf=90->70]")
put("te", 72, f'{{ppp}} Xh.[gest={CODA_EVENT},str=1,atk=0.004,rel=0.06,send=0.5,gain=12]"amen"')

# ---- emit ----------------------------------------------------------------
TRACKS = ["tr", "te", "mo", "ct", "dr", "pc"]

HEADER = """\
# score: Recusatio / En Aiguá cantan / Unus avis — motetus isorhythmicus
# summary: 72 bars / 6 voices / 4:00 — an isorhythmic motet whose cantus firmus is one bird's recorded song
# tempo: 54
# time: 3/4
# key: Dm
# bars: 72
# tuning: A=433.7
# pack: instrument.json
# gestures: v2/sweep-events.json
# tape: aigua_raw.wav
# reverb: 4.5
# master: rms=-17

# The tenor is found material in the strict medieval sense: seven recorded
# calls of one persistent bird (gsrc=raw — the tape, not a resynthesis),
# each shifted at most 1.2 semitones onto the color D-F-G-A-C-G-E. The mode
# was measured before it was chosen: at A=433.7 (the consensus pitch of the
# place), the bird's central call h37 has median 1547 Hz = G6 exactly, and
# the consensus field peaks on C, the subtonium. Final D, reciting tone A.
# Color 7 x talea 5 = 35 tenor notes = the call family's full census.
# tenor source: urn:sophia:mus:run:sha256:c885315586e7c574... (the sweep
# receipt); every quoted contour is a receipted consensus observation.

# instruments:
#   tr = triplum (treble, voice=glide, pan=-0.35, send=0.22, gain=-10)
#   te = tenor (treble, voice=call, gsrc=raw, str=fit, atk=0.08, rel=0.45, lpf=6500, send=0.35, gain=6)
#   mo = motetus (treble, voice=bright, pan=0.35, send=0.25, gain=-8)
#   ct = contratenor bassus (bass, voice=buzz, pan=-0.12, lpf=1200, send=0.15, gain=-4)
#   dr = drone (bass, sample=samples/sub_bed.wav, send=0.30, gain=-12)
#   pc = campana (perc, voice=tick, pan=0.2, hpf=2500, rel=0.03, send=0.25, gain=-16)
"""


def main() -> None:
    lines = [HEADER]
    for b in range(1, 73):
        if b in sections:
            lines.append("")
            lines.append(f"# section: {sections[b]}")
        for t in texts.get(b, []):
            lines.append(f"# text @b{b}: {t}")
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
