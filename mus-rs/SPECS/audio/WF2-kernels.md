# WF2 — remaining pure kernels (`mus-dsp/src/kernels.rs`)

Port the rest of the hand-rolled numpy kernels. Exemplars already in the
file (`ring_mod`, `soft_clip`, `hard_clip`) show the house pattern: doc
comment citing the Python function, f32 slices in/out, scalar math in f64
where numpy holds a float64 scalar. All cases are `max_abs` tier.

Functions to port from `mus_audio.py` (grep the name):

1. **`bitcrush(x, bits, decim)`** — amplitude quantise `round(x*(L/2))/(L/2)`
   with `L = max(2, 2^bits)`; decimation = sample-hold via `np.repeat` of
   `x[:n:d]` over `(len//d)*d` samples, tail beyond `n` appended unchanged,
   result truncated to `len(x)`. numpy `np.round` is banker's rounding
   (round-half-to-even) — use `f32::round_ties_even`. Signature:
   `bitcrush(x: &[f32], bits: Option<f64>, decim: Option<u32>) -> Vec<f32>`.
   Fixtures: `bitcrush_bits`, `bitcrush_decim`, `bitcrush_both`.
2. **`stutter(x, n, slot_samples)`** — retrigger: piece = first
   `max(64, slot/n)` samples, 4 ms linear fades both ends (`f =
   min(0.004*SR, len/4)`, only when `f > 1`), tiled n times. Fixture:
   `stutter_5`.
3. **`chop_shuffle(x, n_grains, slot_samples)`** — deterministic granular
   re-deal: clamp grains to [2,64], `seg = max(len/ n, 64)` (integer div),
   grains sliced `[i*seg:(i+1)*seg]` (the last may be short/empty — Python
   slicing never panics; mirror that), order = evens then odds, every 4th
   dealt grain (j%4==3) reversed, 4 ms fades per grain when `f > 1`,
   concatenated, truncated to `max(slot_samples, seg)` only if longer.
   Fixtures: `chop_shuffle_8`, `chop_shuffle_3_tight`.
4. **`duck_envelope(onsets_s, n, depth, release, hold)`** — gain curve 1.0;
   per onset: hard floor `1-depth` for `hold` samples, then recovery shape
   `1 - depth*exp(-t/(rel/4))` for `rel = max(release*SR, 32)` samples,
   combined with `min` so overlapping ducks deepen, never fight. Onset
   sample = `int(o*SR)` (truncation, not round). Fixture: `duck_envelope`
   (onsets in args as an array).
5. **`pan_stereo(x, p0, p1)`** — equal-power: `theta = (clip(p,-1,1)+1)*π/4`,
   L = x·cos, R = x·sin; constant when `|p0-p1| < 1e-6`, else linspace.
   Return `(Vec<f32>, Vec<f32>)`. Fixtures: `pan_static`, `pan_sweep`
   (expected stored planar: first L then R — split `expected` in half).
6. **`maximum_filter1d(x, size)`** — scipy.ndimage semantics: sliding max,
   window centered (origin 0: window spans `[i - size//2, i + (size-1)//2]`),
   **reflect** boundary (`(d c b a | a b c d | d c b a)`). Used by WF7's
   limiter. Fixture: `maximum_filter1d`.
7. **`np_hanning(m)`** — numpy `np.hanning`: symmetric Hann,
   `0.5 - 0.5*cos(2πk/(M-1))`, in f64. No fixture; unit-test endpoints = 0,
   midpoint = 1, and a couple of hand values; WF7's master fixture
   exercises it end-to-end.

**Tests:** one golden test per fixture case above, same shape as
`tests/golden_kernels.rs` (extend that file or add `golden_kernels2.rs`).
For `pan_stereo` check L and R against the two halves of `expected`.
Plus a slicing-edge unit test for `chop_shuffle` with `len(x)` not
divisible by grains.

**Definition of done:** workspace builds; `cargo test -p mus-dsp` green;
`cargo fmt` clean; diff contains your tests.
