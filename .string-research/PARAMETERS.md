# Ariadne parameter contract

This is the proposed public vocabulary for the deepened guitar and Weave/Ariadne voice. The Rust payload already parses these names. The implementation agent must make `mus-engine`, `mus-vocab`, the CLI dump, Atril controls, receipts, and any plugin wrapper agree with one registry.

## 1. Dispatch

| Name | Type | Values | Meaning |
|---|---|---:|---|
| `synth` | enum | `saw`, `square`, `tri`, `sine`, `pluck`, `weave` | `pluck` selects the deepened guitar; `weave` selects Ariadne’s generalized string network. |

`weave` is a voice/model name, not an oscillator waveform. Code that assumes every `synth` enum member can be passed to `_osc` must dispatch it first.

## 2. Shared pluck controls

These existed before the Ariadne work but their behavior or preferred defaults change.

| Parameter | Proposed control | Engine clamp/default | Applies to | Perceptual meaning |
|---|---|---:|---|---|
| `sus` | seconds | `0.05..20`, `2.5` | both | Requested fundamental T60. It may be shorter when the spectral-loss target cannot be met without feedback gain ≥1. |
| `damp` | ratio | `0..0.95`, `0.35` | both | Frequency-dependent loss: higher values kill high partials faster. |
| `pos` | ratio | `0.02..0.5`, `0.13` | both | Pluck location along speaking length. Midpoint suppresses even modes for the ideal triangular component. |
| `pick` | ratio | `0..1`, `0.6` | both | Contact width/roughness macro: fingertip/felt to hard bright plectrum. |
| `body` | ratio | `0..1`, proposed `0.42` | both | Coupling to stored body modes. This is no longer merely a post-EQ mix. |
| `strum` | milliseconds | `-80..80`, `10` | both | Signed per-course onset stagger. Negative reverses traversal. |
| `pm` | toggle | `false` | both | Palm-mute macro reducing sustain, brightness, onset tension, and sympathetic transfer. |
| `detune` | cents | payload `0..60`, `0` | both + subtractive synth | Adds a companion course. **Registry issue:** the existing subtractive synth UI permits up to 100 cents. Either raise the string clamp to 100 or document model-specific clamping; do not silently report one universal range while implementing another. |

Changing the `body` UI default from the old `0.25` to `0.42` is an intentional sonic decision only after listening. Until then, preserve the existing public default and set the stronger value in named presets.

## 3. New physical-guitar controls

| Parameter | Proposed `ParamKind` | Range/default | Applies to | Contract |
|---|---|---:|---|---|
| `stiff` | `Ratio` | `0..1`, `0.08` | both | Amount of allpass dispersion. Must preserve settled fundamental tuning within the invariant tolerance. |
| `tension` | `Cents` | `0..80`, `5` | both | Initial positive pitch elevation that relaxes exponentially. It is a perceptual macro, not yet a material-physics value. |
| `symp` | `Ratio` | `0..1`, `0.22` | guitar | Coupling scale for hidden open guitar courses. Ignored or zeroed in Weave, whose virtual courses serve a broader role. |
| `buzz` | `Ratio` | `0..1`, `0` | both | Contractive fret/bridge-contact macro. At zero the contact map must be an identity. |
| `body_size` | `Ratio` | `0.45..2.4`, `1` | both | Inverse scale on body-mode frequencies: larger values lower resonances. This is a body-scale macro, not a literal geometric similarity law yet. |

## 4. Weave controls

| Parameter | Proposed `ParamKind` | Range/default | Contract and zero-limit |
|---|---|---:|---|
| `couple` | `Ratio` or new `Radians` | `0..0.45`, `0.11` | Base nearest-neighbour Givens angle in radians. At zero, Weave scattering is identity. |
| `chirality` | bounded signed scalar | `-1..1`, `0.72` | Bias between forward and reverse ordered passes. `+1` is forward only, `-1` reverse only, `0` balanced. It is not pan. |
| `orbit` | `Hz` | `0..20`, `0.31` | Rate of the travelling coupling field. At zero, its phase is static. |
| `orbit_depth` | `Ratio` | `0..1`, `0.62` | Fractional depth of the travelling field. At zero, `orbit` must have no audible effect. |
| `curvature` | `Ratio` | `0..1`, `0.28` | State-energy-gradient deformation of local coupling angle. At zero, scattering is state-independent. |
| `courses` | `Count` | `3..24`, `11` | Target total course count, including played/detuned courses. Values below active course count resolve upward to the active count. |
| `dimension` | `Ratio` | `0.55..3`, `1.35` | Exponent in the Weyl-inspired virtual-frequency scaffold. It is not yet the measured spectral dimension of a graph. |

### `chirality` control typing

The current `ParamKind::Ratio` comment describes a “0..1-ish” value but structurally accepts arbitrary minima and maxima. Two clean options:

1. use `Ratio { min: -1, max: 1 }` and revise the comment to “bounded unitless scalar”; or
2. add `SignedRatio` and teach the vocabulary dump/UI about it.

Option 1 is the smaller change and is adequate.

### `couple` control typing

The value is an angle in radians, but musicians experience it as coupling amount. A generic `Ratio` slider is acceptable initially. A future `Radians` kind would be scientifically cleaner and could display both normalized amount and angle.

## 5. Exact `SYNTH_KEYS` addition

Append these names to `mus-rs/crates/mus-engine/src/pack.rs::SYNTH_KEYS`:

```rust
"stiff",
"tension",
"symp",
"buzz",
"body_size",
"couple",
"chirality",
"orbit",
"orbit_depth",
"curvature",
"courses",
"dimension",
```

Do not add duplicate entries for the existing shared controls.

## 6. Suggested `param_specs` entries

Adapt the prose to the code style; the semantic content should remain.

```rust
ParamSpec {
    name: "stiff",
    layer: Extension,
    kind: Ratio { min: 0.0, max: 1.0, default: Some(0.08) },
    doc: "string stiffness/dispersion; spreads upper partials while the fundamental remains phase-compensated",
},
ParamSpec {
    name: "tension",
    layer: Extension,
    kind: Cents { min: 0.0, max: 80.0, default: Some(5.0) },
    doc: "initial pluck-induced pitch elevation in cents, relaxing with the string energy",
},
ParamSpec {
    name: "symp",
    layer: Extension,
    kind: Ratio { min: 0.0, max: 1.0, default: Some(0.22) },
    doc: "coupling to sympathetic open guitar courses",
},
ParamSpec {
    name: "buzz",
    layer: Extension,
    kind: Ratio { min: 0.0, max: 1.0, default: Some(0.0) },
    doc: "contractive fret/bridge contact: clean at 0, hard buzzing contact at 1",
},
ParamSpec {
    name: "body_size",
    layer: Extension,
    kind: Ratio { min: 0.45, max: 2.4, default: Some(1.0) },
    doc: "body scale macro; larger values lower the body-mode frequencies",
},
ParamSpec {
    name: "couple",
    layer: Extension,
    kind: Ratio { min: 0.0, max: 0.45, default: Some(0.11) },
    doc: "Weave nearest-neighbour lossless scattering angle in radians",
},
ParamSpec {
    name: "chirality",
    layer: Extension,
    kind: Ratio { min: -1.0, max: 1.0, default: Some(0.72) },
    doc: "Weave ordered-path bias: reverse at -1, balanced at 0, forward at +1",
},
ParamSpec {
    name: "orbit",
    layer: Extension,
    kind: Hz { min: 0.0, max: 20.0, default: Some(0.31), sweep: false },
    doc: "rate of the travelling Weave coupling field",
},
ParamSpec {
    name: "orbit_depth",
    layer: Extension,
    kind: Ratio { min: 0.0, max: 1.0, default: Some(0.62) },
    doc: "depth of the travelling coupling field; 0 makes orbit inaudible",
},
ParamSpec {
    name: "curvature",
    layer: Extension,
    kind: Ratio { min: 0.0, max: 1.0, default: Some(0.28) },
    doc: "state-energy deformation of Weave coupling while preserving pointwise orthogonality",
},
ParamSpec {
    name: "courses",
    layer: Extension,
    kind: Count { min: 3, max: 24, default: Some(11) },
    doc: "target total number of played and virtual Weave courses",
},
ParamSpec {
    name: "dimension",
    layer: Extension,
    kind: Ratio { min: 0.55, max: 3.0, default: Some(1.35) },
    doc: "Weyl-inspired spectral-dimension exponent controlling virtual-course spacing",
},
```

The existing `Cents` variant currently appears to have a hard-coded semantic description and may use `default`/range fields exactly as above. Adjust mechanically to the actual enum definition rather than inventing a parallel representation.

## 7. Scope and override behavior

All controls are legal at instrument declaration and event suffix level because they travel through the synth patch merge.

Example:

```mus
# instruments:
#   ar = Ariadne (treble, synth=weave, courses=11, couple=0.11, chirality=0.7)

bar 1: ar=<E3 B3 E4>h[orbit=0.3,curvature=0.2] <F3 C4 F4>h[orbit=0.7,curvature=0.6]
```

Current semantics instantiate a fresh `StringNetworkVoice` per note/chord event. Parameters therefore set the state evolution inside that event; they do not automate one persistent global instrument across events. A plugin may support continuous automation, but it must define state and smoothing semantics rather than assuming event replacement is equivalent.

## 8. Cross-parameter constraints

Parsing clamps each scalar independently. The preset/macro layer should additionally project into a safe joint region.

### Suggested first safe region

```text
couple <= 0.30 for release presets
orbit <= 8 Hz for release presets
orbit_depth * couple <= 0.24
curvature * couple <= 0.22
courses <= 17 unless quality mode/oversampling is active
stiff <= 0.75 below 1 kHz and automatically reduced when phase budget is short
buzz <= 0.35 without oversampling
```

These are conservative engineering hypotheses, not mathematical limits. Replace them with measured CPU, aliasing, and boundedness envelopes.

## 9. Zero-limit laws

Every new control needs an invariant at its neutral value:

| Control at neutral | Required identity |
|---|---|
| `stiff=0` | no dispersion allpasses in the audible loop |
| `tension=0` | no onset pitch elevation |
| `symp=0` | no hidden guitar courses are constructed or coupled |
| `buzz=0` | contact map returns input exactly and emits zero contact output |
| `body=0` | no string/body transfer; body state cannot affect output |
| `couple=0` | `scatter_weave` is identity |
| `orbit_depth=0` | changing `orbit` has no effect |
| `curvature=0` | angle is independent of energy gradient |
| `chirality=0` | forward and reverse weights are equal |

Test these directly. Neutral controls are the most useful debugging surfaces.

## 10. Receipt and provenance fields

A render receipt should make an Ariadne sound reproducible without inspecting prose.

Recommended additions or nested metadata:

```json
{
  "voiceModel": "weave",
  "voiceModelVersion": "ariadne-weave-v0",
  "resolvedPatch": {
    "courses": 11,
    "dimension": 1.35,
    "couple": 0.11,
    "chirality": 0.72,
    "orbit": 0.31,
    "orbit_depth": 0.62,
    "curvature": 0.28
  },
  "bodyProfileDigest": null,
  "topologyDigest": null,
  "energyContract": "empirically-bounded-time-varying-v0"
}
```

Do not pretend a null body/topology digest is a calibrated artifact. Once profiles become files, digest them.

## 11. Plugin macro resolution

The plugin should publish both macro values and resolved scientific parameters. Suggested first-page macros:

| Macro | Principal targets |
|---|---|
| `Thread` | direct mix, courses, couple, dimension |
| `Labyrinth` | couple, chirality magnitude, orbit depth, curvature |
| `Motion` | orbit plus safe coefficient smoothing |
| `Material` | stiff, damp, pick, buzz |
| `Body` | body, body_size/profile morph |
| `Memory` | loss, coupling, orbit rate |
| `Hand` | pos, pick, tension, symp, micro-strum |

A macro is a deterministic mapping to this registry. It is not a hidden second parameter system.

## 12. Naming in UI

Recommended labels:

```text
Model: Guitar / Ariadne
Ariadne engine: Weave

Thread
Labyrinth
Motion
Material
Body
Memory
Hand

Advanced:
Course count
Spectral dimension
Coupling angle
Chirality
Orbit rate/depth
Curvature
```

The score language remains `synth=pluck` and `synth=weave`; the product-facing UI may say **Guitar** and **Ariadne**.
