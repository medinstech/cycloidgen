"""The bearing schedule: every rolling interface, counted and placed.

The failures worth guarding here are not arithmetic. They are a schedule that
quietly leaves out a load path - which reads as "that one needs no bearing" -
and a bearing chosen against the wrong diameter, which reads as a part that
fits.
"""
from __future__ import annotations

import itertools

import numpy as np
import pytest

from cycloidgen.analysis import analyse
from cycloidgen.analysis.bearings import (
    CATALOGUE,
    placements_for_spec,
    select_bearings,
)
from cycloidgen.analysis.mechanics import analyse_contacts
from cycloidgen.core.spec import CARRIER_DROP, Process, preset


def _spec(rollers: bool = True):
    spec = preset(21)
    spec.process = Process.CNC
    spec.apply_process_defaults()
    spec.disc_material = "Steel 4140 (hardened)"
    spec.pin_material = "Bearing steel 100Cr6"
    spec.ring_pins_are_rollers = rollers
    spec.output_pins_are_rollers = rollers
    return spec


def _schedule(spec):
    contact = analyse_contacts(spec)
    return select_bearings(spec, contact.eccentric_bearing_load_N,
                           contact.max_output_force_N,
                           ring_pin_load_N=contact.max_pin_force_N)


def test_every_load_path_appears():
    """Nothing supported the input shaft and no ring pin roller was ever sized,
    while a switch for them existed and changed the efficiency."""
    roles = {c.role for c in _schedule(_spec())}
    assert roles == {"Eccentric cam bearing", "Output pin roller",
                     "Ring pin roller", "Input shaft support",
                     "Main output bearing"}


def test_the_ring_pin_roller_only_appears_when_it_is_selected():
    roles = {c.role for c in _schedule(_spec(rollers=False))}
    assert "Ring pin roller" not in roles
    assert "Input shaft support" in roles


def test_the_eccentric_bearing_fits_the_cam_and_not_the_shaft():
    """Sized against the shaft it was possible to be handed a bearing whose bore
    was smaller than the cam it had to sit on - a part that cannot be assembled,
    reported as a fit."""
    spec = _spec()
    assert spec.cam_diameter > spec.input_shaft_diameter
    choice = next(c for c in _schedule(spec) if c.role == "Eccentric cam bearing")
    assert choice.bearing is not None
    assert choice.bearing.bore >= spec.cam_diameter
    assert choice.bearing.outer <= spec.center_bore_diameter
    assert choice.bearing.width <= spec.disc_thickness


def test_counts_are_numbers_rather_than_prose():
    """'(one per disc)' in the role string cannot be counted, priced or put on
    a drawing."""
    spec = _spec()
    schedule = {c.role: c for c in _schedule(spec)}
    assert schedule["Eccentric cam bearing"].count == spec.disc_count
    assert schedule["Input shaft support"].count == 2
    assert schedule["Main output bearing"].count == 1
    assert schedule["Ring pin roller"].count == spec.pin_count
    assert (schedule["Output pin roller"].count
            == spec.output_pin_count * spec.disc_count)


def test_every_role_says_what_it_carries_and_where_it_sits():
    for choice in _schedule(_spec()):
        assert choice.carries, choice.role
        if choice.count:
            assert choice.seat, choice.role


def test_a_roller_turns_slower_than_the_input():
    """It only turns as fast as the disc flank drags its surface. Taking the
    input speed would overstate the duty several times over."""
    schedule = {c.role: c for c in _schedule(_spec())}
    ring = schedule["Ring pin roller"]
    assert 0.0 < ring.speed_rpm < _spec().input_rpm


def test_the_catalogue_has_something_narrow_enough_for_a_thin_disc():
    """The eccentric bearing can be no wider than the disc, and every needle in
    the cam bore range used to be 20 mm wide - so nothing fitted an 8 mm disc,
    which read as an impossible design rather than a short list."""
    narrow = [b for b in CATALOGUE
              if b.kind == "needle" and 15 <= b.bore <= 25 and b.width <= 8]
    assert narrow


def test_the_schedule_reaches_the_analysis():
    assert len(analyse(_spec()).bearings) == 5


def test_a_bearing_that_fits_lasts_the_life_it_reports():
    """L10 goes as (C/P)^p, so halving the load has to move the life by 2^p and
    not by anything else."""
    spec = _spec()
    contact = analyse_contacts(spec)
    full = select_bearings(spec, contact.eccentric_bearing_load_N,
                           contact.max_output_force_N,
                           ring_pin_load_N=contact.max_pin_force_N)
    half = select_bearings(spec, contact.eccentric_bearing_load_N / 2.0,
                           contact.max_output_force_N,
                           ring_pin_load_N=contact.max_pin_force_N)
    a = next(c for c in full if c.role == "Eccentric cam bearing")
    b = next(c for c in half if c.role == "Eccentric cam bearing")
    assert a.bearing is not None and b.bearing is a.bearing
    assert b.life_hours == pytest.approx(
        a.life_hours * 2.0 ** a.bearing.life_exponent, rel=1e-9)


# ------------------------------------------------------------------- placement
#
# The schedule says where a bearing goes in words.  These are about saying it in
# millimetres - which is what makes it appear in the 3D view and the STEP - and
# the failures worth guarding are the ones that would look right in a picture: a
# ring in a space something else already occupies, a bearing invented where the
# model has nothing to hold it, and a picture that has quietly stopped agreeing
# with the schedule beside it.


def _big_pins():
    """A drive whose pins are large enough to carry real needle rollers.

    Everything at prototype scale is too small for a drawn cup - the smallest is
    12 mm across - so the roller paths would otherwise never be exercised at all.
    """
    spec = preset(15)
    spec.pin_radius = 7.0
    spec.disc_thickness = 12.0
    spec.output_pin_diameter = 14.0
    spec.ring_pins_are_rollers = True
    spec.output_pins_are_rollers = True
    return spec


def _placed(spec):
    return {p.name: p for p in placements_for_spec(spec)}


def test_the_cam_bearing_is_drawn_between_the_cam_and_the_disc_bore():
    """Both faces of it are somebody else's surface, so both have to clear."""
    spec = _spec()
    cam = _placed(spec)["bearing_cam_1"]
    assert cam.bore >= spec.cam_diameter
    assert cam.outer <= spec.center_bore_diameter
    assert cam.host == "disc_1"
    ring, = cam.rings
    assert (ring.cx, ring.cy) == (0.0, 0.0)      # the disc's centre is the cam's
    assert 0.0 <= ring.z0 < ring.z1 <= spec.disc_thickness


def test_one_cam_bearing_per_disc_and_each_on_its_own_disc():
    spec = _spec()
    placed = _placed(spec)
    for i in range(spec.disc_count):
        assert placed[f"bearing_cam_{i + 1}"].host == f"disc_{i + 1}"


def test_a_drawn_bearing_turns_with_the_part_it_was_placed_against():
    """The motion is taken from the host rather than worked out again.

    A cam bearing that did not orbit with its disc would sit still in the middle
    of a bore that does not, and the picture would be of a drive that cannot run.
    """
    from cycloidgen.viz.mesh import build_mesh

    spec = _spec()
    parts = {p.name: p for p in build_mesh(spec).parts}
    for placement in placements_for_spec(spec):
        bearing, host = parts[placement.name], parts[placement.host]
        assert (bearing.spin, bearing.phase, bearing.orbits) == \
            (host.spin, host.phase, host.orbits), placement.name


def test_a_bearing_is_drawn_only_when_both_its_diameters_are_known():
    """Nothing here is allowed to invent a part.

    At prototype scale no drawn cup is small enough for a ring pin, and the
    schedule's answer is a sleeve turning on a smaller pin - how much smaller
    being a diameter this app has not chosen.  Drawing a guessed wall would be
    designing the part rather than showing it.
    """
    small = _spec()                                    # rollers on, pins tiny
    schedule = {c.role: c for c in _schedule(small)}
    assert schedule["Ring pin roller"].bearing is None
    assert "bearing_ring_pins" not in _placed(small)

    placed = _placed(_big_pins())
    assert "bearing_ring_pins" in placed
    assert "bearing_output_pins" in placed


def test_a_pin_under_a_roller_shrinks_to_the_roller_bore():
    """The roller's OD *is* the working pin, so the pin cannot also have it.

    Drawn at nominal size the pin would be inside its own sleeve - two solids in
    one space, which is the one thing the software renderer cannot arbitrate.
    """
    from cycloidgen.export import solid
    from cycloidgen.viz.mesh import build_mesh

    spec = _big_pins()
    placed = _placed(spec)
    mesh = build_mesh(spec)
    pins = next(p for p in mesh.parts if p.name == "ring_pins")

    # Every vertex of the pins sits exactly the shank radius off the nearest pin
    # axis - which also says none of them has been left at nominal size.
    xy = mesh.vertices[pins.vertices][:, :2]
    angles = 2.0 * np.pi * np.arange(spec.pin_count) / spec.pin_count
    axes = spec.pin_circle_radius * np.column_stack([np.cos(angles), np.sin(angles)])
    off_axis = np.linalg.norm(xy[:, None, :] - axes[None, :, :], axis=2).min(axis=1)
    assert np.allclose(off_axis, placed["bearing_ring_pins"].bore / 2.0)
    assert placed["bearing_ring_pins"].bore < 2.0 * spec.pin_radius

    # ...and the exported solid has to be the same part, not the nominal one.
    volume = solid.ring_pins(spec, placements_for_spec(spec)).val().Volume()
    expected = (spec.pin_count * np.pi
                * (placed["bearing_ring_pins"].bore / 2.0) ** 2 * spec.stack_height)
    assert volume == pytest.approx(expected, rel=1e-6)


def test_the_output_roller_is_a_ring_with_a_wall():
    """The bug that stopped one ever being selected.

    The seat was stated as a bore of a full pin diameter *and* an OD of the hole
    less twice the eccentricity - which is the same diameter again, so the part
    asked for had no wall at all and nothing could ever match it.
    """
    spec = _big_pins()
    roller = _placed(spec)["bearing_output_pins"]
    assert roller.outer == pytest.approx(spec.output_pin_diameter)
    assert roller.bore < roller.outer
    assert roller.count % (spec.output_pin_count * spec.disc_count) == 0
    assert roller.host == "output_flange"


def test_the_shaft_supports_sit_in_a_bore_and_not_in_mid_air():
    """Both are held by something now: the input end plate at one end, the
    carrier's boss at the other.  They used to be rings on a bare shaft."""
    spec = _spec()
    placed = _placed(spec)
    inboard = spec.stack_height
    outboard = -CARRIER_DROP - spec.output_flange_thickness

    # Each is hosted on the part that holds it, which is not the same part for
    # both: the input plate does not move, the carrier's boss turns.
    assert placed["bearing_shaft_input"].host == "input_end_plate"
    assert placed["bearing_shaft_output"].host == "output_flange"

    for name, low in (("bearing_shaft_input", inboard),
                      ("bearing_shaft_output", outboard - spec.plate_thickness)):
        support = placed[name]
        assert support.bore >= spec.input_shaft_diameter
        assert support.outer <= spec.hub_bore
        ring, = support.rings
        assert -spec.shaft_overhang <= ring.z0 < ring.z1 <= \
            spec.stack_height + spec.shaft_overhang
        assert low <= ring.z0 and ring.z1 <= low + spec.plate_thickness


def test_the_shaft_is_long_enough_to_reach_through_the_boss():
    """It was not.  A fixed 12 mm overhang predates the boss existing, so the
    outboard support fell off the end of the shaft it is meant to sit on - and
    a deeper carrier made it worse rather than better."""
    spec = _spec()
    outboard = (-CARRIER_DROP - spec.output_flange_thickness
                - spec.plate_thickness)
    assert -spec.shaft_overhang < outboard

    spec.output_flange_thickness = 20.0                # a much deeper carrier
    placed = _placed(spec)
    assert "bearing_shaft_input" in placed and "bearing_shaft_output" in placed


def test_the_main_output_bearing_has_a_seat_at_last():
    """It was the one bearing with nowhere to go: no boss for its bore and no
    end plate for its outside, so it was sized and then not drawn."""
    spec = _spec()
    choice = next(c for c in _schedule(spec) if c.role == "Main output bearing")
    assert choice.bearing is not None
    placed = _placed(spec)["bearing_output_main"]
    assert placed.bore >= spec.hub_diameter
    assert placed.outer <= spec.output_bearing_seat_diameter
    assert placed.host == "output_end_plate"

    # ...and it sits in the plate rather than beside it.
    top = -CARRIER_DROP - spec.output_flange_thickness
    ring, = placed.rings
    assert top - spec.plate_thickness <= ring.z0 < ring.z1 <= top


def test_the_picture_carries_every_bearing_the_schedule_placed():
    """One selection behind both, so a bearing cannot be in one and not the other."""
    from cycloidgen.export import solid
    from cycloidgen.viz.mesh import build_mesh

    spec = _big_pins()
    placed = _placed(spec)
    drawn = {p.name for p in build_mesh(spec).parts if p.group == "bearings"}
    assert drawn == set(placed)
    assert set(solid.bearing_solids(spec)) == set(placed)


def test_the_schedule_and_the_drawing_agree_on_how_many():
    """The count on the schedule is the number of rings drawn, exactly.

    They are worked out separately - one by dividing a stack height, the other
    by laying rollers along it - so a mismatch means one of them is wrong about
    what you have to order.
    """
    spec = _big_pins()
    placed = _placed(spec).values()
    for choice in _schedule(spec):
        # A role can be split over several placements - one cam bearing per
        # disc, because each turns with a different one.
        drawn = [p for p in placed if p.role == choice.role]
        if drawn:
            assert sum(p.count for p in drawn) == choice.count, choice.role


def test_a_roller_covers_the_surface_it_is_the_surface_of():
    """One 8 mm needle on a 25 mm stack leaves the pin loose in its pocket for
    the other 17, and the schedule used to call that one roller per pin."""
    spec = _big_pins()
    sleeve = _placed(spec)["bearing_ring_pins"]
    spans = sorted({(r.z0, r.z1) for r in sleeve.rings})
    assert spans[0][0] == 0.0
    assert spans[-1][1] == pytest.approx(spec.stack_height)
    for (_, end), (start, _) in itertools.pairwise(spans):
        assert start == pytest.approx(end)       # end to end, no bare pin between


# ------------------------------------------------------- built without one
#
# Three of the five load paths can be built without a bearing, and plenty of
# drives are: a printed one usually runs its disc bore straight on the cam, and
# a drive bolted to a motor face lets that motor's bearings hold the shaft.
# These are design decisions, not display ones - the difference being that the
# part is not bought, not drawn, not exported, and the physics changes.


def _stripped():
    spec = _spec(rollers=False)
    spec.cam_bearing_fitted = False
    spec.shaft_bearings_fitted = False
    spec.output_bearing_fitted = False
    return spec


def test_an_omitted_bearing_is_not_bought_drawn_or_exported():
    """The whole difference between this and hiding it in the viewer."""
    from cycloidgen.export import solid
    from cycloidgen.export.bom import bom_items

    spec = _stripped()
    assert not placements_for_spec(spec)
    assert not solid.bearing_solids(spec)
    assert not [i for i in bom_items(analyse(spec)) if i.material == "bearing steel"]


def test_the_load_path_stays_in_the_schedule_when_the_bearing_does_not():
    """A row that vanishes reads as a load path that does not exist.

    That was the bug this schedule was rewritten to fix, and leaving a bearing
    out is not a licence to reintroduce it: the force is still there, and the
    row is what says who is taking it.
    """
    schedule = {c.role: c for c in _schedule(_stripped())}
    assert set(schedule) == {"Eccentric cam bearing", "Output pin roller",
                             "Input shaft support", "Main output bearing"}
    for role in ("Eccentric cam bearing", "Input shaft support",
                 "Main output bearing"):
        assert not schedule[role].fitted
        assert schedule[role].count == 0
        assert schedule[role].carries
        assert schedule[role].note


def test_a_bearing_left_out_is_not_a_bearing_that_does_not_fit():
    """Two different answers, and only one of them is a problem.

    Telling them apart used to mean looking for a phrase in the note - the same
    trick that got the BOM quantities wrong - so it is a field now.  The default
    design has fixed output pins, which is also a deliberate omission and must
    not warn either.
    """
    for spec in (_stripped(), _spec(rollers=False), preset(15)):
        codes = {f.code for f in analyse(spec).report.findings}
        assert "NO_BEARING_FITS" not in codes


def test_only_a_load_that_leaves_the_gearbox_is_reported_as_omitted():
    """A plain cam has no bearing, but the drive still carries that force -
    sliding, which is the PV check's business.  A drive hung on its motor's
    bearings does not carry it at all, and that is what has to be said out loud."""
    schedule = {c.role: c for c in _schedule(_stripped())}
    assert not schedule["Eccentric cam bearing"].carried_elsewhere
    assert schedule["Input shaft support"].carried_elsewhere
    assert schedule["Main output bearing"].carried_elsewhere

    finding = next(f for f in analyse(_stripped()).report.findings
                   if f.code == "BEARINGS_OMITTED")
    assert "input shaft support" in finding.message
    assert "main output bearing" in finding.message
    assert "eccentric cam bearing" not in finding.message


def test_the_cam_grows_to_fill_the_bore_when_nothing_sits_between_them():
    """The default cam is the bore less 8 mm to leave a bearing wall.  Keeping
    that gap with no bearing in it is a disc flopping about on a shaft."""
    fitted, plain = _spec(), _stripped()
    assert fitted.cam_diameter == pytest.approx(fitted.center_bore_diameter - 8.0)
    assert plain.cam_diameter == pytest.approx(plain.center_bore_diameter)


def test_a_plain_cam_costs_what_a_plain_cam_costs():
    """It is the fastest-turning contact in the drive; swapping a rolling
    coefficient for a sliding one there is not a rounding difference."""
    from cycloidgen.analysis.efficiency import analyse_efficiency

    fitted = _spec(rollers=False)
    plain = fitted.model_copy(update={"cam_bearing_fitted": False})
    assert analyse_efficiency(plain).efficiency < \
        0.8 * analyse_efficiency(fitted).efficiency


def test_a_bearing_the_drive_does_not_carry_is_not_its_loss_either():
    """Drag on a flange the driven machine locates belongs to that machine."""
    from cycloidgen.analysis.efficiency import analyse_efficiency

    fitted = _spec(rollers=False)
    without = fitted.model_copy(update={"output_bearing_fitted": False})
    assert analyse_efficiency(without).loss_bearings_W < \
        analyse_efficiency(fitted).loss_bearings_W


def test_the_plain_cam_gets_a_wear_check_and_a_fitted_one_does_not():
    """A printed disc running dry on a steel cam is the textbook PV failure, and
    nothing in the app had ever asked about that contact."""
    from cycloidgen.analysis.thermal import analyse_thermal

    fitted = preset(15)
    assert analyse_thermal(fitted).pv_cam_MPa_m_s == 0.0
    assert analyse_thermal(fitted).cam_pv_margin == float("inf")

    plain = fitted.model_copy(update={"cam_bearing_fitted": False})
    duty = analyse_thermal(plain)
    assert duty.pv_cam_MPa_m_s > 0.0
    assert duty.cam_pv_margin < 1.0                  # PLA on steel, dry, at speed
    assert "PV_LIMIT_CAM" in {f.code for f in analyse(plain).report.findings}


# -------------------------------------------------------------- named by hand
#
# The sizing study takes the smallest part that fits the seat and lasts, which
# is the right default and the wrong answer whenever something outside the
# geometry is deciding: a bearing already in the drawer, one the supplier
# stocks, or simply a bigger one than the smallest that will do.


def _named(role_field, designation, spec=None):
    spec = spec or _spec(rollers=False)
    setattr(spec, role_field, designation)
    return {c.role: c for c in _schedule(spec)}, spec


def test_a_named_bearing_is_used_instead_of_the_smallest_that_fits():
    auto = {c.role: c for c in _schedule(_spec(rollers=False))}
    assert auto["Input shaft support"].bearing.designation == "6800"

    schedule, _ = _named("shaft_bearing", "6004")
    chosen = schedule["Input shaft support"].bearing
    assert chosen.designation == "6004"
    assert chosen.outer > auto["Input shaft support"].bearing.outer


def test_a_named_bearing_that_does_not_fit_is_reported_not_replaced():
    """'This is the bearing I have' is exactly the case where quietly handing
    back a different one is useless."""
    schedule, spec = _named("cam_bearing", "HK2020")     # 20 mm wide, 8 mm disc
    choice = schedule["Eccentric cam bearing"]
    assert choice.bearing.designation == "HK2020"        # not swapped
    assert not choice.fits
    assert "20 mm wide" in choice.problem
    assert "BEARING_DOES_NOT_FIT" in {f.code for f in analyse(spec).report.findings}


def test_a_bearing_that_does_not_go_in_is_not_drawn_either():
    """Drawing it would mean shrinking it to the seat, and a picture of a part
    at a size it is not is worse than no picture."""
    _, spec = _named("cam_bearing", "HK2020")
    assert not [p for p in placements_for_spec(spec) if p.name.startswith("bearing_cam")]
    # ...and the seats that are still fine are untouched
    assert [p for p in placements_for_spec(spec) if p.name.startswith("bearing_shaft")]


def test_a_bore_standing_off_its_journal_is_a_fit_but_it_is_reported():
    """A press fit onto nothing.  The sizing study takes any bore at or above
    the journal, so this was reachable on automatic too and said nothing."""
    schedule, spec = _named("shaft_bearing", "6801")     # 12 mm bore, 10 mm shaft
    choice = schedule["Input shaft support"]
    assert choice.fits                                   # it goes in, loosely
    assert "stands 2.00 mm off" in choice.problem
    assert [p for p in placements_for_spec(spec) if p.name.startswith("bearing_shaft")]


def test_a_designation_this_build_does_not_know_costs_a_warning_not_a_crash():
    """A design saved by a later version must open, not fail to load - so the
    field is a plain string with no validator, and this is where it is caught."""
    schedule, spec = _named("cam_bearing", "HK9999")
    choice = schedule["Eccentric cam bearing"]
    assert choice.bearing is None
    assert "not a designation this build knows" in choice.problem
    assert analyse(spec).report is not None


def test_a_ball_bearing_is_refused_where_the_seat_wants_a_needle():
    schedule, _ = _named("ring_pin_roller", "6800", spec=_big_pins())
    assert "is a ball bearing" in schedule["Ring pin roller"].problem


def test_the_required_life_is_the_design_s_and_not_two_hidden_numbers():
    """Selection used to accept 1000 h while the report warned below 5000, so a
    bearing could be picked and complained about in the same breath."""
    spec = _spec(rollers=False)
    assert spec.bearing_min_life_hours == 5000.0
    for choice in _schedule(spec):
        if choice.bearing is not None:
            assert choice.life_hours >= spec.bearing_min_life_hours

    # Ask for more than anything can give and the seats come back empty rather
    # than filled with something that does not meet the requirement.
    spec.bearing_min_life_hours = 5e8
    assert all(c.bearing is None for c in _schedule(spec) if c.fitted)


def test_a_named_bearing_short_of_the_required_life_is_the_one_case_that_warns():
    """The study will not return one under the line, so only a hand-picked part
    can be - which is why the two numbers have to be the same number."""
    spec = _spec(rollers=False)
    spec.shaft_bearing = "6800"
    spec.bearing_min_life_hours = 1e7          # past what 6800 gives here
    codes = {f.code for f in analyse(spec).report.findings}
    assert "SHORT_BEARING_LIFE" in codes


def test_the_panel_offers_every_catalogue_part_and_the_automatic_setting():
    """A bearing added to the catalogue has to appear in the panel without
    anyone remembering to add it there as well."""
    from cycloidgen.core.spec import AUTOMATIC
    from cycloidgen.ui.fields import GROUPS

    fields = {f.name: f for _, group in GROUPS for f in group}
    offered = fields["cam_bearing"].choices
    assert offered[0] == AUTOMATIC
    assert set(offered[1:]) == {b.designation for b in CATALOGUE}


# ------------------------------------------------- the seats that did not exist


def test_every_bearing_the_drive_fits_is_drawn_somewhere():
    """The point of the end plates and the boss.

    Before them the main output bearing was sized and then not drawn - there was
    no hub for its bore and no plate for its outside - and the shaft supports
    were rings on a bare shaft with nothing around them.
    """
    spec = _spec(rollers=False)
    drawn = {p.role for p in placements_for_spec(spec)}
    for choice in _schedule(spec):
        if choice.bearing is not None and choice.fits:
            assert choice.role in drawn, choice.role


def test_the_end_plates_are_bored_for_what_goes_in_them():
    """Two plates, and they are not interchangeable: one takes a shaft support,
    the other the bearing the whole drive turns on."""
    from cycloidgen.export import solid

    spec = _spec()
    assert spec.hub_bore < spec.output_bearing_seat_diameter
    made = solid.parts(spec)
    assert {"input_end_plate", "output_end_plate"} <= set(made)

    # The bore is the difference between them, so their volumes must differ.
    assert made["input_end_plate"].val().Volume() > \
        made["output_end_plate"].val().Volume()


def test_the_boss_is_a_tube_the_shaft_passes_through():
    """It carries the output bearing outside and a shaft support inside, so it
    has to be open: a solid boss would have nowhere for the shaft to go."""
    spec = _spec()
    assert spec.input_shaft_diameter < spec.hub_bore < spec.hub_diameter
    assert spec.hub_diameter < spec.output_bearing_seat_diameter


def test_the_envelope_counts_the_plates_that_close_it():
    """They are part of the gearbox - they carry three of its bearings - and
    leaving them out understated the length of every drive this app has sized."""
    spec = _spec()
    assert spec.envelope_length > (spec.stack_height
                                   + spec.output_flange_thickness)
    assert spec.envelope_length == pytest.approx(
        spec.stack_height + CARRIER_DROP + spec.output_flange_thickness
        + 2.0 * spec.plate_thickness)


def test_the_plates_are_weighed():
    """A third of the assembled mass was simply not being counted."""
    from cycloidgen.analysis.mass import analyse_mass

    spec = _spec()
    with_plates = analyse_mass(spec).total_mass_g
    spec.end_plate_thickness = 0.001                   # as good as none
    assert analyse_mass(spec).total_mass_g < with_plates
