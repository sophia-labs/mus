# MUS — A Compact LLM-Readable Score Notation

*Working spec, draft 0.4. By Eschaton + Beta, April 28 – May 9 2026. The first score notation designed to enable musical conversation between humans and LLMs as compositional peers. The asymmetry is the design: the human reads the engraved sheet music in its native form, the LLM reads the MUS, and the two readings are faithful enough to the same source that the human and the LLM can talk about the music as peers. Lossless w.r.t. typical sheet-music content, compact enough to fit dense pieces in an LLM context window, and tractable for an LLM to read as a score where engraved notation isn't.*

## Why

MUS makes a kind of conversation possible that wasn't quite possible before. A composer looks at the engraved score; the LLM reads the MUS file; both are reading the same music, and they can talk about it together — voicings, textural relationships, structural arguments — with the LLM responding as something closer to a peer than as a search engine returning facts. The format's job is to make the LLM's reading faithful enough to the human's that the conversation tracks the same musical object. The compactness is what lets the conversation fit in the context window where it has to happen. The compression is the means; the bridge between human and machine compositional intelligence is the end.

MUS is not asking the human to read MUS instead of sheet music — engraved notation evolved for centuries as the human-native form and shouldn't be replaced. MUS is what the LLM reads on its side of the conversation. It's human-readable enough to write, edit, and diff by hand when the human needs to, but the primary reader of MUS-as-text is the LLM. The primary reader of the engraved score is the human. They meet in the middle through the conversation.

Existing formats weren't designed for this audience. MusicXML round-trips between notation editors. LilyPond engraves to print. Humdrum analyses statistically. ABC fits folk-tune corpora. NoteSequence and REMI tokenize for ML training. Each does its own job; none enables the conversation. MUS is the first attempt at a format whose first audience is the dialogue itself.

## Design goals

1. **Lossless-or-near-lossless** w.r.t. typical sheet-music content: pitches, durations, rhythms, voices, articulations, dynamics, slurs, ties, ornaments, repeats, sections, lyrics, tempo/time/key changes.
2. **Tokens carry information.** No XML-style tag overhead.
3. **Editable by hand.** A human can write, correct, or diff MUS without a notation tool when they need to — even though the engraved score remains the human's primary reading surface.
4. **Linear and skimmable.** Top-to-bottom reading tracks a part naturally.
5. **Both score-view and part-view** are first-class and convertible.
6. **Convention over configuration.** Sensible defaults; specify only what's nonstandard.
7. **Diff-friendly.** Line-based. A bar edit = a line diff.
8. **Compress repetition** at the syntax level.
9. **Pitches are absolute.** Always spell pitches in concert pitch with explicit accidentals — no key-signature inheritance. This is the key choice that makes the format LLM-friendly.

## Core grammar

### Pitch

- `C4`, `D4`, `E4` ... octave 4 = the octave containing middle C (scientific pitch notation, MIDI 60 = C4).
- Accidentals: `Bb3` (B-flat), `F#5` (F-sharp), `Bn4` (B-natural; default if no accidental given). Optional Unicode: `B♭3`, `F♯5`.
- Double accidentals: `Fx4` (double-sharp), `Bbb3` (double-flat).
- Always absolute. Never inherits from key signature within or across bars.

### Duration

- `w h q e s t x` = whole / half / quarter / eighth / 16th / 32nd / 64th. `ww` = double whole (breve).
- Dotted: `q.` (one dot), `q..` (two dots).
- **Tuplet shorthand** for common ratios. The number after the duration is the *actual* count played in the time of the next-lower power-of-two count:
  - `q3 e3 s3 t3` — triplet (3:2)
  - `q5 e5 s5 t5` — quintuplet (5:4)
  - `q6 e6 s6 t6` — sextuplet (6:4)
  - `q7 e7 s7 t7` — septuplet (7:4)
  - `e9 s9` — nonuplet (9:8)
- **Explicit ratio** for unusual tuplets: `q{5:6}` (5 in the space of 6), `e{7:8}` (7 in the space of 8). Use when the ratio doesn't match a shorthand above.
- Tie: `~` between durations. `q~q` = quarter tied to quarter (= half value, but notated as tied).

### Rests

- `R` followed by duration: `Rq`, `Re`, `Rw`.
- Whole-bar rest (a single `R` with no duration) implied by bar's time signature.
- Track-level "tacet for this bar": `-` at the bar position, e.g., `g2 1: -`.

### Chords

- Brackets contain simultaneous pitches: `<C4 E4 G4>q` = C major triad as quarter note.
- Articulations and dynamics suffix the chord, not individual notes.
- `<C4 E4 G4>q[acc]` = accented chord.

### Voices and tracks

- **Tracks** = top-level instruments (`g1`, `g2`, `b`, `d`, `v`).
- **Voices within a track** = `g1.v1`, `g1.v2` (use sparingly; most rock/metal scores don't need this).
- **Multi-hand polyphonic instruments** (piano, organ, harp, harpsichord, celesta) use dot-notation for each staff. One piano: `p.r` (right hand) and `p.l` (left hand). Two pianos: `p1.r p1.l p2.r p2.l`. Organ adds `.p` for the pedal staff.
- One physical staff = one track unless the staff legitimately splits into independent voices (e.g., piano).

### Articulations

Suffix the duration with bracketed names. Multi-stack with commas.

**General:**

- `q[stac]` staccato / `q[stacciss]` staccatissimo
- `q[ten]` tenuto / `q[detlg]` detached legato
- `q[acc]` accent / `q[marc]` marcato
- `q[sfz]` sforzando / `q[fer]` fermata
- `q[trill]` trill / `q[mord]` mordent / `q[turn]` turn / `q[invmord]` inverted mordent / `q[invturn]` inverted turn
- `q[trem]` tremolo / `q[slide]` schleifer
- `q[stac,acc]` stacked

**String-specific:**

- `q[pizz]` pizzicato / `q[snappizz]` snap pizzicato / `q[nailpizz]` nail pizzicato
- `q[upbow]` up-bow / `q[downbow]` down-bow
- `q[harm]` harmonic (use `harm.nat` for natural and `harm.art` for artificial when distinguished)
- `q[open]` open string / `q[stopped]` stopped (mute)

Bow direction, color (sul ponticello, sul tasto, col legno), and mute on/off (con/senza sord) typically appear as system text in MusicXML and emit as `# text @bN: ...` comments rather than per-note articulations. They apply until the next directive.

### Dynamics

Curly braces, placed at the position the dynamic begins. Spans implicitly until the next dynamic on the same track.

- `{ppp} {pp} {p} {mp} {mf} {f} {ff} {fff}`
- `{<}` start crescendo / `{>}` start decrescendo / `{|}` end hairpin
- Word forms accepted: `{cresc}`, `{decresc}`, `{dim}`

Example: `g1 5: D2q{mp} D2q D2q D2q{<}` — `mp` from beat 1, crescendo starting beat 4, hairpin terminator implicit at the next dynamic mark or bar boundary.

### Slurs and ties

- **Tie** (same pitch, no rearticulation): `~` between durations. `C4q~q` or `C4q~h`.
- **Slur** (different pitches, legato): `( ... )` around notes. `(C4q D4q E4q)`. Slurs cross bar lines naturally — open in one bar, close in another.

### Ornaments and grace notes

- Trill: `q[trill]`. Mordent: `q[mord]`. Turn: `q[turn]`.
- Grace note: prefix `g` then pitch + duration. `gC4e D4q` = grace eighth C4 leading into quarter D4. Multiple grace notes: `g(C4e D4e) E4q`.
- Glissando / portamento between two notes: `->`. `C4q->D4q` slides from C4 to D4.

### Bar structure and global changes

- A line beginning with `bar N` introduces or annotates bar N.
- Inline metadata in brackets at bar start changes global state from that bar forward:
  - `bar 17 [time=6/8]`
  - `bar 33 [tempo=110]`
  - `bar 25 [key=Bbm]`
  - `bar 5 [accel ♩=82→110]` (gradual change to next bar that resets it)
- For change-heavy pieces (more than 10 changes of any kind), the header summarizes ("tempo: 56 (initial; 60 changes inline)") and each change emits inline at its bar. This keeps the header scannable and the changes locally visible.

### Sections

- `# section: name [N-M]` markdown comment defines a section.
- Section names are free text. Common: intro, verse, chorus, bridge, climax, outro.

### System text annotations

Performance directives, atmospheric notes, and free-text annotations placed in the score (Musescore "system text" or "expression text") emit as comments anchored to the bar where they appear:

```
# text @b53: pluck harder than usual, intense, tense, pained, use a pedal perhaps
# text @b53: jessika will be squealing while we plod
# text @b95: rit.
# text @b97: refuses to let go
```

Multiple text expressions at the same bar each get their own comment line. Text content is preserved verbatim (no quoting or escaping needed since these are comment lines).

This is distinct from `# section:` headers — sections are structural milestones (rehearsal letters: Verse 1, Chorus, Bridge), while text annotations are interpretive directives that don't define a structural unit.

### Repeats and form navigation

- Simple repeat: `|: ... :|` enclosing the repeated material. The opening can be mid-bar.
- First/second endings (voltas): `|: ... [|1. ... :|2. ... |]`
- D.C., D.S., codas: `[DC]`, `[DS]`, `[coda]`, `[segno]`, `[fine]` as bar-level annotations.

### Lyrics

- Per-note inline: `D4q "i" D4q "loved" D4q "you" D4q "from"`
- Multi-syllable extension via `_`: `D4q "love_" D4e "ly"` — the underscore indicates the syllable continues to the next note.
- Bar-level lyric line as alternative: `v.lyrics 6: "i loved you from"`

### Track-level metadata

At the top of a MUS file, before any bar content:

```
# score: <title>
# summary: <bars> bars / <voices> voices / ~<minutes> min
# tempo: <bpm>    time: <num/denom>    key: <key>    bars: <total>

# instruments:
#   <abbr> = <full name> (<clef>[, <transposition>])
```

Clefs: `treble`, `bass`, `alto`, `tenor`, `perc`. Transposition: `+1` (major second up), `-12` (octave down written, sounds), etc.

### Key signature ambiguity

A key signature alone — *N* sharps or *N* flats — is genuinely ambiguous between a major key and its relative minor (one flat = F major *or* D minor). MusicXML's `<mode>` field is often missing or defaulted to major during export, so we can't always trust the major label.

The format renders the **relative pair** when the mode isn't reliably known: `F/Dm`, `C/Am`, `G/Em`, etc. The first item is the major key, the second is its relative minor. The actual mode emerges from the music itself — opening drone, cadential motion, melodic contour — which the reader (human or LLM) determines from context.

Single form (`Dm`) only emerges when the source explicitly marks the mode as minor, which is never the default and therefore trustworthy. Single major (`D`) emerges when the user overrides via flag.

## Two views

The same content can be expressed two ways. The format supports both; converters can transpose between them.

### Bar-major view

Reads like an ensemble score — what's happening at each moment.

```
bar 5: g1=D2w  g2=(D4e F4e A4e D5e ×2)  b=D2w  d=Kq Sq Kq Sq  v=R
bar 6: g1=D2w  g2=(D4e F4e A4e D5e ×2)  b=D2w  d=Kq Sq Kq Sq  v=D4q "i" D4q "loved" D4q "you" D4q "from"
```

### Track-major view

Reads like a part — trace one voice through the song.

```
g1 1-4: D2w (4×)
g1 5-6: D2w (2×)
g1 7-8: F2w (2×)
g1 9: F2h F2h
g1 10-12: F2w D2w D2w
```

## Repetition compression

- `(N×)` after a phrase repeats it: `D2w (4×)` = D2 whole, four times.
- Bar-range expansion: `bars 5-12: <pattern>` applies pattern across the range.
- Looped sub-bar pattern: `(D4e F4e A4e D5e ×2)` = the four-note arpeggio twice.
- Differential annotations: `bar 9 g2 += {Eb4q. on beat 1}` — adds an event to an existing bar without rewriting it.

## Worked example

A 16-bar fragment of "This Is My Body":

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
g2 1-2: -
g2 3-4: (D4e F4e A4e D5e ×2)
b  1-4: D2w (4×)
d  1-4: Kq Sq Kq Sq (4×)
v  1-4: -

# section: v1 [5-12] — vocals enter bar 6, Phrygian inflection bar 9

g1 5-6:  D2w (2×)
g1 7-8:  F2w (2×)
g1 9-12: F2w D2w D2w D2w
g2 5-12: (D4e F4e A4e D5e ×2 per bar)
g2 9 += {Eb4q. on beat 1}
b  5-6:  D2w (2×)
b  7-8:  F2w (2×)
b  9-12: F2w D2w D2w D2w
d  5-12: Kq Sq Kq Sq (8×)
v  5: -
v  6: D4q "i" D4q "loved" D4q "you" D4q "from"
v  7: D4q "the" D4q "start" D4h R
v  8: -
v  9: D4q "traced" D4q "your" D4q "steps" D4q "with"
v  10: D4q "my" D4q "fin_" D4q "gers" D4h R

# section: bridge [13-16] — density triples, dissonance peaks

g1 13-16: <D4 A4 D5>q{ff>}  q  q[sfz]  q  (×4 bars)
g2 13-16: (<Db5 G5>e ×8 per bar)
b  13-16: D2q A2q G2q D2q (×4 bars)
d  13-16: K.s.K.s.K.s.K.s. (×4 bars)
v  13: D5h "this" D5h "is"
v  14: D5h "my" D5h "bo_"
v  15: D5w "dy"
v  16: -
```

That's 16 bars of 5-instrument writing in ~40 lines. Same content as MusicXML would be 8-12KB of XML. **MUS is ~10-20× more compact and the bytes that survive carry musical information.**

## Open questions (design pressure points)

- **Polyrhythm crossing bar lines** — 5-against-4 or beat groupings that don't divide evenly. Current notation handles via tuplets but cross-bar groupings are awkward.
- **Microtonal pitches** — quartertones, just-intonation drone music. Could extend with `Cn4+50¢` (50 cents above C4) or use HEWM/Sagittal accidental notation.
- **Free time / cadenza / rubato** — most formats handle this awkwardly. Inline `[free]` to suspend metric structure?
- **Voicings vs. abstract harmony** — `<C4 E4 G4>` and `<E4 G4 C5>` mean different things sonically (root position vs. first inversion) but encode the same chord. Format treats them as different — that's correct.
- **Chord symbols** — separate from realized voicings. Should there be an optional `chord:` annotation per bar showing the abstract harmony? Probably yes for analytical purposes.
- **Drum kit notation** — `K`, `S`, `H` (kick/snare/hat) as shorthand vs. full pitch. Convention TBD: maybe `d` track defaults to drum-kit shorthand and pitch-based notation falls through to general MIDI percussion mappings.
- **Tablature / fret notation** — for guitar parts. Could append `[fret=N,string=M]` to a note, or have a separate `g1.tab` view.

These don't block the current spec — they're design pressure points to iterate on with real songs.

## Implementation

A v0.4 toolchain has three pieces:

1. **MUS parser**: reads `.mus` text, builds an internal score representation. Can use `music21`'s Score model as the internal representation to leverage existing analysis tools.
2. **MIDI/MusicXML → MUS**: convert from common formats. Lossy in the timbral direction (MIDI), nearly lossless from MusicXML for the supported features.
3. **MUS → MIDI/MusicXML/PDF**: round-trip. Use music21 for MusicXML output, LilyPond/Verovio for engraving.

Current converter ships only the MusicXML/MIDI → MUS direction. Round-trip back is a v0.5+ goal once the format stabilizes.

## Status

- v0.4 spec (this document) — covers the format and the current implementation; both still iterating together.
- v0.4 converter: `mus.py`. Auto-detects format from extension (.mid/.midi/.musicxml/.xml/.mxl). PEP 723 inline metadata so `uv run` handles dependencies.

**Implements (v0.4):** bar-major output; within-bar pattern compression (pattern ×N); tacet-run and identical-bar collapse; tied-note splitting for unmappable durations; PercussionChord handling; multi-tempo/key/time-sig headers with bar-by-bar change lists; **inline change distribution** when a kind exceeds the 10-change threshold; lyrics with syllabic continuation; **expanded articulation taxonomy** including string articulations (pizz, arco, harm, upbow, downbow, snap pizz, etc.); dynamics at changes; **hairpin spanners** (cresc/decresc/end via `{<} {>} {|}`); rehearsal-mark sections with auto-derived end bars; system text comments; slurs from Spanner objects; title-from-credit-words fallback for Musescore exports; **tuplet notation** via notated form (`q3 e5 s7`) with `{n:m}` fallback for unusual ratios; **multi-hand naming** for polyphonic instruments (`p1.r/p1.l/p2.r/p2.l`); **header summary line** ("N bars / N voices / ~N min"); **dynamics-missing diagnostic** on stderr; **relative-pair key rendering** (`F/Dm`) when mode is uncertain.

**Tested on:**

- *This Is My Body* (171 bars, 145→125→145 BPM, distorted-guitar tremolo passages)
- *Crave* (131 bars, 4/4→3/4 mid-piece, key change Cb→Gb, 7-string clusters with system text annotations)
- *Composition 1* (37 bars, oboe + string trio, 4/4↔3/4 alternations, dense per-voice articulation and dynamics)
- *Verklärte Nacht* (Schoenberg, 421 bars, ~30 minutes, 4 piano staves, 60 tempo changes, 20 time changes, 10 key changes, dense quintuplet/sextuplet/septuplet figuration, late-Romantic chromatic harmony) — first stress test against canonical complex repertoire; format held up at ~1 line per bar.

**v0.5 priorities:**

- Round-trip: MUS → MusicXML/MIDI output
- GM percussion → K/S/H drum-kit shorthand mapping
- Voltas / explicit repeats / DC / DS / coda from MusicXML
- Per-track range collapse for partial-match bar groups (current identical-bar collapse requires *all* tracks to match)
- Cross-bar phrase repetition detection (`bars N-M: same as X-Y`)
- Header line wrapping for very-long change lists that still fit under threshold
- Tighter tuplet detection in music21 edge cases (irregular ratios that currently fall through to fractional)

**Conversation as proof of concept.** Outputs of these test runs live alongside the converter and have been read directly by Sophia agents for analytical commentary — that conversation is itself both the stress test of whether the format is doing what it's supposed to and the first artifact in the series of human-LLM compositional dialogues the format was made to enable.
