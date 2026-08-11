//! Sparse ordered factor programs.

use crate::givens::givens;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PlaneRotation {
    pub left: usize,
    pub right: usize,
    pub angle: f64,
}

impl PlaneRotation {
    pub fn inverse(self) -> Self {
        Self {
            angle: -self.angle,
            ..self
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProgramError {
    DimensionMismatch { expected: usize, actual: usize },
    RepeatedCoordinate { index: usize },
    CoordinateOutOfRange { index: usize, dimension: usize },
}

#[derive(Debug, Clone, PartialEq)]
pub struct OperatorProgram {
    dimension: usize,
    factors: Vec<PlaneRotation>,
}

impl OperatorProgram {
    pub fn new(dimension: usize, factors: Vec<PlaneRotation>) -> Result<Self, ProgramError> {
        for factor in &factors {
            if factor.left == factor.right {
                return Err(ProgramError::RepeatedCoordinate { index: factor.left });
            }
            for index in [factor.left, factor.right] {
                if index >= dimension {
                    return Err(ProgramError::CoordinateOutOfRange { index, dimension });
                }
            }
        }
        Ok(Self { dimension, factors })
    }

    pub fn dimension(&self) -> usize {
        self.dimension
    }

    pub fn factors(&self) -> &[PlaneRotation] {
        &self.factors
    }

    /// Apply factors in authored execution order. If factors are
    /// `[F0,F1,...]`, the resulting matrix is `... F1 F0` on column states.
    pub fn apply(&self, state: &mut [f64]) -> Result<(), ProgramError> {
        if state.len() != self.dimension {
            return Err(ProgramError::DimensionMismatch {
                expected: self.dimension,
                actual: state.len(),
            });
        }
        for factor in &self.factors {
            let (left, right) = givens(state[factor.left], state[factor.right], factor.angle);
            state[factor.left] = left;
            state[factor.right] = right;
        }
        Ok(())
    }

    pub fn inverse(&self) -> Self {
        let factors = self
            .factors
            .iter()
            .rev()
            .map(|factor| factor.inverse())
            .collect();
        Self {
            dimension: self.dimension,
            factors,
        }
    }

    /// Program whose resulting matrix is `A B A^-1 B^-1`.
    /// Since column-state execution applies the rightmost factor first, the
    /// authored execution sequence is `B^-1, A^-1, B, A`.
    pub fn commutator(
        dimension: usize,
        a: PlaneRotation,
        b: PlaneRotation,
    ) -> Result<Self, ProgramError> {
        Self::new(dimension, vec![b.inverse(), a.inverse(), b, a])
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn energy(state: &[f64]) -> f64 {
        state.iter().map(|value| value * value).sum::<f64>()
    }

    #[test]
    fn arbitrary_program_preserves_euclidean_energy() {
        let program = OperatorProgram::new(
            4,
            vec![
                PlaneRotation {
                    left: 0,
                    right: 1,
                    angle: 0.31,
                },
                PlaneRotation {
                    left: 1,
                    right: 3,
                    angle: -0.47,
                },
                PlaneRotation {
                    left: 2,
                    right: 0,
                    angle: 1.2,
                },
            ],
        )
        .unwrap();
        let mut state = [0.7, -0.2, 1.1, 0.4];
        let before = energy(&state);
        program.apply(&mut state).unwrap();
        assert!((energy(&state) - before).abs() <= before * 2.0e-14);
    }

    #[test]
    fn inverse_program_recovers_state() {
        let program = OperatorProgram::new(
            3,
            vec![
                PlaneRotation {
                    left: 0,
                    right: 1,
                    angle: 0.31,
                },
                PlaneRotation {
                    left: 1,
                    right: 2,
                    angle: -0.47,
                },
            ],
        )
        .unwrap();
        let original = [0.7, -0.2, 1.1];
        let mut state = original;
        program.apply(&mut state).unwrap();
        program.inverse().apply(&mut state).unwrap();
        for (actual, expected) in state.iter().zip(original.iter()) {
            assert!((actual - expected).abs() <= 2.0e-14);
        }
    }

    #[test]
    fn overlapping_commutator_is_nontrivial_but_zero_work() {
        let a = PlaneRotation {
            left: 0,
            right: 1,
            angle: 0.31,
        };
        let b = PlaneRotation {
            left: 1,
            right: 2,
            angle: -0.47,
        };
        let program = OperatorProgram::commutator(3, a, b).unwrap();
        let mut state = [1.0, 0.0, 0.0];
        let before = energy(&state);
        program.apply(&mut state).unwrap();
        assert!((energy(&state) - before).abs() <= 2.0e-14);
        assert!((state[1].abs() + state[2].abs()) > 0.01);
    }
}
