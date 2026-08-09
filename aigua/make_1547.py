#!/usr/bin/env python3
"""Generate aigua_1547.mus — "1547", low-volume funk from the Aigua birds.

Vulfpeck named a tune after a year; this one is named after a frequency.
The persistent bird's median call is 1547 Hz — a slightly flat G6 — so the
track is in G major because the bird was already in it. Where the motet put
the same bird in a four-and-a-half-second nave, this puts it in a dead room
(reverb 0.6 s, sends near zero) with a rhythm section.

Genre mechanics, and where they come from in this repo:

  swing        `# swing: 16 56` — the new MPC-style header. Straight 16ths
               cannot sit in a pocket; every off-16th lands ~17 ms late.
  kick         the gecs recipe, decaffeinated: a buzz call dropped ~3 octaves
               on an exponential ramp, no distortion, round.
  snare        the car again, but tight: gated to the slot, dark filter,
               ghost notes at -17 dB on the e-and-a before the backbeats.
  hats         offbeat eighths only (the Whitest Boy Alive signature) until
               the last chorus earns its sixteenth-note shaker.
  bass         the lead singer, per Vulfpeck doctrine: buzz, clean, melodic,
               staccato, mixed forward. Everything else leaves it room.
  keys/guitar  mid-voice chords chick on the off-twos; bright-voice triads
               skank on the sixteenth offbeats, high-passed to nothing.
  vocals       the birds themselves — call-voice pentatonic phrases, and the
               ad-libs are gesture QUOTES (gest=), measured contours from
               the research object riffing over a ii-V. The coda is h70,
               the cleanest event in the corpus, verbatim off the tape:
               one chirp, dry, and the band stops.

Every bar of every rhythm track is checked to sum to exactly 4 quarter
notes before the score is written. Funk dies of arithmetic first.
"""
from __future__ import annotations

import re
from pathlib import Path

OUT = Path(__file__).resolve().parent / "aigua_1547.mus"

DUR = {"w": 4.0, "h": 2.0, "q": 1.0, "e": 0.5, "s": 0.25, "t": 0.125}
RE_TOK = re.compile(r"^(?:\{[^}]*\})?(?:<[^>]*>|[A-GRX](?:#|b)?\d*)((?:[whqest]\.?)+)")


def bar_ql(content: str) -> float:
    content = re.sub(r"<[^>]*>", "CH", content)
    total = 0.0
    for tok in content.split():
        if tok.startswith("{"):
            continue
        body = tok.split("[")[0]
        m = re.search(r"((?:[whqest]\.?)+)$", body)
        if not m:
            raise ValueError(f"no duration in token {tok!r}")
        for piece in re.findall(r"[whqest]\.?", m.group(1)):
            total += DUR[piece[0]] * (1.5 if piece.endswith(".") else 1.0)
    return total


bars: dict[int, dict[str, str]] = {b: {} for b in range(1, 53)}
sections: dict[int, str] = {}


def put(track: str, bar: int, content: str, check: bool = True) -> None:
    if check:
        got = bar_ql(content)
        assert abs(got - 4.0) < 1e-6, (track, bar, got, content)
    assert track not in bars[bar], (track, bar)
    bars[bar][track] = content


# ---- drum vocabulary -----------------------------------------------------
KICK_STEADY = "Xq[gate] Rq Xq[gate] Rq"                       # WBA: 1 and 3
KICK_SYNC = "Xe[gate] Rq Re Re Xe[gate] Re Xe[gate]"          # 1, 2.5, 3.5
SNARE_BACK = "Rq Xq[gate] Re Rs Xs[gain=-17] Xq[gate]"        # 2, 4 + ghost
SNARE_GHOSTY = "Rq Xq[gate] Rs Xs[gain=-18] Rs Xs[gain=-16] Xq[gate]"
HATS_OFF = "Re Xe Re Xe Re Xe Re Xe"                          # the WBA hats
SHAKER_16 = "Xs[gain=-3] Xs Xs[gain=-3] Xs " * 4              # last chorus

# ---- bass: the lead singer ----------------------------------------------
BASS_G = "G2e[gate] Rs G2s Re G3s[gate] Rs G2e[gate] Rs G2s Rs D3s E3s F#3s"
BASS_C = "C3e[gate] Rs C3s Re G2s Rs E3e[gate] Rs C3s Rs C3s B2s A2s"
BASS_G2 = "G2e[gate] Rs G2s Re G3s[gate] Rs G2e[gate] Re B2s Rs D3s Rs"
BASS_C2 = "C3e[gate] Rs C3s Re G2s Rs E3e[gate] Rs G3s[gate] Rs F#3s E3s D3s"
BASS_A = "A2e[gate] Rs A2s Re A3s[gate] Rs A2e[gate] Rs G2s Rs A2s B2s C#3s"
BASS_D = "D3e[gate] Rs D3s Re D2s Rs D3e[gate] Rs C3s Rs B2s A2s F#2s"
BASS_Gc = "G2e[gate] Rs G2s Re G3s[gate] Rs B2e[gate] Rs D3s Rs G3s Rs Rs"
BASS_E = "E3e[gate] Rs E3s Re E2s Rs G2e[gate] Rs A2s Rs B2s D3s E3s"
BASS_BRIDGE = "G2e[gate] Re G2s Rs B2s Rs D3e[gate] Re G3s[gate] Rs E3s D3s"
BASS_FILL = "G2s A2s B2s D3s E3s D3s B2s A2s G2e[gate] Rs G3s[gate] Re Re"

# ---- keys and guitar -----------------------------------------------------
KEYS_G = "Rq Re <G4 B4 D5 F#5>e[gate,rel=0.07] Rq Re <G4 B4 D5>s[gate] Rs"
KEYS_C = "Rq Re <G4 C5 E5 B5>e[gate,rel=0.07] Rq Re <G4 C5 E5>s[gate] Rs"
KEYS_A = "Rq Re <G4 C5 E5>e[gate,rel=0.07] Rq Re <A4 C5 E5>s[gate] Rs"
KEYS_D = "Rq Re <F#4 A4 C5 E5>e[gate,rel=0.07] Rq Re <F#4 A4 C5>s[gate] Rs"
KEYS_E = "Rq Re <E4 G4 B4 D5>e[gate,rel=0.07] Rq Re <E4 G4 B4>s[gate] Rs"
GTR = "Rs <D5 G5 B5>s[gate] Re Rs <D5 G5 B5>s[gate] Re Rs <D5 G5 B5>s[gate] Re Rs <B4 E5 G5>s[gate] Re"

# ---- the vocal: pentatonic phrases + quoted ad-libs ----------------------
VOX = {
    "c1": "Rq Re B5e D6q E6e Re",
    "c2": "G6q Re E6e D6q Rq",
    "c3": "Rq Re D6e E6e G6e A6q",
    "c4": "B5q[gest=h70] Rq Rh",              # quoted chirp lands the phrase
    "c5": "Rq Re D6e B5q G5e Re",
    "c6": "A5q Re B5e D6h",
    "c7": "Re E6e D6e B5e G6e E6e D6q",
    "c8": "G6q[gest=h72] Rq Rh",
    "a1": "Rh Re D6e[gest=h70] Rq",           # verse-2 ad-libs, trading with bass
    "a2": "Rq G6e[gest=h52] Re Rh",
    "a3": "Rh Rq B5e[gest=h72] Re",
    "o1": "Rq Re G6e[gest=h70] Rq E6q[gest=h72]",
}

# =========================================================================
sections[1] = "intro [1-4] — rhythm section only, as is right"
for b in range(1, 5):
    put("kk", b, KICK_STEADY)
    put("sn", b, SNARE_BACK if b < 4 else SNARE_GHOSTY)
    put("hh", b, HATS_OFF)
    put("bs", b, [BASS_G, BASS_C, BASS_G, BASS_C2][b - 1])

sections[5] = "verse A [5-12] — keys chick on the off-twos; everything leaves room for the bass"
for i, b in enumerate(range(5, 13)):
    put("kk", b, KICK_STEADY)
    put("sn", b, SNARE_BACK if b % 4 else SNARE_GHOSTY)
    put("hh", b, HATS_OFF)
    put("bs", b, [BASS_G, BASS_C, BASS_G2, BASS_C, BASS_G, BASS_C2, BASS_G2, BASS_C][i])
    put("ky", b, KEYS_G if i % 2 == 0 else KEYS_C)

sections[13] = "chorus B [13-20] — ii-V-I-vi; the birds take the melody, claps arrive"
CHORUS_BASS = [BASS_A, BASS_D, BASS_Gc, BASS_E]
CHORUS_KEYS = [KEYS_A, KEYS_D, KEYS_G, KEYS_E]
for i, b in enumerate(range(13, 21)):
    put("kk", b, KICK_SYNC)
    put("sn", b, SNARE_BACK if b % 4 else SNARE_GHOSTY)
    put("hh", b, HATS_OFF)
    put("bs", b, CHORUS_BASS[i % 4])
    put("ky", b, CHORUS_KEYS[i % 4])
    put("gt", b, GTR)
    put("cp", b, "Rq Xq Rq Xq")
    put("vx", b, VOX[f"c{i + 1}"])

sections[21] = "verse A2 [21-28] — the ad-libs are measured contours; bird and bass trade bars"
for i, b in enumerate(range(21, 29)):
    put("kk", b, KICK_STEADY)
    put("sn", b, SNARE_BACK if b % 4 else SNARE_GHOSTY)
    put("hh", b, HATS_OFF)
    put("bs", b, [BASS_G, BASS_C, BASS_G2, BASS_FILL, BASS_G, BASS_C2, BASS_G2, BASS_FILL][i])
    put("ky", b, KEYS_G if i % 2 == 0 else KEYS_C)
    if i in (0, 2, 5):
        put("vx", b, VOX[["a1", "a2", "a3"][(0, 2, 5).index(i)]])

sections[29] = "bridge [29-32] — strip it: bass, claps, hats. Vulf rule: the drop-out IS the hook"
for i, b in enumerate(range(29, 33)):
    put("bs", b, BASS_BRIDGE if i < 3 else BASS_FILL)
    put("hh", b, HATS_OFF)
    put("cp", b, "Rq Xq Rq Xq")

sections[33] = "chorus B2 [33-40]"
for i, b in enumerate(range(33, 41)):
    put("kk", b, KICK_SYNC)
    put("sn", b, SNARE_BACK if b % 4 else SNARE_GHOSTY)
    put("hh", b, HATS_OFF)
    put("bs", b, CHORUS_BASS[i % 4])
    put("ky", b, CHORUS_KEYS[i % 4])
    put("gt", b, GTR)
    put("cp", b, "Rq Xq Rq Xq")
    put("vx", b, VOX[f"c{i + 1}"])

sections[41] = "chorus B3 [41-48] — the shaker was earned"
for i, b in enumerate(range(41, 49)):
    put("kk", b, KICK_SYNC)
    put("sn", b, SNARE_BACK if b % 4 else SNARE_GHOSTY)
    put("hh", b, HATS_OFF)
    put("sh", b, SHAKER_16.strip())
    put("bs", b, CHORUS_BASS[i % 4])
    put("ky", b, CHORUS_KEYS[i % 4])
    put("gt", b, GTR)
    put("cp", b, "Rq Xq Rq Xq")
    put("vx", b, VOX[f"c{i + 1}"] if i < 7 else VOX["o1"])

sections[49] = "tag [49-52] — band hits, then the bird gets the last word, dry"
HIT = "<G4 B4 D5 G5>q[gate,rel=0.09] Rq Rh"
for b in (49, 50, 51):
    put("kk", b, "Xq[gate] Rq Rh")
    put("sn", b, "Xq[gate] Rq Rh" if b != 50 else "Xq[gate] Rq Rq Xe[stut=3] Re")
    put("ky", b, HIT)
    put("gt", b, "<D5 G5 B5>q[gate] Rq Rh")
    put("bs", b, "G2q[gate] Rq Rh" if b != 51 else BASS_FILL)
    put("cp", b, "Xq Rq Rh")
put("kk", 52, "Xq[gate] Rq Rh")
put("bs", 52, "G2q[gate] Rq Rh")
put("vx", 52, "Rq Re Xe[gest=h70,gsrc=raw,str=1,rel=0.03] Rh")

# ---- emit ----------------------------------------------------------------
TRACKS = ["kk", "sn", "hh", "sh", "cp", "bs", "ky", "gt", "vx"]

HEADER = """\
# score: 1547
# summary: 52 bars / 9 voices / 2:00 — low-volume funk; the title is the bird's median call in Hz, which is why the key is G
# tempo: 104
# time: 4/4
# key: G
# bars: 52
# pack: instrument.json
# gestures: v2/sweep-events.json
# tape: aigua_raw.wav
# swing: 16 56
# reverb: 0.6
# master: rms=-14

# The persistent bird's median call is 1547 Hz — G6, 23 cents flat of the
# 12-TET grid this track deliberately lives on. The motet met the bird in
# its own tuning; this one hands it a click track and a dry room, and the
# bird turns out to be a competent session vocalist. Ad-libs are gest=
# quotes: measured consensus contours from the research object, riffing
# over a ii-V. No pitch outside G major except whatever the bird does
# inside its quoted gestures, which is its business.

# instruments:
#   kk = kick (perc, voice=buzz, st=-30->-46, curve=exp, tau=0.045, lpf=2800, rel=0.09, send=0.02, gain=1)
#   sn = snare (perc, voice=car, off=1150, hpf=180, lpf=5200, rel=0.05, send=0.06, gain=1)
#   hh = hats (perc, voice=tick, hpf=6200, rel=0.007, send=0.03, gain=-8, pan=0.22)
#   sh = shaker (perc, voice=tick, s=3, hpf=7500, rel=0.006, send=0.03, gain=-16, pan=-0.3)
#   cp = clap (perc, voice=chup, hpf=520, rel=0.05, send=0.12, gain=-5, pan=-0.12)
#   bs = bass (bass, voice=buzz, lpf=1600, rel=0.04, send=0.02, gain=0)
#   ky = keys (treble, voice=mid, mode=vocoder, lpf=5200, rel=0.08, send=0.07, gain=-9, pan=-0.25)
#   gt = guitar (treble, voice=bright, hpf=650, rel=0.04, send=0.05, gain=-12, pan=0.35)
#   vx = vocal (treble, voice=call, hpf=280, rel=0.09, send=0.10, gain=-4)
"""


def main() -> None:
    lines = [HEADER]
    for b in range(1, 53):
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
