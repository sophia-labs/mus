# MUS psychoacoustic spatial canvas

This implementation turns a mono recording into an editable object scene. It is deliberately a production canvas, not a historical-scene reconstruction system.

```text
mono asset
  -> additive decomposition + explicit residual
  -> psychoacoustic report per component
  -> analysis-seeded object layout
  -> cue-targeted manipulation
  -> Web Audio HRTF audition
  -> deterministic stereo or FOA AmbiX render
```

## Install

```bash
python -m pip install -e '.[spatial,test]'
# Optional standardized pressure-domain metrics:
python -m pip install -e '.[psychoacoustics,test]'
```

`MoSQITo` is optional. The pipeline always computes digital, spectral, temporal, Bark-energy, modulation, programme-loudness, HPSS and pYIN-derived observations. ISO/DIN/Daniel–Weber rows are returned as `refused` when no pressure calibration is supplied and as `unavailable` when the optional reference implementation is not installed. Digital full scale is never silently interpreted as pascals.

## Fast path

Start with an empty canvas and add sounds in the browser:

```bash
mus-spatial new --output-dir my-spatial-canvas
mus-spatial serve my-spatial-canvas/scene.json --editable
```

The **Add sound** surface accepts one or several recordings and offers six objectization modes: whole sound, event objects, NMF texture components, ERB-rate auditory frequency layers, harmonic/percussive layers, or the recommended hybrid of event objects plus residual texture. Uploads can be placed at the current playhead. WAV/FLAC and other libsndfile formats load directly; AAC/M4A and other common containers fall back to a loud, explicit `ffmpeg` decode when needed.

A generated three-object demonstration is also included:

```bash
python examples/make_spatial_canvas_demo.py --output-dir /tmp/mus-spatial-demo --render
mus-spatial serve /tmp/mus-spatial-demo/scene.json --editable
```

It contrasts a tonal glide, a 70 Hz amplitude-modulated rough call, and a diffuse wind texture so the analysis and controls have visibly and audibly different starting material.

Or prebuild a scene from Aigua and its reviewed event regions:

```bash
mus-spatial scene aigua/source/aigua-birds-2026-08-08.m4a \
  --output-dir aigua/spatial-v1 \
  --mode hybrid \
  --regions aigua/events.json \
  --components 5

mus-spatial serve aigua/spatial-v1/scene.json --editable
```

The browser surface uses Web Audio `PannerNode` in `HRTF` mode. Drag objects around the top-down stage, rotate the listener’s head, change object height and spread, and manipulate brightness, roughness cues, fluctuation cues, attack and pitch while listening. `tonalFocus` is shown but marked offline because it uses HPSS in the deterministic renderer. **Analyze current intervention** applies the same controls server-side and shows metric deltas. **Commit variation** materializes those controls as a new analyzed object with explicit parentage and a manipulation receipt.

Saving writes `scene.edited.json` by default. The scene JSON—not the browser’s current binaural waveform—is the authoring authority.

## Decomposition modes

### `whole`

Creates one analyzed extended object. This is the fastest route for an arbitrary recording.

### `events`

Uses supplied event regions, or generic non-silent proposals, to create one normalized time-frequency soft-mask component per event. All event masks and an explicit residual share every time-frequency cell, preventing overlap from duplicating energy.

### `nmf`

Creates inspectable full-length texture components with non-negative matrix factorization. A time-domain residual preserves exact additive closure.

### `hybrid`

Creates event objects first and decomposes the remaining residual into NMF texture components. This is the recommended general-purpose canvas: compact events remain direct objects while background beds become extended fields.

### `bands`

Partitions the complex STFT into smooth, normalized ERB-rate spectral layers. This is a reversible production decomposition inspired by auditory frequency spacing, not a standardized cochlear model. It is particularly useful for moving the low, middle, and high perceptual material of one recording into different regions of the canvas.

### `hpss`

Creates harmonic-like and percussive-like layers using median-filter harmonic/percussive separation. These are morphology-oriented signal layers, not claims about physical sources or universal perceptual harmonicity.

Every decomposition report includes waveform closure error. Components are acoustic hypotheses and editable material; they are not asserted to be physical sources.

## Psychoacoustic report

Each object stores the full report inline and as a separate JSON file. The initial implementation operationalizes:

- digital RMS, sample peak, approximate true peak, crest factor;
- ITU-style integrated programme loudness through `pyloudnorm`;
- spectral centroid, bandwidth, rolloff, flatness and log-frequency slope;
- attack time and temporal energy centroid;
- a Bark-band sharpness proxy;
- Bark-envelope roughness and fluctuation proxies plus dominant modulation rate;
- HPSS harmonic-energy ratio;
- median pYIN voiced probability as an estimator-specific pitch-salience proxy;
- calibrated ISO 532-1 time-varying loudness, DIN sharpness and Daniel–Weber roughness through MoSQITo when the required pressure mapping is available;
- calibrated ECMA-418-2 hearing-model loudness and roughness when exposed by the installed MoSQITo release;
- calibrated ECMA-418-1 stationary prominence-ratio and tone-to-noise-ratio analyses.

The machine-readable construct registry records evidence grades and non-equivalences such as:

```text
RMS != loudness
programme loudness != psychoacoustic loudness
spectral centroid != brightness
sharpness != brightness
roughness proxy != roughness in asper
psychoacoustic roughness != semantic texture roughness
f0 candidate != perceived pitch
```

## Calibration

Two explicit forms are supported.

```bash
# One digital sample unit corresponds to this many pascals:
mus-spatial analyze sound.wav --pa-per-unit 0.2

# A measured digital RMS corresponds to a known SPL:
mus-spatial analyze sound.wav \
  --reference-rms-dbfs -20 \
  --reference-spl-db 74 \
  --field-type free
```

Without one of these declarations, standardized pressure-domain operators refuse to produce absolute values. Relative proxies remain available for comparison and interaction.

## Cue-targeted manipulation

```bash
mus-spatial manipulate input.wav output.wav \
  --brightness-db 6 \
  --brightness-hz 2500 \
  --roughness-depth .25 \
  --roughness-rate-hz 70 \
  --fluctuation-depth .15 \
  --fluctuation-rate-hz 4 \
  --attack-seconds .08 \
  --pitch-semitones 7 \
  --tonal-focus .4
```

Each operation returns a manipulation receipt. Controls target acoustic cues:

- `brightnessDb` is an RBJ high-shelf, not a brightness-unit setter;
- roughness and fluctuation controls introduce amplitude modulation in relevant rate regions, not absolute asper or vacil values;
- `tonalFocus` mixes HPSS harmonic and percussive components, not universal harmonicity;
- target LUFS is programme-loudness matching, not equal-sensation loudness;
- pitch shift is an intervention whose quality and identity retention remain separate empirical questions.

The intended loop is:

```text
analyze original
-> intervene
-> reanalyze transformed object
-> audition in scene
-> collect perceptual reports
```

## Scene contract

The portable scene stores:

- mono object audio paths;
- point, extended, diffuse or ambient posture;
- position and optional position trajectory;
- spread, gain and room send;
- source timing and region provenance;
- the psychoacoustic report;
- cue-targeted controls;
- placement provenance.

Coordinates follow Web Audio’s default convention: +X right, +Y up and -Z front.

The first automatic layout is explicitly an `analysis-mapped` composition aid:

- family or label distributes azimuth;
- spectral centroid maps to elevation;
- digital RMS maps to distance;
- roughness proxy maps to spatial spread.

These mappings are visible in each object’s metadata and can be replaced by hand.

## Rendering

```bash
mus-spatial render scene.json render-stereo.wav --target stereo
mus-spatial render scene.json render-foa.wav --target foa
```

The offline stereo renderer is deterministic equal-power panning with listener-relative orientation, distance attenuation, simple air absorption, decorrelated spread and a seeded synthetic room. It is a production render, not the browser HRTF renderer.

FOA output is AmbiX ACN/SN3D in channel order `W,Y,Z,X`. It is intended as a portable scene projection for downstream binaural or loudspeaker decoding.

Every render writes a receipt containing object manipulations, spatial parameters, safety gain, output channel order and output digest.

## HTTP boundary

`mus-spatial serve` exposes only:

```text
GET    /api/scene
GET    /api/capabilities
PUT    /api/scene                         editable mode only
POST   /api/objects                       ingest and analyze a recording
DELETE /api/objects/<object-id>           editable mode only
POST   /api/analyze/<object-id>           apply controls and return fresh evidence
POST   /api/objects/<object-id>/derive    materialize controls as a child object
GET    /media/<object-id>                 HTTP Range support
GET    /, /app.js, /styles.css
```

Media paths are resolved only through object IDs already declared by the scene. Arbitrary filesystem paths are not served.

## Next scientific increments

The current implementation is a complete substrate, not the endpoint. The strongest next additions are:

1. Verification-vector gates for every optional standardized operator, including ECMA hearing-model and tonality lanes.
2. A shared ERB excitation/specific-loudness/modulation artifact layer rather than independent metric recomputation.
3. SOFA-backed deterministic offline binaural rendering and HRTF comparison.
4. Learned and query-conditioned separation adapters whose outputs still satisfy the same additive-component and residual contracts.
5. Listening-study objects for brightness, semantic roughness, pitchability, source identity, externalization and transformation quality.
6. A Shrubbery face set over the same scene and reports, replacing the standalone shell without changing domain contracts.
