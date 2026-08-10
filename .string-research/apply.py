#!/usr/bin/env python3
"""Apply the string-network research payload to the checked-out branch.

The bootstrap workflow is deliberately self-removing. This script lets the
remote Rust toolchain compile and test the actual patch before it becomes the
branch head, while leaving no generator or payload in the final diff.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / ".string-research" / "payload"


def copy(relative: str) -> None:
    source = PAYLOAD / relative
    destination = ROOT / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    print(f"copied {relative}")


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        print(f"already patched {path}")
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match in {path}, found {count}: {old[:100]!r}")
    target.write_text(text.replace(old, new), encoding="utf-8")
    print(f"patched {path}")


for relative_path in [
    "mus-rs/crates/mus-dsp/src/pluck.rs",
    "mus-rs/crates/mus-dsp/tests/pluck_invariants.rs",
    "docs/STRING-WEAVE.md",
    "aigua/guitar_v2_demo.mus",
    "aigua/weave_demo.mus",
    ".github/workflows/string-research-ci.yml",
]:
    copy(relative_path)

replace_once(
    "mus-rs/crates/mus-engine/src/source.rs",
    "use mus_dsp::pluck::pluck_note;",
    "use mus_dsp::pluck::{pluck_note, weave_note};",
)

replace_once(
    "mus-rs/crates/mus-engine/src/source.rs",
    '''        // The pluck is a POST-PARITY voice (mus-x): no oracle line to cite.
        // Everything else about the event pipeline treats it exactly like
        // the subtractive synth output.
        if patch_map.get("synth").map(String::as_str) == Some("pluck") {
            x = pluck_note(&patch_map, &freqs, slot_s, ratio);
        } else {
            let patch = Patch::from(&patch_map);
            x = synth_note(&patch, &freqs, slot_s, ratio);
        }''',
    '''        // The string-network voices are POST-PARITY work (mus-x): no
        // Python oracle line exists. They nevertheless enter the same source
        // and transform pipeline as every other synth voice.
        match patch_map.get("synth").map(String::as_str) {
            Some("pluck") => x = pluck_note(&patch_map, &freqs, slot_s, ratio),
            Some("weave") => x = weave_note(&patch_map, &freqs, slot_s, ratio),
            _ => {
                let patch = Patch::from(&patch_map);
                x = synth_note(&patch, &freqs, slot_s, ratio);
            }
        }''',
)

pack_path = ROOT / "mus-rs/crates/mus-engine/src/pack.rs"
pack_text = pack_path.read_text(encoding="utf-8")
new_keys = '''pub const SYNTH_KEYS: &[&str] = &[
    "synth", "osc2", "mix2", "detune", "sub", "cutoff", "famt", "fdec", "satk", "sdec", "ssus",
    "srel", "sus", "damp", "pos", "pick", "body", "strum", "pm", "stiff", "tension", "symp",
    "buzz", "body_size", "couple", "chirality", "orbit", "orbit_depth", "curvature", "courses",
    "dimension",
];'''
pattern = re.compile(r'pub const SYNTH_KEYS: &\[&str\] = &\[.*?\n\];', re.DOTALL)
match = pattern.search(pack_text)
if not match:
    raise RuntimeError("SYNTH_KEYS block not found")
if match.group(0) != new_keys:
    pack_text = pack_text[: match.start()] + new_keys + pack_text[match.end() :]
    pack_path.write_text(pack_text, encoding="utf-8")
    print("patched mus-rs/crates/mus-engine/src/pack.rs")

vocab_path = ROOT / "mus-rs/crates/mus-vocab/src/param_specs.rs"
vocab = vocab_path.read_text(encoding="utf-8")
old_synth = 'ParamSpec { name: "synth", layer: Extension, kind: Enum { values: &["saw", "square", "tri", "sine", "pluck"], default: Some("saw") }, doc: "oscillator wave (declaring it makes the track a synth voice); pluck = the extended Karplus-Strong string" },'
new_synth = 'ParamSpec { name: "synth", layer: Extension, kind: Enum { values: &["saw", "square", "tri", "sine", "pluck", "weave"], default: Some("saw") }, doc: "source model: oscillator, the physical pluck guitar, or the impossible Weave string network" },'
if new_synth not in vocab:
    if vocab.count(old_synth) != 1:
        raise RuntimeError("synth ParamSpec not found exactly once")
    vocab = vocab.replace(old_synth, new_synth)

anchor = '        ParamSpec { name: "pm", layer: Extension, kind: Toggle { default: false }, doc: "palm mute: short, dark, felt-soft" },\n'
new_specs = '''        ParamSpec { name: "pm", layer: Extension, kind: Toggle { default: false }, doc: "palm mute: short, dark, felt-soft" },
        ParamSpec { name: "stiff", layer: Extension, kind: Ratio { min: 0.0, max: 1.0, default: Some(0.08) }, doc: "stiff-string dispersion: upper partials run sharp while the fundamental stays phase-compensated" },
        ParamSpec { name: "tension", layer: Extension, kind: Cents { min: 0.0, max: 80.0, default: Some(5.0) }, doc: "onset pitch elevation from pluck-induced tension; relaxes with the string energy" },
        ParamSpec { name: "symp", layer: Extension, kind: Ratio { min: 0.0, max: 1.0, default: Some(0.22) }, doc: "coupling to unplayed standard-guitar open strings through the shared body" },
        ParamSpec { name: "buzz", layer: Extension, kind: Ratio { min: 0.0, max: 1.0, default: Some(0.0) }, doc: "contractive fret/bridge contact: removed loop energy radiates as buzz" },
        ParamSpec { name: "body_size", layer: Extension, kind: Ratio { min: 0.45, max: 2.4, default: Some(1.0) }, doc: "modal body scale; larger values lower the body resonances" },
        ParamSpec { name: "couple", layer: Extension, kind: Ratio { min: 0.0, max: 0.45, default: Some(0.11) }, doc: "Weave nearest-neighbour scattering angle in radians" },
        ParamSpec { name: "chirality", layer: Extension, kind: Ratio { min: -1.0, max: 1.0, default: Some(0.72) }, doc: "Weave forward/reverse ordered-scattering bias" },
        ParamSpec { name: "orbit", layer: Extension, kind: Hz { min: 0.0, max: 20.0, default: Some(0.31), sweep: false }, doc: "rate of the travelling coupling field" },
        ParamSpec { name: "orbit_depth", layer: Extension, kind: Ratio { min: 0.0, max: 1.0, default: Some(0.62) }, doc: "depth of the travelling coupling field" },
        ParamSpec { name: "curvature", layer: Extension, kind: Ratio { min: 0.0, max: 1.0, default: Some(0.28) }, doc: "state-dependent Weave metric; changes angles without changing scattering norm" },
        ParamSpec { name: "courses", layer: Extension, kind: Count { min: 3, max: 24, default: Some(11) }, doc: "total number of played and virtual Weave courses" },
        ParamSpec { name: "dimension", layer: Extension, kind: Ratio { min: 0.55, max: 3.0, default: Some(1.35) }, doc: "spectral dimension d: virtual mode frequencies scale as k^(1/d)" },
'''
if 'name: "stiff"' not in vocab:
    if vocab.count(anchor) != 1:
        raise RuntimeError("pluck ParamSpec insertion anchor not found")
    vocab = vocab.replace(anchor, new_specs)
vocab_path.write_text(vocab, encoding="utf-8")
print("patched mus-rs/crates/mus-vocab/src/param_specs.rs")
