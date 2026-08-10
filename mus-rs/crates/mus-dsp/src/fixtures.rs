//! Golden-vector harness: load and check cases from `mus-rs/fixtures/dsp/`.
//!
//! `gen_dsp_fixtures.py` dumps each case as raw little-endian binaries plus
//! a manifest entry carrying the function arguments and the tolerance the
//! port must meet. Tests resolve a case by name, run the Rust port on
//! `input`, and call [`Case::check`], which applies the manifest's metric
//! (`max_abs` or `rel_rms`) and panics with a worst-sample report on
//! failure. Never widen a tolerance in the test — tolerances live in the
//! manifest, and changing one is an oracle-policy decision, not a fix.

use std::fs;
use std::path::{Path, PathBuf};

use serde::Deserialize;

/// One manifest entry, as written by `gen_dsp_fixtures.py`.
#[derive(Debug, Clone, Deserialize)]
pub struct CaseMeta {
    pub name: String,
    pub module: String,
    pub func: String,
    #[serde(default)]
    pub args: serde_json::Value,
    pub metric: String,
    pub tol: f64,
    pub dtype: String,
    #[serde(default)]
    pub note: String,
    #[serde(default)]
    pub input: Option<String>,
    #[serde(default)]
    pub shape_in: Option<Vec<usize>>,
    pub output: String,
    pub shape_out: Vec<usize>,
}

/// A loaded case: metadata plus its arrays, everything widened to f64 so
/// checks are metric-exact regardless of the on-disk dtype.
pub struct Case {
    pub meta: CaseMeta,
    pub input: Vec<f64>,
    pub expected: Vec<f64>,
}

pub fn fixtures_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/dsp")
}

pub fn manifest() -> Vec<CaseMeta> {
    let path = fixtures_dir().join("manifest.json");
    let text = fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("read {}: {e} — run gen_dsp_fixtures.py", path.display()));
    serde_json::from_str(&text).expect("manifest.json parses")
}

fn read_bin(name: &str, dtype: &str) -> Vec<f64> {
    let path = fixtures_dir().join(name);
    let bytes = fs::read(&path)
        .unwrap_or_else(|e| panic!("read {}: {e} — run gen_dsp_fixtures.py", path.display()));
    match dtype {
        "<f4" => bytes
            .chunks_exact(4)
            .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]) as f64)
            .collect(),
        "<f8" => bytes
            .chunks_exact(8)
            .map(|c| f64::from_le_bytes([c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7]]))
            .collect(),
        other => panic!("fixture {name}: unsupported dtype {other}"),
    }
}

/// Load a case by manifest name. Panics (with the run instruction) if the
/// fixtures have not been generated.
pub fn case(name: &str) -> Case {
    let meta = manifest()
        .into_iter()
        .find(|m| m.name == name)
        .unwrap_or_else(|| panic!("no fixture case named {name:?} in manifest.json"));
    let input = meta
        .input
        .as_deref()
        .map(|f| read_bin(f, &meta.dtype))
        .unwrap_or_default();
    let expected = read_bin(&meta.output, &meta.dtype);
    Case {
        meta,
        input,
        expected,
    }
}

impl Case {
    /// The case input as f32 (the common audio dtype).
    pub fn input_f32(&self) -> Vec<f32> {
        self.input.iter().map(|&v| v as f32).collect()
    }

    /// A required argument, as f64. Panics if missing or non-numeric.
    pub fn arg_f64(&self, key: &str) -> f64 {
        self.meta.args[key]
            .as_f64()
            .unwrap_or_else(|| panic!("{}: arg {key:?} missing/non-numeric", self.meta.name))
    }

    /// A required argument, as f32.
    pub fn arg_f32(&self, key: &str) -> f32 {
        self.arg_f64(key) as f32
    }

    /// Check an f32 result against the expected vector with the manifest's
    /// metric and tolerance. Length must match exactly — a length mismatch
    /// is always a hard failure, whatever the metric.
    pub fn check(&self, actual: &[f32]) {
        let widened: Vec<f64> = actual.iter().map(|&v| v as f64).collect();
        self.check_f64(&widened);
    }

    /// f64 variant of [`Case::check`] for `<f8` cases (RNG, SOS tables).
    pub fn check_f64(&self, actual: &[f64]) {
        let name = &self.meta.name;
        assert_eq!(
            actual.len(),
            self.expected.len(),
            "{name}: length {} != expected {} — output length is part of the contract",
            actual.len(),
            self.expected.len()
        );
        match self.meta.metric.as_str() {
            "max_abs" => {
                let (mut worst, mut at) = (0.0f64, 0usize);
                for (i, (a, e)) in actual.iter().zip(&self.expected).enumerate() {
                    let d = (a - e).abs();
                    if d > worst {
                        worst = d;
                        at = i;
                    }
                }
                assert!(
                    worst <= self.meta.tol,
                    "{name}: max_abs {worst:.3e} > tol {:.1e} at [{at}] \
                     (got {:.9}, expected {:.9})",
                    self.meta.tol,
                    actual[at],
                    self.expected[at]
                );
            }
            "rel_rms" => {
                let mut num = 0.0f64;
                let mut den = 0.0f64;
                for (a, e) in actual.iter().zip(&self.expected) {
                    num += (a - e) * (a - e);
                    den += e * e;
                }
                let rel = (num / den.max(1e-30)).sqrt();
                assert!(
                    rel <= self.meta.tol,
                    "{name}: rel_rms {rel:.3e} > tol {:.1e}",
                    self.meta.tol
                );
            }
            other => panic!("{name}: unknown metric {other:?}"),
        }
    }
}
