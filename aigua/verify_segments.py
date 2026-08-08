"""Draw detected event boundaries over the denoised spectrogram, so the
segmentation can actually be eyeballed rather than trusted."""
import json
import numpy as np
import librosa
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SR, N_FFT, HOP = 48000, 1024, 128
y, sr = librosa.load("aigua_birds.wav", sr=SR, mono=True)
dur = len(y) / sr
S = librosa.amplitude_to_db(
    np.abs(librosa.stft(y, n_fft=N_FFT, hop_length=HOP)), ref=np.max)
freqs = librosa.fft_frequencies(sr=sr, n_fft=N_FFT)
fmask = freqs <= 9000
ev = json.load(open("events.json"))

PANELS = 4
seg = dur / PANELS
fig, axes = plt.subplots(PANELS, 1, figsize=(24, 4.2 * PANELS))
for i in range(PANELS):
    t0, t1 = i * seg, (i + 1) * seg
    ax = axes[i]
    c0 = int(t0 * sr / HOP)
    c1 = int(t1 * sr / HOP)
    ax.imshow(S[fmask][:, c0:c1], origin="lower", aspect="auto",
              extent=[t0, t1, 0, 9000], cmap="magma", vmin=-66, vmax=0)
    for e in ev:
        if e["t1"] < t0 or e["t0"] > t1:
            continue
        ax.axvspan(e["t0"], e["t1"], color="cyan", alpha=0.13)
        ax.axvline(e["t0"], color="cyan", lw=0.8)
        ax.axvline(e["t1"], color="deepskyblue", lw=0.6, ls=":")
        ax.text(e["t0"], 8300, f'{e["id"]}', color="w", fontsize=7)
        ax.text(e["t0"], 7600, e["shape"][:4], color="cyan", fontsize=6)
        if e["f0_med"]:
            ax.plot([e["t0"], e["t1"]], [e["f0_med"]] * 2,
                    color="lime", lw=1.1, alpha=0.85)
    ax.set_xlim(t0, t1)
    ax.set_ylabel("Hz")
    ax.set_xticks(np.arange(np.floor(t0), t1 + 0.01, 0.5))
    ax.tick_params(labelsize=7)
    ax.grid(axis="x", color="w", alpha=0.15, lw=0.4)
axes[-1].set_xlabel("seconds")
plt.tight_layout()
plt.savefig("verify_segments.png", dpi=80)
print("wrote verify_segments.png")
