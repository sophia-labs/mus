# Exact and numerical results for the Ariadne preprint

This file is a compact durable receipt.  It separates exact identities from
floating-point verification and production measurements.

## 1. Exact three-mode commutator

Let

```text
A = R01(a)
B = R12(b)
C(a,b) = A B A^(-1) B^(-1)
x = sin(a/2)^2
y = sin(b/2)^2.
```

Direct symbolic matrix multiplication gives

```text
trace C = (4xy - 3)(4xy - 1).
```

The squared Ariadne order defect is

```text
delta^2
  = ||R12(b)R01(a) - R01(a)R12(b)||_2^2
  = 16xy(1 - xy).
```

Since `C` is in `SO(3)` and `trace C = 1 + 2 cos(phi)`, its principal rotation
angle satisfies

```text
sin(phi/2)^2 = 4xy(1 - xy),
delta = 2 sin(phi/2).
```

A unit quaternion representative has

```text
w = 1 - 2xy
v = (-x sin b, (sin a sin b)/2, y sin a).
```

For small controls in a fixed quadrant,

```text
phi = |ab| [
  1 - (a^2+b^2)/24
    + (3a^4 + 70a^2b^2 + 3b^4)/5760
    + higher-order terms
].
```

For a balanced loop `a=b=t`, the principal-branch inverse design law is

```text
t(phi) = 2 asin(sqrt(sin(phi/4))),  0 <= phi <= pi.
```

At `a=0.31`, `b=-0.47`:

```text
phi   = 0.14381627598663013 rad
      = 8.240065639322555 degrees
delta = 0.14369236763143287
trace = 2.9793525034844732
axis  = (0.1502339534, -0.9614767643, 0.2302003279).
```

## 2. Float64 reference verification

The deterministic reference suite used seed `0xA11AD0E` and checked:

```text
order-defect identity                8.881784197001252e-16
commutator-angle identity            4.440892098500626e-16
defect/chord identity                9.992007221626409e-16
sixth-order small-loop expansion     7.907986709909665e-09
weighted metric isometry             8.714573669793700e-15
polar reconstruction                 1.311190769628567e-14
work identity                        2.074784788419493e-12
nine-step path ledger closure        3.552713678800501e-14
rank-contraction energy partition    1.332267629550188e-15
rank-expansion isometry              4.357045651032218e-15
balanced inverse formula vs root     2.297051437949449e-13 rad.
```

The sweep included 800 weighted full-rank transports in dimensions 2--8, 250
random nine-step paths, 300 rank-change trials, and 100,000 unit-state
directions for the factor-order experiment.

## 3. Four closed-loop regimes

For a fixed reference state, the four constructed loops were:

```text
null:           work 0;          turn 0 degrees
pure holonomy:  work -1.11e-16;  turn 8.240065639 degrees
pure work:      work 0.1033095;   turn 3.37e-15 degrees
mixed:          work 0.1033095;   turn 7.405677001 degrees.
```

Using the same preserving turn `U` and anisotropic positive factor `H` in the
opposite order at state `(1,0,0)` gave

```text
W(UH) =  0.780
W(HU) = -0.255
difference = 1.035.
```

Across 100,000 approximately uniform unit vectors, the work-difference RMS was
`0.5337436728` and maximum absolute difference `1.0349869261`.  The population
mean is exactly zero by trace invariance, so the result is directional rather
than a global gain bias.

## 4. Coupled instrument--body--space surrogate

The reference medium used six resonators, each represented by position and
momentum coordinates:

```text
instrument: 220 and 329.63 Hz
body:       98 and 186 Hz
space:      31 and 47 Hz.
```

Body and room scale followed one closed two-second control path.  Under the
metric-compatible transport

```text
T_n = M_(n+1)^(-1/2) M_n^(1/2),
```

the measured bounds were

```text
maximum absolute step control work   5.551115123125783e-17
maximum ledger closure residual      5.551115123125783e-16
peak space energy fraction           0.2540208368495552.
```

Keeping physical coordinates fixed instead of transporting them neutrally
produced a cumulative control-work term and changed the pickup waveform by
approximately 2.80% RMS relative to the neutral policy.  This is an audible
modal surrogate, not evidence that a production room model has been completed.

## 5. Production implementation measurements inherited by the paper

The existing Rust branch reports:

```text
settled tuning, E2--E6:              within 8 cents
chirality contrast relative RMS:     0.713
chirality loudness difference:       within 0.7 dB
chirality centroid difference:       within 1.4%
unbent extreme peak:                 3.24
upward-fifth extreme bend peak:      5.38
workspace tests:                     216 green across 32 suites.
```

These measurements motivate the theory but do not establish the proposed
neutral-retuning or full instrument--space contracts.
