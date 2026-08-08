# MUS-A — Sample-Bound MUS

*Working spec, draft 0.1. An extension to [`SPEC.md`](./SPEC.md) that binds MUS
tracks to recorded audio instead of instrument names, so the same notation can
score musique concrète. Reference implementation: [`mus_audio.py`](./mus_audio.py).*

## Why this is an extension and not a new format

MUS's core choice — **pitches are absolute** — was made so an LLM could read a
score without inheriting key-signature state. That choice turns out to be
exactly what a sampler needs. `A6` doesn't mean "the sixth degree in context",
it means *this frequency*; and a frequency is precisely the thing you compare
against a sample's measured f0 to get a transposition. So the note grammar needs
no change at all. A MUS file scores a sample instrument as-is.

What's missing isn't notation for notes. It's notation for the things engraved
notation never needed symbols for, because an orchestra does them by being an
orchestra: where a sound sits in the stereo field, how a filter opens across a
phrase, how much of the sound goes to the room. Those are the additions here.

The design constraint was that a MUS-A file must remain a MUS file — readable by
`mus.py`'s parser, diff-friendly, and degrading to something sensible when the
extension is ignored.

## What is unchanged

Everything in `SPEC.md`'s core grammar: pitch, duration, dotted values, tuplets,
ties, rests, chords, tracks and voices, articulations, dynamics, hairpins,
slurs, bar structure, inline `[tempo=…]` changes, sections, system text, `(N×)`
repetition, and the bar-major/track-major views. A MUS-A score is written in the
same notation and read the same way.

## Additions

### 1. Header: tuning and sample pack

```
# tuning: A=445.6
# pack: instrument.json
```

`tuning` sets the reference frequency for A4; default 440. It exists because
field material is rarely at concert pitch, and quantising it away discards
information the recording actually carries. `pack` points at a JSON manifest
describing the available voices and their samples, resolved relative to the
score.

Both ride on the existing `# key: value` header form and are ignored by the
notation converter.

### 2. Instrument declarations carry `key=value` items

`SPEC.md` already gives instruments a parenthetical for clef and transposition.
MUS-A adds `key=value` items to the same list:

```
# instruments:
#   gl = glide (treble, voice=glide, mode=varispeed, send=0.30)
#   sb = sub   (bass, voice=buzz, mode=varispeed, gain=5, send=0.04)
#   cr = car   (perc, sample=samples/car_pass.wav, root=A4, send=0.26)
```

| item | meaning |
|---|---|
| `voice=<name>` | bind to a named voice in the pack (may hold several samples) |
| `sample=<path>` | bind to one sample file directly, no pack needed |
| `root=<note>` | the sample's native pitch, when the pack hasn't measured one |
| `mode=varispeed\|vocoder` | default transposition method for the track |
| `gain=<dB>` · `pan=<-1..1>` · `send=<0..1>` | track-level defaults |

The clef stays first and keeps its meaning, so these lines still parse as
instrument declarations for notation purposes.

### 3. Microtonal pitch: `A6+22`

A pitch token may carry a cents offset: `A6+22` is 22 cents above A6, `G6-47`
is 47 cents below G6. This realises the microtonal extension `SPEC.md` raises as
an open question, in the minimal form — an integer cents offset after the
octave, no new accidental vocabulary.

It earns its place immediately on recorded material: the birds in the reference
corpus cluster 22 to 47 cents off 12-TET, and rounding them to the grid loses
the specific sound of the place.

### 4. Parameters share the `[...]` suffix with articulations

An item inside `[...]` is a **parameter** if it contains `=`, and an
**articulation or flag** otherwise. No new delimiter is introduced, and existing
articulation suffixes keep working unchanged.

```
A6q[stac,pan=-0.6,send=0.3]
```

| parameter | meaning |
|---|---|
| `pan=<-1..1>` | stereo position, equal-power |
| `gain=<dB>` | level trim on top of the prevailing dynamic |
| `lpf=<Hz>` · `hpf=<Hz>` | filter cutoff |
| `send=<0..1>` | reverb send |
| `s=<N>` | which sample of the voice to use (1-based) |
| `str=<x>` \| `str=fit` | time-stretch factor, or stretch to fill the notated duration |
| `off=<ms>` | start offset into the sample |
| `st=<semitones>` | explicit transposition for unpitched (`X`) events |
| `atk=<s>` · `rel=<s>` | envelope times |
| `drive=<x>` | soft-clip saturation |
| `gliss=<note>` | glissando target (see below) |
| `mode=…` | override the track's transposition method for this event |

Bare flags: `reverse` (play the sample backwards), `gate` (truncate to the
notated duration), plus every articulation in `SPEC.md`.

**Constraint:** no spaces inside `[...]`. This keeps the existing tokenizer,
which splits on whitespace, working unchanged.

### 5. Any parameter can sweep: `a->b`

```
sb 5: A1+22w[pan=-1->1, lpf=70->900]
```

reads "a rumbling bass sweeping from left to right, opening up as it goes".
The `->` is the same arrow `SPEC.md` assigns to glissando, generalised: it
always means *from, to, across this event*.

Pitch glissando uses it in the form the core spec already documents —
`A7q->C8` glides from A7 to C8 across the note. `[gliss=C8]` is an equivalent
spelling for consistency with the other parameters.

### 6. Articulations mean something to a sampler

The existing articulation vocabulary maps onto playback rather than being
discarded:

| notation | playback |
|---|---|
| `[stac]` `[stacciss]` `[spic]` `[detlg]` | truncate to 40% / 25% / 35% / 75% of the slot |
| `[acc]` `[marc]` `[sfz]` | +4 / +6 / +7 dB |
| `[ten]` | hold the full slot |
| `[fer]` | stretch to 1.75× |

### 7. Duration semantics

A notated duration is a **slot**, and by default a sample is a **one-shot**: it
plays to its natural end regardless of the slot, which is what makes recorded
material sound like itself. Two modifiers change that — `[gate]` truncates to
the slot, `[str=fit]` stretches to fill it exactly. Everything else about
rhythm — where the slot begins — is unchanged.

## Backward compatibility

A MUS-A score parses under `mus.py` today. Three small changes were made to the
existing parser so that extension data is *preserved* rather than silently
dropped, none of which alter behaviour on ordinary scores:

- `MusInstrument.params` — retains `key=value` items from the instrument
  parenthetical.
- `ParsedMus.extra` — retains unrecognised `# key: value` header lines.
- Multi-key header lines now parse. `SPEC.md` documents the metadata block as
  one line (`# tempo: 82  time: 4/4  key: Dm  bars: 16`) while `main_forward()`
  emits one key per line; only the latter parsed. Both now do.

Cents offsets round-trip losslessly *within* MUS: `A6+22` parses to a music21
pitch carrying `microtone = +22c` and renders back as `A6+22`. Before this
extension they didn't parse at all — `parse_event_token` matched the pitch head
`A6`, failed on the remaining `+22h` as a duration, and emitted the note as a
**rest**. Converting the reference score exposed it: 769 notes, none pitched.

Going the other way — MUS-A → MusicXML — notes, rhythms, dynamics,
articulations and structure survive; parameters do not, and **cents do not**.
The limit is music21's exporter, not the target format: MusicXML permits a
fractional `<alter>`, but music21 writes only the integer accidental
(`F#6+21` → `<alter>1</alter>`) and omits `<alter>` entirely for a
microtonally-inflected natural. Worth revisiting if microtonal engraving
matters; for now the engraved score is the human's reading of the piece, not a
complete description of the render.

## Not implemented

The renderer covers what the reference piece needed. Known gaps: per-note voice
selection is by index rather than by musical criteria; `str=fit` on very large
transpositions goes through a phase vocoder twice and smears; there is one
reverb for the whole mix rather than per-send spaces; no sidechain, delay, or
modulation beyond the parameter sweeps; and the sample pack format is the
manifest `build_instrument.py` happens to emit rather than a specified schema.
