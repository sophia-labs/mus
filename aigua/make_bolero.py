"""Generate bolero.mus — Ravel's Boléro realised entirely in Aigua birdsong.

FIDELITY. Exact where it can be: 340 bars, 3/4, C major, Ravel's own tempo of
crotchet = 66 (he crossed out the printed 76), which gives 15:27 — next to his
own 1930 recording at 15:50. The snare ostinato is the real one: a two-bar
figure of 10 strokes then 14, twenty-four in all, unchanged from the first bar
to the last, 169 times over. Two 18-bar themes alternating, seventeen
statements, one continuous crescendo, the late swerve to E major for eight
bars, and a six-bar coda where percussion enters for the first time and the
trombones fall apart in glissandi.

RECONSTRUCTED, and this is the honest part: no transcription of the melodies
was reachable from any source available here, and music21's corpus has no
Boléro. The two themes below are therefore built to match the documented
description rather than copied from the score — theme A diatonic, opening on
C, descending through the octave and bouncing back up at its midpoint on G;
theme B beginning on flat-7 (B-flat), descending mostly by semitone, spanning
two octaves and a minor second down to a low C. The shape is right. The notes
are not Ravel's.

AVANT-GARDE. Every sound is a bird from a 56-second field recording made in
Aigua, Uruguay, plus one passing car, which is the tam-tam. Ravel's method was
to hold a melody rigid and let orchestration alone carry the argument; here the
seventeen "orchestrations" are combinations of bird voices, each written in the
register where its sample sits so the transposition stays natural — which is
also what Ravel did with his instruments.
"""

NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def nn(semitones_from_c5):
    """Semitone offset from C5 -> MUS note name."""
    midi = 72 + semitones_from_c5          # C5 = MIDI 72
    return f"{NAMES[midi % 12]}{midi // 12 - 1}"


def dur(q):
    """Quarters -> MUS duration code (only the values the themes use)."""
    return {3.0: "h.", 2.0: "h", 1.5: "q.", 1.0: "q", 0.5: "e", 0.25: "s"}[q]


# --- the two themes, as (semitones from C5, duration in quarters) -------------
# 18 bars each, 3 quarters per bar = 54 quarters.

THEME_A = [
    (0, 1.5), (0, .5), (-1, .5), (0, .5),          # 1
    (2, 1), (0, .5), (-1, .5), (-3, 1),            # 2
    (0, 2), (-3, 1),                               # 3
    (-5, 3),                                       # 4
    (-5, 1), (-3, .5), (-1, .5), (0, 1),           # 5
    (2, 1), (4, .5), (2, .5), (0, 1),              # 6
    (-1, 2), (0, 1),                               # 7
    (-3, 3),                                       # 8
    (0, 1), (-1, .5), (-3, .5), (-5, 1),           # 9   midpoint bounce on G
    (-3, 1), (-5, .5), (-7, .5), (-8, 1),          # 10
    (-5, 2), (-3, 1),                              # 11
    (-5, 3),                                       # 12
    (4, 1), (2, .5), (0, .5), (-1, 1),             # 13
    (-3, 1), (-5, .5), (-7, .5), (-8, 1),          # 14
    (-10, 1), (-8, .5), (-7, .5), (-5, 1),         # 15
    (-8, 2), (-10, 1),                             # 16
    (-12, 2), (-10, 1),                            # 17
    (-12, 3),                                      # 18  octave descent complete
]

THEME_B = [
    (-2, 1.5), (-2, .5), (-4, .5), (-5, .5),       # 1   opens on flat-7
    (-6, 1), (-7, .5), (-8, .5), (-9, 1),          # 2
    (-10, 2), (-11, 1),                            # 3
    (-12, 3),                                      # 4
    (1, 1), (0, .5), (-1, .5), (-2, 1),            # 5   up to high D-flat
    (-3, 1), (-4, .5), (-5, .5), (-6, 1),          # 6
    (-7, 2), (-8, 1),                              # 7
    (-9, 3),                                       # 8
    (-2, 1), (-3, .5), (-4, .5), (-5, 1),          # 9
    (-6, 1), (-7, .5), (-8, .5), (-9, 1),          # 10
    (-10, 2), (-12, 1),                            # 11
    (-13, 3),                                      # 12
    (-14, 1), (-15, .5), (-16, .5), (-17, 1),      # 13
    (-18, 1), (-19, .5), (-20, .5), (-21, 1),      # 14
    (-22, 2), (-23, 1),                            # 15
    (-24, 2), (-22, 1),                            # 16
    (-24, 2), (-24, 1),                            # 17
    (-24, 3),                                      # 18  low C
]
for nm, th in (("A", THEME_A), ("B", THEME_B)):
    assert abs(sum(d for _, d in th) - 54) < 1e-9, (nm, sum(d for _, d in th))


def theme_bars(theme, transpose=0):
    """Split a theme into 18 bars of 3 quarters, as lists of (name, code)."""
    bars, cur, acc = [], [], 0.0
    for off, d in theme:
        cur.append((nn(off + transpose), dur(d)))
        acc += d
        if abs(acc - 3.0) < 1e-9:
            bars.append(cur); cur, acc = [], 0.0
    assert len(bars) == 18 and not cur
    return bars


# --- the snare ostinato: 10 strokes, then 14. unchanged for 340 bars ----------
OSTINATO_ODD = "Xe Xs3 Xs3 Xs3 Xe Xs3 Xs3 Xs3 Xe Xe"
OSTINATO_EVEN = "Xe Xs3 Xs3 Xs3 Xe Xs3 Xs3 Xs3 Xs3 Xs3 Xs3 Xs3 Xs3 Xs3"

# --- the seventeen orchestrations --------------------------------------------
# (theme, [(voice, register offset in semitones)]). Register is chosen so each
# sample plays near its own recorded pitch, exactly as Ravel picked instruments.
ORCH = [
    ("A", [("m1", 24)]),                                        # 1  "flute"
    ("A", [("m2", 12)]),                                        # 2  "clarinet"
    ("B", [("m4", 12)]),                                        # 3  "bassoon"
    ("B", [("m3", 12)]),                                        # 4  "E-flat clarinet"
    ("A", [("m1", 24), ("m2", 12)]),                            # 5  "oboe d'amore"
    ("A", [("m3", 12), ("m1", 24)]),                            # 6  "trumpet + flute"
    ("B", [("m4", 12), ("m2", 12)]),                            # 7  "tenor sax"
    ("B", [("m2", 12), ("m3", 24)]),                            # 8  "soprano sax"
    ("A", [("m1", 24), ("m2", 12), ("m3", 19)]),                # 9  the organ chord
    ("A", [("m2", 12), ("m3", 12), ("m4", 12)]),                # 10 double reeds
    ("B", [("m5", 0), ("m4", 12)]),                             # 11 "trombone"
    ("B", [("m3", 12), ("m4", 12), ("m1", 24)]),                # 12 woodwinds
    ("A", [("m1", 24), ("m2", 12), ("m3", 12), ("m4", 12)]),    # 13
    ("A", [("m1", 24), ("m2", 12), ("m3", 19), ("m5", 0)]),     # 14
    ("B", [("m1", 24), ("m2", 12), ("m3", 12), ("m4", 12)]),    # 15
    ("B", [("m2", 12), ("m3", 12), ("m4", 12), ("m5", 0)]),     # 16
    ("A", [("m1", 24), ("m2", 12), ("m3", 19), ("m4", 12), ("m5", 0)]),  # 17
]

TOTAL_BARS = 340
INTRO = 4                     # snare and pizzicato alone
FIRST = INTRO + 1             # theme enters at bar 5
E_MAJOR_AT = 327              # the swerve, 8 bars
CODA_AT = 335                 # percussion enters for the first time


def cres_db(bar, lo=-30.0, hi=0.0, start=1, end=326):
    """One unbroken crescendo. Boléro's only dynamic event."""
    t = min(max((bar - start) / (end - start), 0.0), 1.0)
    return lo + (hi - lo) * t


out = []
w = out.append

w("# score: Boléro (Ravel) — for birds recorded in Aigua")
w("# summary: 340 bars / 9 voices / 15:27")
w("# tempo: 66")
w("# time: 3/4")
w("# key: C")
w("# bars: 340")
w("# pack: instrument.json")
w("# master: rms=-18")
w("")
w("# text @b1: 340 bars, 3/4, crotchet=66 — Ravel's own marking, over the printed")
w("# text @b1: 76. That gives 15:27, beside his 1930 recording at 15:50.")
w("# text @b1: The snare figure is exact: ten strokes then fourteen, twenty-four")
w("# text @b1: over two bars, unchanged 169 times from here to the end.")
w("# text @b2: The two themes are RECONSTRUCTED, not transcribed — no score was")
w("# text @b2: reachable. Theme A is diatonic, opens on C, falls through the octave")
w("# text @b2: and bounces at its midpoint on G. Theme B opens on flat-7, descends")
w("# text @b2: by semitone, spans two octaves and a minor second. The shape is")
w("# text @b2: Ravel's; the notes are not.")
w("# text @b3: Every sound is a bird from 56 seconds of tape. The tam-tam is a car.")
w("")
w("# instruments:")
w("#   sn = snare (perc, voice=tick, hpf=1800, rel=0.02, send=0.16, gain=-6)")
w("#   ba = pizzicato bass (bass, voice=buzz, lpf=900, rel=0.05, send=0.10, gain=-7)")
w("#   m1 = melody I (treble, voice=glide, send=0.26, gain=-4)")
w("#   m2 = melody II (treble, voice=call, send=0.24, gain=-4)")
w("#   m3 = melody III (treble, voice=bright, send=0.24, gain=-6)")
w("#   m4 = melody IV (treble, voice=mid, send=0.24, gain=-6)")
w("#   m5 = melody V (bass, voice=buzz, send=0.22, gain=-8)")
w("#   tam = tam-tam (perc, voice=car, send=0.40, gain=-2)")
w("#   gl = collapse (treble, voice=glide, s=3, str=fit, send=0.44, gain=-6)")
w("")

# Which statement, if any, owns each bar.
stmt_at = {}
for i, (theme, voices) in enumerate(ORCH):
    start = FIRST + 18 * i
    stmt_at[start] = (i, theme, voices)

lines_for_bar = {}
for i, (theme, voices) in enumerate(ORCH):
    start = FIRST + 18 * i
    for vname, reg in voices:
        bars = theme_bars(THEME_A if theme == "A" else THEME_B, reg)
        for k, bar in enumerate(bars):
            b = start + k
            toks = " ".join(f"{n}{c}[gate]" for n, c in bar)
            lines_for_bar.setdefault(b, {})[vname] = toks

# The climax after the seventeen statements: theme B fragments, all voices.
climax_bars = theme_bars(THEME_B, 12)
for k in range(16):
    b = 311 + k
    bar = climax_bars[k % 18]
    toks = " ".join(f"{n}{c}[gate]" for n, c in bar)
    for vname, reg in (("m1", 12), ("m2", 0), ("m3", 0), ("m4", 0), ("m5", -12)):
        shifted = theme_bars(THEME_B, 12 + reg)[k % 18]
        lines_for_bar.setdefault(b, {})[vname] = " ".join(
            f"{n}{c}[gate]" for n, c in shifted)

# E major: the same material, everything up four semitones.
e_bars = theme_bars(THEME_A, 12 + 4)
for k in range(8):
    b = E_MAJOR_AT + k
    for vname, reg in (("m1", 12), ("m2", 0), ("m3", 7), ("m4", 0), ("m5", -12)):
        shifted = theme_bars(THEME_A, 12 + 4 + reg)[k % 18]
        lines_for_bar.setdefault(b, {})[vname] = " ".join(
            f"{n}{c}[gate]" for n, c in shifted)

section_at = {
    1: "introduction [1-4]",
    FIRST: "statement 1 — theme A [5-22]",
    311: "climax [311-326]",
    E_MAJOR_AT: "E major [327-334]",
    CODA_AT: "coda — percussion enters for the first time [335-340]",
}
for i in range(1, len(ORCH)):
    section_at[FIRST + 18 * i] = (
        f"statement {i+1} — theme {ORCH[i][0]} [{FIRST+18*i}-{FIRST+18*i+17}]")

for bar in range(1, TOTAL_BARS + 1):
    if bar in section_at:
        w("")
        w(f"# section: {section_at[bar]}")
    parts = []

    # the ostinato — every bar, no exceptions
    sn_gain = cres_db(bar, -36.0, -7.0)
    pat = OSTINATO_ODD if bar % 2 == 1 else OSTINATO_EVEN
    parts.append("sn=" + " ".join(f"{t}[gate,gain={sn_gain:.1f}]"
                                  for t in pat.split()))

    # pizzicato bass, from bar 1
    ba_gain = cres_db(bar, -34.0, -11.0)
    root = "C3" if bar < E_MAJOR_AT or bar >= CODA_AT else "E3"
    fifth = "G2" if bar < E_MAJOR_AT or bar >= CODA_AT else "B2"
    if bar % 2 == 1:
        parts.append(f"ba={root}q[stac,gain={ba_gain:.1f}] Rq Rq")
    else:
        parts.append(f"ba={root}q[stac,gain={ba_gain:.1f}] Rq {fifth}q[stac,gain={ba_gain:.1f}]")

    mel_gain = cres_db(bar, -13.0, 2.0)
    for vname, toks in sorted(lines_for_bar.get(bar, {}).items()):
        if bar >= CODA_AT:
            continue
        parts.append(f"{vname}=" + toks.replace("[gate]", f"[gate,gain={mel_gain:.1f}]"))

    if bar >= CODA_AT:
        k = bar - CODA_AT
        if k == 0:
            parts.append("tam=Xh.[str=fit,lpf=300->9000,gain=2]{fff}")
            parts.append("gl=C7h.->C6[gain=-2]")
            parts.append("m5=C4h.[gate,gain=0]")
        elif k == 1:
            parts.append("gl=B6h.->A#5[gain=-2]")
            parts.append("m5=A#3h.[gate,gain=0]")
            parts.append("m2=F5h.[gate,gain=-2]")
        elif k == 2:
            parts.append("tam=Xh.[str=fit,lpf=500->9000,gain=2]")
            parts.append("gl=A#6h.->G#5[gain=-2]")
            parts.append("m5=G#3h.[gate,gain=0]")
            parts.append("m2=D#5h.[gate,gain=-2]")
        elif k == 3:
            parts.append("gl=G#6h.->F5[gain=-2]")
            parts.append("m5=F3h.[gate,gain=0]")
            parts.append("m2=C#5h.[gate,gain=-2]")
        elif k == 4:
            parts.append("tam=Xh.[str=fit,lpf=200->9000,gain=3]")
            parts.append("gl=F6h.->C5[gain=-1]")
            parts.append("m5=F3h.[gate,gain=1]")
            parts.append("m2=A#4h.[gate,gain=-1]")
        else:
            parts.append("tam=Xh.[str=fit,lpf=120->9000,gain=4]")
            parts.append("m5=C3h.[gate,gain=2]")
            parts.append("m2=C5h.[gate,gain=0]")
            parts.append("m1=C7h.[gate,gain=-2]")
            parts.append("gl=C6h.->C7[gain=-3]")

    w(f"bar {bar}: " + "  ".join(parts))

text = "\n".join(out) + "\n"
open("bolero.mus", "w").write(text)

secs = TOTAL_BARS * 3 * 60 / 66
print(f"wrote bolero.mus — {TOTAL_BARS} bars, {len(text)} chars")
print(f"duration at crotchet=66 in 3/4: {secs:.1f} s = {int(secs//60)}:{secs%60:04.1f}")
print(f"ostinato strokes: {170*10 + 170*14} over {TOTAL_BARS} bars")
