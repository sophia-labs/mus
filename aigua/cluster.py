"""Phase 3: cluster events into sound families.

Feature vector deliberately mixes three descriptions of an event, because
each alone mis-groups these calls:
  - scalar acoustics (duration, pitch, brightness, AM)
  - pitch-contour morphology (8-point normalised f0 track)
  - timbre (20-band mel silhouette, level-normalised)
Ward linkage on the standardised, group-weighted stack.
"""
import json
import numpy as np
import scipy.signal as sig
import librosa
import soundfile as sf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import AgglomerativeClustering

SR, N_FFT, HOP = 48000, 1024, 128
K = 7
PAD = 0.015

birds, sr = librosa.load("aigua_birds.wav", sr=SR, mono=True)
raw, _ = librosa.load("aigua_raw.wav", sr=SR, mono=True)
ev = json.load(open("events.json"))
fr = librosa.fft_frequencies(sr=sr, n_fft=N_FFT)
melfb = librosa.filters.mel(sr=sr, n_fft=N_FFT, n_mels=20, fmin=700, fmax=11000)


def shs_track(Se):
    cand = np.arange(700.0, 5000.0, 6.0)
    idxs = [np.clip(cand * h / (fr[1] - fr[0]), 0, len(fr) - 1) for h in range(1, 6)]
    out = []
    for t in range(Se.shape[1]):
        col = Se[:, t]
        if col.max() < 1e-8:
            out.append(np.nan); continue
        sc = np.zeros_like(cand)
        for h, ix in enumerate(idxs, start=1):
            sc += (0.84 ** (h - 1)) * np.interp(ix, np.arange(len(fr)), col)
        out.append(cand[int(np.argmax(sc))])
    return np.array(out)


contours, mels, scal = [], [], []
for e in ev:
    a = max(0, int((e["t0"] - PAD) * sr))
    b = min(len(birds), int((e["t1"] + PAD) * sr))
    segc = birds[a:b]
    Se = np.abs(librosa.stft(segc, n_fft=N_FFT, hop_length=HOP))
    fe = Se.sum(axis=0)
    keep = fe > 0.35 * (fe.max() + 1e-12)

    f0 = shs_track(Se)
    f0 = np.where(keep, f0, np.nan)
    good = f0[np.isfinite(f0)]
    if len(good) >= 4:
        st = 12 * np.log2(good / np.median(good))
        c8 = np.interp(np.linspace(0, 1, 8), np.linspace(0, 1, len(st)), st)
    else:
        c8 = np.zeros(8)
    contours.append(c8)

    m = melfb @ (Se ** 2)
    m = librosa.power_to_db(m.mean(axis=1) + 1e-12)
    mels.append(m - m.max())

    scal.append([
        np.log(e["dur"]),
        np.log(max(e["f0_med"], 1.0)),
        e["span_st"], e["sweep_st"],
        np.log(e["centroid"]), np.log(e["bandwidth"]),
        np.log(e["flatness"] + 1e-6),
        e["am_rate"] / 100.0, e["am_depth"],
        np.log(max(e["f_hi"], 1.0)),
        e["centroid"] / max(e["f0_med"], 1.0),   # harmonic reach
    ])

Xs = StandardScaler().fit_transform(np.array(scal))
Xc = StandardScaler().fit_transform(np.array(contours))
Xm = StandardScaler().fit_transform(np.array(mels))
X = np.hstack([Xs * 1.0, Xc * 0.55, Xm * 0.45])

labels = AgglomerativeClustering(n_clusters=K, linkage="ward").fit_predict(X)

# Order clusters by median f0 so ids read low→high, with noise-like last.
order, stats = [], {}
for c in range(K):
    m = labels == c
    f0s = [ev[i]["f0_med"] for i in np.where(m)[0] if ev[i]["f0_med"] > 0]
    stats[c] = dict(n=int(m.sum()),
                    f0=float(np.median(f0s)) if f0s else 0.0,
                    dur=float(np.median([ev[i]["dur"] for i in np.where(m)[0]])),
                    flat=float(np.median([ev[i]["flatness"] for i in np.where(m)[0]])))
order = sorted(range(K), key=lambda c: (stats[c]["flat"] > 0.0009, stats[c]["f0"]))
remap = {old: new for new, old in enumerate(order)}
labels = np.array([remap[l] for l in labels])

for e, l in zip(ev, labels):
    e["cluster"] = int(l)
json.dump(ev, open("events.json", "w"), indent=1)

print(f"{K} clusters over {len(ev)} events\n")
print(f"{'cl':>3} {'n':>4} {'f0med':>7} {'dur':>6} {'cent':>6} {'bw':>6} "
      f"{'flat':>8} {'am':>6} {'span':>6} {'shapes'}")
from collections import Counter
for c in range(K):
    ii = np.where(labels == c)[0]
    g = [ev[i] for i in ii]
    f0s = [x["f0_med"] for x in g if x["f0_med"] > 0]
    sh = Counter(x["shape"] for x in g).most_common(3)
    print(f"{c:>3} {len(ii):>4} "
          f"{(np.median(f0s) if f0s else 0):>7.0f} "
          f"{np.median([x['dur'] for x in g]):>6.3f} "
          f"{np.median([x['centroid'] for x in g]):>6.0f} "
          f"{np.median([x['bandwidth'] for x in g]):>6.0f} "
          f"{np.median([x['flatness'] for x in g]):>8.5f} "
          f"{np.median([x['am_rate'] for x in g]):>6.0f} "
          f"{np.median([x['span_st'] for x in g]):>6.1f} "
          f"{sh}")
    print(f"      ids: {[int(x['id']) for x in g][:22]}")

# --- contact sheet -----------------------------------------------------------
COLS = 8
fig, axes = plt.subplots(K, COLS, figsize=(COLS * 2.5, K * 2.3))
for c in range(K):
    ii = [i for i in np.where(labels == c)[0]]
    ii = sorted(ii, key=lambda i: -ev[i]["rms_db"])[:COLS]
    for j in range(COLS):
        ax = axes[c, j]
        ax.set_xticks([]); ax.set_yticks([])
        if j >= len(ii):
            ax.axis("off"); continue
        e = ev[ii[j]]
        a = max(0, int((e["t0"] - PAD) * sr))
        b = min(len(birds), int((e["t1"] + PAD) * sr))
        Se = librosa.amplitude_to_db(
            np.abs(librosa.stft(birds[a:b], n_fft=N_FFT, hop_length=HOP)),
            ref=np.max)
        ax.imshow(Se[fr <= 9000], origin="lower", aspect="auto",
                  cmap="magma", vmin=-60, vmax=0)
        ax.set_title(f'#{e["id"]} {e["dur"]*1000:.0f}ms '
                     f'{e["f0_med"]:.0f}Hz {e["shape"][:4]}', fontsize=6.5)
        if j == 0:
            ax.set_ylabel(f"cluster {c}\n(n={int((labels==c).sum())})", fontsize=9)
plt.tight_layout()
plt.savefig("clusters.png", dpi=95)
print("\nwrote clusters.png")
