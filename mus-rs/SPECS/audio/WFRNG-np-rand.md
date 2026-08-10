# WFRNG — numpy-compatible RNG (`crates/np-rand`)

Make `np.random.default_rng(seed)` reproducible in Rust, bit-faithfully.
The render face needs exactly one consumer — `make_ir`'s
`default_rng(7).standard_normal((2, n))` — but the crate is designed
standalone (no deps) because numpy-stream compatibility is a recurring gap
when porting scientific Python.

Three layers; the crate's lib.rs doc comment describes them. All oracle
vectors are already dumped in `mus-rs/fixtures/dsp/`:

1. **SeedSequence** — numpy's entropy-mixing pool. Port from numpy's
   `_bit_generator` implementation (numpy source `numpy/random/
   bit_generator.pyx`, or its rendered C — the algorithm: 4-word uint32
   entropy pool, `hashmix` with constants `INIT_A = 0x43b0d7e5`,
   `MULT_A = 0x931e8875`, `INIT_B = 0x8b51f9dd`, `MULT_B = 0x58f38ded`,
   `MIX_MULT_L = 0xca01f9dd`, `MIX_MULT_R = 0x4973f715`, `XSHIFT = 16`,
   cycle-through pool mixing, then `generate_state` drawing uint32 pairs →
   uint64 words). Verify: `seedseq_7_state.json` — `SeedSequence(7).
   generate_state(8, uint64)`.
2. **PCG64** — numpy's default BitGenerator: PCG XSL-RR 128/64. 128-bit
   LCG, multiplier `0x2360ed051fc65da44385df649fccf645`; state and
   increment seeded from SeedSequence (4 uint64 words: 2 for state, 2 for
   inc — read numpy's `pcg64_set_seed`: `state = seed_words`, `inc =
   (inc_words << 1) | 1` composition). Output: `XSL-RR` — xor-shift-low,
   random rotate. Verify: `pcg64_7_raw.json` — `PCG64(7).random_raw(64)`.
3. **`standard_normal` (f64)** — numpy Generator's ziggurat
   (`random_standard_normal` in numpy's `distributions.c`): draw uint64
   `r`; `idx = r & 0xff`; `sign = (r >> 8) & 1`; `rabs = (r >> 9) &
   0x000fffffffffffff`; `x = rabs * wi_double[idx]`; accept if `rabs <
   ki_double[idx]`; idx==0 → tail via `-log(random_double)` loop; else
   wedge test with `fi_double` tables and a fresh uniform. The 256-entry
   `ki_double`/`wi_double`/`fi_double` tables come from numpy's
   `ziggurat_constants.h` — transcribe them or regenerate via the
   documented ziggurat construction (r = 3.6541528853610088,
   v = 0.00492867323399); either way the fixtures arbitrate.
   `random_double` = next_uint64 >> 11 × 2⁻⁵³. Verify:
   `standard_normal_64` and `standard_normal_2x32` (`max_abs 1e-12` f64 —
   bit-faithful in practice; row-major fill order for shaped output).

**API sketch:** `SeedSequence::new(u64)` + `generate_state(n) -> Vec<u64>`;
`Pcg64::from_seed_sequence(&mut SeedSequence)` (matching
`default_rng(seed)`'s seeding path exactly) + `next_u64`;
`Pcg64::standard_normal(&mut self) -> f64` + a helper
`standard_normal_vec(&mut self, n)`.

**Tests:** golden against all four oracle files (parse the two JSON hex
files with a tiny hand parser or serde — if serde, add it as a
dev-dependency only, keep the lib dependency-free); a shaped-order test
proving `standard_normal_2x32` equals the first 64 draws reshaped
row-major.

**Fallback if bit-fidelity stalls:** do NOT ship an approximation. Report
which layer diverges and at which draw index; the leg falls back to
loading `make_ir_*` fixtures as assets. An RNG that is almost numpy is
worse than none.

**DoD:** builds; `cargo test -p np-rand` green; fmt clean; tests in diff.
