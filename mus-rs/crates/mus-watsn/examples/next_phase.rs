use std::env;
use std::f64::consts::{FRAC_PI_2, PI, TAU};
use std::fs::{create_dir_all, File};
use std::io::{BufWriter, Write};
use std::path::PathBuf;

use mus_watsn::{
    balanced_inverse_branches, commutator_matrix, order_defect, principal_rotation_angle,
    quadratic_energy, resample_periodic_linear, resample_periodic_linear_neutral,
    AllpassSection,
};

fn deterministic_state(len: usize, phase_offset: f64) -> Vec<f64> {
    (0..len)
        .map(|index| {
            let phase = TAU * index as f64 / len as f64 + phase_offset;
            0.71 * phase.sin()
                + 0.23 * (2.0 * phase + 0.17).cos()
                + 0.11 * (5.0 * phase - 0.41).sin()
        })
        .collect()
}

fn normalized_correlation(left: &[f64], right: &[f64]) -> f64 {
    assert_eq!(left.len(), right.len());
    let dot = left.iter().zip(right).map(|(a, b)| a * b).sum::<f64>();
    let left_norm = left.iter().map(|value| value * value).sum::<f64>().sqrt();
    let right_norm = right.iter().map(|value| value * value).sum::<f64>().sqrt();
    dot / (left_norm * right_norm).max(1.0e-30)
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let output_dir = env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("ariadne-next-phase-results"));
    create_dir_all(&output_dir)?;

    let mut max_allpass_neutral_work: f64 = 0.0;
    let mut max_allpass_legacy_work: f64 = 0.0;
    for old_index in 0..=80 {
        let old = -0.98 + 1.96 * old_index as f64 / 80.0;
        for new_index in 0..=80 {
            let new = -0.98 + 1.96 * new_index as f64 / 80.0;
            let x1 = 0.37 + 0.19 * (old * 2.7).sin();
            let y1 = -0.29 + 0.13 * (new * 1.9).cos();
            let mut neutral = AllpassSection::from_state(old, x1, y1);
            let neutral_receipt = neutral.set_coefficient_neutral(new);
            max_allpass_neutral_work =
                max_allpass_neutral_work.max(neutral_receipt.control_work.abs());
            let mut legacy = AllpassSection::from_state(old, x1, y1);
            let legacy_receipt = legacy.set_coefficient_legacy(new);
            max_allpass_legacy_work =
                max_allpass_legacy_work.max(legacy_receipt.control_work.abs());
        }
    }

    let lengths = [8_usize, 16, 31, 64, 127, 256, 512, 1024];
    let ratios = [(1_usize, 2_usize), (2, 3), (1, 1), (3, 2), (2, 1)];
    let mut remap_csv = BufWriter::new(File::create(output_dir.join("delay-remap.csv"))?);
    writeln!(
        remap_csv,
        "old_len,new_len,raw_energy_ratio,neutral_relative_residual,neutral_scale"
    )?;
    let mut max_delay_neutral_relative_residual: f64 = 0.0;
    let mut max_raw_energy_ratio_error: f64 = 0.0;
    for old_len in lengths {
        let source = deterministic_state(old_len, old_len as f64 * 0.013);
        let source_energy = quadratic_energy(&source);
        for (numerator, denominator) in ratios {
            let new_len = ((old_len * numerator + denominator / 2) / denominator).max(3);
            let mut raw = vec![0.0; new_len];
            resample_periodic_linear(&source, &mut raw);
            let raw_ratio = quadratic_energy(&raw) / source_energy;
            max_raw_energy_ratio_error = max_raw_energy_ratio_error.max((raw_ratio - 1.0).abs());
            let mut neutral = vec![0.0; new_len];
            let receipt = resample_periodic_linear_neutral(&source, &mut neutral);
            let relative_residual = receipt.control_work.abs() / source_energy.max(1.0e-30);
            max_delay_neutral_relative_residual =
                max_delay_neutral_relative_residual.max(relative_residual);
            writeln!(
                remap_csv,
                "{old_len},{new_len},{raw_ratio:.17e},{relative_residual:.17e},{:.17e}",
                receipt.scale
            )?;
        }
    }
    remap_csv.flush()?;

    let original = deterministic_state(147, 0.31);
    let mut cycle_state = original.clone();
    let initial_energy = quadratic_energy(&cycle_state);
    let mut max_cycle_energy_drift: f64 = 0.0;
    for _ in 0..100 {
        let mut expanded = vec![0.0; 221];
        resample_periodic_linear_neutral(&cycle_state, &mut expanded);
        let mut contracted = vec![0.0; 147];
        resample_periodic_linear_neutral(&expanded, &mut contracted);
        cycle_state = contracted;
        max_cycle_energy_drift = max_cycle_energy_drift
            .max((quadratic_energy(&cycle_state) - initial_energy).abs());
    }
    let cycle_correlation = normalized_correlation(&original, &cycle_state);

    let angle_a = 0.31;
    let angle_b = -0.47;
    let commutator_angle = principal_rotation_angle(commutator_matrix(angle_a, angle_b));
    let defect = order_defect(angle_a, angle_b);
    let (inverse_low, inverse_high) = balanced_inverse_branches(commutator_angle);

    let stretch = [1.6_f64, 0.7, 1.0];
    let state = [1.0_f64, 0.0, 0.0];
    let rotate = |value: [f64; 3]| -> [f64; 3] {
        let (x, y) = mus_watsn::givens(value[0], value[1], FRAC_PI_2);
        [x, y, value[2]]
    };
    let apply_stretch = |value: [f64; 3]| -> [f64; 3] {
        [stretch[0] * value[0], stretch[1] * value[1], value[2]]
    };
    let energy = |value: [f64; 3]| -> f64 {
        0.5 * value.iter().map(|component| component * component).sum::<f64>()
    };
    let uh_work = energy(rotate(apply_stretch(state))) - energy(state);
    let hu_work = energy(apply_stretch(rotate(state))) - energy(state);
    let lambda = stretch[0] * stretch[0] - stretch[1] * stretch[1];
    let exact_work_difference_max = 0.5 * lambda.abs();
    let exact_work_difference_rms = lambda.abs() / (15.0_f64).sqrt();

    let mut json = BufWriter::new(File::create(output_dir.join("results.json"))?);
    writeln!(json, "{{")?;
    writeln!(json, "  \"schema\": \"ariadne-next-phase/1\",")?;
    writeln!(json, "  \"allpass\": {{")?;
    writeln!(
        json,
        "    \"max_neutral_abs_work\": {:.17e},",
        max_allpass_neutral_work
    )?;
    writeln!(
        json,
        "    \"max_legacy_abs_work\": {:.17e}",
        max_allpass_legacy_work
    )?;
    writeln!(json, "  }},")?;
    writeln!(json, "  \"delay_remap\": {{")?;
    writeln!(
        json,
        "    \"max_neutral_relative_residual\": {:.17e},",
        max_delay_neutral_relative_residual
    )?;
    writeln!(
        json,
        "    \"max_raw_energy_ratio_error\": {:.17e},",
        max_raw_energy_ratio_error
    )?;
    writeln!(
        json,
        "    \"hundred_cycle_max_abs_energy_drift\": {:.17e},",
        max_cycle_energy_drift
    )?;
    writeln!(
        json,
        "    \"hundred_cycle_state_correlation\": {:.17e}",
        cycle_correlation
    )?;
    writeln!(json, "  }},")?;
    writeln!(json, "  \"commutator\": {{")?;
    writeln!(json, "    \"a_rad\": {:.17e},", angle_a)?;
    writeln!(json, "    \"b_rad\": {:.17e},", angle_b)?;
    writeln!(
        json,
        "    \"principal_angle_rad\": {:.17e},",
        commutator_angle
    )?;
    writeln!(json, "    \"order_defect\": {:.17e},", defect)?;
    writeln!(json, "    \"balanced_inverse_low\": {:.17e},", inverse_low)?;
    writeln!(
        json,
        "    \"balanced_inverse_high\": {:.17e}",
        inverse_high
    )?;
    writeln!(json, "  }},")?;
    writeln!(json, "  \"factor_order\": {{")?;
    writeln!(json, "    \"work_U_after_H\": {:.17e},", uh_work)?;
    writeln!(json, "    \"work_H_after_U\": {:.17e},", hu_work)?;
    writeln!(
        json,
        "    \"exact_max_abs_difference\": {:.17e},",
        exact_work_difference_max
    )?;
    writeln!(
        json,
        "    \"exact_rms_difference\": {:.17e}",
        exact_work_difference_rms
    )?;
    writeln!(json, "  }},")?;
    writeln!(json, "  \"notes\": [")?;
    writeln!(
        json,
        "    \"Neutral scalar remapping preserves the declared state energy but repeated interpolation still loses waveform identity.\","
    )?;
    writeln!(
        json,
        "    \"The allpass transport is an exact metric state change for the section realization, unlike post-hoc output normalization.\","
    )?;
    writeln!(
        json,
        "    \"The high balanced inverse branch approaches pi for small target holonomy and is intentionally not the default musical branch.\""
    )?;
    writeln!(json, "  ]")?;
    writeln!(json, "}}")?;
    json.flush()?;

    let mut summary = BufWriter::new(File::create(output_dir.join("SUMMARY.md"))?);
    writeln!(summary, "# Ariadne next-phase reference results")?;
    writeln!(summary)?;
    writeln!(
        summary,
        "- Maximum neutral allpass coefficient-change work: `{max_allpass_neutral_work:.3e}`."
    )?;
    writeln!(
        summary,
        "- Maximum legacy allpass coefficient-change work over the same grid: `{max_allpass_legacy_work:.3e}`."
    )?;
    writeln!(
        summary,
        "- Maximum relative energy residual of neutral periodic remapping: `{max_delay_neutral_relative_residual:.3e}`."
    )?;
    writeln!(
        summary,
        "- Largest raw-remap energy-ratio error: `{max_raw_energy_ratio_error:.3e}`."
    )?;
    writeln!(
        summary,
        "- 100 expansion/contraction cycles preserve energy within `{max_cycle_energy_drift:.3e}` absolute, but final waveform correlation is only `{cycle_correlation:.6}`."
    )?;
    writeln!(
        summary,
        "- Reference commutator: angle `{:.9}` degrees, defect `{defect:.9}`.",
        commutator_angle * 180.0 / PI
    )?;
    writeln!(
        summary,
        "- Exact factor-order RMS work difference: `{exact_work_difference_rms:.9}`; maximum `{exact_work_difference_max:.9}`."
    )?;
    summary.flush()?;

    println!("results written to {}", output_dir.display());
    println!("max neutral allpass work: {max_allpass_neutral_work:.3e}");
    println!("max neutral delay residual: {max_delay_neutral_relative_residual:.3e}");
    println!("100-cycle state correlation: {cycle_correlation:.6}");
    Ok(())
}
