//! Binary64 changing-delay reference model shaped after the production
//! `DelayString` control law.
//!
//! The model is deliberately smaller than the production instrument: one
//! recursive line, its one-zero damping memory, two dispersion allpasses, and
//! one fractional-delay allpass. It exists to compare state-transition
//! policies before altering the production audio kernel.
//!
//! The declared delay-state energy is the Euclidean energy of the active loop
//! segment ending at the write head. This is a research metric, not yet a
//! physical string Hamiltonian. `NeutralRemap` preserves that energy for the
//! current state by periodic interpolation plus a scalar correction; it is a
//! state-contingent approximation, not a globally linear polar isometry.

use std::f64::consts::{LN_10, PI};

use crate::allpass::AllpassSection;
use crate::delay::{quadratic_energy, resample_periodic_linear_neutral};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RetunePolicy {
    /// Production-style coefficient and read-tap updates with state unchanged.
    Legacy,
    /// Preserve the exact storage coordinate of every time-varying allpass,
    /// while retaining the production read-tap update.
    NeutralFilters,
    /// Preserve allpass storage and remap the active periodic delay state to
    /// the new integer length with state-contingent energy normalization.
    NeutralRemap,
}

impl RetunePolicy {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Legacy => "legacy",
            Self::NeutralFilters => "neutral_filters",
            Self::NeutralRemap => "neutral_remap",
        }
    }

    fn neutral_filters(self) -> bool {
        matches!(self, Self::NeutralFilters | Self::NeutralRemap)
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct StringExperimentConfig {
    pub sample_rate: f64,
    pub duration_s: f64,
    pub f0: f64,
    pub f1: f64,
    pub t60: f64,
    pub damp: f64,
    pub stiff: f64,
    pub tension_cents: f64,
    pub update_stride: usize,
}

impl Default for StringExperimentConfig {
    fn default() -> Self {
        Self {
            sample_rate: 48_000.0,
            duration_s: 1.5,
            f0: 110.0,
            f1: 165.0,
            t60: 4.0,
            damp: 0.18,
            stiff: 0.08,
            tension_cents: 0.0,
            update_stride: 16,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct StringExperimentResult {
    pub policy: RetunePolicy,
    pub samples: usize,
    pub output_peak: f64,
    pub baseline_energy: f64,
    pub max_energy_after_excitation: f64,
    pub max_energy_ratio: f64,
    pub final_energy: f64,
    pub cumulative_line_control_work: f64,
    pub cumulative_filter_control_work: f64,
    pub sum_abs_line_control_work: f64,
    pub sum_abs_filter_control_work: f64,
    pub max_abs_line_control_work: f64,
    pub max_abs_filter_control_work: f64,
    pub integer_delay_changes: u64,
    pub coefficient_updates: u64,
    pub finite: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct StringExperimentRun {
    pub result: StringExperimentResult,
    pub output: Vec<f64>,
}

fn one_zero_response(damp: f64, omega: f64) -> (f64, f64) {
    let real = 1.0 - damp + damp * omega.cos();
    let imag = -damp * omega.sin();
    let magnitude = real.hypot(imag).max(1.0e-12);
    let phase_delay = if omega > 1.0e-12 {
        -imag.atan2(real) / omega
    } else {
        damp
    };
    (magnitude, phase_delay)
}

fn allpass_phase_delay(coefficient: f64, omega: f64) -> f64 {
    if omega <= 1.0e-12 {
        return (1.0 - coefficient) / (1.0 + coefficient);
    }
    let numerator_phase = (-omega.sin()).atan2(coefficient + omega.cos());
    let denominator_phase = (-coefficient * omega.sin()).atan2(1.0 + coefficient * omega.cos());
    let mut phase = numerator_phase - denominator_phase;
    while phase > 0.0 {
        phase -= 2.0 * PI;
    }
    while phase <= -2.0 * PI {
        phase += 2.0 * PI;
    }
    -phase / omega
}

fn allpass_coefficient_for_delay(delay_samples: f64, omega: f64) -> f64 {
    let delay = delay_samples.clamp(0.02, 1.98);
    if omega.abs() < 1.0e-9 {
        return ((1.0 - delay) / (1.0 + delay)).clamp(-0.999_5, 0.999_5);
    }
    let denominator = (omega * 0.5).tan();
    if denominator.abs() < 1.0e-12 {
        return ((1.0 - delay) / (1.0 + delay)).clamp(-0.999_5, 0.999_5);
    }
    let ratio = (omega * delay * 0.5).tan() / denominator;
    ((1.0 - ratio) / (1.0 + ratio)).clamp(-0.999_5, 0.999_5)
}

fn excitation(sample_rate: f64, frequency: f64) -> Vec<f64> {
    let period = (sample_rate / frequency.max(20.0)).ceil().max(8.0) as usize;
    let pick = 0.13;
    let mut values = Vec::with_capacity(period);
    for index in 0..period {
        let x = index as f64 / period as f64;
        values.push(if x < pick {
            x / pick
        } else {
            (1.0 - x) / (1.0 - pick)
        });
    }
    let mean = values.iter().sum::<f64>() / values.len() as f64;
    for value in &mut values {
        *value -= mean;
    }
    let rms = (values.iter().map(|value| value * value).sum::<f64>() / values.len() as f64)
        .sqrt()
        .max(1.0e-12);
    for value in &mut values {
        *value *= 0.35 / rms;
    }
    values
}

struct ReferenceString {
    config: StringExperimentConfig,
    policy: RetunePolicy,
    line: Vec<f64>,
    write_index: usize,
    integer_delay: usize,
    damping_x1: f64,
    dispersion_coefficient: f64,
    dispersion: [AllpassSection; 2],
    fractional: AllpassSection,
    loop_gain: f64,
    excitation: Vec<f64>,
    tension_tau_samples: f64,
    cumulative_line_control_work: f64,
    cumulative_filter_control_work: f64,
    sum_abs_line_control_work: f64,
    sum_abs_filter_control_work: f64,
    max_abs_line_control_work: f64,
    max_abs_filter_control_work: f64,
    integer_delay_changes: u64,
    coefficient_updates: u64,
}

impl ReferenceString {
    fn new(config: StringExperimentConfig, policy: RetunePolicy) -> Self {
        assert!(config.sample_rate.is_finite() && config.sample_rate > 1_000.0);
        assert!(config.duration_s.is_finite() && config.duration_s > 0.0);
        assert!(config.f0.is_finite() && config.f0 >= 20.0);
        assert!(config.f1.is_finite() && config.f1 >= 20.0);
        assert!(config.t60.is_finite() && config.t60 > 0.0);
        assert!(config.update_stride > 0);
        let minimum_frequency = config.f0.min(config.f1).max(15.0);
        let line_len = (config.sample_rate / minimum_frequency).ceil() as usize + 32;
        let dispersion_coefficient = if config.stiff <= 1.0e-12 {
            0.0
        } else {
            -0.93 * config.stiff.clamp(0.0, 1.0).powf(0.35)
        };
        let tension_tau_s = (config.t60 / (6.0 * LN_10)).clamp(0.025, 1.5);
        Self {
            config,
            policy,
            line: vec![0.0; line_len],
            write_index: 0,
            integer_delay: 2,
            damping_x1: 0.0,
            dispersion_coefficient,
            dispersion: [
                AllpassSection::new(dispersion_coefficient),
                AllpassSection::new(dispersion_coefficient),
            ],
            fractional: AllpassSection::new(0.0),
            loop_gain: 0.999,
            excitation: excitation(config.sample_rate, config.f0),
            tension_tau_samples: tension_tau_s * config.sample_rate,
            cumulative_line_control_work: 0.0,
            cumulative_filter_control_work: 0.0,
            sum_abs_line_control_work: 0.0,
            sum_abs_filter_control_work: 0.0,
            max_abs_line_control_work: 0.0,
            max_abs_filter_control_work: 0.0,
            integer_delay_changes: 0,
            coefficient_updates: 0,
        }
    }

    fn frequency(&self, sample_index: usize, total_samples: usize) -> f64 {
        let progress = sample_index as f64 / total_samples.max(1) as f64;
        let nominal = self.config.f0 + (self.config.f1 - self.config.f0) * progress.min(1.0);
        if self.config.tension_cents <= 1.0e-12 {
            return nominal;
        }
        let cents =
            self.config.tension_cents * (-(sample_index as f64) / self.tension_tau_samples).exp();
        nominal * 2.0_f64.powf(cents / 1200.0)
    }

    fn active_segment(&self, delay: usize) -> Vec<f64> {
        let delay = delay.clamp(1, self.line.len());
        (0..delay)
            .map(|offset| {
                let index = (self.write_index + self.line.len() - delay + offset) % self.line.len();
                self.line[index]
            })
            .collect()
    }

    fn active_line_energy(&self, delay: usize) -> f64 {
        quadratic_energy(&self.active_segment(delay))
    }

    fn replace_active_segment(&mut self, old_delay: usize, new_delay: usize) {
        let source = self.active_segment(old_delay);
        let mut target = vec![0.0; new_delay];
        resample_periodic_linear_neutral(&source, &mut target);
        let clear_len = old_delay.max(new_delay).min(self.line.len());
        for offset in 0..clear_len {
            let index = (self.write_index + self.line.len() - clear_len + offset) % self.line.len();
            self.line[index] = 0.0;
        }
        for (offset, value) in target.into_iter().enumerate() {
            let index = (self.write_index + self.line.len() - new_delay + offset) % self.line.len();
            self.line[index] = value;
        }
    }

    fn set_allpass_coefficient(
        section: &mut AllpassSection,
        coefficient: f64,
        neutral: bool,
    ) -> f64 {
        let receipt = if neutral {
            section.set_coefficient_neutral(coefficient)
        } else {
            section.set_coefficient_legacy(coefficient)
        };
        receipt.control_work
    }

    fn update_loop(&mut self, sample_index: usize, total_samples: usize) {
        let frequency = self.frequency(sample_index, total_samples).max(20.0);
        let omega = 2.0 * PI * frequency / self.config.sample_rate;
        let (damping_magnitude, damping_delay) = one_zero_response(self.config.damp, omega);
        let total_delay = self.config.sample_rate / frequency;
        let mut effective_dispersion = self.dispersion_coefficient;
        let available_dispersion_delay = (total_delay - damping_delay - 2.25).max(0.0);
        for _ in 0..12 {
            let candidate_delay = if effective_dispersion.abs() > 1.0e-12 {
                2.0 * allpass_phase_delay(effective_dispersion, omega)
            } else {
                0.0
            };
            if candidate_delay <= available_dispersion_delay + 1.0e-9 {
                break;
            }
            effective_dispersion *= 0.72;
        }

        let neutral_filters = self.policy.neutral_filters();
        let mut filter_work = 0.0;
        for section in &mut self.dispersion {
            filter_work +=
                Self::set_allpass_coefficient(section, effective_dispersion, neutral_filters);
        }
        let dispersion_delay = if effective_dispersion.abs() > 1.0e-12 {
            2.0 * allpass_phase_delay(effective_dispersion, omega)
        } else {
            0.0
        };
        let remaining = (total_delay - damping_delay - dispersion_delay).max(2.25);
        let mut new_integer_delay = (remaining - 0.20).floor().max(2.0) as usize;
        new_integer_delay = new_integer_delay.min(self.line.len().saturating_sub(2));
        let mut fractional_delay = remaining - new_integer_delay as f64;
        if fractional_delay > 1.95 && new_integer_delay + 1 < self.line.len() {
            new_integer_delay += 1;
            fractional_delay -= 1.0;
        }
        if fractional_delay < 0.02 && new_integer_delay > 2 {
            new_integer_delay -= 1;
            fractional_delay += 1.0;
        }

        let old_integer_delay = self.integer_delay;
        let line_energy_before = self.active_line_energy(old_integer_delay);
        if new_integer_delay != old_integer_delay {
            if self.policy == RetunePolicy::NeutralRemap {
                self.replace_active_segment(old_integer_delay, new_integer_delay);
            }
            self.integer_delay = new_integer_delay;
            self.integer_delay_changes += 1;
        }
        let line_energy_after = self.active_line_energy(self.integer_delay);
        let line_work = line_energy_after - line_energy_before;

        let fractional_coefficient = allpass_coefficient_for_delay(fractional_delay, omega);
        filter_work += Self::set_allpass_coefficient(
            &mut self.fractional,
            fractional_coefficient,
            neutral_filters,
        );

        let target_circulation_gain = 10.0_f64.powf(-3.0 / (self.config.t60 * frequency));
        self.loop_gain = (target_circulation_gain / damping_magnitude).min(0.999_999_5);

        self.cumulative_line_control_work += line_work;
        self.cumulative_filter_control_work += filter_work;
        self.sum_abs_line_control_work += line_work.abs();
        self.sum_abs_filter_control_work += filter_work.abs();
        self.max_abs_line_control_work = self.max_abs_line_control_work.max(line_work.abs());
        self.max_abs_filter_control_work = self.max_abs_filter_control_work.max(filter_work.abs());
        self.coefficient_updates += 1;
    }

    fn filter_storage_energy(&self) -> f64 {
        self.dispersion
            .iter()
            .map(AllpassSection::storage_energy)
            .sum::<f64>()
            + self.fractional.storage_energy()
    }

    fn proxy_energy(&self) -> f64 {
        self.active_line_energy(self.integer_delay) + self.filter_storage_energy()
    }

    fn tick(&mut self, sample_index: usize, total_samples: usize) -> f64 {
        if sample_index.is_multiple_of(self.config.update_stride) {
            self.update_loop(sample_index, total_samples);
        }
        let read_index =
            (self.write_index + self.line.len() - self.integer_delay) % self.line.len();
        let delayed = self.line[read_index];
        let mut value = (1.0 - self.config.damp) * delayed + self.config.damp * self.damping_x1;
        self.damping_x1 = delayed;
        if self.dispersion[0].coefficient().abs() > 1.0e-12 {
            value = self.dispersion[0].tick(value);
            value = self.dispersion[1].tick(value);
        }
        value = self.fractional.tick(value) * self.loop_gain;
        let excitation = self.excitation.get(sample_index).copied().unwrap_or(0.0);
        self.line[self.write_index] = value + excitation;
        self.write_index = (self.write_index + 1) % self.line.len();
        value
    }
}

pub fn run_string_experiment(
    config: StringExperimentConfig,
    policy: RetunePolicy,
) -> StringExperimentRun {
    let total_samples = (config.duration_s * config.sample_rate).round().max(1.0) as usize;
    let mut string = ReferenceString::new(config, policy);
    let excitation_samples = string.excitation.len();
    let mut output = Vec::with_capacity(total_samples);
    let mut output_peak: f64 = 0.0;
    let mut baseline_energy = 0.0;
    let mut max_energy_after_excitation: f64 = 0.0;
    let mut finite = true;
    for sample_index in 0..total_samples {
        let sample = string.tick(sample_index, total_samples);
        finite &= sample.is_finite();
        output_peak = output_peak.max(sample.abs());
        output.push(sample);
        let energy = string.proxy_energy();
        finite &= energy.is_finite();
        if sample_index == excitation_samples {
            baseline_energy = energy;
            max_energy_after_excitation = energy;
        } else if sample_index > excitation_samples {
            max_energy_after_excitation = max_energy_after_excitation.max(energy);
        }
    }
    if baseline_energy <= f64::MIN_POSITIVE {
        baseline_energy = string.proxy_energy().max(f64::MIN_POSITIVE);
    }
    let final_energy = string.proxy_energy();
    StringExperimentRun {
        result: StringExperimentResult {
            policy,
            samples: total_samples,
            output_peak,
            baseline_energy,
            max_energy_after_excitation,
            max_energy_ratio: max_energy_after_excitation / baseline_energy,
            final_energy,
            cumulative_line_control_work: string.cumulative_line_control_work,
            cumulative_filter_control_work: string.cumulative_filter_control_work,
            sum_abs_line_control_work: string.sum_abs_line_control_work,
            sum_abs_filter_control_work: string.sum_abs_filter_control_work,
            max_abs_line_control_work: string.max_abs_line_control_work,
            max_abs_filter_control_work: string.max_abs_filter_control_work,
            integer_delay_changes: string.integer_delay_changes,
            coefficient_updates: string.coefficient_updates,
            finite,
        },
        output,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn static_path_is_identical_across_policies() {
        let config = StringExperimentConfig {
            f1: 110.0,
            tension_cents: 0.0,
            ..StringExperimentConfig::default()
        };
        let legacy = run_string_experiment(config, RetunePolicy::Legacy);
        let filters = run_string_experiment(config, RetunePolicy::NeutralFilters);
        let remap = run_string_experiment(config, RetunePolicy::NeutralRemap);
        assert_eq!(legacy.output, filters.output);
        assert_eq!(legacy.output, remap.output);
    }

    #[test]
    fn neutral_filter_transport_eliminates_filter_update_work() {
        let config = StringExperimentConfig::default();
        let legacy = run_string_experiment(config, RetunePolicy::Legacy);
        let neutral = run_string_experiment(config, RetunePolicy::NeutralFilters);
        assert!(legacy.result.sum_abs_filter_control_work > 1.0e-5);
        assert!(neutral.result.max_abs_filter_control_work <= 1.0e-12);
        assert!(neutral.result.sum_abs_line_control_work > 1.0e-5);
    }

    #[test]
    fn neutral_remap_closes_declared_update_work() {
        let config = StringExperimentConfig::default();
        let run = run_string_experiment(config, RetunePolicy::NeutralRemap);
        assert!(run.result.max_abs_filter_control_work <= 1.0e-12);
        assert!(run.result.max_abs_line_control_work <= 1.0e-10);
        assert!(run.result.integer_delay_changes > 0);
        assert!(run.result.finite);
    }
}
