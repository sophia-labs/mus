# Aigua — a worked example

A 56-second field recording made in Aigua, Uruguay on 2026-08-08 (birds, wind,
and one car), analysed into a playable sample instrument and used to score two
pieces in [MUS-A](../SPEC-AUDIO.md). Nothing in either piece comes from any
other source.

## The source

`source/aigua-birds-2026-08-08.m4a` — 56.32 s, mono, 48 kHz, AAC at 62 kbps.

That bitrate matters: **nothing above ~9 kHz survives the encode**, so the top
octave of the birdsong is simply absent. Everything downstream is bounded by
that. 89% of the file's energy sits below 400 Hz — wind and the car — and the
birds live in a thin band from 900 Hz to 8 kHz.

## Pipeline

Needs `ffmpeg`, and a Python env with `numpy scipy librosa soundfile
matplotlib scikit-learn music21`. On Intel macOS pin `numba<0.61` — recent
`llvmlite` ships no x86_64 wheels and will try to build LLVM from source.

```bash
# 0. decode to float WAV
ffmpeg -i source/aigua-birds-2026-08-08.m4a -ac 1 -ar 48000 -c:a pcm_f32le aigua_raw.wav

python recon.py             # → recon_spectrogram.png    what is actually in here?
python segment.py           # → events.csv/json          band split, denoise, 100 events
python verify_segments.py   # → verify_segments.png      eyeball the segmentation
python cluster.py           # → clusters.png             7 families + contact sheet
python build_instrument.py  # → instrument.json, samples/
python pitch_field.py       # → pitch_field.png          what key is this place in?
python make_tour.py         # → render/instrument_tour.wav

# render a score
python ../mus_audio.py aigua.mus      -o render/aigua.wav
python ../mus_audio.py aigua_gecs.mus -o render/aigua_gecs.wav
python analyze_render.py render/aigua.wav
```

Each stage writes an artefact you can look at. That's deliberate — the two
substantive bugs found while building this (a stuck noise gate, a reverb bus
30 dB too hot) were both invisible in the numbers and obvious in a plot.

## What the analysis found

**Seven call families**, clustered on scalar acoustics + 8-point pitch contour
+ 20-band mel silhouette, Ward linkage, verified against a per-cluster
spectrogram contact sheet:

| voice | n | median f0 | character |
|---|---|---|---|
| `buzz` | 5 | 886 Hz | dense low harmonic stack, growly |
| `chup` | 3 | 1030 Hz | short soft low chirp, percussive |
| `mid` | 19 | 1216 Hz | mid call, strong low partial |
| `call` | 35 | 1546 Hz | the signature call — long arched fundamental + full ladder |
| `bright` | 21 | 1642 Hz | shorter bright cousin, fast AM |
| `glide` | 10 | 3494 Hz | clean high tonal sweep — the most musical, most pitchable |
| `tick` | 7 | 1360 Hz | very short bright transient |

Plus `car` (a broadband pass-by at 9.05–10.4 s) and `sub` (the low bed).

**The birds are not in a key, they're in a band.** F♯–A♯ holds 71% of the
energy as a contiguous smear. Krumhansl–Schmuckler correlates best with G minor
at only r = +0.39, which is the number you get when there is no tonal system to
find. The energy-weighted pitch-class density has three peaks, and none of them
are on the grid:

```
A  +22¢   strength 1.00
G  −47¢   strength 0.86
D♯ −44¢   strength 0.47
```

**They are gesture instruments, not note instruments.** Median within-call
pitch span is **18.7 semitones** (p90 = 26.1, max = 31.9). A single call
travels more than an octave and a half. This is why MUS-A's `->` sweep is the
native gesture here rather than an effect.

## The two scores

| | |
|---|---|
| `aigua.mus` | 56 bars, 2:29. Tuned to **A = 445.6 Hz** — the pitch of the place. Harmony from the three density peaks above, i.e. a cluster rather than a triad. |
| `aigua_gecs.mus` | 78 bars, 2:01, 160 BPM. The deliberate inverse: **no tuning line**, everything snapped to 12-TET, clipped to −10.8 dBFS. A full drum kit built out of the same birds — kick is a `buzz` dropped ~50 semitones with an exponential pitch envelope, snare is the car gated to 190 ms, hats are `tick` pitched up two octaves, clap is a `chup` at 5-bit. |

Same 34 samples, same notation, same renderer. The difference is the score and
one header line.

## Caveats

- **Species are not identified.** The families are acoustic clusters, not taxa.
  Several may be one bird's repertoire; the `call` family's 35 members are
  plausibly a single persistent individual.
- The `sub`/`car` split is a band split, not source separation — wind, the car,
  and handling noise are not disentangled from each other below 300 Hz.
- Cluster `k = 7` was chosen by looking at the contact sheet, not by a
  selection criterion.
- Sample exemplars are picked by a hand-weighted score (level, temporal
  isolation, pitch confidence), which is a heuristic, not a criterion.
- Every mix judgement in both pieces was made by reading spectrograms and
  stereo-correlation traces. No one has listened to them critically.

## Aigua Analysis v2

The scripts above are now treated as the historical v1 analysis rather than a
mutable source of universal facts. [`ANALYSIS-V2.md`](ANALYSIS-V2.md) describes
and implements the next scientific layer:

- content-addressed artifacts and write-once run receipts;
- separate event hypotheses, observations, model memberships, human curation,
  claims, and compositional interpretations;
- corrected descriptor semantics (`am_depth` is preserved as an envelope
  autocorrelation peak, not falsely promoted to modulation depth);
- a MUS audio ontology plus SHACL shapes;
- independent historical-style and PCEN segmentation lanes with explicit
  split/merge reconciliation;
- SHS, pYIN, and dominant-ridge pitch trajectories with consensus refusal for
  octave conflicts and estimator disagreement;
- continuous gesture bundles with spectral, FM, AM, envelope, and consensus
  pitch trajectories;
- cluster co-assignment and stability tools for testing the seven-family
  hypothesis.

Preserve the current outputs as an immutable research object:

```bash
python import_research_object.py \
  --config research/aigua-v1-import.json

python -m mus_analysis verify --store research-object
```

The generated `research-object/` directory is local and reproducible. Its
`projections/aigua-v1.nt` file is the first `gardend`-ready RDF face of Aigua.
