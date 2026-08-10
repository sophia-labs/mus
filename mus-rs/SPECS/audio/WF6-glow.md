# WF6 — the glow chain and event-level treatments (`mus-dsp/src/glow.rs`)

New module: add `pub mod glow;` to `mus-dsp/src/lib.rs` (that one line is
your only edit outside your own files). Depends on WF4 (`vocode`), WF3
(`sweep_filter`), WF2 (`bitcrush`).

1. **`glow_chain(x, st_g, params, slot_samples) -> Vec<f32>`** — port
   `mus_audio.glow_chain` (a top-level function; the render call site
   guards `len(x) >= 2048`, keep that guard at the call site, not here):
   - **hold** (`ghold` not in {"0","off"}): 70 ms window; moving-average
     energy via `np.convolve(|x|, ones(win)/win, mode="valid")` (length
     `len-win+1`); loudest window start = argmax; 15 ms raised edges on a
     rectangular window; overlap-add the piece every `win - f` samples
     into `n_out + win`, truncate to `n_out = max(slot_samples, win)`.
   - **warble** (`gwarble` = rate Hz): square-LFO crossfade between x and
     `vocode(x, 1.0)` — `lfo = ((t*rate) % 1) < 0.5` picks dry.
   - **harmonizer** (`gharm`, default "0", `|`→`+`, parse floats,
     ValueError → [0.0]): per interval `layer = vocode(x, st_g + iv)`,
     layer 0 replaced by `0.6·voc(st_g+iv) + 0.2·voc(+0.15) +
     0.2·voc(-0.15)`; accumulate with weights 0.85^j into `len(x)`;
     `/ sqrt(len(ivs))`.
   - **coating**: `sweep_filter(y, 600, 600, "high")`, `(7800, 7800,
     "low")`, `bitcrush(bits=10)`, `tanh(y*2.4)/tanh(2.4)`.
   - **pump** (`pump` = rate Hz > 0): `y *= 0.45 + 0.55·exp(-3.5·((t·rate)
     % 1))`.
   Params arrive as a string map (WF8 feeds event params); accept
   `&BTreeMap<String, String>` plus explicit `st_g`/`slot_samples`.
   Fixtures: `glow_full_chain`, `glow_hold_pump` (`rel_rms 5e-3` —
   vocode-tier because vocode runs inside).

2. **`haas(right: &mut Vec<f32>, ms: f64)`** — the width treatment from
   the render path: delay R by `d = int(ms*SR/1000)` samples (prepend
   zeros, truncate) only when `0 < d < len`. Unit-test structurally
   (impulse position shifts; d=0 and d≥len are no-ops).

3. **`event_envelope(x: &mut [f32], atk_s, rel_s)`** — the note-shaping
   envelope from the render path: `atk = int(max(0.0015, atk_s)*SR)`,
   `rel = int(max(0.004, rel_s)*SR)`, clamped to `len/3` and `len/2`;
   attack ramp `linspace(0,1)^0.7`, release `linspace(1,0)^1.5`, each only
   when the clamped count > 1. Unit-test: monotone ramps, correct
   lengths, and the small-buffer clamps.

**Tests:** golden for the two glow fixtures; structural unit tests for
`haas` and `event_envelope`; a `gharm` parse test ("0+4+7+12", "0|12",
garbage → [0.0]).

**DoD:** builds; `cargo test -p mus-dsp` green; fmt clean; tests in diff.
