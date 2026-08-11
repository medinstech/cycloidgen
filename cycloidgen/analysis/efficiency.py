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

The *sliding* coefficient is no longer a number off the spec.  It comes from
:mod:`cycloidgen.analysis.lubrication`, which builds the film at each of those
contacts and returns the friction the regime earns - so it depends on the load,
the speed, the surface finish, what is in there and how hot it has got.  With no
lubricant that resolves to the design's own ``friction_coefficient`` and nothing
about the answer changes.  The rolling coefficients below stay constants,
deliberately: a needle roller's own contact is the bearing's business and not
this mesh's, and pretending otherwise would put a film model inside a catalogue
part that already comes with a rated life.

Not modelled: seal drag, lubricant churning, bearing preload, and any losses from
misalignment or clearance take-up.  The result is therefore an **upper bound**.
Well-built steel drives measure 88-94%; a printed one with fixed pins is usually
somewhere in 45-65%.  If this function reports much above that band for the same
construction, the difference is the unmodelled paths, not free efficiency.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.kinematics import SWEEP_STEPS, output_loads, output_sweep_angles, sweep
from ..core.spec import GearSpec
from .lubrication import LubricationResult, analyse_lubrication

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
    #: The regime behind the sliding coefficients above, at the temperature this
    #: was evaluated at.  Carried on the result because the coefficients are no
    #: longer constants anybody can look up - they are an output now, and the
    #: film they came from is what makes them arguable.
    lubrication: LubricationResult

    @property
    def total_loss_W(self) -> float:
        return self.loss_ring_pins_W + self.loss_output_pins_W + self.loss_bearings_W


def analyse_efficiency(spec: GearSpec, steps: int = SWEEP_STEPS,
                       temperature_C: float | None = None) -> EfficiencyResult:
    """Average the loss over one lobe pitch and turn it into an efficiency.

    ``temperature_C`` is where the lubricant is asked how thick it is.  It
    defaults to ambient, which is the cold-start answer; the running one is a
    fixed point, because the losses computed here are what heats the drive that
    thins the oil that sets the losses.  :func:`cycloidgen.analysis.thermal
    .solve_operating_point` closes that loop.
    """
    omega_in = spec.input_rpm * 2.0 * np.pi / 60.0
    omega_out = omega_in / spec.ratio
    torque_out_Nmm = spec.output_torque_Nm * 1000.0
    torque_per_disc = torque_out_Nmm / spec.disc_count

    # relative sliding speed of the disc in the carrier frame (mm/s)
    v_out = spec.eccentricity * omega_in * (1.0 - 1.0 / spec.ratio)
    # eccentric bearing: inner race at input speed, outer at disc speed
    omega_rel = omega_in * (1.0 - 1.0 / spec.ratio)
    d_mean = (spec.input_shaft_diameter + spec.center_bore_diameter) / 2.0
    r_cam = spec.cam_diameter / 2.0
    v_cam = omega_rel * r_cam / 1000.0                       # m/s

    # One sweep, and the friction coefficients applied to the total afterwards.
    # They cannot be applied inside it: the coefficient at a sliding contact now
    # comes from a film thickness, the film thickness from the load, and the load
    # is what this loop is working out.  So the loop collects what is independent
    # of friction and the coefficients multiply it at the end.
    ring_fv: list[float] = []                                # sum(F*v), N mm/s
    out_f: list[float] = []                                  # sum(F), N
    ecc_f: list[float] = []                                  # crank reaction, N
    peak_pin = 0.0
    peak_out = 0.0
    peak_slide = 0.0

    for cs in sweep(spec, steps):
        f = cs.forces(torque_per_disc)                       # N
        v = cs.sliding_speed * omega_in                      # mm/s
        ring_fv.append(float((f * v).sum()))
        peak_pin = max(peak_pin, float(f.max(initial=0.0)))
        peak_slide = max(peak_slide, float(cs.sliding_speed.max(initial=0.0)))

        fv = (f[:, None] * cs.normals).sum(axis=0)
        ecc_f.append(float(np.hypot(*fv)))

    # Output pins on their own period - see output_stage_period.  Splitting the
    # loop is exactly valid for what comes out of it: the total loss is a sum of
    # per-stage means, and the mean of a sum is the sum of the means however
    # differently the two stages are sampled.
    for phi in output_sweep_angles(spec.lobes, spec.output_pin_count, steps):
        ol = output_loads(spec, float(phi), torque_per_disc)
        out_f.append(float(ol.forces.sum()))
        peak_out = max(peak_out, float(ol.forces.max(initial=0.0)))

    # The film is evaluated at the peak load of the cycle, which is the thinnest
    # it gets.  A coefficient averaged over the cycle would be kinder and would
    # describe a contact that is not the one that wears.
    lub = analyse_lubrication(
        spec, ring_load_N=peak_pin, output_load_N=peak_out,
        cam_load_N=max(ecc_f, default=0.0),
        ring_sliding_m_s=peak_slide * omega_in / 1000.0,
        output_sliding_m_s=v_out / 1000.0, cam_sliding_m_s=v_cam,
        temperature_C=temperature_C)

    mu_ring = ROLLING_MU if spec.ring_pins_are_rollers else lub["Ring pin / disc flank"].mu
    mu_out = ROLLING_MU if spec.output_pins_are_rollers else lub["Output pin / disc hole"].mu

    # With no cam bearing the disc bore is a plain journal on the cam: the same
    # torque expression, but the sliding coefficient instead of the rolling one
    # and the cam's own radius as the arm.  It is the fastest-turning contact in
    # the drive, so this is not a small difference - which is the point of being
    # able to choose it.
    if spec.cam_bearing_fitted:
        mu_ecc, r_ecc = BEARING_MU, d_mean / 2.0
    else:
        mu_ecc, r_ecc = lub["Disc bore / cam"].mu, r_cam

    n = spec.disc_count
    loss_ring = mu_ring * float(np.mean(ring_fv)) / 1000.0 * n
    loss_out = mu_out * float(np.mean(out_f)) * v_out / 1000.0 * n
    loss_ecc = mu_ecc * float(np.mean(ecc_f)) * r_ecc * omega_rel / 1000.0 * n

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
        lubrication=lub,
    )
