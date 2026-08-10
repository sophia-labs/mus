#!/usr/bin/env python3
"""Golden-vector generator for the mus-dsp parity port.

Dumps deterministic input/output pairs for every DSP function in mus_audio.py
into mus-rs/fixtures/dsp/ as raw little-endian float binaries plus a
manifest.json describing each case: the function, its arguments, the file
names, shapes, and the tolerance the Rust port must meet.

The Python implementation is the oracle. Nothing here is hand-computed —
every output array is produced by calling the exact function the renderer
calls, so a passing Rust test means "same math", not "similar idea".

Run from the repo root:  uv run --extra audio python mus-rs/tools/gen_dsp_fixtures.py
"""

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import mus_audio as ma  # noqa: E402
import scipy.signal as sig  # noqa: E402
from scipy.ndimage import maximum_filter1d  # noqa: E402

SR = ma.SR
OUT = ROOT / "mus-rs" / "fixtures" / "dsp"
OUT.mkdir(parents=True, exist_ok=True)

manifest = []


def _write(name, arr, dtype="<f4"):
    arr = np.ascontiguousarray(arr, dtype=np.dtype(dtype))
    (OUT / name).write_bytes(arr.tobytes())
    return list(arr.shape)


def case(name, module, func, args, x_in, x_out, metric, tol,
         dtype="<f4", note=""):
    entry = {
        "name": name, "module": module, "func": func, "args": args,
        "metric": metric, "tol": tol, "dtype": dtype, "note": note,
    }
    if x_in is not None:
        entry["input"] = f"{name}.in.bin"
        entry["shape_in"] = _write(entry["input"], x_in, dtype)
    entry["output"] = f"{name}.out.bin"
    entry["shape_out"] = _write(entry["output"], x_out, dtype)
    manifest.append(entry)
    print(f"  {name:36s} in={entry.get('shape_in')} out={entry['shape_out']}")


# ------------------------------------------------------------- test signals
def sine(f=220.0, secs=0.5, amp=0.7):
    t = np.arange(int(secs * SR)) / SR
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)


def chirp(f0=300.0, f1=1800.0, secs=0.7, amp=0.8):
    t = np.arange(int(secs * SR)) / SR
    f = f0 * (f1 / f0) ** (t / secs)
    phase = np.cumsum(f) / SR
    y = amp * np.sin(2 * np.pi * phase)
    fade = int(0.01 * SR)
    y[:fade] *= np.linspace(0, 1, fade)
    y[-fade:] *= np.linspace(1, 0, fade)
    return y.astype(np.float32)


def burst(secs=0.35):
    """AM-modulated upward sweep, roughly birdlike."""
    t = np.arange(int(secs * SR)) / SR
    f = 2000.0 + 3000.0 * (t / secs) ** 1.5
    phase = np.cumsum(f) / SR
    am = 0.55 + 0.45 * np.sin(2 * np.pi * 37.0 * t)
    y = 0.8 * am * np.sin(2 * np.pi * phase)
    env = np.minimum(t / 0.02, 1.0) * np.exp(-2.2 * t / secs)
    return (y * env).astype(np.float32)


def noise(secs=1.0, seed=42, amp=0.3):
    rng = np.random.default_rng(seed)
    return (amp * rng.standard_normal(int(secs * SR))).astype(np.float32)


SINE = sine()
CHIRP = chirp()
BURST = burst()
NOISE = noise()
MIX = (SINE[: len(BURST)] * 0.5 + BURST * 0.8).astype(np.float32)

print("kernels:")
case("ring_mod_sine", "kernels", "ring_mod", {"f_hz": 220.0, "wet": 1.0},
     SINE, ma.ring_mod(SINE, 220.0, 1.0), "max_abs", 1e-6)
case("ring_mod_burst_wet", "kernels", "ring_mod", {"f_hz": 91.7, "wet": 0.6},
     BURST, ma.ring_mod(BURST, 91.7, 0.6), "max_abs", 1e-6)
case("soft_clip_drive", "kernels", "soft_clip", {"drive": 3.2},
     MIX, ma.soft_clip(MIX, 3.2), "max_abs", 1e-6)
case("hard_clip_noise", "kernels", "hard_clip", {"amount": 4.0},
     NOISE, ma.hard_clip(NOISE, 4.0), "max_abs", 1e-6)
case("bitcrush_bits", "kernels", "bitcrush", {"bits": 10, "decim": None},
     CHIRP, ma.bitcrush(CHIRP, bits=10), "max_abs", 1e-6)
case("bitcrush_decim", "kernels", "bitcrush", {"bits": None, "decim": 7},
     CHIRP, ma.bitcrush(CHIRP, decim=7), "max_abs", 1e-6)
case("bitcrush_both", "kernels", "bitcrush", {"bits": 6, "decim": 3},
     BURST, ma.bitcrush(BURST, bits=6, decim=3), "max_abs", 1e-6)
case("stutter_5", "kernels", "stutter", {"n": 5, "slot_samples": len(BURST)},
     BURST, ma.stutter(BURST, 5, len(BURST)), "max_abs", 1e-6)
case("chop_shuffle_8", "kernels", "chop_shuffle",
     {"n_grains": 8, "slot_samples": int(0.5 * SR)},
     BURST, ma.chop_shuffle(BURST, 8, int(0.5 * SR)), "max_abs", 1e-6)
case("chop_shuffle_3_tight", "kernels", "chop_shuffle",
     {"n_grains": 3, "slot_samples": int(0.1 * SR)},
     CHIRP, ma.chop_shuffle(CHIRP, 3, int(0.1 * SR)), "max_abs", 1e-6)

onsets = [0.0, 0.25, 0.5, 0.625, 0.75]
case("duck_envelope", "kernels", "duck_envelope",
     {"onsets": onsets, "n": SR, "depth": 0.6, "release": 0.16, "hold": 0.012},
     None, ma.duck_envelope(onsets, SR, 0.6, 0.16, 0.012), "max_abs", 1e-6)

L, R = ma.pan_stereo(SINE, 0.3, 0.3)
case("pan_static", "kernels", "pan_stereo", {"p0": 0.3, "p1": 0.3},
     SINE, np.stack([L, R]), "max_abs", 1e-6, note="planar LR")
L, R = ma.pan_stereo(CHIRP, -0.8, 0.8)
case("pan_sweep", "kernels", "pan_stereo", {"p0": -0.8, "p1": 0.8},
     CHIRP, np.stack([L, R]), "max_abs", 1e-6, note="planar LR")

sz = int(0.02 * SR) | 1
case("maximum_filter1d", "kernels", "maximum_filter1d", {"size": sz},
     np.abs(NOISE), maximum_filter1d(np.abs(NOISE), size=sz), "max_abs", 1e-6,
     note="scipy.ndimage semantics: window centered, reflect boundary")

print("filters:")
NYQ = SR / 2.0
for nm, (order, fc, btype) in {
    "butter4_low_1200": (4, 1200.0, "low"),
    "butter4_high_300": (4, 300.0, "high"),
    "butter2_low_5200": (2, 5200.0, "low"),
    "butter2_high_28": (2, 28.0, "high"),
}.items():
    sos = sig.butter(order, fc / NYQ, btype=btype, output="sos")
    case(f"sos_{nm}", "filters", "butter_sos",
         {"order": order, "fc_hz": fc, "btype": btype}, None, sos,
         "max_abs", 1e-10, dtype="<f8", note="SOS rows [b0 b1 b2 a0 a1 a2]")

sos = sig.butter(4, 1200.0 / NYQ, btype="low", output="sos")
case("sosfilt_low_noise", "filters", "sosfilt",
     {"order": 4, "fc_hz": 1200.0, "btype": "low"},
     NOISE, sig.sosfilt(sos, NOISE).astype(np.float32), "max_abs", 1e-5)
zi = sig.sosfilt_zi(sos)
case("sosfilt_zi_low_1200", "filters", "sosfilt_zi",
     {"order": 4, "fc_hz": 1200.0, "btype": "low"}, None, zi,
     "max_abs", 1e-9, dtype="<f8")
case("sweep_static_low", "filters", "sweep_filter",
     {"f_start": 1200.0, "f_end": 1200.0, "btype": "low"},
     NOISE, ma.sweep_filter(NOISE, 1200.0, 1200.0, "low"), "max_abs", 1e-5)
case("sweep_low_fall", "filters", "sweep_filter",
     {"f_start": 4200.0, "f_end": 800.0, "btype": "low"},
     NOISE, ma.sweep_filter(NOISE, 4200.0, 800.0, "low"), "max_abs", 5e-5)
case("sweep_high_rise", "filters", "sweep_filter",
     {"f_start": 300.0, "f_end": 2000.0, "btype": "high"},
     NOISE, ma.sweep_filter(NOISE, 300.0, 2000.0, "high"), "max_abs", 5e-5)

print("pitch:")
case("varispeed_up5", "pitch", "varispeed", {"semitones": 5.0},
     CHIRP, ma.varispeed(CHIRP, 5.0), "rel_rms", 5e-4,
     note="librosa.resample res_type=soxr_hq; lengths must match exactly")
case("varispeed_down12", "pitch", "varispeed", {"semitones": -12.0},
     BURST, ma.varispeed(BURST, -12.0), "rel_rms", 5e-4)
case("vocode_up35", "pitch", "vocode", {"semitones": 3.5},
     CHIRP, ma.vocode(CHIRP, 3.5), "rel_rms", 5e-3,
     note="librosa.effects.pitch_shift: stft(2048,512,hann)->phase_vocoder->istft->soxr")
case("vocode_down7", "pitch", "vocode", {"semitones": -7.0},
     MIX, ma.vocode(MIX, -7.0), "rel_rms", 5e-3)
case("stretch_140", "pitch", "stretch", {"factor": 1.4},
     BURST, ma.stretch(BURST, 1.4), "rel_rms", 5e-3)
case("stretch_060", "pitch", "stretch", {"factor": 0.6},
     CHIRP, ma.stretch(CHIRP, 0.6), "rel_rms", 5e-3)
case("pitch_ramp_lin", "pitch", "pitch_ramp",
     {"st0": 8.0, "st1": -4.0, "curve": "lin", "tau": 0.045},
     CHIRP, ma.pitch_ramp(CHIRP, 8.0, -4.0, "lin"), "max_abs", 1e-5,
     note="pure numpy: iterative length solve + cumsum readback")
case("pitch_ramp_exp_kick", "pitch", "pitch_ramp",
     {"st0": 0.0, "st1": -40.0, "curve": "exp", "tau": 0.045},
     BURST, ma.pitch_ramp(BURST, 0.0, -40.0, "exp"), "max_abs", 1e-5)
anch_t = [0.0, 0.12, 0.3, 0.42]
anch_st = [-2.0, 3.0, 1.0, -6.0]
case("pitch_polyline", "pitch", "pitch_polyline",
     {"t_anchor": anch_t, "st_anchor": anch_st},
     BURST, ma.pitch_polyline(BURST, anch_t, anch_st), "max_abs", 1e-5,
     note="gesture quotation core; includes tape-runs-out fade branch")

import librosa  # noqa: E402

buzz, _ = librosa.load(str(ROOT / "aigua" / "samples" / "buzz_01.wav"),
                       sr=SR, mono=True)
case("load_buzz01_native", "pitch", "load_decode", {
    "path": "aigua/samples/buzz_01.wav", "native_sr": 48000, "target_sr": SR},
    None, buzz.astype(np.float32), "max_abs", 1e-6,
    note="librosa.load with source native rate == SR: pure decode, no resample; "
         "PCM_16 -> float32 scaled by 1/32768. If a future pack sample's native "
         "rate differs, the load path must resample with soxr_hq like varispeed.")

print("synth:")
phase = np.cumsum(np.full(2048, 220.0)) / SR
case("osc_phase", "synth", "_osc_phase_input", {}, None, phase,
     "max_abs", 1e-9, dtype="<f8", note="shared phase array for the four osc cases")
for wave in ("saw", "square", "tri", "sine"):
    case(f"osc_{wave}", "synth", "_osc", {"wave": wave},
         None, ma._osc(wave, phase), "max_abs", 1e-6)

patch_a = {"synth": "saw", "detune": 12.0, "sub": 0.4, "cutoff": 900.0,
           "famt": 2600.0, "satk": 0.006, "sdec": 0.08, "ssus": 0.6,
           "srel": 0.2}
case("synth_note_funk_bass", "synth", "synth_note",
     {"patch": patch_a, "freqs_hz": [110.0], "slot_s": 0.5, "gliss_ratio": 1.0},
     None, ma.synth_note(patch_a, [110.0], 0.5), "max_abs", 5e-5)
patch_b = {"synth": "square", "osc2": "sine", "mix2": 0.35, "cutoff": 4200.0}
case("synth_note_chord_gliss", "synth", "synth_note",
     {"patch": patch_b, "freqs_hz": [220.0, 277.18, 329.63],
      "slot_s": 0.35, "gliss_ratio": 1.5},
     None, ma.synth_note(patch_b, [220.0, 277.18, 329.63], 0.35, 1.5),
     "max_abs", 5e-5)

print("rng (np-rand):")
ss = np.random.SeedSequence(7)
(OUT / "seedseq_7_state.json").write_text(json.dumps(
    {"seed": 7, "n_words": 8,
     "state": [hex(int(w)) for w in ss.generate_state(8, np.uint64)]}, indent=1))
print("  seedseq_7_state.json")
raw = np.random.PCG64(7).random_raw(64)
(OUT / "pcg64_7_raw.json").write_text(json.dumps(
    {"seed": 7, "raw": [hex(int(w)) for w in raw]}, indent=1))
print("  pcg64_7_raw.json")
case("standard_normal_64", "rng", "standard_normal",
     {"seed": 7, "n": 64}, None,
     np.random.default_rng(7).standard_normal(64), "max_abs", 1e-12,
     dtype="<f8", note="numpy ziggurat; must be bit-faithful")
case("standard_normal_2x32", "rng", "standard_normal_2d",
     {"seed": 7, "shape": [2, 32]}, None,
     np.random.default_rng(7).standard_normal((2, 32)), "max_abs", 1e-12,
     dtype="<f8", note="row-major fill order")

print("bus:")
for secs in (0.6, 2.6, 4.5):
    nm = f"make_ir_{str(secs).replace('.', '_')}"
    case(nm, "bus", "make_ir", {"seconds": secs, "seed": 7},
         None, ma.make_ir(seconds=secs), "max_abs", 1e-6,
         note="planar stereo; depends on np-rand standard_normal((2,n))")

ir06 = ma.make_ir(seconds=0.6)
wetin = noise(secs=0.8, seed=11, amp=0.4)
rev = np.stack([sig.oaconvolve(wetin, ir06[c])[: len(wetin)] for c in range(2)])
case("reverb_apply_0_6", "bus", "oaconvolve",
     {"ir": "make_ir_0_6", "n_out": len(wetin)},
     wetin, rev.astype(np.float32), "max_abs", 1e-5, note="planar LR")

t = np.arange(int(1.5 * SR)) / SR
click = np.zeros(len(t), np.float32)
click[:: SR // 4] = 0.95
mL = (0.3 * np.sin(2 * np.pi * 220 * t) + click).astype(np.float32)
mR = (0.25 * np.sin(2 * np.pi * 330 * t) + np.roll(click, 200)).astype(np.float32)
mst = np.stack([mL, mR])
case("master_rms14", "bus", "master", {"target_rms_db": -14.0, "ceiling": 0.89},
     mst, ma.master(mst.copy(), target_rms_db=-14.0), "max_abs", 5e-4,
     note="planar stereo in/out; includes limiter fftconvolve smoothing")

(OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
print(f"\n{len(manifest)} cases -> {OUT}/manifest.json")
