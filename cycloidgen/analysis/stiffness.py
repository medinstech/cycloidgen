"""Torsional stiffness, lost motion, and clearance-aware load sharing.

Stiffness and backlash are the two numbers a gearbox datasheet leads with and
the two this app used to be silent about.  Both come out of the same model, so
they live together here.

The model
---------
Hold the input still and twist the output.  The disc and the output carrier turn
at the same rate in a fixed-ring drive - that is exactly what the output pins
are for - so with the crank locked the disc's rotation *is* the output rotation,
and two compliances sit in series between output torque and output angle:

1. **ring stage** - the disc rotating against the ring pins, resisted by one
   Hertzian line contact per engaged pin;
2. **output stage** - the disc rotating relative to the carrier, resisted by the
   output pins in their holes.

Everything else (housing, shaft, carrier plate, pins in bending) is taken as
rigid, so the result is an **upper bound on stiffness**.  A real drive also has
a compliant housing and a shaft in torsion, and measures softer.

Clearance
---------
Unlike the rest of the app's load model, this one *does* see clearance.  The gap
at each ring pin is measured geometrically - the true distance from the pin
centre to the manufactured profile, less the pin radius - so it is whatever the
selected offset mode actually produces.  A contact carries load only once the
disc has turned far enough to close its own gap:

    delta_i = max(0, theta * |h_i| - g_i)

Two things fall out of that, and they are the point of this module:

* the angle needed to close the *smallest* gap is the **lost motion**;
* when the gaps differ from pin to pin, the pins with the smallest gaps take
  more than their ideal share - the **load concentration** the rest of the app
  warns it cannot see.  An equidistant offset produces a uniform gap and so no
  concentration at all; growing the pin circle instead does not.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..core.kinematics import SWEEP_STEPS, mesh_gaps, output_loads, sweep
from ..core.spec import GearSpec
from .mechanics import effective_modulus

__all__ = [
    "RAD_PER_ARCMIN",
    "StiffnessResult",
    "analyse_stiffness",
    "line_contact_approach",
]

RAD_PER_ARCMIN = math.pi / (180.0 * 60.0)

#: Local exponent of the line-contact load/deflection law.  The exact Johnson
#: expression below is logarithmic in the load; fitting ``delta ~ F**0.9``
#: through the operating point reproduces it to well under a percent over any
#: plausible load range, and is the same exponent Palmgren's empirical roller
#: formula uses.  It buys a closed-form inverse and a closed-form stiffness.
_LOAD_EXPONENT = 0.9

#: Crank angles per lobe pitch for the stiffness sweep.  Stiffness barely moves
#: through the mesh cycle, so a coarse sweep is enough and keeps this cheap.
_STIFFNESS_STEPS = 8


def line_contact_approach(force_N: np.ndarray | float, length_mm: float,
                          R1_mm: np.ndarray | float, R2_mm: np.ndarray | float,
                          E1_GPa: float, nu1: float, E2_GPa: float, nu2: float,
                          reference_mm: float = 50.0) -> np.ndarray:
    """Elastic approach of two bodies in line contact, mm.  Johnson eq. 4.45.

    ``R2_mm`` is negative for a conforming (concave) counterface, which is the
    normal case here: the pin sits in a valley of the disc.

    A 2D line contact has no intrinsic length scale, so the approach comes out
    logarithmic in the size of the *bodies*, not only of the contact - press a
    cylinder onto a true half space and the answer diverges.  That is a property
    of the plane problem, not of this implementation.  The usual engineering
    reading is to take the body radii as the reference, capped at the size of
    the parts, which is what ``reference_mm`` does; the dependence is
    logarithmic, so the choice moves the answer by percent, not by factors.
    """
    f = np.asarray(force_N, dtype=float)
    cap = max(reference_mm, 1e-6)
    r1 = np.clip(np.abs(np.asarray(R1_mm, dtype=float)), 1e-9, cap)
    r2_signed = np.asarray(R2_mm, dtype=float)
    r2 = np.clip(np.abs(r2_signed), 1e-9, cap)
    line = max(length_mm, 1e-9)
    p = np.maximum(f, 0.0) / line                      # load per unit length

    e_star = effective_modulus(E1_GPa, nu1, E2_GPa, nu2)
    # signed: a negative counterface radius is a conforming (concave) face and
    # subtracts, which is what makes a pin in an oversized hole so much gentler
    # than the same pin on a flat.
    inv_req = 1.0 / r1 + np.sign(r2_signed) / r2
    r_eq = 1.0 / np.maximum(np.abs(inv_req), 1e-9)

    a = np.sqrt(np.maximum(4.0 * p * r_eq / (np.pi * e_star), 1e-30))
    c1 = (1.0 - nu1 ** 2) / (E1_GPa * 1000.0)
    c2 = (1.0 - nu2 ** 2) / (E2_GPa * 1000.0)
    # The bracket is ``ln(4R/a) - 1/2``, and 4R/a is enormous for any real
    # contact - a is a contact half-width and R a body radius.  Floor the
    # argument at sqrt(e) so the bracket cannot go negative on degenerate
    # geometry the checks are about to reject anyway: a negative "approach" is
    # not a softer contact, it is a NaN one power law later.
    floor = math.sqrt(math.e)
    term1 = c1 * (np.log(np.maximum(4.0 * r1 / a, floor)) - 0.5)
    term2 = c2 * (np.log(np.maximum(4.0 * r2 / a, floor)) - 0.5)
    return (2.0 * p / np.pi) * (term1 + term2)


@dataclass
class StiffnessResult:
    """Torsional behaviour of the drive, referred to the output shaft."""

    stiffness_Nm_per_arcmin: float
    ring_stage_Nm_per_arcmin: float
    output_stage_Nm_per_arcmin: float
    windup_arcmin: float               # elastic twist at the rated torque
    lost_motion_arcmin: float          # total play, both directions
    lost_motion_ring_arcmin: float
    lost_motion_output_arcmin: float
    backlash_total_arcmin: float       # lost motion plus windup
    pins_engaged: float                # mean, with clearance
    pins_engaged_ideal: float          # mean, ignoring clearance
    load_concentration: float          # peak pin force with clearance / without
    max_gap_spread_mm: float           # how unequal the gaps are

    @property
    def clearance_is_uniform(self) -> bool:
        return self.max_gap_spread_mm < 1e-4


def _fit_compliance(force_N: np.ndarray, length: float, r_pin: float,
                    r_face: np.ndarray | float, disc, pin,
                    reference_mm: float) -> np.ndarray:
    """Per-contact ``c`` in ``delta = c * F**0.9``, fitted at the working load."""
    ref = np.maximum(force_N, 1e-6)
    delta = line_contact_approach(ref, length, r_pin, r_face,
                                  disc.E_GPa, disc.nu, pin.E_GPa, pin.nu,
                                  reference_mm=reference_mm)
    # strictly positive: it is about to be a divisor under a fractional power
    return np.maximum(delta, 1e-12) / ref ** _LOAD_EXPONENT


def _solve_rotation(c: np.ndarray, arms: np.ndarray, gaps: np.ndarray,
                    torque_Nmm: float) -> tuple[float, np.ndarray]:
    """Rotation that transmits ``torque_Nmm`` through gapped nonlinear contacts.

    ``T(theta)`` is monotone increasing from zero, so a bracket-and-bisect is
    both sufficient and robust; there is no derivative to lose near the point
    where a contact first touches.
    """
    if not len(arms) or torque_Nmm <= 0:
        return 0.0, np.zeros_like(arms)

    def torque_at(theta: float) -> tuple[float, np.ndarray]:
        delta = np.maximum(theta * arms - gaps, 0.0)
        f = np.where(delta > 0, (delta / c) ** (1.0 / _LOAD_EXPONENT), 0.0)
        return float((f * arms).sum()), f

    lo = 0.0
    hi = max(gaps.max(), 0.0) / max(arms.max(), 1e-9) + 1e-6
    for _ in range(200):
        t, _f = torque_at(hi)
        if t >= torque_Nmm:
            break
        hi *= 2.0
    else:                                    # pathological; report it as rigid
        return hi, np.zeros_like(arms)

    for _ in range(80):
        mid = 0.5 * (lo + hi)
        t, _f = torque_at(mid)
        if t < torque_Nmm:
            lo = mid
        else:
            hi = mid
    theta = 0.5 * (lo + hi)
    return theta, torque_at(theta)[1]


def _stage_stiffness(c: np.ndarray, arms: np.ndarray, forces: np.ndarray,
                     theta: float, gaps: np.ndarray) -> float:
    """dT/dtheta in Nmm/rad at the solved point.

    ``F = (delta/c)**(1/n)`` differentiates to ``dF/ddelta = F/(n*delta)``, and
    ``ddelta_i/dtheta = |h_i|`` for every contact that is actually touching.
    """
    delta = np.maximum(theta * arms - gaps, 0.0)
    live = (delta > 0) & (forces > 0)
    if not live.any():
        return 0.0
    k = forces[live] / (_LOAD_EXPONENT * delta[live])          # N/mm
    return float((k * arms[live] ** 2).sum())                  # Nmm/rad


def analyse_stiffness(spec: GearSpec, steps: int = _STIFFNESS_STEPS) -> StiffnessResult:
    """Torsional stiffness, lost motion and clearance-aware load sharing."""
    torque_total_Nmm = spec.output_torque_Nm * 1000.0
    torque_per_disc = torque_total_Nmm / spec.disc_count
    length = spec.disc_thickness
    disc, pin = spec.disc_mat, spec.pin_mat

    states = sweep(spec, SWEEP_STEPS)
    picked = states[:: max(1, len(states) // max(steps, 1))]

    ring_k: list[float] = []
    ring_theta: list[float] = []
    engaged: list[int] = []
    engaged_ideal: list[int] = []
    concentration: list[float] = []
    spreads: list[float] = []
    ring_gap_close: list[float] = []

    for cs in picked:
        loaded = cs.loaded_mask
        if not loaded.any():
            continue
        arms = np.abs(cs.moment_arms[loaded])
        ideal = cs.forces(torque_per_disc)[loaded]

        # counterface radius at the contact, negative where the disc is concave
        with np.errstate(divide="ignore"):
            r_face = np.where(np.abs(cs.curvature[loaded]) > 1e-12,
                              -1.0 / cs.curvature[loaded], 1e9)
        c = _fit_compliance(ideal, length, spec.pin_radius, r_face, disc, pin,
                            spec.pin_circle_radius)

        gaps = np.maximum(mesh_gaps(spec, cs.phi)[loaded], 0.0)
        spreads.append(float(gaps.max() - gaps.min()))
        ring_gap_close.append(float((gaps / np.maximum(arms, 1e-9)).min()))

        theta, forces = _solve_rotation(c, arms, gaps, torque_per_disc)
        ring_theta.append(theta)
        k = _stage_stiffness(c, arms, forces, theta, gaps)
        if k > 0:
            ring_k.append(k)
        engaged.append(int((forces > 0).sum()))
        engaged_ideal.append(int((ideal > 0).sum()))
        if ideal.max() > 0:
            concentration.append(float(forces.max() / ideal.max()))

    # ---- output pin stage ---------------------------------------------------
    r_p = spec.output_pin_diameter / 2.0
    r_hole = r_p + spec.eccentricity
    out_k: list[float] = []
    out_theta: list[float] = []
    for cs in picked:
        ol = output_loads(spec, cs.phi, torque_per_disc)
        live = ol.forces > 0
        if not live.any():
            continue
        arms = np.abs(ol.moment_arms[live])
        c = _fit_compliance(ol.forces[live], length, r_p, -r_hole, disc, pin,
                            spec.pin_circle_radius)
        gaps = np.full(arms.shape, spec.hole_clearance / 2.0)
        theta, forces = _solve_rotation(c, arms, gaps, torque_per_disc)
        out_theta.append(theta)
        k = _stage_stiffness(c, arms, forces, theta, gaps)
        if k > 0:
            out_k.append(k)

    n = spec.disc_count
    # discs act in parallel on one carrier, so their stiffnesses add
    k_ring = float(np.mean(ring_k)) * n if ring_k else 0.0
    k_out = float(np.mean(out_k)) * n if out_k else 0.0
    k_series = (1.0 / (1.0 / k_ring + 1.0 / k_out)) if k_ring > 0 and k_out > 0 else 0.0

    def to_nm_arcmin(k_nmm_rad: float) -> float:
        return k_nmm_rad / 1000.0 * RAD_PER_ARCMIN

    # ---- lost motion --------------------------------------------------------
    # the drive must traverse each gap in both directions, hence the factor 2
    lost_ring = 2.0 * (max(ring_gap_close) if ring_gap_close else 0.0) / RAD_PER_ARCMIN
    lost_out = (2.0 * (spec.hole_clearance / 2.0) / spec.output_bolt_circle_radius
                / RAD_PER_ARCMIN)
    lost_total = lost_ring + lost_out

    windup = 0.0
    if ring_theta:
        # theta already includes closing the gap; the elastic part is what is
        # left once the play is taken out
        elastic_ring = max(float(np.mean(ring_theta)) - 0.5 * lost_ring * RAD_PER_ARCMIN, 0.0)
        elastic_out = max(float(np.mean(out_theta)) - 0.5 * lost_out * RAD_PER_ARCMIN,
                          0.0) if out_theta else 0.0
        windup = (elastic_ring + elastic_out) / RAD_PER_ARCMIN

    return StiffnessResult(
        stiffness_Nm_per_arcmin=to_nm_arcmin(k_series),
        ring_stage_Nm_per_arcmin=to_nm_arcmin(k_ring),
        output_stage_Nm_per_arcmin=to_nm_arcmin(k_out),
        windup_arcmin=windup,
        lost_motion_arcmin=lost_total,
        lost_motion_ring_arcmin=lost_ring,
        lost_motion_output_arcmin=lost_out,
        backlash_total_arcmin=lost_total + windup,
        pins_engaged=float(np.mean(engaged)) if engaged else 0.0,
        pins_engaged_ideal=float(np.mean(engaged_ideal)) if engaged_ideal else 0.0,
        load_concentration=float(np.mean(concentration)) if concentration else 1.0,
        max_gap_spread_mm=float(np.max(spreads)) if spreads else 0.0,
    )
