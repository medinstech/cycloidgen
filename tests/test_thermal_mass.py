"""Sliding duty, heat, mass properties and the disc web."""
from __future__ import annotations

import math

import pytest

from cycloidgen.analysis.mass import analyse_mass
from cycloidgen.analysis.thermal import CONVECTION_W_M2K, analyse_thermal
from cycloidgen.core.spec import MATERIALS, preset

# ---------------------------------------------------------------------- PV


def test_pv_is_pressure_times_speed():
    """The reported PV has to be the product of the two numbers beside it, or
    the comparison against a catalogue limit means nothing."""
    r = analyse_thermal(preset(15))
    assert r.pv_ring_MPa_m_s == pytest.approx(
        r.ring_pressure_MPa * r.ring_sliding_speed_m_s, rel=1e-9)
    assert r.pv_output_MPa_m_s == pytest.approx(
        r.output_pressure_MPa * r.output_sliding_speed_m_s, rel=1e-9)


def test_pv_uses_the_projected_area_convention():
    """Published limiting-PV figures are load over diameter x length.  Using the
    Hertzian peak instead would overstate the duty several times over.

    The reported pressure belongs to the worst *PV* contact, which is not
    generally the most heavily loaded one - the fastest-sliding contact often
    wins - so it can only be bounded by the peak-force pressure, not equal it.
    """
    spec = preset(15)
    r = analyse_thermal(spec)
    from cycloidgen.analysis.mechanics import analyse_contacts
    contact = analyse_contacts(spec)
    projected_peak = contact.max_pin_force_N / (2 * spec.pin_radius
                                                * spec.disc_thickness)
    assert 0 < r.ring_pressure_MPa <= projected_peak * (1 + 1e-9)
    assert r.ring_pressure_MPa < 0.1 * contact.max_pin_pressure_MPa


def test_pv_climbs_with_speed_and_torque():
    base = analyse_thermal(preset(15))
    fast = preset(15)
    fast.input_rpm = 3000
    heavy = preset(15)
    heavy.output_torque_Nm = 20
    assert analyse_thermal(fast).pv_ring_MPa_m_s > base.pv_ring_MPa_m_s
    assert analyse_thermal(heavy).pv_ring_MPa_m_s > base.pv_ring_MPa_m_s


def test_rollers_take_the_contact_out_of_the_pv_regime():
    sliding = analyse_thermal(preset(15))
    rolling = preset(15)
    rolling.ring_pins_are_rollers = True
    rolling.output_pins_are_rollers = True
    r = analyse_thermal(rolling)
    assert r.pv_ring_MPa_m_s < sliding.pv_ring_MPa_m_s
    assert r.pv_output_MPa_m_s < sliding.pv_output_MPa_m_s


def test_the_softer_material_sets_the_pv_limit():
    spec = preset(15)
    r = analyse_thermal(spec)
    assert r.pv_ring_limit_MPa_m_s == min(MATERIALS[spec.disc_material].pv_limit_MPa_m_s,
                                          MATERIALS[spec.pin_material].pv_limit_MPa_m_s)


def test_a_dry_printed_drive_at_speed_fails_pv():
    """This is the point of the whole module: a PLA drive can be well inside its
    stress allowable and still wear itself round."""
    spec = preset(15)
    spec.input_rpm = 1000
    assert analyse_thermal(spec).ring_pv_margin < 1.0


# ------------------------------------------------------------------ thermal


def test_temperature_follows_the_lumped_balance():
    r = analyse_thermal(preset(15))
    expected = r.loss_W / (CONVECTION_W_M2K * r.cooling_area_mm2 * 1e-6)
    assert r.temperature_rise_C == pytest.approx(expected, rel=1e-9)
    assert r.temperature_C == pytest.approx(20.0 + r.temperature_rise_C, rel=1e-9)


def test_a_bigger_housing_runs_cooler_for_the_same_loss():
    small, big = preset(15), preset(15)
    big.housing_wall = 20.0
    assert big.cooling_area_mm2 > small.cooling_area_mm2
    assert (analyse_thermal(big).temperature_rise_C
            < analyse_thermal(small).temperature_rise_C)


def test_ambient_shifts_the_answer_one_for_one():
    hot = preset(15)
    hot.ambient_temp_C = 60.0
    assert (analyse_thermal(hot).temperature_C
            == pytest.approx(analyse_thermal(preset(15)).temperature_C + 40.0, rel=1e-9))


# --------------------------------------------------------------------- mass


def test_disc_mass_is_less_than_the_cylinder_it_came_from():
    """A lobed annulus with a bore and six holes cannot weigh what a solid
    cylinder of the same outside diameter does."""
    spec = preset(15)
    m = analyse_mass(spec)
    solid = (math.pi * spec.disc_outer_radius ** 2 * spec.disc_thickness
             * 1e-3 * spec.disc_mat.density_g_cm3)
    assert 0.3 * solid < m.disc_mass_g < 0.85 * solid


def test_mass_scales_with_density_and_thickness():
    light = preset(15)
    heavy = preset(15)
    heavy.disc_material = "Steel 1045"
    ratio = MATERIALS["Steel 1045"].density_g_cm3 / MATERIALS["PLA"].density_g_cm3
    assert (analyse_mass(heavy).disc_mass_g
            == pytest.approx(analyse_mass(light).disc_mass_g * ratio, rel=1e-6))

    thick = preset(15)
    thick.disc_thickness = 2 * light.disc_thickness
    assert (analyse_mass(thick).disc_mass_g
            == pytest.approx(2 * analyse_mass(light).disc_mass_g, rel=1e-6))


def test_the_parts_add_up_to_the_assembly():
    spec = preset(15)
    m = analyse_mass(spec)
    parts = (spec.disc_count * m.disc_mass_g + m.housing_mass_g + m.plates_mass_g
             + m.pins_mass_g + m.shaft_mass_g + m.flange_mass_g)
    assert m.total_mass_g == pytest.approx(parts, rel=1e-9)


def test_radius_of_gyration_sits_inside_the_disc():
    m = analyse_mass(preset(15))
    k = math.sqrt(m.disc_inertia_kg_mm2 / (m.disc_mass_g / 1000.0))
    assert 0.0 < k < preset(15).disc_outer_radius


def test_reflected_inertia_combines_the_orbit_and_the_spin():
    """The disc orbits at input speed and spins at output speed, so the input
    sees ``m*E^2 + J/ratio^2`` per disc.  Neither term is negligible: the orbit
    radius is small but the disc's own inertia is large."""
    spec = preset(15)
    m = analyse_mass(spec)
    orbit = (m.disc_mass_g / 1000.0) * spec.eccentricity ** 2
    spin = m.disc_inertia_kg_mm2 / spec.ratio ** 2
    assert m.reflected_inertia_kg_mm2 == pytest.approx(
        spec.disc_count * (orbit + spin), rel=1e-9)


def test_a_longer_crank_throw_costs_reflected_inertia():
    small, large = preset(15), preset(15)
    large.eccentricity = 1.4 * small.eccentricity
    assert (analyse_mass(large).reflected_inertia_kg_mm2
            > analyse_mass(small).reflected_inertia_kg_mm2)


# ---------------------------------------------------------------- unbalance


def test_evenly_phased_discs_cancel_the_shaking_force():
    for count in (2, 3):
        spec = preset(15)
        spec.disc_count = count
        m = analyse_mass(spec)
        assert m.balanced
        assert m.unbalance_force_N == pytest.approx(0.0, abs=1e-9)
        assert m.unbalance_couple_Nmm > 0.0     # force cancels, couple does not


def test_a_single_disc_shakes_and_it_goes_as_speed_squared():
    slow, fast = preset(15), preset(15)
    slow.disc_count = fast.disc_count = 1
    slow.input_rpm, fast.input_rpm = 1000, 2000
    a, b = analyse_mass(slow), analyse_mass(fast)
    assert a.unbalance_force_N > 0
    assert b.unbalance_force_N == pytest.approx(4 * a.unbalance_force_N, rel=1e-6)
    assert not a.balanced


def test_the_couple_uses_the_real_disc_pitch():
    spec = preset(15)
    spec.disc_count = 2
    m = analyse_mass(spec)
    single = ((m.disc_mass_g / 1000.0) * (spec.eccentricity / 1000.0)
              * (spec.input_rpm * 2 * math.pi / 60.0) ** 2)
    arm = spec.disc_thickness + spec.disc_gap
    assert m.unbalance_couple_Nmm == pytest.approx(single * arm, rel=1e-6)


# --------------------------------------------------------------------- web


def test_web_stress_rises_as_the_ligament_thins():
    thick = preset(15)
    thin = preset(15)
    # push the bolt circle out until the outer rim ligament is the thin one
    thin.output_bolt_circle_radius = thick.output_bolt_circle_radius + 6.0
    a, b = analyse_mass(thick), analyse_mass(thin)
    assert b.min_web_mm < a.min_web_mm
    assert b.web_shear_MPa > a.web_shear_MPa


def test_web_allowable_is_von_mises_shear():
    spec = preset(15)
    m = analyse_mass(spec)
    assert m.web_shear_allow_MPa == pytest.approx(
        0.577 * spec.disc_mat.sigma_yield_MPa, rel=1e-9)


def test_a_thicker_disc_relieves_the_web():
    thin, thick = preset(15), preset(15)
    thick.disc_thickness = 3 * thin.disc_thickness
    assert analyse_mass(thick).web_shear_MPa < analyse_mass(thin).web_shear_MPa


def test_power_density_uses_the_assembled_mass():
    m = analyse_mass(preset(15))
    assert m.power_density_Nm_per_kg(10.0) == pytest.approx(
        10.0 / (m.total_mass_g / 1000.0), rel=1e-9)
