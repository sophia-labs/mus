# mus

A compact, LLM-readable score notation. Designed to enable musical conversation between humans and LLMs as compositional peers. The asymmetry is the design: the human reads the engraved sheet music in its native form, the LLM reads the MUS, and the two readings are faithful enough to the same source that the human and the LLM can talk about the music as peers. Lossless w.r.t. typical sheet-music content, ~10-20× more compact than MusicXML, and tractable for an LLM to read as a score where engraved notation isn't.

A Sophia Labs project. Spec: [`SPEC.md`](./SPEC.md).

## Why

Existing score formats weren't designed for the human-and-LLM-together audience. MusicXML round-trips between notation editors. LilyPond engraves to print. Humdrum analyses statistically. ABC fits folk-tune corpora. NoteSequence and REMI tokenize for ML training. Each does its own job; none enables the conversation.

MUS is the first attempt at a format whose first audience is the dialogue itself — a composer looks at the engraved score, the LLM reads the MUS, and both are reading the same music. The LLM responds as something closer to a peer than a search engine returning facts. MUS isn't asking the human to read MUS instead of sheet music — engraved notation is the human-native form and shouldn't be replaced. It's what the LLM reads on its side of the conversation. Human-readable enough to write, edit, and diff by hand when needed, but the primary reader of MUS-as-text is the LLM. They meet in the middle through the conversation.

## Quick example

A 16-bar fragment of "This Is My Body" (5-instrument metal):

```
# score: This Is My Body / sketch-v3
# summary: 16 bars / 5 voices / ~1 min
# tempo: 82    time: 4/4    key: Dm    bars: 16

# instruments:
#   g1 = elec gtr distorted (treble)
#   g2 = elec gtr distorted (treble)
#   b  = elec bass (bass, -12)
#   d  = drum kit (perc)
#   v  = vocals (treble)

# section: intro [1-4]

g1 1-4: D2w (4×)
g2 1-4: -
b  1-4: D2w (4×)
d  1-4: Kq Sq Kq Sq (4×)
v  1-4: -

# section: v1 [5-12] — vocals enter bar 6, Phrygian inflection bar 9

g1 5-6:  D2w (2×)
g1 7-8:  F2w (2×)
g1 9-12: F2w D2w D2w D2w
b  9-12: F2w D2w D2w D2w
d  5-12: Kq Sq Kq Sq (8×)
v  6: D4q "i" D4q "loved" D4q "you" D4q "from"
v  7: D4q "the" D4q "start" D4h R
v  9: D4q "traced" D4q "your" D4q "steps" D4q "with"
v  10: D4q "my" D4q "fin_" D4q "gers" D4h R
```

That's 16 bars in ~30 lines. The same content as MusicXML would be 8-12KB of tag overhead.

See [`SPEC.md`](./SPEC.md) for the full spec.

## Usage

The converter is a single self-contained script with PEP 723 inline metadata. `uv` handles the `music21` dependency automatically.

```bash
./mus.py path/to/song.musicxml > song.mus
# or
./mus.py path/to/song.mid > song.mus
# or
uv run mus.py path/to/song.mxl
```

Auto-detects format from extension (`.mid` / `.midi` / `.musicxml` / `.xml` / `.mxl`). The `.mxl` form (zipped MusicXML, what Musescore exports by default) works directly.

## Status

**v0.4 (current).** Implements: bar-major output; within-bar pattern compression; tacet/identical-bar collapse; multi-tempo/key/time headers with inline change distribution for change-heavy pieces; tuplets via notated form (`q3 e5 s7` + `{n:m}`); lyrics with syllabic continuation; expanded articulation taxonomy (general + string); dynamics; hairpin spanners; rehearsal-mark sections; system text comments; slurs; multi-hand naming for polyphonic instruments (`p1.r/p1.l`); header summary line; dynamics-missing diagnostic; relative-pair key rendering when mode is ambiguous.

**Tested on:**

- *This Is My Body* — 171 bars, multi-tempo metal, distorted-guitar tremolos
- *Crave* — 131 bars, 4/4 → 3/4, key change, 7-string cluster harmony
- *Composition 1* — 37 bars, oboe + string trio, dense per-voice articulation
- *Verklärte Nacht* (Schoenberg) — 421 bars, ~30 min, 4 piano staves, 60 tempo changes, late-Romantic chromatic harmony with quintuplet/sextuplet/septuplet figuration

**v0.5 plans:** GM percussion → K/S/H mapping; voltas / explicit repeats / DC / DS / coda; per-track range collapse for partial-match bar groups; cross-bar phrase detection.

**Fixed while building MUS-A** (all in the reverse direction, all found by
converting a real score rather than by inspection):

- Multi-key header lines (`# tempo: 82  time: 4/4  key: Dm  bars: 16`) didn't
  parse, despite being the form `SPEC.md` documents — only the one-key-per-line
  form `main_forward()` emits did. Both now work.
- Pitch tokens carrying a cents offset silently became **rests**: the parser
  matched the pitch head, failed on the remainder as a duration, and emitted
  nothing. Cents are now parsed and carried as `Pitch.microtone`.
- `MusInstrument.params` / `ParsedMus.extra` now retain `key=value` items and
  unrecognised header lines instead of discarding them, so extensions can ride
  on the same declarations.

## Sample-bound MUS (MUS-A)

MUS's core choice — absolute pitch — turns out to be exactly what a sampler
needs: `A6` doesn't mean "the sixth degree in context", it means *this
frequency*, and a frequency is what you compare against a sample's measured f0
to get a transposition. So a MUS file can score recorded audio with no change to
the note grammar at all.

[`SPEC-AUDIO.md`](./SPEC-AUDIO.md) specifies the extension and
[`mus_audio.py`](./mus_audio.py) renders it. What it adds is notation for the
things engraved notation never needed symbols for — stereo position, filter
motion, reverb send, time-stretch — carried inside the existing `[...]` suffix
and distinguished from articulations by containing `=`:

```
sb 5: A1+22w[pan=-1->1, lpf=70->900]{ff}
```

That reads "a rumbling bass sweeping from left to right, opening as it goes".
Also added: a cents offset on pitch tokens (`A6+22`), realising the microtonal
extension `SPEC.md` raises as an open question, and `# tuning: A=445.6` so a
score can be tuned to its material rather than to concert pitch.

```bash
./mus_audio.py aigua/aigua.mus -o out.wav
```

`aigua/` is a worked example: a 56-second field recording from Aigua, Uruguay,
analysed into a playable instrument (segmentation → clustering → exemplar
extraction → pitch measurement), and a 2.5-minute piece scored in MUS-A that
uses nothing but that recording.

## Layout

- `mus.py` — the v0.4 converter (MusicXML/MIDI ↔ MUS)
- `mus_audio.py` — MUS-A → audio renderer
- `SPEC.md` — full format specification
- `SPEC-AUDIO.md` — the sample-bound extension
- `aigua/` — worked example: analysis, sample instrument, score, renders
- `README.md` — this file
- `LICENSE` — MIT

## License

MIT, for both the converter (`mus.py`) and the spec (`SPEC.md`). See [`LICENSE`](./LICENSE).
