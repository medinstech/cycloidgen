"""The duty cycle: four aggregations, and none of them the same one.

The whole argument for this feature is that a single point cannot stand in for a
cycle, so the tests that matter are the ones that would pass if it could.  Each
of the four aggregates is checked against a cycle built so that picking any
representative point would give a different - and wrong - answer.

The other half is the promise the motor work made and this one has to keep: a
design that has *not* been given a cycle analyses exactly as it did before.
"""
from __future__ import annotations

import math

import pytest

from cycloidgen.analysis import analyse
from cycloidgen.analysis.duty import analyse_duty
from cycloidgen.analysis.motor import COMFORTABLE_MARGIN
from cycloidgen.core.duty import DutyCycle, DutyPoint
from cycloidgen.core.spec import GearSpec, MotorKind, Process, preset
from cycloidgen.report.build import report_dict

#: A machine that lifts, holds and returns.  Built so the four aggregates land
#: in four different places: the heaviest point is the one that does not turn,
#: the fastest is the lightest, and half the cycle is standstill.
LIFT = DutyPoint(name="lift", output_torque_Nm=40.0, output_rpm=12.0, seconds=4.0)
HOLD = DutyPoint(name="hold", output_torque_Nm=55.0, output_rpm=0.0, seconds=6.0)
RETURN = DutyPoint(name="return", output_torque_Nm=8.0, output_rpm=30.0, seconds=2.0)
CYCLE = DutyCycle(points=(LIFT, HOLD, RETURN))


def driven(**over) -> GearSpec:
    """A machined steel drive, rated at the cycle's peak unless a test says not."""
    return preset(21).model_copy(update={
        "process": Process.CNC,
        "disc_material": "Steel 4140 (hardened)",
        "pin_material": "Bearing steel 100Cr6",
        "housing_material": "Aluminium 7075-T6",
        "output_torque_Nm": 55.0,
        "input_rpm": 250.0,
        "duty_cycle": CYCLE,
        **over,
    })


# ------------------------------------------------------------ the arithmetic --

def test_the_four_aggregates_are_four_different_numbers():
    """The premise.  If peak, mean, RMS and cubic mean agreed, one point would
    do and none of this would be worth building."""
    torques = tuple(p.output_torque_Nm for p in CYCLE.points)
    peak = max(torques)
    mean = CYCLE.mean_of(torques)
    rms = CYCLE.rms_of(torques)
    cubic = CYCLE.cubic_mean_of(torques)
    assert len({round(v, 3) for v in (peak, mean, rms, cubic)}) == 4
    assert mean < rms < peak
    # Below the mean here, and that is the physics rather than an accident: the
    # heaviest point is a hold, and a bearing standing still consumes no life.
    assert cubic < mean


def test_shares_are_the_durations_and_nothing_else_has_to_add_up():
    assert CYCLE.shares() == pytest.approx((4 / 12, 6 / 12, 2 / 12))
    assert sum(CYCLE.shares()) == pytest.approx(1.0)
    # The same cycle in different units is the same cycle.
    doubled = DutyCycle(points=tuple(
        p.model_copy(update={"seconds": p.seconds * 2}) for p in CYCLE.points))
    assert doubled.shares() == pytest.approx(CYCLE.shares())


def test_a_hold_is_a_point_and_not_an_error():
    assert HOLD.is_hold and not LIFT.is_hold
    assert CYCLE.moving_share == pytest.approx(0.5)


def test_one_point_is_refused_because_it_is_the_rated_duty():
    with pytest.raises(ValueError, match="at least two points"):
        DutyCycle(points=(LIFT,))
    assert not DutyCycle().stated


def test_the_cubic_mean_weighs_revolutions_not_seconds():
    """A bearing wears per revolution, so a point at half the speed contributes
    half as much of the wear - and a point at no speed contributes none."""
    loads = (100.0, 900.0, 100.0)          # the huge one is the hold
    assert CYCLE.cubic_mean_of(loads) == pytest.approx(100.0)
    turning = DutyCycle(points=(LIFT, RETURN))
    # Same two speeds, same two loads: now weighted 4x12 against 2x30.
    weights = (4 * 12.0, 2 * 30.0)
    expected = ((100.0 ** 3 * weights[0] + 300.0 ** 3 * weights[1])
                / sum(weights)) ** (1 / 3)
    assert turning.cubic_mean_of((100.0, 300.0)) == pytest.approx(expected)


# --------------------------------------------------------------- the analysis --

def test_stress_comes_from_the_worst_point_even_when_it_does_not_turn():
    d = analyse_duty(driven())
    assert d.worst_stress.point.name == "hold"
    assert d.worst_stress.input_rpm == 0.0
    assert d.worst_stress.max_pin_pressure_MPa == max(
        r.max_pin_pressure_MPa for r in d.points)


def test_a_hold_loses_nothing_and_wears_nothing():
    d = analyse_duty(driven())
    held = next(r for r in d.points if r.point.is_hold)
    assert held.loss_W == 0.0
    assert held.pv_ring_MPa_m_s == 0.0
    # And it still has to be held: the torque is real.
    assert held.motor_required_Nm > 0.0


def test_temperature_follows_the_mean_loss_and_not_the_peak():
    """A housing integrates.  Sizing the cooling to the worst point is sizing it
    to a transient, and the mean is what it actually settles at."""
    d = analyse_duty(driven())
    worst_loss = max(r.loss_W for r in d.points)
    assert d.mean_loss_W < worst_loss
    assert d.mean_loss_W == pytest.approx(
        CYCLE.mean_of(tuple(r.loss_W for r in d.points)))
    at_peak = analyse(driven(output_torque_Nm=40.0, input_rpm=12.0 * 21))
    assert d.temperature_C < at_peak.thermal.temperature_C


def test_the_equivalent_speed_counts_the_standstill():
    """Life is quoted in hours of *cycle*, so the speed it is quoted at has to
    include the time the drive spends holding still."""
    d = analyse_duty(driven())
    turning_only = (12.0 * 21 * 4 + 30.0 * 21 * 2) / (4 + 2)
    assert d.equivalent_input_rpm < turning_only
    assert d.equivalent_input_rpm == pytest.approx(
        (12.0 * 21 * 4 + 0.0 * 6 + 30.0 * 21 * 2) / 12)


def test_the_bearing_schedule_is_asked_at_the_equivalent_load():
    d = analyse_duty(driven())
    assert d.equivalent_eccentric_load_N > 0
    assert [c.role for c in d.bearings]
    assert math.isfinite(d.shortest_life_hours)


def test_the_motor_needs_the_peak_and_survives_the_rms():
    d = analyse_duty(driven(motor_kind=MotorKind.STEPPER,
                            motor_holding_torque_Nm=2.0,
                            motor_rated_current_A=3.0,
                            motor_inductance_mH=4.0, motor_supply_V=48.0))
    assert d.motor_is_modelled
    assert d.rms_motor_torque_Nm < d.peak_motor_torque_Nm


def test_the_hardest_moment_for_the_motor_is_not_the_heaviest_point():
    """The case a single rated point cannot see.  Torque falls with speed, so
    the tightest moment is where load and speed are worst *together* - here the
    40 Nm lift rather than the 55 Nm hold, because a hold turns nothing and asks
    for no loss on top of its torque."""
    d = analyse_duty(driven(motor_kind=MotorKind.STEPPER,
                            motor_holding_torque_Nm=2.0,
                            motor_rated_current_A=3.0,
                            motor_inductance_mH=4.0, motor_supply_V=48.0))
    assert d.worst_motor.point.name == "lift"
    heaviest = next(r for r in d.points if r.point.name == "hold")
    assert heaviest.point.output_torque_Nm > d.worst_motor.point.output_torque_Nm
    assert d.worst_motor.motor_margin < heaviest.motor_margin


# ------------------------------------------------ nothing moves without a cycle --

def test_a_design_with_no_cycle_analyses_exactly_as_it_did():
    """The promise this is only allowed to ship with, and the same one the motor
    curve made: a cycle is a question asked *of* a design, never an input to
    it."""
    plain = preset(15)
    assert not plain.duty_cycle.stated
    a = report_dict(analyse(plain))
    for section in ("derived", "contact", "stiffness", "efficiency", "thermal",
                    "mass", "motor"):
        assert a[section] == report_dict(analyse(preset(15)))[section], section
    assert a["duty"]["stated"] is False
    assert a["duty"]["mean_loss_W"] is None


def test_stating_a_cycle_moves_no_headline_number():
    plain = driven(duty_cycle=DutyCycle())
    with_cycle = driven()
    a, b = report_dict(analyse(plain)), report_dict(analyse(with_cycle))
    for section in ("derived", "contact", "stiffness", "efficiency", "thermal",
                    "mass", "motor"):
        assert a[section] == b[section], section
    assert b["duty"]["stated"] and not a["duty"]["stated"]


# ------------------------------------------------------------------- checks --

def _codes(spec: GearSpec) -> dict[str, str]:
    return {f.code: f.severity.name for f in analyse(spec).report.findings}


def test_a_cycle_that_outruns_its_rating_says_so():
    """The check that makes the rest of the report safe to read: every headline
    number is computed at the rated torque, so a cycle that goes above it leaves
    them all describing an easier machine."""
    codes = _codes(driven(output_torque_Nm=40.0))
    assert codes.get("DUTY_RATING_MISMATCH") == "WARNING"
    assert "DUTY_RATING_MISMATCH" not in _codes(driven())


def test_the_reading_is_there_whenever_a_cycle_is():
    assert "DUTY_CYCLE" in _codes(driven())
    assert "DUTY_CYCLE" not in _codes(preset(21))


def test_a_motor_that_cannot_do_one_point_of_the_cycle_says_which():
    weak = driven(motor_kind=MotorKind.STEPPER, motor_holding_torque_Nm=0.05,
                  motor_rated_current_A=1.0, motor_inductance_mH=3.0)
    assert _codes(weak).get("DUTY_MOTOR_SHORT") == "WARNING"
    message = next(f.message for f in analyse(weak).report.findings
                   if f.code == "DUTY_MOTOR_SHORT")
    assert "lift" in message


def test_a_comfortable_motor_is_silent():
    """Note what "comfortable" costs here, because it is not more torque.

    An 8 Nm motor at the same current and bus is *worse* at this cycle than a
    4 Nm one: torque per amp is volts per rad/s, so the bigger motor meets the
    supply at half the speed and has nothing left at the 630 rpm the return
    asks for.  The motor that clears every point is the one with the ceiling to
    reach the fastest of them.
    """
    roomy = driven(motor_kind=MotorKind.STEPPER, motor_holding_torque_Nm=4.5,
                   motor_rated_current_A=6.0, motor_inductance_mH=2.0,
                   motor_supply_V=48.0)
    assert analyse_duty(roomy).worst_motor_margin >= COMFORTABLE_MARGIN
    assert "DUTY_MOTOR_SHORT" not in _codes(roomy)

    stronger = driven(motor_kind=MotorKind.STEPPER, motor_holding_torque_Nm=8.0,
                      motor_rated_current_A=6.0, motor_inductance_mH=2.0,
                      motor_supply_V=48.0)
    assert analyse_duty(stronger).worst_motor.point.name == "return"
    assert analyse_duty(stronger).worst_motor.motor_available_Nm == 0.0


def test_the_bearings_are_the_drives_own_and_only_their_lives_are_recomputed():
    """The question is whether the parts fitted survive the cycle, not which
    parts one would fit for it.

    Re-selecting would answer the second, and could then never report a bearing
    that falls short - it would simply have chosen a bigger one.  So the rated
    schedule's parts are kept and asked again at the cycle's equivalent duty.
    """
    a = analyse(driven())
    fitted = {c.role: c for c in a.bearings if c.fitted and c.bearing}
    assert fitted
    for b in a.duty.bearings:
        assert b.designation == fitted[b.role].bearing.designation
    # This cycle is lighter than the rating, so the parts last *longer* over it
    # than the rated point suggests - which is the answer a cycle exists to give.
    assert a.duty.equivalent_torque_Nm < a.spec.output_torque_Nm
    assert a.duty.shortest_life_hours > min(
        c.life_hours for c in fitted.values())


def test_a_short_bearing_life_over_the_cycle_is_reported_in_cycle_hours():
    """Reachable exactly where it matters: the schedule was chosen for a rated
    point the cycle is harsher than, so the parts that were picked do not last
    the duty they will actually see."""
    under_rated = driven(output_torque_Nm=20.0)
    assert _codes(under_rated).get("DUTY_BEARING_LIFE") == "WARNING"
    message = next(f.message for f in analyse(under_rated).report.findings
                   if f.code == "DUTY_BEARING_LIFE")
    assert "of cycle" in message and "not hours of rotation" in message
    assert "DUTY_BEARING_LIFE" not in _codes(driven())


# ------------------------------------------------------------------ writing --

def test_the_cycle_survives_a_round_trip_through_json():
    spec = driven()
    back = GearSpec.model_validate_json(spec.model_dump_json())
    assert back.duty_cycle == spec.duty_cycle
    assert [p.name for p in back.duty_cycle.points] == ["lift", "hold", "return"]


def test_the_report_and_the_analysis_state_the_same_aggregates():
    a = analyse(driven())
    block = report_dict(a)["duty"]
    assert block["mean_loss_W"] == pytest.approx(a.duty.mean_loss_W)
    assert block["peak_torque_Nm"] == pytest.approx(55.0)
    assert len(block["points"]) == 3
    assert [p["share"] for p in block["points"]] == pytest.approx(
        list(CYCLE.shares()))
