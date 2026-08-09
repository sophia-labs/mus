# Aigua Analysis v2 — executable foundation

Aigua v1 is an unusually productive exploratory analysis: it decodes one field
recording, constructs source-oriented signal views, proposes event regions,
computes event descriptors, forms one seven-way acoustic partition, curates a
sample instrument, composes with it, and inspects the renders. Its scientific
weakness is not a lack of ingenuity or features. It is that one mutable set of
files carries several incompatible kinds of truth.

Aigua v2 begins by making those kinds explicit and durable.

This directory now has an executable scientific-computing substrate under
`mus_analysis/`. The first revision does four things:

1. preserves the existing branch as an immutable historical research object;
2. separates event hypotheses, observations, model memberships, human curation,
   perceptual claims, and compositional interpretation;
3. emits a deterministic RDF projection governed by a first MUS audio ontology;
4. implements the first genuinely new analysis lanes: detector reconciliation,
   cross-estimator pitch consensus, continuous gesture analysis, and
   model/bootstrap cluster stability.

The code is deliberately additive. The historical scripts are not rewritten in
place. They remain the executable fossil whose outputs are imported and made
semantically honest.

## 1. Scientific invariants

Aigua v2 enforces the following rules in code and data contracts.

### Exact material identity

All durable inputs and outputs are content-addressed by SHA-256. A run receipt
refers to exact bytes, not merely a path such as `events.json` that can later be
rewritten.

### Write-once runs and projections

Content-addressed objects, run receipts, and named projections are immutable.
Rewriting an identical value is idempotent. Rewriting different bytes at an
existing durable name is an error.

### Signal-view identity

An observation can name the exact signal view on which it was computed. The raw
capture, bird-band filter, spectrally gated view, PCEN representation, and any
model-separated component are distinct entities. None is silently promoted to
"the birds."

### Evidence-kind identity

The model distinguishes:

- directly measured;
- deterministically computed;
- statistically estimated;
- model inferred;
- human annotated;
- human curated;
- perceptually reported;
- compositional interpretation;
- unresolved.

A spectral centroid, a Ward membership, the label `bright`, and a listener
rating can target the same event without becoming the same kind of assertion.

### Typed scores

There is no unqualified `confidence` field. Every score names its semantics.
The historical `f0_conf` is imported as an
`aigua-shs-peak-to-mean-score`, not probability. The historical `am_depth` is
corrected to `envelopeAutocorrelationPeakStrength`; its implementation returned
an autocorrelation value and could be negative, so calling it modulation depth
was materially misleading.

### Refusal is a result

Pitch consensus has four states:

- `resolved`;
- `octave-conflict`;
- `disagreement`;
- `insufficient-support`.

An octave conflict records an octave-equivalent candidate for diagnosis but does
not silently emit a consensus frequency.

### Model categories are not domain kinds

The ontology keeps separate:

- acoustic cluster membership;
- call-type hypothesis;
- taxonomic hypothesis;
- individual-identity hypothesis;
- curatorial-family membership;
- instrument-voice membership.

### Dense arrays stay outside RDF

RDF carries identity, provenance, method, relationships, evidence kind, compact
results, and references. Frame trajectories, spectrograms, embeddings, and
co-assignment matrices are data artifacts, not millions of triples.

## 2. Repository layout

```text
mus_analysis/
  canonical.py             deterministic JSON and semantic identities
  model.py                 typed scientific records
  store.py                 immutable content-addressed research objects
  run.py                   real-command execution receipts
  rdf.py                   deterministic N-Triples projection
  aigua_v1.py              historical Aigua importer
  segmentation.py          segmentation-lattice reconciliation
  audio_segmentation.py    historical-style + independent PCEN proposal lanes
  pitch.py                 cross-estimator consensus and refusal states
  audio_pitch.py           SHS, pYIN, and dominant-ridge operators
  audio_gesture.py         continuous trajectory and gesture summaries
  clustering.py            co-assignment, stability, and partition distance
  cli.py                   executable pipeline surface

ontology/
  mus-audio.ttl
  mus-audio-shapes.ttl

schemas/
  run-receipt.schema.json
  observation.schema.json
  analysis-profile.schema.json

aigua/research/
  aigua-v1-import.json
  profile-registry.json
  descriptor-registry.json
```

## 3. Preserve Aigua v1

Run from the repository root:

```bash
python aigua/import_research_object.py \
  --config aigua/research/aigua-v1-import.json
```

or after installing the package:

```bash
mus-analysis import-aigua-v1 \
  --project-root . \
  --store aigua/research-object \
  --config aigua/research/aigua-v1-import.json
```

The importer does **not** rerun DSP. It preserves:

- the historical `events.json` and `events.csv`;
- `instrument.json`;
- the source recording when a configured candidate path exists;
- separate event-hypothesis records;
- separate observation records with corrected semantics;
- separate Ward-model memberships;
- attributed family and sample-selection interpretations;
- an explicit claim register;
- five historical run receipts;
- a deterministic N-Triples projection.

The resulting store has the shape:

```text
aigua/research-object/
  objects/sha256/...
  runs/.../receipt.json
  projections/aigua-v1.json
  projections/aigua-v1.nt
  profile-registry-snapshot.json
  manifest.json
```

Verify it with:

```bash
mus-analysis verify --store aigua/research-object
```

The importer is idempotent. Running it again over identical source artifacts
produces identical durable objects. If a named projection would change, the
write is refused rather than silently replacing the historical record.

## 4. Segmentation lattice

The first new audio profile runs two independent event-proposal lanes:

1. a typed, non-mutating form of the historical local-floor/hysteresis detector;
2. a PCEN mel representation followed by an independent local hysteresis rule.

```bash
mus-analysis segment-audio aigua/aigua_raw.wav \
  --sample-rate 48000 \
  --band-low-hz 900 \
  --band-high-hz 11000 \
  --output aigua/v2/segmentation.json \
  --store aigua/research-object
```

The result retains both detector runs, their activity traces and thresholds,
then derives cross-run relations:

```text
approximately-corresponds-to
contains
contained-by
overlaps
disjoint
```

Connected cross-run regions become `ReconciledEventHypothesis` records with a
support fraction. If one detector proposes one phrase while another proposes
two syllables, the component is marked `ambiguous_split_or_merge`; it is not
flattened into one supposedly canonical event.

The next detector lanes should be manual review, spectral change-point
proposals, and a trained syllable segmenter. The reconciliation contract need
not change.

## 5. Pitch ensemble and consensus

Aigua v2 includes three reference trajectories:

- log-frequency SHS at constant cents resolution;
- `librosa.pyin`, retaining its voiced-probability output and semantics;
- a dominant spectral ridge, explicitly **not** named f0 because it may track an
  overtone.

Run them over one region:

```bash
mus-analysis extract-pitch aigua/aigua_raw.wav \
  --start-seconds 12.464 \
  --end-seconds 12.969 \
  --fmin-hz 700 \
  --fmax-hz 5000 \
  --output aigua/v2/event-20-pitch.json \
  --store aigua/research-object
```

The consensus is computed in cents. It emits a frequency only when the required
number of methods agree within the declared tolerance. Exact or approximate
octave disagreements become `octave-conflict`, preserving the possibility that
a spectral ridge follows a harmonic while an f0 method follows a fundamental.

Event-level span summaries are derived only from resolved frames. This is the
first concrete correction to Aigua v1's large-span claim: the representation
can now state how much of the event was resolved, how many frames conflicted by
octave, and how many disagreed otherwise.

The next operator adapters should be SWIPE, CREPE, and an explicit partial-track
model. They can enter as additional trajectories without changing consensus
semantics.

## 6. Continuous gesture bundle

One-row-per-event analysis is replaced by a `GestureObservationBundle`:

```bash
mus-analysis analyze-gesture aigua/aigua_raw.wav \
  --start-seconds 12.464 \
  --end-seconds 12.969 \
  --fmin-hz 700 \
  --fmax-hz 5000 \
  --output aigua/v2/event-20-gesture.json \
  --store aigua/research-object
```

The bundle currently preserves trajectories for:

- frame RMS in dBFS;
- spectral centroid;
- spectral bandwidth;
- spectral flatness;
- 95-percent spectral rolloff;
- normalized-frame spectral flux;
- consensus pitch, with unresolved frames represented as missing.

It derives compact summaries for:

- duration;
- attack and release estimates;
- resolved-pitch coverage;
- median pitch and resolved pitch span;
- median and maximum absolute FM velocity;
- FM inflection count;
- centroid distribution;
- median flatness;
- dominant envelope-modulation rate;
- modulation-spectrum peak-to-median score;
- a separately named robust envelope modulation index.

The robust modulation index is deliberately not advertised as a universal
psychoacoustic modulation depth. Its formula and semantics are explicit.

The next gesture operators should add partial tracks, spectral-envelope
trajectories, aperiodicity, AM/FM coupling, scattering features, trajectory
covariance, and analysis-resynthesis fixtures.

## 7. Cluster stability

Aigua v1 hard-assigned every event to one of seven Ward clusters. Aigua v2 can
now ingest any number of bootstrap, model, representation, or boundary-perturbed
label runs:

```json
{
  "labelRuns": [
    {"event-0": 0, "event-1": 0, "event-2": 1},
    {"event-0": 4, "event-1": 4, "event-2": -1}
  ]
}
```

```bash
mus-analysis cluster-stability label-runs.json \
  --threshold 0.8 \
  --output cluster-stability.json
```

The output includes:

- pairwise co-assignment probabilities;
- the number of runs in which each pair was comparable;
- per-item stability summaries;
- thresholded consensus components;
- variation-of-information support in the Python API.

Noise and missing assignments do not count as evidence that two events belong
apart. This matters for HDBSCAN and other models that can refuse to assign an
outlier.

## 8. Ontology projection

`ontology/mus-audio.ttl` is the first domain ontology. It imports no assumption
that cluster, call type, taxon, curation, and instrument voice are equivalent.
It defines the principal classes and relations for:

- material identity and signal views;
- analysis runs, profiles, and operator bindings;
- observations, estimates, and hypotheses;
- representation spaces and models;
- human interpretation and perceptual reporting;
- claims and evidence kinds.

`ontology/mus-audio-shapes.ttl` provides initial SHACL shapes. In particular:

- observations must identify target, run, procedure, property, evidence kind,
  and result;
- a score value requires score semantics;
- model membership must identify target, cluster model, cluster, run, and
  evidence kind;
- interpretations and claims require attribution.

The Aigua importer writes `projections/aigua-v1.nt` through the same model. Dense
frame series remain in data artifacts.

## 9. What remains scientifically unfinished

The foundation is intentionally not represented as completion of the research
program. Important next work includes:

1. execute the importer against the full committed Aigua assets and inspect the
   resulting graph in `gardend`;
2. add array-artifact storage for trajectories and spectrograms rather than
   carrying large series in one JSON response;
3. manually review a stratified event subset and quantify both historical and
   PCEN detector error;
4. add SWIPE, CREPE, and partial-track pitch lanes, plus known-trajectory
   synthetic fixtures;
5. run the pitch ensemble over all historical events and replace the old span
   distribution with a method-sensitive report;
6. build interpretable, DTW, auditory/scattering, and learned representation
   spaces;
7. fit model and bootstrap ensembles, then publish a co-assignment/stability
   report for the seven-family claim;
8. add bout and transition analysis with explicit evidence-sufficiency tests;
9. add taxonomic model adapters as hypotheses with checkpoint and score
   semantics;
10. build transformation grids and listening-study objects;
11. project the research object into a real local `gardend` graph and implement
    Shrubbery faces for signal views, segmentation, gestures, repertoire
    geometry, claims, and provenance.

The important architectural work is already done: none of these additions
needs to recover scientific meaning from a shared mutable CSV again.
