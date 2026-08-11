# Next-phase result: exact allpass transport and the limits of scalar-neutral delay remapping

This note is the paper-facing durable result of the first production-shaped retuning experiments on `agent/ariadne-next-phase`. It is intended to become a new Results subsection and to refine the immediate-experiments discussion.

## Exact local result

For the production first-order allpass

```text
y  = a*u + x1 - a*y1
x1' = u
y1' = y,
```

define

```text
s = x1 - a*y1.
```

Then

```text
y  = a*u + s
s' = (1-a^2)u - a*s
```

and

```text
u^2 + s^2/(1-a^2) = y^2 + s'^2/(1-a^2).
```

The section therefore has declared storage

```text
E_a(s) = 1/2 * s^2/(1-a^2).
```

A coefficient change `a0 -> a1` is energy-neutral when it preserves the normalized storage coordinate:

```text
s1 / sqrt(1-a1^2) = s0 / sqrt(1-a0^2).
```

Equivalently,

```text
s1 = s0 * sqrt((1-a1^2)/(1-a0^2)).
```

Retaining `y1` and reconstructing `x1 = s1 + a1*y1` gives an exact state transport for this realization. Across the deterministic coefficient/state sweep, maximum absolute control work was `1.776e-15`; retaining implementation state unchanged produced absolute work as large as `9.386` on the adversarial grid.

## Production-shaped reference experiment

A binary64 one-string reference mirrors the production update law for bend interpolation, damping phase, dispersion-budget reduction, two dispersion allpasses, fractional-delay phase compensation, and T60 loop gain. It compares:

- `legacy`: update coefficients and the integer read distance without transporting state;
- `neutral_filters`: apply the exact allpass transport but retain the legacy active-line update;
- `neutral_remap`: additionally resample the active periodic delay segment and apply a state-contingent scalar correction so its declared Euclidean energy is unchanged.

The 72-configuration sweep spans four fundamentals, downward and upward pitch paths, two stiffness values, and three control-update cadences. All 216 policy runs remained finite.

| Observable | Legacy | Neutral filters | Neutral remap |
|---|---:|---:|---:|
| maximum one-update line work | `0.709790` | `0.709795` | `1.07e-14` |
| maximum one-update allpass work | `0.374991` | `1.39e-16` | `1.67e-16` |
| maximum proxy-energy ratio | `1.038514` | `1.034754` | `1.003079` |
| minimum output correlation to legacy | `1.0` | `0.983412` | `0.471193` |
| median output correlation to legacy | `1.0` | `0.996414` | `0.822820` |

The exact filter transport therefore passes the first production-trial gate: it closes the section's declared storage law while remaining close to the existing sound. The scalar-normalized line remap does not. It closes a state-contingent scalar ledger but changes the output strongly for large low-register rank changes. This is direct evidence that energy preservation alone does not specify a musically acceptable state correspondence.

## Canonical upward-fifth case

At 48 kHz, 110 -> 165 Hz:

| Observable | Legacy | Neutral filters | Neutral remap |
|---|---:|---:|---:|
| sum absolute line work | `2.03682549` | `2.07483139` | `5.88e-13` |
| sum absolute filter work | `4.01597283` | `2.01e-15` | `2.30e-15` |
| output correlation to legacy | `1.0` | `0.99648376` | `0.85608516` |

The isolated proxy-energy ratio remains `1.0` for all three policies. The model therefore does not reproduce the production renderer's 3.24-to-5.38 peak transient. The result narrows rather than closes the investigation: filter-state reinterpretation is exactly repairable, but the complete transient must be located in the production union of delay state, multiple courses, body, scattering, contact, and pickup interference.

## Claim boundary

The periodic line candidate uses

```text
scale = sqrt(E_before/E_raw_after)
```

after interpolation. This is nonlinear and state-contingent. It is not the weighted polar factor of a linear remapping operator, a physical moving-boundary model, or a proof that unweighted per-cell Euclidean energy is the correct metric under changing rank. It should remain a research control.

The next strong result is now sharply specified:

1. declare a consistent metric for a changing delay discretization;
2. construct the dense weighted polar/partial-isometry oracle;
3. approximate it with either fixed-capacity material coordinates or sparse variable-rank transport;
4. compare energy closure and state fidelity separately;
5. instrument the complete production network before making a claim about the origin of its measured peak transient.

## Proposed manuscript insertion

The paper should add a Results subsection titled **“Exact filter-state transport and a failed scalar-neutral delay shortcut.”** The subsection should emphasize that one local state transport passed both the energy and continuity gates, while one whole-line shortcut passed only the energy gate. This negative result materially supports the paper's argument that a metric does not by itself choose a connection: preserving one scalar storage value is weaker than preserving the musically relevant orientation of live acoustic state.
