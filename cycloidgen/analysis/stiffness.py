"""Torsional stiffness, lost motion, and clearance-aware load sharing.

Stiffness and backlash are the two numbers a gearbox datasheet leads with and
the two this app used to be silent about.  Both come out of the same model, so
they live together here.

The model
---------
Hold the input still and twist the output.  The disc and the output carrier turn
at the same rate in a fixed-ring drive - that is exactly what the output pins
are for - so with the crank locked the disc's rotation *is* the output rotation,
and the compliances between output torque and output angle sit in series:

1. **ring stage** - the disc rotating against the ring pins, resisted by one
   Hertzian line contact per engaged pin;
2. **output stage** - the disc rotating relative to the carrier, resisted by the
   output pins in their holes;
3. **the structure** - the parts those contacts are mounted in, which used to be
   taken as rigid and are not.  See :mod:`cycloidgen.analysis.compliance`.

Both decompositions are reported, because both are worth knowing: the contacts
alone are what the mesh can do, and they were the whole of this model until the
structure went in.  On a printed drive the two halves are comparable, which is
already enough to cost the answer a third.  The better the mesh, the worse the
imbalance: a ground steel drive stiffens its contacts by two orders of magnitude
and its cantilevered carrier pins by nothing at all, and ends up an order of
magnitude softer than its own mesh.

That is a *first-principles* accounting of the parts, not a calibrated one.  It
is no longer an upper bound, but a real drive still has joints, fits and
fasteners that nothing here models, so it will measure softer again.

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

from ..core.kinematics import (
    SWEEP_STEPS,
    contacts,
    mesh_gaps,
    output_loads,
    ring_stage_period,
    sweep,
)
from ..core.kinematics import output_stage_period as _output_stage_period
from ..core.spec import GearSpec
from .compliance import StructureStiffness, analyse_parts, series_stiffness
from .mechanics import effective_modulus
from .tolerance import (
    DEFAULT_SAMPLES,
    DEFAULT_TE_SAMPLES,
    carrier_position_errors,
    ring_position_errors,
    tolerance_samples,
)

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
#: per disc.
#:
#: Twelve was enough while the ring sweep covered one lobe pitch.  It covers the
#: whole ring-stage period now - ten lobe pitches on the default drive - and
#: twelve samples across that is less than one per pitch, which resolved nothing
#: and read 11% low on the ring share.  Forty-eight is where it stops moving:
#: identical to using every state the shared sweep has.
#:
#: That leaves it bounded by ``SWEEP_STEPS`` rather than by this number.  All
#: 144 states put the ring share about 2% under a sweep four times finer - 0.7%
#: on the total, since the output stage carries most of it - and closing that
#: last 2% means quadrupling the sweep every other study shares.  It is left
#: open, and stated, rather than paid for: a transmission error 2% conservative
#: on one of its two halves is not what limits this model.
_TE_RING_STEPS = 48


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

    stiffness_Nm_per_arcmin: float     # everything in series: the answer
    contact_only_Nm_per_arcmin: float  # the two contact stages alone
    structure_Nm_per_arcmin: float     # every part outside the contacts
    structure: StructureStiffness      # and each of those on its own
    ring_stage_Nm_per_arcmin: float    # ring contacts only
    output_stage_Nm_per_arcmin: float  # output contacts only
    windup_arcmin: float               # elastic twist at the rated torque
    lost_motion_arcmin: float          # total play, both directions
    lost_motion_ring_arcmin: float
    lost_motion_output_arcmin: float
    backlash_total_arcmin: float       # lost motion plus windup
    pins_engaged: float                # mean, with clearance
    pins_engaged_ideal: float          # mean, ignoring clearance
    load_concentration: float          # peak pin force with clearance / without
    max_gap_spread_mm: float           # how unequal the gaps are

    #: How many rings the position tolerance was sampled over.  One means the
    #: drawing carries no tolerance and the pins are where it says they are, in
    #: which case the three figures below are that one ring and say nothing.
    rings_sampled: int = 1
    stiffness_p10_Nm_per_arcmin: float = 0.0   # the soft decile of the batch
    load_concentration_p90: float = 0.0
    lost_motion_p90_arcmin: float = 0.0
    #: Deepest a sampled ring drove a pin past the profile, mm.  Anything above
    #: zero means the tolerance has eaten the clearance on some builds, and the
    #: figures above are the optimistic reading of a ring that binds.
    position_interference_mm: float = 0.0

    @property
    def clearance_is_uniform(self) -> bool:
        return self.max_gap_spread_mm < 1e-4

    @property
    def tolerance_was_sampled(self) -> bool:
        return self.rings_sampled > 1


def _fit_compliance(force_N: np.ndarray, length: float, r_body: float,
                    r_face: np.ndarray | float, body, face,
                    reference_mm: float) -> np.ndarray:
    """Per-contact ``c`` in ``delta = c * F**0.9``, fitted at the working load.

    ``body`` is the material of the part ``r_body`` is the radius of, and
    ``face`` the material of ``r_face``.  Each body's own radius sits inside its
    own logarithm in Johnson's expression, so the pairing is not free to be
    chosen: crossing them charges the steel pin's radius against the polymer's
    modulus and comes out a few percent soft.
    """
    ref = np.maximum(force_N, 1e-6)
    delta = line_contact_approach(ref, length, r_body, r_face,
                                  body.E_GPa, body.nu, face.E_GPa, face.nu,
                                  reference_mm=reference_mm)
    # strictly positive: it is about to be a divisor under a fractional power
    return np.maximum(delta, 1e-12) / ref ** _LOAD_EXPONENT


class _Contacts(NamedTuple):
    """One stage's contacts at one crank angle, ready for the solver."""

    c: np.ndarray        # per-contact compliance in delta = c * F**0.9
    arms: np.ndarray     # |moment arm| of each contact about the axis
    gaps: np.ndarray     # clearance each contact has to close before it bites
    ideal: np.ndarray    # the rigid-disc share of the load, for reference
    #: How far the worst pin was driven *past* the profile before the gaps were
    #: clamped at zero, mm.  Always zero without a position tolerance.  It is
    #: reported rather than absorbed because it is the point at which the model
    #: stops applying: a ring whose pins interfere does not turn, and a
    #: single-rotation solve cannot say what it does instead.
    interference: float = 0.0


def _ring_contacts(spec: GearSpec, cs, torque_per_disc: float,
                   error: np.ndarray | None = None) -> _Contacts | None:
    """Ring-pin contacts of one disc at one crank angle, or ``None`` if none bite.

    ``error`` displaces each pin from where the drawing put it, in the housing
    frame.  Only its component along the contact normal reaches the gap - a pin
    that slides along the flank it touches has not moved relative to it.
    """
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
                        spec.pin_mat, spec.disc_mat, spec.pin_circle_radius)
    gaps = mesh_gaps(spec, cs.phi)[loaded]
    if error is not None:
        gaps = gaps + (error[loaded] * cs.normals[loaded]).sum(axis=1)
    bite = max(-float(gaps.min()), 0.0)
    gaps = np.maximum(gaps, 0.0)
    return _Contacts(c=c, arms=arms, gaps=gaps, ideal=ideal, interference=bite)


def _output_contacts(spec: GearSpec, phi: float, torque_per_disc: float,
                     error: np.ndarray | None = None) -> _Contacts | None:
    """Output pin/hole contacts of one disc at one crank angle.

    The pin sits in a hole ``E`` larger in radius, so the counterface is
    conforming and its radius is negative - the same convention the ring stage
    uses for a valley of the profile.

    Every one of these contacts shares a normal - the disc translates against
    the carrier rather than rotating in it - so a pin's position error reaches
    its gap through that one direction.
    """
    ol = output_loads(spec, phi, torque_per_disc)
    live = ol.forces > 0
    if not live.any():
        return None
    arms = np.abs(ol.moment_arms[live])
    r_p = spec.output_pin_diameter / 2.0
    c = _fit_compliance(ol.forces[live], spec.disc_thickness, r_p,
                        -(r_p + spec.eccentricity), spec.pin_mat, spec.disc_mat,
                        spec.pin_circle_radius)
    gaps = np.full(arms.shape, spec.hole_clearance / 2.0)
    bite = 0.0
    if error is not None:
        eps = phi - phi / spec.lobes
        normal = np.array([math.cos(eps), -math.sin(eps)])
        gaps = gaps + error[live] @ normal
        bite = max(-float(gaps.min()), 0.0)
        gaps = np.maximum(gaps, 0.0)
    return _Contacts(c=c, arms=arms, gaps=gaps, ideal=ol.forces[live],
                     interference=bite)


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


def _seat_stiffness(spec: GearSpec, forces: np.ndarray,
                    arms: np.ndarray) -> float:
    """Ring pins bedding into their housing pockets, Nmm/rad for one disc.

    The pins are half-buried in pockets cut to their own radius and supported
    along their whole length, so they do not bend - the housing gives way under
    them instead.  That is a conforming line contact, a pin in a bore its own
    size, and the fit is the process's hole clearance: enough of a gap to have a
    finite contact width, which is what makes the problem well posed at all.

    Loaded over the disc thickness, like the contact that caused it.  The pin
    would really spread some of it along its length into the pockets either
    side, so this is the soft reading of the two.
    """
    live = forces > 0
    if not live.any():
        return math.inf
    f = forces[live]
    seat_r = spec.pin_radius + spec.hole_clearance / 2.0
    delta = line_contact_approach(f, spec.disc_thickness, spec.pin_radius, -seat_r,
                                  spec.pin_mat.E_GPa, spec.pin_mat.nu,
                                  spec.housing_mat.E_GPa, spec.housing_mat.nu,
                                  reference_mm=spec.pin_circle_radius)
    k = f / (_LOAD_EXPONENT * np.maximum(delta, 1e-12))         # N/mm
    return float((k * arms[live] ** 2).sum())                   # Nmm/rad


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


class _Ring(NamedTuple):
    """One ring, averaged over the mesh cycle: what a single build would measure.

    Every field is a reduction over the crank angles of one set of pin
    positions.  With no tolerance entered there is exactly one such ring and
    these *are* the answer; with a tolerance there are many, and the answer is
    a distribution over them.
    """

    ring_k: float
    seat_k: float
    out_k: float
    pin_k: float
    ring_theta: float
    out_theta: float
    engaged: float
    engaged_ideal: float
    concentration: float
    gap_close: float          # sets the lost motion
    spread: float
    interference: float       # deepest bite into the profile, mm


def _one_ring(spec: GearSpec, picked, torque_per_disc: float,
              pin_stiffness_N_per_mm: float,
              ring_error: np.ndarray | None,
              carrier_error: np.ndarray | None) -> _Ring:
    """Solve the whole mesh cycle for one set of pin positions."""
    ring_k: list[float] = []
    seat_k: list[float] = []
    pin_k: list[float] = []
    ring_theta: list[float] = []
    engaged: list[int] = []
    engaged_ideal: list[int] = []
    concentration: list[float] = []
    spreads: list[float] = []
    ring_gap_close: list[float] = []
    bites: list[float] = []

    for cs in picked:
        stage = _ring_contacts(spec, cs, torque_per_disc, ring_error)
        if stage is None:
            continue
        c, arms, gaps, ideal = stage[:4]
        bites.append(stage.interference)
        spreads.append(float(gaps.max() - gaps.min()))
        ring_gap_close.append(float((gaps / np.maximum(arms, 1e-9)).min()))

        theta, forces = _solve_rotation(c, arms, gaps, torque_per_disc)
        ring_theta.append(theta)
        k = _stage_stiffness(c, arms, forces, theta, gaps)
        if k > 0:
            ring_k.append(k)
            seat_k.append(_seat_stiffness(spec, forces, arms))
        engaged.append(int((forces > 0).sum()))
        engaged_ideal.append(int((ideal > 0).sum()))
        if ideal.max() > 0:
            concentration.append(float(forces.max() / ideal.max()))

    # ---- output pin stage ---------------------------------------------------
    out_k: list[float] = []
    out_theta: list[float] = []
    for cs in picked:
        stage = _output_contacts(spec, cs.phi, torque_per_disc, carrier_error)
        if stage is None:
            continue
        c, arms, gaps, _ideal = stage[:4]
        bites.append(stage.interference)
        theta, forces = _solve_rotation(c, arms, gaps, torque_per_disc)
        out_theta.append(theta)
        k = _stage_stiffness(c, arms, forces, theta, gaps)
        if k > 0:
            out_k.append(k)
            # the pins that carry the load are the ones that bend under it
            live = forces > 0
            pin_k.append(pin_stiffness_N_per_mm * float((arms[live] ** 2).sum()))

    return _Ring(
        ring_k=float(np.mean(ring_k)) if ring_k else 0.0,
        seat_k=float(np.mean(seat_k)) if seat_k else math.inf,
        out_k=float(np.mean(out_k)) if out_k else 0.0,
        pin_k=float(np.mean(pin_k)) if pin_k else math.inf,
        ring_theta=float(np.mean(ring_theta)) if ring_theta else 0.0,
        out_theta=float(np.mean(out_theta)) if out_theta else 0.0,
        engaged=float(np.mean(engaged)) if engaged else 0.0,
        engaged_ideal=float(np.mean(engaged_ideal)) if engaged_ideal else 0.0,
        concentration=float(np.mean(concentration)) if concentration else 1.0,
        gap_close=max(ring_gap_close) if ring_gap_close else 0.0,
        spread=float(np.max(spreads)) if spreads else 0.0,
        interference=max(bites) if bites else 0.0,
    )


def analyse_stiffness(spec: GearSpec, steps: int = _STIFFNESS_STEPS,
                      samples: int = DEFAULT_SAMPLES) -> StiffnessResult:
    """Torsional stiffness, lost motion and clearance-aware load sharing.

    With a position tolerance entered this solves ``samples`` different rings
    and reports the distribution; with none it solves the one perfect ring the
    drawing describes, and ``samples`` costs nothing.
    """
    torque_total_Nmm = spec.output_torque_Nm * 1000.0
    torque_per_disc = torque_total_Nmm / spec.disc_count
    parts = analyse_parts(spec)

    states = sweep(spec, SWEEP_STEPS)
    picked = states[:: max(1, len(states) // max(steps, 1))]

    drawn = tolerance_samples(spec, samples)
    ring_err = ring_position_errors(spec, drawn)
    carrier_err = carrier_position_errors(spec, drawn)
    perfect = spec.position_tolerance <= 0.0
    rings = [_one_ring(spec, picked, torque_per_disc, parts.output_pin_N_per_mm,
                       None if perfect else ring_err[i],
                       None if perfect else carrier_err[i])
             for i in range(drawn)]

    def middle(values: list[float]) -> float:
        """The median ring's value.  With one ring, that ring's value exactly."""
        return float(np.median(values)) if len(values) > 1 else values[0]

    def tail(values: list[float], percentile: float) -> float:
        return float(np.percentile(values, percentile)) if len(values) > 1 else values[0]

    ring_theta = [r.ring_theta for r in rings]
    out_theta = [r.out_theta for r in rings]

    n = spec.disc_count

    def to_nm_arcmin(k_nmm_rad: float) -> float:
        return k_nmm_rad / 1000.0 * RAD_PER_ARCMIN if math.isfinite(k_nmm_rad) \
            else math.inf

    def contacts_of(ring: _Ring) -> float:
        # discs act in parallel on one carrier, so their stiffnesses add
        return series_stiffness(ring.ring_k * n, ring.out_k * n)

    def structure_of(ring: _Ring) -> float:
        """The seats scale with the disc count for the same reason the contacts
        do - each disc bears on its own slice of the pocket, and the slices are
        in parallel.  The carrier pins do not: there is *one* set of them,
        carrying the whole stack, and a taller stack only makes them longer."""
        return series_stiffness(ring.seat_k * n, parts.housing_Nmm_per_rad,
                                parts.disc_body_Nmm_per_rad, ring.pin_k,
                                parts.carrier_plate_Nmm_per_rad,
                                parts.input_shaft_Nmm_per_rad)

    def whole_drive(ring: _Ring) -> float:
        """One ring's stiffness, composed exactly as the headline is composed.

        Nested the same way on purpose: a decile that cannot be compared with
        the number above it by ``<`` is not a decile of anything.
        """
        return series_stiffness(contacts_of(ring), structure_of(ring))

    middling = _Ring(
        ring_k=middle([r.ring_k for r in rings]),
        seat_k=middle([r.seat_k for r in rings]),
        out_k=middle([r.out_k for r in rings]),
        pin_k=middle([r.pin_k for r in rings]),
        ring_theta=middle(ring_theta), out_theta=middle(out_theta),
        engaged=middle([r.engaged for r in rings]),
        engaged_ideal=middle([r.engaged_ideal for r in rings]),
        concentration=middle([r.concentration for r in rings]),
        gap_close=middle([r.gap_close for r in rings]),
        spread=middle([r.spread for r in rings]),
        interference=max(r.interference for r in rings),
    )
    k_ring = middling.ring_k * n
    k_out = middling.out_k * n
    k_seat = middling.seat_k * n
    k_pins = middling.pin_k
    k_contact = contacts_of(middling)
    k_structure = structure_of(middling)
    k_series = whole_drive(middling)

    # ---- lost motion --------------------------------------------------------
    # the drive must traverse each gap in both directions, hence the factor 2
    lost_ring = 2.0 * middling.gap_close / RAD_PER_ARCMIN
    lost_out = (2.0 * (spec.hole_clearance / 2.0) / spec.output_bolt_circle_radius
                / RAD_PER_ARCMIN)
    lost_total = lost_ring + lost_out

    # the structure has no play to take up, so all of its deflection is windup
    structural = (torque_total_Nmm / k_structure
                  if math.isfinite(k_structure) and k_structure > 0 else 0.0)
    windup = structural / RAD_PER_ARCMIN
    # theta already includes closing the gap; the elastic part is what is left
    # once the play is taken out
    elastic_ring = max(middling.ring_theta - 0.5 * lost_ring * RAD_PER_ARCMIN, 0.0)
    elastic_out = max(middling.out_theta - 0.5 * lost_out * RAD_PER_ARCMIN, 0.0)
    windup += (elastic_ring + elastic_out) / RAD_PER_ARCMIN

    # ---- what a bad ring out of the same batch looks like --------------------
    # The tail that matters is the soft, loose, concentrated one, so each
    # quantity is taken from the decile it is worst in.  With one ring these are
    # that ring: a drawing with no tolerance on it has no spread to report.
    lost_p90 = tail([2.0 * r.gap_close / RAD_PER_ARCMIN + lost_out
                     for r in rings], 90.0)

    return StiffnessResult(
        stiffness_Nm_per_arcmin=to_nm_arcmin(k_series),
        contact_only_Nm_per_arcmin=to_nm_arcmin(k_contact),
        structure_Nm_per_arcmin=to_nm_arcmin(k_structure),
        structure=StructureStiffness(
            ring_seat_Nm_per_arcmin=to_nm_arcmin(k_seat),
            housing_Nm_per_arcmin=to_nm_arcmin(parts.housing_Nmm_per_rad),
            disc_body_Nm_per_arcmin=to_nm_arcmin(parts.disc_body_Nmm_per_rad),
            output_pin_Nm_per_arcmin=to_nm_arcmin(k_pins),
            carrier_plate_Nm_per_arcmin=to_nm_arcmin(parts.carrier_plate_Nmm_per_rad),
            input_shaft_Nm_per_arcmin=to_nm_arcmin(parts.input_shaft_Nmm_per_rad),
        ),
        ring_stage_Nm_per_arcmin=to_nm_arcmin(k_ring),
        output_stage_Nm_per_arcmin=to_nm_arcmin(k_out),
        windup_arcmin=windup,
        lost_motion_arcmin=lost_total,
        lost_motion_ring_arcmin=lost_ring,
        lost_motion_output_arcmin=lost_out,
        backlash_total_arcmin=lost_total + windup,
        pins_engaged=middling.engaged,
        pins_engaged_ideal=middling.engaged_ideal,
        load_concentration=middling.concentration,
        max_gap_spread_mm=middling.spread,
        rings_sampled=len(rings),
        stiffness_p10_Nm_per_arcmin=to_nm_arcmin(
            tail([whole_drive(r) for r in rings], 10.0)),
        load_concentration_p90=tail([r.concentration for r in rings], 90.0),
        lost_motion_p90_arcmin=lost_p90,
        position_interference_mm=middling.interference,
    )


# --------------------------------------------------------- transmission error --


@dataclass
class TransmissionErrorResult:
    """Ripple in the output angle under a steady load, referred to the output."""

    peak_to_peak_arcmin: float       # the headline: the whole error band
    rms_arcmin: float
    ring_arcmin: float               # the ring stage's own share, peak to peak
    output_arcmin: float             # the output stage's own share
    ring_period_deg: float           # of crank, one ring-pin pitch
    output_period_deg: float         # of crank, one output-hole pitch

    #: Rings the position tolerance was sampled over; one means the drawing
    #: carries no tolerance, and ``worst_ring_arcmin`` is then this same ring.
    rings_sampled: int = 1
    worst_ring_arcmin: float = 0.0

    @property
    def dominant_stage(self) -> str:
        return "ring" if self.ring_arcmin > self.output_arcmin else "output"

    @property
    def tolerance_was_sampled(self) -> bool:
        return self.rings_sampled > 1


def output_stage_period(spec: GearSpec) -> float:
    """:func:`~cycloidgen.core.kinematics.output_stage_period` for a spec.

    The rule this states - that a stage has to be swept over *its own* period -
    was worked out here, for the output stage, and left unapplied to the ring
    stage for four releases.  It lives in ``kinematics`` now so that there is
    one place to look before writing the next sweep.
    """
    return _output_stage_period(spec.lobes, spec.output_pin_count)


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


def _te_of_one_ring(spec: GearSpec, steps: int, ring_steps: int, period: float,
                    ring_error: np.ndarray | None,
                    carrier_error: np.ndarray | None
                    ) -> tuple[float, float, float, float]:
    """``(ring pp, ring rms, output pp, output rms)`` for one set of positions."""
    torque_total = spec.output_torque_Nm * 1000.0
    torque_per_disc = torque_total / spec.disc_count
    phases = spec.disc_phases

    ring: list[float] = []
    states = sweep(spec, SWEEP_STEPS)
    for cs in states[:: max(1, len(states) // max(ring_steps, 1))]:
        parts = [p for p in (_ring_contacts(spec, contacts(spec, cs.phi + phase),
                                            torque_per_disc, ring_error)
                             for phase in phases) if p is not None]
        if parts:
            ring.append(_stack_rotation(parts, torque_total))

    out: list[float] = []
    for phi in np.linspace(0.0, period, max(steps, 1), endpoint=False):
        parts = [p for p in (_output_contacts(spec, float(phi) + phase,
                                              torque_per_disc, carrier_error)
                             for phase in phases) if p is not None]
        if parts:
            out.append(_stack_rotation(parts, torque_total))

    ring_pp, ring_rms = _ripple(ring)
    out_pp, out_rms = _ripple(out)
    return ring_pp, ring_rms, out_pp, out_rms


def analyse_transmission_error(spec: GearSpec, steps: int = _TE_STEPS,
                               ring_steps: int = _TE_RING_STEPS,
                               samples: int = DEFAULT_TE_SAMPLES
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

    With a position tolerance entered, the third half goes in too - the pins are
    not where the drawing put them, which is what a measured transmission error
    trace is mostly showing you.  It is sampled over fewer rings than the load
    study because each one costs a full mesh cycle at ripple resolution, so the
    spread comes back as the worst of the batch rather than as a percentile
    that few rings cannot support.
    """
    period = output_stage_period(spec)
    drawn = tolerance_samples(spec, samples)
    perfect = spec.position_tolerance <= 0.0
    ring_err = ring_position_errors(spec, drawn)
    carrier_err = carrier_position_errors(spec, drawn)

    measured = [_te_of_one_ring(spec, steps, ring_steps, period,
                                None if perfect else ring_err[i],
                                None if perfect else carrier_err[i])
                for i in range(drawn)]
    totals = [r_pp + o_pp for r_pp, _r_rms, o_pp, _o_rms in measured]
    typical = measured[int(np.argsort(totals)[len(totals) // 2])]
    ring_pp, ring_rms, out_pp, out_rms = typical

    return TransmissionErrorResult(
        peak_to_peak_arcmin=ring_pp + out_pp,
        rms_arcmin=math.hypot(ring_rms, out_rms),
        ring_arcmin=ring_pp,
        output_arcmin=out_pp,
        ring_period_deg=math.degrees(ring_stage_period(spec.lobes)),
        output_period_deg=math.degrees(period),
        rings_sampled=drawn,
        worst_ring_arcmin=max(totals),
    )
