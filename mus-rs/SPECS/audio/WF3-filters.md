# WF3 — scipy-parity IIR filters (`mus-dsp/src/filters.rs`)

The renderer uses exactly one filter design everywhere: Butterworth →
second-order sections, applied causally (`sosfilt`, not filtfilt), plus the
block-interpolated `sweep_filter`. Port these to `max_abs` parity — the
coefficient fixtures are f64 at 1e-10, so this must be the same math, not a
lookalike.

1. **`butter_sos(order, wn, btype) -> Vec<[f64; 6]>`** — port scipy's
   `butter(..., output="sos")` for `btype` in {low, high}. Read the actual
   implementation in `.venv/lib/python3.12/site-packages/scipy/signal/
   _filter_design.py` (`butter` → `iirfilter` → analog prototype `buttap`,
   frequency pre-warp `2*fs*tan(π*wn/fs)` with fs=2, `lp2lp_zpk`/`lp2hp_zpk`,
   `bilinear_zpk`, then `zpk2sos` with the default `pairing='nearest'`).
   The SOS **row order and pole pairing must match scipy exactly** — the
   fixtures `sos_butter4_low_1200`, `sos_butter4_high_300`,
   `sos_butter2_low_5200`, `sos_butter2_high_28` pin every coefficient
   (rows flattened, `[b0 b1 b2 a0 a1 a2]` per row). scipy is only called
   with these two btypes and orders 2/4; implement generally for order n
   but test the pinned four.
2. **`sosfilt(sos, x, zi) -> (y, zf)`** — direct-form II transposed per
   section, f64 state even for f32 signals (scipy computes in f64 when
   given f64 sos and f32 x? No — scipy upcasts: `sosfilt(f64_sos, f32_x)`
   returns f64; the oracle then casts to f32. Compute in f64, cast the
   output). Fixture: `sosfilt_low_noise` (zi = None → zero state).
3. **`sosfilt_zi(sos) -> Vec<[f64; 2]>`** — steady-state initial conditions,
   scipy `_signaltools.sosfilt_zi`: per-section `lfilter_zi` (solve
   `(I - A^T) zi = B`-style companion system) with the cumulative
   scale factor carried across sections. Fixture: `sosfilt_zi_low_1200`.
4. **`sweep_filter(x, f_start, f_end, btype)`** — port `mus_audio.
   sweep_filter` verbatim: clip to [20, 0.97·nyq]; static path when
   `|f_start-f_end| < 1` (fresh sosfilt, zero state); else 256-sample
   blocks, per-block cutoff = geometric interpolation at the block
   *midpoint* fraction `(s + (e-s)/2)/n`, fresh `butter_sos` per block,
   state: `zi = sosfilt_zi(sos) * x[0]` **built from the first block's
   sos** then carried across blocks (the sos changes under a fixed state —
   that is the Python behavior, keep it). Fixtures: `sweep_static_low`,
   `sweep_low_fall`, `sweep_high_rise`.

**Tests:** golden per fixture; plus one unit test that `sosfilt` with an
explicit zi equals scipy's carried-state behavior across a split signal
(filter halves with carried zf == filter whole).

**DoD:** builds; `cargo test -p mus-dsp` green; fmt clean; tests in diff.
