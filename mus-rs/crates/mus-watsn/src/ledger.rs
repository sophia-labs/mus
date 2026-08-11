//! Explicit block/sample energy receipts.

#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct WorkFrame {
    pub energy_start: f64,
    pub source_work: f64,
    pub control_work: f64,
    pub internal_loss: f64,
    pub radiation_loss: f64,
    pub output_work: f64,
    pub energy_end: f64,
}

impl WorkFrame {
    pub fn expected_energy_end(&self) -> f64 {
        self.energy_start + self.source_work + self.control_work
            - self.internal_loss
            - self.radiation_loss
            - self.output_work
    }

    pub fn residual(&self) -> f64 {
        self.energy_end - self.expected_energy_end()
    }
}

#[derive(Debug, Clone, PartialEq, Default)]
pub struct WorkLedger {
    pub frames: u64,
    pub source_work: f64,
    pub control_work: f64,
    pub internal_loss: f64,
    pub radiation_loss: f64,
    pub output_work: f64,
    pub initial_energy: Option<f64>,
    pub final_energy: Option<f64>,
    pub max_abs_residual: f64,
    pub cumulative_residual: f64,
}

impl WorkLedger {
    pub fn push(&mut self, frame: WorkFrame) {
        if self.initial_energy.is_none() {
            self.initial_energy = Some(frame.energy_start);
        }
        self.final_energy = Some(frame.energy_end);
        self.frames += 1;
        self.source_work += frame.source_work;
        self.control_work += frame.control_work;
        self.internal_loss += frame.internal_loss;
        self.radiation_loss += frame.radiation_loss;
        self.output_work += frame.output_work;
        let residual = frame.residual();
        self.max_abs_residual = self.max_abs_residual.max(residual.abs());
        self.cumulative_residual += residual;
    }

    pub fn global_residual(&self) -> f64 {
        let Some(initial) = self.initial_energy else {
            return 0.0;
        };
        let final_energy = self.final_energy.unwrap_or(initial);
        final_energy
            - (initial + self.source_work + self.control_work
                - self.internal_loss
                - self.radiation_loss
                - self.output_work)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ledger_closes_over_multiple_frames() {
        let frames = [
            WorkFrame {
                energy_start: 1.0,
                source_work: 0.2,
                control_work: -0.05,
                internal_loss: 0.1,
                radiation_loss: 0.0,
                output_work: 0.0,
                energy_end: 1.05,
            },
            WorkFrame {
                energy_start: 1.05,
                source_work: 0.0,
                control_work: 0.1,
                internal_loss: 0.02,
                radiation_loss: 0.03,
                output_work: 0.0,
                energy_end: 1.10,
            },
        ];
        let mut ledger = WorkLedger::default();
        for frame in frames {
            assert!(frame.residual().abs() <= 1.0e-15);
            ledger.push(frame);
        }
        assert!(ledger.global_residual().abs() <= 1.0e-15);
    }
}
