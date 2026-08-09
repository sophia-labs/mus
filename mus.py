#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["music21>=9.0"]
# ///
"""
MUS v0.4 — Score → MUS converter.

Reads MIDI (.mid/.midi) or MusicXML (.musicxml/.xml/.mxl) and emits MUS
notation (bar-major view) to stdout. Format auto-detected from extension.

Usage:
  ./mus.py path/to/song.musicxml > song.mus
  uv run mus.py path/to/song.mid

Captures (input-dependent):
  - Pitches, durations, ties, chords, rests          (both)
  - Tempo / time / key changes — inline if heavy     (both)
  - Tuplets via notated form (q3/e5/s7/{n:m})        (both)
  - Within-bar pattern compression (×N)              (both)
  - Tacet runs / identical-bar runs                  (both)
  - PercussionChord → X markers                      (both)
  - Lyrics with syllabic markers                     (MusicXML)
  - Articulations [stac,acc,pizz,arco,harm,…]        (MusicXML)
  - Dynamics {p,mf,ff,…} at changes                  (MusicXML)
  - Hairpins {<} {>} {|} (cresc / decresc / end)     (MusicXML)
  - Slurs ( … )                                      (MusicXML)
  - Section markers from rehearsal letters           (MusicXML)
  - Multi-hand polyphonic naming (p1.r/p1.l, etc.)   (MusicXML)
  - Header summary line (bars / voices / minutes)    (both)
  - Warning when source has no dynamic markings      (both)
  - Fingering markers (StringIndication etc.) are stripped — tab noise.

Not yet captured (planned v0.5+):
  - Voltas / repeats / DC / DS / coda
  - GM percussion → K/S/H mapping
  - Per-track range collapse
  - Cross-bar phrase / scale-run compression
"""

import sys
import re
import argparse
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from music21 import converter, stream, note, chord, meter, key, tempo as m21tempo
from music21 import dynamics as m21dynamics, expressions as m21expressions
from music21 import spanner as m21spanner
from music21 import (
    pitch as m21pitch,
    duration as m21duration,
    articulations as m21articulations,
    clef as m21clef,
    instrument as m21instrument,
    metadata as m21metadata,
    tie as m21tie,
)


# Articulation class name → MUS shorthand. Names are music21 class names.
ARTICULATION_MAP: dict[str, str] = {
    # General articulations
    "Staccato": "stac",
    "Staccatissimo": "stacciss",
    "Accent": "acc",
    "StrongAccent": "marc",        # marcato
    "Tenuto": "ten",
    "DetachedLegato": "detlg",
    "Spiccato": "spic",
    "Stress": "stress",
    "Unstress": "unstress",
    # String-specific (bowing, attack, hand position, color)
    "Pizzicato": "pizz",
    "SnapPizzicato": "snappizz",
    "NailPizzicato": "nailpizz",
    "UpBow": "upbow",
    "DownBow": "downbow",
    "Harmonic": "harm",
    "StringHarmonic": "harm",
    "OpenString": "open",
    "Stopped": "stopped",
    "ImpliedHarmonic": "harm.nat",
    # Wind/brass-specific
    "DoubleTongue": "doubletongue",
    "TripleTongue": "tripletongue",
    "Stopped": "stopped",
}

# Expression class name → MUS shorthand (ornaments + fermata).
EXPRESSION_MAP: dict[str, str] = {
    "Fermata": "fer",
    "Trill": "trill",
    "Mordent": "mord",
    "InvertedMordent": "invmord",
    "Turn": "turn",
    "InvertedTurn": "invturn",
    "Schleifer": "slide",
    "Tremolo": "trem",
    "Sforzando": "sfz",  # rare as expression
}


# Note-value → quarter-length conventions:
#   1 quarter (q) = 1.0
#   triplet quarter (q3) = 2/3 of a quarter (3 fit in a half = 2 quarters → ⅔ each)
#   triplet eighth  (e3) = 1/3 of a quarter (3 fit in a quarter)
#   triplet 16th    (s3) = 1/6 of a quarter (3 fit in an eighth)
#   triplet 32nd    (t3) = 1/12 of a quarter (often appears as a quantization artifact)
DURATION_MAP: dict[Fraction, str] = {
    Fraction(8, 1):  "ww",   # double whole (breve)
    Fraction(6, 1):  "w.",   # dotted whole
    Fraction(4, 1):  "w",
    Fraction(3, 1):  "h.",   # dotted half
    Fraction(2, 1):  "h",
    Fraction(3, 2):  "q.",   # dotted quarter
    Fraction(1, 1):  "q",
    Fraction(3, 4):  "e.",   # dotted eighth
    Fraction(1, 2):  "e",
    Fraction(3, 8):  "s.",   # dotted sixteenth
    Fraction(1, 4):  "s",
    Fraction(1, 8):  "t",    # 32nd
    Fraction(4, 3):  "h3",   # half triplet
    Fraction(2, 3):  "q3",   # quarter triplet
    Fraction(1, 3):  "e3",   # eighth triplet
    Fraction(1, 6):  "s3",   # sixteenth triplet
    Fraction(1, 12): "t3",   # 32nd triplet (also: triplet quantization artifact)
    Fraction(1, 24): "x3",   # 64th triplet (rare; mostly artifact)
}


# music21 duration.type → MUS base note value
TYPE_TO_BASE: dict[str, str] = {
    "breve":   "ww",
    "whole":   "w",
    "half":    "h",
    "quarter": "q",
    "eighth":  "e",
    "16th":    "s",
    "32nd":    "t",
    "64th":    "x",
}

# Tuplet ratio (actual:normal) → suffix shorthand. Triplet (3:2) → "3", etc.
# Anything not in this map renders as explicit "{N:M}".
TUPLET_SHORTHAND: dict[tuple[int, int], str] = {
    (3, 2): "3",   # triplet
    (5, 4): "5",   # quintuplet (in time of 4)
    (6, 4): "6",   # sextuplet
    (7, 4): "7",   # septuplet (in time of 4)
    (9, 8): "9",   # nonuplet
}


def duration_to_code(quarter_length: float) -> str:
    """Convert music21 quarter-length to MUS duration string (single token)."""
    f = Fraction(quarter_length).limit_denominator(64)
    if f in DURATION_MAP:
        return DURATION_MAP[f]
    return f"?{f}"  # unknown — flag for inspection


def elem_duration_codes(elem) -> list[str]:
    """Get MUS duration code(s) for a music21 element using its notated form.

    Prefers element.duration.type + dots + tuplets (semantic) over computing
    from quarterLength (numeric). Falls back to fractional decomposition for
    durations music21 marks as 'complex' or otherwise unrepresentable.

    Tuplets emit as suffix on the base value:
      q3   = triplet quarter (3:2)
      e5   = quintuplet eighth (5:4)
      s7   = septuplet 16th (7:4)
      e{5:6} = explicit ratio when not in TUPLET_SHORTHAND
    """
    dur = getattr(elem, "duration", None)
    if dur is None:
        return split_duration(elem.quarterLength)

    base = TYPE_TO_BASE.get(getattr(dur, "type", None))
    dots = getattr(dur, "dots", 0)
    if base is None or dots > 2:
        return split_duration(elem.quarterLength)

    code = base + ("." * dots)
    tuplets = list(getattr(dur, "tuplets", None) or [])
    if len(tuplets) == 1:
        t = tuplets[0]
        ratio = (t.numberNotesActual, t.numberNotesNormal)
        code += TUPLET_SHORTHAND.get(ratio, f"{{{ratio[0]}:{ratio[1]}}}")
    elif len(tuplets) > 1:
        # Nested tuplets — rare; fall back to fractional for safety.
        return split_duration(elem.quarterLength)

    return [code]


def split_duration(quarter_length: float) -> list[str]:
    """Split a quarter-length into a sequence of MUS duration codes.
    For durations not directly in DURATION_MAP, decomposes greedily into
    the largest mapped pieces. Used as a fallback when elem_duration_codes
    can't read the notated form (e.g., music21 reports 'complex' type).
    """
    f = Fraction(quarter_length).limit_denominator(64)
    if f in DURATION_MAP:
        return [DURATION_MAP[f]]
    parts: list[str] = []
    remaining = f
    # Greedy: subtract largest known duration first
    for dur_frac in sorted(DURATION_MAP.keys(), reverse=True):
        while remaining >= dur_frac:
            parts.append(DURATION_MAP[dur_frac])
            remaining -= dur_frac
        if remaining == 0:
            break
    if remaining != 0:
        parts.append(f"?{remaining}")
    return parts


def pitch_to_mus(pitch) -> str:
    """Convert music21 Pitch → MUS pitch string. C4 = middle C.

    A non-zero microtone emits as a cents suffix ('A6+22'), so microtonal
    sources survive the conversion instead of snapping to the semitone grid.
    """
    name = pitch.name.replace("-", "b")  # music21 uses '-' for flat
    octave = pitch.octave if pitch.octave is not None else 4
    cents = 0
    try:
        cents = int(round(pitch.microtone.cents))
    except Exception:
        pass
    return f"{name}{octave}{cents:+d}" if cents else f"{name}{octave}"


def find_pattern_in_events(events: list[str]) -> str:
    """Detect a repeating sub-pattern in an event list and return compressed form.
    Uses the shortest pattern length that fully tiles the sequence.
    Only compresses if the result is shorter than the uncompressed form.
    """
    n = len(events)
    if n < 4:
        return " ".join(events)
    raw = " ".join(events)
    best: str | None = None
    for plen in range(1, n // 2 + 1):
        if n % plen != 0:
            continue
        pattern = events[:plen]
        repeats = n // plen
        if repeats < 2:
            continue
        if all(events[i * plen:(i + 1) * plen] == pattern for i in range(repeats)):
            compressed = f"({' '.join(pattern)} ×{repeats})"
            if best is None or len(compressed) < len(best):
                best = compressed
            break  # shortest plen wins; longer plens give same content with fewer repeats
    return best if best and len(best) < len(raw) else raw


# Tab fingering markers — present on tablature parts, but noise for LLM analysis.
# They don't change what the note sounds like, only how it's physically played.
FINGERING_ARTICULATIONS: set[str] = {
    "StringIndication", "FretIndication",
}

# music21 base-class names that get instantiated as fallbacks for unrecognized
# articulations/expressions. Skip these — they emit as bare "articulation"/"expression"
# tags which are noise.
BASE_ARTICULATION_CLASSES: set[str] = {
    "Articulation", "Expression", "Ornament", "TextExpression",
}


def collect_articulations(elem) -> str:
    """Build a [stac,acc,…] suffix from a note's articulations + expressions.
    Skips fingering markers (StringIndication, FretIndication) by default — they're
    tablature noise, not phrasing information."""
    tags: list[str] = []
    for a in getattr(elem, "articulations", []) or []:
        cn = type(a).__name__
        if cn in FINGERING_ARTICULATIONS or cn in BASE_ARTICULATION_CLASSES:
            continue
        tags.append(ARTICULATION_MAP.get(cn, cn.lower()))
    for e in getattr(elem, "expressions", []) or []:
        cn = type(e).__name__
        if cn in BASE_ARTICULATION_CLASSES:
            continue
        tags.append(EXPRESSION_MAP.get(cn, cn.lower()))
    return f"[{','.join(tags)}]" if tags else ""


def collect_lyrics(elem) -> str:
    """Build the lyric suffix for a note. Returns ' \"text\"' or empty."""
    lyrics = getattr(elem, "lyrics", None) or []
    if not lyrics:
        return ""
    rendered: list[str] = []
    for lyr in lyrics:
        text = (lyr.text or "").replace('"', '\\"')
        syl = getattr(lyr, "syllabic", None) or "single"
        if syl == "begin":
            rendered.append(f'"{text}_"')
        elif syl == "middle":
            rendered.append(f'"_{text}_"')
        elif syl == "end":
            rendered.append(f'"_{text}"')
        else:
            rendered.append(f'"{text}"')
    return " " + " ".join(rendered)


def event_to_mus(elem) -> str:
    """Convert a single music21 element to a MUS event token (or tied sequence)."""
    parts = elem_duration_codes(elem)
    suffix = collect_articulations(elem)
    lyric = collect_lyrics(elem)

    def decorate(tokens: list[str], is_pitched: bool) -> str:
        """Apply [art] suffix to first token's duration; tie joins for pitched."""
        if suffix and tokens:
            tokens = [tokens[0] + suffix] + tokens[1:]
        sep = "~" if (is_pitched and len(tokens) > 1) else " "
        return sep.join(tokens) + lyric

    if isinstance(elem, note.Unpitched):
        return decorate([f"X{p}" for p in parts], is_pitched=False)

    if isinstance(elem, note.Note):
        pitch = pitch_to_mus(elem.pitch)
        return decorate([f"{pitch}{p}" for p in parts], is_pitched=True)

    if isinstance(elem, chord.Chord):
        seen: set[str] = set()
        unique: list[str] = []
        for p in elem.pitches:
            tok = pitch_to_mus(p)
            if tok not in seen:
                seen.add(tok)
                unique.append(tok)
        head = unique[0] if len(unique) == 1 else f"<{' '.join(unique)}>"
        return decorate([f"{head}{p}" for p in parts], is_pitched=True)

    if isinstance(elem, note.Rest):
        return decorate([f"R{p}" for p in parts], is_pitched=False)

    cls_name = type(elem).__name__
    if "Percussion" in cls_name or (hasattr(elem, "pitches") and elem.pitches):
        return decorate([f"X{p}" for p in parts], is_pitched=False)
    return " ".join(f"?{p}" for p in parts)


# Instruments that conventionally split across multiple staves for one player.
# Triggers dot-notation naming when multiple consecutive parts share the name.
POLYPHONIC_INSTRUMENTS: set[str] = {
    "piano", "organ", "harp", "harpsichord", "celesta", "fortepiano",
    "marimba", "vibraphone",
}


def part_abbreviation_base(name: str, idx: int) -> str:
    """Compute the base abbreviation from a part name (no uniquification)."""
    if not name:
        return f"t{idx}"
    words = name.lower().split()
    if len(words) > 1:
        return "".join(w[0] for w in words)
    return name[:2].lower()


def is_polyphonic_inst(name: str) -> bool:
    n = (name or "").lower()
    return any(p in n for p in POLYPHONIC_INSTRUMENTS)


CLEF_TO_HAND: dict[str, str] = {
    "treble": "r",   # right hand
    "bass": "l",     # left hand
    "perc": "p",     # pedal (organ)
}


def assign_track_names(parts) -> list[str]:
    """Return one MUS track abbreviation per part.

    Detects runs of same-name *polyphonic* instruments (piano, organ, harp,
    harpsichord, etc.) and uses dot-notation:
      2 staves of one piano: p.r, p.l
      4 staves of two pianos: p1.r, p1.l, p2.r, p2.l
    Heterogeneous parts and single-staff parts use the original numbering.
    """
    abbrevs: list[str | None] = [None] * len(parts)
    taken: set[str] = set()

    # Find contiguous runs of identical part names that are polyphonic instruments.
    i = 0
    while i < len(parts):
        name = (parts[i].partName or "").strip()
        # Walk forward while same name and polyphonic
        j = i + 1
        while (
            j < len(parts)
            and (parts[j].partName or "").strip() == name
            and is_polyphonic_inst(name)
        ):
            j += 1
        run = list(range(i, j))

        if len(run) >= 2 and is_polyphonic_inst(name):
            base = part_abbreviation_base(name, i)
            staves_per_instance = 2  # assume two-staff polyphonic instruments
            instances = max(1, len(run) // staves_per_instance)
            for k, part_idx in enumerate(run):
                hand = CLEF_TO_HAND.get(part_clef(parts[part_idx]), chr(ord("a") + k))
                if instances == 1:
                    abbr = f"{base}.{hand}"
                else:
                    inst_num = (k // staves_per_instance) + 1
                    abbr = f"{base}{inst_num}.{hand}"
                # Uniquify in case of collisions (e.g., two treble staves)
                candidate = abbr
                n = 2
                while candidate in taken:
                    candidate = f"{abbr}{n}"
                    n += 1
                taken.add(candidate)
                abbrevs[part_idx] = candidate
            i = j
        else:
            # Single part or non-polyphonic — use original logic.
            base = part_abbreviation_base(name, i)
            candidate = base
            n = 1
            while candidate in taken:
                n += 1
                candidate = f"{base}{n}"
            taken.add(candidate)
            abbrevs[i] = candidate
            i += 1

    return [a for a in abbrevs if a is not None]


def part_abbreviation(part, idx: int, taken: set[str]) -> str:
    """Legacy single-part abbreviation. Kept for backward compatibility but
    main() now uses assign_track_names() for the whole list at once."""
    name = (part.partName or "").strip()
    base = part_abbreviation_base(name, idx)
    candidate = base
    n = 1
    while candidate in taken:
        n += 1
        candidate = f"{base}{n}"
    taken.add(candidate)
    return candidate


def part_full_name(part) -> str:
    if part.partName:
        return part.partName
    inst = part.getInstrument()
    if inst and inst.instrumentName:
        return inst.instrumentName
    return "unknown"


def part_clef(part) -> str:
    clefs = list(part.flatten().getElementsByClass("Clef"))
    if not clefs:
        return "treble"
    cn = clefs[0].__class__.__name__.lower()
    for known in ("treble", "bass", "alto", "tenor", "percussion"):
        if known in cn:
            return "perc" if known == "percussion" else known
    return "treble"


# Sharps count → (major_key, relative_minor_key). Used to render the
# major/minor pair when the source doesn't explicitly say minor.
SHARPS_TO_RELATIVE_PAIR: dict[int, tuple[str, str]] = {
    -7: ("Cb", "Abm"), -6: ("Gb", "Ebm"), -5: ("Db", "Bbm"), -4: ("Ab", "Fm"),
    -3: ("Eb", "Cm"),  -2: ("Bb", "Gm"),  -1: ("F",  "Dm"),
     0: ("C",  "Am"),
     1: ("G",  "Em"),   2: ("D",  "Bm"),   3: ("A",  "F#m"),  4: ("E",  "C#m"),
     5: ("B",  "G#m"),  6: ("F#", "D#m"),  7: ("C#", "A#m"),
}


def format_key(ks) -> str:
    """KeySignature → MUS key string.

    Relative major/minor share the same signature, so a bare key signature
    is genuinely ambiguous. We render as the *pair* ('F/Dm') unless the
    source explicitly marks the mode as minor — in which case we trust it
    and emit the single form ('Dm'). Major is music21's default mode for
    bare key signatures, so we can't trust it; minor must be intentional.
    """
    sharps = getattr(ks, "sharps", 0) or 0

    # Trust explicit minor (it's never the default).
    mode = getattr(ks, "mode", None)
    tonic = getattr(ks, "tonic", None)
    if mode == "minor" and tonic is not None:
        return tonic.name.replace("-", "b") + "m"

    # Otherwise — render the ambiguous pair so analysis can pick correctly.
    pair = SHARPS_TO_RELATIVE_PAIR.get(sharps)
    if pair is None:
        return "C/Am"
    return f"{pair[0]}/{pair[1]}"


def read_credit_title(path: str) -> str | None:
    """Walk the MusicXML <credit><credit-type>title</credit-type><credit-words>...
    Musescore puts the *page* title here even when <work-title> is "Untitled score".
    Returns None if the file isn't MusicXML or no credit title is found.
    """
    p = Path(path)

    def _from_root(root) -> str | None:
        for credit in root.findall("credit"):
            ct = credit.find("credit-type")
            if ct is not None and (ct.text or "").strip() == "title":
                cw = credit.find("credit-words")
                if cw is not None and cw.text:
                    return cw.text.strip()
        return None

    try:
        if p.suffix.lower() == ".mxl":
            with zipfile.ZipFile(p) as z:
                # Find the actual score xml (usually "score.xml" or first non-META-INF .xml)
                for name in z.namelist():
                    if name.startswith("META-INF"):
                        continue
                    if name.lower().endswith(".xml"):
                        with z.open(name) as f:
                            root = ET.parse(f).getroot()
                            t = _from_root(root)
                            if t:
                                return t
        elif p.suffix.lower() in (".musicxml", ".xml"):
            root = ET.parse(p).getroot()
            return _from_root(root)
    except Exception:
        return None
    return None


def collect_slur_marks(score) -> tuple[set, set]:
    """Return (slur_start_ids, slur_end_ids) — sets of id() values for the
    first and last notes of each Slur in the score."""
    starts: set = set()
    ends: set = set()
    for slur in score.flatten().getElementsByClass(m21spanner.Slur):
        first = slur.getFirst()
        last = slur.getLast()
        if first is not None:
            starts.add(id(first))
        if last is not None:
            ends.add(id(last))
    return starts, ends


def collect_hairpin_marks(score) -> tuple[set, set, set]:
    """Return (cresc_start_ids, decresc_start_ids, hairpin_end_ids) — sets of
    id() values for the first/last notes of Crescendo and Diminuendo spanners.

    Emits as {<} (cresc), {>} (decresc), {|} (terminator) in the bar stream,
    inline like dynamics."""
    cresc_starts: set = set()
    decresc_starts: set = set()
    hairpin_ends: set = set()
    for c in score.flatten().getElementsByClass(m21dynamics.Crescendo):
        first = c.getFirst()
        last = c.getLast()
        if first is not None:
            cresc_starts.add(id(first))
        if last is not None:
            hairpin_ends.add(id(last))
    for d in score.flatten().getElementsByClass(m21dynamics.Diminuendo):
        first = d.getFirst()
        last = d.getLast()
        if first is not None:
            decresc_starts.add(id(first))
        if last is not None:
            hairpin_ends.add(id(last))
    return cresc_starts, decresc_starts, hairpin_ends


def collect_text_expressions(parts) -> dict[int, list[str]]:
    """Find TextExpression elements (system text, expression text, tempo text)
    and return {bar_number: [text, ...]}. Dedupes identical texts at same bar."""
    result: dict[int, list[str]] = {}
    seen_at_bar: dict[int, set[str]] = {}
    for part in parts:
        measures = list(part.getElementsByClass(stream.Measure))
        for bar_num, m in enumerate(measures, start=1):
            for te in m.flatten().getElementsByClass(m21expressions.TextExpression):
                content = (te.content or "").strip()
                if not content:
                    continue
                if bar_num not in seen_at_bar:
                    seen_at_bar[bar_num] = set()
                if content in seen_at_bar[bar_num]:
                    continue
                seen_at_bar[bar_num].add(content)
                result.setdefault(bar_num, []).append(content)
    return result


def collect_sections(parts) -> list[tuple[int, int, str]]:
    """Find rehearsal marks and return (start_bar, end_bar, name) tuples.
    Each section runs from its mark to the bar before the next mark (or end of song)."""
    marks: list[tuple[int, str]] = []
    for part in parts:
        measures = list(part.getElementsByClass(stream.Measure))
        for bar_num, m in enumerate(measures, start=1):
            for rm in m.getElementsByClass(m21expressions.RehearsalMark):
                if rm.content:
                    marks.append((bar_num, rm.content))
    # Dedupe by bar number — the same mark may appear in multiple parts
    seen_bars: dict[int, str] = {}
    for bar, name in marks:
        if bar not in seen_bars:
            seen_bars[bar] = name
    sorted_marks = sorted(seen_bars.items())
    if not sorted_marks:
        return []
    # Build ranges
    total_bars = max(len(list(p.getElementsByClass(stream.Measure))) for p in parts)
    sections: list[tuple[int, int, str]] = []
    for i, (bar, name) in enumerate(sorted_marks):
        end_bar = sorted_marks[i + 1][0] - 1 if i + 1 < len(sorted_marks) else total_bars
        sections.append((bar, end_bar, name))
    return sections


def bar_events_with_dynamics(m: stream.Measure) -> list:
    """Walk a measure in offset order, including dynamics interleaved with notes/rests."""
    events = []
    for cls_name in ("Note", "Rest", "Chord", "Unpitched", "PercussionChord"):
        for e in m.flatten().getElementsByClass(cls_name):
            events.append(("event", e.offset, e))
    for d in m.flatten().getElementsByClass(m21dynamics.Dynamic):
        events.append(("dynamic", d.offset, d))
    events.sort(key=lambda x: (x[1], 0 if x[0] == "dynamic" else 1))
    return events


def collect_changes(parts) -> tuple[list, list, list]:
    """Walk measures and return (tempo_changes, key_changes, time_changes).
    Each is a list of (bar_num, value) where the value first becomes that.
    Dedupes successive identical values."""
    tempo_changes: list[tuple[int, int]] = []
    key_changes: list[tuple[int, str]] = []
    time_changes: list[tuple[int, str]] = []

    measures = list(parts[0].getElementsByClass(stream.Measure))
    for bar_num, m in enumerate(measures, start=1):
        for mm in m.getElementsByClass(m21tempo.MetronomeMark):
            if mm.number:
                v = int(round(mm.number))
                if not tempo_changes or tempo_changes[-1][1] != v:
                    tempo_changes.append((bar_num, v))
        for ks in m.getElementsByClass(key.KeySignature):
            v = format_key(ks)
            if not key_changes or key_changes[-1][1] != v:
                key_changes.append((bar_num, v))
        for ts in m.getElementsByClass(meter.TimeSignature):
            v = ts.ratioString
            if not time_changes or time_changes[-1][1] != v:
                time_changes.append((bar_num, v))

    return tempo_changes, key_changes, time_changes


# Number of changes of a single kind (tempo/time/key) above which we summarize
# in the header and emit each change inline at its bar instead of a giant arrow chain.
INLINE_CHANGE_THRESHOLD = 10


def format_change_list(changes: list, label: str, default: str = "",
                       threshold: int = INLINE_CHANGE_THRESHOLD) -> str:
    """Render a change list for the header.

    - Empty: 'tempo: <default>'
    - Single: 'tempo: 145'
    - Few (≤threshold): 'tempo: 145 (b1) → 110 (b40) → 80 (b89)'
    - Many (>threshold): 'tempo: 145 (initial; N changes inline)'
    """
    if not changes:
        return f"{label}: {default}"
    if len(changes) == 1:
        return f"{label}: {changes[0][1]}"
    if len(changes) <= threshold:
        parts = [f"{v} (b{b})" for b, v in changes]
        return f"{label}: " + " → ".join(parts)
    first = changes[0][1]
    return f"{label}: {first} (initial; {len(changes) - 1} changes inline)"


def collect_inline_changes(
    tempo_changes: list,
    time_changes: list,
    key_changes: list,
    threshold: int = INLINE_CHANGE_THRESHOLD,
) -> dict[int, list[str]]:
    """For each change kind that exceeds the threshold, accumulate its
    non-initial changes into per-bar inline markers like 'tempo=110'.
    Returns {bar_num: [marker, ...]}.
    """
    inline: dict[int, list[str]] = {}
    for kind, changes in (("tempo", tempo_changes),
                          ("time", time_changes),
                          ("key", key_changes)):
        if len(changes) <= threshold:
            continue
        for bar_num, value in changes[1:]:  # initial value remains in header
            inline.setdefault(bar_num, []).append(f"{kind}={value}")
    return inline


def main_forward(args) -> int:
    """Score → MUS. Reads MIDI/MusicXML, emits MUS to stdout."""
    score = converter.parse(args.input_path)

    # Title resolution order:
    #   1. Explicit --title flag
    #   2. <credit-words> with <credit-type>title</credit-type>  (Musescore's page title)
    #   3. score.metadata.title  (the <work-title> field — Musescore leaves this as boilerplate)
    #   4. Filename stem
    title = args.title
    if not title:
        title = read_credit_title(args.input_path)
    if not title:
        if score.metadata and score.metadata.title:
            mt = score.metadata.title.strip()
            if mt and mt.lower() != "untitled score":
                title = mt
    if not title:
        title = Path(args.input_path).stem

    parts = list(score.parts)
    if not parts:
        print("# (no parts found in MIDI)", file=sys.stderr)
        return 1

    # Determine bar count from longest part
    bar_count = max(len(list(p.getElementsByClass(stream.Measure))) for p in parts)

    # Collect tempo/key/time changes across the whole song
    tempo_changes, key_changes, time_changes = collect_changes(parts)

    # Estimate duration for the summary line
    qpb = 4
    if time_changes:
        try:
            num, den = time_changes[0][1].split("/")
            qpb = int(num) * 4 // int(den)
        except (ValueError, ZeroDivisionError):
            pass
    if tempo_changes:
        avg_tempo = sum(t for _, t in tempo_changes) / len(tempo_changes)
    else:
        avg_tempo = 120
    est_minutes = max(1, int(round(bar_count * qpb / avg_tempo)))

    # Warn if source contains no dynamics anywhere — useful diagnostic for
    # scores stripped during MuseScore export, missing playback layers, etc.
    has_dynamics = any(
        list(p.flatten().getElementsByClass(m21dynamics.Dynamic)) for p in parts
    )
    if not has_dynamics:
        print(
            "Warning: source contains no dynamic markings — output will have no dynamics field.",
            file=sys.stderr,
        )

    # Header
    print(f"# score: {title}")
    print(f"# summary: {bar_count} bars / {len(parts)} voices / ~{est_minutes} min")
    print(f"# {format_change_list(tempo_changes, 'tempo', '120')}")
    print(f"# {format_change_list(time_changes, 'time', '4/4')}")
    print(f"# {format_change_list(key_changes, 'key', 'C')}")
    print(f"# bars: {bar_count}")
    print()

    # Instruments
    print("# instruments:")
    abbrevs = assign_track_names(parts)
    for i, part in enumerate(parts):
        full = part_full_name(part)
        clef = part_clef(part)
        print(f"#   {abbrevs[i]} = {full} ({clef})")
    print()

    # Slur start/end markers — wrap event tokens with ( and ).
    slur_starts, slur_ends = collect_slur_marks(score)

    def wrap_slur(token: str, elem) -> str:
        eid = id(elem)
        if eid in slur_starts:
            token = "(" + token
        if eid in slur_ends:
            token = token + ")"
        return token

    # Hairpin start/end markers — emit {<}/{>} before, {|} after the anchor note.
    cresc_starts, decresc_starts, hairpin_ends = collect_hairpin_marks(score)

    def hairpin_prefix(elem) -> str:
        eid = id(elem)
        if eid in cresc_starts:
            return "{<} "
        if eid in decresc_starts:
            return "{>} "
        return ""

    def hairpin_suffix(elem) -> str:
        return " {|}" if id(elem) in hairpin_ends else ""

    # Collect per-bar per-track content, applying within-bar pattern compression.
    # Tracks current dynamic per-part across bars to emit only at changes.
    current_dynamic: dict[int, str] = {}
    bar_data: list[dict[str, str]] = []
    for bar_num in range(1, bar_count + 1):
        per_track: dict[str, str] = {}
        for i, part in enumerate(parts):
            measures = list(part.getElementsByClass(stream.Measure))
            if bar_num > len(measures):
                per_track[abbrevs[i]] = "-"
                continue
            m = measures[bar_num - 1]
            tokens: list[str] = []
            for kind, _offset, obj in bar_events_with_dynamics(m):
                if kind == "dynamic":
                    val = obj.value
                    if current_dynamic.get(i) != val:
                        tokens.append("{" + val + "}")
                        current_dynamic[i] = val
                else:
                    body = wrap_slur(event_to_mus(obj), obj)
                    tokens.append(hairpin_prefix(obj) + body + hairpin_suffix(obj))
            content = find_pattern_in_events(tokens) if tokens else "-"
            per_track[abbrevs[i]] = content
        bar_data.append(per_track)

    # Map sections to start-bars for emission
    sections = collect_sections(parts)
    section_at: dict[int, tuple[int, str]] = {start: (end, name) for start, end, name in sections}

    # System text expressions, keyed by bar number
    text_at: dict[int, list[str]] = collect_text_expressions(parts)

    # Inline change markers — emitted when a change-kind exceeds the threshold,
    # so the header stays readable and the changes land at their actual bars.
    inline_changes_at: dict[int, list[str]] = collect_inline_changes(
        tempo_changes, time_changes, key_changes
    )

    # Emit with tacet- and identical-run compression.
    def is_tacet(d: dict[str, str]) -> bool:
        return all(c in ("Rw", "-") for c in d.values())

    def render_bar_content(d: dict[str, str]) -> str:
        return "  ".join(f"{abbr}={d[abbr]}" for abbr in abbrevs if abbr in d)

    n = len(bar_data)
    idx = 0
    while idx < n:
        # Emit a section header if this bar starts one.
        if (idx + 1) in section_at:
            end_bar, name = section_at[idx + 1]
            print()
            print(f"# section: {name} [{idx + 1}-{end_bar}]")
        # Emit any system text expressions at this bar.
        if (idx + 1) in text_at:
            for txt in text_at[idx + 1]:
                print(f"# text @b{idx + 1}: {txt}")
        # Tacet run?
        if is_tacet(bar_data[idx]):
            j = idx
            while j < n and is_tacet(bar_data[j]):
                j += 1
            if j > idx + 1:
                print(f"bars {idx + 1}-{j}: tacet")
            else:
                print(f"bar {idx + 1}: tacet")
            idx = j
            continue

        # Identical-bar run? (We can only collapse if no inline change marker
        # falls inside the run, since a change at bar k must be visible at k.)
        bar_one_based = idx + 1
        j = idx + 1
        while j < n and bar_data[j] == bar_data[idx] and (j + 1) not in inline_changes_at:
            j += 1
        if j > idx + 1:
            label = f"bars {bar_one_based}-{j}"
        else:
            label = f"bar {bar_one_based}"
        inline_str = ""
        if bar_one_based in inline_changes_at:
            inline_str = " [" + ", ".join(inline_changes_at[bar_one_based]) + "]"
        print(f"{label}{inline_str}: {render_bar_content(bar_data[idx])}")
        idx = j

    return 0


# ============================================================================
# REVERSE DIRECTION: MUS → music21 → MusicXML/MIDI
# ============================================================================
#
# Round-trip target: a .mus file produced by the forward direction can be
# parsed back into a music21 Score and emitted as MusicXML or MIDI for
# re-import into Musescore. This closes the conversational loop — edits
# made in MUS by hand or by an LLM go back into the human's notation tool.


# Inverse maps built from the forward dicts -----------------------------------

QL_FROM_DURATION_CODE: dict[str, Fraction] = {v: k for k, v in DURATION_MAP.items()}
TYPE_FROM_BASE: dict[str, str] = {v: k for k, v in TYPE_TO_BASE.items()}
RATIO_FROM_TUPLET_SHORT: dict[str, tuple[int, int]] = {
    v: k for k, v in TUPLET_SHORTHAND.items()
}


def _invert_first_wins(d: dict) -> dict:
    """Invert a dict, taking the first-occurring source for each target."""
    out: dict = {}
    for k, v in d.items():
        if v not in out:
            out[v] = k
    return out


CLS_FROM_ARTICULATION_CODE = _invert_first_wins(ARTICULATION_MAP)
CLS_FROM_EXPRESSION_CODE = _invert_first_wins(EXPRESSION_MAP)

# Codes the forward converter emits as a class-name lowercase fallback (not via
# the explicit maps). Match them back to their music21 class so they survive
# round-trip.
CLS_FROM_EXPRESSION_CODE.setdefault("arpeggiomark", "ArpeggioMark")
CLS_FROM_EXPRESSION_CODE.setdefault("arpeggio", "ArpeggioMark")

KEY_PAIRS_TO_SHARPS: dict[str, int] = {
    f"{maj}/{minr}": s for s, (maj, minr) in SHARPS_TO_RELATIVE_PAIR.items()
}
KEY_MAJOR_TO_SHARPS: dict[str, int] = {
    maj: s for s, (maj, _) in SHARPS_TO_RELATIVE_PAIR.items()
}
KEY_MINOR_TO_SHARPS: dict[str, int] = {
    minr: s for s, (_, minr) in SHARPS_TO_RELATIVE_PAIR.items()
}

CLEF_FROM_NAME: dict[str, str] = {
    "treble": "TrebleClef",
    "bass": "BassClef",
    "alto": "AltoClef",
    "tenor": "TenorClef",
    "perc": "PercussionClef",
}


# Pitch / duration / articulation token-level parsers -------------------------

# Optional trailing cents offset (`A6+22`) — the microtonal form SPEC.md raises
# as an open question and SPEC-AUDIO.md adopts. Carried as music21's
# Pitch.microtone, so it survives MUS → music21 → MUS intact. It does NOT reach
# MusicXML: music21's exporter emits only the integer accidental as <alter>
# (F#6+21 → <alter>1</alter>) and nothing at all for an inflected natural, even
# though MusicXML itself permits a fractional alter.
RE_PITCH = re.compile(r"^([A-G])(bb|b|n|##|#|x)?(-?\d+)([+-]\d+)?$")
RE_PITCH_HEAD = r"[A-G](?:bb|b|n|##|#|x)?-?\d+(?:[+-]\d+)?"
RE_DURATION_BASE = re.compile(
    r"^([whqestxWHQESTX][whqestxWHQESTX]?)(\.*)(\d+|\{\d+:\d+\})?$"
)
RE_ARTIC_SUFFIX = re.compile(r"\[([^\]]+)\]")
RE_RANGE_PIECE = re.compile(r"^(\S+)\s*\(b(\d+)\)\s*$")

_ACC_MAP = {None: "", "b": "-", "bb": "--", "n": "n", "#": "#", "x": "##", "##": "##"}


def parse_pitch_token(s: str):
    """Parse 'Bb4', 'F#5', 'Bbb3', 'Fx4', 'A6+22' → music21 Pitch (or None)."""
    m = RE_PITCH.match(s)
    if not m:
        return None
    step = m.group(1)
    acc = m.group(2)
    octave = int(m.group(3))
    cents = int(m.group(4)) if m.group(4) else 0
    acc_str = _ACC_MAP.get(acc, "")
    try:
        p = m21pitch.Pitch(f"{step}{acc_str}{octave}")
    except Exception:
        return None
    if cents:
        try:
            p.microtone = cents
        except Exception:
            pass
    return p


def parse_duration_code(code: str):
    """Parse 'q', 'q.', 'e3', 'q{5:6}', 'ww' → music21 Duration (or None)."""
    if code in QL_FROM_DURATION_CODE:
        return m21duration.Duration(float(QL_FROM_DURATION_CODE[code]))
    m = RE_DURATION_BASE.match(code)
    if not m:
        return None
    base = m.group(1).lower()
    if base not in TYPE_FROM_BASE:
        return None
    dots = len(m.group(2))
    tuplet_str = m.group(3)

    d = m21duration.Duration()
    try:
        d.type = TYPE_FROM_BASE[base]
    except Exception:
        return None
    if dots:
        try:
            d.dots = dots
        except Exception:
            pass
    if tuplet_str:
        if tuplet_str.startswith("{"):
            mr = re.match(r"\{(\d+):(\d+)\}", tuplet_str)
            if mr:
                actual, normal = int(mr.group(1)), int(mr.group(2))
                try:
                    d.appendTuplet(m21duration.Tuplet(
                        numberNotesActual=actual,
                        numberNotesNormal=normal,
                    ))
                except Exception:
                    pass
        else:
            ratio = RATIO_FROM_TUPLET_SHORT.get(tuplet_str)
            if ratio:
                try:
                    d.appendTuplet(m21duration.Tuplet(
                        numberNotesActual=ratio[0],
                        numberNotesNormal=ratio[1],
                    ))
                except Exception:
                    pass
    return d


def _titlecase_tag(tag: str) -> str:
    """'arpeggiomark' → 'Arpeggiomark'; 'invmord' → 'Invmord'."""
    if not tag:
        return tag
    return tag[0].upper() + tag[1:]


def parse_articulation_codes(suffix: str):
    """Parse 'stac,acc,fer' → (list[Articulation], list[Expression]).
    First-pass: explicit maps. Second-pass: TitleCase the tag and try the music21
    class by name. Unknown tags are silently dropped."""
    arts: list = []
    exprs: list = []
    if not suffix:
        return arts, exprs
    for tag in (t.strip() for t in suffix.split(",")):
        if not tag:
            continue
        base_tag = tag.split(".")[0]

        # Explicit expression map first.
        cls_name = (CLS_FROM_EXPRESSION_CODE.get(tag)
                    or CLS_FROM_EXPRESSION_CODE.get(base_tag))
        if cls_name:
            cls = getattr(m21expressions, cls_name, None)
            if cls:
                try:
                    exprs.append(cls())
                    continue
                except Exception:
                    pass

        # Explicit articulation map.
        cls_name = (CLS_FROM_ARTICULATION_CODE.get(tag)
                    or CLS_FROM_ARTICULATION_CODE.get(base_tag))
        if cls_name:
            cls = getattr(m21articulations, cls_name, None)
            if cls:
                try:
                    arts.append(cls())
                    continue
                except Exception:
                    pass

        # Fallback: maybe the tag IS the lowercase class name (the forward
        # converter emits cls.__name__.lower() for any unrecognized class).
        titlecase = _titlecase_tag(base_tag)
        for module, target_list in ((m21expressions, exprs),
                                     (m21articulations, arts)):
            cls = getattr(module, titlecase, None)
            if cls is None:
                # try CamelCase ("ArpeggioMark" from "arpeggiomark") via title()
                cls = getattr(module, base_tag.title(), None)
            if cls is not None:
                try:
                    target_list.append(cls())
                    break
                except Exception:
                    pass
    return arts, exprs


def parse_key_string(key_str: str):
    """Parse 'F/Dm', 'Gm', 'C' → (sharps, mode_or_None, tonic_or_None)."""
    key_str = (key_str or "").strip()
    if "/" in key_str:
        sharps = KEY_PAIRS_TO_SHARPS.get(key_str)
        return ((sharps if sharps is not None else 0), None, None)
    if key_str.endswith("m") and len(key_str) > 1:
        sharps = KEY_MINOR_TO_SHARPS.get(key_str)
        if sharps is not None:
            return (sharps, "minor", key_str[:-1])
    sharps = KEY_MAJOR_TO_SHARPS.get(key_str)
    if sharps is not None:
        return (sharps, "major", key_str)
    return (0, None, None)


# File-level parser ----------------------------------------------------------

@dataclass
class MusInstrument:
    abbrev: str
    name: str
    clef: str
    transpose: int | None = None
    # Any further `key=value` items in the instrument parenthetical. Unknown to
    # the notation converter, but preserved so extensions (e.g. sample binding
    # for the audio renderer) can read them off the same declaration line.
    params: dict[str, str] = field(default_factory=dict)


@dataclass
class MusBar:
    bar_num: int
    end_bar: int
    track_content: dict[str, str]
    inline_changes: list[str] = field(default_factory=list)


@dataclass
class ParsedMus:
    title: str
    summary: str | None
    tempo_changes: list[tuple[int, int]]
    time_changes: list[tuple[int, str]]
    key_changes: list[tuple[int, str]]
    bar_count: int
    instruments: list[MusInstrument]
    bars: list[MusBar]
    sections: list[tuple[int, int, str]]
    text_at: dict[int, list[str]]
    # Header `# key: value` lines the notation converter doesn't recognise
    # (e.g. `# tuning: A=445.6`). Preserved rather than dropped.
    extra: dict[str, str] = field(default_factory=dict)


RE_HEADER_KV = re.compile(r"^\s*(\w+)\s*:\s*(.+?)\s*$")
# SPEC.md documents the metadata block as one line —
#   `# tempo: 82    time: 4/4    key: Dm    bars: 16`
# — while main_forward() emits one key per line. Accept both by splitting a
# header line before any *known* subsequent key, which leaves free-text values
# (titles, summaries) that happen to contain a colon intact.
RE_HEADER_SPLIT = re.compile(r"\s+(?=(?:tempo|time|key|bars)\s*:)", re.IGNORECASE)
RE_INSTRUMENT = re.compile(r"^\s*(\S+)\s*=\s*(.+?)\s*\(([^)]+)\)\s*$")
# Trailing prose after the bar range is allowed ("# section: ice [25-38] —
# resolved frames only…"). It must parse as a section, because a section line
# that falls through to header parsing can contain words like "tempo:" and
# silently re-tempo the piece — a real incident (2026-08-09).
RE_SECTION = re.compile(r"^\s*section\s*:\s*(.+?)\s*\[(\d+)-(\d+)\]\s*(?:[—–-].*)?$")
RE_TEXT = re.compile(r"^\s*text\s*@b(\d+)\s*:\s*(.+?)\s*$")
RE_BAR = re.compile(r"^bar\s+(\d+)\s*(?:\[([^\]]+)\])?\s*:\s*(.+)$")
RE_BARS_RANGE = re.compile(r"^bars\s+(\d+)-(\d+)\s*(?:\[([^\]]+)\])?\s*:\s*(.+)$")


def parse_mus(text: str) -> ParsedMus:
    """Parse a .mus file's text into a ParsedMus structure."""
    title = "Untitled"
    summary: str | None = None
    bar_count = 0
    tempo_str: str | None = None
    time_str: str | None = None
    key_str: str | None = None
    instruments: list[MusInstrument] = []
    bars: list[MusBar] = []
    sections: list[tuple[int, int, str]] = []
    text_at: dict[int, list[str]] = {}
    extra: dict[str, str] = {}
    in_instruments = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            in_instruments = False
            continue

        if line.lstrip().startswith("#"):
            body = line.lstrip("#").strip()

            m_text = RE_TEXT.match(body)
            if m_text:
                bar = int(m_text.group(1))
                text_at.setdefault(bar, []).append(m_text.group(2).strip())
                in_instruments = False
                continue

            m_sec = RE_SECTION.match(body)
            if m_sec:
                name = m_sec.group(1).strip()
                if "—" in name:
                    name = name.split("—")[0].strip()
                sections.append((int(m_sec.group(2)), int(m_sec.group(3)), name))
                in_instruments = False
                continue

            if body.lower() in ("instruments:", "instruments"):
                in_instruments = True
                continue

            if in_instruments:
                m_inst = RE_INSTRUMENT.match(body)
                if m_inst:
                    parts = [p.strip() for p in m_inst.group(3).split(",")]
                    clef_name = parts[0] if parts else "treble"
                    transpose: int | None = None
                    params: dict[str, str] = {}
                    for p in parts[1:]:
                        if "=" in p:
                            k, v = p.split("=", 1)
                            params[k.strip().lower()] = v.strip()
                            continue
                        try:
                            transpose = int(p)
                        except ValueError:
                            pass
                    instruments.append(MusInstrument(
                        abbrev=m_inst.group(1),
                        name=m_inst.group(2),
                        clef=clef_name,
                        transpose=transpose,
                        params=params,
                    ))
                continue

            # Guard: annotation-shaped comment lines never reach header
            # parsing, even when malformed — see the RE_SECTION note above.
            if body.lower().startswith(("section", "text")):
                continue

            for piece in RE_HEADER_SPLIT.split(body):
                m_kv = RE_HEADER_KV.match(piece)
                if not m_kv:
                    continue
                key_name = m_kv.group(1).lower()
                val = m_kv.group(2).strip()
                if key_name == "score":
                    title = val
                elif key_name == "summary":
                    summary = val
                elif key_name == "tempo":
                    tempo_str = val
                elif key_name == "time":
                    time_str = val
                elif key_name == "key":
                    key_str = val
                elif key_name == "bars":
                    try:
                        bar_count = int(val)
                    except ValueError:
                        pass
                else:
                    extra[key_name] = val
            continue

        m_bars = RE_BARS_RANGE.match(line)
        m_single = RE_BAR.match(line)
        if m_bars:
            bar_num = int(m_bars.group(1))
            end_bar = int(m_bars.group(2))
            inline_str = m_bars.group(3) or ""
            content = m_bars.group(4)
        elif m_single:
            bar_num = int(m_single.group(1))
            end_bar = bar_num
            inline_str = m_single.group(2) or ""
            content = m_single.group(3)
        else:
            continue

        inline_changes = (
            [c.strip() for c in inline_str.split(",")] if inline_str else []
        )

        if content.strip() == "tacet":
            track_content = {inst.abbrev: "-" for inst in instruments}
        else:
            track_content = _split_bar_content(
                content, [inst.abbrev for inst in instruments]
            )

        bars.append(MusBar(bar_num, end_bar, track_content, inline_changes))

    tempo_changes = _parse_header_change_list(tempo_str or "", to_int=True)
    time_changes = _parse_header_change_list(time_str or "", to_int=False)
    key_changes = _parse_header_change_list(key_str or "", to_int=False)

    if not bar_count and bars:
        bar_count = max(b.end_bar for b in bars)

    return ParsedMus(
        title=title,
        summary=summary,
        tempo_changes=tempo_changes,
        time_changes=time_changes,
        key_changes=key_changes,
        bar_count=bar_count,
        instruments=instruments,
        bars=bars,
        sections=sections,
        text_at=text_at,
        extra=extra,
    )


def _split_bar_content(content: str, track_abbrevs: list[str]) -> dict[str, str]:
    """Split 'pi.r=... pi.l=...' style content into {abbrev: substring}."""
    if not track_abbrevs:
        return {}
    sorted_abbrevs = sorted(track_abbrevs, key=len, reverse=True)
    pattern = re.compile(
        r"(?:^|\s)(" + "|".join(re.escape(a) for a in sorted_abbrevs) + r")="
    )
    matches = list(pattern.finditer(content))
    result: dict[str, str] = {}
    for i, m in enumerate(matches):
        abbr = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        result[abbr] = content[start:end].strip()
    return result


def _parse_header_change_list(s: str, to_int: bool):
    """Parse '72 (b1) → 60 (b67)' / '72' / '72 (initial; 60 changes inline)'."""
    s = s.strip()
    if not s:
        return []

    def coerce(v):
        if not to_int:
            return v
        try:
            return int(v)
        except (ValueError, TypeError):
            return v

    if "(initial" in s:
        first = s.split(" ", 1)[0]
        try:
            return [(1, coerce(first))]
        except Exception:
            return []

    if "→" not in s and "(b" not in s:
        try:
            return [(1, coerce(s))]
        except Exception:
            return []

    result: list = []
    for piece in s.split("→"):
        piece = piece.strip()
        m = RE_RANGE_PIECE.match(piece)
        if m:
            try:
                result.append((int(m.group(2)), coerce(m.group(1))))
            except Exception:
                pass
        else:
            try:
                result.append((1, coerce(piece)))
            except Exception:
                pass
    return result


# Tokenizer ------------------------------------------------------------------

def tokenize_bar_content(content: str) -> list[str]:
    """Whitespace-split with bracket-balancing so <chords> and {marks} survive whole."""
    tokens: list[str] = []
    i = 0
    n = len(content)
    while i < n:
        if content[i].isspace():
            i += 1
            continue
        start = i
        depth_angle = 0
        depth_brace = 0
        in_quote = False
        while i < n:
            c = content[i]
            if in_quote:
                if c == '"':
                    in_quote = False
                i += 1
                continue
            if c == '"':
                in_quote = True
                i += 1
                continue
            if c == "<":
                depth_angle += 1
                i += 1
                continue
            if c == ">":
                if depth_angle > 0:
                    depth_angle -= 1
                i += 1
                continue
            if c == "{":
                depth_brace += 1
                i += 1
                continue
            if c == "}":
                if depth_brace > 0:
                    depth_brace -= 1
                i += 1
                continue
            if c.isspace() and depth_angle == 0 and depth_brace == 0:
                break
            i += 1
        tokens.append(content[start:i])
    return tokens


def expand_pattern_repetitions(tokens: list[str]) -> list[str]:
    """Expand '(... ×N)' sub-bar pattern repetitions in-place."""
    text = " ".join(tokens)
    while True:
        m = re.search(r"\(([^()]*?)\s*×\s*(\d+)\)", text)
        if not m:
            break
        pattern = m.group(1).strip()
        n = int(m.group(2))
        text = text[:m.start()] + " ".join([pattern] * n) + text[m.end():]
    return tokenize_bar_content(text)


# Event-token parser ---------------------------------------------------------

@dataclass
class ParsedEventToken:
    kind: str  # 'note' / 'chord' / 'rest' / 'dynamic' / 'hairpin_start' / 'hairpin_end' / 'tacet' / 'unknown'
    pitches: list = field(default_factory=list)
    duration_codes: list[str] = field(default_factory=list)
    articulations: list = field(default_factory=list)
    expressions: list = field(default_factory=list)
    slur_start: bool = False
    slur_end: bool = False
    dynamic_value: str | None = None
    raw: str = ""


def parse_event_token(token: str) -> ParsedEventToken:
    """Parse a single token like 'G4q' / '<C4 E4 G4>w[fer]' / 'Rh' / '{p}' / '{<}'."""
    raw = token

    # Slur wrappers: '(G4q' or 'G4q)' (must not mis-strip '({')
    slur_start = token.startswith("(") and not token.startswith("({")
    if slur_start:
        token = token[1:]
    slur_end = token.endswith(")") and not token.endswith(("}", ">"))
    if slur_end:
        token = token[:-1]

    if token == "{<}":
        return ParsedEventToken(kind="hairpin_start", dynamic_value="cresc", raw=raw)
    if token == "{>}":
        return ParsedEventToken(kind="hairpin_start", dynamic_value="decresc", raw=raw)
    if token == "{|}":
        return ParsedEventToken(kind="hairpin_end", raw=raw)
    if token.startswith("{") and token.endswith("}"):
        return ParsedEventToken(kind="dynamic", dynamic_value=token[1:-1], raw=raw)

    if token == "-":
        return ParsedEventToken(kind="tacet", raw=raw)

    artic_match = RE_ARTIC_SUFFIX.search(token)
    art_suffix = ""
    if artic_match:
        art_suffix = artic_match.group(1)
        token = token[:artic_match.start()] + token[artic_match.end():]
    arts, exprs = parse_articulation_codes(art_suffix)

    if token.startswith("<"):
        close = token.find(">")
        if close < 0:
            return ParsedEventToken(kind="unknown", raw=raw)
        chord_body = token[1:close]
        dur_part = token[close + 1:]
        pitch_strs = chord_body.split()
        pitches = [p for p in (parse_pitch_token(s) for s in pitch_strs) if p is not None]
        if not pitches:
            return ParsedEventToken(kind="unknown", raw=raw)
        duration_codes = dur_part.split("~") if "~" in dur_part else [dur_part]
        return ParsedEventToken(
            kind="chord",
            pitches=pitches,
            duration_codes=duration_codes,
            articulations=arts,
            expressions=exprs,
            slur_start=slur_start,
            slur_end=slur_end,
            raw=raw,
        )

    if token.startswith("R"):
        dur_part = token[1:]
        if not dur_part:
            return ParsedEventToken(kind="rest", duration_codes=[], raw=raw)
        duration_codes = dur_part.split("~") if "~" in dur_part else [dur_part]
        return ParsedEventToken(kind="rest", duration_codes=duration_codes, raw=raw)

    if token.startswith("X"):
        # Unpitched/percussion — placeholder rest for MVP. (v0.5: GM mapping)
        dur_match = re.search(r"([whqestx][whqestx]?\.*\d?(?:\{\d+:\d+\})?)$", token)
        duration_codes = [dur_match.group(1)] if dur_match else ["q"]
        return ParsedEventToken(kind="rest", duration_codes=duration_codes, raw=raw)

    pitch_match = re.match(rf"^({RE_PITCH_HEAD})(.+)$", token)
    if not pitch_match:
        return ParsedEventToken(kind="unknown", raw=raw)
    pitch = parse_pitch_token(pitch_match.group(1))
    if pitch is None:
        return ParsedEventToken(kind="unknown", raw=raw)
    dur_part = pitch_match.group(2)
    duration_codes = dur_part.split("~") if "~" in dur_part else [dur_part]
    return ParsedEventToken(
        kind="note",
        pitches=[pitch],
        duration_codes=duration_codes,
        articulations=arts,
        expressions=exprs,
        slur_start=slur_start,
        slur_end=slur_end,
        raw=raw,
    )


# Score builder --------------------------------------------------------------

def _make_clef(name: str):
    cls_name = CLEF_FROM_NAME.get(name, "TrebleClef")
    cls = getattr(m21clef, cls_name, m21clef.TrebleClef)
    return cls()


def build_score(parsed: ParsedMus):
    """Build a music21 Score from a ParsedMus."""
    score = stream.Score()
    md = m21metadata.Metadata()
    md.title = parsed.title
    md.movementName = parsed.title
    score.metadata = md

    initial_tempo = parsed.tempo_changes[0][1] if parsed.tempo_changes else 120
    initial_time = parsed.time_changes[0][1] if parsed.time_changes else "4/4"
    initial_key = parsed.key_changes[0][1] if parsed.key_changes else "C"

    # Expand 'bars N-M' into per-bar content
    bar_content_at: dict[int, dict[str, str]] = {}
    inline_changes_at: dict[int, list[str]] = {}
    for mb in parsed.bars:
        for b in range(mb.bar_num, mb.end_bar + 1):
            bar_content_at[b] = dict(mb.track_content)
            if mb.inline_changes:
                inline_changes_at[b] = list(mb.inline_changes)

    tempo_at: dict[int, int] = {b: v for b, v in parsed.tempo_changes}
    time_at: dict[int, str] = {b: v for b, v in parsed.time_changes}
    key_at: dict[int, str] = {b: v for b, v in parsed.key_changes}

    for bar_num, changes in inline_changes_at.items():
        for c in changes:
            if "=" not in c:
                continue
            k, v = c.split("=", 1)
            k, v = k.strip().lower(), v.strip()
            if k == "tempo":
                try:
                    tempo_at[bar_num] = int(v)
                except ValueError:
                    pass
            elif k == "time":
                time_at[bar_num] = v
            elif k == "key":
                key_at[bar_num] = v

    section_at: dict[int, str] = {start: name for start, _, name in parsed.sections}

    inst_by_abbr: dict[str, MusInstrument] = {i.abbrev: i for i in parsed.instruments}
    parts_in_order: list[tuple[str, stream.Part]] = []
    for inst in parsed.instruments:
        p = stream.Part()
        p.id = inst.abbrev
        p.partName = inst.name
        try:
            inst_obj = m21instrument.fromString(inst.name)
        except Exception:
            inst_obj = (m21instrument.Piano() if "piano" in inst.name.lower()
                        else m21instrument.Instrument())
        inst_obj.partName = inst.name
        p.insert(0, inst_obj)
        parts_in_order.append((inst.abbrev, p))

    open_cresc: dict[str, list] = {abbr: [] for abbr, _ in parts_in_order}
    open_decresc: dict[str, list] = {abbr: [] for abbr, _ in parts_in_order}
    open_slurs: dict[str, list] = {abbr: [] for abbr, _ in parts_in_order}
    pending_hairpins: list = []  # finalized hairpin spanners
    pending_slurs: list = []     # finalized slur spanners

    current_time_sig = initial_time

    for bar_num in range(1, parsed.bar_count + 1):
        bar_content = bar_content_at.get(bar_num, {})
        if bar_num in time_at:
            current_time_sig = time_at[bar_num]

        for abbr, part in parts_in_order:
            inst = inst_by_abbr[abbr]
            m = stream.Measure(number=bar_num)

            if bar_num == 1:
                m.insert(0, _make_clef(inst.clef))

            if bar_num == 1 or bar_num in time_at:
                try:
                    m.timeSignature = meter.TimeSignature(current_time_sig)
                except Exception:
                    m.timeSignature = meter.TimeSignature("4/4")

            if bar_num == 1 or bar_num in key_at:
                ks_str = key_at.get(bar_num, initial_key)
                sharps, mode, tonic = parse_key_string(ks_str)
                if mode == "minor" and tonic:
                    try:
                        m.keySignature = key.Key(tonic, "minor")
                    except Exception:
                        m.keySignature = key.KeySignature(sharps)
                else:
                    m.keySignature = key.KeySignature(sharps)

            if bar_num == 1 or bar_num in tempo_at:
                t_val = tempo_at.get(bar_num, initial_tempo)
                try:
                    m.insert(0, m21tempo.MetronomeMark(number=int(t_val)))
                except Exception:
                    pass

            if bar_num in section_at:
                try:
                    m.insert(0, m21expressions.RehearsalMark(section_at[bar_num]))
                except Exception:
                    pass

            if bar_num in parsed.text_at:
                for txt in parsed.text_at[bar_num]:
                    try:
                        m.insert(0, m21expressions.TextExpression(txt))
                    except Exception:
                        pass

            content = bar_content.get(abbr, "")
            if not content or content == "-":
                ts = m.timeSignature or meter.TimeSignature(current_time_sig)
                r = note.Rest(quarterLength=float(ts.barDuration.quarterLength))
                m.insert(0, r)
                part.append(m)
                continue

            tokens = expand_pattern_repetitions(tokenize_bar_content(content))

            offset = 0.0
            last_pitched = None

            for token in tokens:
                ev = parse_event_token(token)

                if ev.kind == "dynamic":
                    try:
                        m.insert(offset, m21dynamics.Dynamic(ev.dynamic_value))
                    except Exception:
                        pass
                    continue

                if ev.kind == "hairpin_start":
                    if ev.dynamic_value == "cresc":
                        open_cresc[abbr].append(m21dynamics.Crescendo())
                    else:
                        open_decresc[abbr].append(m21dynamics.Diminuendo())
                    continue

                if ev.kind == "hairpin_end":
                    if last_pitched is not None:
                        if open_cresc[abbr]:
                            sp = open_cresc[abbr].pop(0)
                            sp.addSpannedElements([last_pitched])
                            pending_hairpins.append(sp)
                        elif open_decresc[abbr]:
                            sp = open_decresc[abbr].pop(0)
                            sp.addSpannedElements([last_pitched])
                            pending_hairpins.append(sp)
                    continue

                if ev.kind in ("tacet", "unknown"):
                    continue

                if ev.kind in ("note", "chord", "rest"):
                    built = []
                    for i_dc, dc in enumerate(ev.duration_codes):
                        d = parse_duration_code(dc)
                        if d is None:
                            continue
                        if ev.kind == "rest":
                            n = note.Rest()
                            n.duration = d
                        elif ev.kind == "note":
                            n = note.Note(ev.pitches[0])
                            n.duration = d
                        else:
                            n = chord.Chord(ev.pitches)
                            n.duration = d
                        if i_dc == 0:
                            for a in ev.articulations:
                                n.articulations.append(a)
                            for e in ev.expressions:
                                n.expressions.append(e)
                        if ev.kind in ("note", "chord") and len(ev.duration_codes) > 1:
                            if i_dc == 0:
                                n.tie = m21tie.Tie("start")
                            elif i_dc == len(ev.duration_codes) - 1:
                                n.tie = m21tie.Tie("stop")
                            else:
                                n.tie = m21tie.Tie("continue")
                        m.insert(offset, n)
                        built.append(n)
                        offset += float(d.quarterLength)

                    if built and ev.kind in ("note", "chord"):
                        for sp in open_cresc[abbr]:
                            if sp.getFirst() is None:
                                sp.addSpannedElements([built[0]])
                        for sp in open_decresc[abbr]:
                            if sp.getFirst() is None:
                                sp.addSpannedElements([built[0]])
                        # Slur lifecycle: open on slur_start, close on slur_end.
                        if ev.slur_start:
                            slur = m21spanner.Slur()
                            slur.addSpannedElements([built[0]])
                            open_slurs[abbr].append(slur)
                        if ev.slur_end and open_slurs[abbr]:
                            slur = open_slurs[abbr].pop()
                            slur.addSpannedElements([built[-1]])
                            pending_slurs.append(slur)
                        last_pitched = built[-1]

            part.append(m)

    # Insert parts into the score
    for _, part in parts_in_order:
        score.insert(0, part)

    # Attach spanners (hairpins, slurs) after parts are in place — spanners
    # need their elements to be reachable in the score hierarchy.
    for sp in pending_hairpins + pending_slurs:
        try:
            score.insert(0, sp)
        except Exception:
            pass

    return score


# Output entrypoint ----------------------------------------------------------

def score_to_musicxml_bytes(score) -> bytes:
    """Render a music21 Score to MusicXML bytes."""
    from music21.musicxml.m21ToXml import GeneralObjectExporter
    exporter = GeneralObjectExporter(score)
    return exporter.parse()


def main_reverse(args) -> int:
    """MUS → MusicXML/MIDI. Reads a .mus file; emits to stdout (MusicXML)
    or to a target file (extension picks MusicXML/.mxl/MIDI)."""
    text = Path(args.input_path).read_text()
    parsed = parse_mus(text)
    score = build_score(parsed)

    if args.output:
        out_path = Path(args.output)
        suffix = out_path.suffix.lower()
        if suffix in (".mid", ".midi"):
            score.write("midi", fp=str(out_path))
        elif suffix == ".mxl":
            score.write("mxl", fp=str(out_path))
        else:
            score.write("musicxml", fp=str(out_path))
        print(f"Wrote {out_path}", file=sys.stderr)
    else:
        xml_bytes = score_to_musicxml_bytes(score)
        sys.stdout.write(xml_bytes.decode("utf-8"))
    return 0


# Main dispatcher ------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "MUS converter (bidirectional). Auto-detects direction from "
            "input extension: .mid/.musicxml/.xml/.mxl → MUS; .mus → MusicXML."
        )
    )
    ap.add_argument("input_path", help="Path to input file")
    ap.add_argument("--title", help="Override title (forward direction only)")
    ap.add_argument(
        "-o", "--output",
        help=(
            "Output file (reverse direction). Extension picks format: "
            ".musicxml/.xml writes XML; .mxl writes compressed; .mid writes MIDI. "
            "If omitted, writes MusicXML to stdout."
        ),
    )
    ap.add_argument(
        "--from-mus",
        action="store_true",
        help="Force MUS → MusicXML even if extension is non-.mus.",
    )
    args = ap.parse_args()

    suffix = Path(args.input_path).suffix.lower()
    if args.from_mus or suffix == ".mus":
        return main_reverse(args)
    return main_forward(args)


if __name__ == "__main__":
    sys.exit(main())
