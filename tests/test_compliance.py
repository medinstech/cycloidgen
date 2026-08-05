"""The springs outside the contacts, one formula at a time.

These are closed forms, so they get checked against the closed form rather than
against each other: a sign error in an exponent is invisible in a trend test and
obvious in a number.
"""
from __future__ import annotations

import math

import pytest

from cycloidgen.analysis.compliance import (
    analyse_parts,
    annulus_torsion_stiffness,
    barrel_torsion_stiffness,
    cantilever_stiffness,
    series_stiffness,
    shear_modulus,
)
from cycloidgen.core.spec import MATERIALS, preset

# --------------------------------------------------------------------- series


def test_springs_in_series_add_their_compliances():
    assert series_stiffness(10.0, 10.0) == pytest.approx(5.0)
    assert series_stiffness(2.0, 3.0, 6.0) == pytest.approx(1.0)


def test_a_rigid_part_is_the_identity_and_a_dead_one_absorbs():
    """`inf` is what "not modelled, taken as rigid" has to mean, or adding a
    part the app knows nothing about would change the answer."""
    assert series_stiffness(7.0, math.inf) == pytest.approx(7.0)
    assert series_stiffness(math.inf, math.inf) == math.inf
    assert series_stiffness(7.0, 0.0) == 0.0


# ------------------------------------------------------------------- formulae


def test_shear_modulus_is_the_isotropic_relation():
    steel = MATERIALS["Steel 1045"]
    assert shear_modulus(steel) == pytest.approx(
        steel.E_GPa * 1000.0 / (2.0 * (1.0 + steel.nu)))
    assert shear_modulus(steel) == pytest.approx(79457.4, rel=1e-4)


def test_the_annulus_matches_its_closed_form():
    G, t, r_i, r_o = 79000.0, 6.0, 10.0, 40.0
    expected = 4.0 * math.pi * G * t / (1.0 / r_i ** 2 - 1.0 / r_o ** 2)
    assert annulus_torsion_stiffness(G, t, r_i, r_o) == pytest.approx(expected)


def test_a_plate_driven_at_its_hub_is_far_softer_than_one_driven_at_its_rim():
    """The whole carrier-plate assumption in one test.

    The formula goes as 1/r**2, so where the torque is taken off decides the
    answer.  Same plate, same material: crossing it from the bolt circle out to
    the rim is stiff, and funnelling the same torque into a hub on the axis is
    not remotely the same part.
    """
    G, t = 1287.0, 6.0
    rim = annulus_torsion_stiffness(G, t, 30.0, 36.0)
    hub = annulus_torsion_stiffness(G, t, 5.5, 30.0)
    assert rim > 10.0 * hub


def test_the_barrel_is_G_J_over_L():
    assert barrel_torsion_stiffness(80000.0, 1000.0, 20.0) == pytest.approx(4.0e6)


def test_a_stubby_cantilever_is_softer_than_bending_alone_says():
    """Shear is not a rounding error at these proportions - a 6 mm pin reaching
    8.5 mm out of a carrier loses about a fifth of its stiffness to it."""
    E, nu, d, a = 205000.0, 0.29, 6.0, 8.5
    second_moment = 0.25 * math.pi * (d / 2.0) ** 4
    bending_only = 3.0 * E * second_moment / a ** 3
    k = cantilever_stiffness(E, nu, d, a)
    assert k < bending_only
    assert k == pytest.approx(bending_only, rel=0.35)


def test_a_slender_cantilever_is_all_bending():
    E, nu, d, a = 205000.0, 0.29, 6.0, 120.0
    second_moment = 0.25 * math.pi * (d / 2.0) ** 4
    bending_only = 3.0 * E * second_moment / a ** 3
    assert cantilever_stiffness(E, nu, d, a) == pytest.approx(bending_only, rel=0.01)


def test_a_cantilever_stiffens_as_the_fourth_power_of_diameter():
    """Near enough: the bending term is d**4 and the shear term is d**2, so
    doubling the diameter buys somewhere between 4x and 16x."""
    thin = cantilever_stiffness(205000.0, 0.29, 5.0, 8.5)
    fat = cantilever_stiffness(205000.0, 0.29, 10.0, 8.5)
    assert 4.0 < fat / thin < 16.0


# ----------------------------------------------------------------- the drive


def test_every_part_of_a_real_drive_gets_a_finite_stiffness():
    parts = analyse_parts(preset(15))
    for name, value in vars(parts).items():
        assert math.isfinite(value) and value > 0.0, name


def test_the_parts_answer_to_the_dimensions_that_make_them():
    thin, thick = preset(15), preset(15)
    thick.housing_wall = 3.0 * thin.housing_wall
    assert (analyse_parts(thick).housing_Nmm_per_rad
            > analyse_parts(thin).housing_Nmm_per_rad)

    thin, thick = preset(15), preset(15)
    thick.output_flange_thickness = 2.0 * thin.output_flange_thickness
    assert analyse_parts(thick).carrier_plate_Nmm_per_rad == pytest.approx(
        2.0 * analyse_parts(thin).carrier_plate_Nmm_per_rad)

    one, two = preset(15), preset(15)
    one.disc_count, two.disc_count = 1, 2
    # two discs share the torque in parallel, but a taller stack is a longer
    # cantilever for the carrier pins - the two go opposite ways on purpose
    assert (analyse_parts(two).disc_body_Nmm_per_rad
            > analyse_parts(one).disc_body_Nmm_per_rad)
    assert (analyse_parts(two).output_pin_N_per_mm
            < analyse_parts(one).output_pin_N_per_mm)


def test_the_input_shaft_is_divided_by_the_square_of_the_ratio():
    """Referred to the output, which is where everything here is referred.  It
    is why the one part carrying the least material worries the model least."""
    spec = preset(15)
    parts = analyse_parts(spec)
    raw = barrel_torsion_stiffness(
        shear_modulus(spec.shaft_mat),
        0.5 * math.pi * (spec.input_shaft_diameter / 2.0) ** 4,
        spec.stack_height + 24.0)
    assert parts.input_shaft_Nmm_per_rad == pytest.approx(raw * spec.ratio ** 2)
