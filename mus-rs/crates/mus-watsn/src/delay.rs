//! Periodic delay-state remapping with an explicit quadratic-energy receipt.

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PeriodicRemapReceipt {
    pub source_len: usize,
    pub target_len: usize,
    pub energy_before: f64,
    pub raw_energy_after: f64,
    pub energy_after: f64,
    pub scale: f64,
    pub control_work: f64,
}

pub fn quadratic_energy(state: &[f64]) -> f64 {
    0.5 * state.iter().map(|value| value * value).sum::<f64>()
}

/// Periodic linear resampling. This preserves phase continuity around the
/// loop but does not by itself preserve the declared quadratic energy.
pub fn resample_periodic_linear(source: &[f64], target: &mut [f64]) {
    assert!(!source.is_empty(), "source state must be non-empty");
    assert!(!target.is_empty(), "target state must be non-empty");
    if source.len() == target.len() {
        target.copy_from_slice(source);
        return;
    }
    let source_len = source.len();
    let ratio = source_len as f64 / target.len() as f64;
    for (index, slot) in target.iter_mut().enumerate() {
        let position = index as f64 * ratio;
        let left = position.floor() as usize % source_len;
        let right = (left + 1) % source_len;
        let fraction = position - position.floor();
        *slot = source[left] + fraction * (source[right] - source[left]);
    }
}

/// Resample a periodic state and apply the unique positive scalar correction
/// that preserves its declared Euclidean storage energy for this state.
///
/// The correction is state-contingent rather than a globally linear isometry;
/// it is therefore a useful real-time approximation and diagnostic, not a
/// substitute for the dense polar oracle described by the paper.
pub fn resample_periodic_linear_neutral(
    source: &[f64],
    target: &mut [f64],
) -> PeriodicRemapReceipt {
    resample_periodic_linear(source, target);
    let energy_before = quadratic_energy(source);
    let raw_energy_after = quadratic_energy(target);
    let scale = if energy_before <= f64::MIN_POSITIVE {
        0.0
    } else if raw_energy_after <= f64::MIN_POSITIVE {
        1.0
    } else {
        (energy_before / raw_energy_after).sqrt()
    };
    if energy_before <= f64::MIN_POSITIVE {
        target.fill(0.0);
    } else {
        for value in target.iter_mut() {
            *value *= scale;
        }
    }
    let energy_after = quadratic_energy(target);
    PeriodicRemapReceipt {
        source_len: source.len(),
        target_len: target.len(),
        energy_before,
        raw_energy_after,
        energy_after,
        scale,
        control_work: energy_after - energy_before,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture(len: usize) -> Vec<f64> {
        (0..len)
            .map(|index| {
                let phase = std::f64::consts::TAU * index as f64 / len as f64;
                0.8 * phase.sin() + 0.21 * (3.0 * phase + 0.2).cos()
            })
            .collect()
    }

    #[test]
    fn neutral_resample_preserves_energy_across_rank_changes() {
        for old_len in [8, 13, 31, 64, 127, 256] {
            let source = fixture(old_len);
            for new_len in [5, 8, 21, 64, 111, 384] {
                let mut target = vec![0.0; new_len];
                let receipt = resample_periodic_linear_neutral(&source, &mut target);
                let tolerance = receipt.energy_before.max(1.0) * 5.0e-14;
                assert!(receipt.control_work.abs() <= tolerance);
            }
        }
    }

    #[test]
    fn raw_resampling_has_nontrivial_energy_bias() {
        let source = fixture(47);
        let mut target = vec![0.0; 113];
        resample_periodic_linear(&source, &mut target);
        assert!((quadratic_energy(&target) - quadratic_energy(&source)).abs() > 1.0);
    }
}
