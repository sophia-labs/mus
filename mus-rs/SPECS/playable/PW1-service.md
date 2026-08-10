# PW1 — service completion: windows, events, diffs, peaks, GC

Extend `crates/mus-cli/src/service.rs` (keystone: protocol v0) into the
full audition engine behind Atril's probe. Everything below is governed by
the window-exactness law in `SPECS/playable/README.md`.

## 1. The extent table (the enabler — build first)

`renderScore` currently memoizes only the mixed PCM. Extend the engine
path so a full render also produces, per placed event, its **placement
extent**: `{eventIndex, track, onsetSeconds, startFrame, endFrame}` where
`[startFrame, endFrame)` bounds every nonzero sample that event
contributed to the dry+wet buses (endFrame includes the reverb tail its
send produced: conservatively, `event dry extent + IR length` when
`send > 0`, exact dry extent when `send == 0`). This likely means a
surgical extension of `mus-engine`'s mix path to record extents while
placing (`mixbus.rs`/`lib.rs`) behind a flag or always-on (they are
cheap). Cache the table in the service's `RenderedEntry`.

Also cache the **master trajectory**: `master()` applies (a) an RMS
pre-gain scalar, (b) a smoothed limiter gain curve (a full-length f32
vector), (c) `tanh` shaping, (d) a final trim scalar. For window
exactness the window path must reuse the full render's exact gain curve
slice — store the pre-gain scalar, the post-smoothing limiter curve, and
the final trim scalar in `RenderedEntry` (one f32 vec + two scalars; the
tanh is memoryless). The final output high-pass (`highpass28`) carries
filter state across the whole piece — for windows, either (a) slice the
FULL rendered output (the trivially-exact path: the full mix is already
memoized — a window is then literally `full[a..b)` copied out) or (b)
re-run the chain windowed with carried state. **(a) is the mandated v1
implementation**: `renderWindow` slices the memoized full render. The
extent table still matters — it powers `soloEventIds`/`tracks` filtered
windows, which DO re-render (see §2).

## 2. Methods to add

- **`renderWindow {docKey, startSeconds, endSeconds, tracks?, soloEventIds?}`**
  - No filter → slice the memoized full render (bit-exact by
    construction). Response shape = `renderScore`'s plus
    `{startSeconds, endSeconds, sliceOfFull: true}`.
  - With `tracks` (array of track abbrevs) or `soloEventIds` (array of
    event indices as the check report numbers them) → a **filtered
    render**: re-run the render including only the selected events
    (using the extent table to skip everything not intersecting
    `[start, end)`), apply the CACHED master pre-gain/limiter-slice/trim
    from the full render (so a solo sits at in-mix loudness — the
    interaction grammar's "probe hears in context" rule), slice, return
    with `sliceOfFull: false`. Filtered renders are memoized under
    `(docKey, filterKey)`.
- **`renderEvent {docKey, eventIndex, contextTail?: seconds=0.5}`** —
  sugar over the filtered path: solo that event from its onset to its
  extent end + tail, at in-mix loudness. Returns the same PCM envelope
  plus `{onsetSeconds, extentSeconds}`.
- **`renderDiff {docKey, altSource}`** — load+render the alternative
  source (same baseDir), return BOTH: `{a: <renderScore result>, b:
  <renderScore result>, firstDivergenceFrame: number|null}` where
  `firstDivergenceFrame` is the first frame where the two full renders
  differ (null when byte-identical). This powers hold-to-hear A/B.
- **`peaks {docKey, buckets, startSeconds?, endSeconds?}`** — min/max
  per bucket over the full render's mono fold (`max(|L|,|R|)` per
  frame), returned inline as two f32 arrays (JSON numbers are fine at
  ≤4096 buckets; reject larger with `bad-request`). Powers waveform
  strips.
- **`stats {}`** — cache inventory: loaded docs, rendered entries,
  tmpdir bytes. For the GC test and for ops eyes.

## 3. GC discipline

The service tmpdir must not grow unboundedly under an editing session
(every keystroke is a new docKey). LRU by last-touch over rendered
entries: default budget 1 GiB or 64 entries, whichever trips first;
evict = delete the `.f32` and drop the entry (extent tables and master
curves go with it). Loaded docs (sources) are small — cap at 256,
LRU-evict. Budgets overridable via env
(`MUS_SERVICE_PCM_BUDGET_BYTES`, `MUS_SERVICE_MAX_RENDERS`).

## 4. Tests (the stage ships them in the same diff)

Extend `tests/service_smoke.rs` or add `tests/service_windows.rs`:
1. **The crown jewel**: render `aigua/aigua_states.mus` fully; request
   three windows (start, middle spanning a bar line, tail including the
   final reverb decay); assert each window's bytes equal the full
   render's slice EXACTLY (read both files, memcmp the ranges).
2. Filtered window: solo one track of `smoke.mus`; assert (a) response
   `sliceOfFull: false`, (b) determinism (same request twice → same
   digest), (c) the solo is NOT byte-equal to the full slice (it must
   actually filter).
3. `renderEvent` on a known event: extent sanity (extent ≥ slot,
   includes tail when send > 0).
4. `renderDiff` on smoke.mus vs smoke.mus with one pitch changed:
   `firstDivergenceFrame` is not null and is ≥ the changed event's
   `startFrame` per the extent table; diff of identical sources →
   `firstDivergenceFrame: null`.
5. `peaks`: bucket count honored; values within [-1, 1]; deterministic.
6. GC: set tiny budgets via env in a spawned service; load+render N+2
   variants; assert `stats` shows eviction and the evicted `.f32` is
   gone from disk.

## DoD

Workspace builds; all mus-cli tests green (including the untouched
render/check/parity suites); `cargo fmt --check` clean; tests in the
diff; any construct where window exactness could not be met reported
with measured divergence, not hidden.
