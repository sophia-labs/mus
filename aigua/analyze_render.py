"""Look at a stereo render: spectrogram, level, and stereo placement over time.
The pan trace is what lets a gesture like 'sweeping left to right' be checked
rather than assumed."""
import sys
import numpy as np
import librosa
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

path = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else path.replace(".wav", "_analysis.png")
SR, N_FFT, HOP = 48000, 2048, 256

y, sr = librosa.load(path, sr=SR, mono=False)
if y.ndim == 1:
    y = np.stack([y, y])
L, R = y[0], y[1]
mid = (L + R) / 2
dur = len(mid) / sr

S = librosa.amplitude_to_db(
    np.abs(librosa.stft(mid, n_fft=N_FFT, hop_length=HOP)), ref=np.max)
freqs = librosa.fft_frequencies(sr=sr, n_fft=N_FFT)
times = librosa.times_like(S, sr=sr, hop_length=HOP)

fl = librosa.feature.rms(y=L, frame_length=N_FFT, hop_length=HOP)[0]
frr = librosa.feature.rms(y=R, frame_length=N_FFT, hop_length=HOP)[0]
tt = librosa.times_like(fl, sr=sr, hop_length=HOP)
pan = (frr - fl) / (frr + fl + 1e-9)                 # -1 hard L, +1 hard R
tot = 20 * np.log10((fl + frr) / 2 + 1e-12)
loud = tot > (tot.max() - 34)

# band energy split, to confirm the low material is really there
def band_db(lo, hi):
    m = (freqs >= lo) & (freqs < hi)
    Sm = np.abs(librosa.stft(mid, n_fft=N_FFT, hop_length=HOP))[m]
    return 20 * np.log10(np.sqrt((Sm ** 2).sum(axis=0)) + 1e-12)


fig, ax = plt.subplots(4, 1, figsize=(20, 13),
                       gridspec_kw={"height_ratios": [3.2, 1, 1, 1]})
ax[0].imshow(S[freqs <= 10000], origin="lower", aspect="auto",
             extent=[0, dur, 0, 10000], cmap="magma", vmin=-70, vmax=0)
ax[0].set_ylabel("Hz")
ax[0].set_title(path)

ax[1].plot(tt, tot, lw=0.8)
ax[1].set_ylabel("level dB")
ax[1].grid(alpha=0.3)

ax[2].plot(tt[loud], pan[loud], ".", ms=1.6, color="tab:purple")
ax[2].axhline(0, color="k", lw=0.5)
ax[2].set_ylim(-1.05, 1.05)
ax[2].set_ylabel("pan  L ← → R")
ax[2].grid(alpha=0.3)

for lo, hi, lab in [(20, 120, "20–120"), (120, 500, "120–500"),
                    (500, 2000, "0.5–2k"), (2000, 10000, "2–10k")]:
    ax[3].plot(tt[:len(band_db(lo, hi))], band_db(lo, hi), lw=0.8, label=lab)
ax[3].legend(fontsize=7, ncol=4)
ax[3].set_ylabel("band dB")
ax[3].set_xlabel("seconds")
ax[3].grid(alpha=0.3)
for a in ax[1:]:
    a.set_xlim(0, dur)
plt.tight_layout()
plt.savefig(out, dpi=85)

corr = float(np.corrcoef(L, R)[0, 1])
print(f"{path}: {dur:.1f}s  peak {20*np.log10(np.abs(y).max()+1e-12):.1f} dBFS  "
      f"rms {20*np.log10(np.sqrt((mid**2).mean())+1e-12):.1f} dBFS")
print(f"L/R correlation {corr:+.3f}   pan range [{pan[loud].min():+.2f},"
      f" {pan[loud].max():+.2f}]")
lo_share = 10 ** (band_db(20, 300).max() / 20)
print(f"wrote {out}")
