# Ariadne next phase — executable retuning laws and production-shaped reference study

**Branch:** `agent/ariadne-next-phase`  
**Base:** `agent/ariadne-field-theory` at `16a8f0a`  
**Green workflow:** run `31453757295`  
**Artifact digest:** `sha256:a0c85dde6c5905947b3057b38a5540748ee47d6900ff0e09c8668f5201d3c26d`

## 1. Why this phase exists

The paper's immediate engineering claim is not yet that the production guitar has a neutral bend. It is that every state change must become an explicit, testable transport before the production renderer is altered. This phase establishes that executable seam.

The work therefore proceeds in three levels:

1. exact storage laws for the smallest time-varying recursive stages;
2. a production-shaped binary64 changing-delay oracle;
3. an evidence-based decision about what is safe to integrate into the real renderer next.

The result is deliberately narrower than the full paper. It does not yet provide a physical string Hamiltonian, a globally linear polar transport for the whole delay state, or a production `retune=neutral` mode. It does identify one exact repair that is ready for a production trial and rejects one superficially attractive repair as scientifically insufficient.

## 2. What was implemented

A new standalone workspace crate, `mus-watsn`, now contains:

- an exact storage coordinate and energy law for the production first-order allpass realization;
- exact energy-neutral transport of live allpass state when its coefficient changes;
- periodic delay-state interpolation with raw and state-normalized energy receipts;
- a sample/block work ledger;
- sparse ordered Givens programs, inversion, and closed commutator construction;
- the exact three-mode order-defect relation and both balanced inverse branches;
- a production-shaped one-string reference model and deterministic sweep generator;
- fail-loud CI that runs formatting, tests, Clippy, artifact generation, and scientific assertions.

The crate is independent of the MUS parser, RDF, Garden, KG-ULTRA, network services, and audio hosts. That dependency posture is intentional: it is the executable law layer beneath later authoring and semantic systems.

## 3. Exact first-order allpass storage

The production section implements

```text
y  = a*u + x1 - a*y1
x1' = u
y1' = y
```

Define the canonical stored coordinate

```text
s = x1 - a*y1.
```

Then one sample can be written

```text
y  = a*u + s
s' = (1-a^2)u - a*s,
```

and the exact real-arithmetic balance is

```text
u^2 + s^2/(1-a^2) = y^2 + s'^2/(1-a^2).
```

Thus the section's declared internal storage is

```text
E_a(s) = 1/2 * s^2/(1-a^2).
```

When the coefficient changes from `a0` to `a1`, preserving

```text
z = s / sqrt(1-a^2)
```

gives the exact neutral transport

```text
s1 = s0 * sqrt((1-a1^2)/(1-a0^2)).
```

The implementation retains `y1` and reconstructs

```text
x1_new = s1 + a1*y1.
```

A no-op coefficient update is byte-inert: if the clamped coefficient is unchanged, no state arithmetic is performed.

### Allpass result

Across the deterministic coefficient/state sweep:

| Quantity | Result |
|---|---:|
| maximum neutral coefficient-change work | `1.7763568394e-15` |
| maximum legacy coefficient-change work | `9.3860359522` |
| per-sample storage-balance tests | pass at binary64 roundoff |
| no-op neutral update | byte-inert |

The adversarial legacy maximum is not a claim about a normal guitar preset. It proves that changing a stable allpass coefficient while silently retaining its implementation state can reinterpret a large amount of stored energy. The exact neutral state map removes that ambiguity for this section.

## 4. Periodic delay remapping

The first rank-changing candidate periodically resamples the active delay state with linear interpolation. Raw interpolation does not preserve the declared Euclidean sum-of-squares metric. Doubling a well-resolved periodic state approximately doubles that sum because there are approximately twice as many stored coordinates; the worst raw energy-ratio error in the sweep was `0.999983`, corresponding to a raw ratio near `1.999983`.

A state-contingent scalar correction

```text
scale = sqrt(E_before/E_raw_after)
```

closes the declared energy difference for the current state. It is useful as a diagnostic and bounded real-time approximation. It is **not**:

- a globally linear isometry;
- the weighted polar factor of the full remapping operator;
- a physical moving-boundary model;
- proof that the Euclidean per-cell metric is the correct string energy as state dimension changes.

### Remap law result

| Quantity | Result |
|---|---:|
| maximum neutral relative energy residual | `1.9508399660e-15` |
| maximum raw energy-ratio error | `0.9999831604` |
| maximum absolute drift after 100 expand/contract cycles | `2.0961010705e-13` |
| state correlation after 100 cycles | `0.9987094442` |

The crucial negative result is that exact scalar energy closure does not preserve all state information. Repeated interpolation slowly changes waveform orientation even while the scalar energy is fixed. This distinction is central to the paper: a work ledger is necessary, not sufficient, for a musically faithful transport.

## 5. Production-shaped changing-delay reference

The binary64 reference model mirrors the current `DelayString` control law closely enough to isolate the state-transition issue before production integration. It includes:

- the production bend interpolation;
- the production onset-tension exponential;
- one-zero damping magnitude and phase delay;
- the production dispersion pole mapping and delay-budget shrink;
- two dispersion allpasses;
- the fractional-delay allpass solved at the fundamental;
- T60 loop-gain calibration;
- integer delay changes at a configurable update stride;
- physical triangular excitation.

It omits body modes, sympathetic strings, detuned courses, contact, Weave scattering, the master chain, and a final physical metric over every internal state. The active delay segment uses a declared Euclidean research metric. Results from this model therefore characterize state-transition policies; they do not replace the production bend experiment.

Three policies were compared:

- **Legacy:** coefficient and integer-read-tap updates with stored state unchanged.
- **NeutralFilters:** exact neutral transport for allpass state; integer delay reinterpretation remains legacy.
- **NeutralRemap:** neutral allpass transport plus state-contingent periodic remapping of the active delay segment.

The sweep contains 72 control configurations and 216 policy rows:

```text
f0:             82.4069, 110, 220, 440 Hz
pitch ratio:    2/3, 3/2, 2
stiffness:      0, 0.75
update stride:  1, 16, 64 samples
sample rate:    12 kHz
```

A canonical 48 kHz upward-fifth case is also retained.

## 6. Results

### 6.1 Full sweep

| Quantity | Legacy | Neutral filters | Neutral remap |
|---|---:|---:|---:|
| maximum active-line work at one update | `0.709790` | `0.709795` | `1.07e-14` |
| maximum allpass work at one update | `0.374991` | `1.39e-16` | `1.67e-16` |
| maximum proxy-energy ratio | `1.038514` | `1.034754` | `1.003079` |
| worst output correlation to legacy | `1.0` | `0.983412` | `0.471193` |
| median output correlation to legacy | `1.0` | `0.996414` | `0.822820` |
| all states finite | yes | yes | yes |

Two findings are load-bearing.

**First, exact neutral allpass transport is ready for a production trial.** It reduces measured coefficient-update work to roundoff while retaining very high waveform continuity over the complete sweep. The minimum correlation to the legacy reference is `0.983412`; the median is `0.996414`. This does not prove perceptual transparency, but it is strong enough to justify an explicit `neutral_filters` production mode behind a legacy comparison.

**Second, the scalar-normalized line remap is not ready for production.** It closes the declared update ledger and greatly limits proxy-energy excursions, but large low-register upward octave changes produce correlations as low as `0.471193`. Energy closure has been purchased with too much phase/state distortion. This candidate remains useful as an oracle control and as evidence that scalar normalization alone is not the right final state transport.

### 6.2 Canonical 48 kHz upward fifth

| Quantity | Legacy | Neutral filters | Neutral remap |
|---|---:|---:|---:|
| sum of absolute active-line update work | `2.03682549` | `2.07483139` | `5.88e-13` |
| sum of absolute allpass update work | `4.01597283` | `2.01e-15` | `2.30e-15` |
| correlation to legacy output | `1.0` | `0.99648376` | `0.85608516` |

The exact allpass repair removes essentially all filter-state reinterpretation while leaving the active-line problem visible. That decomposition is more informative than applying one monolithic normalization and observing only the final peak.

The proxy-energy maximum for this isolated case is `1.0` under all three policies. The reference model therefore does **not** reproduce the production 3.24-to-5.38 output-peak transient. This is a meaningful boundary, not a failed experiment. It implies that the production phenomenon depends on stages absent from this reference, on a different state metric, on output interference, or on some combination. The next production instrumentation must locate it rather than assuming that the isolated delay line explains the whole 66% peak change.

## 7. Scientific decision

### Accept for production trial

**Exact neutral allpass state transport.** Integrate it first behind an explicit mode such as

```text
retune=legacy
retune=neutral_filters
```

and retain byte identity for static/no-op updates. Instrument the production renderer so each coefficient change reports old/new storage, control work, and cumulative absolute work.

### Retain as research control, do not ship as neutral retuning

**State-contingent scalar-normalized active-line remapping.** It is useful because it closes a declared scalar ledger and exposes the difference between energy and state fidelity. It should not be called the final neutral transport, a polar correction, or physical string mechanics.

### Build next

1. Declare a physically or discretization-consistent metric for delay cells as length and cell count change. In particular, decide whether per-cell energy weights scale with spatial step rather than using an unweighted sum.
2. Construct the dense weighted remapping operator and its polar partial isometry as the float64 oracle.
3. Compare two real-time candidates against that oracle:
   - fixed-capacity material coordinates;
   - variable-rank remap factored into sparse or low-rank stages.
4. Measure tuning, sidebands, attack continuity, state correlation, control work, CPU, and repeated-cycle drift independently.
5. Instrument the actual production string/body/Weave state, because the isolated model does not explain the full measured peak transient.
6. Only after the delay transport is selected, expose the complete production mode as `retune=neutral`.

## 8. Consequences for the paper

The next paper version can now make four additional, defensible statements.

1. The first-order allpass used by the production string has an exact quadratic storage function and an exact neutral coefficient-state transport.
2. In a production-shaped binary64 sweep, that transport eliminates coefficient-update work to roundoff while preserving output correlation above `0.983` relative to legacy.
3. A state-contingent scalar energy correction can close the active-line ledger but fails a waveform-fidelity gate, demonstrating experimentally that scalar energy conservation does not determine an acceptable state correspondence.
4. The isolated changing-delay reference does not reproduce the full production peak transient, so the paper's next empirical target remains internal instrumentation of the complete production network rather than retroactively attributing the transient to one stage.

These results materially strengthen the paper because they convert the proposed implementation sequence into a falsifiable ladder. One local repair passed. One whole-line shortcut failed. The remaining scientific object is now sharply defined: a globally linear or otherwise explicitly physical delay-state correspondence that closes the work ledger without erasing musically relevant phase and state structure.

## 9. Verification

The green workflow performs:

```text
cargo fmt --all -- --check
cargo test -p mus-watsn --all-targets
cargo clippy -p mus-watsn --all-targets -- -D warnings
cargo run -p mus-watsn --example next_phase --release
cargo run -p mus-watsn --example string_retune --release
fail-loud Python assertions
artifact upload
```

The crate currently has 15 passing unit tests. Generated compact receipts are committed under `.string-research/next-phase/`; the complete CSV sweeps and summaries are retained in the workflow artifact.

## 10. Bottom line

The next phase is no longer merely a proposal to “make bends passive.” We now know that the production retuning problem contains at least two separable state transports:

- allpass filter memory, for which an exact, low-cost, nearly transparent neutral map is available now;
- active delay state, for which scalar energy normalization is mathematically honest but musically inadequate.

That is real progress. It identifies the first production patch, rules out a tempting shortcut, and leaves the paper with a much more precise next theorem and experiment: construct and audition a metric-consistent delay-state connection, then locate the remaining work in the complete instrument–body–space network.
