"""A quick audible tour of the instrument: every sample in order, grouped by
voice, so the library can be heard rather than read off a table."""
import json
import numpy as np
import soundfile as sf
import librosa

SR = 48000
man = json.load(open("instrument.json"))
out = [np.zeros(int(0.3 * SR), np.float32)]
index = []
t = 0.3


def add(x, gap):
    global t
    out.append(x.astype(np.float32))
    out.append(np.zeros(int(gap * SR), np.float32))
    t_start = t
    t += len(x) / SR + gap
    return t_start


for vname, v in man["voices"].items():
    for i, s in enumerate(v["samples"]):
        y, _ = librosa.load(s["file"], sr=SR, mono=True)
        y *= 0.7 / (np.abs(y).max() + 1e-9)
        st = add(y, 0.35)
        index.append((round(st, 2), f"{vname}_{i+1:02d}",
                      f'{s["note"]} {s["cents"]:+.0f}¢ {s["dur_s"]*1000:.0f}ms {s["shape"]}'))
    t += 0.55
    out.append(np.zeros(int(0.55 * SR), np.float32))

for nname, nd in man["noise"].items():
    y, _ = librosa.load(nd["file"], sr=SR, mono=True)
    y *= 0.7 / (np.abs(y).max() + 1e-9)
    st = add(y, 0.6)
    index.append((round(st, 2), nname, nd["desc"][:52]))

sig = np.concatenate(out)
sf.write("render/instrument_tour.wav", sig, SR, subtype="PCM_16")
print(f"{len(index)} samples, {len(sig)/SR:.1f}s → render/instrument_tour.wav\n")
for st, name, desc in index:
    print(f"  {st:6.2f}s  {name:<14} {desc}")
json.dump([{"t": a, "name": b, "desc": c} for a, b, c in index],
          open("render/instrument_tour_index.json", "w"), indent=1)
