"""Clearance, stiffness and lost motion.

The clearance tests are the important ones here: two of the three offset modes
used to cut an interference instead of a gap, and nothing in the suite noticed
because every other test ran on the default mode.
"""
from __future__ import annotations

import numpy as np
import pytest

from cycloidgen.analysis.stiffness import (
    analyse_stiffness,
    analyse_transmission_error,
    line_contact_approach,
    output_stage_period,
)
from cycloidgen.core.kinematics import mesh_gaps, output_loads
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
    args = {"length_mm": 10.0, "R1_mm": 4.0, "R2_mm": -12.0,
            "nu1": 0.3, "nu2": 0.3}
    soft = float(line_contact_approach(force_N=500, E1_GPa=3.5, E2_GPa=210, **args))
    stiff = float(line_contact_approach(force_N=500, E1_GPa=210, E2_GPa=210, **args))
    heavy = float(line_contact_approach(force_N=1500, E1_GPa=210, E2_GPa=210, **args))
    assert soft > stiff
    assert heavy > stiff


def test_a_conforming_face_deflects_less_than_a_flat_one():
    args = {"force_N": 800.0, "length_mm": 8.0, "R1_mm": 4.0,
            "E1_GPa": 210, "nu1": 0.3, "E2_GPa": 210, "nu2": 0.3,
            "reference_mm": 50.0}
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
    """The whole is softer than any part of it - that is what series means.

    Two decompositions of the same number, and both have to hold exactly:
    the contacts split into their two stages, and the drive splits into its
    contacts and everything the contacts are mounted in.
    """
    r = analyse_stiffness(preset(15))
    assert r.contact_only_Nm_per_arcmin == pytest.approx(
        1.0 / (1.0 / r.ring_stage_Nm_per_arcmin + 1.0 / r.output_stage_Nm_per_arcmin),
        rel=1e-9)
    assert r.stiffness_Nm_per_arcmin == pytest.approx(
        1.0 / (1.0 / r.contact_only_Nm_per_arcmin + 1.0 / r.structure_Nm_per_arcmin),
        rel=1e-9)
    assert r.stiffness_Nm_per_arcmin < min(r.ring_stage_Nm_per_arcmin,
                                           r.output_stage_Nm_per_arcmin,
                                           r.structure_Nm_per_arcmin)


def test_the_structure_is_the_series_of_its_own_parts():
    r = analyse_stiffness(preset(15))
    parts = r.structure.items
    assert len(parts) == 6
    assert r.structure_Nm_per_arcmin == pytest.approx(
        1.0 / sum(1.0 / k for _name, k in parts), rel=1e-9)
    assert r.structure.total_Nm_per_arcmin == pytest.approx(
        r.structure_Nm_per_arcmin, rel=1e-9)
    assert r.structure.softest == min(parts, key=lambda kv: kv[1])[0]


def test_the_parts_outside_the_mesh_only_ever_make_it_softer():
    """They used to be rigid, so the old answer is now the upper bound it always
    said it was - and every design has to sit under it."""
    for spec in (preset(15), preset(29), preset(10)):
        r = analyse_stiffness(spec)
        assert r.stiffness_Nm_per_arcmin < r.contact_only_Nm_per_arcmin
        assert r.windup_arcmin > 0.0


def test_a_stouter_carrier_stiffens_the_drive():
    """The carrier pins are cantilevers, so their diameter is a fourth power and
    the biggest single lever on a drive whose mesh is already stiff."""
    thin, fat = preset(15), preset(15)
    thin.output_pin_diameter, fat.output_pin_diameter = 5.0, 8.0
    a, b = analyse_stiffness(thin), analyse_stiffness(fat)
    assert (b.structure.output_pin_Nm_per_arcmin
            > 3.0 * a.structure.output_pin_Nm_per_arcmin)
    assert b.stiffness_Nm_per_arcmin > a.stiffness_Nm_per_arcmin


def test_a_softer_housing_shows_up_in_the_parts_it_is_made_of():
    """Ring, housing and carrier are all housing_material, so switching it moves
    three of the six terms and none of the others."""
    printed, machined = preset(15), preset(15)
    machined.housing_material = "Aluminium 7075-T6"
    a, b = analyse_stiffness(printed).structure, analyse_stiffness(machined).structure
    assert b.housing_Nm_per_arcmin > a.housing_Nm_per_arcmin
    assert b.carrier_plate_Nm_per_arcmin > a.carrier_plate_Nm_per_arcmin
    assert b.ring_seat_Nm_per_arcmin > a.ring_seat_Nm_per_arcmin
    assert b.disc_body_Nm_per_arcmin == pytest.approx(a.disc_body_Nm_per_arcmin)
    assert b.input_shaft_Nm_per_arcmin == pytest.approx(a.input_shaft_Nm_per_arcmin)


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


def test_cached_gaps_cannot_be_scribbled_on():
    """The array is shared between every caller that asks for the same angle."""
    gaps = mesh_gaps(preset(15), 0.31)
    with pytest.raises(ValueError):
        gaps[0] = 99.0


# --------------------------------------------------------- transmission error


def test_the_output_stage_really_does_repeat_on_its_own_period():
    """The period the sweep uses, checked against the loads themselves.

    It is not the lobe pitch: the eccentricity direction seen from the carrier
    advances at (N-1)/N of the crank, so the load pattern comes back around
    after 2*pi*N/(n*(N-1)).  Sweeping a lobe pitch instead reports about half
    the ripple that is really there.

    The pattern returns turned by one pin pitch, so it is the *set* of forces
    that repeats rather than each pin's own - and a rotation is exactly what the
    solver cannot tell apart.
    """
    spec = preset(15)
    period = output_stage_period(spec)
    assert period > 2.0 * np.pi / spec.lobes            # longer than a lobe pitch
    for phi in (0.13, 0.77, 1.9):
        a = np.sort(output_loads(spec, phi, 1000.0).forces)
        b = np.sort(output_loads(spec, phi + period, 1000.0).forces)
        assert np.allclose(a, b, atol=1e-9)


def test_transmission_error_is_a_real_ripple_and_the_stages_add():
    r = analyse_transmission_error(preset(15))
    assert r.peak_to_peak_arcmin > 0.0
    assert r.peak_to_peak_arcmin == pytest.approx(r.ring_arcmin + r.output_arcmin)
    assert 0.0 < r.rms_arcmin < r.peak_to_peak_arcmin


def test_a_tighter_process_cuts_transmission_error():
    """The clearance is in it, not only the deflection, so the fit is the lever."""
    results = {}
    for process in (Process.FDM, Process.CNC, Process.EDM):
        spec = preset(15)
        spec.process = process
        spec.apply_process_defaults()
        results[process] = analyse_transmission_error(spec).peak_to_peak_arcmin
    assert results[Process.FDM] > results[Process.CNC] > results[Process.EDM]


def test_more_output_pins_cut_transmission_error():
    """The output stage is most of it, and it is a handover between pins: the
    more pins share the cycle, the less the output angle moves at each one."""
    errors = [analyse_transmission_error(
        preset(15).model_copy(update={"output_pin_count": n})).peak_to_peak_arcmin
        for n in (4, 6, 10)]
    assert errors[0] > errors[1] > errors[2]


def test_a_stiffer_disc_does_not_fix_transmission_error():
    """The one worth pinning, because it is the fix everybody reaches for first.

    Stiffening the disc leaves the clearance to be taken up exactly where it
    was, and pulls fewer pins into mesh while it is at it - so the ring stage's
    share of the ripple comes out *worse*, not better.  Lost motion and
    transmission error do not have the same cure.
    """
    soft, hard = preset(15), preset(15)
    hard.disc_material = "Steel 4140 (hardened)"
    assert (analyse_transmission_error(hard).ring_arcmin
            > analyse_transmission_error(soft).ring_arcmin)


def test_transmission_error_does_not_vanish_at_light_load():
    """It is not purely elastic: at a twentieth of the rated torque the drive is
    barely deflected and the ripple is still there, because what is left is the
    clearance take-up wandering as the contact that bites first changes."""
    rated, light = preset(15), preset(15)
    light.output_torque_Nm = rated.output_torque_Nm / 20.0
    assert (analyse_transmission_error(light).peak_to_peak_arcmin
            > 0.5 * analyse_transmission_error(rated).peak_to_peak_arcmin)


def test_a_phased_disc_stack_cancels_ripple():
    """Discs on opposite crank phases ride opposite halves of the same mesh
    cycle, so most of the fundamental cancels.  This is the one thing about
    transmission error that a stiffness average cannot see: the *mean* is
    unchanged by phasing, and the ripple is not."""
    one, two = preset(15), preset(15)
    one.disc_count, two.disc_count = 1, 2
    assert (analyse_transmission_error(two).peak_to_peak_arcmin
            < analyse_transmission_error(one).peak_to_peak_arcmin)


def test_the_default_sweep_resolves_the_ripple():
    """A ripple sampled too coarsely is reported too small.  The shipped step
    counts have to be close to a sweep several times finer."""
    for spec in (preset(15), preset(29)):
        coarse = analyse_transmission_error(spec).peak_to_peak_arcmin
        fine = analyse_transmission_error(spec, steps=192,
                                          ring_steps=36).peak_to_peak_arcmin
        assert coarse == pytest.approx(fine, rel=0.05)


def test_a_ground_steel_drive_has_far_less_of_it():
    """Order of magnitude, not decimals: a printed drive is arcminutes and a
    ground steel one is arcseconds, and the model has to say so."""
    printed = analyse_transmission_error(preset(29)).peak_to_peak_arcmin
    spec = preset(29)
    spec.disc_material = "Steel 4140 (hardened)"
    spec.pin_material = "Bearing steel 100Cr6"
    spec.process = Process.EDM
    spec.apply_process_defaults()
    ground = analyse_transmission_error(spec).peak_to_peak_arcmin
    assert ground < printed / 10.0
