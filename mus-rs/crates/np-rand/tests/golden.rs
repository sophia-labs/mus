//! Golden tests for `np-rand`, resolved directly against
//! `mus-rs/fixtures/dsp/`: the two RNG-specific JSON fixtures
//! (`seedseq_7_state.json`, `pcg64_7_raw.json`) plus the `standard_normal_*`
//! cases in `manifest.json`. This is the RNG-layer analogue of
//! `mus-dsp/tests/golden_kernels.rs` and `mus-dsp/src/fixtures.rs`, but
//! hand-rolled rather than reusing that harness: `np-rand` is deliberately
//! dependency-free (see the crate's module doc), and depending on
//! `mus-dsp` from `np-rand`'s own tests would invert the crate graph
//! (`mus-dsp` depends on `np-rand`, never the reverse). Tolerances still
//! come from the manifest, never a literal in this file.

use np_rand::{Pcg64, SeedSequence};
use std::fs;
use std::path::{Path, PathBuf};

fn fixtures_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/dsp")
}

/// Every `"0x..."` hex token inside the named JSON array field
/// (`seedseq_7_state.json`'s `"state"`, `pcg64_7_raw.json`'s `"raw"`) —
/// a tiny hand parser standing in for a `serde_json` dev-dependency.
fn parse_hex_array(path: &Path, key: &str) -> Vec<u64> {
    let text = fs::read_to_string(path)
        .unwrap_or_else(|e| panic!("read {}: {e} — run gen_dsp_fixtures.py", path.display()));
    let key_pat = format!("\"{key}\"");
    let after_key = text
        .find(&key_pat)
        .unwrap_or_else(|| panic!("{}: no {key_pat} field", path.display()));
    let array_start = after_key
        + text[after_key..]
            .find('[')
            .expect("array open bracket after key")
        + 1;
    let array_end = array_start + text[array_start..].find(']').expect("array close bracket");
    text[array_start..array_end]
        .split(',')
        .filter_map(|tok| {
            let tok = tok.trim().trim_matches('"');
            if tok.is_empty() {
                return None;
            }
            Some(
                u64::from_str_radix(tok.trim_start_matches("0x"), 16)
                    .unwrap_or_else(|e| panic!("{}: bad hex token {tok:?}: {e}", path.display())),
            )
        })
        .collect()
}

/// A little-endian `<f8` binary fixture (raw `float64` bytes) as a `Vec<f64>`.
fn read_f64_bin(path: &Path) -> Vec<f64> {
    let bytes = fs::read(path)
        .unwrap_or_else(|e| panic!("read {}: {e} — run gen_dsp_fixtures.py", path.display()));
    bytes
        .chunks_exact(8)
        .map(|c| f64::from_le_bytes(c.try_into().unwrap()))
        .collect()
}

/// The manifest `tol` for the named case, found by string search — the
/// tolerance still lives in the manifest, this just avoids pulling in
/// `serde_json` to read one field of it.
fn manifest_tol(case_name: &str) -> f64 {
    let path = fixtures_dir().join("manifest.json");
    let text = fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("read {}: {e} — run gen_dsp_fixtures.py", path.display()));
    let name_pat = format!("\"name\": \"{case_name}\"");
    let case_start = text
        .find(&name_pat)
        .unwrap_or_else(|| panic!("no fixture case named {case_name:?} in manifest.json"));
    let tol_key_end = case_start
        + text[case_start..]
            .find("\"tol\":")
            .expect("case has a tol field")
        + "\"tol\":".len();
    let tol_end = tol_key_end
        + text[tol_key_end..]
            .find([',', '\n', '}'])
            .expect("tol value terminator");
    text[tol_key_end..tol_end]
        .trim()
        .parse()
        .unwrap_or_else(|e| panic!("{case_name}: bad tol value: {e}"))
}

#[test]
fn seedseq_7_state() {
    // Oracle: `numpy.random.SeedSequence(7).generate_state(8, np.uint64)`.
    let expected = parse_hex_array(&fixtures_dir().join("seedseq_7_state.json"), "state");
    assert_eq!(expected.len(), 8, "fixture shape sanity");
    let got = SeedSequence::new(7).generate_state(8);
    assert_eq!(got, expected, "SeedSequence(7).generate_state(8, uint64)");
}

#[test]
fn pcg64_7_raw() {
    // Oracle: `numpy.random.PCG64(7).random_raw(64)`.
    let expected = parse_hex_array(&fixtures_dir().join("pcg64_7_raw.json"), "raw");
    assert_eq!(expected.len(), 64, "fixture shape sanity");
    let mut pcg = Pcg64::seeded(7);
    let got: Vec<u64> = (0..64).map(|_| pcg.next_u64()).collect();
    assert_eq!(got, expected, "PCG64(7).random_raw(64)");
}

/// Shared body for the two `standard_normal_*` cases: both dump
/// `default_rng(7).standard_normal(...)` — one flat, one `(2, 32)` — from
/// the *same* 64-draw stream, so both are checked the same way against
/// `np-rand`'s own stream-order output.
///
/// Two checks, deliberately layered rather than one replacing the other:
/// a `max_abs`-vs-manifest-`tol` check (the house convention — the
/// tolerance itself always comes from the manifest, never a literal
/// here), *and* a strictly stronger exact `to_bits` equality per draw.
/// The tolerance check alone previously passed against tables that were
/// provably wrong (see `ziggurat_tables`'s module doc): `KI_DOUBLE`/
/// `WI_DOUBLE` entries off by a handful of ULPs produced errors under
/// `1e-12` on this particular 64-draw stream, comfortably inside the
/// manifest tolerance, so `max_abs` alone never caught it. `to_bits`
/// equality has no slack to hide behind — this is `np-rand`'s
/// `standard_normal (f64)` layer declared bit-faithful "in practice" per
/// the WFRNG spec, so require exactly that.
fn check_standard_normal(case_name: &str) {
    let tol = manifest_tol(case_name);
    let expected = read_f64_bin(&fixtures_dir().join(format!("{case_name}.out.bin")));

    let mut pcg = Pcg64::seeded(7);
    let got = pcg.standard_normal_vec(expected.len());

    assert_eq!(
        got.len(),
        expected.len(),
        "{case_name}: length {} != expected {} — output length is part of the contract",
        got.len(),
        expected.len()
    );
    let (mut worst, mut at) = (0.0f64, 0usize);
    for (i, (a, e)) in got.iter().zip(&expected).enumerate() {
        let d = (a - e).abs();
        if d > worst {
            worst = d;
            at = i;
        }
    }
    assert!(
        worst <= tol,
        "{case_name}: max_abs {worst:.3e} > tol {tol:.1e} at [{at}] (got {:.17}, expected {:.17})",
        got[at],
        expected[at]
    );

    // Stronger, additional check: every draw bit-for-bit identical to the
    // oracle, not merely within `tol`. A single mismatched draw here
    // means the ported ziggurat has desynchronized from numpy's stream at
    // or before that index — sample-parity for this layer means this
    // passing, not just `max_abs` passing.
    for (i, (a, e)) in got.iter().zip(&expected).enumerate() {
        assert_eq!(
            a.to_bits(),
            e.to_bits(),
            "{case_name}[{i}]: to_bits mismatch — got {a:.17e} ({:#018x}), \
             expected {e:.17e} ({:#018x}); max_abs alone would not have \
             caught this (worst {worst:.3e} was within tol {tol:.1e})",
            a.to_bits(),
            e.to_bits()
        );
    }
}

/// Documents (and change-detects) what blackbox tail-branch evidence is
/// available in the `standard_normal_64` / `standard_normal_2x32` oracle
/// stream (both are the same draws — see
/// `standard_normal_2x32_is_standard_normal_64_reshaped`). This is *not*
/// the crate's slow-path coverage proof — see that note below — just the
/// one slow-path fact a blackbox test (public API only; `np-rand`'s
/// ziggurat branch internals are `pub(crate)`, invisible here) can prove
/// on its own: a tail-branch (`idx == 0`) draw always has magnitude
/// strictly greater than `ziggurat_nor_r`, since it returns `±(R + xx)`
/// with `xx >= 0`, and no non-tail branch can reach that magnitude — so a
/// value beyond `R` is sound, self-contained tail evidence, no internal
/// access required.
///
/// Measured on this stream: the tail branch is **not** reached (0 draws
/// exceed `R`). The stream's actual slow-path coverage — draw index 31
/// takes the wedge-test path — is real but not blackbox-provable this way
/// (a wedge-accepted value and a fast-accepted value from the same layer
/// aren't distinguishable by magnitude alone), so it's proven instead in
/// `src/lib.rs`'s `standard_normal_64_stream_exact_bits_with_wedge_coverage`,
/// which has direct access to `ZigguratBranch` and asserts on it directly.
/// This test exists so the tail-coverage gap stays a measured, asserted
/// fact rather than a claim in a comment nobody re-checks.
#[test]
fn standard_normal_64_tail_branch_not_reached() {
    // `ziggurat_nor_r`, numpy's tail-start boundary — duplicated as a
    // literal here (not imported: `np_rand`'s equivalent constant is
    // private) since it's a numpy-defined constant, not a hand-derived
    // expectation about this crate's output. Full source precision, as in
    // `np_rand::ziggurat_tables` — see that module's doc for why.
    #[allow(clippy::excessive_precision)]
    const ZIGGURAT_R: f64 = 3.6541528853610087963519472518;

    let expected = read_f64_bin(&fixtures_dir().join("standard_normal_64.out.bin"));
    let tail_count = expected.iter().filter(|v| v.abs() > ZIGGURAT_R).count();
    // Not asserted >0: measured to be 0 on this stream (documented above
    // and in the whitebox test) — asserting a false positive here would
    // be worse than having no assertion at all. This test exists so a
    // *future* change to the oracle stream (different seed, more draws)
    // that does add tail coverage is visible rather than silently ignored:
    // flip this to `assert!(tail_count > 0, ...)` the day that's true.
    assert_eq!(
        tail_count, 0,
        "measured tail-branch coverage changed — 0 was the recorded \
         baseline for this stream; update this test (and the doc comments \
         pointing at it) to assert coverage now that there is some"
    );
}

#[test]
fn standard_normal_64() {
    // Oracle: `np.random.default_rng(7).standard_normal(64)`.
    check_standard_normal("standard_normal_64");
}

#[test]
fn standard_normal_2x32_matches_2x32_shape() {
    // Shaped-order proof: this fixture is
    // `default_rng(7).standard_normal((2, 32))`, dumped row-major.
    // `np-rand` has no notion of shape at all — [`Pcg64::standard_normal_vec`]
    // just returns 64 draws in stream order. Those 64 draws matching this
    // fixture exactly (same tolerance, same oracle seed) *is* the proof
    // that stream order equals numpy's row-major fill order: were the
    // fill order column-major, or the two fixture calls not draw-for-draw
    // identical, this would diverge from `standard_normal_64` above.
    check_standard_normal("standard_normal_2x32");
}

#[test]
fn standard_normal_2x32_is_standard_normal_64_reshaped() {
    // Belt-and-suspenders: the two oracle dumps should be bit-identical
    // to each other (both are `default_rng(7)`'s first 64 draws, just
    // shaped differently on the numpy side), independent of `np-rand`
    // entirely. If this ever fails, the fixtures disagree with each
    // other, not with this crate.
    let flat = read_f64_bin(&fixtures_dir().join("standard_normal_64.out.bin"));
    let shaped = read_f64_bin(&fixtures_dir().join("standard_normal_2x32.out.bin"));
    assert_eq!(flat, shaped);
}
