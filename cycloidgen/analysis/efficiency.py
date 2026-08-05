"""Friction loss and efficiency estimate.

Four loss paths are modelled, all evaluated from the verified kinematics rather
than from a rule of thumb:

1. ring pin / disc contact sliding  - the cycloid slides everywhere except at the
   instantaneous pitch point, so this dominates in a dry printed drive
2. output pin / hole sliding        - the disc translates on a circle of radius E
   relative to the carrier
3. eccentric bearing drag           - runs at nearly full input speed
4. main output bearing drag         - slow but carries the whole reaction

Rolling elements (needle rollers on the ring pins, bushings on the output pins)
replace the sliding coefficient with a much smaller rolling one.  The same
choice runs the other way at the cam: a drive built without a cam bearing has a
plain journal there instead, at nearly full input speed, and pays the sliding
coefficient for it.  A bearing the drive does not carry - a flange located by
the machine it drives - is not counted here at all, because that drag is the
machine's and not this gearbox's.

Not modelled: seal drag, lubricant churning, bearing preload, and any losses from
misalignment or clearance take-up.  The result is therefore an **upper bound**.
Well-built steel drives measure 88-94%; a printed one with fixed pins is usually
somewhere in 45-65%.  If this function reports much above that band for the same
construction, the difference is the unmodelled paths, not free efficiency.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.kinematics import SWEEP_STEPS, output_loads, sweep
from ..core.spec import GearSpec

__all__ = ["EfficiencyResult", "analyse_efficiency"]

#: Effective friction coefficient at a loaded rolling contact.  This is a
#: *calibration constant*, not a first-principles value: a free-running needle
#: bearing sits near 0.002, but a roller in a cycloidal mesh also skids and
#: deforms under a cycling load, and this value is what puts a rolling steel
#: drive into the 88-94% band that such drives actually measure.
ROLLING_MU = 0.018
#: Rolling friction coefficient of a lubricated ball/needle bearing.
BEARING_MU = 0.0015


@dataclass
class EfficiencyResult:
    efficiency: float
    loss_ring_pins_W: float
    loss_output_pins_W: float
    loss_bearings_W: float
    output_power_W: float
    input_power_W: float
    input_torque_Nm: float

    @property
    def total_loss_W(self) -> float:
        return self.loss_ring_pins_W + self.loss_output_pins_W + self.loss_bearings_W


def analyse_efficiency(spec: GearSpec, steps: int = SWEEP_STEPS) -> EfficiencyResult:
    """Average the loss over one lobe pitch and turn it into an efficiency."""
    omega_in = spec.input_rpm * 2.0 * np.pi / 60.0
    omega_out = omega_in / spec.ratio
    torque_out_Nmm = spec.output_torque_Nm * 1000.0
    torque_per_disc = torque_out_Nmm / spec.disc_count

    mu_ring = ROLLING_MU if spec.ring_pins_are_rollers else spec.friction_coefficient
    mu_out = ROLLING_MU if spec.output_pins_are_rollers else spec.friction_coefficient

    ring_losses: list[float] = []
    out_losses: list[float] = []
    ecc_losses: list[float] = []

    # relative sliding speed of the disc in the carrier frame (mm/s)
    v_out = spec.eccentricity * omega_in * (1.0 - 1.0 / spec.ratio)
    # eccentric bearing: inner race at input speed, outer at disc speed
    omega_rel = omega_in * (1.0 - 1.0 / spec.ratio)
    d_mean = (spec.input_shaft_diameter + spec.center_bore_diameter) / 2.0

    # With no cam bearing the disc bore is a plain journal on the cam: the same
    # torque expression, but the sliding coefficient instead of the rolling one
    # and the cam's own radius as the arm.  It is the fastest-turning contact in
    # the drive, so this is not a small difference - which is the point of being
    # able to choose it.
    if spec.cam_bearing_fitted:
        mu_ecc, r_ecc = BEARING_MU, d_mean / 2.0
    else:
        mu_ecc, r_ecc = spec.friction_coefficient, spec.cam_diameter / 2.0

    for cs in sweep(spec, steps):
        f = cs.forces(torque_per_disc)                       # N
        v = cs.sliding_speed * omega_in                      # mm/s
        ring_losses.append(float((mu_ring * f * v).sum()) / 1000.0)   # W

        ol = output_loads(spec, cs.phi, torque_per_disc)
        out_losses.append(float(mu_out * ol.forces.sum() * v_out) / 1000.0)

        fv = (f[:, None] * cs.normals).sum(axis=0)
        f_ecc = float(np.hypot(*fv))
        ecc_losses.append(mu_ecc * f_ecc * r_ecc * omega_rel / 1000.0)

    n = spec.disc_count
    loss_ring = float(np.mean(ring_losses)) * n
    loss_out = float(np.mean(out_losses)) * n
    loss_ecc = float(np.mean(ecc_losses)) * n

    # Main output bearing: slow, but it reacts the whole output torque.  With no
    # bearing fitted the flange is located by the machine it drives, so that drag
    # belongs to the machine and not to this gearbox - it does not disappear, it
    # stops being ours to count.
    f_main = 2.0 * spec.output_torque_Nm * 1000.0 / spec.output_bolt_circle_radius
    loss_main = (BEARING_MU * f_main * spec.center_bore_diameter / 2.0
                 * omega_out / 1000.0) if spec.output_bearing_fitted else 0.0

    p_out = spec.output_torque_Nm * omega_out
    p_in = p_out + loss_ring + loss_out + loss_ecc + loss_main
    eff = p_out / p_in if p_in > 0 else 0.0

    return EfficiencyResult(
        efficiency=eff,
        loss_ring_pins_W=loss_ring,
        loss_output_pins_W=loss_out,
        loss_bearings_W=loss_ecc + loss_main,
        output_power_W=p_out,
        input_power_W=p_in,
        input_torque_Nm=(p_in / omega_in) if omega_in > 0 else 0.0,
    )
