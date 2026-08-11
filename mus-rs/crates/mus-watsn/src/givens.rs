//! Exact three-mode ordered-scattering identities.

use std::f64::consts::PI;

pub type Mat3 = [[f64; 3]; 3];

pub fn givens(a: f64, b: f64, angle: f64) -> (f64, f64) {
    let (sin_angle, cos_angle) = angle.sin_cos();
    (
        cos_angle * a - sin_angle * b,
        sin_angle * a + cos_angle * b,
    )
}

pub fn rotation_01(angle: f64) -> Mat3 {
    let (sin_angle, cos_angle) = angle.sin_cos();
    [
        [cos_angle, -sin_angle, 0.0],
        [sin_angle, cos_angle, 0.0],
        [0.0, 0.0, 1.0],
    ]
}

pub fn rotation_12(angle: f64) -> Mat3 {
    let (sin_angle, cos_angle) = angle.sin_cos();
    [
        [1.0, 0.0, 0.0],
        [0.0, cos_angle, -sin_angle],
        [0.0, sin_angle, cos_angle],
    ]
}

pub fn mat3_mul(left: Mat3, right: Mat3) -> Mat3 {
    let mut result = [[0.0; 3]; 3];
    for row in 0..3 {
        for column in 0..3 {
            result[row][column] = (0..3)
                .map(|inner| left[row][inner] * right[inner][column])
                .sum();
        }
    }
    result
}

pub fn mat3_transpose(matrix: Mat3) -> Mat3 {
    let mut result = [[0.0; 3]; 3];
    for row in 0..3 {
        for column in 0..3 {
            result[row][column] = matrix[column][row];
        }
    }
    result
}

pub fn commutator_matrix(angle_a: f64, angle_b: f64) -> Mat3 {
    let a = rotation_01(angle_a);
    let b = rotation_12(angle_b);
    mat3_mul(
        mat3_mul(mat3_mul(a, b), mat3_transpose(a)),
        mat3_transpose(b),
    )
}

pub fn principal_rotation_angle(matrix: Mat3) -> f64 {
    let trace = matrix[0][0] + matrix[1][1] + matrix[2][2];
    ((trace - 1.0) * 0.5).clamp(-1.0, 1.0).acos()
}

/// Existing Ariadne order-defect observable, equal to the spectral-norm
/// chord from the corresponding three-mode commutator to identity.
pub fn order_defect(angle_a: f64, angle_b: f64) -> f64 {
    let x = (0.5 * angle_a).sin().powi(2);
    let y = (0.5 * angle_b).sin().powi(2);
    (16.0 * x * y * (1.0 - x * y)).max(0.0).sqrt()
}

/// Both balanced solutions `a=b=t` for a principal commutator angle.
/// The first is the minimal-control branch; the second is the high-coupling
/// branch approaching `pi` as the target angle approaches zero.
pub fn balanced_inverse_branches(target_angle: f64) -> (f64, f64) {
    let target_angle = target_angle.clamp(0.0, PI);
    let quarter = target_angle * 0.25;
    let minimal = 2.0 * quarter.sin().sqrt().asin();
    let high = 2.0 * quarter.cos().sqrt().asin();
    (minimal, high)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_chord_relation_holds() {
        for angle_a in [-1.1, -0.47, -0.1, 0.0, 0.31, 0.9] {
            for angle_b in [-0.8, -0.2, 0.0, 0.53, 1.2] {
                let angle = principal_rotation_angle(commutator_matrix(angle_a, angle_b));
                let chord = 2.0 * (0.5 * angle).sin();
                assert!((order_defect(angle_a, angle_b) - chord).abs() <= 2.0e-14);
            }
        }
    }

    #[test]
    fn both_inverse_branches_hit_the_target() {
        for degrees in [0.01_f64, 1.0, 8.24, 45.0, 90.0, 179.0] {
            let target = degrees.to_radians();
            let (low, high) = balanced_inverse_branches(target);
            for control in [low, high] {
                let actual = principal_rotation_angle(commutator_matrix(control, control));
                assert!((actual - target).abs() <= 2.0e-12);
            }
        }
    }
}
