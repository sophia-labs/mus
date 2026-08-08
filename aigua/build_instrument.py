"""Phase 4: turn the catalogue into a playable instrument.

Selects clean, well-isolated exemplars per family, extracts them with proper
fades from a gently-gated signal (heavy gating sounds artificial as a sample
even though it segments better), measures pitch, and writes a manifest saying
what notes are literally at hand and what is reachable by shifting.

Also builds the two non-bird instruments: the car pass-by, and pitched sub
material resonated out of the low-frequency bed.
"""
import json
import numpy as np
import scipy.signal as sig
import librosa
import soundfile as sf

SR, N_FFT, HOP = 48000, 1024, 128
CAR_EVENT = 14                       # identified visually: broadband pass-by
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

y, sr = librosa.load("aigua_raw.wav", sr=SR, mono=True)
ev = json.load(open("events.json"))


def hz_to_note(f):
    """Hz → (name, octave, cents deviation). C4 = middle C, A4 = 440."""
    if not f or f <= 0:
        return None, None, None
    midi = 69 + 12 * np.log2(f / 440.0)
    nearest = int(round(midi))
    cents = (midi - nearest) * 100
    return f"{NOTE_NAMES[nearest % 12]}{nearest // 12 - 1}", nearest, round(float(cents), 1)


def butter_band(x, lo, hi, order=6):
    nyq = sr / 2
    if lo <= 0:
        b, a = sig.butter(order, hi / nyq, btype="low")
    elif hi >= nyq:
        b, a = sig.butter(order, lo / nyq, btype="high")
    else:
        b, a = sig.butter(order, [lo / nyq, hi / nyq], btype="band")
    return sig.filtfilt(b, a, x)


# --- sample-grade signal: high-passed, only gently gated ---------------------
hp = butter_band(y, 700, 14000)
S = librosa.stft(hp, n_fft=N_FFT, hop_length=HOP)
mag, ph = np.abs(S), np.angle(S)
n = mag.shape[1]
blk = int(2.0 * sr / HOP)
prof = np.zeros_like(mag)
for s in range(0, n, blk):
    e = min(n, s + blk)
    prof[:, s:e] = np.percentile(mag[:, s:e], 15, axis=1, keepdims=True)
g = np.clip((mag - 1.15 * prof) / (mag + 1e-10), 0.0, 1.0)
g = 0.25 + 0.75 * g                                   # floor the gate: keep air
g = sig.medfilt2d(g.astype(np.float32), (3, 5))
clean = librosa.istft(mag * g * np.exp(1j * ph), hop_length=HOP, length=len(y))


def fade(x, fin=0.006, fout=0.030):
    x = x.copy()
    ni, no = int(fin * sr), int(fout * sr)
    ni, no = min(ni, len(x) // 3), min(no, len(x) // 2)
    if ni > 1:
        x[:ni] *= np.linspace(0, 1, ni) ** 0.6
    if no > 1:
        x[-no:] *= np.linspace(1, 0, no) ** 1.4
    return x


def isolation(e, all_ev):
    """Seconds of silence before and after — how safely can we grab a tail?"""
    before = min([e["t0"] - o["t1"] for o in all_ev if o["t1"] <= e["t0"]] or [9.0])
    after = min([o["t0"] - e["t1"] for o in all_ev if o["t0"] >= e["t1"]] or [9.0])
    return before, after


# --- family definitions ------------------------------------------------------
FAMILIES = {
    0: ("buzz",  "dense low harmonic stack — many close partials, growly"),
    1: ("chup",  "short soft low chirp, few harmonics — percussive"),
    2: ("mid",   "mid call, strong low partial, moderate ladder"),
    3: ("call",  "THE signature call: long arched 1.5 kHz fundamental + full ladder"),
    4: ("bright","shorter bright cousin of the signature call, fast AM"),
    5: ("glide", "clean high tonal sweep 3–4 kHz — the most musical, most pitchable"),
    6: ("tick",  "very short bright transient, falling"),
}
PER_FAMILY = 5

voices = {}
for cl, (vname, desc) in FAMILIES.items():
    pool = [e for e in ev if e["cluster"] == cl and e["id"] != CAR_EVENT]
    scored = []
    for e in pool:
        bef, aft = isolation(e, ev)
        # Prefer loud, well-isolated, and (for pitched voices) confidently pitched.
        s = (e["rms_db"] + 6 * min(bef, 0.30) / 0.30 + 10 * min(aft, 0.30) / 0.30
             + 3 * min(e["f0_conf"], 8) / 8)
        scored.append((s, e))
    scored.sort(key=lambda t: -t[0])

    samples = []
    for k, (_, e) in enumerate(scored[:PER_FAMILY]):
        bef, aft = isolation(e, ev)
        pre = min(0.020, max(0.004, bef * 0.5))
        post = min(0.120, max(0.020, aft * 0.6))
        a = max(0, int((e["t0"] - pre) * sr))
        b = min(len(clean), int((e["t1"] + post) * sr))
        x = fade(clean[a:b])
        pk = np.abs(x).max() + 1e-12
        x = x * (10 ** (-3 / 20) / pk)
        fn = f"samples/{vname}_{k+1:02d}.wav"
        sf.write(fn, x.astype(np.float32), sr)

        name, midi, cents = hz_to_note(e["f0_med"])
        samples.append(dict(
            file=fn, event=e["id"], t0=e["t0"], dur_s=round(len(x) / sr, 4),
            f0_hz=e["f0_med"], note=name, midi=midi, cents=cents,
            shape=e["shape"], span_st=e["span_st"], sweep_st=e["sweep_st"],
            centroid=e["centroid"], f_hi=e["f_hi"],
            am_rate=e["am_rate"], rms_db=e["rms_db"], f0_conf=e["f0_conf"],
        ))

    f0s = [s["f0_hz"] for s in samples if s["f0_hz"] > 0]
    voices[vname] = dict(
        family=desc, cluster=cl, population=len(pool), samples=samples,
        f0_median=round(float(np.median(f0s)), 1) if f0s else None,
        notes_at_hand=sorted({s["note"] for s in samples if s["note"]}),
    )

# --- the car -----------------------------------------------------------------
ce = next(e for e in ev if e["id"] == CAR_EVENT)
a, b = int((ce["t0"] - 0.9) * sr), int((ce["t1"] + 1.4) * sr)
car = fade(y[max(0, a):min(len(y), b)], 0.25, 0.6)
car *= 10 ** (-3 / 20) / (np.abs(car).max() + 1e-12)
sf.write("samples/car_pass.wav", car.astype(np.float32), sr)

# --- sub: the low bed, and a resonated pitched version -----------------------
low = butter_band(y, 0, 260)
w = librosa.feature.rms(y=low, frame_length=4096, hop_length=1024)[0]
wt = librosa.frames_to_time(np.arange(len(w)), sr=sr, hop_length=1024)
k = int(np.argmax(np.convolve(w, np.ones(90) / 90, mode="same")))
t_c = float(wt[k])
a = max(0, int((t_c - 2.0) * sr))
b = min(len(y), a + int(4.0 * sr))
sub = fade(low[a:b], 0.35, 0.35)
sub *= 10 ** (-3 / 20) / (np.abs(sub).max() + 1e-12)
sf.write("samples/sub_bed.wav", sub.astype(np.float32), sr)

manifest = dict(
    source="New Recording 22.m4a — Aigua, Uruguay",
    sr=SR,
    bandwidth_note="source is AAC 62 kbps mono; nothing above ~9 kHz survives",
    voices=voices,
    noise=dict(
        car=dict(file="samples/car_pass.wav", t0=round(ce["t0"] - 0.9, 2),
                 dur_s=round(len(car) / sr, 3),
                 desc="broadband vehicle pass-by; use as noise source / sweep bed"),
        sub=dict(file="samples/sub_bed.wav", t0=round(t_c - 2.0, 2),
                 dur_s=round(len(sub) / sr, 3),
                 desc="low bed <260 Hz, loudest 4 s; unpitched — resonate or "
                      "ring-mod it to get definite pitch"),
    ),
    shifting=dict(
        varispeed="resample: pitch and duration couple. Natural on these "
                  "transients. Good -30..+12 st; below -24 st it stops being a "
                  "bird and becomes a large animal, which is useful.",
        vocoder="phase vocoder: duration held, pitch free. Clean ±7 st; beyond "
                "that the AM ladder smears into metallic ringing.",
    ),
)
json.dump(manifest, open("instrument.json", "w"), indent=1)

print(f"{'voice':<8} {'n':>3} {'f0':>7} {'note':>6}  notes at hand")
for v, d in voices.items():
    print(f"{v:<8} {len(d['samples']):>3} {str(d['f0_median']):>7} "
          f"{(d['samples'][0]['note'] or '-'):>6}  {d['notes_at_hand']}")
print(f"\ncar  {len(car)/sr:.2f}s @ {ce['t0']-0.9:.2f}s")
print(f"sub  {len(sub)/sr:.2f}s @ {t_c-2.0:.2f}s")
print("\nwrote instrument.json + samples/")
