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
import argparse
import xml.etree.ElementTree as ET
import zipfile
from fractions import Fraction
from pathlib import Path
from music21 import converter, stream, note, chord, meter, key, tempo as m21tempo
from music21 import dynamics as m21dynamics, expressions as m21expressions
from music21 import spanner as m21spanner


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
    """Convert music21 Pitch → MUS pitch string. C4 = middle C."""
    name = pitch.name.replace("-", "b")  # music21 uses '-' for flat
    octave = pitch.octave if pitch.octave is not None else 4
    return f"{name}{octave}"


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


def main() -> int:
    ap = argparse.ArgumentParser(description="Convert MIDI to MUS v0.1.1")
    ap.add_argument("midi_path", help="Path to a .mid file")
    ap.add_argument("--title", help="Override title (else inferred from metadata or filename)")
    args = ap.parse_args()

    score = converter.parse(args.midi_path)

    # Title resolution order:
    #   1. Explicit --title flag
    #   2. <credit-words> with <credit-type>title</credit-type>  (Musescore's page title)
    #   3. score.metadata.title  (the <work-title> field — Musescore leaves this as boilerplate)
    #   4. Filename stem
    title = args.title
    if not title:
        title = read_credit_title(args.midi_path)
    if not title:
        if score.metadata and score.metadata.title:
            mt = score.metadata.title.strip()
            if mt and mt.lower() != "untitled score":
                title = mt
    if not title:
        title = Path(args.midi_path).stem

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


if __name__ == "__main__":
    sys.exit(main())
