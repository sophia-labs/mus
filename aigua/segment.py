"""Phase 2: band separation, denoise, event detection, per-event features.

The recording is really two superimposed instruments already:
  - a low continuous bed (wind + the car) below ~300 Hz
  - discrete bird events above ~900 Hz
so the first move is to split them, because they want different treatment.

Everything here uses a TIME-VARYING noise floor. A global one fails on this
file: the car pass-by around 9 s lifts the broadband floor by ~10 dB, which
both defeats the spectral gate and jams an energy gate permanently open.
"""
import json
import numpy as np
import scipy.signal as sig
import librosa
import soundfile as sf

SR = 48000
N_FFT, HOP = 1024, 128          # 21.3 ms window, 2.67 ms hop
BIRD_LO, BIRD_HI = 900.0, 11000.0
RUMBLE_HI = 300.0
BLOCK_SEC = 2.0                 # noise-floor estimation block

y, sr = librosa.load("aigua_raw.wav", sr=SR, mono=True)
dur = len(y) / sr


def butter_band(x, lo, hi, order=6):
    nyq = sr / 2
    if lo <= 0:
        b, a = sig.butter(order, hi / nyq, btype="low")
    elif hi >= nyq:
        b, a = sig.butter(order, lo / nyq, btype="high")
    else:
        b, a = sig.butter(order, [lo / nyq, hi / nyq], btype="band")
    return sig.filtfilt(b, a, x)


def blockwise_percentile(M, q, block):
    """Percentile along axis 1 in blocks, linearly interpolated back to full
    length. A cheap stand-in for a sliding percentile filter."""
    n = M.shape[1]
    centers, vals = [], []
    for s in range(0, n, block):
        e = min(n, s + block)
        centers.append((s + e - 1) / 2.0)
        vals.append(np.percentile(M[:, s:e], q, axis=1))
    centers = np.array(centers)
    V = np.stack(vals, axis=1)                       # (bins, nblocks)
    if len(centers) == 1:
        return np.repeat(V, n, axis=1)
    xi = np.arange(n)
    out = np.empty((M.shape[0], n), dtype=M.dtype)
    for k in range(M.shape[0]):
        out[k] = np.interp(xi, centers, V[k])
    return out


rumble = butter_band(y, 0, RUMBLE_HI)
birds_raw = butter_band(y, BIRD_LO, BIRD_HI)

# --- spectral gate on the bird band, time-varying floor ---------------------
S = librosa.stft(birds_raw, n_fft=N_FFT, hop_length=HOP)
mag, phase = np.abs(S), np.angle(S)
block = int(BLOCK_SEC * sr / HOP)
noise = blockwise_percentile(mag, 15, block)
ALPHA = 2.4                      # over-subtraction factor
gain = np.clip((mag - ALPHA * noise) / (mag + 1e-10), 0.0, 1.0)
gain = sig.medfilt2d(gain.astype(np.float32), kernel_size=(3, 5))
birds = librosa.istft(mag * gain * np.exp(1j * phase),
                      hop_length=HOP, length=len(y))

sf.write("aigua_birds.wav", birds, sr)
sf.write("aigua_rumble.wav", rumble, sr)

# Where is the broadband floor elevated? That is the car.
floor_db = 20 * np.log10(noise.mean(axis=0) + 1e-12)
floor_times = librosa.frames_to_time(np.arange(len(floor_db)), sr=sr, hop_length=HOP)
med_floor = np.median(floor_db)
loud = floor_db > med_floor + 4.0
if loud.any():
    print(f"elevated broadband floor (car/wind): "
          f"{floor_times[loud].min():.2f}–{floor_times[loud].max():.2f} s, "
          f"max +{(floor_db.max()-med_floor):.1f} dB over median")

# --- event detection: hysteresis against a LOCAL floor ----------------------
frame_e = librosa.feature.rms(y=birds, frame_length=N_FFT, hop_length=HOP)[0]
edb = 20 * np.log10(frame_e + 1e-12)
times = librosa.frames_to_time(np.arange(len(edb)), sr=sr, hop_length=HOP)

local_floor = blockwise_percentile(edb[None, :], 30, block)[0]
local_peak = blockwise_percentile(edb[None, :], 99.0, block)[0]
rng = np.maximum(local_peak - local_floor, 6.0)
T_HI = local_floor + 0.38 * rng
T_LO = local_floor + 0.20 * rng

active = np.zeros(len(edb), dtype=bool)
on = False
for i, v in enumerate(edb):
    if not on and v > T_HI[i]:
        on = True
    elif on and v < T_LO[i]:
        on = False
    active[i] = on
for i in range(1, len(active)):          # walk the attack back to the low gate
    if active[i] and not active[i - 1]:
        j = i
        while j > 0 and edb[j - 1] > T_LO[j - 1]:
            j -= 1
            active[j] = True

MIN_DUR, MERGE_GAP, MAX_DUR = 0.045, 0.035, 1.6
runs, i = [], 0
while i < len(active):
    if active[i]:
        j = i
        while j < len(active) and active[j]:
            j += 1
        runs.append([times[i], times[min(j, len(times) - 1)]])
        i = j
    else:
        i += 1

merged = []
for r in runs:
    if merged and r[0] - merged[-1][1] < MERGE_GAP:
        merged[-1][1] = r[1]
    else:
        merged.append(r)


def split_long(t0, t1):
    """An over-long run is a phrase, not a note. Split it at internal energy
    minima found on a smoothed envelope."""
    a, b = int(t0 * sr / HOP), int(t1 * sr / HOP)
    seg = edb[a:b]
    if len(seg) < 20:
        return [[t0, t1]]
    sm = sig.savgol_filter(seg, min(51, len(seg) // 2 * 2 - 1), 2)
    inv = -sm
    pk, _ = sig.find_peaks(inv, distance=int(0.09 * sr / HOP),
                           prominence=0.30 * (sm.max() - sm.min() + 1e-9))
    if len(pk) == 0:
        return [[t0, t1]]
    cuts = [t0] + [times[a + p] for p in pk] + [t1]
    return [[cuts[k], cuts[k + 1]] for k in range(len(cuts) - 1)]


events = []
for r in merged:
    if (r[1] - r[0]) > MAX_DUR:
        events.extend(split_long(r[0], r[1]))
    else:
        events.append(r)
events = [r for r in events if (r[1] - r[0]) >= MIN_DUR]
print(f"{len(runs)} raw runs → {len(merged)} merged → {len(events)} events "
      f"≥{MIN_DUR*1000:.0f} ms (long runs split at internal minima)")


# --- feature helpers ---------------------------------------------------------

def am_rate(x):
    """Dominant amplitude-modulation frequency of an event, 8–220 Hz.

    Must find a genuine autocorrelation PEAK: a smooth envelope has a
    monotonically decaying ACF, so a plain argmax just returns the smallest
    allowed lag and reports a rattle where there is none.
    """
    if len(x) < 1024:
        return 0.0, 0.0
    env = np.abs(sig.hilbert(x))
    env = sig.decimate(env, 8, ftype="fir", zero_phase=True)
    fs_e = sr / 8
    env = env - env.mean()
    if env.std() < 1e-9:
        return 0.0, 0.0
    ac = np.correlate(env, env, mode="full")[len(env) - 1:]
    ac = ac / (ac[0] + 1e-12)
    lo_lag, hi_lag = int(fs_e / 220), min(int(fs_e / 8), len(ac) - 2)
    if hi_lag <= lo_lag + 2:
        return 0.0, 0.0
    seg = ac[lo_lag:hi_lag]
    pk, props = sig.find_peaks(seg, prominence=0.06)
    if len(pk) == 0:
        return 0.0, 0.0
    best = pk[int(np.argmax(props["prominences"]))]
    return float(fs_e / (best + lo_lag)), float(seg[best])


def shs_f0(Se, fr, fmin=700.0, fmax=5000.0, n_harm=5):
    """Subharmonic summation f0 per frame + a confidence.

    Robust for both near-sinusoidal whistles and harmonic-stack calls, where
    pyin's speech prior does poorly and reports its own fmin back at you.
    """
    cand = np.arange(fmin, fmax, 6.0)
    interp_idx = [np.clip(cand * h / (fr[1] - fr[0]), 0, len(fr) - 1)
                  for h in range(1, n_harm + 1)]
    f0s, conf = [], []
    for t in range(Se.shape[1]):
        col = Se[:, t]
        if col.max() < 1e-8:
            f0s.append(np.nan); conf.append(0.0); continue
        score = np.zeros_like(cand)
        for h, idx in enumerate(interp_idx, start=1):
            score += (0.84 ** (h - 1)) * np.interp(idx, np.arange(len(fr)), col)
        k = int(np.argmax(score))
        f0s.append(float(cand[k]))
        conf.append(float(score[k] / (score.mean() + 1e-12)))
    return np.array(f0s), np.array(conf)


def contour_shape(f0):
    """Classify a pitch contour: flat / rise / fall / arch / v / complex."""
    f = f0[np.isfinite(f0)]
    if len(f) < 4:
        return "none"
    st = 12 * np.log2(f / f[0])
    n = len(st)
    a, b, c = st[:n // 3].mean(), st[n // 3:2 * n // 3].mean(), st[2 * n // 3:].mean()
    span = st.max() - st.min()
    if span < 1.2:
        return "flat"
    if b > a + 0.8 and b > c + 0.8:
        return "arch"
    if b < a - 0.8 and b < c - 0.8:
        return "v"
    if c > a + 1.2:
        return "rise"
    if c < a - 1.2:
        return "fall"
    return "complex"


# --- per-event features ------------------------------------------------------
PAD = 0.015
fr = librosa.fft_frequencies(sr=sr, n_fft=N_FFT)
rows = []
for idx, (t0, t1) in enumerate(events):
    a = max(0, int((t0 - PAD) * sr))
    b = min(len(y), int((t1 + PAD) * sr))
    seg_clean, seg_band = birds[a:b], birds_raw[a:b]
    if len(seg_clean) < 256:
        continue

    Se = np.abs(librosa.stft(seg_clean, n_fft=N_FFT, hop_length=HOP))
    spec = Se.mean(axis=1)
    tot = spec.sum() + 1e-12
    cum = np.cumsum(spec) / tot
    f_lo = float(fr[np.searchsorted(cum, 0.05)])
    f_hi = float(fr[np.searchsorted(cum, 0.95)])
    f_peak = float(fr[int(np.argmax(spec))])
    centroid = float((fr * spec).sum() / tot)
    bandwidth = float(np.sqrt(((fr - centroid) ** 2 * spec).sum() / tot))
    flatness = float(librosa.feature.spectral_flatness(S=Se).mean())

    # Only trust f0 on frames carrying real level within the event.
    fe = Se.sum(axis=0)
    keep = fe > 0.35 * fe.max()
    f0t, cft = shs_f0(Se, fr)
    f0t = np.where(keep & (cft > 3.0), f0t, np.nan)
    fv = f0t[np.isfinite(f0t)]

    if len(fv) >= 3:
        f0_med = float(np.median(fv))
        f0_min, f0_max = float(fv.min()), float(fv.max())
        f0_start, f0_end = float(np.median(fv[:3])), float(np.median(fv[-3:]))
        sweep_st = float(12 * np.log2(f0_end / f0_start))
        span_st = float(12 * np.log2(f0_max / f0_min))
        conf = float(np.median(cft[np.isfinite(f0t)]))
        shape = contour_shape(f0t)
    else:
        f0_med = f0_min = f0_max = sweep_st = span_st = 0.0
        conf, shape = 0.0, "none"

    amr, amd = am_rate(seg_band)
    rows.append(dict(
        id=idx, t0=round(float(t0), 4), t1=round(float(t1), 4),
        dur=round(float(t1 - t0), 4),
        rms_db=round(float(20 * np.log10(np.sqrt((seg_clean ** 2).mean()) + 1e-12)), 2),
        peak_db=round(float(20 * np.log10(np.abs(seg_clean).max() + 1e-12)), 2),
        f_peak=round(f_peak, 1), f_lo=round(f_lo, 1), f_hi=round(f_hi, 1),
        centroid=round(centroid, 1), bandwidth=round(bandwidth, 1),
        flatness=round(flatness, 5),
        f0_med=round(f0_med, 1), f0_min=round(f0_min, 1), f0_max=round(f0_max, 1),
        sweep_st=round(sweep_st, 2), span_st=round(span_st, 2),
        f0_conf=round(conf, 2), shape=shape,
        am_rate=round(amr, 1), am_depth=round(amd, 3),
    ))

with open("events.json", "w") as f:
    json.dump(rows, f, indent=1)
hdr = list(rows[0].keys())
with open("events.csv", "w") as f:
    f.write(",".join(hdr) + "\n")
    for r in rows:
        f.write(",".join(str(r[k]) for k in hdr) + "\n")

d = np.array([r["dur"] for r in rows])
print(f"wrote {len(rows)} events → events.csv / events.json")
print(f"durations: min {d.min():.3f} med {np.median(d):.3f} max {d.max():.3f}"
      f"  total {d.sum():.1f}s ({100*d.sum()/dur:.0f}% active)")
am = np.array([r["am_rate"] for r in rows])
print(f"AM detected on {int((am > 0).sum())}/{len(rows)} events; "
      f"of those med {np.median(am[am > 0]):.0f} Hz")
from collections import Counter
print("contour shapes:", dict(Counter(r["shape"] for r in rows)))
