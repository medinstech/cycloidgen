"""The design against a whole duty cycle rather than against one point.

Four aggregations, because the quantities do not aggregate the same way and no
single point is conservative for all of them at once - see
:mod:`cycloidgen.core.duty` for why.  What this module does is run each point
through the cheap half of the analysis and then combine the results the way each
quantity is combined in the machine:

* **the worst point** for contact stress, which is what sizes the disc;
* **the mean loss** for temperature, because a housing integrates;
* **the cubic mean load at the mean speed** for bearing life, which is ISO 281's
  equivalent load for a varying one;
* **the peak and the RMS** for the motor, which has to make the first and
  survive the second.

What is *not* recomputed per point
----------------------------------
The stiffness solve and the transmission error, which together are five sixths
of a full analysis and neither of which the cycle changes in a way worth the
cost: they are geometry and clearance, evaluated at a load, and the load that
matters for both is the peak the design is rated at.  So the headline analysis
stays where it is - at the rated point - and this adds what only a spectrum can
say.  A duty point costs about fourteen milliseconds; a full analysis costs
ninety.

Holding still is a point
------------------------
Zero output speed is a real duty and most of what some drives do.  The torque is
there, so the contact loads are; nothing slides, so there is no PV and no
friction loss; nothing turns, so no bearing life is consumed.  The awkwardness
is that ``GearSpec.input_rpm`` is required to be positive, and a hold has to be
evaluated through a spec like any other point.  It is evaluated at a placeholder
speed and nothing speed-derived is read from it - which is sound rather than a
dodge, because the contact forces and Hertzian pressures come from torque alone;
speed enters ``analyse_contacts`` only through the sliding velocity, which is
exactly the quantity a hold does not have.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

from ..core.duty import DutyCycle, DutyPoint
from ..core.spec import GearSpec
from .bearings import BearingChoice, life_hours, select_bearings
from .efficiency import analyse_efficiency
from .mechanics import analyse_contacts
from .motor import COMFORTABLE_MARGIN
from .thermal import CONVECTION_W_M2K, analyse_thermal

__all__ = ["BearingOverCycle", "DutyPointResult", "DutyResult", "analyse_duty"]

#: The speed a hold is evaluated at, so that a spec can be built for it at all.
#: Nothing speed-derived is read back - see the module docstring.
_HOLD_RPM = 1.0


@dataclass(frozen=True)
class DutyPointResult:
    """What the drive does at one point of the cycle."""

    point: DutyPoint
    #: This point's share of the cycle, 0 to 1.
    share: float
    #: Input speed the point asks for, rpm.  Zero at a hold.
    input_rpm: float
    #: Peak Hertzian pressure at the ring mesh, MPa.
    max_pin_pressure_MPa: float
    #: What the three load paths carry here, N.
    eccentric_bearing_load_N: float
    output_pin_load_N: float
    ring_pin_load_N: float
    #: Friction loss, W.  Zero at a hold: nothing is sliding.
    loss_W: float
    #: Pressure times velocity at the ring contact, MPa m/s.  Zero at a hold.
    pv_ring_MPa_m_s: float
    #: What the motor is asked for here, Nm, loss included.  A hold still needs
    #: torque; it is the torque the drive stalls against.
    motor_required_Nm: float
    #: What the motor can hold there.  ``inf`` with no curve stated.
    motor_available_Nm: float

    @property
    def motor_margin(self) -> float:
        if self.motor_required_Nm <= 0:
            return math.inf
        return self.motor_available_Nm / self.motor_required_Nm


@dataclass(frozen=True)
class BearingOverCycle:
    """How long one of the drive's actual bearings lasts over the whole cycle.

    The parts are the ones the drive *has* - selected at the rated point, which
    is where a schedule is decided - and only their lives are recomputed.  The
    alternative was to re-select for the cycle, which is a different and much
    less useful question: it answers "what would I fit for this duty" and can
    never report a bearing that falls short, because it would simply have picked
    a bigger one.
    """

    role: str
    designation: str
    load_N: float
    speed_rpm: float
    life_hours: float


@dataclass(frozen=True)
class DutyResult:
    """The cycle, aggregated four ways."""

    stated: bool
    points: tuple[DutyPointResult, ...]
    #: Revolutions per minute at the input, averaged over the whole cycle
    #: including the time it stands still.  The speed a life in *hours of cycle*
    #: has to be quoted at.
    equivalent_input_rpm: float
    #: Fraction of the cycle in which anything turns.
    moving_share: float
    #: Time-weighted mean friction loss, W, and the temperature it settles at.
    mean_loss_W: float
    temperature_C: float
    #: The worst point for contact stress, and what it reaches.
    worst_stress: DutyPointResult | None
    #: ISO 281 equivalent loads over the cycle, N.
    equivalent_eccentric_load_N: float
    equivalent_output_pin_load_N: float
    equivalent_ring_pin_load_N: float
    #: The drive's own bearings, with their lives recomputed over the cycle -
    #: hours of cycle rather than hours of running.
    bearings: tuple[BearingOverCycle, ...]
    #: The single torque that does the same damage as the whole cycle, Nm.  Every
    #: load in this drive is linear in output torque, so one scalar carries the
    #: cycle onto every seat without anyone having to match a role to a load
    #: path by its name.
    equivalent_torque_Nm: float
    #: What the motor has to make, and what it has to survive.
    peak_motor_torque_Nm: float
    rms_motor_torque_Nm: float
    #: The point that asks the most of the motor, by margin rather than by
    #: torque: the hardest moment is not always the one with the most load, it
    #: is the one where load and speed are worst together.
    worst_motor: DutyPointResult | None

    @property
    def shortest(self) -> BearingOverCycle | None:
        """The bearing that gives out first over the cycle."""
        lasting = [b for b in self.bearings if math.isfinite(b.life_hours)]
        return min(lasting, key=lambda b: b.life_hours) if lasting else None

    @property
    def shortest_life_hours(self) -> float:
        first = self.shortest
        return first.life_hours if first is not None else math.inf

    @property
    def motor_is_modelled(self) -> bool:
        return any(math.isfinite(p.motor_available_Nm) for p in self.points)

    @property
    def worst_motor_margin(self) -> float:
        margins = [p.motor_margin for p in self.points]
        return min(margins) if margins else math.inf


def _empty() -> DutyResult:
    return DutyResult(
        stated=False, points=(), equivalent_input_rpm=0.0, moving_share=0.0,
        mean_loss_W=0.0, temperature_C=0.0, worst_stress=None,
        equivalent_eccentric_load_N=0.0, equivalent_output_pin_load_N=0.0,
        equivalent_ring_pin_load_N=0.0, bearings=(), equivalent_torque_Nm=0.0,
        peak_motor_torque_Nm=0.0, rms_motor_torque_Nm=0.0, worst_motor=None)


def _at(spec: GearSpec, point: DutyPoint) -> DutyPointResult:
    """One point, through the cheap half of the analysis."""
    running = not point.is_hold
    input_rpm = point.output_rpm * spec.ratio if running else 0.0
    at = spec.model_copy(update={
        "output_torque_Nm": point.output_torque_Nm,
        "input_rpm": input_rpm if running else _HOLD_RPM,
    })

    contact = analyse_contacts(at)
    curve = at.motor_curve
    if running:
        efficiency = analyse_efficiency(at)
        thermal = analyse_thermal(at, efficiency=efficiency)
        loss_W = efficiency.total_loss_W
        pv = thermal.pv_ring_MPa_m_s
        required = efficiency.input_torque_Nm
        available = (curve.continuous_torque_at(input_rpm) if curve.modelled
                     else math.inf)
    else:
        # A hold turns nothing, so it slides nothing and loses nothing.  It
        # still has to be held: the torque the motor stalls against is the
        # output torque through the ratio, with no loss to help or hinder,
        # because a loss is a rate and there is no rate here.
        loss_W = 0.0
        pv = 0.0
        required = point.output_torque_Nm / spec.ratio
        available = (curve.continuous_torque_at(0.0) if curve.modelled
                     else math.inf)

    return DutyPointResult(
        point=point, share=0.0, input_rpm=input_rpm,
        max_pin_pressure_MPa=contact.max_pin_pressure_MPa,
        eccentric_bearing_load_N=contact.eccentric_bearing_load_N,
        output_pin_load_N=contact.max_output_force_N,
        ring_pin_load_N=contact.max_pin_force_N,
        loss_W=loss_W, pv_ring_MPa_m_s=pv,
        motor_required_Nm=required, motor_available_Nm=available)


def analyse_duty(spec: GearSpec, cycle: DutyCycle | None = None,
                 rated: list[BearingChoice] | None = None) -> DutyResult:
    """Run every point of the cycle and combine the results four ways.

    ``cycle`` defaults to the one on the spec.  With no cycle stated this
    returns an unstated result and touches nothing: a design that has never been
    given a duty cycle gets exactly the answers it always got.
    """
    cycle = cycle if cycle is not None else spec.duty_cycle
    if cycle is None or not cycle.stated:
        return _empty()

    shares = cycle.shares()
    evaluated = tuple(replace(_at(spec, p), share=share)
                      for p, share in zip(cycle.points, shares, strict=True))

    losses = tuple(r.loss_W for r in evaluated)
    mean_loss = cycle.mean_of(losses)
    area_m2 = max(spec.cooling_area_mm2 * 1e-6, 1e-12)
    temperature = spec.ambient_temp_C + mean_loss / (CONVECTION_W_M2K * area_m2)

    # Revolutions per minute of *cycle*, standstill included.  It is what makes
    # the life below a number of hours somebody can put in a service schedule
    # rather than a number of hours of rotation they would have to convert.
    total = cycle.total_seconds
    equivalent_rpm = (sum(r.input_rpm * r.point.seconds for r in evaluated)
                      / total) if total > 0 else 0.0

    eccentric = cycle.cubic_mean_of(
        tuple(r.eccentric_bearing_load_N for r in evaluated))
    output_pin = cycle.cubic_mean_of(
        tuple(r.output_pin_load_N for r in evaluated))
    ring_pin = cycle.cubic_mean_of(
        tuple(r.ring_pin_load_N for r in evaluated))

    # The drive's own bearings, at the cycle's equivalent duty.
    #
    # One scalar carries the whole cycle onto every seat: every load in this
    # machine is linear in output torque and every speed is linear in input
    # speed, so the equivalent torque and the equivalent speed scale the rated
    # schedule exactly.  Doing it that way rather than by matching each role to
    # a load path means nothing here has to read a role *string* to decide what
    # a number means, which is how the bearing quantities went wrong once
    # before.
    if rated is None:
        contact = analyse_contacts(spec)
        rated = select_bearings(spec, contact.eccentric_bearing_load_N,
                                contact.max_output_force_N,
                                ring_pin_load_N=contact.max_pin_force_N)
    equivalent_torque = cycle.cubic_mean_of(
        tuple(p.output_torque_Nm for p in cycle.points))
    load_factor = equivalent_torque / max(spec.output_torque_Nm, 1e-9)
    speed_factor = equivalent_rpm / max(spec.input_rpm, 1e-9)
    bearings = tuple(
        BearingOverCycle(
            role=choice.role,
            designation=choice.bearing.designation,
            load_N=choice.load_N * load_factor,
            speed_rpm=choice.speed_rpm * speed_factor,
            life_hours=life_hours(choice.bearing, choice.load_N * load_factor,
                                  choice.speed_rpm * speed_factor))
        for choice in rated if choice.fitted and choice.bearing is not None)

    torques = tuple(r.motor_required_Nm for r in evaluated)
    return DutyResult(
        stated=True,
        points=evaluated,
        equivalent_input_rpm=equivalent_rpm,
        moving_share=cycle.moving_share,
        mean_loss_W=mean_loss,
        temperature_C=temperature,
        worst_stress=max(evaluated, key=lambda r: r.max_pin_pressure_MPa),
        equivalent_eccentric_load_N=eccentric,
        equivalent_output_pin_load_N=output_pin,
        equivalent_ring_pin_load_N=ring_pin,
        bearings=bearings,
        equivalent_torque_Nm=equivalent_torque,
        peak_motor_torque_Nm=max(torques),
        rms_motor_torque_Nm=cycle.rms_of(torques),
        worst_motor=min(evaluated, key=lambda r: r.motor_margin),
    )


def comfortable(result: DutyResult) -> bool:
    """Whether every point leaves the usual margin on the motor."""
    return result.worst_motor_margin >= COMFORTABLE_MARGIN
