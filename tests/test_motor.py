"""The motor curve, and what the analysis does with it.

Two things are being held here.  The first is that the models are the models
they claim to be - the stepper's ceiling really is where back-EMF meets the
supply, the DC line really does run from ``Kt*V/R`` to ``Kv*V`` - because both
are stated as physics in the module docstring and a docstring is not a test.

The second matters more: that a design which has *not* been told what drives it
gets exactly the answers it got before there was a curve at all.  A feature that
quietly moves a number on every existing design is a feature that invalidates
work somebody has already built, and this one has no business touching the
geometry.
"""
from __future__ import annotations

import itertools
import math

import pytest

from cycloidgen.analysis import analyse
from cycloidgen.analysis.motor import COMFORTABLE_MARGIN, analyse_motor
from cycloidgen.core.motor import (
    MOTOR_FIELDS,
    MotorCurve,
    MotorKind,
    curve_from,
)
from cycloidgen.core.spec import GearSpec, OutputMember, Process, preset
from cycloidgen.design.optimize import (
    RATIO_FROM_MOTOR,
    Requirements,
    optimise,
    ratio_band,
    requirements_from_spec,
)
from cycloidgen.report.build import report_dict

#: A real 42x40 stepper, off a datasheet, on a 24 V bus.
STEPPER = {"kind": MotorKind.STEPPER, "supply_V": 24.0, "resistance_ohm": 1.5,
           "rated_current_A": 1.7, "holding_torque_Nm": 0.4,
           "inductance_mH": 2.8}

#: A hobby brushless motor, which is the case where peak and continuous are two
#: orders of magnitude apart.
BRUSHLESS = {"kind": MotorKind.DC, "supply_V": 24.0, "resistance_ohm": 0.1,
             "rated_current_A": 20.0, "kv_rpm_per_V": 270.0}


def stepper(**over) -> MotorCurve:
    return MotorCurve(**{**STEPPER, **over})


def brushless(**over) -> MotorCurve:
    return MotorCurve(**{**BRUSHLESS, **over})


def with_motor(base: GearSpec | None = None, **over) -> GearSpec:
    """A preset told what turns it."""
    spec = base or preset(21)
    return spec.model_copy(update=over)


# --------------------------------------------------------------- the stepper --

def test_the_ceiling_is_where_back_emf_reaches_the_supply():
    """The one number in the stepper model that is a hard bound rather than an
    estimate, so it is worth deriving twice and comparing."""
    m = stepper()
    omega = 2.0 * math.pi * m.ceiling_rpm / 60.0
    assert m.torque_constant_Nm_per_A * omega == pytest.approx(m.supply_V)
    assert m.torque_at(m.ceiling_rpm) == 0.0
    assert m.torque_at(m.ceiling_rpm * 1.2) == 0.0


def test_the_top_speed_is_proportional_to_the_bus():
    """Halving the supply halves the top speed - the single most useful thing
    the model says, and the one people are most often surprised by."""
    assert stepper(supply_V=12.0).ceiling_rpm == pytest.approx(
        stepper(supply_V=24.0).ceiling_rpm / 2.0)


def test_holding_torque_is_what_it_makes_standing_still():
    m = stepper()
    assert m.torque_at(0.0) == pytest.approx(m.holding_torque_Nm)
    assert m.stall_torque_Nm == pytest.approx(m.holding_torque_Nm)


def test_torque_constant_and_holding_torque_are_one_statement():
    """Both phases at rated current is what holding torque is measured with, so
    one phase carries it over root two.  The identity is what lets the ceiling
    be computed from a mechanical rating, so it is checked rather than trusted."""
    m = stepper()
    assert (m.torque_constant_Nm_per_A * math.sqrt(2.0) * m.rated_current_A
            == pytest.approx(m.holding_torque_Nm))


def test_the_curve_only_ever_falls():
    m = stepper()
    torques = [m.torque_at(rpm) for rpm in range(0, 1500, 25)]
    assert all(b <= a + 1e-12 for a, b in itertools.pairwise(torques))
    assert torques[0] > torques[-1]


def test_a_finer_step_angle_runs_out_sooner():
    """A 0.9 degree motor reaches the same electrical frequency at half the
    speed, so the reactance that limits its current arrives at half the rpm.
    The ceiling is unmoved, because that is back-EMF and not reactance."""
    coarse, fine = stepper(steps_per_rev=200), stepper(steps_per_rev=400)
    assert fine.torque_at(600.0) < coarse.torque_at(600.0)
    assert fine.ceiling_rpm == pytest.approx(coarse.ceiling_rpm)


def test_more_holding_torque_on_the_same_bus_and_current_is_less_top_speed():
    """Not obvious, and the reason a bigger motor sometimes makes it worse.

    Torque per amp and volts per rad/s are the same constant, so a motor that
    makes twice the torque at the same current builds back-EMF twice as fast
    and meets the supply at half the speed.  Buying torque without buying
    current or volts moves the ceiling down.
    """
    small = stepper(holding_torque_Nm=0.4)
    large = stepper(holding_torque_Nm=0.8)
    assert large.ceiling_rpm == pytest.approx(small.ceiling_rpm / 2.0)
    assert large.torque_at(0.0) > small.torque_at(0.0)
    assert (large.torque_at(small.ceiling_rpm * 0.75)
            < small.torque_at(small.ceiling_rpm * 0.75))


def test_a_supply_too_low_to_reach_rated_current_scales_the_whole_curve():
    """A 30 ohm winding on 12 V cannot take 1.7 A standing still, so the
    datasheet's holding torque is not available anywhere - including at zero,
    which is the part that surprises people."""
    starved = stepper(resistance_ohm=30.0, supply_V=12.0)
    assert starved.torque_at(0.0) < starved.holding_torque_Nm
    assert starved.torque_at(0.0) == pytest.approx(
        starved.holding_torque_Nm * (12.0 / 30.0) / 1.7)


# -------------------------------------------------------------- the DC motor --

def test_the_dc_line_runs_between_the_two_ends_it_is_defined_by():
    m = brushless()
    assert m.ceiling_rpm == pytest.approx(m.kv_rpm_per_V * m.supply_V)
    assert m.stall_torque_Nm == pytest.approx(
        m.torque_constant_Nm_per_A * m.supply_V / m.resistance_ohm)
    assert m.torque_at(m.ceiling_rpm / 2.0) == pytest.approx(
        m.stall_torque_Nm / 2.0)


def test_kv_and_kt_are_the_same_constant():
    assert (brushless(kv_rpm_per_V=100.0).torque_constant_Nm_per_A
            == pytest.approx(9.5493 / 100.0, rel=1e-4))


def test_continuous_is_far_below_peak_on_a_brushless_motor():
    """The whole reason the continuous line is carried separately.  Sizing a
    gearbox on the stall end of this curve is sizing it on a current the motor
    survives for seconds."""
    m = brushless()
    assert m.continuous_torque_at(0.0) == pytest.approx(
        m.torque_constant_Nm_per_A * m.rated_current_A)
    assert m.continuous_torque_at(0.0) < m.stall_torque_Nm / 10.0


def test_a_stepper_has_no_second_line():
    """It is current limited everywhere already, so drawing a continuous line
    under its curve would promise headroom that does not exist."""
    m = stepper()
    for rpm in (0.0, 400.0, 900.0):
        assert m.continuous_torque_at(rpm) == pytest.approx(m.torque_at(rpm))


# ------------------------------------------------------------ inverting them --

@pytest.mark.parametrize("curve", [stepper(), brushless()])
def test_speed_for_torque_really_is_the_inverse(curve):
    """The number the app reports as an output speed ceiling, so it has to land
    back on the curve it came from rather than near it."""
    for fraction in (0.2, 0.5, 0.8):
        want = curve.continuous_torque_at(0.0) * fraction
        rpm = curve.speed_for_torque(want)
        assert curve.torque_at(rpm) == pytest.approx(want, rel=1e-6)


@pytest.mark.parametrize("curve", [stepper(), brushless()])
def test_a_torque_it_cannot_make_at_all_is_zero_speed_not_a_guess(curve):
    assert curve.speed_for_torque(curve.stall_torque_Nm * 2.0) == 0.0


def test_a_dc_motor_asked_for_more_than_it_can_hold_has_no_continuous_speed():
    """Distinct from the peak answer on purpose: the peak line would hand back a
    speed, and running there is a burst rather than a duty."""
    m = brushless()
    over = m.torque_constant_Nm_per_A * m.rated_current_A * 1.5
    assert m.speed_for_torque(over) > 0.0
    assert m.continuous_speed_for_torque(over) == 0.0


# ------------------------------------------------ nothing moves without a curve --

def test_no_curve_stated_changes_no_number_anywhere():
    """The promise this feature is only allowed to ship with.

    A motor curve is a question asked *of* the design; it must not be an input
    *to* it.  So a design carrying a full set of motor numbers has to analyse
    identically to the same design with the kind left at none - every geometry,
    stress, efficiency and thermal number the same, and only the motor result
    and its findings different.
    """
    plain = preset(15)
    described = with_motor(plain, motor_holding_torque_Nm=0.4,
                           motor_rated_current_A=1.7, motor_inductance_mH=2.8,
                           motor_supply_V=48.0)
    assert described.motor_kind is MotorKind.NONE

    a, b = report_dict(analyse(plain)), report_dict(analyse(described))
    for section in ("derived", "contact", "stiffness", "efficiency", "thermal",
                    "mass"):
        assert a[section] == b[section], section
    assert [f["code"] for f in a["findings"]] == [f["code"] for f in b["findings"]]


def test_with_no_curve_the_motor_result_declines_to_answer():
    a = analyse(preset(15))
    assert not a.motor.modelled
    assert not [f for f in a.report.findings if f.code.startswith("MOTOR_TORQUE")]
    assert report_dict(a)["motor"]["margin"] is None


def test_turning_a_curve_on_does_not_move_the_geometry_either():
    """The other direction of the same promise: adding the curve is allowed to
    add findings, and nothing else."""
    plain = preset(15)
    driven = with_motor(plain, motor_kind=MotorKind.STEPPER)
    a, b = report_dict(analyse(plain)), report_dict(analyse(driven))
    for section in ("derived", "contact", "stiffness", "efficiency", "mass"):
        assert a[section] == b[section], section


# ------------------------------------------------------- the analysis result --

def test_the_required_torque_is_the_one_the_efficiency_reports():
    """Two places in the app state what the motor has to turn, and they have to
    be the same number - the datasheet reads one and the check reads the other."""
    a = analyse(with_motor(motor_kind=MotorKind.STEPPER))
    assert a.motor.required_Nm == pytest.approx(a.efficiency.input_torque_Nm)


def test_the_motor_turns_the_input_shaft_whichever_member_is_grounded():
    """The speed the curve is sampled at is the input shaft's, full stop.

    Worth pinning, because there is a nearby quantity that looks like it and is
    not: ``crank_rate`` is crank angle per input revolution *in the ring-fixed
    frame the kinematics are parameterised in*, which is how every relative
    speed inside the drive is stated and is not a shaft speed at all. It is not
    1 on a ring-output drive, so multiplying by it samples the motor curve in
    the wrong place - by 4.5% on a 21:1, and further out the lower the ratio.
    """
    for member in (OutputMember.CARRIER, OutputMember.RING):
        spec = with_motor(preset(21).model_copy(update={"output_member": member}),
                          motor_kind=MotorKind.STEPPER)
        assert analyse(spec).motor.motor_rpm == pytest.approx(spec.input_rpm)
    ring = preset(21).model_copy(update={"output_member": OutputMember.RING})
    assert ring.crank_rate != pytest.approx(1.0)


def test_the_output_ceilings_are_the_curve_through_the_gearbox():
    a = analyse(with_motor(motor_kind=MotorKind.STEPPER))
    m, s = a.motor, a.spec
    assert m.output_torque_ceiling_Nm == pytest.approx(
        m.continuous_Nm * s.ratio * a.efficiency.efficiency)
    assert m.output_speed_ceiling_rpm == pytest.approx(m.top_motor_rpm / s.ratio)


def test_the_top_speed_is_where_the_curve_meets_the_requirement():
    a = analyse(with_motor(motor_kind=MotorKind.STEPPER, input_rpm=600.0))
    m = a.motor
    assert 0.0 < m.top_motor_rpm <= m.ceiling_rpm
    assert a.spec.motor_curve.torque_at(m.top_motor_rpm) == pytest.approx(
        m.required_Nm, rel=1e-6)


def test_the_fraction_left_of_standing_still_falls_with_speed():
    slow = analyse(with_motor(motor_kind=MotorKind.STEPPER, input_rpm=200.0)).motor
    fast = analyse(with_motor(motor_kind=MotorKind.STEPPER, input_rpm=900.0)).motor
    assert fast.fraction_of_stall < slow.fraction_of_stall
    assert fast.fraction_of_ceiling > slow.fraction_of_ceiling


# ------------------------------------------------------------------- checks --

def _codes(spec: GearSpec) -> dict[str, str]:
    return {f.code: f.severity.name for f in analyse(spec).report.findings}


def test_a_motor_that_cannot_turn_it_is_a_warning_and_does_not_block_export():
    """A warning rather than an error, even though the drive will not turn.

    An error in this app means the files are wrong.  These files are right - the
    geometry is the geometry - and what is wrong is which motor goes on the end
    of it, which is fixed by buying a different one as readily as by redrawing
    anything.  Blocking the export would also make the app refuse to hand over a
    gearbox somebody is having machined so they can go and find a motor for it.
    Same argument MOTOR_SHAFT_MISMATCH is a warning on.
    """
    weak = with_motor(motor_kind=MotorKind.STEPPER,
                      motor_holding_torque_Nm=0.02, input_rpm=600.0)
    report = analyse(weak).report
    assert {f.code: f.severity.name for f in report.findings}[
        "MOTOR_TORQUE_SHORT"] == "WARNING"
    assert "does not turn at this duty point" in next(
        f.message for f in report.findings if f.code == "MOTOR_TORQUE_SHORT")
    assert report.ok, "a motor mismatch must not block the export"


def test_a_thin_margin_is_a_warning_and_a_healthy_one_is_silent():
    a = analyse(with_motor(motor_kind=MotorKind.STEPPER,
                           motor_holding_torque_Nm=0.4, input_rpm=600.0))
    assert a.motor.margin < COMFORTABLE_MARGIN
    assert _codes(a.spec).get("MOTOR_TORQUE_SHORT") == "WARNING"

    # More torque *and* more current: on a fixed bus, holding torque alone
    # buys nothing at speed - see the test below.
    roomy = with_motor(motor_kind=MotorKind.STEPPER,
                       motor_holding_torque_Nm=0.9, motor_rated_current_A=3.0,
                       input_rpm=600.0)
    assert analyse(roomy).motor.margin > COMFORTABLE_MARGIN
    assert "MOTOR_TORQUE_SHORT" not in _codes(roomy)


def test_a_burst_is_told_apart_from_a_rating():
    """A brushless motor asked for more than it can hold but less than it can
    peak at will do the job and cook itself, which is neither a pass nor the
    same failure as not turning at all."""
    burst = with_motor(preset(15), motor_kind=MotorKind.DC,
                       motor_kv_rpm_per_V=270.0, motor_resistance_ohm=0.1,
                       motor_rated_current_A=0.2, input_rpm=600.0)
    a = analyse(burst)
    assert a.motor.peak_margin > 1.0 > a.motor.margin
    assert _codes(burst).get("MOTOR_TORQUE_SHORT") == "WARNING"


def test_a_bus_too_low_for_the_winding_is_reported_on_its_own():
    starved = with_motor(motor_kind=MotorKind.STEPPER, motor_resistance_ohm=30.0,
                         motor_supply_V=12.0)
    assert _codes(starved).get("MOTOR_SUPPLY_VOLTAGE") == "WARNING"
    assert "MOTOR_SUPPLY_VOLTAGE" not in _codes(
        with_motor(motor_kind=MotorKind.STEPPER))


def test_the_operating_point_is_always_reported_when_there_is_a_curve():
    assert "MOTOR_OPERATING_POINT" in _codes(with_motor(motor_kind=MotorKind.STEPPER))
    assert "MOTOR_OPERATING_POINT" in _codes(
        with_motor(motor_kind=MotorKind.DC, motor_kv_rpm_per_V=100.0))
    assert "MOTOR_OPERATING_POINT" not in _codes(preset(21))


# ----------------------------------------------------------------- the panel --

def test_every_motor_field_the_panel_greys_is_a_field_that_exists():
    """The relevance map addresses widgets by spec field name, so a rename that
    misses it silently stops greying the field it was meant to."""
    from cycloidgen.ui.fields import GROUPS, MOTOR_FIELD_KINDS

    shown = {f.name for _, fields in GROUPS for f in fields}
    assert set(MOTOR_FIELD_KINDS) <= shown
    assert set(MOTOR_FIELD_KINDS) <= set(GearSpec.model_fields)


def test_every_kind_leaves_at_least_one_field_live():
    """A kind that greyed everything would be a model with no inputs, which is
    a sign the map and the models have drifted apart."""
    from cycloidgen.ui.fields import MOTOR_FIELD_KINDS

    for kind in (MotorKind.STEPPER, MotorKind.DC):
        live = [n for n, kinds in MOTOR_FIELD_KINDS.items() if kind in kinds]
        assert len(live) >= 3, kind
    assert not [n for n, kinds in MOTOR_FIELD_KINDS.items()
                if MotorKind.NONE in kinds]


# ------------------------------------------------------------------- writing --

def test_the_kind_survives_a_round_trip_through_json():
    spec = with_motor(motor_kind=MotorKind.DC, motor_kv_rpm_per_V=140.0)
    back = GearSpec.model_validate_json(spec.model_dump_json())
    assert back.motor_kind is MotorKind.DC
    assert back.motor_curve.ceiling_rpm == pytest.approx(spec.motor_curve.ceiling_rpm)


def test_the_report_and_the_analysis_state_the_same_margin():
    a = analyse(with_motor(motor_kind=MotorKind.STEPPER))
    assert report_dict(a)["motor"]["margin"] == pytest.approx(a.motor.margin)
    assert report_dict(a)["motor"]["kind"] == a.motor.kind.value


def test_the_batch_metric_is_nan_where_no_motor_was_stated():
    from cycloidgen.design.batch import METRICS

    metric = next(m for m in METRICS if m.name == "motor_margin")
    assert math.isnan(metric.of(analyse(preset(15))))
    assert metric.of(analyse(with_motor(motor_kind=MotorKind.STEPPER))) > 0.0


def test_analyse_motor_can_be_called_on_its_own():
    """It is part of the documented surface, so it has to work without the rest
    of the analysis having been run around it."""
    spec = with_motor(motor_kind=MotorKind.STEPPER)
    a = analyse(spec)
    direct = analyse_motor(spec, a.efficiency)
    assert direct.margin == pytest.approx(a.motor.margin)


# ------------------------------------------------------- choosing the ratio --

def _requirements(**over) -> Requirements:
    """A job a NEMA 17 can actually do, unless a test breaks it on purpose."""
    return Requirements(**{
        "ratio": RATIO_FROM_MOTOR,
        "output_torque_Nm": 6.0,
        "output_rpm": 10.0,
        "motor_kind": MotorKind.STEPPER,
        "motor_holding_torque_Nm": 0.45,
        "motor_rated_current_A": 1.5,
        "motor_inductance_mH": 3.0,
        "motor_supply_V": 24.0,
        "max_outer_diameter_mm": 130.0,
        "max_length_mm": 60.0,
        "process": Process.CNC,
        "disc_material": "Steel 4140 (hardened)",
        "pin_material": "Bearing steel 100Cr6",
        "housing_material": "Aluminium 7075-T6",
        **over,
    })


def test_the_band_is_a_band_and_not_a_scatter():
    """Torque runs out below it and speed runs out above it, so what works is
    one contiguous run - and a gap in it would mean the screen is wrong."""
    band = ratio_band(_requirements())
    assert band.ok
    low, high = band.span
    assert tuple(range(low, high + 1)) == band.ratios
    assert all(r < low for r in band.torque_short)
    assert all(r > high for r in band.speed_short)


def test_every_reduction_in_the_band_is_one_the_motor_can_hold():
    req = _requirements()
    curve = req.motor
    for ratio in ratio_band(req).ratios:
        needed = req.output_torque_Nm / (ratio * 0.55)
        assert (curve.continuous_torque_at(req.output_rpm * ratio)
                >= COMFORTABLE_MARGIN * needed)


def test_the_two_ends_fail_for_different_reasons_and_say_so():
    """The whole value of the band: below it, gear down; above it, no amount of
    gearing helps and the answer is volts or a different motor."""
    band = ratio_band(_requirements())
    top = band.span[1]
    assert band.speed_short and band.speed_short[0] == top + 1
    assert "between" in band.explain()

    # Short of torque at the low end and out of speed at the high end, with
    # nothing in between: on a 12 V bus this motor cannot do this job at all,
    # and no reduction is the answer.
    both_ends = ratio_band(_requirements(motor_supply_V=12.0))
    assert not both_ends.ok
    assert both_ends.torque_short and both_ends.speed_short
    assert "cannot drive this load at any reduction" in both_ends.explain()

    # Out of speed everywhere is a different failure and says so: the output is
    # simply being asked to turn faster than the motor can drive it.
    too_fast = ratio_band(_requirements(output_rpm=200.0))
    assert not too_fast.ok and not too_fast.torque_short
    assert "out of speed at every reduction" in too_fast.explain()


def test_a_faster_output_narrows_the_band_from_the_top():
    slow = ratio_band(_requirements(output_rpm=5.0))
    fast = ratio_band(_requirements(output_rpm=12.0))
    assert slow.span[1] > fast.span[1]
    assert slow.span[0] == fast.span[0]      # the low end is torque, not speed


def test_a_higher_bus_widens_it():
    """The lever people miss, and the one the band makes visible."""
    low = ratio_band(_requirements(motor_supply_V=12.0))
    high = ratio_band(_requirements(motor_supply_V=48.0))
    assert len(high.ratios) > len(low.ratios)


def test_no_motor_means_no_band_and_no_free_reduction():
    assert not ratio_band(Requirements(ratio=29)).ok
    with pytest.raises(ValueError, match="only be worked out from a motor"):
        Requirements(ratio=RATIO_FROM_MOTOR)


def test_stating_the_reduction_derives_the_input_speed():
    """The point of leaving it free: the job fixes what the output does, and
    how fast the motor has to turn is an answer rather than a question."""
    req = _requirements(output_rpm=12.0)
    at = req.at_ratio(40)
    assert at.ratio == 40
    assert at.input_rpm == pytest.approx(480.0)
    assert not at.ratio_is_free


def test_the_search_only_returns_drives_the_motor_can_turn():
    req = _requirements()
    result = optimise(req, effort="quick")
    assert result.ok, result.tally.explain()
    assert result.band is not None and result.band.ok
    for cand in result.best:
        assert cand.spec.ratio in result.band.ratios
        assert cand.analysis is not None
        assert cand.analysis.motor.margin >= COMFORTABLE_MARGIN


def test_the_reductions_searched_are_a_sample_and_it_is_declared():
    """A bounded search that looks exhaustive is how somebody concludes a
    reduction does not work when it was never tried."""
    result = optimise(_requirements(), effort="quick")
    assert len(result.ratios_searched) <= 5
    assert set(result.ratios_searched) <= set(result.band.ratios)
    assert result.band.span[0] in result.ratios_searched
    if len(result.band.ratios) > len(result.ratios_searched):
        assert any("were not searched" in reason for reason in result.tally.counts)


def test_a_motor_that_cannot_do_the_job_returns_the_reason_not_an_empty_list():
    """No geometry is ever at fault here, so telling somebody to loosen the
    envelope would send them to the wrong knob entirely."""
    result = optimise(_requirements(output_rpm=200.0), effort="quick")
    assert not result.ok
    assert result.evaluations == 0
    assert result.band is not None and not result.band.ok
    assert any("out of speed" in reason for reason in result.tally.counts)


def test_a_stated_reduction_is_still_screened_against_the_motor():
    """Telling the search what motor you have should not hand you a drive that
    motor cannot turn, whether or not it chose the reduction."""
    weak = _requirements(ratio=8, motor_holding_torque_Nm=0.02)
    result = optimise(weak, effort="quick")
    assert not result.ok
    assert any("motor" in reason for reason in result.tally.counts)


def test_requirements_taken_from_a_spec_bring_its_motor_with_them():
    spec = with_motor(motor_kind=MotorKind.DC, motor_kv_rpm_per_V=140.0)
    req = requirements_from_spec(spec)
    assert req.motor_kind is MotorKind.DC
    assert req.motor.ceiling_rpm == pytest.approx(spec.motor_curve.ceiling_rpm)
    assert req.output_rpm == pytest.approx(spec.output_rpm)


def test_the_search_hands_the_motor_on_to_every_candidate():
    """A candidate whose spec has forgotten the motor would analyse as a drive
    with no curve, and the datasheet the winner arrives with would be silent
    about the one thing the search was steered by."""
    result = optimise(_requirements(), effort="quick")
    for cand in result.best:
        assert cand.spec.motor_kind is MotorKind.STEPPER
        assert cand.spec.motor_supply_V == pytest.approx(24.0)


# ------------------------------------------------- one list of eight fields --

def test_the_field_list_is_the_model_and_not_a_copy_of_it():
    """Five places carry these eight names, so they are declared once.

    Checked against the spec rather than written out again here: a ninth number
    added to the model without the list following would otherwise be dropped
    silently on every hand-off - by the search's requirements, by the candidates
    it builds, by the dialog and by the command line - and the motor that came
    out the far end would be a different motor, not an error.
    """
    on_spec = {f for f in GearSpec.model_fields if f.startswith("motor_")}
    # The two that are not part of the curve: one is the mounting face and the
    # other is a shaft decision.  Named rather than pattern-matched, so adding a
    # third of them has to be a deliberate act.
    assert on_spec - set(MOTOR_FIELDS) == {"motor_frame", "motor_drives_the_shaft"}
    assert set(MOTOR_FIELDS) <= on_spec


def test_the_curve_is_assembled_the_same_way_from_either_side():
    """A spec and a set of requirements both carry the eight fields, and both
    hand them to one function - so the two cannot come to disagree about which
    field feeds which part of the model, which is a mistake that produces a
    plausible curve rather than an error."""
    spec = with_motor(motor_kind=MotorKind.DC, motor_kv_rpm_per_V=140.0,
                      motor_supply_V=36.0)
    req = requirements_from_spec(spec)
    assert curve_from(spec) == curve_from(req) == spec.motor_curve == req.motor


# ------------------------------------------------------------ command line --

def test_the_command_line_will_not_guess_a_motor():
    """``--ratio-from-motor`` reads the curve off a design file, so without one
    there is nothing to work the reduction out from. Refused with a message that
    names the flag to add, rather than quietly falling back to a default motor
    nobody stated."""
    from cycloidgen.__main__ import main

    assert main(["--optimise", "--ratio-from-motor", "--effort", "quick"]) == 2


def test_the_command_line_takes_the_output_speed_for_a_free_reduction(tmp_path):
    """The duty the search is given is the *output's*, which is the whole point
    of letting the motor pick the reduction."""
    import json

    from cycloidgen.__main__ import main
    from cycloidgen.core.designfile import design_dict

    design = tmp_path / "driven.json"
    design.write_text(json.dumps(design_dict(
        with_motor(motor_kind=MotorKind.STEPPER))), encoding="utf-8")
    # Asked for something no NEMA 17 can do, so this returns on the band rather
    # than spending a search: exit 3 is "nothing met the requirements".
    assert main(["--optimise", "--ratio-from-motor", "--design", str(design),
                 "--torque", "50", "--out-rpm", "300", "--effort", "quick"]) == 3
