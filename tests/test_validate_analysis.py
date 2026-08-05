"""Checks and the engineering analysis."""
from __future__ import annotations

import numpy as np
import pytest

from cycloidgen.analysis import analyse
from cycloidgen.analysis.efficiency import analyse_efficiency
from cycloidgen.analysis.mechanics import (
    analyse_contacts,
    effective_modulus,
    hertz_line_pressure,
    torque_capacity,
)
from cycloidgen.core.spec import GearSpec, Process, preset
from cycloidgen.core.validate import Severity, validate


def _codes(rep):
    return {f.code for f in rep.findings}


def test_clean_design_has_no_errors():
    assert validate(preset(15)).ok


def test_undercut_is_caught():
    s = preset(15)
    s.pin_radius = 30.0            # far past the curvature limit
    rep = validate(s)
    assert not rep.ok
    assert "UNDERCUT" in _codes(rep)


def test_k1_above_one_is_an_error():
    s = GearSpec(lobes=11, pin_circle_radius=20.0, pin_radius=1.0, eccentricity=2.0)
    assert s.K1 >= 1.0
    assert "K1_TOO_HIGH" in _codes(validate(s))


def test_output_holes_breaking_into_the_bore_is_an_error():
    s = preset(15)
    s.output_bolt_circle_radius = s.center_bore_diameter / 2 + 1.0
    rep = validate(s)
    assert not rep.ok
    assert "HOLE_HITS_BORE" in _codes(rep)


def test_output_holes_breaking_the_rim_is_an_error():
    s = preset(15)
    s.output_bolt_circle_radius = s.pin_circle_radius
    assert "HOLE_BREAKS_RIM" in _codes(validate(s))


def test_overlapping_ring_pins_are_caught():
    s = preset(15)
    # pins touch when Rr == R*sin(pi/pins); go just past it
    s.pin_radius = 1.05 * s.pin_circle_radius * np.sin(np.pi / s.pin_count)
    assert "PIN_OVERLAP" in _codes(validate(s))


def test_single_disc_at_speed_warns():
    s = preset(15)
    s.disc_count = 1
    s.input_rpm = 3000
    assert "SINGLE_DISC_UNBALANCE" in _codes(validate(s))


def test_tight_clearance_warns():
    s = preset(15)
    s.process = Process.FDM
    s.profile_clearance = 0.01
    assert "CLEARANCE_DEFICIT" in _codes(validate(s))


def test_pressure_angle_is_sane():
    """Must be reported at the loaded contact, not at a zero-torque one."""
    findings = {f.code: f for f in validate(preset(15)).findings}
    assert 0.0 < findings["PRESSURE_ANGLE"].value < 89.0


# --------------------------------------------------------------------- analysis


def test_hertz_matches_the_textbook_case():
    """Steel cylinder on a flat steel plate, 1000 N over 10 mm."""
    e_star = effective_modulus(210, 0.3, 210, 0.3)
    p = float(hertz_line_pressure(1000.0, 10.0, 10.0, e_star))
    # p_max = sqrt(F' E* / (pi R))
    assert p == pytest.approx(np.sqrt(100.0 * e_star / (np.pi * 10.0)), rel=1e-12)
    assert 500 < p < 1500                      # sanity: right order of magnitude


def test_equivalent_radius_collapses_at_the_undercut_limit():
    """R_eq_min = Rr (1 - Rr/rho_c): a parabola that peaks at Rr = rho_c/2 and
    goes to zero at the limit.  So contact stress is worst for a *very* large or
    a very small pin, and best at half the critical radius."""
    from cycloidgen.core.profile import critical_radius
    s = preset(15)
    rho_c = critical_radius(s.pin_circle_radius, s.eccentricity, s.lobes)

    def r_eq(frac):
        t = s.model_copy(update={"pin_radius": frac * rho_c})
        return analyse_contacts(t).min_R_eq_mm

    assert r_eq(0.95) < r_eq(0.50)
    assert r_eq(0.05) < r_eq(0.50)
    assert r_eq(0.50) == pytest.approx(0.25 * rho_c, rel=0.02)


def test_torque_capacity_is_self_consistent():
    s = preset(15)
    cap = torque_capacity(s)
    s2 = s.model_copy(update={"output_torque_Nm": cap})
    assert analyse_contacts(s2).pin_safety_factor == pytest.approx(1.0, rel=2e-2)


def test_stronger_material_carries_more_torque():
    soft = preset(15)
    hard = preset(15)
    hard.disc_material = "Steel 4140 (hardened)"
    assert torque_capacity(hard) > 10 * torque_capacity(soft)


def test_two_discs_halve_the_pin_load():
    one, two = preset(15), preset(15)
    one.disc_count, two.disc_count = 1, 2
    assert analyse_contacts(two).max_pin_force_N == pytest.approx(
        analyse_contacts(one).max_pin_force_N / 2, rel=1e-6)


def test_efficiency_is_a_fraction_and_rollers_help():
    s = preset(15)
    fixed = analyse_efficiency(s)
    assert 0.0 < fixed.efficiency < 1.0
    s.ring_pins_are_rollers = True
    s.output_pins_are_rollers = True
    assert analyse_efficiency(s).efficiency > fixed.efficiency


def test_power_balance_closes():
    e = analyse_efficiency(preset(15))
    assert e.input_power_W == pytest.approx(e.output_power_W + e.total_loss_W, rel=1e-9)


def test_analysis_bundles_findings():
    a = analyse(preset(29))
    assert a.spec.ratio == 29
    assert a.contact.max_pin_force_N > 0
    # Four load paths on fixed ring pins, five when they are rollers: the
    # eccentric cam, the output pins, the input shaft and the output flange.
    assert len(a.bearings) == 4 + int(a.spec.ring_pins_are_rollers)
    assert all(f.severity in Severity for f in a.report.findings)
