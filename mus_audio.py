#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "numpy>=1.24", "scipy>=1.10", "soundfile>=0.12",
#   "librosa>=0.10,<0.11", "numba<0.61", "music21>=9.0",
# ]
# ///
"""
MUS-A v0.1 — render MUS to audio through a sample instrument.

MUS was designed so a human reads engraved notation while an LLM reads the
text. That asymmetry doesn't require the sound source to be an orchestra. This
renderer binds each MUS track to recorded samples instead of an instrument
name, so the same notation drives musique concrète: a score an LLM can compose
in, and a human can hear.

The note grammar is unchanged. Absolute pitch already means "this frequency",
which is exactly what a sampler needs — a pitch token becomes a transposition
away from the sample's measured f0. What's added is a parameter vocabulary for
the things engraved notation has no symbols for (pan, filter, send, stretch),
carried inside the existing `[...]` suffix and distinguished from articulations
by containing '='. See SPEC-AUDIO.md.

  ./mus_audio.py score.mus -o out.wav

Note for Intel macOS: llvmlite ships no wheels for recent versions on x86_64,
hence the numba<0.61 pin.
"""

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import scipy.signal as sig
import soundfile as sf
import librosa

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mus  # noqa: E402  — reuse the MUS parser and duration maps

SR = 48000
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
# Pitch, with the microtonal cents offset SPEC.md's open questions propose:
# `A6+22` is 22 cents above A6. Needed here because the source material sits
# 20–50 cents off 12-TET and quantising it away loses the sound of the place.
RE_NOTE = re.compile(r"^([A-G])(bb|b|n|##|#|x)?(-?\d+)([+-]\d+)?$")
ACC_OFFSET = {None: 0, "n": 0, "b": -1, "bb": -2, "#": 1, "##": 2, "x": 2}
RE_PITCH_HEAD = r"[A-G](?:bb|b|n|##|#|x)?-?\d+(?:[+-]\d+)?"

# Dynamic → dB trim relative to unity.
DYN_DB = {"ppp": -30, "pp": -25, "p": -20, "mp": -15, "mf": -11,
          "f": -7, "ff": -3.5, "fff": 0, "sfz": -2, "sf": -3}

# Articulations that mean something to a sampler.
ART_GAIN = {"acc": 4.0, "marc": 6.0, "sfz": 7.0, "stress": 2.5, "unstress": -4.0}
ART_SHORTEN = {"stac": 0.40, "stacciss": 0.25, "spic": 0.35, "detlg": 0.75}


# ---------------------------------------------------------------- pitch utils

def note_to_midi(tok: str):
    """Note token → fractional MIDI. Returns a float so cents survive."""
    m = RE_NOTE.match(tok)
    if not m:
        return None
    step, acc, octv = m.group(1), m.group(2), int(m.group(3))
    cents = int(m.group(4)) if m.group(4) else 0
    base = [0, 2, 4, 5, 7, 9, 11]["CDEFGAB".index(step)]
    return (octv + 1) * 12 + base + ACC_OFFSET.get(acc, 0) + cents / 100.0


def midi_to_hz(midi: float, a4: float = 440.0) -> float:
    return a4 * (2.0 ** ((midi - 69) / 12.0))


# ------------------------------------------------------------------ dsp utils

def varispeed(x: np.ndarray, semitones: float) -> np.ndarray:
    """Resample: pitch and duration couple, like tape. Natural on transients."""
    if abs(semitones) < 1e-4 or len(x) < 8:
        return x
    rate = 2.0 ** (semitones / 12.0)
    n_out = max(8, int(round(len(x) / rate)))
    return librosa.resample(x, orig_sr=len(x), target_sr=n_out,
                            res_type="soxr_hq").astype(np.float32)


def vocode(x: np.ndarray, semitones: float) -> np.ndarray:
    """Phase vocoder: duration held, pitch free. Smears above about ±7 st."""
    if abs(semitones) < 1e-4 or len(x) < 2048:
        return x
    return librosa.effects.pitch_shift(
        x, sr=SR, n_steps=semitones, bins_per_octave=12).astype(np.float32)


def stretch(x: np.ndarray, factor: float) -> np.ndarray:
    """factor > 1 makes it longer."""
    if abs(factor - 1.0) < 1e-3 or len(x) < 2048:
        return x
    return librosa.effects.time_stretch(x, rate=1.0 / factor).astype(np.float32)


def pitch_ramp(x, st0, st1, curve="lin", tau=0.045):
    """Continuous varispeed ramp — a pitch sweep across the sample.

    Non-uniform resampling: integrate the instantaneous rate into a read
    position map, then interpolate. The birds already behave this way (median
    call spans 18.7 st), so it is the native gesture rather than an effect.

    'exp' falls fast then flattens — that is the shape of an 808 kick's pitch
    envelope, so a bird dropped ~40 semitones with an exponential ramp becomes
    a usable kick drum rather than a slow swoop.
    """
    n_in = len(x)
    if n_in < 8:
        return x
    if abs(st0 - st1) < 1e-3:
        return varispeed(x, st0)
    est = int(n_in / (2.0 ** (min(st0, st1) / 12.0))) + 16
    t = np.arange(est) / SR
    if curve == "exp":
        st = st1 + (st0 - st1) * np.exp(-t / max(tau, 1e-4))
    else:
        st = np.linspace(st0, st1, est)
    pos = np.cumsum(2.0 ** (st / 12.0))
    pos = pos[pos < (n_in - 1)]
    if len(pos) < 8:
        return varispeed(x, st1)
    return np.interp(pos, np.arange(n_in), x).astype(np.float32)


def bitcrush(x, bits=None, decim=None):
    """Quantise amplitude and/or hold samples. Both are aliasing on purpose."""
    if bits:
        levels = max(2.0, 2.0 ** float(bits))
        x = np.round(x * (levels / 2)) / (levels / 2)
    if decim and int(decim) > 1:
        d = int(decim)
        n = (len(x) // d) * d
        if n >= d:
            held = np.repeat(x[:n:d], d)
            x = np.concatenate([held, x[n:]])[:len(x)]
    return x.astype(np.float32)


def hard_clip(x, amount=4.0):
    """Clip, don't saturate. tanh is polite; this is the other thing."""
    if amount <= 1.0:
        return x
    pk = np.abs(x).max() + 1e-9
    return (np.clip(x * amount / pk, -1.0, 1.0) * pk).astype(np.float32)


def stutter(x, n, slot_samples):
    """Retrigger a sample n times inside its slot."""
    n = int(n)
    if n < 2 or slot_samples < 64:
        return x
    seg = max(64, int(slot_samples / n))
    piece = x[:seg].copy()
    f = min(int(0.004 * SR), len(piece) // 4)
    if f > 1:
        piece[:f] *= np.linspace(0, 1, f)
        piece[-f:] *= np.linspace(1, 0, f)
    return np.tile(piece, n).astype(np.float32)


def duck_envelope(onsets, n, depth=0.75, release=0.18, hold=0.012):
    """Sidechain gain curve built from known note onsets.

    The score already says where the kick is, so the pump can be derived from
    the notation instead of detected back out of the audio.
    """
    g = np.ones(n, np.float32)
    rel = max(int(release * SR), 32)
    shape = 1.0 - depth * np.exp(-np.arange(rel) / (rel / 4.0))
    hd = int(hold * SR)
    for o in onsets:
        s = int(o * SR)
        if s >= n:
            continue
        if hd:
            g[s:min(n, s + hd)] = np.minimum(g[s:min(n, s + hd)], 1.0 - depth)
        a = min(n, s + hd)
        b = min(n, a + rel)
        if b > a:
            g[a:b] = np.minimum(g[a:b], shape[:b - a])
    return g


def sweep_filter(x, f_start, f_end, btype, order=4, block=256):
    """Block-wise IIR with interpolated cutoff; filter state carried across
    coefficient updates. Cheap and stable for audio-rate sweeps."""
    nyq = SR / 2.0
    f_start = float(np.clip(f_start, 20.0, nyq * 0.97))
    f_end = float(np.clip(f_end, 20.0, nyq * 0.97))
    if abs(f_start - f_end) < 1.0:
        sos = sig.butter(order, f_start / nyq, btype=btype, output="sos")
        return sig.sosfilt(sos, x).astype(np.float32)
    out = np.empty_like(x)
    n = len(x)
    zi = None
    for s in range(0, n, block):
        e = min(n, s + block)
        frac = (s + (e - s) / 2) / max(n, 1)
        f = math.exp(math.log(f_start) + frac * (math.log(f_end) - math.log(f_start)))
        sos = sig.butter(order, np.clip(f, 20.0, nyq * 0.97) / nyq,
                         btype=btype, output="sos")
        if zi is None:
            zi = sig.sosfilt_zi(sos) * x[s]
        y, zi = sig.sosfilt(sos, x[s:e], zi=zi)
        out[s:e] = y
    return out.astype(np.float32)


def pan_stereo(x, p0, p1):
    """Equal-power pan; p in [-1, 1]. Interpolated for sweeps."""
    p = np.full(len(x), p0, dtype=np.float32) if abs(p0 - p1) < 1e-6 \
        else np.linspace(p0, p1, len(x)).astype(np.float32)
    theta = (np.clip(p, -1, 1) + 1.0) * (math.pi / 4.0)
    return x * np.cos(theta), x * np.sin(theta)


def make_ir(seconds=2.6, seed=7):
    """Synthetic stereo reverb impulse: decorrelated noise under an
    exponential envelope, progressively darkened. Enough for a field-recording
    space without dragging in a convolution library."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    env = np.exp(-4.2 * t / seconds)
    ir = rng.standard_normal((2, n)).astype(np.float32) * env
    sos = sig.butter(2, 5200 / (SR / 2), btype="low", output="sos")
    ir = np.stack([sig.sosfilt(sos, ch) for ch in ir]).astype(np.float32)
    pre = int(0.018 * SR)
    ir = np.concatenate([np.zeros((2, pre), np.float32), ir], axis=1)
    # Normalise to unit ENERGY, not unit peak. A 2.6 s noise impulse peak-
    # normalised carries ~30 dB of convolution gain, which turns any sane-
    # looking send into a wash that swallows note articulation and collapses
    # pan gestures toward centre.
    ir /= np.sqrt((ir ** 2).sum(axis=1, keepdims=True)) + 1e-9
    return (ir * 0.9).astype(np.float32)


def soft_clip(x, drive=1.0):
    return np.tanh(x * drive) / math.tanh(drive) if drive > 1.001 else x


def master(x, target_rms_db=-17.0, ceiling=0.89):
    """Bring a render to a sane listening level.

    Peak-normalising alone leaves this material ~24 dB down: birdcalls are
    almost all transient, so crest factor is enormous and the peaks spend the
    headroom that the body of the piece needs. Pre-gain toward an RMS target,
    then a smoothed look-ahead limiter to catch what that pushes over.
    """
    from scipy.ndimage import maximum_filter1d
    rms = float(np.sqrt((x ** 2).mean()) + 1e-12)
    x = x * (10 ** ((target_rms_db - 20 * math.log10(rms)) / 20.0))

    env = maximum_filter1d(np.abs(x).max(axis=0), size=int(0.02 * SR) | 1)
    g = np.minimum(1.0, ceiling / (env + 1e-9))
    w = np.hanning(int(0.03 * SR) | 1)
    g = sig.fftconvolve(g, w / w.sum(), mode="same")
    x = x * g

    x = np.tanh(x * 1.08) * 0.95
    return (x * ((10 ** (-1.0 / 20)) / (np.abs(x).max() + 1e-9))).astype(np.float32)


# ------------------------------------------------------------------- the pack

@dataclass
class Sample:
    path: Path
    f0_hz: float
    audio: np.ndarray = None

    def load(self):
        if self.audio is None:
            y, _ = librosa.load(str(self.path), sr=SR, mono=True)
            self.audio = y.astype(np.float32)
        return self.audio


@dataclass
class Voice:
    abbrev: str
    name: str
    samples: list
    mode: str = "varispeed"
    gain_db: float = 0.0
    pan: float = 0.0
    send: float = 0.12
    root_hz: float = 0.0        # fallback when a sample has no measured pitch
    # Any other params on the instrument line become per-track defaults, so a
    # drum voice can declare its whole character once instead of on every hit.
    defaults: dict = field(default_factory=dict)


STRUCTURAL_PARAMS = {"voice", "sample", "root", "mode", "gain", "pan",
                     "send", "duck"}


def load_pack(path: Path):
    data = json.load(open(path))
    base = path.parent
    out = {}
    for vname, v in data.get("voices", {}).items():
        out[vname] = [Sample(base / s["file"], float(s.get("f0_hz") or 0.0))
                      for s in v["samples"]]
    for nname, nd in data.get("noise", {}).items():
        out[nname] = [Sample(base / nd["file"], 0.0)]
    return out


# ------------------------------------------------------------- token grammar

@dataclass
class Note:
    kind: str                    # note / chord / rest / unpitched / dynamic / hairpin
    midis: list = field(default_factory=list)
    ql: float = 0.0
    params: dict = field(default_factory=dict)
    flags: set = field(default_factory=set)
    dyn: str = None
    gliss_midi: float = None


RE_ART = re.compile(r"\[([^\]]*)\]")


def duration_ql(codes):
    total = 0.0
    for c in codes:
        d = mus.parse_duration_code(c)
        if d is not None:
            total += float(d.quarterLength)
    return total


def parse_token(tok: str):
    """Parse one extended MUS event token."""
    raw = tok
    tok = tok.strip()
    if not tok:
        return None
    tok = tok.lstrip("(").rstrip(")")
    tok = re.sub(r'\s*"[^"]*"', "", tok)          # lyrics are silent here

    if tok in ("{<}", "{>}", "{|}"):
        return Note(kind="hairpin", dyn={"{<}": "cresc", "{>}": "dim",
                                         "{|}": "end"}[tok])
    if tok.startswith("{") and tok.endswith("}"):
        return Note(kind="dynamic", dyn=tok[1:-1].strip())
    if tok == "-":
        return None

    params, flags = {}, set()
    m = RE_ART.search(tok)
    if m:
        for item in m.group(1).split(","):
            item = item.strip()
            if not item:
                continue
            if "=" in item:
                k, v = item.split("=", 1)
                params[k.strip().lower()] = v.strip()
            else:
                flags.add(item.lower())
        tok = tok[:m.start()] + tok[m.end():]

    # spec-form glissando: A6q->C7  (a trailing duration on the target is ignored)
    gliss = None
    if "->" in tok:
        tok, tgt = tok.split("->", 1)
        gm = re.match(rf"^({RE_PITCH_HEAD})", tgt.strip())
        if gm:
            gliss = note_to_midi(gm.group(1))
    if "gliss" in params:
        gliss = note_to_midi(params.pop("gliss"))

    if tok.startswith("<"):
        close = tok.find(">")
        pitches = [note_to_midi(p) for p in tok[1:close].split()]
        pitches = [p for p in pitches if p is not None]
        ql = duration_ql(tok[close + 1:].split("~"))
        return Note("chord", pitches, ql, params, flags, gliss_midi=gliss)

    if tok.startswith("R"):
        return Note("rest", [], duration_ql(tok[1:].split("~")) if tok[1:] else 0.0,
                    params, flags)

    if tok.startswith("X"):
        return Note("unpitched", [], duration_ql(tok[1:].split("~")) if tok[1:] else 1.0,
                    params, flags, gliss_midi=gliss)

    pm = re.match(rf"^({RE_PITCH_HEAD})(.*)$", tok)
    if not pm:
        return None
    midi = note_to_midi(pm.group(1))
    if midi is None:
        return None
    ql = duration_ql(pm.group(2).split("~")) or 1.0
    return Note("note", [midi], ql, params, flags, gliss_midi=gliss)


def param_pair(params, key, default):
    """A param may be a scalar or a 'a->b' sweep. Always returns (start, end)."""
    if key not in params:
        return default, default
    v = str(params[key])
    if "->" in v:
        a, b = v.split("->", 1)
        try:
            return float(a), float(b)
        except ValueError:
            return default, default
    try:
        return float(v), float(v)
    except ValueError:
        return default, default


# ---------------------------------------------------------------- the render

def render(score_path: Path, out_path: Path, verbose=True):
    text = score_path.read_text()
    parsed = mus.parse_mus(text)

    a4 = 440.0
    tun = parsed.extra.get("tuning", "")
    tm = re.search(r"A\s*=\s*([\d.]+)", tun)
    if tm:
        a4 = float(tm.group(1))

    pack_ref = parsed.extra.get("pack")
    pack = load_pack((score_path.parent / pack_ref).resolve()) if pack_ref else {}

    voices = {}
    for inst in parsed.instruments:
        p = inst.params
        vkey = p.get("voice")
        samples = []
        if vkey and vkey in pack:
            samples = list(pack[vkey])
        if "sample" in p:
            sp = (score_path.parent / p["sample"]).resolve()
            samples = [Sample(sp, 0.0)]
        if not samples:
            print(f"  ! no samples for track '{inst.abbrev}' — skipped", file=sys.stderr)
            continue
        if "root" in p:
            rm = note_to_midi(p["root"])
            root_hz = midi_to_hz(rm, a4) if rm else 0.0
            for s in samples:
                if s.f0_hz <= 0:
                    s.f0_hz = root_hz
        voices[inst.abbrev] = Voice(
            abbrev=inst.abbrev, name=inst.name, samples=samples,
            mode=p.get("mode", "varispeed"),
            gain_db=float(p.get("gain", 0.0)),
            pan=float(p.get("pan", 0.0)),
            send=float(p.get("send", 0.12)),
            defaults={k: v for k, v in p.items() if k not in STRUCTURAL_PARAMS},
        )

    # ---- bar → seconds map
    tempo_at = {b: v for b, v in parsed.tempo_changes}
    time_at = {b: v for b, v in parsed.time_changes}
    for mb in parsed.bars:
        for c in mb.inline_changes:
            if "=" not in c:
                continue
            k, v = (s.strip() for s in c.split("=", 1))
            if k.lower() == "tempo":
                try:
                    tempo_at[mb.bar_num] = int(v)
                except ValueError:
                    pass
            elif k.lower() == "time":
                time_at[mb.bar_num] = v

    n_bars = parsed.bar_count
    tempo, tsig = tempo_at.get(1, 96), time_at.get(1, "4/4")
    bar_start, bar_qlen, bar_spq = {}, {}, {}
    t = 0.0
    for b in range(1, n_bars + 1):
        tempo = tempo_at.get(b, tempo)
        tsig = time_at.get(b, tsig)
        num, den = (int(x) for x in tsig.split("/"))
        qlen = num * 4.0 / den
        spq = 60.0 / tempo
        bar_start[b], bar_qlen[b], bar_spq[b] = t, qlen, spq
        t += qlen * spq
    total_s = t + 4.0

    n_total = int(total_s * SR)
    wet = np.zeros((2, n_total), np.float32)

    # `# sidechain: <track> depth=0.75 rel=0.16` — the pump. Derived from the
    # trigger track's notated onsets, not detected from the audio.
    sc_track, sc_depth, sc_rel = None, 0.75, 0.16
    if "sidechain" in parsed.extra:
        bits = parsed.extra["sidechain"].split()
        if bits:
            sc_track = bits[0]
        for bit in bits[1:]:
            if "=" in bit:
                k, v = bit.split("=", 1)
                try:
                    if k.strip() == "depth":
                        sc_depth = float(v)
                    elif k.strip() in ("rel", "release"):
                        sc_rel = float(v)
                except ValueError:
                    pass
    sc_onsets = []
    placed = []          # (track, start, L, R, send, db) — mixed after all tracks

    bar_content = {}
    for mb in parsed.bars:
        for b in range(mb.bar_num, mb.end_bar + 1):
            bar_content[b] = mb.track_content

    stats = {"notes": 0, "skipped": 0}

    for abbr, voice in voices.items():
        cur_dyn = "mf"
        hairpin = None            # (start_index_in_pending, direction)
        pending = []              # (sample_index_into_buffers, base_db)

        for b in range(1, n_bars + 1):
            content = bar_content.get(b, {}).get(abbr, "")
            if not content or content.strip() == "-":
                continue
            toks = mus.expand_pattern_repetitions(mus.tokenize_bar_content(content))
            q_off = 0.0
            for tk in toks:
                ev = parse_token(tk)
                if ev is None:
                    continue
                if voice.defaults:
                    ev.params = {**voice.defaults, **ev.params}

                if ev.kind == "dynamic":
                    cur_dyn = ev.dyn
                    continue
                if ev.kind == "hairpin":
                    if ev.dyn in ("cresc", "dim"):
                        hairpin = (len(pending), ev.dyn)
                    else:
                        if hairpin:
                            i0, d = hairpin
                            span = pending[i0:]
                            for k, item in enumerate(span):
                                amt = (k / max(len(span) - 1, 1)) * (9.0 if d == "cresc" else -9.0)
                                item[1] += amt
                            hairpin = None
                    continue
                if ev.kind == "rest":
                    q_off += ev.ql
                    continue

                onset = bar_start[b] + q_off * bar_spq[b]
                slot = max(ev.ql * bar_spq[b], 1e-3)
                q_off += ev.ql

                # --- sample choice
                si = int(float(ev.params.get("s", 1))) - 1
                si = max(0, min(si, len(voice.samples) - 1))
                smp = voice.samples[si]
                x = smp.load().copy()
                if "off" in ev.params:
                    o = int(float(ev.params["off"]) * SR / 1000.0)
                    x = x[min(o, max(len(x) - 64, 0)):]
                if "reverse" in ev.flags:
                    x = x[::-1].copy()
                if len(x) < 32:
                    stats["skipped"] += 1
                    continue

                # --- transposition
                mode = ev.params.get("mode", voice.mode)
                st = 0.0
                st_end = None
                if ev.kind in ("note", "chord") and smp.f0_hz > 0:
                    st = 12 * math.log2(midi_to_hz(ev.midis[0], a4) / smp.f0_hz)
                    if ev.gliss_midi is not None:
                        st_end = 12 * math.log2(midi_to_hz(ev.gliss_midi, a4) / smp.f0_hz)
                elif ev.kind == "unpitched":
                    st, _ = param_pair(ev.params, "st", 0.0)
                    _, st_end2 = param_pair(ev.params, "st", 0.0)
                    st_end = st_end2 if abs(st_end2 - st) > 1e-6 else None

                curve = ev.params.get("curve", "lin")
                tau = float(ev.params.get("tau", 0.045))
                if st_end is not None:
                    x = pitch_ramp(x, st, st_end, curve, tau)
                elif mode == "vocoder":
                    x = vocode(x, st)
                else:
                    x = varispeed(x, st)

                # --- time treatment
                if ev.params.get("str") == "fit":
                    x = stretch(x, slot / max(len(x) / SR, 1e-4))
                elif "str" in ev.params:
                    try:
                        x = stretch(x, float(ev.params["str"]))
                    except ValueError:
                        pass

                cut = None
                for a_name, f in ART_SHORTEN.items():
                    if a_name in ev.flags:
                        cut = slot * f
                if "gate" in ev.flags:
                    cut = min(cut or slot, slot)
                if "fer" in ev.flags:
                    x = stretch(x, 1.75)
                if cut is not None:
                    nkeep = max(64, int(cut * SR))
                    if len(x) > nkeep:
                        x = x[:nkeep]

                # --- envelope
                atk = int(max(0.0015, float(ev.params.get("atk", 0.003))) * SR)
                rel = int(max(0.004, float(ev.params.get("rel", 0.035))) * SR)
                atk, rel = min(atk, len(x) // 3), min(rel, len(x) // 2)
                if atk > 1:
                    x[:atk] *= np.linspace(0, 1, atk) ** 0.7
                if rel > 1:
                    x[-rel:] *= np.linspace(1, 0, rel) ** 1.5

                # --- filters
                if "lpf" in ev.params:
                    f0, f1 = param_pair(ev.params, "lpf", 20000)
                    x = sweep_filter(x, f0, f1, "low")
                if "hpf" in ev.params:
                    f0, f1 = param_pair(ev.params, "hpf", 20)
                    x = sweep_filter(x, f0, f1, "high")
                if "drive" in ev.params:
                    x = soft_clip(x, float(ev.params["drive"]))
                if "dist" in ev.params:
                    x = hard_clip(x, float(ev.params["dist"]))
                if "crush" in ev.params or "decim" in ev.params:
                    x = bitcrush(x, ev.params.get("crush"), ev.params.get("decim"))
                if "stut" in ev.params:
                    x = stutter(x, float(ev.params["stut"]), int(slot * SR))

                # --- level
                db = DYN_DB.get(cur_dyn, -11.0) + voice.gain_db
                for a_name, g in ART_GAIN.items():
                    if a_name in ev.flags:
                        db += g
                db += float(ev.params.get("gain", 0.0))

                # --- place
                start = int(onset * SR)
                if start >= n_total:
                    continue
                x = x[:max(0, n_total - start)]
                if len(x) < 32:
                    continue

                p0, p1 = param_pair(ev.params, "pan", voice.pan)
                L, R = pan_stereo(x, p0, p1)
                send = float(ev.params.get("send", voice.send))

                if abbr == sc_track:
                    sc_onsets.append(onset)
                pending.append([(start, L, R, send), db])
                stats["notes"] += 1

        if hairpin:
            i0, d = hairpin
            span = pending[i0:]
            for k, item in enumerate(span):
                item[1] += (k / max(len(span) - 1, 1)) * (9.0 if d == "cresc" else -9.0)

        ducks = voices[abbr] is not None and \
            str(next((i.params.get("duck", "1") for i in parsed.instruments
                      if i.abbrev == abbr), "1")) not in ("0", "no", "off")
        for (start, L, R, send), db in pending:
            placed.append((abbr, ducks, start, L, R, send, 10 ** (db / 20.0)))

    # ---- mixdown, with the pump applied to ducking tracks
    dry = np.zeros((2, n_total), np.float32)
    duck = (duck_envelope(sc_onsets, n_total, sc_depth, sc_rel)
            if sc_track and sc_onsets else None)
    for abbr, ducks, start, L, R, send, g in placed:
        end = start + len(L)
        dl, dr = L * g, R * g
        if duck is not None and ducks and abbr != sc_track:
            d = duck[start:end]
            dl, dr = dl * d, dr * d
        dry[0, start:end] += dl
        dry[1, start:end] += dr
        if send > 0:
            wet[0, start:end] += dl * send
            wet[1, start:end] += dr * send
    if duck is not None:
        print(f"  sidechain: {len(sc_onsets)} hits from '{sc_track}' "
              f"depth {sc_depth} rel {sc_rel}s")

    # ---- reverb + master
    ir = make_ir()
    rev = np.stack([sig.fftconvolve(wet[c], ir[c])[:n_total] for c in range(2)])
    out = dry + rev.astype(np.float32)

    sos = sig.butter(2, 28 / (SR / 2), btype="high", output="sos")
    out = np.stack([sig.sosfilt(sos, ch) for ch in out]).astype(np.float32)
    mtgt = -17.0
    mm = re.search(r"rms\s*=\s*(-?[\d.]+)", parsed.extra.get("master", ""))
    if mm:
        mtgt = float(mm.group(1))
    out = master(out, target_rms_db=mtgt)

    sf.write(str(out_path), out.T, SR, subtype="PCM_24")
    if verbose:
        rms = float(np.sqrt((out ** 2).mean()))
        print(f"{score_path.name}: {stats['notes']} events, "
              f"{len(voices)} voices, {total_s:.1f}s, A={a4:.1f} Hz")
        print(f"wrote {out_path}  peak -1.0 dBFS  rms {20*math.log10(rms+1e-12):.1f} dBFS")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Render MUS to audio via a sample pack.")
    ap.add_argument("score", help="path to .mus score")
    ap.add_argument("-o", "--output", default=None, help="output .wav")
    args = ap.parse_args()
    sp = Path(args.score)
    op = Path(args.output) if args.output else sp.with_suffix(".wav")
    render(sp, op)
    return 0


if __name__ == "__main__":
    sys.exit(main())
