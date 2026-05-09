# mus

A compact, LLM-readable score notation. Designed to enable musical conversation between humans and LLMs as compositional peers — a format whose primary design goal is mutual legibility, with compression as the means rather than the end. Lossless w.r.t. typical sheet-music content, ~10-20× more compact than MusicXML, and natively legible to both humans and LLMs.

A Sophia Labs project. Spec: [`SPEC.md`](./SPEC.md).

## Why

Existing score formats weren't designed for the human-and-LLM-together audience. MusicXML round-trips between notation editors. LilyPond engraves to print. Humdrum analyses statistically. ABC fits folk-tune corpora. NoteSequence and REMI tokenize for ML training. Each does its own job; none enables the conversation.

MUS is the first attempt at a format whose first audience is the dialogue itself — a composer can show an LLM a score, the LLM can read it as music, and respond as something closer to a peer than as a search engine returning facts. The legibility is what makes the conversation possible; the compactness is what lets the conversation fit in the context window where it has to happen.

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

**v0.5 plans:** round-trip MUS → MusicXML/MIDI; GM percussion → K/S/H mapping; voltas / explicit repeats / DC / DS / coda; per-track range collapse for partial-match bar groups; cross-bar phrase detection.

## Layout

- `mus.py` — the v0.4 converter
- `SPEC.md` — full format specification
- `README.md` — this file
- `LICENSE` — MIT

## License

MIT, for both the converter (`mus.py`) and the spec (`SPEC.md`). See [`LICENSE`](./LICENSE).
