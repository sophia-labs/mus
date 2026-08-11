use std::env;
use std::fs::{create_dir_all, File};
use std::io::{BufWriter, Write};
use std::path::PathBuf;

use mus_watsn::{
    run_string_experiment, RetunePolicy, StringExperimentConfig, StringExperimentRun,
};

fn correlation(left: &[f64], right: &[f64]) -> f64 {
    assert_eq!(left.len(), right.len());
    let dot = left.iter().zip(right).map(|(a, b)| a * b).sum::<f64>();
    let left_norm = left.iter().map(|value| value * value).sum::<f64>().sqrt();
    let right_norm = right.iter().map(|value| value * value).sum::<f64>().sqrt();
    dot / (left_norm * right_norm).max(1.0e-30)
}

fn write_row(
    csv: &mut BufWriter<File>,
    config: StringExperimentConfig,
    run: &StringExperimentRun,
    legacy_correlation: f64,
) -> std::io::Result<()> {
    let result = &run.result;
    writeln!(
        csv,
        "{},{:.9},{:.9},{:.6},{:.6},{:.6},{},{:.17e},{:.17e},{:.17e},{:.17e},{:.17e},{:.17e},{:.9},{:.9},{},{},{}",
        result.policy.as_str(),
        config.f0,
        config.f1,
        config.stiff,
        config.sample_rate,
        config.duration_s,
        config.update_stride,
        result.cumulative_line_control_work,
        result.cumulative_filter_control_work,
        result.sum_abs_line_control_work,
        result.sum_abs_filter_control_work,
        result.max_abs_line_control_work,
        result.max_abs_filter_control_work,
        result.max_energy_ratio,
        result.output_peak,
        result.integer_delay_changes,
        legacy_correlation,
        result.finite
    )
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let output_dir = env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("ariadne-string-retune-results"));
    create_dir_all(&output_dir)?;

    let mut csv = BufWriter::new(File::create(output_dir.join("string-retune-sweep.csv"))?);
    writeln!(
        csv,
        "policy,f0,f1,stiff,sample_rate,duration_s,update_stride,cumulative_line_work,cumulative_filter_work,sum_abs_line_work,sum_abs_filter_work,max_abs_line_work,max_abs_filter_work,max_energy_ratio,output_peak,delay_changes,correlation_to_legacy,finite"
    )?;

    let mut all_finite = true;
    let mut neutral_remap_max_abs_step_work: f64 = 0.0;
    let mut neutral_filters_max_abs_filter_step_work: f64 = 0.0;
    let mut legacy_max_abs_line_step_work: f64 = 0.0;
    let mut legacy_max_abs_filter_step_work: f64 = 0.0;
    let mut min_neutral_remap_correlation: f64 = 1.0;
    let mut min_neutral_filters_correlation: f64 = 1.0;
    let mut max_neutral_remap_energy_ratio: f64 = 0.0;
    let mut max_legacy_energy_ratio: f64 = 0.0;

    for f0 in [82.4069, 110.0, 220.0, 440.0] {
        for ratio in [2.0 / 3.0, 1.5, 2.0] {
            for stiff in [0.0, 0.75] {
                for update_stride in [1, 16, 64] {
                    let config = StringExperimentConfig {
                        sample_rate: 12_000.0,
                        duration_s: 0.65,
                        f0,
                        f1: f0 * ratio,
                        t60: 3.0,
                        damp: 0.18,
                        stiff,
                        tension_cents: 0.0,
                        update_stride,
                    };
                    let legacy = run_string_experiment(config, RetunePolicy::Legacy);
                    let neutral_filters =
                        run_string_experiment(config, RetunePolicy::NeutralFilters);
                    let neutral_remap =
                        run_string_experiment(config, RetunePolicy::NeutralRemap);
                    let filters_correlation = correlation(&legacy.output, &neutral_filters.output);
                    let remap_correlation = correlation(&legacy.output, &neutral_remap.output);

                    write_row(&mut csv, config, &legacy, 1.0)?;
                    write_row(
                        &mut csv,
                        config,
                        &neutral_filters,
                        filters_correlation,
                    )?;
                    write_row(&mut csv, config, &neutral_remap, remap_correlation)?;

                    all_finite &= legacy.result.finite
                        && neutral_filters.result.finite
                        && neutral_remap.result.finite;
                    neutral_remap_max_abs_step_work = neutral_remap_max_abs_step_work.max(
                        neutral_remap.result.max_abs_line_control_work
                            + neutral_remap.result.max_abs_filter_control_work,
                    );
                    neutral_filters_max_abs_filter_step_work =
                        neutral_filters_max_abs_filter_step_work
                            .max(neutral_filters.result.max_abs_filter_control_work);
                    legacy_max_abs_line_step_work = legacy_max_abs_line_step_work
                        .max(legacy.result.max_abs_line_control_work);
                    legacy_max_abs_filter_step_work = legacy_max_abs_filter_step_work
                        .max(legacy.result.max_abs_filter_control_work);
                    min_neutral_filters_correlation =
                        min_neutral_filters_correlation.min(filters_correlation);
                    min_neutral_remap_correlation =
                        min_neutral_remap_correlation.min(remap_correlation);
                    max_neutral_remap_energy_ratio = max_neutral_remap_energy_ratio
                        .max(neutral_remap.result.max_energy_ratio);
                    max_legacy_energy_ratio =
                        max_legacy_energy_ratio.max(legacy.result.max_energy_ratio);
                }
            }
        }
    }
    csv.flush()?;

    let canonical_config = StringExperimentConfig::default();
    let canonical_legacy = run_string_experiment(canonical_config, RetunePolicy::Legacy);
    let canonical_filters =
        run_string_experiment(canonical_config, RetunePolicy::NeutralFilters);
    let canonical_remap = run_string_experiment(canonical_config, RetunePolicy::NeutralRemap);
    let canonical_filters_correlation =
        correlation(&canonical_legacy.output, &canonical_filters.output);
    let canonical_remap_correlation =
        correlation(&canonical_legacy.output, &canonical_remap.output);

    let mut json = BufWriter::new(File::create(output_dir.join("results.json"))?);
    writeln!(json, "{{")?;
    writeln!(json, "  \"schema\": \"ariadne-string-retune/1\",")?;
    writeln!(json, "  \"sweep\": {{")?;
    writeln!(json, "    \"all_finite\": {all_finite},")?;
    writeln!(
        json,
        "    \"neutral_remap_max_abs_step_work\": {neutral_remap_max_abs_step_work:.17e},"
    )?;
    writeln!(
        json,
        "    \"neutral_filters_max_abs_filter_step_work\": {neutral_filters_max_abs_filter_step_work:.17e},"
    )?;
    writeln!(
        json,
        "    \"legacy_max_abs_line_step_work\": {legacy_max_abs_line_step_work:.17e},"
    )?;
    writeln!(
        json,
        "    \"legacy_max_abs_filter_step_work\": {legacy_max_abs_filter_step_work:.17e},"
    )?;
    writeln!(
        json,
        "    \"min_neutral_filters_correlation\": {min_neutral_filters_correlation:.17e},"
    )?;
    writeln!(
        json,
        "    \"min_neutral_remap_correlation\": {min_neutral_remap_correlation:.17e},"
    )?;
    writeln!(
        json,
        "    \"max_legacy_energy_ratio\": {max_legacy_energy_ratio:.17e},"
    )?;
    writeln!(
        json,
        "    \"max_neutral_remap_energy_ratio\": {max_neutral_remap_energy_ratio:.17e}"
    )?;
    writeln!(json, "  }},")?;
    writeln!(json, "  \"canonical_48khz_upward_fifth\": {{")?;
    writeln!(
        json,
        "    \"legacy_max_energy_ratio\": {:.17e},",
        canonical_legacy.result.max_energy_ratio
    )?;
    writeln!(
        json,
        "    \"neutral_filters_max_energy_ratio\": {:.17e},",
        canonical_filters.result.max_energy_ratio
    )?;
    writeln!(
        json,
        "    \"neutral_remap_max_energy_ratio\": {:.17e},",
        canonical_remap.result.max_energy_ratio
    )?;
    writeln!(
        json,
        "    \"legacy_sum_abs_line_work\": {:.17e},",
        canonical_legacy.result.sum_abs_line_control_work
    )?;
    writeln!(
        json,
        "    \"legacy_sum_abs_filter_work\": {:.17e},",
        canonical_legacy.result.sum_abs_filter_control_work
    )?;
    writeln!(
        json,
        "    \"neutral_filters_sum_abs_line_work\": {:.17e},",
        canonical_filters.result.sum_abs_line_control_work
    )?;
    writeln!(
        json,
        "    \"neutral_filters_sum_abs_filter_work\": {:.17e},",
        canonical_filters.result.sum_abs_filter_control_work
    )?;
    writeln!(
        json,
        "    \"neutral_remap_sum_abs_line_work\": {:.17e},",
        canonical_remap.result.sum_abs_line_control_work
    )?;
    writeln!(
        json,
        "    \"neutral_remap_sum_abs_filter_work\": {:.17e},",
        canonical_remap.result.sum_abs_filter_control_work
    )?;
    writeln!(
        json,
        "    \"neutral_filters_correlation_to_legacy\": {canonical_filters_correlation:.17e},"
    )?;
    writeln!(
        json,
        "    \"neutral_remap_correlation_to_legacy\": {canonical_remap_correlation:.17e}"
    )?;
    writeln!(json, "  }},")?;
    writeln!(json, "  \"interpretation\": [")?;
    writeln!(
        json,
        "    \"NeutralFilters removes exact allpass coefficient-change work but leaves active delay-rank reinterpretation untouched.\","
    )?;
    writeln!(
        json,
        "    \"NeutralRemap closes the declared active-segment and allpass update ledger for the current state, but it is nonlinear and must be judged separately for pitch and timbral fidelity.\","
    )?;
    writeln!(
        json,
        "    \"This model mirrors the production control law but omits body, sympathetic strings, contact, and the full physical energy metric.\""
    )?;
    writeln!(json, "  ]")?;
    writeln!(json, "}}")?;
    json.flush()?;

    let mut summary = BufWriter::new(File::create(output_dir.join("SUMMARY.md"))?);
    writeln!(summary, "# Changing-delay reference results")?;
    writeln!(summary)?;
    writeln!(
        summary,
        "- Maximum neutral-remap update work over the sweep: `{neutral_remap_max_abs_step_work:.3e}`."
    )?;
    writeln!(
        summary,
        "- Maximum neutral-filter allpass work over the sweep: `{neutral_filters_max_abs_filter_step_work:.3e}`."
    )?;
    writeln!(
        summary,
        "- Maximum legacy active-line update work: `{legacy_max_abs_line_step_work:.3e}`."
    )?;
    writeln!(
        summary,
        "- Maximum legacy allpass update work: `{legacy_max_abs_filter_step_work:.3e}`."
    )?;
    writeln!(
        summary,
        "- Worst correlation to legacy: neutral filters `{min_neutral_filters_correlation:.6}`, neutral remap `{min_neutral_remap_correlation:.6}`."
    )?;
    writeln!(summary)?;
    writeln!(summary, "## Canonical 48 kHz upward fifth")?;
    writeln!(
        summary,
        "- Legacy max proxy-energy ratio: `{:.6}`.",
        canonical_legacy.result.max_energy_ratio
    )?;
    writeln!(
        summary,
        "- Neutral filters max proxy-energy ratio: `{:.6}`.",
        canonical_filters.result.max_energy_ratio
    )?;
    writeln!(
        summary,
        "- Neutral remap max proxy-energy ratio: `{:.6}`.",
        canonical_remap.result.max_energy_ratio
    )?;
    writeln!(
        summary,
        "- Neutral-remap correlation to legacy: `{canonical_remap_correlation:.6}`."
    )?;
    summary.flush()?;

    println!("results written to {}", output_dir.display());
    println!("neutral remap max step work: {neutral_remap_max_abs_step_work:.3e}");
    println!("legacy max line step work: {legacy_max_abs_line_step_work:.3e}");
    println!("canonical remap correlation: {canonical_remap_correlation:.6}");
    Ok(())
}
