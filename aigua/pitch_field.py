"""Phase 4b: what key is this place in?

Derives a tonal centre from the corpus itself rather than imposing one:
an energy-weighted, wrap-around kernel density over pitch class, correlated
against Krumhansl–Schmuckler profiles. Also measures the melodic intervals
the birds actually use between successive calls.
"""
import json
import numpy as np
import librosa
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
ev = json.load(open("events.json"))
p = [e for e in ev if e["f0_med"] > 0 and e["f0_conf"] > 3.5 and e["id"] != 14]
print(f"{len(p)}/{len(ev)} events confidently pitched")

midi = np.array([69 + 12 * np.log2(e["f0_med"] / 440.0) for e in p])
w = np.array([e["dur"] * 10 ** (e["rms_db"] / 20) for e in p])
w /= w.sum()
pc = midi % 12.0

# wrap-around KDE over pitch class
grid = np.linspace(0, 12, 1201)
SIGMA = 0.45          # semitones — wide enough that birds needn't be in tune
dens = np.zeros_like(grid)
for x, wi in zip(pc, w):
    for off in (-12, 0, 12):
        dens += wi * np.exp(-0.5 * ((grid - (x + off)) / SIGMA) ** 2)
dens /= dens.max()

peaks = []
for i in range(1, len(grid) - 1):
    if dens[i] > dens[i - 1] and dens[i] >= dens[i + 1] and dens[i] > 0.35:
        peaks.append((grid[i], dens[i]))
peaks = [pk for pk in peaks if pk[0] < 12.0]
print("\npitch-class density peaks (weighted by duration × level):")
for x, d in sorted(peaks, key=lambda t: -t[1]):
    n = NOTE_NAMES[int(round(x)) % 12]
    cents = (x - round(x)) * 100
    print(f"  {x:5.2f}  ≈ {n:<2} {cents:+6.1f}¢   strength {d:.2f}")

# 12-TET chroma for key correlation
chroma = np.zeros(12)
for x, wi in zip(pc, w):
    lo, frac = int(np.floor(x)) % 12, x - np.floor(x)
    chroma[lo] += wi * (1 - frac)
    chroma[(lo + 1) % 12] += wi * frac
chroma /= chroma.sum()

KS_MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KS_MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def corr(a, b):
    a, b = a - a.mean(), b - b.mean()
    return float((a * b).sum() / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-12))


scores = []
for t in range(12):
    scores.append((corr(chroma, np.roll(KS_MAJ, t)), f"{NOTE_NAMES[t]} major"))
    scores.append((corr(chroma, np.roll(KS_MIN, t)), f"{NOTE_NAMES[t]} minor"))
scores.sort(reverse=True)
print("\nkey correlation (Krumhansl–Schmuckler):")
for s, k in scores[:5]:
    print(f"  {k:<10} r = {s:+.3f}")

print("\nchroma:")
for i in np.argsort(-chroma):
    bar = "█" * int(round(chroma[i] * 120))
    print(f"  {NOTE_NAMES[i]:<2} {chroma[i]*100:5.1f}%  {bar}")

# melodic intervals actually used between consecutive calls
p_sorted = sorted(p, key=lambda e: e["t0"])
iv = []
for a, b in zip(p_sorted, p_sorted[1:]):
    if b["t0"] - a["t1"] < 2.0:
        iv.append(12 * np.log2(b["f0_med"] / a["f0_med"]))
iv = np.array(iv)
print(f"\n{len(iv)} consecutive-call intervals; |median| {np.median(np.abs(iv)):.2f} st")
hist, edges = np.histogram(iv, bins=np.arange(-24.5, 25.5, 1.0))
top = np.argsort(-hist)[:8]
print("most common intervals (semitones):")
for i in sorted(top, key=lambda i: -hist[i]):
    if hist[i]:
        print(f"  {edges[i]+0.5:+5.0f} st  ×{hist[i]}")

# internal sweep range — how far a single call travels
sw = np.array([e["span_st"] for e in p])
print(f"\nwithin-call pitch span: med {np.median(sw):.1f} st  "
      f"p90 {np.percentile(sw,90):.1f} st  max {sw.max():.1f} st")

fig, ax = plt.subplots(2, 1, figsize=(13, 7))
ax[0].plot(grid, dens, lw=1.6)
ax[0].fill_between(grid, dens, alpha=0.25)
for x, d in peaks:
    ax[0].annotate(f"{NOTE_NAMES[int(round(x))%12]}", (x, d),
                   textcoords="offset points", xytext=(0, 6), ha="center")
ax[0].set_xticks(range(13))
ax[0].set_xticklabels(NOTE_NAMES + ["C"])
ax[0].set_title("Aigua pitch-class field (energy-weighted, σ=0.45 st)")
ax[0].grid(alpha=0.3)
ax[1].hist(iv, bins=np.arange(-24.5, 25.5, 1.0), color="tab:green", alpha=0.8)
ax[1].set_xlabel("semitones between consecutive calls")
ax[1].set_title("melodic intervals the birds actually use")
ax[1].grid(alpha=0.3)
plt.tight_layout()
plt.savefig("pitch_field.png", dpi=100)
print("\nwrote pitch_field.png")
