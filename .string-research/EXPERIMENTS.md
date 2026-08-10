# Ariadne experiment program

Ariadne succeeds only if three things are simultaneously true:

1. the conservative guitar is audibly better;
2. the impossible instrument has a repeatable capability that ordinary physical models do not expose;
3. the implementation remains bounded, reproducible, and usable in a real-time host.

This file turns those claims into stop conditions.

## 0. Artifact discipline

For every experiment, retain:

```text
score or event manifest
resolved patch JSON
source commit
engine version and vocabulary digest
sample rate and block schedule
WAV digest
analysis JSON
spectrogram
short human listening note
```

Suggested output tree:

```text
.string-research/results/<date>/<experiment>/<condition>/
  score.mus
  patch.json
  receipt.json
  render.wav
  analysis.json
  spectrogram.png
  notes.md
```

Do not commit large renders by default. Commit compact receipts, manifests, plots when useful, and instructions for regeneration.

## 1. Build and identity gate

### E0.1 — assembly integrity

After `assemble.sh --apply`:

- assembled `pluck.rs` begins with the expected module documentation;
- it exports `pluck_note`, `weave_note`, and `StringNetworkVoice`;
- assembled invariant file imports all three;
- no staging marker, duplicated boundary, or missing newline remains.

### E0.2 — compilation

```bash
cd mus-rs
cargo fmt --all -- --check
cargo check --workspace
cargo test -p mus-dsp --test pluck_invariants -- --nocapture
```

Record every initial test failure before changing a threshold. A failure may reveal a model bug, an estimator bug, or an invalid claim.

### E0.3 — deterministic identity

For each of ten patches and ten pitches:

- render twice offline;
- render through block schedules `[1]`, `[16]`, `[31,64,127]`, `[509,7,2048]`;
- require exact f32 equality unless the implementation explicitly adopts a weaker deterministic contract;
- change one semantic input at a time and require a different digest.

Inputs that must participate in content identity include pitch, duration, excitation controls, mode, and course index. Decide explicitly whether body/topology profile digest also participates.

## 2. Guitar baseline protocol

Before replacing the source file, render the old `aigua/pluck_demo.mus` and a new fixed test corpus from the base commit. Preserve those WAVs as the baseline.

The corpus should contain isolated notes and short phrases at:

```text
E2, A2, D3, G3, B3, E4
E4, B4, E5, E6
single note, octave, fifth, open E minor, close triad
finger, soft pick, hard pick
bridge, 1/5, 1/3, midpoint pluck
normal, palm mute, bend, detuned course
```

Match integrated loudness before preference listening; do not let “new is louder” win.

## 3. Isolated-string experiments

### E1 — settled tuning across the neck

Sweep:

```text
pitch: MIDI 40..88 in semitone steps
stiff: 0, 0.08, 0.25, 0.5, 0.75
variant: static, +2-semitone bend, -2-semitone bend
```

Measure:

- early F0 after attack;
- settled F0;
- post-bend target F0;
- cents error;
- discontinuity at coefficient-update boundaries.

Initial gate:

- settled static fundamental: median <3 cents, max <8 cents;
- post-bend tail: median <10 cents, max <35 cents;
- no isolated zipper line louder than -55 dB relative to the fundamental for a slow bend.

The values may be revised after the estimator is validated, not merely because the implementation misses them.

### E2 — T60 and spectral decay

Sweep:

```text
pitch: E2, A2, D3, G3, B3, E4, E5
sus: 0.25, 0.5, 0.8, 1.5, 3, 6, 12
damp: 0, 0.2, 0.4, 0.7, 0.9
```

Measure T20/T30/T60 extrapolations for:

- fundamental;
- partials 2–8;
- ERB or octave bands;
- broadband RMS.

Report where requested fundamental T60 becomes infeasible under the contraction clamp. Do not hide those cells. The parameter contract may need to change from exact T60 to a target or low-frequency decay time.

### E3 — pick-position physics

Sweep `pos=0.05..0.5` in 0.025 increments with `pick=0`, then with `pick=0.5` and `1`.

For partial index `n`, compare measured amplitude against the ideal displaced-string envelope:

\[
A_n\propto\frac{\sin(n\pi p)}{n^2p(1-p)}.
\]

Required qualitative result:

- nodal valleys move with `pos`;
- midpoint strongly suppresses even partials;
- roughness fills nulls gradually as `pick` rises rather than erasing position identity;
- RMS normalization does not produce extreme peaks near rational positions.

### E4 — stiffness/in\-harmonicity

Fit partial frequencies to a stiff-string approximation:

\[
f_n\approx nf_0\sqrt{1+Bn^2}.
\]

Sweep pitch and `stiff`. Estimate `B`, settled fundamental error, and spectral centroid.

Required result:

- fitted `B` is nondecreasing with `stiff` over the useful region;
- fundamental remains within tuning gate;
- high-note stiffness is gracefully reduced when the phase budget is insufficient;
- no allpass coefficient approaches an unstable or numerically pathological value.

### E5 — onset tension modulation

Sweep:

```text
tension: 0, 3, 6, 12, 24, 40, 80 cents
sus: 0.5, 1.5, 3, 6
pitch: E2, A3, E4, E5
```

Track instantaneous F0 and amplitude envelope. Fit the cents trajectory to an exponential and compare its time constant with the intended relationship to T60.

Required result:

- `tension=0` is identity;
- positive values begin above nominal and settle toward it;
- no late pitch bias remains beyond tolerance;
- the effect remains audible at moderate values without sounding like a generic synth pitch envelope.

### E6 — contact and aliasing

Sweep `buzz`, pitch, displacement level, and sample rate/oversampling factor.

Measure:

- feedback magnitude before/after contact;
- removed scalar energy proxy;
- emitted contact energy;
- alias-to-signal ratio above the physical partial region;
- peak and DC drift.

Stop-the-line if feedback contact ever increases `|y|` in the scalar model or emits NaN/Inf.

## 4. Body and sympathetic resonance

### E7 — body is dynamic coupling, not EQ

For a single string between two body modes, compare:

1. body disabled;
2. coupled modal body;
3. dry string followed by an EQ matched to the average spectrum of condition 2.

Use time-frequency descriptors and listening. The coupled body should differ from the matched post-EQ condition in decay trajectory, beating, and after-ring, not only static magnitude response.

### E8 — body-size sweep

Sweep `body_size=0.5..2.0`. Track each body peak.

Expected first-order law in the rough implementation:

\[
f_{m}(s)=f_m(1)/s.
\]

Listen for discontinuities and unmusical modal pileups. Decide whether damping, coupling, and radiation weights also require scale laws.

### E9 — sympathetic selectivity

Directly excite pitches at and between open-string harmonics. For each hidden open course, measure stored/radiated energy.

Required result:

- response peaks near compatible harmonics;
- off-resonant pitches transfer substantially less;
- `symp=0` removes hidden strings and is byte-identical to a build without them;
- `symp=1` remains subordinate to direct excitation and bounded.

## 5. Guitar listening studies

### E10 — expert diagnostic A/B

Conditions:

- old pluck;
- new isolated string, no body/sympathy;
- new full guitar;
- optionally a strong external physical-model guitar reference.

Prompts:

- Which sounds more like a string under a hand?
- Which attack is less noise-burst-like?
- Which body response sounds coupled rather than filtered?
- Which bend sounds like changing string length/tension rather than resampling?
- Which would you choose in a mix?

Rate 1–7:

```text
string identity
attack credibility
pitch stability
body credibility
gesture responsiveness
absence of synthetic artifacts
musical preference
```

Blind condition labels and loudness-match within 0.2 LU where practical.

### E11 — phrase test

Use the same eight-bar score for old and new implementations:

- fingerstyle arpeggio;
- alternating down/up strums;
- muted ostinato;
- whole-step bend;
- bridge vs neck pluck;
- open chord let-ring.

A model that wins isolated-note analysis but loses the phrase test is not an improved instrument.

## 6. Weave/Ariadne structural experiments

### E12 — zero-limit decomposition

Render identical input while independently setting:

```text
couple=0
orbit_depth=0
curvature=0
body=0
chirality=0
```

Verify the identity laws in `PARAMETERS.md`. This isolates each mechanism before combined presets are judged.

### E13 — local order-defect verification

For a grid of angles `a,b ∈ [-0.45,0.45]`:

1. build `U=R12(b)R01(a)` and `V=R01(a)R12(b)`;
2. compute SVD norm `||U-V||₂`;
3. compare against `weave_holonomy_defect(a,b)`;
4. verify small-angle ratio `δ/|ab| → 1` away from zero numerical noise.

Require agreement near machine precision in f64.

### E14 — chirality A/B

Use identical note, body, course set, and loudness. Compare `chirality=+c` and `-c` across:

```text
c: 0.2, 0.5, 0.8, 1
couple: 0.04, 0.08, 0.12, 0.2, 0.3
courses: 5, 8, 11, 17
```

Measure:

- waveform distance;
- log-spectral distance;
- ERB-envelope distance;
- modulation-spectrum distance;
- pitch and loudness difference;
- listener ABX identification.

The effect fails as an instrument capability if identification depends only on gross loudness or detuning.

### E15 — closed control-loop commutator

This is the strongest first demonstration of “the thread remembers the path.”

Construct a sustained fixed-delay network and two local coupling generators `A` and `B`. Starting from zero control, apply the four pulse segments

\[
\gamma_{AB}=A,\,B,\,-A,\,-B
\]

and the reversed-order loop

\[
\gamma_{BA}=B,\,A,\,-B,\,-A.
\]

Both control sequences return every scalar control to its initial value. Their state transports are group commutators and need not be identity or equal.

Implementation options:

- a direct DSP test over the scattering state;
- a research renderer with piecewise coupling automation inside one persistent voice;
- later, a MUS span/automation form.

Outputs:

- state difference immediately after the loop;
- `H₂` operator/path metric where tractable;
- pickup-projected difference `H_C`;
- a loudness-matched audio pair;
- ABX listener result.

Do not call this Berry holonomy. It is a discrete cyclic ordered-product result and is already mathematically meaningful.

### E16 — orbit sidebands

With curvature off, sweep `orbit` and `orbit_depth`. For a simple input, track sideband spacing.

Expected result: prominent modulation spacing should follow orbit rate, while total scattering energy remains approximately unchanged before explicit losses. Check for coefficient-rate aliasing and accidental DC.

### E17 — state-dependent curvature

Prepare two internal states with equal total energy but energy concentrated in different courses. Apply identical instantaneous controls with curvature on and off.

Required result:

- with `curvature=0`, the same matrix applies regardless of energy distribution;
- with curvature on, local angles differ while each individual scattering step remains norm-preserving;
- the resulting audible difference persists beyond one sample and is not a floating-point accident.

### E18 — path-memory decay

After two control paths produce different internal orientations, freeze controls to the same endpoint and observe the output/state distance over time.

Define a path-memory decay time as the time for projected difference energy to fall 60 dB. Map it over sustain, body coupling, course loss, and topology.

This measurement should eventually underlie the plugin’s `Memory` macro.

## 7. Spectral-dimension experiments

### E19 — current scaffold sweep

Grid:

```text
dimension: 0.55, 0.65, 0.8, 1, 1.2, 1.35, 1.6, 2, 2.5, 3
courses: 5, 8, 11, 17, 24
base pitch: E2, A2, A3, E4
```

For each configuration record:

- generated frequencies before and after octave fold;
- minimum cents spacing;
- duplicates/collisions;
- spectral centroid and flatness;
- roughness/dissonance proxies;
- pitch salience;
- listener descriptors.

Flag any pair within 3 cents and any virtual course above the antialias policy.

### E20 — collision-aware replacement

Compare current octave folding against a constrained projection that minimizes

\[
\sum_k\left(\log f_k-\log f_k^*\right)^2
\]

subject to range and minimum log-frequency spacing. Determine whether the collision-aware version sounds more structured or merely less dense.

### E21 — graph-derived spectra

Prototype at least four explicit topologies with similar course count and total bandwidth:

- ring;
- path/chain;
- binary tree;
- Möbius ladder or another nontrivial cyclic graph.

Use a normalized weighted Laplacian or declared wave operator. Compare eigenfrequency distribution, excitation localization, route memory, and musical utility. This is the experiment that can turn spectral dimension from a scalar frequency recipe into instrument geometry.

## 8. Broad parameter exploration

A full factorial over all controls is wasteful. Use three stages.

### Stage A — one-factor and pairwise maps

For every parameter, sweep 21 points around a moderate reference preset. For strongly interacting pairs, render 11×11 maps:

```text
couple × chirality
couple × orbit_depth
couple × curvature
dimension × courses
stiff × damp
body × symp
buzz × pick
```

Generate descriptor heatmaps and listen at corners, center, ridges, and discontinuities.

### Stage B — space-filling sample

Generate a deterministic Sobol or Latin-hypercube design of 512–2,048 points over the declared safe region. For every render, calculate:

```text
peak and loudness
F0 confidence/error
spectral centroid/flatness/rolloff
inharmonicity
roughness
modulation energy
decay times by band
path/chirality contrast when paired
CPU and allocation metrics
```

Cluster descriptor vectors. Select medoids and outliers for human listening rather than listening to thousands of near-duplicates.

### Stage C — constrained search for instruments

Optimize separate objectives:

- convincing guitar;
- pitched impossible instrument;
- maximal path audibility at controlled loudness/pitch;
- maximal timbral motion without loss of pitch salience;
- extreme texture under alias/peak constraints.

Human ratings must remain in the loop. Descriptor optimization alone will find clever noises.

## 9. Whole-network energy experiments

### E22 — fixed-geometry decay

Disable excitation after initialization, tension, bends, orbit, and all coefficient motion. Track a declared state-energy proxy and output.

Required result:

- scattering-only step changes energy only by roundoff;
- explicit body/string losses make the envelope nonincreasing at circulation-scale resolution;
- no hidden mode grows.

### E23 — time-varying-delay work

Repeat with controlled bends and tension relaxation. Measure state energy immediately before and after each coefficient/delay update.

Report:

\[
G_{\mathrm{mod}}=10\log_{10}\frac{\max_n E_n}{E_0}
\]

and net energy change relative to the corresponding fixed-delay decay.

This experiment is mandatory before claiming whole-network passivity. A bounded audible render is not proof that modulation never injects energy.

### E24 — energy-compensated alternatives

Implement and compare at least two approaches:

- current coefficient update;
- a literature-derived energy-compensated time-varying waveguide;
- optionally a crossfaded dual-reader or state-resampling method with explicit normalization.

Compare pitch smoothness, sidebands, energy change, CPU, and sound. Prefer the method that makes the mathematical contract true without sterilizing bends.

## 10. Real-time engineering experiments

### E25 — allocation audit

Construction may allocate. `next_sample` and `render_block` may not.

Use an allocator counter or real-time test harness. Exercise all modes and automation paths. Any allocation, lock, filesystem access, or logging in the callback is a failure.

### E26 — CPU matrix

Benchmark release builds at 48, 96, and 192 kHz over:

```text
voices: 1, 8, 32, 64
courses: 6, 11, 17, 24
body modes: 0, 10, future 32
quality: base, oversampled contact if implemented
block: 16, 32, 64, 128, 512
```

Report median, p95, p99 callback time and deadline misses on at least one Apple Silicon and one x86-64 target if available.

### E27 — denormals and long tails

Render 60 seconds after excitation with long sustain. Check CPU and state for denormals. Apply an explicit strategy if needed; do not add nondeterministic noise casually.

### E28 — automation continuity

For every continuously automatable parameter, render steps, ramps, and host block-boundary changes. Measure discontinuity and sidebands. Define which controls are:

- sample-smoothed;
- block-smoothed;
- note-on only;
- topology-rebuild controls requiring crossfade.

`courses` and graph topology should not mutate an active voice without an explicit state-transfer design.

## 11. Preliminary spectrograms

The originating research session produced three prototype images named:

```text
guitar_proto_spectrogram.png
weave_proto_spectrogram.png
weave_extreme_spectrogram.png
```

Qualitatively, the guitar prototype showed a decaying harmonic ladder; moderate Weave showed denser inharmonic sidebands while retaining pitch; extreme Weave showed broad, moving, comb-like partial structure. These files were not generated from the integrated branch and are **not acceptance evidence**. Reproduce the conditions from committed scores and receipts.

## 12. Stop-the-line failures

Do not compensate downstream for any of the following:

- NaN or Inf;
- unbounded unforced state;
- hidden gain in a stage documented as lossless;
- pitch error concealed by body/reverb;
- T60 promise missed without reporting the infeasible control cell;
- a “path effect” caused only by loudness, pan, random seed, or different endpoint controls;
- parameter change that does nothing despite a nonzero UI control;
- block-size-dependent output;
- callback allocation or lock;
- aliasing dominating release presets;
- old non-pluck parity regression;
- listening preference measured without loudness matching;
- theorem language stronger than the implemented premises.

## 13. First sprint exit report

The implementation agent should finish with one compact report containing:

1. branch and commit;
2. files changed;
3. compile/test/parity status;
4. invariant table with measured values;
5. guitar A/B links or artifact paths;
6. moderate and extreme Ariadne renders;
7. AB/BA or chirality path demonstration;
8. CPU/allocation result;
9. unresolved P0 issues;
10. an explicit recommendation: merge, continue experimentally, or reject/rework a premise.
