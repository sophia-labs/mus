"""Generate cadiz.mus — the Act I finale march from Chueca & Valverde's
zarzuela *Cádiz* (Teatro Apolo, Madrid, 20 November 1886), realised in birds.

WHAT IS FAITHFUL. The form and the idiom. A Spanish military pasodoble in
2/4 at 116, in B-flat — the band key — running 200 bars, about 3:27. It opens
the way the number opens and is named for: *las cornetas nos anuncian*, a
bugle call, so the opening fanfare uses only the natural harmonics a bugle can
actually sound (B-flat, F, B-flat, D, F, B-flat) and nothing else. The
`¡Rataplán!` of the chorus text is the snare. There is a copla, a refrain on
*¡Que viva España!*, a trio in the subdominant as marches have, and a tutti
reprise. This march served as Spain's de facto anthem for about a decade, and
Chueca had already used the tune as an 1868 anthem for General Prim.

WHAT IS NOT. The notes. No score or transcription of this march was reachable
from here, so the melodies are written to the idiom and to the shape of the
sung text rather than copied. The bugle calls are constrained by physics and
so are probably close; the copla and refrain are mine.

The instrument is 56 seconds of birdsong recorded in Aigua, Uruguay. The
cornetas are a bird. The cymbal is a passing car.
"""

TEMPO = 116
BEATS = 2                       # 2/4
BAR_Q = 2.0


def dur(q):
    return {2.0: "h", 1.5: "q.", 1.0: "q", 0.5: "e", 0.25: "s"}[q]


def bars_of(seq):
    """(note, quarters) list -> list of bars, each summing to 2 quarters."""
    out, cur, acc = [], [], 0.0
    for n, q in seq:
        cur.append(f"{n}{dur(q)}")
        acc += q
        if abs(acc - BAR_Q) < 1e-9:
            out.append(" ".join(cur)); cur, acc = [], 0.0
        elif acc > BAR_Q + 1e-9:
            raise ValueError(f"bar overflow at {n}")
    assert not cur, cur
    return out


# --- LLAMADA: natural harmonics only. a bugle has no valves. -----------------
BUGLE = bars_of([
    ("R", 1), ("Bb4", .5), ("Bb4", .5),
    ("D5", 1), ("F5", 1),
    ("F5", .5), ("D5", .5), ("Bb4", .5), ("D5", .5),
    ("F5", 2),
    ("Bb5", 1), ("F5", 1),
    ("D5", .5), ("F5", .5), ("D5", .5), ("Bb4", .5),
    ("F4", .5), ("Bb4", .5), ("D5", .5), ("F5", .5),
    ("Bb5", 2),
])

# The second corneta an octave down — still only harmonics, still playable.
BUGLE_LOW = bars_of([
    ("R", 1), ("Bb3", .5), ("Bb3", .5),
    ("D4", 1), ("F4", 1),
    ("F4", .5), ("D4", .5), ("Bb3", .5), ("D4", .5),
    ("F4", 2),
    ("Bb4", 1), ("F4", 1),
    ("D4", .5), ("F4", .5), ("D4", .5), ("Bb3", .5),
    ("F3", .5), ("Bb3", .5), ("D4", .5), ("F4", .5),
    ("Bb4", 2),
])

# --- COPLA: "Las cornetas nos anuncian / que los bravos llegan ya" -----------
COPLA = bars_of([
    ("Bb4", .5), ("Bb4", .5), ("C5", .5), ("D5", .5),
    ("D5", 1), ("C5", 1),
    ("Bb4", .5), ("C5", .5), ("D5", .5), ("Eb5", .5),
    ("F5", 2),
    ("F5", .5), ("F5", .5), ("Eb5", .5), ("D5", .5),
    ("C5", 1), ("Bb4", 1),
    ("A4", .5), ("Bb4", .5), ("C5", .5), ("A4", .5),
    ("Bb4", 2),
    ("F5", .5), ("F5", .5), ("G5", .5), ("A5", .5),
    ("Bb5", 1), ("A5", 1),
    ("G5", .5), ("F5", .5), ("Eb5", .5), ("D5", .5),
    ("C5", 2),
    ("D5", .5), ("Eb5", .5), ("F5", .5), ("G5", .5),
    ("F5", 1), ("D5", 1),
    ("C5", .5), ("D5", .5), ("C5", .5), ("Bb4", .5),
    ("Bb4", 2),
])

# --- ESTRIBILLO: "¡Que viva España!" -----------------------------------------
ESTRIB = bars_of([
    ("Bb5", 2),
    ("Bb5", .5), ("A5", .5), ("G5", .5), ("F5", .5),
    ("G5", 1), ("F5", 1),
    ("Eb5", 2),
    ("F5", 2),
    ("F5", .5), ("G5", .5), ("A5", .5), ("Bb5", .5),
    ("C6", 1), ("Bb5", 1),
    ("A5", 2),
    ("Bb5", 2),
    ("Bb5", .5), ("C6", .5), ("D6", .5), ("C6", .5),
    ("Bb5", 1), ("A5", 1),
    ("G5", 2),
    ("F5", .5), ("G5", .5), ("A5", .5), ("Bb5", .5),
    ("A5", 1), ("G5", 1),
    ("F5", .5), ("Eb5", .5), ("D5", .5), ("C5", .5),
    ("Bb4", 2),
])

# --- TRIO: the subdominant, as marches do ------------------------------------
TRIO = bars_of([
    ("Bb4", .5), ("C5", .5), ("D5", .5), ("Eb5", .5),
    ("G5", 1), ("F5", 1),
    ("Eb5", .5), ("D5", .5), ("C5", .5), ("Bb4", .5),
    ("Bb4", 2),
    ("C5", .5), ("D5", .5), ("Eb5", .5), ("F5", .5),
    ("G5", 1), ("Ab5", 1),
    ("G5", .5), ("F5", .5), ("Eb5", .5), ("D5", .5),
    ("Eb5", 2),
    ("Eb5", .5), ("F5", .5), ("G5", .5), ("Ab5", .5),
    ("Bb5", 1), ("Ab5", 1),
    ("G5", .5), ("F5", .5), ("Eb5", .5), ("F5", .5),
    ("G5", 2),
    ("F5", .5), ("Eb5", .5), ("D5", .5), ("C5", .5),
    ("D5", 1), ("Eb5", 1),
    ("F5", .5), ("Eb5", .5), ("D5", .5), ("C5", .5),
    ("Bb4", 2),
])

for nm, blk, want in (("bugle", BUGLE, 8), ("copla", COPLA, 16),
                      ("estrib", ESTRIB, 16), ("trio", TRIO, 16)):
    assert len(blk) == want, (nm, len(blk))

SNARE_MARCH = "Xe Xs Xs Xe Xe"
SNARE_RATA = "Xs Xs Xs Xs Xs Xs Xs Xs"
SNARE_ROLL = "Xt Xt Xt Xt Xt Xt Xt Xt Xt Xt Xt Xt Xt Xt Xt Xt"

# I / V in B-flat; trio leans to the subdominant E-flat.
CH_I = "<D4 F4 Bb4>"
CH_V = "<C4 F4 A4>"
CH_IV = "<Eb4 G4 Bb4>"
CH_EbV = "<Bb3 D4 F4>"

TOTAL = 200
SECTIONS = [
    (1, 8, "llamada — the buglers announce them"),
    (9, 16, "rataplán"),
    (17, 48, "copla I"),
    (49, 56, "puente"),
    (57, 88, "estribillo — ¡Que viva España!"),
    (89, 120, "copla II"),
    (121, 152, "trío"),
    (153, 192, "estribillo final — tutti"),
    (193, 200, "coda"),
]
sec_at = {a: (b, t) for a, b, t in SECTIONS}

out = []
w = out.append
w("# score: Marcha de Cádiz — «Los cornetas nos anuncian» (Chueca & Valverde, 1886)")
w("# summary: 200 bars / 9 voices / 3:27")
w("# tempo: 116")
w("# time: 2/4")
w("# key: Bb")
w("# bars: 200")
w("# pack: instrument.json")
w("# master: rms=-13")
w("")
w("# text @b1: Final del Acto I de la zarzuela «Cádiz», Teatro Apolo, Madrid,")
w("# text @b1: 20 de noviembre de 1886. Fue himno nacional de facto una década.")
w("# text @b1: The opening fanfare uses only the natural harmonics a bugle can")
w("# text @b1: sound — Bb F Bb D F Bb — because that is what a corneta is.")
w("# text @b2: FORM and idiom are faithful. The NOTES are not: no score was")
w("# text @b2: reachable, so the copla and estribillo are written to the shape of")
w("# text @b2: the sung text, not transcribed. The bugle calls are constrained by")
w("# text @b2: physics and are probably close.")
w("# text @b3: Las cornetas son un pájaro. El platillo es un coche que pasaba.")
w("")
w("# instruments:")
w("#   c1 = corneta I (treble, voice=bright, send=0.20, gain=-3)")
w("#   c2 = corneta II (treble, voice=bright, s=2, send=0.20, gain=-7)")
w("#   me = melodía (treble, voice=call, send=0.18, gain=-2)")
w("#   hi = flautín (treble, voice=glide, send=0.24, gain=-13)")
w("#   ha = armonía (treble, voice=mid, send=0.16, gain=-13)")
w("#   ba = bajo (bass, voice=buzz, lpf=1100, send=0.05, gain=-6)")
w("#   sn = caja (perc, voice=tick, hpf=1700, rel=0.02, send=0.12, gain=-9)")
w("#   bd = bombo (perc, voice=buzz, st=-28->-46, curve=exp, tau=0.04, lpf=200, rel=0.10, send=0.04, gain=-4)")
w("#   cy = platillo (perc, voice=car, send=0.34, gain=-9)")
w("")


def harm_for(bar_in_phrase):
    """Two bars I, two bars V — plain march harmony."""
    return CH_I if (bar_in_phrase // 2) % 2 == 0 else CH_V


lines = {}


def put(bar, trk, content):
    lines.setdefault(bar, {})[trk] = content


# llamada: bugles alone, snare joins at bar 5
for k, b in enumerate(BUGLE):
    put(1 + k, "c1", b)
    if k >= 4:
        put(1 + k, "c2", BUGLE_LOW[k])
for b in range(5, 9):
    put(b, "sn", SNARE_MARCH)

# rataplán
for b in range(9, 17):
    put(b, "sn", SNARE_RATA if b % 2 else SNARE_MARCH)
    put(b, "bd", "Xq Rq")
    if b >= 13:
        put(b, "ba", "Bb2q Rq")
        put(b, "ha", f"Rq {CH_I}q")
put(16, "sn", SNARE_ROLL)

# copla I  (16-bar theme, twice)
for rep in range(2):
    for k, b in enumerate(COPLA):
        bar = 17 + rep * 16 + k
        put(bar, "me", b)
        put(bar, "sn", SNARE_MARCH)
        put(bar, "bd", "Xq Rq")
        put(bar, "ba", "Bb2q Rq" if (k // 2) % 2 == 0 else "F2q Rq")
        put(bar, "ha", f"Rq {harm_for(k)}q")
        if rep == 1:
            put(bar, "hi", b)

# puente — bugle interjections over the drums
for k in range(8):
    bar = 49 + k
    put(bar, "sn", SNARE_RATA if k % 2 else SNARE_MARCH)
    put(bar, "bd", "Xq Xq")
    put(bar, "ba", "Bb2q F2q")
    put(bar, "ha", f"Rq {CH_V}q")
    put(bar, "c1", BUGLE[k])
put(56, "sn", SNARE_ROLL)
put(56, "cy", "Xh[str=fit,lpf=600->9000]")

# estribillo (16-bar refrain, twice)
for rep in range(2):
    for k, b in enumerate(ESTRIB):
        bar = 57 + rep * 16 + k
        put(bar, "me", b)
        put(bar, "hi", b)
        put(bar, "sn", SNARE_MARCH)
        put(bar, "bd", "Xq Xq")
        put(bar, "ba", "Bb2q F2q" if (k // 2) % 2 == 0 else "F2q Bb2q")
        put(bar, "ha", f"Rq {harm_for(k)}q")
        if k % 4 == 0:
            put(bar, "c1", "Bb5q F5q")

# copla II — with piccolo doubling an octave up
for rep in range(2):
    for k, b in enumerate(COPLA):
        bar = 89 + rep * 16 + k
        put(bar, "me", b)
        put(bar, "sn", SNARE_MARCH)
        put(bar, "bd", "Xq Rq")
        put(bar, "ba", "Bb2q Rq" if (k // 2) % 2 == 0 else "F2q Rq")
        put(bar, "ha", f"Rq {harm_for(k)}q")
        put(bar, "c2", b)

# trío — subdominant, drums pulled back
for rep in range(2):
    for k, b in enumerate(TRIO):
        bar = 121 + rep * 16 + k
        put(bar, "me", b)
        put(bar, "sn", "Xe Re Xe Re")
        put(bar, "ba", "Eb2q Rq" if (k // 2) % 2 == 0 else "Bb1q Rq")
        put(bar, "ha", f"Rq {(CH_IV if (k // 2) % 2 == 0 else CH_EbV)}q")
        if rep == 1:
            put(bar, "hi", b)

# estribillo final — everything, 40 bars: refrain twice plus an 8-bar drive
for rep in range(2):
    for k, b in enumerate(ESTRIB):
        bar = 153 + rep * 16 + k
        put(bar, "me", b)
        put(bar, "hi", b)
        put(bar, "c1", b)
        put(bar, "sn", SNARE_MARCH if k % 4 else SNARE_RATA)
        put(bar, "bd", "Xq Xq")
        put(bar, "ba", "Bb2q F2q" if (k // 2) % 2 == 0 else "F2q Bb2q")
        put(bar, "ha", f"Rq {harm_for(k)}q")
        if k % 8 == 0:
            put(bar, "cy", "Xh[str=fit,lpf=800->9000]")
for k in range(8):
    bar = 185 + k
    put(bar, "sn", SNARE_RATA)
    put(bar, "bd", "Xq Xq")
    put(bar, "ba", "Bb2q F2q")
    put(bar, "ha", f"Rq {CH_V if k % 2 else CH_I}q")
    put(bar, "c1", BUGLE[k])
    put(bar, "c2", BUGLE_LOW[k])

# coda
CODA = bars_of([
    ("Bb5", .5), ("Bb5", .5), ("F5", .5), ("D5", .5),
    ("Bb5", 1), ("F5", 1),
    ("D5", .5), ("F5", .5), ("Bb5", .5), ("D6", .5),
    ("Bb5", 2),
    ("F5", 1), ("Bb5", 1),
    ("Bb5", 2),
    ("R", 2),
    ("Bb5", 2),
])
for k, b in enumerate(CODA):
    bar = 193 + k
    put(bar, "me", b); put(bar, "c1", b); put(bar, "hi", b)
    put(bar, "sn", SNARE_ROLL if k in (5, 6) else SNARE_RATA)
    put(bar, "bd", "Xq Xq")
    put(bar, "ba", "Bb2q F2q" if k < 6 else "Bb2h")
    put(bar, "ha", f"Rq {CH_I}q")
put(193, "cy", "Xh[str=fit,lpf=500->9000,gain=-4]")
put(200, "cy", "Xh[str=fit,lpf=200->9000,gain=-1]")

# --- one long crescendo is wrong for a march; use section dynamics -----------
DYN = {1: "mf", 9: "mp", 17: "mf", 49: "f", 57: "ff", 89: "mf",
       121: "mp", 153: "ff", 185: "fff", 193: "fff"}

ORDER = ["c1", "c2", "me", "hi", "ha", "ba", "sn", "bd", "cy"]
for bar in range(1, TOTAL + 1):
    if bar in sec_at:
        end, title = sec_at[bar]
        w("")
        w(f"# section: {title} [{bar}-{end}]")
    got = lines.get(bar, {})
    if not got:
        continue
    parts = []
    for trk in ORDER:
        if trk in got:
            pre = "{" + DYN[bar] + "} " if bar in DYN else ""
            parts.append(f"{trk}={pre}{got[trk]}")
    w(f"bar {bar}: " + "  ".join(parts))

text = "\n".join(out) + "\n"
open("cadiz.mus", "w").write(text)
secs = TOTAL * BEATS * 60.0 / TEMPO
print(f"wrote cadiz.mus — {TOTAL} bars, {len(text)} chars")
print(f"duration at {TEMPO} in 2/4: {secs:.1f}s = {int(secs//60)}:{secs%60:04.1f}")
