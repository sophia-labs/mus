//! Exact storage coordinates for the first-order allpass
//! `H(z) = (a + z^-1) / (1 + a z^-1)`.
//!
//! With the implementation state `s = x1 - a*y1`, one sample obeys
//!
//! ```text
//! y  = a*u + s
//! s' = (1-a^2)u - a*s
//! ```
//!
//! and therefore
//!
//! ```text
//! u^2 + s^2/(1-a^2) = y^2 + s'^2/(1-a^2).
//! ```
//!
//! When `a` changes, preserving the normalized coordinate
//! `s/sqrt(1-a^2)` gives an exact energy-neutral state transport for the
//! declared quadratic storage.

const COEFFICIENT_LIMIT: f64 = 0.999_5;
const METRIC_FLOOR: f64 = 1.0e-15;

fn clamp_coefficient(coefficient: f64) -> f64 {
    coefficient.clamp(-COEFFICIENT_LIMIT, COEFFICIENT_LIMIT)
}

fn metric_denominator(coefficient: f64) -> f64 {
    (1.0 - coefficient * coefficient).max(METRIC_FLOOR)
}

/// Canonical one-state coordinate used by the lossless allpass realization.
pub fn allpass_state(coefficient: f64, x1: f64, y1: f64) -> f64 {
    x1 - clamp_coefficient(coefficient) * y1
}

/// Normalized allpass state, whose squared magnitude is twice stored energy.
pub fn allpass_normalized_state(coefficient: f64, x1: f64, y1: f64) -> f64 {
    let coefficient = clamp_coefficient(coefficient);
    allpass_state(coefficient, x1, y1) / metric_denominator(coefficient).sqrt()
}

/// Declared internal storage energy of the first-order allpass.
pub fn allpass_storage_energy(coefficient: f64, x1: f64, y1: f64) -> f64 {
    let normalized = allpass_normalized_state(coefficient, x1, y1);
    0.5 * normalized * normalized
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct AllpassTransportReceipt {
    pub old_coefficient: f64,
    pub new_coefficient: f64,
    pub energy_before: f64,
    pub energy_after: f64,
    pub control_work: f64,
    pub old_normalized_state: f64,
    pub new_normalized_state: f64,
}

/// Change an allpass coefficient while preserving its normalized storage
/// coordinate. `y1` is retained and `x1` is reconstructed so the next sample
/// sees the transported canonical state.
pub fn neutral_allpass_state_transport(
    old_coefficient: f64,
    new_coefficient: f64,
    x1: f64,
    y1: f64,
) -> (f64, f64, AllpassTransportReceipt) {
    let old_coefficient = clamp_coefficient(old_coefficient);
    let new_coefficient = clamp_coefficient(new_coefficient);
    let old_normalized_state = allpass_normalized_state(old_coefficient, x1, y1);
    let new_state = old_normalized_state * metric_denominator(new_coefficient).sqrt();
    let new_y1 = y1;
    let new_x1 = new_state + new_coefficient * new_y1;
    let energy_before = allpass_storage_energy(old_coefficient, x1, y1);
    let energy_after = allpass_storage_energy(new_coefficient, new_x1, new_y1);
    let new_normalized_state = allpass_normalized_state(new_coefficient, new_x1, new_y1);
    (
        new_x1,
        new_y1,
        AllpassTransportReceipt {
            old_coefficient,
            new_coefficient,
            energy_before,
            energy_after,
            control_work: energy_after - energy_before,
            old_normalized_state,
            new_normalized_state,
        },
    )
}

/// Executable reference section used by tests and research examples.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct AllpassSection {
    coefficient: f64,
    x1: f64,
    y1: f64,
}

impl AllpassSection {
    pub fn new(coefficient: f64) -> Self {
        Self {
            coefficient: clamp_coefficient(coefficient),
            x1: 0.0,
            y1: 0.0,
        }
    }

    pub fn from_state(coefficient: f64, x1: f64, y1: f64) -> Self {
        Self {
            coefficient: clamp_coefficient(coefficient),
            x1,
            y1,
        }
    }

    pub fn coefficient(&self) -> f64 {
        self.coefficient
    }

    pub fn x1(&self) -> f64 {
        self.x1
    }

    pub fn y1(&self) -> f64 {
        self.y1
    }

    pub fn storage_energy(&self) -> f64 {
        allpass_storage_energy(self.coefficient, self.x1, self.y1)
    }

    pub fn normalized_state(&self) -> f64 {
        allpass_normalized_state(self.coefficient, self.x1, self.y1)
    }

    pub fn set_coefficient_legacy(&mut self, coefficient: f64) -> AllpassTransportReceipt {
        let old_coefficient = self.coefficient;
        let old_normalized_state = self.normalized_state();
        let energy_before = self.storage_energy();
        self.coefficient = clamp_coefficient(coefficient);
        let energy_after = self.storage_energy();
        AllpassTransportReceipt {
            old_coefficient,
            new_coefficient: self.coefficient,
            energy_before,
            energy_after,
            control_work: energy_after - energy_before,
            old_normalized_state,
            new_normalized_state: self.normalized_state(),
        }
    }

    pub fn set_coefficient_neutral(&mut self, coefficient: f64) -> AllpassTransportReceipt {
        let (x1, y1, receipt) = neutral_allpass_state_transport(
            self.coefficient,
            coefficient,
            self.x1,
            self.y1,
        );
        self.coefficient = receipt.new_coefficient;
        self.x1 = x1;
        self.y1 = y1;
        receipt
    }

    pub fn tick(&mut self, input: f64) -> f64 {
        let output = self.coefficient * input + self.x1 - self.coefficient * self.y1;
        self.x1 = input;
        self.y1 = output;
        output
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn per_sample_balance_is_exact_to_roundoff() {
        let mut section = AllpassSection::from_state(0.71, -0.33, 0.27);
        for input in [-1.0, -0.2, 0.0, 0.37, 1.4] {
            let before = input * input * 0.5 + section.storage_energy();
            let output = section.tick(input);
            let after = output * output * 0.5 + section.storage_energy();
            assert!((after - before).abs() <= before.max(1.0) * 2.0e-14);
        }
    }

    #[test]
    fn neutral_coefficient_transport_preserves_storage() {
        for old in [-0.98, -0.7, -0.1, 0.0, 0.4, 0.92] {
            for new in [-0.97, -0.4, 0.0, 0.61, 0.96] {
                let mut section = AllpassSection::from_state(old, 0.37, -0.29);
                let receipt = section.set_coefficient_neutral(new);
                assert!(receipt.control_work.abs() <= 3.0e-14);
                assert!(
                    (receipt.new_normalized_state - receipt.old_normalized_state).abs()
                        <= 3.0e-14
                );
            }
        }
    }

    #[test]
    fn legacy_coefficient_change_can_do_hidden_work() {
        let mut section = AllpassSection::from_state(0.05, 0.37, -0.29);
        let receipt = section.set_coefficient_legacy(0.96);
        assert!(receipt.control_work.abs() > 0.01);
    }
}
