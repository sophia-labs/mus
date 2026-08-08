"""Phase 1 reconnaissance: what is actually in this recording?

Renders a multi-panel spectrogram so the whole 56 s can be read at usable
time resolution, plus a numeric summary of level / brightness / band energy.
"""
import numpy as np
import librosa
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SR = 48000
y, sr = librosa.load("aigua_raw.wav", sr=SR, mono=True)
dur = len(y) / sr
print(f"duration {dur:.2f}s  sr {sr}  samples {len(y)}")
print(f"peak {np.abs(y).max():.4f}  rms {np.sqrt((y**2).mean()):.5f}  "
      f"dBFS peak {20*np.log10(np.abs(y).max()+1e-12):.1f}")

# DC offset / infrasonic content check
print(f"dc offset {y.mean():+.6f}")

N_FFT, HOP = 2048, 256
S = np.abs(librosa.stft(y, n_fft=N_FFT, hop_length=HOP))
freqs = librosa.fft_frequencies(sr=sr, n_fft=N_FFT)
times = librosa.frames_to_time(np.arange(S.shape[1]), sr=sr, hop_length=HOP)
Sdb = librosa.amplitude_to_db(S, ref=np.max)

# Band energy over time — where does this recording actually live?
bands = [(0, 100), (100, 400), (400, 1000), (1000, 2500),
         (2500, 5000), (5000, 9000), (9000, 16000), (16000, 24000)]
total = (S ** 2).sum() + 1e-12
print("\nband energy share (whole file):")
for lo, hi in bands:
    m = (freqs >= lo) & (freqs < hi)
    print(f"  {lo:>5}-{hi:<5} Hz  {100*(S[m]**2).sum()/total:6.2f}%")

rms = librosa.feature.rms(y=y, frame_length=N_FFT, hop_length=HOP)[0]
cent = librosa.feature.spectral_centroid(S=S, sr=sr)[0]
flat = librosa.feature.spectral_flatness(S=S)[0]
rms_db = 20 * np.log10(rms + 1e-12)
print(f"\nrms dB: min {rms_db.min():.1f}  med {np.median(rms_db):.1f}  max {rms_db.max():.1f}")
print(f"centroid Hz: min {cent.min():.0f}  med {np.median(cent):.0f}  max {cent.max():.0f}")

np.save("recon_cache.npy", {"rms": rms, "cent": cent, "flat": flat,
                            "times": times}, allow_pickle=True)

# --- multi-panel spectrogram -------------------------------------------------
PANELS = 4
seg = dur / PANELS
fig, axes = plt.subplots(PANELS + 1, 1, figsize=(22, 4 * PANELS + 3))
fmax_plot = 12000
fmask = freqs <= fmax_plot

for i in range(PANELS):
    t0, t1 = i * seg, (i + 1) * seg
    sel = (times >= t0) & (times <= t1)
    ax = axes[i]
    ax.imshow(Sdb[fmask][:, sel], origin="lower", aspect="auto",
              extent=[t0, t1, 0, fmax_plot], cmap="magma", vmin=-72, vmax=0)
    ax.set_ylabel("Hz")
    ax.set_xticks(np.arange(np.floor(t0), t1 + 0.01, 1.0))
    ax.grid(axis="x", color="w", alpha=0.18, lw=0.5)
    ax.set_title(f"{t0:.1f}–{t1:.1f} s", fontsize=9, loc="left")

ax = axes[-1]
ax.plot(times, rms_db, lw=0.7, label="RMS dB")
ax.set_xlim(0, dur)
ax.set_ylabel("dBFS")
ax.grid(alpha=0.3)
ax2 = ax.twinx()
ax2.plot(times, cent, lw=0.6, color="tab:red", alpha=0.6)
ax2.set_ylabel("centroid Hz", color="tab:red")
ax.set_xlabel("seconds")
ax.set_xticks(np.arange(0, dur + 0.01, 2.0))

plt.tight_layout()
plt.savefig("recon_spectrogram.png", dpi=90)
print("\nwrote recon_spectrogram.png")
