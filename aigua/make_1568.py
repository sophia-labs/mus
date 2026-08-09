#!/usr/bin/env python3
"""Generate aigua_1568.mus — "1568", the sequel to "1547" with a synthesizer.

1547 Hz is the persistent bird's median call — a G6 sitting 23 cents flat of
the grid. 1568 Hz is the grid's own G6. This is the tune where the machine's
G joins the bird's: the sample instrument stays at the core, but the band
gains a soft synth (SPEC-AUDIO: `synth=` instruments — saw/square/tri,
detune, sub-oscillator, filter sweep), the bird gets experimental transforms
(`chop=` granular resequencing, `ring=` ring-mod — the bird becomes a
drummer, then a Martian), the mix gets Haas-delay width, and the tempo goes
to 122 with sixteenth-note interplay everywhere.

Harmonic loosening, per the brief: verses and riffs live in G dorian (the
Bb and F the funk always wanted); choruses resolve to the major-key ii-V
world of 1547. The pad is the warmth the tape alone could not supply.

Every bar of every track is duration-checked to exactly 4 quarters.
"""
from __future__ import annotations

import re
from pathlib import Path

OUT = Path(__file__).resolve().parent / "aigua_1568.mus"

DUR = {"w": 4.0, "h": 2.0, "q": 1.0, "e": 0.5, "s": 0.25, "t": 0.125}


def bar_ql(content: str) -> float:
    content = re.sub(r"<[^>]*>", "CH", content)
    total = 0.0
    for tok in content.split():
        if tok.startswith("{"):
            continue
        body = tok.split("[")[0].split("->")[0]
        m = re.search(r"((?:[whqest]\.?)+)$", body)
        if not m:
            raise ValueError(f"no duration in token {tok!r}")
        for piece in re.findall(r"[whqest]\.?", m.group(1)):
            total += DUR[piece[0]] * (1.5 if piece.endswith(".") else 1.0)
    return total


bars: dict[int, dict[str, str]] = {b: {} for b in range(1, 69)}
sections: dict[int, str] = {}


def put(track: str, bar: int, content: str) -> None:
    got = bar_ql(content)
    assert abs(got - 4.0) < 1e-6, (track, bar, got, content)
    assert track not in bars[bar], (track, bar)
    bars[bar][track] = content


# ---- drums ---------------------------------------------------------------
KICK_A = "Xe[gate] Rq Re Re Xe[gate] Re Xe[gate]"
KICK_B = "Xe[gate] Rq Rs Xs[gain=-9] Re Xe[gate] Rs Xs[gain=-9] Xe[gate]"
KICK_SPARSE = "Xq[gate] Rq Rh"
SN_A = "Rq Xq[gate] Re Rs Xs[gain=-17] Xq[gate]"
SN_FILL = "Rq Xq[gate] Xs[gain=-14] Xs[gain=-10] Xs[gain=-6] Xs[gain=-3] Xq[gate]"
HATS_OFF = "Re Xe Re Xe Re Xe Re Xe"
HATS_16 = "Xs Xs[gain=-6] Xs[gain=-3] Xs[gain=-6] " * 4
SH_16 = "Xs[gain=-3] Xs Xs[gain=-3] Xs " * 4
CLAP = "Rq Xq Rq Xq"

# ---- the riff (unison, G dorian) -----------------------------------------
RIFF_SB = "G1s G1s Rs Bb1s Rs G1s F2s Rs G2s Rs F2s D2s Bb1s C2s Rs Rs"
RIFF_CL = "G3s G3s Rs Bb3s Rs G3s F4s Rs G4s Rs F4s D4s Bb3s C4s Rs Rs"

# ---- synth bass ----------------------------------------------------------
SB_G1 = "G1e Rs G2s Rs Bb1s G1s Rs F2e Rs G2s G1s Rs D2s Rs"
SB_G2 = "G1s Rs G2s Rs G1e Bb1s C2s D2e Rs D2s F2s G2s Rs Rs"
SB_A = "A1e Rs A2s Rs C2s A1s Rs G2e Rs E2s C2s Rs A1s Rs"
SB_D = "D2e Rs D2s Rs F#2s A2s Rs D2e Rs C2s A1s Rs D2s Rs"
SB_Gc = "G1e Rs G2s Rs B1s D2s Rs G2e Rs D2s B1s Rs G1s Rs"
SB_E = "E2e Rs E2s Rs G2s E2s Rs D2e Rs B1s A1s Rs E2s Rs"
SB_FILL = "G1s A1s Bb1s C2s D2s E2s F2s G2s A2s G2s F2s D2s C2s Bb1s A1s G1s"
SB_PEDAL = "G1h Rq G1q"

# ---- clav + pad ----------------------------------------------------------
CL_COMP = ("Rs <G3 Bb3 F4>s Rs Rs Rs <G3 Bb3 F4>s Rs <F3 A3 C4>s "
           "Rs <G3 Bb3 F4>s Rs Rs Rs <G3 C4 E4>s Rs Rs")
PD = {"A": "<A3 C4 E4 G4>w", "D": "<D4 F#4 C5>w",
      "G": "<G3 B3 D4 F#4>w", "E": "<E3 G3 B3 D4>w",
      "dark": "<G3 Bb3 D4>w[satk=0.5]"}

# ---- lead solo (G dorian, scoops via gliss) ------------------------------
LEAD = [
    "Rq D5e->G5 Re Bb5e A5s G5s F5e G5e",
    "G5s F5s D5s Bb4s C5e G4e Rq D5q->D6",
    "Re G5e Bb5e C6e D6q->G6 Rq",
    "F6s D6s C6s Bb5s C6s Bb5s G5s F5s G5h",
    "Rq Bb5e->D6 Re G5e F5s D5s F5e G5e",
    "D5s F5s G5s Bb5s D6s Bb5s G5s F5s D6e C6e Bb5e G5e",
    "Re C6e D6e F6e G6q->G5 Rq",
    "G5s Rs F5s G5s Rs Bb5s G5s Rs D5e F5s G5s G5q",
]

# ---- bird ----------------------------------------------------------------
VOX = {
    "c1": "Rq Re B5e D6q E6e Re", "c2": "G6q[stut=3] Re E6e D6q Rq",
    "c3": "Rq Re D6e E6e G6e A6q", "c4": "B5q[gest=h70] Rq Rh",
    "c5": "Rq Re D6e B5q G5e Re", "c6": "A5q Re B5e D6h[stut=6]",
    "c7": "Re E6e D6e B5e G6e E6e D6q", "c8": "G6q[gest=h72,stut=4] Rq Rh",
    "a1": "Rh Re D6e[gest=h70] Rq", "a2": "Rq G6e[gest=h52] Re Rh",
}
FX1 = "Xq[chop=8] Rq Xh[chop=12,ring=180]"
FX2 = "Xe[chop=6] Xe[chop=6,ring=90] Rq Xh[chop=16]"
FX3 = "Xh[chop=24,ring=45] Xq[chop=10] Xq[chop=4,ring=310]"
FX4 = "Xw[chop=32]"

CHORUS_SB = [SB_A, SB_D, SB_Gc, SB_E]
CHORUS_PD = ["A", "D", "G", "E"]

# =========================================================================
sections[1] = "riff [1-4] — the hook in unison, machine G under bird-adjacent dorian; drums at 3"
for b in (1, 2, 3, 4):
    put("sb", b, RIFF_SB)
    put("cl", b, RIFF_CL)
    if b >= 3:
        put("kk", b, KICK_A)
        put("sn", b, SN_A)
        put("hh", b, HATS_OFF)

sections[5] = "A1 [5-12] — sixteenth interplay: bass and clav lock, bird sprinkles"
for i, b in enumerate(range(5, 13)):
    put("kk", b, KICK_A)
    put("sn", b, SN_A if b != 12 else SN_FILL)
    put("hh", b, HATS_OFF if b < 9 else HATS_16.strip())
    put("sb", b, [SB_G1, SB_G2, SB_G1, SB_G2, SB_G1, SB_G2, SB_G1, SB_FILL][i])
    put("cl", b, CL_COMP)
    if i in (3, 6):
        put("vx", b, VOX["a1"] if i == 3 else VOX["a2"])
    if i == 5:
        put("fx", b, FX1)

sections[13] = "B1 [13-20] — chorus: the pad is the warmth the tape could not supply"
for i, b in enumerate(range(13, 21)):
    put("kk", b, KICK_B)
    put("sn", b, SN_A if b % 4 else SN_FILL)
    put("hh", b, HATS_16.strip())
    put("sb", b, CHORUS_SB[i % 4])
    put("pd", b, PD[CHORUS_PD[i % 4]])
    put("cp", b, CLAP)
    put("vx", b, VOX[f"c{i + 1}"])

sections[21] = "A2 [21-28] — riff returns, then the bird and the chop trade bars"
for b in (21, 22):
    put("sb", b, RIFF_SB)
    put("cl", b, RIFF_CL)
    put("kk", b, KICK_A)
    put("sn", b, SN_A)
    put("hh", b, HATS_16.strip())
for i, b in enumerate(range(23, 29)):
    put("kk", b, KICK_A)
    put("sn", b, SN_A if b != 28 else SN_FILL)
    put("hh", b, HATS_OFF)
    put("sb", b, [SB_G1, SB_G2, SB_G1, SB_G2, SB_G1, SB_FILL][i])
    put("cl", b, CL_COMP)
    if i % 2 == 1:
        put("fx", b, [FX1, FX2, FX3][i // 2])
    else:
        put("vx", b, VOX["a1"] if i == 0 else (VOX["a2"] if i == 2 else VOX["c4"]))

sections[29] = "C [29-36] — the lead earns the speed. Dorian sixteenths, portamento scoops"
for i, b in enumerate(range(29, 37)):
    put("kk", b, KICK_B)
    put("sn", b, SN_A if b % 4 else SN_FILL)
    put("hh", b, HATS_16.strip())
    put("sh", b, SH_16.strip() if b >= 33 else "Rw")
    put("sb", b, [SB_G1, SB_G2][i % 2] if b != 36 else SB_FILL)
    put("cl", b, CL_COMP)
    put("ld", b, LEAD[i])

sections[37] = "breakdown [37-42] — the transforms get the floor: the bird as drummer, then as Martian"
for i, b in enumerate(range(37, 43)):
    put("kk", b, KICK_SPARSE)
    put("hh", b, HATS_OFF)
    put("sb", b, SB_PEDAL)
    put("fx", b, [FX1, FX2, FX3, FX4, FX2, FX3][i])
    if i in (1, 4):
        put("pd", b, PD["dark"])
    if i == 5:
        put("sn", b, SN_FILL)

sections[43] = "B2 [43-50]"
for i, b in enumerate(range(43, 51)):
    put("kk", b, KICK_B)
    put("sn", b, SN_A if b % 4 else SN_FILL)
    put("hh", b, HATS_16.strip())
    put("sb", b, CHORUS_SB[i % 4])
    put("pd", b, PD[CHORUS_PD[i % 4]])
    put("cp", b, CLAP)
    put("vx", b, VOX[f"c{i + 1}"])

sections[51] = "B3 [51-58] — shaker on, lead obligato answers the bird"
for i, b in enumerate(range(51, 59)):
    put("kk", b, KICK_B)
    put("sn", b, SN_A if b % 4 else SN_FILL)
    put("hh", b, HATS_16.strip())
    put("sh", b, SH_16.strip())
    put("sb", b, CHORUS_SB[i % 4])
    put("pd", b, PD[CHORUS_PD[i % 4]])
    put("cp", b, CLAP)
    put("vx", b, VOX[f"c{i + 1}"])
    if i in (1, 3, 5):
        put("ld", b, LEAD[4 + i // 2])

sections[59] = "D [59-64] — riff reprise with the whole band on it"
for i, b in enumerate(range(59, 65)):
    put("sb", b, RIFF_SB if b != 62 else SB_FILL)
    put("cl", b, RIFF_CL)
    put("kk", b, KICK_B)
    put("sn", b, SN_A if b != 64 else SN_FILL)
    put("hh", b, HATS_16.strip())
    put("sh", b, SH_16.strip())
    if i in (1, 3):
        put("fx", b, FX1 if i == 1 else FX2)

sections[65] = "tag [65-68] — hits; the bird's G gets the last word over the machine's"
for b in (65, 66):
    put("kk", b, "Xq[gate] Rq Rh")
    put("sn", b, "Xq[gate] Rq Rh")
    put("sb", b, "G1q Rq Rh")
    put("cl", b, "<G3 Bb3 F4>q Rq Rh")
    put("cp", b, "Xq Rq Rh")
put("kk", 67, "Xq[gate] Rq Rh")
put("sb", 67, "G1q Rq Rh")
put("vx", 67, "Rq Re Xe[gest=h70,gsrc=raw,str=1,rel=0.03] Rh")
put("sb", 68, "G1w")
put("kk", 68, "Xq[gate] Rq Rh")

# ---- emit ----------------------------------------------------------------
TRACKS = ["kk", "sn", "hh", "sh", "cp", "sb", "cl", "pd", "ld", "vx", "fx", "rm"]

HEADER = """\
# score: 1568
# summary: 68 bars / 12 voices / 2:14 — the sequel to 1547: the grid's G6 joins the bird's, with a soft synth in the band
# tempo: 122
# time: 4/4
# key: G
# bars: 68
# pack: instrument.json
# gestures: v2/sweep-events.json
# tape: aigua_raw.wav
# swing: 16 55
# reverb: 0.8
# master: rms=-14.5

# 1547 Hz is the bird's median G6, 23 cents flat. 1568 Hz is equal
# temperament's answer. The soft synth (SPEC-AUDIO: synth= instruments) is
# the first sound in this project that never passed through the Aigua air —
# and the mix leans on it for the warmth the 62 kbps tape cannot give.
# Verses ride G dorian; choruses resolve major. The bird keeps its
# quotations (gest=) and gains transforms: chop= re-deals a call into a
# drum fill, ring= makes it briefly extraterrestrial. It gets the last
# word anyway, verbatim, at bar 67.

# instruments:
#   kk = kick (perc, voice=buzz, st=-30->-46, curve=exp, tau=0.062, lpf=2100, rel=0.17, send=0.02, gain=3)
#   sn = snare (perc, voice=car, off=1150, hpf=160, lpf=4000, rel=0.05, send=0.08, gain=-3)
#   hh = hats (perc, voice=tick, hpf=6200, rel=0.007, send=0.03, gain=-11, pan=0.22)
#   sh = shaker (perc, voice=tick, s=3, hpf=7500, rel=0.006, send=0.03, gain=-17, pan=-0.3)
#   cp = clap (perc, voice=chup, hpf=520, rel=0.05, send=0.12, gain=-8, pan=-0.12)
#   sb = synth bass (bass, synth=saw, sub=0.9, cutoff=520, famt=850, satk=0.004, sdec=0.11, ssus=0.65, srel=0.07, send=0.02, gain=2)
#   cl = clav (treble, synth=square, cutoff=1100, famt=1100, satk=0.004, sdec=0.06, ssus=0.22, srel=0.06, send=0.08, gain=-17, pan=0.18, haas=8)
#   pd = pad (treble, synth=tri, detune=9, cutoff=1900, satk=0.26, sdec=0.3, ssus=0.85, srel=0.7, send=0.30, gain=-14, pan=-0.1, haas=14)
#   ld = lead (treble, synth=saw, detune=11, cutoff=2400, famt=1100, satk=0.006, sdec=0.08, ssus=0.7, srel=0.11, send=0.14, gain=-13, pan=-0.15)
#   vx = vocal (treble, voice=call, glow=12, ghold=1, gwarble=7.6, gharm=0+4+7+12, pump=2.033, haas=11, rel=0.10, send=0.18, gain=1)
#   fx = bird fx (perc, voice=bright, glow=12, gharm=0+7+12+19, pump=2.033, send=0.20, gain=-6, pan=0.3)
#   rm = rumble (bass, sample=samples/sub_bed.wav, send=0.06, gain=-7)
"""


for _b in range(3, 67):
    if "rm" not in bars[_b]:
        put("rm", _b, "Xw[gate,lpf=95->140]" if _b % 2 else "Xw[gate,lpf=140->95]")


def main() -> None:
    lines = [HEADER]
    for b in range(1, 69):
        if b in sections:
            lines.append("")
            lines.append(f"# section: {sections[b]}")
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
