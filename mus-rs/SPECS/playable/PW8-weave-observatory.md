# PW8 — the Weave Observatory (DRAFT for Vera's reaction)

A standalone Shrubbery/Atril face that is a control-and-visualization
surface for `synth=weave`. Status: **PW8a landed** (render_traced +
service vocab/renderWeaveProbe, this repo) and **the app v1 shipped**
(shrubbery `apps/observatory`, feat/atril): Ring + Defect Gauge +
vocab-driven controls + string bar, verified live. PW8c (Braid,
trajectory record/replay) still waits on the within-note automation
seam below.

## The idea in one sentence

Weave's topology is a ring of courses with ordered nearest-neighbour
coupling — so the interface should *be that ring*, with every control a
gesture on the picture and every picture element backed by real engine
state, never a decorative reconstruction.

## Why this instrument earns its own surface

The Playable Graph's Stack face (PW5) renders any voice's typed params as
vocab-derived controls — sliders in a column. That is correct and
sufficient for `cutoff`. It is structurally wrong for Weave, because
Weave's seven controls are not independent scalars: they are one
geometry. `couple` is edge strength, `chirality` is flow direction,
`orbit`/`orbit_depth` are a travelling wave on the edges, `curvature`
bends angles toward energy, `courses`/`dimension` populate the ring.
A column of sliders hides exactly the thing the instrument is about —
that these controls compose into a *path*, and the path is audible
(measured: rel RMS 0.713 between traversal orders at equal loudness).

## The surface

**1. The Ring.** N course-nodes on a circle (the literal network
topology). Played courses filled, virtual courses hollow, radius ∝ live
per-course energy, hue by pitch class. Coupling edges between neighbours
glow with the instantaneous angle; the orbit field is *visible* as a
brightness wave circulating at `orbit` Hz. Chirality is particle-flow
direction along the edges. Curvature displaces nodes toward the energy
gradient. Nothing invented: every visual quantity maps to a value the
engine actually computes (`energy_smooth`, the per-edge clamped angle,
the travelling factor).

**2. The Braid.** Time along one axis, courses across the other; the
scatter history drawn as thread crossings — a render literally shows its
weave. Two renders with opposite chirality sit as mirrored braids;
**hold-to-hear the diff** (the Takes gesture, inherited). This is the
path-memory demonstration as a first-class UI object.

**3. The Defect Gauge.** A small parallelogram between two adjacent
edges whose *area* is the live `weave_holonomy_defect(a,b)` — exact for
the reason the mathematics packet proves (small-angle δ ≈ |ab| = the
area). The gauge answers, at a glance: "how much does order matter right
now?" Zero when either coupling sleeps; growing as gestures overlap.

**4. Rooms and paths.** The three presets (thread / labyrinth / extreme)
are *places*; the current patch is a *position*; moving between rooms is
a *path* — and the surface records control **trajectories**, not just
endpoints, because in this instrument two roads to the same knob values
sound different (§12's audibility functional made tangible). A recorded
trajectory can be replayed onto a note, which is also exactly the
missing E15 experiment surface.

**5. Laws inherited from the Playable Graph:** everything hearable
(every gesture auditions through the warm service), everything
attributed, refusal visible (an out-of-range control shows the typed
refusal, never a silent clamp), one-body flip, keyboard-first.

## What exists vs what must be built

Already on the shelf (Shrubbery `feat/atril` + mus service):
- typed controls from the `mus vocab` dump (the Stack's mechanism —
  chirality arrives as a signed ratio, courses as a count, all landed);
- `MusRenderServiceClient` + `AuditionEngine` (render/press/release,
  4 ms ramps), `RenderRecord.pcmUrl`, room pool, presence.

To build, mus side (small, honest):
- **PW8a — trace API**: `renderEventTraced` on the service returning,
  besides PCM, a downsampled per-course telemetry block (per ~256
  samples: each course's `energy_smooth`, the per-edge effective angle,
  orbit phase). Engine-side this is a `render_traced()` variant of
  `StringNetworkVoice` filling a preallocated trace buffer — no change
  to the audio path, tested byte-identical to `render()`.

To build, shrubbery side:
- **PW8b — the face**: `mus-weave-face` (Ring + Defect Gauge, SVG,
  no new deps), controls bound to the vocab dump, auditions via the
  existing engine; **PW8c — the Braid + trajectory recorder** (canvas),
  including replay-onto-note once the automation seam exists.

## The honest dependency

The Braid's replay and E15 both want **within-note control automation**
— today params are per-event. That is the same engine seam the plugin
wrapper needs (design doc §8), and it should be designed once, as its
own keystone, not improvised inside a face. PW8a/b are buildable now;
PW8c's replay half waits on that seam.
