"""Clearance, stiffness and lost motion.

The clearance tests are the important ones here: two of the three offset modes
used to cut an interference instead of a gap, and nothing in the suite noticed
because every other test ran on the default mode.
"""
from __future__ import annotations

import numpy as np
import pytest

from cycloidgen.analysis.stiffness import (analyse_stiffness,
                                           line_contact_approach)
from cycloidgen.core.kinematics import mesh_gaps
from cycloidgen.core.spec import OffsetMode, Process, preset


# ------------------------------------------------------------------- clearance


@pytest.mark.parametrize("mode", list(OffsetMode))
def test_every_offset_mode_opens_a_gap(mode):
    """Whatever the mode, the disc must not touch the pins at rest.

    The pin circle mode had this backwards and drove the profile 200 um *into*
    the pins; the drive could not have been assembled.
    """
    spec = preset(15)
    spec.offset_mode = mode
    for phi in (0.0, 0.4, 1.3, 2.7):
        gaps = mesh_gaps(spec, phi)
        assert gaps.min() > 0.0, f"{mode.value} interferes by {-gaps.min() * 1000:.0f} um"


def test_equidistant_offset_gives_a_uniform_gap():
    """A normal offset moves every point of the profile by the same amount, so
    every pin should see the same clearance - that is the whole appeal."""
    spec = preset(15)
    spec.offset_mode = OffsetMode.EQUIDISTANT
    gaps = mesh_gaps(spec, 0.5)
    assert gaps.mean() == pytest.approx(spec.profile_clearance, abs=5e-3)
    assert gaps.max() - gaps.min() < 0.01


def test_gap_tracks_the_requested_clearance():
    spec = preset(15)
    for clearance in (0.05, 0.12, 0.3):
        spec.profile_clearance = clearance
        assert mesh_gaps(spec, 0.9).min() == pytest.approx(clearance, abs=5e-3)


def test_zero_clearance_touches_but_does_not_bite():
    spec = preset(15)
    spec.profile_clearance = 0.0
    gaps = mesh_gaps(spec, 0.2)
    assert abs(gaps.min()) < 5e-3


# ------------------------------------------------------------- contact springs


def test_line_contact_matches_palmgrens_roller_formula():
    """A steel roller in a raceway is the one line contact with a widely used
    empirical answer; the first-principles form has to land on it."""
    delta = float(line_contact_approach(1000.0, 10.0, 5.0, -15.0,
                                        210, 0.3, 210, 0.3, reference_mm=50.0))
    palmgren = 3.84e-5 * 1000.0 ** 0.9 / 10.0 ** 0.8
    assert delta == pytest.approx(palmgren, rel=0.35)


def test_approach_grows_with_load_and_shrinks_with_stiffness():
    args = dict(length_mm=10.0, R1_mm=4.0, R2_mm=-12.0, nu1=0.3, nu2=0.3)
    soft = float(line_contact_approach(force_N=500, E1_GPa=3.5, E2_GPa=210, **args))
    stiff = float(line_contact_approach(force_N=500, E1_GPa=210, E2_GPa=210, **args))
    heavy = float(line_contact_approach(force_N=1500, E1_GPa=210, E2_GPa=210, **args))
    assert soft > stiff
    assert heavy > stiff


def test_a_conforming_face_deflects_less_than_a_flat_one():
    args = dict(force_N=800.0, length_mm=8.0, R1_mm=4.0,
                E1_GPa=210, nu1=0.3, E2_GPa=210, nu2=0.3, reference_mm=50.0)
    conforming = float(line_contact_approach(R2_mm=-5.0, **args))
    flat = float(line_contact_approach(R2_mm=1e6, **args))
    assert conforming < flat


# ------------------------------------------------------------------- stiffness


def test_more_torque_pulls_more_pins_into_mesh():
    """With a uniform normal gap, only the long-lever-arm contacts touch at low
    torque; the rest come in as the disc rotates further."""
    engaged = []
    for torque in (0.5, 5.0, 40.0):
        spec = preset(15)
        spec.output_torque_Nm = torque
        engaged.append(analyse_stiffness(spec).pins_engaged)
    assert engaged[0] < engaged[1] < engaged[2]


def test_a_tighter_process_buys_less_backlash_and_more_stiffness():
    results = {}
    for process in (Process.FDM, Process.CNC, Process.EDM):
        spec = preset(15)
        spec.process = process
        spec.apply_process_defaults()
        results[process] = analyse_stiffness(spec)
    assert (results[Process.FDM].lost_motion_arcmin
            > results[Process.CNC].lost_motion_arcmin
            > results[Process.EDM].lost_motion_arcmin)
    assert (results[Process.FDM].stiffness_Nm_per_arcmin
            < results[Process.EDM].stiffness_Nm_per_arcmin)


def test_clearance_concentrates_load_onto_fewer_pins():
    spec = preset(15)
    result = analyse_stiffness(spec)
    assert result.load_concentration > 1.0
    assert result.pins_engaged <= result.pins_engaged_ideal


def test_hole_clearance_shows_up_as_lost_motion():
    spec = preset(15)
    loose = spec.model_copy(update={"hole_clearance": 0.6})
    tight = spec.model_copy(update={"hole_clearance": 0.05})
    assert (analyse_stiffness(loose).lost_motion_output_arcmin
            > analyse_stiffness(tight).lost_motion_output_arcmin)


def test_a_ground_steel_drive_lands_in_the_right_order_of_magnitude():
    """Commercial precision cycloidal reducers of this size quote single-digit
    arcmin backlash and tens to hundreds of Nm/arcmin.  Being an order of
    magnitude out here would mean the model is wrong, not merely optimistic."""
    spec = preset(29)
    spec.disc_material = "Steel 4140 (hardened)"
    spec.pin_material = "Bearing steel 100Cr6"
    spec.process = Process.EDM
    spec.apply_process_defaults()
    spec.output_torque_Nm = 50.0
    result = analyse_stiffness(spec)
    assert 1.0 < result.lost_motion_arcmin < 20.0
    assert 10.0 < result.stiffness_Nm_per_arcmin < 2000.0
    assert result.windup_arcmin < result.lost_motion_arcmin


def test_stiffer_material_is_stiffer():
    soft, hard = preset(15), preset(15)
    hard.disc_material = "Steel 4140 (hardened)"
    assert (analyse_stiffness(hard).stiffness_Nm_per_arcmin
            > analyse_stiffness(soft).stiffness_Nm_per_arcmin)


def test_stiffness_stages_are_in_series():
    """The whole is softer than either half - that is what series means."""
    r = analyse_stiffness(preset(15))
    assert r.stiffness_Nm_per_arcmin < min(r.ring_stage_Nm_per_arcmin,
                                           r.output_stage_Nm_per_arcmin)
    assert r.stiffness_Nm_per_arcmin == pytest.approx(
        1.0 / (1.0 / r.ring_stage_Nm_per_arcmin + 1.0 / r.output_stage_Nm_per_arcmin),
        rel=1e-9)


def test_backlash_is_lost_motion_plus_windup():
    r = analyse_stiffness(preset(15))
    assert r.backlash_total_arcmin == pytest.approx(
        r.lost_motion_arcmin + r.windup_arcmin, rel=1e-9)


def test_two_discs_share_the_load_and_stiffen_the_drive():
    one, two = preset(15), preset(15)
    one.disc_count, two.disc_count = 1, 2
    assert (analyse_stiffness(two).stiffness_Nm_per_arcmin
            > analyse_stiffness(one).stiffness_Nm_per_arcmin)


def test_mesh_gaps_are_periodic_in_the_lobe_pitch():
    """The mesh repeats every 2*pi/N of crank, so the set of gaps must too."""
    spec = preset(15)
    a = np.sort(mesh_gaps(spec, 0.31))
    b = np.sort(mesh_gaps(spec, 0.31 + 2 * np.pi / spec.lobes))
    assert np.allclose(a, b, atol=2e-3)
