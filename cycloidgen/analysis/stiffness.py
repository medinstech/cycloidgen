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

Transmission error
------------------
Stiffness is the *average* of that solve; :func:`analyse_transmission_error` is
its **ripple**.  Hold the load steady and turn the input: the rotation solved
above does not stay put, because the mesh keeps handing load from one contact to
the next.  What comes out of the output shaft is therefore not exactly
``input / ratio``, and the difference is the number that decides whether a drive
can position.  The rotation this module already solves at each crank angle *is*
that curve; the peak-to-peak of it is the transmission error.

Two things move it, and the solve sees both:

* **taking up the clearance** - which contact bites first changes through the
  cycle, and a contact with a short lever arm needs more rotation to close the
  same gap, so the rest position itself wanders;
* **deflecting** the contacts that are biting.

Which of the two dominates shifts with load, so this is *not* a number that
simply grows with torque.  It is also why a stiffer disc is not the fix it looks
like: stiffening the parts leaves the clearance term alone and puts what is left
on fewer pins.  A tighter fit, more output pins and a phased disc stack are the
levers that work.

Not modelled: pin position error, profile error and runout - the *manufacturing*
half of transmission error, which needs a tolerance input the app does not have.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np

from ..core.kinematics import SWEEP_STEPS, contacts, mesh_gaps, output_loads, sweep
from ..core.spec import GearSpec
from .mechanics import effective_modulus

__all__ = [
    "RAD_PER_ARCMIN",
    "StiffnessResult",
    "TransmissionErrorResult",
    "analyse_stiffness",
    "analyse_transmission_error",
    "line_contact_approach",
    "output_stage_period",
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

#: Steps per period for the output stage of the transmission-error sweep.  A
#: ripple has to be *resolved*, not averaged - a mean over one period converges
#: whatever the step count, a peak-to-peak only ever comes out too small - so
#: this is much finer than the stiffness sweep.  It is also nearly free: the
#: output stage needs no profile measurement.
_TE_STEPS = 48

#: The same for the ring stage, where every angle costs a profile measurement
#: per disc.  Twelve is where it stops mattering: the shipped pair lands within
#: a quarter of a percent of a sweep six times finer, and eight - the stiffness
#: sweep's own count - can be 30% low on the ring share.
_TE_RING_STEPS = 12


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


class _Contacts(NamedTuple):
    """One stage's contacts at one crank angle, ready for the solver."""

    c: np.ndarray        # per-contact compliance in delta = c * F**0.9
    arms: np.ndarray     # |moment arm| of each contact about the axis
    gaps: np.ndarray     # clearance each contact has to close before it bites
    ideal: np.ndarray    # the rigid-disc share of the load, for reference


def _ring_contacts(spec: GearSpec, cs, torque_per_disc: float) -> _Contacts | None:
    """Ring-pin contacts of one disc at one crank angle, or ``None`` if none bite."""
    loaded = cs.loaded_mask
    if not loaded.any():
        return None
    arms = np.abs(cs.moment_arms[loaded])
    ideal = cs.forces(torque_per_disc)[loaded]

    # counterface radius at the contact, negative where the disc is concave
    with np.errstate(divide="ignore"):
        r_face = np.where(np.abs(cs.curvature[loaded]) > 1e-12,
                          -1.0 / cs.curvature[loaded], 1e9)
    c = _fit_compliance(ideal, spec.disc_thickness, spec.pin_radius, r_face,
                        spec.disc_mat, spec.pin_mat, spec.pin_circle_radius)
    gaps = np.maximum(mesh_gaps(spec, cs.phi)[loaded], 0.0)
    return _Contacts(c=c, arms=arms, gaps=gaps, ideal=ideal)


def _output_contacts(spec: GearSpec, phi: float,
                     torque_per_disc: float) -> _Contacts | None:
    """Output pin/hole contacts of one disc at one crank angle.

    The pin sits in a hole ``E`` larger in radius, so the counterface is
    conforming and its radius is negative - the same convention the ring stage
    uses for a valley of the profile.
    """
    ol = output_loads(spec, phi, torque_per_disc)
    live = ol.forces > 0
    if not live.any():
        return None
    arms = np.abs(ol.moment_arms[live])
    r_p = spec.output_pin_diameter / 2.0
    c = _fit_compliance(ol.forces[live], spec.disc_thickness, r_p,
                        -(r_p + spec.eccentricity), spec.disc_mat, spec.pin_mat,
                        spec.pin_circle_radius)
    gaps = np.full(arms.shape, spec.hole_clearance / 2.0)
    return _Contacts(c=c, arms=arms, gaps=gaps, ideal=ol.forces[live])


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
        stage = _ring_contacts(spec, cs, torque_per_disc)
        if stage is None:
            continue
        c, arms, gaps, ideal = stage
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
    out_k: list[float] = []
    out_theta: list[float] = []
    for cs in picked:
        stage = _output_contacts(spec, cs.phi, torque_per_disc)
        if stage is None:
            continue
        c, arms, gaps, _ideal = stage
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


# --------------------------------------------------------- transmission error --


@dataclass
class TransmissionErrorResult:
    """Ripple in the output angle under a steady load, referred to the output."""

    peak_to_peak_arcmin: float       # the headline: the whole error band
    rms_arcmin: float
    ring_arcmin: float               # the ring stage's own share, peak to peak
    output_arcmin: float             # the output stage's own share
    ring_period_deg: float           # of crank, one lobe pitch
    output_period_deg: float         # of crank, one output-hole pitch

    @property
    def dominant_stage(self) -> str:
        return "ring" if self.ring_arcmin > self.output_arcmin else "output"


def output_stage_period(spec: GearSpec) -> float:
    """Crank angle over which the output-pin engagement pattern repeats, rad.

    Not the lobe pitch, and getting that wrong is the easy mistake here.  The
    disc's eccentricity direction, *seen from the carrier*, advances at
    ``(N-1)/N`` of the crank; the pin pattern repeats every ``2*pi/n`` of that.
    So the output stage's period is ``2*pi*N / (n*(N-1))`` - two and a half lobe
    pitches on a typical drive, and sampling only one lobe pitch of it reports
    about half the ripple that is really there.
    """
    return (2.0 * math.pi * spec.lobes
            / (spec.output_pin_count * (spec.lobes - 1)))


def _stack_rotation(parts: list[_Contacts], torque_Nmm: float) -> float:
    """Output rotation with every disc in the stack solved at once.

    The discs sit on different crank phases but drive one carrier, so they share
    a single rotation and split the torque between them however their own
    contacts decide.  Concatenating the stack's contacts into one system and
    solving it for the total torque is exactly that statement.

    :func:`analyse_stiffness` does not need this - phasing a stack does not move
    the *mean*, so multiplying one disc's stiffness by the disc count is right
    there.  It moves the *ripple* a great deal: discs half a lobe pitch apart
    are near antiphase, and most of the fundamental cancels.
    """
    if not parts:
        return 0.0
    theta, _forces = _solve_rotation(
        np.concatenate([p.c for p in parts]),
        np.concatenate([p.arms for p in parts]),
        np.concatenate([p.gaps for p in parts]),
        torque_Nmm)
    return theta


def _ripple(values: list[float]) -> tuple[float, float]:
    """Peak-to-peak and rms of a sampled cycle, both in arcmin."""
    a = np.asarray(values, dtype=float)
    if not a.size:
        return 0.0, 0.0
    return (float(a.max() - a.min()) / RAD_PER_ARCMIN,
            float(a.std()) / RAD_PER_ARCMIN)


def analyse_transmission_error(spec: GearSpec, steps: int = _TE_STEPS,
                               ring_steps: int = _TE_RING_STEPS
                               ) -> TransmissionErrorResult:
    """Ripple in the output angle through the mesh cycle, at the rated torque.

    Each stage is swept over **its own** period - see
    :func:`output_stage_period` - and the two are added.  The periods are
    incommensurate on any ordinary drive, so over a full output revolution the
    two ripples do eventually line up: the band the output wanders in is the sum
    of the two bands, and the variances add for the rms.

    Both halves of the error are in here, the clearance take-up and the elastic
    deflection, because the solve does not separate them and neither does the
    output shaft.  See the module docstring for what that means for reading the
    number - in particular that it does not simply grow with load.
    """
    torque_total = spec.output_torque_Nm * 1000.0
    torque_per_disc = torque_total / spec.disc_count
    phases = spec.disc_phases

    ring: list[float] = []
    states = sweep(spec, SWEEP_STEPS)
    for cs in states[:: max(1, len(states) // max(ring_steps, 1))]:
        parts = [p for p in (_ring_contacts(spec, contacts(spec, cs.phi + phase),
                                            torque_per_disc)
                             for phase in phases) if p is not None]
        if parts:
            ring.append(_stack_rotation(parts, torque_total))

    out: list[float] = []
    period = output_stage_period(spec)
    for phi in np.linspace(0.0, period, max(steps, 1), endpoint=False):
        parts = [p for p in (_output_contacts(spec, float(phi) + phase,
                                              torque_per_disc)
                             for phase in phases) if p is not None]
        if parts:
            out.append(_stack_rotation(parts, torque_total))

    ring_pp, ring_rms = _ripple(ring)
    out_pp, out_rms = _ripple(out)
    return TransmissionErrorResult(
        peak_to_peak_arcmin=ring_pp + out_pp,
        rms_arcmin=math.hypot(ring_rms, out_rms),
        ring_arcmin=ring_pp,
        output_arcmin=out_pp,
        ring_period_deg=360.0 / spec.lobes,
        output_period_deg=math.degrees(period),
    )
