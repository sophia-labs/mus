"""One-off visualiser for an excerpt of the Boléro render.

Scrolling spectrogram over the whole-piece crescendo arc. The arc matters for
this piece specifically: Boléro has exactly one dynamic event, a single
unbroken climb across 340 bars, so showing where an excerpt sits inside it is
showing the only structural argument the piece makes.

Frames are pushed straight to ffmpeg's stdin as raw RGBA — 1500 PNGs on disk
would be slower than the drawing.
"""
import subprocess
import sys
import numpy as np
import soundfile as sf
import librosa
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import gridspec

SRC = "render/bolero.wav"
OUT = "render/bolero_visual.mp4"
T0, T1 = 120.0, 180.0          # the excerpt
FPS = 30
SR = 48000
WIN = 7.0                      # seconds of spectrogram on screen
PLAYHEAD = 0.68                # where "now" sits across the window
FMAX = 9000
BG = "#07070c"
FG = "#e8e2d8"
ACCENT = "#ffb347"
DIM = "#4a4550"

# --- score geometry, so the panel can name what you are hearing --------------
TEMPO, BEATS = 66.0, 3
BAR_S = BEATS * 60.0 / TEMPO                      # 2.727 s
TOTAL_BARS = 340
FIRST, ORCH_N = 5, 17
THEMES = ["A", "A", "B", "B", "A", "A", "B", "B", "A",
          "A", "B", "B", "A", "A", "B", "B", "A"]
LABELS = ["flute", "clarinet", "bassoon", "E♭ clarinet", "oboe d'amore",
          "trumpet + flute", "tenor sax", "soprano sax", "the organ chord",
          "double reeds", "trombone", "woodwinds", "tutti I", "tutti II",
          "tutti III", "tutti IV", "tutti V"]


def bar_at(t):
    return int(t / BAR_S) + 1


def statement_at(bar):
    if bar < FIRST:
        return None, "introduction"
    i = (bar - FIRST) // 18
    if i >= ORCH_N:
        if bar >= 335:
            return None, "coda"
        if bar >= 327:
            return None, "E major"
        return None, "climax"
    return i + 1, f"{LABELS[i]} · theme {THEMES[i]}"


# --- whole-piece envelope, read in blocks so nothing large is held -----------
info = sf.info(SRC)
dur_total = info.frames / info.samplerate
env, block = [], 1 << 15
for b in sf.blocks(SRC, blocksize=block, dtype="float32", always_2d=True):
    env.append(float(np.sqrt((b ** 2).mean()) + 1e-9))
env = np.array(env)
env_t = np.arange(len(env)) * block / info.samplerate
env_db = 20 * np.log10(env + 1e-9)
env_db = np.convolve(env_db, np.ones(9) / 9, mode="same")
print(f"whole piece {dur_total:.1f}s, envelope {env_db.min():.1f}..{env_db.max():.1f} dB")

# --- excerpt spectrogram ------------------------------------------------------
pad = WIN
y, _ = librosa.load(SRC, sr=SR, mono=True,
                    offset=max(0.0, T0 - pad), duration=(T1 - T0) + 2 * pad)
N_FFT, HOP = 2048, 256
S = np.abs(librosa.stft(y, n_fft=N_FFT, hop_length=HOP))
Sdb = librosa.amplitude_to_db(S, ref=np.max(S))
freqs = librosa.fft_frequencies(sr=SR, n_fft=N_FFT)
fsel = freqs <= FMAX
Sdb = Sdb[fsel]
spec_t0 = max(0.0, T0 - pad)
frames_per_s = SR / HOP

# --- figure -------------------------------------------------------------------
fig = plt.figure(figsize=(19.2, 10.8), dpi=100, facecolor=BG)
gs = gridspec.GridSpec(3, 1, height_ratios=[0.7, 6.2, 1.5], hspace=0.28,
                       left=0.045, right=0.985, top=0.97, bottom=0.07)

ax_t = fig.add_subplot(gs[0]); ax_t.axis("off")
# Both in axes coords — mixing data and axes coords collided the subtitle
# into the title.
_title = ax_t.text(0.0, 0.62, "BOLÉRO", color=FG, fontsize=34,
                   fontweight="bold", family="DejaVu Sans", va="center",
                   transform=ax_t.transAxes)
# Measure the title rather than guessing an offset — two guesses collided.
fig.canvas.draw()
_bb = _title.get_window_extent().transformed(ax_t.transAxes.inverted())
ax_t.text(_bb.x1 + 0.014, 0.58, "Ravel · for birds recorded in Aigua, Uruguay",
          color=DIM, fontsize=15, va="center", transform=ax_t.transAxes)
lbl_right = ax_t.text(1.0, 0.62, "", color=ACCENT, fontsize=17, ha="right",
                      va="center", transform=ax_t.transAxes)

ax = fig.add_subplot(gs[1], facecolor=BG)
n_win = int(WIN * frames_per_s)
im = ax.imshow(Sdb[:, :n_win], origin="lower", aspect="auto", cmap="magma",
               vmin=-72, vmax=0, extent=[0, WIN, 0, FMAX / 1000.0],
               interpolation="bilinear")
ax.axvline(WIN * PLAYHEAD, color=FG, lw=1.1, alpha=0.85)
ax.set_ylabel("kHz", color=DIM, fontsize=13)
ax.tick_params(colors=DIM, labelsize=11)
for sp in ax.spines.values():
    sp.set_color("#1b1b24")
ax.set_xticks([])

ax_e = fig.add_subplot(gs[2], facecolor=BG)
ax_e.plot(env_t, env_db, color=DIM, lw=1.0)
ax_e.fill_between(env_t, env_db, env_db.min() - 2, color="#191722")
for i in range(ORCH_N):
    ax_e.axvline((FIRST - 1 + 18 * i) * BAR_S, color="#2a2733", lw=0.7)
marker = ax_e.axvline(T0, color=ACCENT, lw=1.8)
ax_e.set_xlim(0, dur_total)
ax_e.set_ylim(env_db.min() - 2, env_db.max() + 2)
ax_e.set_xlabel("the whole 15:27 — one unbroken crescendo, 340 bars",
                color=DIM, fontsize=12)
ax_e.tick_params(colors=DIM, labelsize=10)
ax_e.set_yticks([])
for sp in ax_e.spines.values():
    sp.set_color("#1b1b24")

fig.canvas.draw()
w, h = fig.canvas.get_width_height()

ff = subprocess.Popen(
    ["ffmpeg", "-y", "-v", "error",
     "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}", "-r", str(FPS),
     "-i", "-",
     "-ss", str(T0), "-t", str(T1 - T0), "-i", SRC,
     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium",
     "-c:a", "aac", "-b:a", "224k", "-shortest", OUT],
    stdin=subprocess.PIPE)

n_frames = int((T1 - T0) * FPS)
for k in range(n_frames):
    t = T0 + k / FPS
    left = t - WIN * PLAYHEAD
    a = int((left - spec_t0) * frames_per_s)
    a = max(0, min(a, Sdb.shape[1] - n_win - 1))
    im.set_data(Sdb[:, a:a + n_win])
    marker.set_xdata([t, t])
    bar = bar_at(t)
    num, name = statement_at(bar)
    tag = f"bar {bar} / 340   ·   " + (f"{num}. {name}" if num else name)
    lbl_right.set_text(tag)
    fig.canvas.draw()
    ff.stdin.write(fig.canvas.buffer_rgba())
    if k % 150 == 0:
        print(f"  frame {k}/{n_frames}  t={t:.1f}s  {tag}", flush=True)

ff.stdin.close()
rc = ff.wait()
print(f"ffmpeg exit {rc} -> {OUT}")
