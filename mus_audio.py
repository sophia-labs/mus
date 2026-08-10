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

    def ramp(n):
        if curve == "exp":
            return st1 + (st0 - st1) * np.exp(-(np.arange(n) / SR) / max(tau, 1e-4))
        return np.linspace(st0, st1, n)

    # Solve for the output length whose integrated read rate consumes exactly
    # the sample. Laying the ramp over a fixed estimate and then dropping the
    # samples that overrun truncates the glide partway: a notated +12 st
    # delivered +6.1, a +24 delivered +8.4. Two rescalings converge, and the
    # iteration handles the exponential curve as well as the linear one.
    n_out = max(16, int(n_in / (2.0 ** (min(st0, st1) / 12.0))))
    for _ in range(3):
        total = float(np.sum(2.0 ** (ramp(n_out) / 12.0)))
        if total <= 1e-9:
            break
        n_out = max(16, int(n_out * (n_in - 1) / total))

    pos = np.cumsum(2.0 ** (ramp(n_out) / 12.0))
    pos = np.clip(pos, 0.0, n_in - 1.0)
    if len(pos) < 8:
        return varispeed(x, st1)
    return np.interp(pos, np.arange(n_in), x).astype(np.float32)


def pitch_polyline(x, t_anchor, st_anchor):
    """Continuous varispeed along a measured pitch polyline.

    This is `->` generalised one more step: pitch_ramp draws a line between
    two pitches; a gesture quotation follows the polyline an analysis actually
    measured. The gesture defines the duration — the sample is tape material
    read through at the trajectory's varying rate, and if the gesture wants
    more sample than exists, the quote fades where the tape runs out rather
    than inventing material.
    """
    n_in = len(x)
    if n_in < 8 or len(t_anchor) < 2:
        return x
    dur = float(t_anchor[-1]) - float(t_anchor[0])
    n_out = max(16, int(dur * SR))
    tt = np.linspace(t_anchor[0], t_anchor[-1], n_out)
    st = np.interp(tt, t_anchor, st_anchor)
    rate = 2.0 ** (st / 12.0)
    pos = np.cumsum(rate) - rate[0]
    valid = pos <= (n_in - 1)
    pos = np.clip(pos, 0.0, n_in - 1.0)
    y = np.interp(pos, np.arange(n_in), x).astype(np.float32)
    if not valid.all():
        k = max(int(valid.sum()), 0)
        f = min(k, int(0.010 * SR))
        if f > 1:
            y[k - f:k] *= np.linspace(1, 0, f).astype(np.float32)
        y[k:] = 0.0
    return y


def load_gestures(path: Path):
    """Load consensus contours from an aigua-sweep-events file.

    Returns {key: {"resolved": [(t, hz)...], "octave": [(t, hz)...],
    "median_hz": float}} keyed three ways: full hypothesis id, `h<index>` in
    file order, and the sha256 segment hash (matched by unique prefix at
    lookup). Only frames the consensus actually emitted are used: the
    resolved layer is the r-frames, the octave layer is the o-frames'
    octave-equivalent candidates. Nothing is invented for disagreement
    frames — a quote can only play what the ensemble agreed it heard.
    """
    data = json.load(open(path))
    events = data.get("events", data if isinstance(data, list) else [])
    out = {}
    for i, e in enumerate(events):
        contour = e.get("contour")
        if not contour:
            continue
        resolved = [(r[0], r[1]) for r in contour if r[2] == "r" and r[1]]
        octave = [(r[0], r[3]) for r in contour if r[2] == "o" and len(r) > 3 and r[3]]
        ref = resolved or octave
        if len(ref) < 2:
            continue
        med = sorted(hz for _, hz in ref)[len(ref) // 2]
        rec = {"resolved": resolved, "octave": octave, "median_hz": med,
               "t0": e.get("start_seconds"), "t1": e.get("end_seconds"),
               "id": e.get("hypothesis_id", f"h{i}")}
        out[f"h{i}"] = rec
        hid = e.get("hypothesis_id")
        if hid:
            out[hid] = rec
            m = re.search(r"sha256:([0-9a-f]+)", hid)
            if m:
                out.setdefault(m.group(1), rec)
    return out


def lookup_gesture(gestures: dict, key: str):
    if key in gestures:
        return gestures[key]
    hits = [v for k, v in gestures.items()
            if len(key) >= 6 and k.startswith(key) and not k.startswith("h")]
    if len(hits) == 1:
        return hits[0]
    return None


SYNTH_KEYS = {"synth", "osc2", "mix2", "detune", "sub", "cutoff",
              "famt", "fdec", "satk", "sdec", "ssus", "srel"}


def _osc(wave: str, phase: np.ndarray) -> np.ndarray:
    frac = phase - np.floor(phase)
    if wave == "square":
        return np.where(frac < 0.5, 1.0, -1.0).astype(np.float32)
    if wave == "tri":
        return (2.0 * np.abs(2.0 * frac - 1.0) - 1.0).astype(np.float32)
    if wave == "sine":
        return np.sin(2 * np.pi * frac).astype(np.float32)
    return (2.0 * frac - 1.0).astype(np.float32)          # saw


def synth_note(patch: dict, freqs_hz, slot_s: float, gliss_ratio: float = 1.0):
    """A small subtractive synth: osc1 + detuned copy + optional osc2 and
    sub-oscillator, ADSR, and a downward filter sweep standing in for a
    filter envelope. Deterministic, unapologetically simple — a funk box,
    not a workstation. Chords render all tones; a gliss target sweeps every
    tone by the same ratio (synth portamento is a frequency ramp, not a
    resample, so there is no tape artifact)."""
    satk = float(patch.get("satk", 0.004))
    sdec = float(patch.get("sdec", 0.05))
    ssus = float(patch.get("ssus", 0.75))
    srel = float(patch.get("srel", 0.12))
    n = max(64, int((slot_s + srel) * SR))
    t = np.arange(n, dtype=np.float32) / SR
    wave = str(patch.get("synth", "saw"))
    osc2 = patch.get("osc2")
    mix2 = float(patch.get("mix2", 0.5))
    det = float(patch.get("detune", 0.0))          # cents
    sub = float(patch.get("sub", 0.0))
    out = np.zeros(n, np.float32)
    for f in freqs_hz:
        ramp = np.linspace(1.0, gliss_ratio, n).astype(np.float32) if abs(gliss_ratio - 1.0) > 1e-6 else 1.0
        freq = f * ramp
        phase = np.cumsum(freq) / SR
        tone = _osc(wave, phase)
        if det > 0:
            r = 2.0 ** (det / 1200.0)
            tone = tone + _osc(wave, np.cumsum(freq * r) / SR) \
                        + _osc(wave, np.cumsum(freq / r) / SR)
            tone /= 3.0
        if osc2:
            tone = (1.0 - mix2) * tone + mix2 * _osc(str(osc2), np.cumsum(freq) / SR * 2.0)
        if sub > 0:
            tone = tone + sub * _osc("sine", np.cumsum(freq * 0.5) / SR)
        out += tone
    out /= math.sqrt(max(len(freqs_hz), 1))
    # ADSR: attack, decay to sustain, hold to the slot, release beyond it
    env = np.full(n, ssus, np.float32)
    na, nd = max(int(satk * SR), 1), max(int(sdec * SR), 1)
    env[:na] = np.linspace(0, 1, na)
    if n > na:
        nd2 = min(nd, n - na)
        env[na:na + nd2] = np.linspace(1, ssus, nd2)
    ns = int(slot_s * SR)
    if ns < n:
        env[ns:] = env[min(ns, n - 1)] * np.linspace(1, 0, n - ns) ** 1.4
    out *= env
    cutoff = float(patch.get("cutoff", 4200.0))
    famt = float(patch.get("famt", 0.0))
    if famt > 0:
        out = sweep_filter(out, cutoff + famt, cutoff, "low")
    else:
        out = sweep_filter(out, cutoff, cutoff, "low")
    return (out * 0.5).astype(np.float32)


def chop_shuffle(x: np.ndarray, n_grains: int, slot_samples: int) -> np.ndarray:
    """Granular resequence: cut the material into n grains and deal them
    back evens-first, every fourth grain reversed. Deterministic — the same
    token always renders the same scatter. The bird becomes a drummer."""
    n_grains = max(2, min(int(n_grains), 64))
    seg = max(len(x) // n_grains, 64)
    grains = [x[i * seg:(i + 1) * seg].copy() for i in range(n_grains)]
    order = list(range(0, n_grains, 2)) + list(range(1, n_grains, 2))
    f = min(int(0.004 * SR), seg // 4)
    outs = []
    for j, gi in enumerate(order):
        g = grains[gi]
        if j % 4 == 3:
            g = g[::-1].copy()
        if f > 1:
            g[:f] *= np.linspace(0, 1, f, dtype=np.float32)
            g[-f:] *= np.linspace(1, 0, f, dtype=np.float32)
        outs.append(g)
    y = np.concatenate(outs)
    return y[:max(slot_samples, seg)] if len(y) > max(slot_samples, seg) else y


def ring_mod(x: np.ndarray, f_hz: float, wet: float = 1.0) -> np.ndarray:
    """Multiply by a sine — inharmonic sidebands, the classic weird-ifier."""
    car = np.sin(2 * np.pi * f_hz * np.arange(len(x)) / SR).astype(np.float32)
    return ((1.0 - wet) * x + wet * x * car).astype(np.float32)


def glow_chain(x, st_g, params, slot_samples):
    """Hyperpop candy chain. The un-birding move is the HOLD: loop the
    loudest slice of the call to the notated slot. Birds cannot sustain a
    pitch (median FM velocity 11 st/s, by our own measurement); holding one
    is the most artificial thing this material can do. Then the coating:
    micro-detuned doubles for ensemble shine, a +24 sparkle, plastic
    bitcrush, dense saturation, beat-synced pump."""
    if str(params.get("ghold", "0")) not in ("0", "off"):
        win = int(0.07 * SR)
        if len(x) > 2 * win:
            e = np.convolve(np.abs(x), np.ones(win) / win, mode="valid")
            piece = x[int(np.argmax(e)):int(np.argmax(e)) + win].copy()
            f = int(0.015 * SR)
            w = np.ones(win, np.float32)
            w[:f] = np.linspace(0, 1, f)
            w[-f:] = np.linspace(1, 0, f)
            n_out = max(slot_samples, win)
            held = np.zeros(n_out + win, np.float32)
            pos = 0
            while pos < n_out:
                held[pos:pos + win] += piece * w
                pos += win - f
            x = held[:n_out]
    if "gwarble" in params:
        # autotune-artifact trill: square-LFO crossfade between the tone
        # and itself a semitone up. Robots only.
        wr = float(params["gwarble"])
        up = vocode(x, 1.0)
        n_w = min(len(x), len(up))
        tt = np.arange(n_w, dtype=np.float32) / SR
        lfo = ((tt * wr) % 1.0) < 0.5
        x = np.where(lfo, x[:n_w], up[:n_w]).astype(np.float32)
    # `gharm=0+4+7+12` — the harmonizer glued to the voice: every note
    # becomes a parallel chord of itself, weights falling 0.85 per layer,
    # root layer micro-detuned.
    try:
        ivs = [float(t) for t in
               str(params.get("gharm", "0")).replace("|", "+").split("+") if t]
    except ValueError:
        ivs = [0.0]
    y = np.zeros(len(x), np.float32)
    w = 1.0
    for j, iv in enumerate(ivs):
        layer = vocode(x, st_g + iv)
        if j == 0:
            layer = (0.6 * layer
                     + 0.2 * vocode(x, st_g + iv + 0.15)
                     + 0.2 * vocode(x, st_g + iv - 0.15))
        y[:len(layer)] += w * layer[:len(y)]
        w *= 0.85
    y /= math.sqrt(max(len(ivs), 1))
    y = sweep_filter(y, 600.0, 600.0, "high")
    y = sweep_filter(y, 7800.0, 7800.0, "low")
    y = bitcrush(y, bits=10)
    y = np.tanh(y * 2.4) / math.tanh(2.4)
    pump = float(params.get("pump", 0.0))
    if pump > 0:
        tt = np.arange(len(y), dtype=np.float32) / SR
        ph = (tt * pump) % 1.0
        y *= (0.45 + 0.55 * np.exp(-3.5 * ph)).astype(np.float32)
    return y.astype(np.float32)


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
    # Land on the requested RMS, bounded by the peak ceiling. Neither half of
    # this is optional: normalising peak unconditionally lets crest factor
    # decide the level and silently overrides `# master: rms=` (a -20 target
    # came out at -17.8), while pre-gain alone undershoots it by however much
    # the limiter then removed (-17 came out at -18.3).
    ceil_lin = 10 ** (-1.0 / 20)
    cur = float(np.sqrt((x ** 2).mean()) + 1e-12)
    want = 10 ** ((target_rms_db - 20 * math.log10(cur)) / 20.0)
    allowed = ceil_lin / (float(np.abs(x).max()) + 1e-9)
    return (x * min(want, allowed)).astype(np.float32)


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
    synth: dict = None          # a `synth=` instrument generates instead of sampling


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


RE_TRAILING_DYN = re.compile(r"\{([^}]*)\}$")


def split_attached_dynamics(tokens):
    """Detach a dynamic written onto a note into its own preceding token.

    SPEC.md writes dynamics attached to notes — `D2q{mp} D2q D2q D2q{<}`.
    Left joined, the whole thing fails to parse as a duration and the note is
    dropped: every riser in the gecs score was silent for exactly this reason.
    The tuplet form `q{5:6}` also ends in a brace group, so exclude it.
    """
    out = []
    for t in tokens:
        if not t.startswith("{") and not t.startswith("("):
            m = RE_TRAILING_DYN.search(t)
            if m and m.start() > 0 and not re.fullmatch(r"\d+:\d+", m.group(1)):
                out.append("{" + m.group(1).strip() + "}")
                out.append(t[:m.start()])
                continue
        out.append(t)
    return out


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

    # `# gestures: <path>` — measured consensus contours available for
    # quotation via `gest=`. Rides ParsedMus.extra like `pack`/`tuning`.
    gest_ref = parsed.extra.get("gestures")
    gestures = load_gestures((score_path.parent / gest_ref).resolve()) if gest_ref else {}

    # `# tape: <path>` — the source recording itself, for `gsrc=raw` quotes:
    # a quoted event plays its own slice of the tape (the bird's actual voice)
    # rather than a pack sample bent along the contour.
    tape_audio = None
    tape_ref = parsed.extra.get("tape")
    if tape_ref:
        tape_audio, _ = librosa.load(
            str((score_path.parent / tape_ref).resolve()), sr=SR, mono=True)
        tape_audio = tape_audio.astype(np.float32)

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
        synth_patch = {k: p[k] for k in SYNTH_KEYS if k in p} if "synth" in p else None
        if not samples and synth_patch is None:
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
            defaults={k: v for k, v in p.items()
                      if k not in STRUCTURAL_PARAMS and k not in SYNTH_KEYS},
            synth=synth_patch,
        )

    # `# swing: [unit] percent` — MPC-style swing: every second grid position
    # at the given subdivision is delayed so the pair divides percent/(100-
    # percent) instead of 50/50. `# swing: 16 56` is a classic light pocket.
    # Onsets shift; notated durations and bar accounting stay on the grid.
    swing_unit_ql, swing_r = 0.0, 0.5
    swm = parsed.extra.get("swing", "").split()
    if swm:
        try:
            unit, pct = (int(swm[0]), float(swm[1])) if len(swm) > 1 else (16, float(swm[0]))
            swing_unit_ql = 4.0 / unit
            swing_r = min(0.75, max(0.5, pct / 100.0))
        except (ValueError, ZeroDivisionError):
            pass

    def swung(q_pos: float) -> float:
        if swing_unit_ql <= 0 or swing_r <= 0.5:
            return q_pos
        k = int(q_pos / swing_unit_ql + 1e-6)
        if k % 2 == 1 and abs(q_pos - k * swing_unit_ql) < 1e-6:
            return q_pos + swing_unit_ql * (2.0 * swing_r - 1.0)
        return q_pos

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
    dry = np.zeros((2, n_total), np.float32)

    def mix_one(start, L, R, send, g, duck_env=None):
        end = start + len(L)
        dl, dr = L * g, R * g
        if duck_env is not None:
            d = duck_env[start:end]
            dl, dr = dl * d, dr * d
        dry[0, start:end] += dl
        dry[1, start:end] += dr
        if send > 0:
            wet[0, start:end] += dl * send
            wet[1, start:end] += dr * send

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
    # A sidechain needs every trigger onset before anything can be ducked, so
    # note audio must be held until the end. Without one there is no such
    # dependency, and holding it is what makes a 15-minute score run out of
    # memory — so flush to the bus at every bar line instead.
    eager = sc_track is None

    bar_content = {}
    for mb in parsed.bars:
        for b in range(mb.bar_num, mb.end_bar + 1):
            bar_content[b] = mb.track_content

    stats = {"notes": 0, "skipped": 0, "bad": []}

    for abbr, voice in voices.items():
        cur_dyn = "mf"
        hairpin = None            # (start_index_in_pending, direction)
        pending = []              # (sample_index_into_buffers, base_db)

        for b in range(1, n_bars + 1):
            content = bar_content.get(b, {}).get(abbr, "")
            if not content or content.strip() == "-":
                continue
            toks = split_attached_dynamics(
                    mus.expand_pattern_repetitions(mus.tokenize_bar_content(content)))
            q_off = 0.0
            for tk in toks:
                ev = parse_token(tk)
                if ev is None:
                    # Silently dropping unparseable tokens hides typos that
                    # shift a whole bar's timing. A homoglyph in a duration
                    # ('Rе' with a Cyrillic e) cost two debugging passes.
                    if tk.strip() not in ("-", ""):
                        stats["bad"].append(f"b{b} {abbr}: {tk}")
                    continue
                if (ev.ql <= 0 and tk.strip() != "R"
                        and ev.kind in ("note", "chord", "rest", "unpitched")):
                    stats["bad"].append(f"b{b} {abbr}: {tk} (zero duration)")
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

                onset = bar_start[b] + swung(q_off) * bar_spq[b]
                slot = max(ev.ql * bar_spq[b], 1e-3)
                q_off += ev.ql

                # --- source: synth patch or sample
                if voice.synth is not None:
                    if not ev.midis:
                        stats["bad"].append(f"b{b} {abbr}: synth track needs a pitch")
                        continue
                    patch = {**voice.synth,
                             **{k: ev.params[k] for k in SYNTH_KEYS if k in ev.params}}
                    slot_pre = max(ev.ql * bar_spq[b], 1e-3)
                    ratio = 1.0
                    if ev.gliss_midi is not None:
                        ratio = midi_to_hz(ev.gliss_midi, a4) / midi_to_hz(ev.midis[0], a4)
                    x = synth_note(patch, [midi_to_hz(m_, a4) for m_ in ev.midis],
                                   slot_pre, ratio)
                    smp = None
                else:
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
                if smp is not None and ev.kind in ("note", "chord") and smp.f0_hz > 0:
                    st = 12 * math.log2(midi_to_hz(ev.midis[0], a4) / smp.f0_hz)
                    if ev.gliss_midi is not None:
                        st_end = 12 * math.log2(midi_to_hz(ev.gliss_midi, a4) / smp.f0_hz)
                elif ev.kind == "unpitched":
                    st, _ = param_pair(ev.params, "st", 0.0)
                    _, st_end2 = param_pair(ev.params, "st", 0.0)
                    st_end = st_end2 if abs(st_end2 - st) > 1e-6 else None

                curve = ev.params.get("curve", "lin")
                tau = float(ev.params.get("tau", 0.045))
                quoted = False
                if "gest" in ev.params and ev.params.get("gsrc") == "raw" \
                        and ev.kind in ("note", "unpitched"):
                    # Cantus-firmus quotation: the event plays its own slice
                    # of the tape. A notated pitch transposes the whole call
                    # from its consensus median (vocoder, so time is the
                    # score's to shape); an X event takes the bird verbatim.
                    g = lookup_gesture(gestures, str(ev.params["gest"]))
                    if g is None or tape_audio is None or g.get("t0") is None:
                        stats["bad"].append(
                            f"b{b} {abbr}: gest={ev.params['gest']} "
                            f"({'no tape header' if tape_audio is None else 'unknown gesture'})")
                    else:
                        x = tape_audio[int(g["t0"] * SR): int(g["t1"] * SR)].copy()
                        if ev.kind == "note" and ev.midis:
                            shift = 12 * math.log2(
                                midi_to_hz(ev.midis[0], a4) / g["median_hz"])
                            if abs(shift) > 0.05:
                                x = vocode(x, shift)
                        quoted = True
                elif "gest" in ev.params and ev.kind == "note" \
                        and smp is not None and smp.f0_hz > 0:
                    g = lookup_gesture(gestures, str(ev.params["gest"]))
                    layer = ev.params.get("glayer", "resolved")
                    anchors = g.get(layer, []) if g else []
                    if g is None or len(anchors) < 2:
                        stats["bad"].append(
                            f"b{b} {abbr}: gest={ev.params['gest']} "
                            f"({'unknown gesture' if g is None else f'layer {layer} too sparse'})")
                    else:
                        # The notated pitch states where the gesture's median
                        # resolved pitch lands; the contour supplies the shape
                        # around it. A quote is transposable material, and the
                        # octave layer transposes with the same reference so
                        # the conflict shadow stays where it was heard.
                        base_st = 12 * math.log2(midi_to_hz(ev.midis[0], a4) / smp.f0_hz)
                        med = g["median_hz"]
                        t_arr = [a[0] for a in anchors]
                        st_arr = [base_st + 12 * math.log2(hz / med) for _, hz in anchors]
                        x = pitch_polyline(x, t_arr, st_arr)
                        quoted = True
                if quoted:
                    pass
                elif ev.kind == "chord" and len(ev.midis) > 1 \
                        and smp is not None and smp.f0_hz > 0:
                    # Layer every chord tone. Until now a chord silently
                    # played only its first pitch; a sampler has no excuse.
                    # Varispeed tones end at different times (tape physics —
                    # reads as a strum tail); vocoder tones stay aligned.
                    parts = []
                    for m_ in ev.midis:
                        st_i = 12 * math.log2(midi_to_hz(m_, a4) / smp.f0_hz)
                        parts.append(vocode(x, st_i) if mode == "vocoder"
                                     else varispeed(x, st_i))
                    acc = np.zeros(max(len(p) for p in parts), np.float32)
                    for p in parts:
                        acc[:len(p)] += p
                    x = acc / math.sqrt(len(parts))
                elif st_end is not None:
                    x = pitch_ramp(x, st, st_end, curve, tau)
                elif mode == "vocoder":
                    x = vocode(x, st)
                else:
                    x = varispeed(x, st)

                # --- experimental transforms
                if "chop" in ev.params:
                    x = chop_shuffle(x, float(ev.params["chop"]), int(slot * SR))
                if "ring" in ev.params:
                    x = ring_mod(x, float(ev.params["ring"]),
                                 float(ev.params.get("rwet", 1.0)))
                if "glow" in ev.params and len(x) >= 2048:
                    x = glow_chain(x, float(ev.params["glow"]),
                                   ev.params, int(slot * SR))

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
                if "haas" in ev.params:
                    # a few ms of interaural delay: width without a pan move
                    d = int(float(ev.params["haas"]) * SR / 1000.0)
                    if 0 < d < len(R):
                        R = np.concatenate([np.zeros(d, np.float32), R[:-d]])
                send = float(ev.params.get("send", voice.send))

                if abbr == sc_track:
                    sc_onsets.append(onset)
                pending.append([(start, L, R, send), db])
                stats["notes"] += 1

            if eager and hairpin is None and pending:
                for (st_, L_, R_, sd_), db_ in pending:
                    mix_one(st_, L_, R_, sd_, 10 ** (db_ / 20.0))
                pending = []

        if hairpin:
            i0, d = hairpin
            span = pending[i0:]
            for k, item in enumerate(span):
                item[1] += (k / max(len(span) - 1, 1)) * (9.0 if d == "cresc" else -9.0)

        ducks = voices[abbr] is not None and \
            str(next((i.params.get("duck", "1") for i in parsed.instruments
                      if i.abbrev == abbr), "1")) not in ("0", "no", "off")
        for (start, L, R, send), db in pending:
            if eager:
                mix_one(start, L, R, send, 10 ** (db / 20.0))
            else:
                placed.append((abbr, ducks, start, L, R, send, 10 ** (db / 20.0)))

    # ---- deferred mixdown, with the pump applied to ducking tracks
    duck = (duck_envelope(sc_onsets, n_total, sc_depth, sc_rel)
            if sc_track and sc_onsets else None)
    for abbr, ducks, start, L, R, send, g in placed:
        mix_one(start, L, R, send, g,
                duck if (duck is not None and ducks and abbr != sc_track) else None)
    if duck is not None:
        print(f"  sidechain: {len(sc_onsets)} hits from '{sc_track}' "
              f"depth {sc_depth} rel {sc_rel}s")

    # ---- reverb + master
    # `# reverb: <seconds>` — the size of the room. A motet wants a nave;
    # a drum piece wants the default 2.6 s.
    rv_s = 2.6
    rvm = re.search(r"([\d.]+)", parsed.extra.get("reverb", ""))
    if rvm:
        rv_s = max(0.3, min(float(rvm.group(1)), 12.0))
    ir = make_ir(seconds=rv_s)
    rev = np.stack([sig.oaconvolve(wet[c], ir[c])[:n_total] for c in range(2)])
    out = dry + rev.astype(np.float32)

    sos = sig.butter(2, 28 / (SR / 2), btype="high", output="sos")
    out = np.stack([sig.sosfilt(sos, ch) for ch in out]).astype(np.float32)
    mtgt = -17.0
    mm = re.search(r"rms\s*=\s*(-?[\d.]+)", parsed.extra.get("master", ""))
    if mm:
        mtgt = float(mm.group(1))
    out = master(out, target_rms_db=mtgt)

    sf.write(str(out_path), out.T, SR, subtype="PCM_24")
    if stats["bad"]:
        print(f"  ! {len(stats['bad'])} unparseable token(s):", file=sys.stderr)
        for b in stats["bad"][:12]:
            print(f"      {b}", file=sys.stderr)
        if len(stats["bad"]) > 12:
            print(f"      ... and {len(stats['bad']) - 12} more", file=sys.stderr)
    if verbose:
        rms = float(np.sqrt((out ** 2).mean()))
        print(f"{score_path.name}: {stats['notes']} events, "
              f"{len(voices)} voices, {total_s:.1f}s, A={a4:.1f} Hz")
        print(f"wrote {out_path}  peak -1.0 dBFS  rms {20*math.log10(rms+1e-12):.1f} dBFS")
    return out


# ------------------------------------------------------------------- check
#
# `--check` is the effect-free half of this renderer: parse + layout, no
# sample loading, no DSP, no writes. It emits mus.audio.check-report.v1
# (schemas/mus-check-report.schema.json — the ratified binary interface
# between any MUS checker and any host). Diagnostics anchor to semantic
# coordinates ({bar, track, tokenIndex}), never byte offsets, and a refused
# score is an outcome, not an error: exit code stays 0, `clean` says false.

RENDERER_VERSION = "mus_audio/0.2.0"

_ERROR_CODES = {"unparseable-token", "unknown-gesture", "synth-needs-pitch",
                "bad-header-value"}

_CHAIN_ORDER = ["gest", "glayer", "gsrc", "chop", "ring", "glow", "ghold",
                "gwarble", "gharm", "pump", "str", "stut", "haas"]

RE_SECTION_PROSE = re.compile(
    r"^#\s*section\s*:\s*(.+?)\s*\[(\d+)-(\d+)\]\s*(?:[—–-]\s*(.*))?$")


def _file_digest(path: Path):
    if not path.exists():
        return None
    import hashlib
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _midi_to_name(midi: float) -> str:
    n = int(round(midi))
    cents = int(round((midi - n) * 100))
    name = NOTE_NAMES[n % 12] + str(n // 12 - 1)
    if cents:
        name += f"{cents:+d}"
    return name


def check_score(score_path: Path, base_dir: Path | None = None) -> dict:
    """`base_dir` overrides the directory pack/gestures/tape resolve against
    (default: the score's own directory). It exists for hosts that check a
    temp copy of a score that lives elsewhere — the Atril route writes the
    fence's bytes to a tmpdir but resolves assets against the real repo."""
    base = base_dir if base_dir is not None else score_path.parent
    text = score_path.read_text()
    parsed = mus.parse_mus(text)
    diagnostics = []

    def diag(code, anchor, message):
        diagnostics.append({
            "severity": "error" if code in _ERROR_CODES else "warning",
            "code": code, "anchor": anchor, "message": message,
        })

    def header_float(key, pattern, default):
        raw = parsed.extra.get(key)
        if raw is None:
            return default
        m = re.search(pattern, raw)
        if not m:
            diag("bad-header-value", {"kind": "header", "key": key},
                 f"could not read {key!r} from {raw!r}")
            return default
        return float(m.group(1))

    a4 = header_float("tuning", r"A\s*=\s*([\d.]+)", 440.0)
    reverb_s = header_float("reverb", r"([\d.]+)", 2.6)
    master_rms = header_float("master", r"rms\s*=\s*(-?[\d.]+)", -17.0)

    swing = None
    swing_unit_ql, swing_r = 0.0, 0.5
    swm = parsed.extra.get("swing", "").split()
    if swm:
        try:
            unit, pct = (int(swm[0]), float(swm[1])) if len(swm) > 1 else (16, float(swm[0]))
            swing_unit_ql = 4.0 / unit
            swing_r = min(0.75, max(0.5, pct / 100.0))
            swing = {"unit": unit, "percent": pct}
        except (ValueError, ZeroDivisionError):
            diag("bad-header-value", {"kind": "header", "key": "swing"},
                 f"could not read swing from {parsed.extra['swing']!r}")

    def swung(q_pos):
        if swing_unit_ql <= 0 or swing_r <= 0.5:
            return q_pos
        k = int(q_pos / swing_unit_ql + 1e-6)
        if k % 2 == 1 and abs(q_pos - k * swing_unit_ql) < 1e-6:
            return q_pos + swing_unit_ql * (2.0 * swing_r - 1.0)
        return q_pos

    # ---- external artifacts: digests and manifests, never audio ----------
    pack_ref = parsed.extra.get("pack")
    pack_path = (base / pack_ref).resolve() if pack_ref else None
    pack_digest = _file_digest(pack_path) if pack_path else None
    pack_voices = {}
    if pack_ref and pack_digest is None:
        diag("missing-pack", {"kind": "header", "key": "pack"}, f"{pack_ref} not found")
    elif pack_path and pack_digest:
        data = json.load(open(pack_path))
        for vname, v in data.get("voices", {}).items():
            pack_voices[vname] = [float(s.get("f0_hz") or 0.0) for s in v["samples"]]
        for nname in data.get("noise", {}):
            pack_voices[nname] = [0.0]

    gest_ref = parsed.extra.get("gestures")
    gest_path = (base / gest_ref).resolve() if gest_ref else None
    gestures_digest = _file_digest(gest_path) if gest_path else None
    gestures = {}
    if gest_ref and gestures_digest is None:
        diag("missing-gestures", {"kind": "header", "key": "gestures"}, f"{gest_ref} not found")
    elif gest_path and gestures_digest:
        gestures = load_gestures(gest_path)

    tape_ref = parsed.extra.get("tape")
    tape_path = (base / tape_ref).resolve() if tape_ref else None
    tape_digest = _file_digest(tape_path) if tape_path else None
    if tape_ref and tape_digest is None:
        diag("missing-tape", {"kind": "header", "key": "tape"}, f"{tape_ref} not found")

    # ---- instruments ------------------------------------------------------
    instruments = []
    sources = {}
    for inst in parsed.instruments:
        p = inst.params
        if any(k in p for k in SYNTH_KEYS):
            source = {"kind": "synth", "patch": {k: p[k] for k in SYNTH_KEYS if k in p}}
        elif "sample" in p:
            source = {"kind": "sample", "path": p["sample"]}
        elif p.get("voice") in pack_voices:
            f0s = pack_voices[p["voice"]]
            source = {"kind": "voice", "voice": p["voice"],
                      "samples": len(f0s), "sampleF0Hz": f0s}
        else:
            source = {"kind": "missing"}
            diag("no-samples-for-track", {"kind": "instrument", "abbrev": inst.abbrev},
                 f"track '{inst.abbrev}' resolves no samples and declares no synth")
        defaults = {k: v for k, v in p.items()
                    if k not in STRUCTURAL_PARAMS and k not in SYNTH_KEYS}
        chain = [k for k in _CHAIN_ORDER if k in p]
        sources[inst.abbrev] = source
        instruments.append({
            "abbrev": inst.abbrev, "name": inst.name, "clef": inst.clef,
            "source": source, "defaults": defaults, "transformChain": chain,
        })

    # ---- bar → seconds map (mirrors render()) -----------------------------
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
        bar_qlen[b] = num * 4.0 / den
        bar_spq[b] = 60.0 / tempo
        bar_start[b] = t
        t += bar_qlen[b] * bar_spq[b]

    bar_content = {}
    for mb in parsed.bars:
        for b in range(mb.bar_num, mb.end_bar + 1):
            bar_content[b] = mb.track_content

    # ---- events (mirrors render()'s traversal, minus DSP) -----------------
    events = []
    used_gestures = {}
    for inst in parsed.instruments:
        abbr = inst.abbrev
        source = sources[abbr]
        defaults = {k: v for k, v in inst.params.items()
                    if k not in STRUCTURAL_PARAMS and k not in SYNTH_KEYS}
        cur_dyn = "mf"
        for b in range(1, n_bars + 1):
            content = bar_content.get(b, {}).get(abbr, "")
            if not content or content.strip() == "-":
                continue
            toks = split_attached_dynamics(
                mus.expand_pattern_repetitions(mus.tokenize_bar_content(content)))
            q_off = 0.0
            for ti, tk in enumerate(toks):
                ev = parse_token(tk)
                anchor = {"kind": "event", "bar": b, "track": abbr, "tokenIndex": ti}
                if ev is None:
                    if tk.strip() not in ("-", ""):
                        diag("unparseable-token", anchor, tk)
                    continue
                if ev.kind == "dynamic":
                    cur_dyn = ev.dyn
                    continue
                if ev.kind == "hairpin":
                    continue
                if ev.kind == "rest":
                    q_off += ev.ql
                    continue
                if ev.ql <= 0 and tk.strip() != "R":
                    diag("zero-duration", anchor, tk)
                if q_off >= bar_qlen.get(b, 4.0) - 1e-6:
                    # A long final note ringing past the barline is idiom; an
                    # event whose ONSET falls outside the bar is arithmetic.
                    diag("overfull-bar", anchor,
                         f"onset at {q_off:g} ql in a {bar_qlen.get(b, 4.0):g} ql bar")
                params = dict(ev.params)
                eff = {**defaults, **params}
                quote = None
                if "gest" in eff:
                    g = lookup_gesture(gestures, str(eff["gest"]))
                    layer = eff.get("glayer", "resolved")
                    if g is None:
                        diag("unknown-gesture", anchor, f"gest={eff['gest']}")
                    else:
                        shift = None
                        if ev.kind == "note" and ev.midis and g.get("median_hz"):
                            shift = round(12 * math.log2(
                                midi_to_hz(ev.midis[0], a4) / g["median_hz"]), 2)
                        if len(g.get(layer, [])) < 2 and eff.get("gsrc") != "raw":
                            diag("sparse-gesture-layer", anchor,
                                 f"gest={eff['gest']} layer {layer}")
                        if eff.get("gsrc") == "raw" and tape_digest is None:
                            diag("no-tape-header", anchor,
                                 "gsrc=raw without a # tape: header")
                        quote = {"gest": str(eff["gest"]), "layer": layer,
                                 "gsrc": eff.get("gsrc"),
                                 "hypothesisId": g.get("id"),
                                 "t0": g.get("t0"), "t1": g.get("t1"),
                                 "medianHz": g.get("median_hz"), "shiftSt": shift}
                        used_gestures[str(eff["gest"])] = g.get("id")
                if source["kind"] == "synth" and ev.kind == "unpitched" \
                        and not (quote and quote.get("gsrc") == "raw"):
                    diag("synth-needs-pitch", anchor, tk)
                lyr = re.search(r'"([^"]*)"', tk)
                events.append({
                    "bar": b, "track": abbr, "tokenIndex": ti, "kind": ev.kind,
                    "onsetQl": round(q_off, 6),
                    "onsetSeconds": round(bar_start[b] + q_off * bar_spq[b], 6),
                    "swungOnsetSeconds": round(bar_start[b] + swung(q_off) * bar_spq[b], 6),
                    "durationQl": round(ev.ql, 6),
                    "durationSeconds": round(ev.ql * bar_spq[b], 6),
                    "pitches": [_midi_to_name(m_) for m_ in ev.midis],
                    "pitchesHz": [round(midi_to_hz(m_, a4), 3) for m_ in ev.midis],
                    "glissTargetHz": round(midi_to_hz(ev.gliss_midi, a4), 3)
                        if ev.gliss_midi is not None else None,
                    "dynamic": cur_dyn,
                    "params": params, "effectiveParams": eff,
                    "flags": sorted(ev.flags),
                    "sweeps": sorted(k for k, v in eff.items() if "->" in str(v)),
                    "lyric": lyr.group(1) if lyr else None,
                    "quote": quote,
                })
                q_off += ev.ql

    # ---- sections with prose (tolerant re-scan; parse_mus keeps name only)
    sections = []
    for line in text.splitlines():
        m = RE_SECTION_PROSE.match(line.strip())
        if m:
            sections.append({"name": m.group(1).split("—")[0].strip(),
                             "from": int(m.group(2)), "to": int(m.group(3)),
                             "prose": (m.group(4) or "").strip() or None})
    texts = [{"bar": bar, "prose": p}
             for bar, lines in sorted(parsed.text_at.items()) for p in lines]

    declared = ([{"id": i["abbrev"], "kind": "instrument", "iri": None} for i in instruments]
                + [{"id": s["name"], "kind": "section", "iri": None} for s in sections]
                + [{"id": gid, "kind": "gesture", "iri": iri}
                   for gid, iri in sorted(used_gestures.items())])

    return {
        "schema": "mus.audio.check-report.v1",
        "producer": "mus_audio",
        "rendererVersion": RENDERER_VERSION,
        "clean": not any(d["severity"] == "error" for d in diagnostics),
        "sourceDigest": "sha256:" + __import__("hashlib").sha256(text.encode()).hexdigest(),
        "packDigest": pack_digest,
        "gesturesDigest": gestures_digest,
        "tapeDigest": tape_digest,
        "score": {
            "title": parsed.title, "summary": parsed.summary,
            "bars": n_bars, "durationSeconds": round(t, 3), "tuningA": a4,
            "swing": swing, "reverbSeconds": reverb_s, "masterRmsDb": master_rms,
            "sidechain": ({"raw": parsed.extra["sidechain"]}
                          if "sidechain" in parsed.extra else None),
            "tempoChanges": [[b, float(v)] for b, v in sorted(tempo_at.items())],
            "timeChanges": [[b, v] for b, v in sorted(time_at.items())],
            "sections": sections, "texts": texts,
        },
        "instruments": instruments,
        "events": events,
        "declaredObjects": declared,
        "diagnostics": diagnostics,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Render MUS to audio via a sample pack.")
    ap.add_argument("score", help="path to .mus score")
    ap.add_argument("-o", "--output", default=None, help="output .wav")
    ap.add_argument("--check", action="store_true",
                    help="effect-free parse+layout verdict as JSON on stdout (no render)")
    ap.add_argument("--base", default=None,
                    help="directory pack/gestures/tape resolve against (default: score dir)")
    args = ap.parse_args()
    sp = Path(args.score)
    if args.check:
        print(json.dumps(check_score(sp, Path(args.base) if args.base else None), indent=1))
        return 0
    op = Path(args.output) if args.output else sp.with_suffix(".wav")
    render(sp, op)
    return 0


if __name__ == "__main__":
    sys.exit(main())
