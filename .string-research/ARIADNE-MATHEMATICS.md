# Ariadne mathematics

This note states the mathematics the current Weave draft actually implements, the stronger mathematics it gestures toward, and the exact boundary between the two. The implementation agent should treat it as the claim ledger.

## 1. State-space view

A useful abstract form of one unforced sample of Ariadne is

\[
x_{n+1}=D_n P_n Q_n(x_n;\lambda_n)x_n,
\]

and with excitation,

\[
x_{n+1}=D_n P_n Q_n(x_n;\lambda_n)x_n+B_nu_n.
\]

Here:

- \(x_n\) is the complete stored state: string delay memories, allpass and damping states, and body-mode coordinates;
- \(Q_n\) is the instantaneous scattering/coupling operation;
- \(P_n\) is propagation through delay, damping-phase, and dispersion state;
- \(D_n\) is explicit loss;
- \(u_n\) is the finite pluck/contact excitation;
- \(\lambda_n\) is the control point: coupling, chirality, orbit phase, curvature, body amount, bend, and so on.

The implementation does not construct these as literal dense matrices. This factorization is the mathematical interpretation of the sample loop.

## 2. Pointwise orthogonal scattering

A real Givens rotation on coordinates \(i,j\) is the identity except for

\[
R_{ij}(\theta)_{ij}=\begin{bmatrix}
\cos\theta&-\sin\theta\\
\sin\theta&\cos\theta
\end{bmatrix}.
\]

Therefore

\[
R_{ij}(\theta)^TR_{ij}(\theta)=I
\]

and every finite product of such rotations is orthogonal.

Weave lets the angle depend on time and state:

\[
\theta_{ij,n}=c\,m_{ij}(x_n)\left[1+d\sin(\Omega n+\phi_i)\right].
\]

The resulting mapping \(F(x)=Q(x)x\) is generally nonlinear because the matrix depends on the vector. It is nevertheless **pointwise norm-preserving**:

\[
\|F(x)\|_2^2=x^TQ(x)^TQ(x)x=\|x\|_2^2.
\]

No derivative or linearization is needed for that statement. It does **not** imply that distances between two different states are preserved, nor that the full delayed system is passive.

## 3. Contractive ordered-scattering theorem

The clean theorem Ariadne is aiming at is elementary but useful.

Let \(Q_n(x)\) be pointwise orthogonal, let \(P_n\) be an isometry in the declared state norm, and let the loss operator satisfy

\[
\|D_n\|\leq\rho_n<1.
\]

Then the unforced system obeys

\[
\|x_{n+1}\|\leq\rho_n\|x_n\|
\]

and hence

\[
\|x_N\|\leq\left(\prod_{n=0}^{N-1}\rho_n\right)\|x_0\|.
\]

If \(\rho_n\leq\rho<1\) uniformly, then

\[
\|x_N\|\leq\rho^N\|x_0\|.
\]

This is the analytic version of the quantized skeleton already proved in `formal/MusFormal/Holonomy.lean`: energy-preserving junctions cannot undo a strictly lossy edge.

### What is not proved yet

The current Rust draft satisfies the local orthogonal-scattering premise. It does not yet establish that its **time-varying propagation** \(P_n\) is an isometry. Changing the effective delay length or allpass coefficient can perform numerical work on the state. Bends and onset-tension relaxation therefore sit outside the current whole-network proof.

Until that is repaired, the honest statement is:

> The scattering stage is exactly lossless up to floating-point error; the complete modulated network is designed to be contractive and is tested for boundedness over a declared control domain.

## 4. The physical energy metric

Euclidean norm represents physical energy only when every coordinate has been impedance-normalized. In general,

\[
E(x)=\tfrac12x^TMx,
\]

where \(M\) is symmetric positive definite.

The correct lossless condition is then

\[
Q^TMQ=M.
\]

There are two implementation routes.

### Normalized coordinates

Choose \(M=L^TL\), store \(z=Lx\), perform ordinary orthogonal scattering \(R\) in \(z\), and map back:

\[
Q=L^{-1}RL.
\]

Then \(Q^TMQ=M\) by construction.

### Direct weighted two-coordinate rotation

For coordinates with positive energy weights \(m_i,m_j\), normalize the pair

\[
(\sqrt{m_i}x_i,\sqrt{m_j}x_j),
\]

apply a Givens rotation, then divide by the square roots. This is cheap enough for the current sparse nearest-neighbour network.

The body-mode coordinates in the draft should either be declared already normalized or upgraded to this weighted construction before the word “energy” is used physically.

## 5. Noncommutativity and the exact local path defect

Consider two overlapping rotations in three coordinates:

\[
U=R_{12}(b)R_{01}(a),\qquad
V=R_{01}(a)R_{12}(b).
\]

They share coordinate 1 and generally do not commute. Define the local order defect

\[
\delta(a,b)=\|U-V\|_2.
\]

For this three-dimensional pair, the draft implements the closed form

\[
\boxed{
\delta(a,b)=\sqrt{
(\cos a-1)^2\sin^2b+
(\cos b-1)^2\sin^2a+
\sin^2a\sin^2b
}}
}
\]

The code derives it as \(\|U-V\|_F/\sqrt2\). Because \(U,V\in SO(3)\), their relative transform is a three-dimensional rotation: the two nonzero singular values of \(U-V\) are equal. Consequently

\[
\|U-V\|_2=\frac{\|U-V\|_F}{\sqrt2},
\]

so the implemented value is not merely a convenient scalar; it is the exact worst-case state displacement per unit input norm caused by swapping the two local operations.

Thus, for all states,

\[
\|(U-V)x\|_2\leq\delta(a,b)\|x\|_2,
\]

and some state attains equality.

For small angles,

\[
\delta(a,b)=|ab|+O\!\left(|ab|(a^2+b^2)\right).
\]

This supplies a useful instrument-design law: weak adjacent couplings produce order memory quadratically in their control amplitudes, while stronger couplings can make the path distinction first-class and audible.

## 6. Discrete control holonomy

For a control path \(\gamma=(\lambda_0,\ldots,\lambda_{T-1})\), define the path-ordered scattering product

\[
W[\gamma]=Q(\lambda_{T-1})\cdots Q(\lambda_1)Q(\lambda_0).
\]

Two paths may end at the same control point and still satisfy

\[
W[\gamma_1]\neq W[\gamma_2].
\]

A state-independent path-memory distance is

\[
H_2(\gamma_1,\gamma_2)=\|W[\gamma_1]-W[\gamma_2]\|_2.
\]

A state- and pickup-specific audible distance is

\[
H_C(\gamma_1,\gamma_2;x)=
\frac{\|C(W[\gamma_1]-W[\gamma_2])x\|_2}
{\|Cx\|_2+\varepsilon},
\]

where \(C\) is the radiation/pickup map.

These definitions are already enough to justify **ordered-scattering path memory**. They also give the experiment agent something to measure.

### What would make it geometric holonomy

A stronger Berry/Wilczek–Zee analogy needs all of the following:

1. a control cycle with \(\lambda_T=\lambda_0\);
2. a continuously identified modal subspace transported around that cycle;
3. a connection or discrete parallel-transport rule;
4. an observable invariant under basis changes inside that subspace, such as conjugacy class, eigenvalues, or a Wilson-loop trace;
5. preferably an adiabatic regime separating the transported subspace from the rest of the spectrum.

The current code has noncommuting path ordering but not this full structure. That is a promising research program, not a completed theorem.

## 7. Loss, damping, and T60

For the one-zero loop filter

\[
H_d(z)=(1-d)+dz^{-1},
\]

its fundamental response at \(\omega_0\) is

\[
|H_d(e^{j\omega_0})|
=\sqrt{(1-d+d\cos\omega_0)^2+(d\sin\omega_0)^2}.
\]

If a string circulates approximately \(f_0\) times per second, the desired per-circulation amplitude gain for a T60 of \(T\) seconds is

\[
g_{60}=10^{-3/(Tf_0)}.
\]

The draft sets

\[
g=\min\left(\frac{g_{60}}{|H_d(e^{j\omega_0})|},\,1-\epsilon\right).
\]

This makes the fundamental T60 correct when the required compensation remains contractive. At dark settings, the requested compensation may exceed one and the clamp wins; the actual T60 is then shorter than requested.

A production solution should design a frequency-dependent loss filter under explicit constraints:

\[
|G(e^{j\omega_0})|=g_{60},\qquad
\sup_\omega|G(e^{j\omega})|\leq1-\epsilon,
\]

while optimizing the desired spectral decay slope. The UI may then distinguish `fundamental_t60` from `brightness_decay` without promising an impossible pair.

## 8. Dispersion and exact fundamental phase budget

A stiff string has inharmonic partials. The draft introduces two first-order allpasses into the loop and recalculates the residual fractional delay so the total phase delay at the fundamental remains

\[
\tau_{\mathrm{loop}}(\omega_0)=\frac{f_s}{f_0}.
\]

For first-order allpass

\[
A(z)=\frac{a+z^{-1}}{1+az^{-1}},
\]

its magnitude is one and its phase delay is frequency-dependent. The draft computes the phase delay at \(\omega_0\), subtracts it and the damping-filter phase delay from the delay budget, and solves the final fractional allpass coefficient exactly at \(\omega_0\).

This is a stronger tuning method than assigning an integer delay plus a DC fractional-delay approximation. The remaining questions are perceptual calibration of `stiff`, stability while coefficients move, and whether a higher-order dispersion design gives a more guitar-like inharmonicity curve.

## 9. Onset tension modulation

The draft uses

\[
f(t)=f_{\mathrm{nom}}(t)\,2^{c(t)/1200},
\qquad
c(t)=c_0e^{-t/\tau_c}.
\]

It ties \(\tau_c\) heuristically to the squared-amplitude decay. If amplitude reaches \(10^{-3}\) at T60 \(T\), squared amplitude reaches \(10^{-6}\), suggesting

\[
\tau_c\approx\frac{T}{6\ln10}.
\]

This is musically plausible and literature-aligned as a tension-modulation control, but it is not yet derived from string elongation, Young’s modulus, speaking length, and displacement. A calibrated guitar model should expose a physical or at least dimensionally interpretable parameterization beneath the perceptual `tension` macro.

## 10. Contractive contact and exact radiation

The current contact map produces a feedback value \(F(y)\) satisfying

\[
|F(y)|\leq|y|.
\]

That is enough for a scalar non-expansive feedback contact. The current radiated contact signal is based on the amplitude removed, \(y-F(y)\). It is not exact energy bookkeeping.

If exact scalar energy accounting is desired, define removed energy

\[
\Delta E=\max(y^2-F(y)^2,0)
\]

and a radiation coordinate

\[
r=\operatorname{sgn}(y-F(y))\sqrt{\eta\Delta E},\qquad0\leq\eta\leq1.
\]

The residual \((1-\eta)\Delta E\) is heat/loss. A multidimensional physical contact should instead use a passive potential or collision scheme.

## 11. Spectral dimension as an instrument coordinate

Suppose a mode-counting law has the form

\[
N(\omega)\sim C\omega^{d_s}.
\]

Inverting it gives

\[
\omega_k\sim\left(\frac{k}{C}\right)^{1/d_s}.
\]

The draft uses this relation to create virtual-course fundamentals:

\[
f_k=f_{\mathrm{base}}(k+k_0)^{1/d_s},
\]

then octave-folds ratios into a four-octave window. This gives a structured continuum between compressed and expanded inharmonic spectra.

The octave fold is a musical intervention, not spectral geometry. It can create duplicate or near-duplicate courses and destroys monotone counting. Three progressively stronger implementations are available:

1. **Current scaffold:** power-law frequencies with folding.
2. **Collision-aware scaffold:** power-law frequencies projected into range by constrained optimization that preserves spacing.
3. **Operator-derived instrument:** construct a graph, fractal string, or weighted Laplacian; use its eigenvalues as modal frequencies and its eigenvectors to define excitation, coupling, and radiation.

Only the third gives `dimension` an endogenous relationship to the network topology.

## 12. A proposed Ariadne audibility functional

Ariadne should not optimize mathematical difference that cannot be heard. Let \(y_1,y_2\) be renders from two equal-endpoint control paths. Define a perceptually weighted transform \(\Phi\), for example ERB-band envelopes plus instantaneous pitch and modulation features. Then

\[
\mathcal A(\gamma_1,\gamma_2)
=\frac{\|\Phi(y_1)-\Phi(y_2)\|_W}
{\tfrac12(\|\Phi(y_1)\|_W+\|\Phi(y_2)\|_W)+\varepsilon}.
\]

The research task is to find control cycles that maximize \(\mathcal A\) subject to:

- identical initial score and final control point;
- bounded peak and loudness difference;
- comparable global spectral centroid;
- no clipping or instability;
- listener identification above chance.

That would turn “path memory” from a visual matrix fact into a measured musical capability.

## 13. Formalization backlog

The existing pure-core Lean theorem is a useful skeleton. The next formal package should separate exact mathematics from floating-point conformance.

### Exact layer

1. `givens_preserves_norm`.
2. `product_orthogonal`.
3. `state_dependent_pointwise_preserves`.
4. weighted-coordinate preservation, `QᵀMQ=M`.
5. contractive-product bound.
6. exact overlapping-rotation defect formula.
7. `defect_zero_iff` for the relevant angle domain.
8. small-angle asymptotic bound.
9. a discrete path-product definition and conjugacy-invariant cyclic observable.

### Numerical conformance layer

1. f64 energy drift after long Givens products.
2. f32 output boundedness.
3. block-size identity.
4. coefficient-update continuity.
5. measured propagation-energy change during delay modulation.
6. end-to-end decay envelope under no excitation.

The law remains: **Lean proves the declared model; Rust tests police the implemented bytes.** Neither substitutes for listening.

## 14. Claim table

| Claim | Current status |
|---|---|
| Individual Givens scattering preserves Euclidean norm | proved algebraically; tested numerically |
| State-dependent Givens scattering is pointwise norm-preserving | proved algebraically; tested numerically |
| Overlapping ordered rotations produce path-dependent state | exact closed form plus test |
| Implemented defect equals worst-case local state displacement | follows from the SO(3) relative-rotation argument; should be formalized |
| Fixed-delay network with strict loss is contractive | standard theorem; quantized Lean skeleton exists |
| Entire current modulated Rust network is passive | **not established** because delay/filter retuning is time-varying and energy coordinates are not fully normalized |
| `dimension` is the spectral dimension of the implemented topology | **not established**; it is a Weyl-inspired frequency scaffold |
| Current ordered scattering is a non-Abelian geometric phase | **not established**; it is algebraic noncommutativity/path ordering |
| Guitar body is a measured physical guitar | false; current modes are exploratory design values |
| Ariadne is musically novel | plausible research hypothesis; requires prior-art search and listening evidence |
