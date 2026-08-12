"""Which member the output comes off, and everything that follows from it.

A cycloidal drive is a three-shaft machine.  The crank is always the input; the
ring and the carrier are interchangeable, and grounding one rather than the
other is a real design choice that changes the reduction, the direction, the
speed of every rubbing contact, which part turns on screen and which end of the
gearbox the motor bolts to.  The app used to have the first of the two wired in
as an assumption spread across a dozen modules.

The tests here fall into two groups.  The first re-derives the motion from the
meshing constraint and checks the rate model against it - that is the half that
found a sign error the analysis had been carrying in three places.  The second
follows the choice out into the geometry, because a ratio that changes while
the motor stays bolted to a plate that now turns is not a feature, it is a
gearbox nobody can build.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from cycloidgen.analysis import analyse
from cycloidgen.core import kinematics as kin
from cycloidgen.core.spec import OutputMember, preset

RATIOS = [10, 15, 21, 29, 39, 59]


def _spec(ratio: int = 15, member: OutputMember = OutputMember.RING, **kw):
    spec = preset(ratio)
    spec.output_member = member
    for name, value in kw.items():
        setattr(spec, name, value)
    return spec


# ------------------------------------------------------------------- the ratio


@pytest.mark.parametrize("ratio", RATIOS)
def test_grounding_the_other_member_is_worth_exactly_one_tooth(ratio):
    """The two members are one tooth apart, so the two reductions are too.

    Not an approximation and not a coincidence: it is the whole content of a
    single-tooth-difference drive, and it is the reason a ring-output build is
    free reduction - the same parts, bolted down at the other end.
    """
    carrier = _spec(ratio, OutputMember.CARRIER)
    ring = _spec(ratio, OutputMember.RING)
    assert carrier.ratio == carrier.lobes
    assert ring.ratio == ring.pin_count
    assert ring.ratio == carrier.ratio + 1


@pytest.mark.parametrize("ratio", RATIOS)
def test_the_ratio_is_the_quotient_of_the_two_spins_it_is_meant_to_be(ratio):
    """``ratio`` is declared as a tooth count and used as a speed ratio.

    Those are two different statements about the drive and only one of them is
    in the code, so this is where they are held together: whatever the spins
    say the reduction is, the integer has to agree - and it has to agree in
    both configurations, which is what stops the field being right by accident
    in the one it was written for.
    """
    for member in OutputMember:
        spec = _spec(ratio, member)
        assert abs(spec.shaft_spin / spec.output_spin) == pytest.approx(spec.ratio)
        assert spec.output_rpm == pytest.approx(spec.input_rpm / spec.ratio)


@pytest.mark.parametrize("ratio", RATIOS)
def test_only_the_carrier_reverses(ratio):
    """Off the carrier the output turns against the input; off the ring it turns
    with it.  Read off the signs rather than declared, so the flag cannot
    disagree with the picture drawn from the same numbers."""
    carrier, ring = _spec(ratio, OutputMember.CARRIER), _spec(ratio, OutputMember.RING)
    assert carrier.output_reverses
    assert not ring.output_reverses
    assert (carrier.output_spin < 0) != (carrier.shaft_spin < 0)
    assert (ring.output_spin < 0) == (ring.shaft_spin < 0)


# -------------------------------------------------------------- the rate model


@pytest.mark.parametrize("ratio", RATIOS)
def test_a_relative_speed_does_not_care_which_member_is_bolted_down(ratio):
    """Grounding a member adds one rigid rotation to the whole drive.

    So anything measured *between* two bodies has to come out the same in both
    configurations when it is stated per unit crank angle - and anything
    measured against the ground has to differ.  Both halves matter: a model
    that got the first wrong would report a mesh that changes when you turn the
    gearbox round, and one that got the second wrong would report an output
    that does not.
    """
    carrier, ring = _spec(ratio, OutputMember.CARRIER), _spec(ratio, OutputMember.RING)
    for a, b in ((carrier, ring),):
        assert (a.disc_spin - a.shaft_spin) == pytest.approx(b.disc_spin - b.shaft_spin)
        assert (a.carrier_spin - a.ring_spin) == pytest.approx(
            b.carrier_spin - b.ring_spin)
    # ...and against the ground they differ, which is the point of the choice
    assert carrier.ring_spin == 0.0
    assert ring.carrier_spin == pytest.approx(0.0)


@pytest.mark.parametrize("ratio", RATIOS)
def test_the_disc_runs_against_the_crank_so_their_rates_add(ratio):
    """``1 + 1/N`` per crank radian, and the app read ``1 - 1/N`` for a long time.

    The disc turns the opposite way from the crank, so the bearing between them
    sees the sum.  With the sign the other way the cam bearing - the fastest in
    the drive - was understated by 14% at fifteen lobes, and understated worst
    exactly where the ratio is low and the speed is highest.
    """
    for member in OutputMember:
        spec = _spec(ratio, member)
        per_crank = abs(spec.disc_spin - spec.shaft_spin)
        assert per_crank == pytest.approx(1.0 + 1.0 / ratio)
        assert spec.crank_relative_rate == pytest.approx(per_crank * spec.crank_rate)

    # And in each configuration it lands on a number worth recognising.
    assert _spec(ratio, OutputMember.CARRIER).crank_relative_rate == pytest.approx(
        1.0 + 1.0 / ratio)
    # With the carrier grounded the disc does not rotate at all, so the cam
    # bearing simply turns at the input speed.
    assert _spec(ratio, OutputMember.RING).crank_relative_rate == pytest.approx(1.0)


@pytest.mark.parametrize("ratio", RATIOS)
def test_the_carrier_rotation_is_the_one_the_pins_can_actually_follow(ratio):
    """Solved from the coupling rather than assumed.

    The output pins sit in holes on the same bolt circle, and the disc
    translates on a circle of radius E relative to the carrier - so at every
    crank angle each pin must be exactly E from its hole centre.  Only one
    carrier rotation satisfies that, and it is the disc's own.  This is the
    constraint that caught the sign: with the rate turned round the pins walk
    out of their holes within a few degrees.
    """
    spec = _spec(ratio, OutputMember.CARRIER)
    n, bc, E = spec.output_pin_count, spec.output_bolt_circle_radius, spec.eccentricity
    gamma = 2.0 * np.pi * np.arange(n) / n
    for phi in (0.0, 0.37, 1.9, 4.4):
        holes = kin.to_world(bc * np.column_stack([np.cos(gamma), np.sin(gamma)]),
                             phi, E, ratio)
        psi = phi / ratio                      # the carrier's rotation
        pins = bc * np.column_stack([np.cos(gamma + psi), np.sin(gamma + psi)])
        assert np.allclose(np.linalg.norm(holes - pins, axis=1), E, atol=1e-9)


@pytest.mark.parametrize("ratio", RATIOS)
def test_the_two_stage_periods_agree_once_the_sign_is_right(ratio):
    """The ring pattern repeats over a turn; the output pattern repeats ``n``
    times in it.

    The two were derived independently - one from the profile parameter at each
    pin, the other from the eccentricity direction seen from the carrier - and
    they only meet on the correct rate.  They did not, and the output stage was
    being swept over a window 14% too wide that was not a period of anything.
    """
    for pins in (4, 6, 9, 12):
        assert (kin.ring_stage_period(ratio) / pins
                == pytest.approx(kin.output_stage_period(ratio, pins)))


@pytest.mark.parametrize("ratio", [15, 29])
def test_the_output_load_pattern_really_does_repeat_over_that_period(ratio):
    """The period claimed, measured on the thing it is a period of.

    The set of loaded pins comes back rotated by one pin pitch rather than
    identical, so it is the force *spectrum* that has to match - which is
    exactly what every statistic taken over the sweep depends on.
    """
    spec = preset(ratio)
    period = kin.output_stage_period(ratio, spec.output_pin_count)
    for phi in (0.0, 0.29, 1.13):
        here = np.sort(kin.output_loads(spec, phi, 1000.0).forces)
        later = np.sort(kin.output_loads(spec, phi + period, 1000.0).forces)
        assert np.allclose(here, later, atol=1e-9)


def test_a_ring_output_drive_reflects_less_inertia_back_to_the_motor():
    """The disc does not rotate in the ground frame when the carrier is held, so
    only its orbiting mass is reflected - a consequence of the rate model that
    is worth pinning down because nothing else in the app would notice it."""
    carrier, ring = _spec(21, OutputMember.CARRIER), _spec(21, OutputMember.RING)
    assert carrier.disc_speed_ratio == pytest.approx(1.0 / 21)
    assert ring.disc_speed_ratio == pytest.approx(0.0)
    assert (analyse(ring).mass.reflected_inertia_kg_mm2
            < analyse(carrier).mass.reflected_inertia_kg_mm2)


# ------------------------------------------------------------------ the bearings


def test_the_cam_bearing_speed_follows_the_member_that_is_grounded():
    """The one number the sign error moved most, checked against the model that
    replaced it rather than against a constant."""
    for member in OutputMember:
        spec = _spec(21, member, input_rpm=1200.0)
        cam = next(c for c in analyse(spec).bearings
                   if c.role == "Eccentric cam bearing")
        assert cam.speed_rpm == pytest.approx(
            spec.input_rpm * spec.crank_relative_rate)
    # It is above the input speed off the carrier and exactly it off the ring.
    assert _spec(21, OutputMember.CARRIER).crank_relative_rate > 1.0


def test_the_main_output_bearing_turns_at_the_output_speed_either_way():
    """It separates the carrier from the ring, and that difference *is* the
    output speed however the drive is mounted - which is why the one seat whose
    geometry does not move between the two configurations is this one."""
    for member in OutputMember:
        spec = _spec(21, member)
        rate = abs(spec.carrier_spin - spec.ring_spin) * spec.crank_rate
        assert rate == pytest.approx(1.0 / spec.ratio)
        main = next(c for c in analyse(spec).bearings
                    if c.role == "Main output bearing")
        assert main.speed_rpm == pytest.approx(spec.output_rpm)


# ------------------------------------------------------------------ the geometry


def test_the_motor_bolts_to_the_member_that_stands_still():
    """A motor on a plate that turns is a gearbox nobody can build.

    So the pattern moves off the input end plate and onto the carrier's base
    when the housing becomes the output - and the plate it left has to come out
    heavier than it was, because the holes are no longer in it.
    """
    from cycloidgen.export import solid

    carrier = _spec(21, OutputMember.CARRIER, motor_frame="NEMA 17")
    ring = _spec(21, OutputMember.RING, motor_frame="NEMA 17")
    assert carrier.motor_mounts_on_carrier is False
    assert ring.motor_mounts_on_carrier is True

    plain = solid.housing_end_plate(carrier, carrier.hub_bore).val().Volume()
    with_motor = solid.housing_end_plate(
        carrier, carrier.hub_bore, motor_face=True).val().Volume()
    assert with_motor < plain                       # four holes taken out of it

    # And on the ring-output drive the motor's holes are in the carrier instead.
    flange = solid.output_flange(ring).val()
    box = flange.BoundingBox()
    assert box.zmin == pytest.approx(ring.base_plate_bottom)
    half = ring.motor.bolt_span / 2.0
    reach = math.hypot(half, half) + ring.motor.bolt_diameter / 2.0
    assert box.xlen / 2.0 == pytest.approx(ring.housing_outer_radius, rel=1e-3)
    assert reach < ring.housing_outer_radius        # the pattern lands on it


def test_the_base_is_only_there_when_the_carrier_is_the_ground():
    """Off the carrier the boss is a shaft end and a coupling grips it; a plate
    across the end of it would be a plate across the output."""
    from cycloidgen.export import solid

    carrier, ring = _spec(21, OutputMember.CARRIER), _spec(21, OutputMember.RING)
    assert not carrier.mount_base_fitted and ring.mount_base_fitted
    assert (solid.output_flange(ring).val().Volume()
            > solid.output_flange(carrier).val().Volume())
    # The envelope grows by the base and the standoff it needs, and says so.
    assert (ring.envelope_length - carrier.envelope_length
            == pytest.approx(ring.plate_thickness + ring.output_boss_protrusion))


def test_the_mass_model_weighs_the_base_it_exported():
    """A made part the mass model has not been told about is a gearbox that
    weighs less on paper than in your hand.

    Compared as the *difference* between the two configurations rather than as
    an absolute, because the carrier's solid also carries the output pins and
    those are weighed as bought dowels rather than as part of it.  The
    difference is the base and nothing else, which is exactly the thing being
    checked.
    """
    from cycloidgen.export import solid

    carrier, ring = _spec(21, OutputMember.CARRIER), _spec(21, OutputMember.RING)
    rho = ring.housing_mat.density_g_cm3
    drawn = (solid.output_flange(ring).val().Volume()
             - solid.output_flange(carrier).val().Volume())
    weighed = (analyse(ring).mass.flange_mass_g
               - analyse(carrier).mass.flange_mass_g) / rho * 1000.0
    assert drawn > 0
    assert weighed == pytest.approx(drawn, rel=0.02)


def test_the_turning_housing_gets_a_face_to_bolt_a_load_to():
    """A barrel has nowhere to grip.  Off the ring the interface is the input
    end plate, on the tie bolts' own circle because that is the one radius with
    wall behind it - so the two patterns share a circle and interleave."""
    from cycloidgen.export import solid

    ring = _spec(21, OutputMember.RING)
    assert ring.output_face_bolt_radius == ring.housing_bolt_radius
    assert ring.output_bolt_phase == pytest.approx(math.pi / ring.housing_bolt_count)

    plate = solid.housing_end_plate(ring, ring.hub_bore, motor_face=True)
    bare = solid.housing_end_plate(ring, ring.hub_bore)
    assert plate.val().Volume() < bare.val().Volume()

    none = _spec(21, OutputMember.RING, output_bolt_count=0)
    assert (solid.housing_end_plate(none, none.hub_bore, motor_face=True)
            .val().Volume()
            == pytest.approx(solid.housing_end_plate(none, none.hub_bore)
                             .val().Volume()))


@pytest.mark.parametrize("counts,severity", [
    # Equal counts interleave exactly, which is why they are the default pair.
    ((6, 6), None), ((8, 8), None),
    # A multiple lands every other output hole on a tie bolt.
    ((6, 12), "error"),
    # Coprime counts drift: seven against six brings one pair to 0.12 mm of
    # metal - not an overlap, but not something to drill either.
    ((6, 7), "warning"),
    # Nothing to collide with at either end.
    ((0, 6), None), ((6, 0), None),
])
def test_the_two_bolt_circles_are_checked_against_each_other(counts, severity):
    """They share a radius, so whether they fit is a question about the counts -
    and the counts are two fields set independently."""
    ties, outs = counts
    spec = _spec(21, OutputMember.RING, housing_bolt_count=ties,
                 output_bolt_count=outs)
    found = [f for f in analyse(spec).report.findings
             if f.code == "OUTPUT_BOLT_CLASH"]
    if severity is None:
        assert not found, found
    else:
        assert [f for f in found if f.severity.value == severity], found


def test_the_check_does_not_fire_on_a_carrier_output_drive():
    """There is no output bolt circle there at all - the interface is the boss."""
    spec = _spec(21, OutputMember.CARRIER, output_bolt_count=12)
    assert not [f for f in analyse(spec).report.findings
                if f.code == "OUTPUT_BOLT_CLASH"]


# -------------------------------------------------------------- what turns


@pytest.mark.parametrize("ratio", [15, 21])
def test_the_grounded_part_does_not_move_and_the_output_part_does(ratio):
    """The 3D view has to draw the mechanism the analysis describes.

    Measured on the vertices rather than on the declared spin, because the
    frame rotation is applied at placement time and a part could carry the
    right number and still be drawn in the wrong frame.
    """
    from cycloidgen.viz.mesh import build_mesh

    for member in OutputMember:
        spec = _spec(ratio, member)
        mesh = build_mesh(spec)
        at_zero = mesh.world_vertices(0.0)
        turned = mesh.world_vertices(1.1)
        moved = {}
        for part in mesh.parts:
            delta = np.abs(turned[part.vertices] - at_zero[part.vertices]).max()
            moved[part.name] = float(delta)
        assert moved[spec.grounded_part] < 1e-9, (member, moved)
        assert moved[spec.output_part] > 1e-6, (member, moved)


@pytest.mark.parametrize("ratio", [15, 21])
def test_the_output_part_turns_by_exactly_one_over_the_ratio(ratio):
    """Not merely "it moves": the angle it moves by is the reduction, and the
    reduction is what the whole choice is about."""
    from cycloidgen.viz.mesh import build_mesh

    for member in OutputMember:
        spec = _spec(ratio, member)
        mesh = build_mesh(spec)
        part = next(p for p in mesh.parts if p.name == spec.output_part)
        # A point well off the axis, so the angle is readable.
        base = mesh.world_vertices(0.0)[part.vertices]
        j = int(np.argmax(np.hypot(base[:, 0], base[:, 1])))
        phi = 0.9
        after = mesh.world_vertices(phi)[part.vertices][j]
        turn = math.atan2(after[1], after[0]) - math.atan2(base[j][1], base[j][0])
        turn = (turn + math.pi) % (2.0 * math.pi) - math.pi
        expected = abs(spec.shaft_spin) * phi / spec.ratio
        assert abs(turn) == pytest.approx(expected, rel=1e-6)


@pytest.mark.parametrize("ratio", [15, 21])
def test_both_renderers_place_a_ring_output_part_the_same_way(ratio):
    """The software view transforms vertices; the hardware view hands VTK a
    rotation and a translation.

    They already agreed on the per-part motion, and the frame rotation is a
    second place the same law now has to be written down - so it is a second
    place it can be left out.  Leaving it out of the pose is exactly the bug
    that would draw the housing turning in one view and standing still in the
    other, from one mesh, with nothing failing.
    """
    from cycloidgen.viz.mesh import build_mesh
    from cycloidgen.viz.vtkbridge import pose_matrix

    mesh = build_mesh(_spec(ratio, OutputMember.RING))
    assert mesh.frame_spin != 0.0
    phi = 1.3
    world = mesh.world_vertices(phi, explode=0.4)
    for part in mesh.parts:
        angle, dx, dy, dz = pose_matrix(mesh, part, phi, explode=0.4)
        c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        local = mesh.vertices[part.vertices]
        placed = local[:, :2] @ np.array([[c, -s], [s, c]]).T + [dx, dy]
        assert np.allclose(placed, world[part.vertices, :2], atol=1e-9), part.name
        assert np.allclose(local[:, 2] + dz, world[part.vertices, 2], atol=1e-9)


def test_the_mesh_cache_can_tell_the_two_configurations_apart():
    """They differ in the base, the motor face, the bolt pattern and the frame
    the whole thing is drawn in - a shared fingerprint would serve one for the
    other."""
    from cycloidgen.viz.mesh import mesh_fingerprint, mesh_for_spec

    carrier, ring = _spec(21, OutputMember.CARRIER), _spec(21, OutputMember.RING)
    assert mesh_fingerprint(carrier) != mesh_fingerprint(ring)
    assert mesh_for_spec(carrier) is not mesh_for_spec(ring)


@pytest.mark.parametrize("ratio", RATIOS)
def test_every_part_of_a_ring_output_drive_is_still_watertight(ratio):
    """The base is a new prism stacked on the boss and pierced by the motor's
    bolts, and every one of those is a chance to leave a face open.  The section
    plane can only cap a closed surface, so this is the test that says the new
    geometry is geometry and not a heap of panels."""
    from vtkmodules.vtkFiltersCore import vtkFeatureEdges, vtkTriangleFilter

    from cycloidgen.viz.mesh import build_mesh
    from cycloidgen.viz.vtkbridge import closed_polydata

    spec = _spec(ratio, OutputMember.RING, motor_frame="NEMA 23")
    mesh = build_mesh(spec)
    faults = []
    for part in mesh.parts:
        triangles = vtkTriangleFilter()
        triangles.SetInputData(closed_polydata(mesh, part))
        triangles.Update()
        for boundary, nonmanifold, label in ((True, False, "holes"),
                                             (False, True, "non-manifold")):
            edges = vtkFeatureEdges()
            edges.SetInputConnection(triangles.GetOutputPort())
            edges.SetBoundaryEdges(boundary)
            edges.SetNonManifoldEdges(nonmanifold)
            edges.FeatureEdgesOff()
            edges.ManifoldEdgesOff()
            edges.Update()
            count = edges.GetOutput().GetNumberOfCells()
            if count:
                faults.append(f"{part.name}: {count} {label}")
    assert not faults, "; ".join(faults)


def test_a_saved_ring_output_design_comes_back_as_one():
    """The choice has to survive the round trip, or a saved design reopens as a
    different gearbox with a different ratio."""
    from cycloidgen.core.designfile import design_dict, spec_from_dict

    spec = _spec(29, OutputMember.RING, output_bolt_count=8, housing_bolt_count=8)
    back = spec_from_dict(design_dict(spec))
    assert back.output_member is OutputMember.RING
    assert back.ratio == spec.ratio == 30
    assert back.output_bolt_count == 8
