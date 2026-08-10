# Return note — sprint 1 results, and a proposal: the room is the same network

**To:** the mathematician who sent us Ariadne.
**From:** the implementation agent (Claude, in-codebase) and Vera.
**Branch:** `agent/weave-string-network`, through `6ce824d`. The formal
account is `.string-research/SPRINT-1-REPORT.md`; this note is the
narrative, the numbers that matter, and what we want from round 2.

---

## 1. What we implemented, and how it went

Everything in your P0 sequence landed the same day the handoff arrived.
The short version: **your design survived contact with the compiler,
the invariant suite, the render pipeline, and measurement, with one
model fix and one honest narrowing.** Recommendation was merge; it is
effectively merged — the branch now carries eight commits of
implementation on top of your eight of research.

**Assembly and compilation.** `assemble.sh --apply` validated cleanly.
The 1,181-line payload compiled on the first `cargo check` with a
single dead-field warning. Ten of eleven invariant tests passed on the
first run. For DSP drafted without a compiler we want you to know this
was remarkable, and it materially changed how much of the day went to
science instead of syntax.

**The one failure was real, and the fix is a deviation you should
review.** `stiff_string_spreads_upper_partials` failed with
`ratio 1.000000` on both sides — your dispersion mapping
`a = −0.72·stiff^0.75` produces only **+0.16 cents** of 5th-partial
sharpening at stiff=0.75, 110 Hz (we computed the allpass phase delays
exactly: the pole never gets close enough to 1 for a first-order pair
to develop audible delay variation across the first partials). Physical
guitar inharmonicity at the 5th partial is 6–30 cents. We replaced the
mapping with `a = −0.93·stiff^0.35`: measured ~0.03 c at the 0.08
default, ~4.6 c at 0.75, ~44 c at 1.0 (110 Hz; roughly ×6 at 220 Hz).
Tuning stays exact at the fundamental via your own phase-budget
compensation, and your budget-shrink loop protects short high-note
loops unchanged. No test tolerance was touched.

**Other deviations, all per your own contract's instructions:** `detune`
unified at the registry's 0..100 cents (your option 1); `body` default
held at the public 0.25 pending the listening decision (your §2 note);
the never-read `active` field removed. Dispatch, `SYNTH_KEYS`, the
typed vocabulary (chirality as a signed ratio, `dimension` documented
as scaffold), and the CLI dump tests all landed as specified. Both your
demo scores parsed and round-tripped through our parser **unmodified**
— they are corpus scores now, exercised by every test run.

## 2. The measurements

- **Tuning:** E2–E6 settled estimates within 8 cents everywhere
  (autocorrelation + parabolic refinement).
- **T60 honesty (raw voice output, Goertzel at the fundamental,
  damp=0):** requested 0.5/1/2/4 s measured −53.0/−56.5/−58.3/−59.2 dB
  at t=sus — converging on −60, residual consistent with the 100 ms
  windows. **Your §7 compensation works exactly:** at damp=0.35,
  sus=2, the fundamental decays −30.0 dB in 1 s — precisely the
  promised 60·t/T60 slope — while h2/h3/h5 run −30.3/−31.0/−33.4.
  (Caveat we hit: full-engine renders pass a master limiter, so
  end-to-end decay measurements understate the string; all numbers
  above are raw.)
- **Path memory:** chirality +0.92 vs −0.92, identical patch,
  five-note chord: **relative RMS distance 0.713** with loudness within
  0.7 dB and spectral centroid within 1.4 %. Traversal order is
  first-class and audible, and it is not a level or EQ artifact. Your
  closed-form defect matches the basis-vector Frobenius computation to
  <1e-13.
- **Spectral-dimension scaffold:** sustained-segment peak lattices are
  measurably distinct per `d` (d=1.35 shows 1.67/2.31 among the
  harmonics; d=2.6 compresses to 2.00/2.12/2.61/2.87; d=1.0 collapses
  toward 1.97/2.03/3.00). The 98 Hz body mode appears in every lattice,
  as it should.
- **Your predicted passivity gap, demonstrated with numbers.** We added
  a bend probe to the boundedness test: the extreme weave patch peaks
  **3.24 unbent and 5.38 during an upward-fifth bend** — a ~0.3 s
  energy transient (+66 %) that then decays monotonically to silence.
  This is your issue A / §3 "time-varying propagation is not an
  isometry," measured. We took your option 3: the claim is narrowed in
  writing to *scattering lossless; modulated system empirically bounded
  over the tested control domain*, and the test bound (8.0) carries the
  measurement and the reasoning in a comment. This is ask #1 below.
- **Nothing regressed:** the 13-score oracle parity corpus is
  byte-for-byte at its pre-Ariadne worst case (rel_rms 1.847e-4,
  motet). Workspace: 216 tests green across 32 suites; clippy
  `-D warnings` clean.

## 3. What we built on top of it, same day

You should know what your instrument did within hours of compiling,
because it says something about the design's reach:

- **The Weave Observatory** — a standalone app whose interface is the
  network's literal topology: courses as a ring (played gold, virtual
  violet, labeled with their actual lattice pitches), edges glowing
  with the applied |Givens angle| per pass, the orbit field as a comet
  at its true phase — all drawn from a `render_traced()` telemetry tap
  we added (byte-identical audio, tested). **Your δ(a,b) is now a
  musician-facing gauge:** a parallelogram whose sides are the two
  adjacent coupling angles and whose area is the defect — "how much
  does order matter right now," live, at a glance. The small-angle law
  δ ≈ |ab| is what makes that visualization *exact* rather than
  metaphorical, which we find genuinely delightful.
- **A composed piece.** *Romanza del hilo* (E minor, 3/4, 28 bars):
  three hands of one weave guitar in the low-couple limit; a middle
  section where the lattice wakes by event-level couple/orbit/curvature
  rises; an A′ section played on **mirrored-chirality instrument
  declarations** — the same phrase traversed in the opposite order, as
  a compositional device; and a coda of exact midpoint plucks whose
  even harmonics vanish by nodal geometry. Path memory as musical
  rhyme. It renders clean and it is corpus score #17.

## 4. The proposal: the instrument and the room are one network

Here is the direction we want to point round 2 at, and we believe it is
*your* direction seen from one step further back.

Every arrow in our current signal chain points outward: string →
body → out → send → reverb, nothing flows back. The body inside Weave
is already coupled bidirectionally (your rotors), but the *space* the
instrument sounds in is still a one-shot convolution that never hears
itself. The observation: once arrows go both ways, **"instrument" and
"room" stop being different kinds of thing.** Strings are short delay
cycles (audio-rate pitches); rooms are long delay cycles (10–300 ms);
bridges and walls are junctions. The distinction is topology, not
ontology — an instrument is a dense cluster, a room is a sparse halo,
and coupling is edges between them. **Your contractive holonomy network
is not adjacent to this idea; it already is this idea.** The Givens
junctions are exactly the passive scattering the coupled system needs,
and the Lean skeleton we landed (`network_silences`: preserving
junctions + a lossy edge ⇒ silence) is accidentally the safety theorem
for instrument-in-space.

What makes this musically explosive is that every law a physical room
obeys becomes a dial: **non-reciprocal rooms** (directed cycles —
echoes that only circulate one way); **curved space you can hear**
(holonomy on the room's cycles: every bounce applies a rotation, so
echo generations drift along your fractional ladder — reverb as a
comma pump, the room extending the instrument's own inharmonicity —
this is where your braids and the space fuse into one object); **a room
in a key** (long cycles tuned to a chord; the space ignites for its
tonality); **dispersion walls** (allpass chains per bounce — chirp-fog
late reverb); **pre-verb** (we render offline and deterministically, so
an anticausal reversed-room pass coupled back is *legal* for us);
**rooms that respond** (amplitude-dependent wall loss — declared,
bounded, invariant-tested nonlinearity).

Two engineering facts make us the right lab for this mathematics: we
have no real-time deadline, so we can **iterate the coupled system to
convergence per block** instead of dodging delay-free loops; and our
renders are deterministic, so *spaces are A/B-able* — same phrase,
possible room versus impossible room, as comparable takes. A Rust port
of our spatial-scene renderer (listener, trajectories, FOA) is landing
in parallel, which gives the halo its spatialization layer for free.

## 5. What we ask of round 2

Each ask names what we will do with the answer. We supply probes and
acceptance criteria; you supply conditions and constructions.

1. **Passive time-varying retuning** (your issue A, now measured).
   Give us an energy-compensated delay-modulation scheme (Virtual
   Slide Guitar lineage) or a passive state transformation in a
   declared weighted norm. Acceptance: our bend probe's peak stays
   within a declared ε of the unbent peak across the control domain;
   the probe is in `pluck_invariants.rs` and currently reads
   3.24 → 5.38 over an upward fifth.
2. **Two-timescale contraction.** Extend your state-space model to a
   graph with a dense cluster (delays ~SR/f₀) and a sparse halo
   (delays 10–300 ms) joined by junction edges. Conditions on angles
   and losses so the contraction theorem covers the union. We suspect
   your existing skeleton nearly does; we want the statement and its
   hypotheses written down.
3. **Holonomy across timescales.** With rotations on the halo's
   cycles, the path-ordered product W[γ] now interleaves string
   scattering with bounce operators. What is the composed ladder? In
   particular: a fixed per-bounce rotation should make successive echo
   generations drift by a fixed interval — derive the drift law, and
   its interaction with the instrument's own fractional ladder, so
   "comma-pump reverb" has a formula before it has a preset.
4. **Non-reciprocity with passivity.** Directed scattering on the halo
   that remains norm-preserving/contractive: conditions and a
   construction. When does a gyre stay stable? (We will refuse
   non-reciprocal patches that fail the condition, so make the
   condition checkable.)
5. **Weighted energy metric** (your issue B, inherited). The
   M-orthogonal recipe applied concretely to string + body + room
   coordinates of different impedance — or a principled license for
   unit normalization at declared interfaces.
6. **Inverse design.** Given a target lattice or drift spec ("a room
   in E minor whose echoes fall 21.5 cents per bounce"), solve for
   angles and topology. Even a local-linearization answer makes the
   room-in-a-key a compiler target instead of a knob hunt.
7. **E15, properly.** We will build the within-note control-automation
   seam next (it is also what the Braid view and the plugin need).
   Specify the cleanest cyclic protocol A,B,−A,−B and the invariant
   observable per your §6 conditions 1–5, so the closed-loop
   demonstration overclaims nothing when we run it.

By the time you answer we expect to have: the automation seam, the
scene-renderer port, listening verdicts on the guitar A/B (human ears
are scheduled), and the Lean formalization of your defect identity
(`‖U−V‖₂ = ‖U−V‖_F/√2` on SO(3)) on our pure-core bench.

## 6. Closing

The thread remembers the labyrinth; we checked. What we are proposing
now is to let the labyrinth be weather — one network whose dense corner
is the instrument, wrapped in a room that couldn't exist. Your move.
