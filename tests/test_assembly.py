"""Does the assembly actually fit together?

The 2D meshing tests prove the disc rolls on the ring.  These prove the *rest*
of the machine agrees with it - which is a separate claim, and one that was
wrong the first time: every disc past the first had its output holes at the
wrong angle, so the carrier pins could not enter them.

The headline check is the one you can see by eye in the drawing: an output pin
must stay inside its hole at every crank angle.
"""
from __future__ import annotations

import numpy as np
import pytest

from cycloidgen.analysis import analyse
from cycloidgen.core.spec import GearSpec, preset
from cycloidgen.core.validate import Severity

RATIOS = [10, 15, 21, 29, 59]
STACKS = [1, 2, 3]


def _pin_and_hole_centres(spec: GearSpec, phi: float, disc: int):
    """Carrier pin centres and disc hole centres in the housing frame."""
    n = spec.output_pin_count
    base = 2.0 * np.pi * np.arange(n) / n
    # the carrier rotates with the discs
    pins = spec.output_bolt_circle_radius * np.column_stack(
        [np.cos(base + phi / spec.lobes), np.sin(base + phi / spec.lobes)])

    phase = spec.disc_phases[disc]
    hole_phase = spec.disc_hole_phases[disc]
    centre = np.array([spec.eccentricity * np.cos(phi + phase),
                       -spec.eccentricity * np.sin(phi + phase)])
    d = (phi + phase) / spec.lobes
    ang = base + d + hole_phase
    holes = centre + spec.output_bolt_circle_radius * np.column_stack(
        [np.cos(ang), np.sin(ang)])
    return pins, holes


@pytest.mark.parametrize("ratio", RATIOS)
@pytest.mark.parametrize("discs", STACKS)
def test_output_pin_never_leaves_its_hole(ratio, discs):
    """The visible one: green circle stays inside blue circle, always.

    The pin centre orbits the hole centre at radius exactly E, and the hole is
    the pin plus 2E across, so the pin is permanently inside - by zero margin in
    theory and by the hole clearance in practice.
    """
    spec = preset(ratio)
    spec.disc_count = discs
    slack = spec.output_hole_diameter / 2 - spec.output_pin_diameter / 2
    for disc in range(discs):
        for phi in np.linspace(0, 2 * np.pi, 72, endpoint=False):
            pins, holes = _pin_and_hole_centres(spec, float(phi), disc)
            offset = np.hypot(*(pins - holes).T)
            assert offset.max() <= slack + 1e-9, (
                f"disc {disc + 1} at {np.degrees(phi):.0f} deg: pin centre "
                f"{offset.max():.4f} mm from the hole centre, only {slack:.4f} mm "
                f"of room - the pin is outside its hole")


@pytest.mark.parametrize("ratio", RATIOS)
@pytest.mark.parametrize("discs", [2, 3])
def test_pin_orbit_radius_is_exactly_the_eccentricity(ratio, discs):
    """Ignoring clearance, the offset traces a circle of radius E, not less."""
    spec = preset(ratio)
    spec.disc_count = discs
    spec.hole_clearance = 0.0
    for disc in range(discs):
        offsets = []
        for phi in np.linspace(0, 2 * np.pi, 180, endpoint=False):
            pins, holes = _pin_and_hole_centres(spec, float(phi), disc)
            offsets.append(np.hypot(*(pins - holes).T))
        offsets = np.array(offsets)
        assert np.allclose(offsets, spec.eccentricity, atol=1e-9)


@pytest.mark.parametrize("ratio", RATIOS)
def test_disc_clears_the_housing_bore(ratio):
    """Disc reach is (R - Rr + E) from its own centre, which is E off axis."""
    spec = preset(ratio)
    reach = spec.pin_circle_radius - spec.effective_Rr + 2 * spec.eccentricity
    assert reach < spec.pin_circle_radius, (
        f"disc reaches {reach:.3f} mm, housing bore is "
        f"{spec.pin_circle_radius:.3f} mm - needs 2E <= Rr")


def test_discs_are_identical_only_when_pins_allow_it():
    spec = preset(15)
    spec.disc_count = 2
    assert not spec.discs_are_identical
    spec.output_pin_count = 2 * spec.lobes if 2 * spec.lobes <= 24 else 24
    if spec.output_pin_count == 2 * spec.lobes:
        assert spec.discs_are_identical

    single = preset(15)
    single.disc_count = 1
    assert single.discs_are_identical


def test_stl_export_emits_one_file_per_distinct_disc(tmp_path):
    from cycloidgen.export import solid
    spec = preset(15)
    spec.disc_count = 2
    names = {p.stem for p in solid.write_stls(spec, tmp_path)}
    assert {"disc_1", "disc_2"} <= names
    assert "disc" not in names


def test_stl_export_emits_one_disc_when_they_are_identical(tmp_path):
    from cycloidgen.export import solid
    spec = preset(15)
    spec.disc_count = 1
    names = {p.stem for p in solid.write_stls(spec, tmp_path)}
    assert "disc" in names


def test_assembly_reports_that_the_discs_differ():
    from cycloidgen.core.validate import validate
    spec = preset(15)
    spec.disc_count = 2
    assert "DISCS_DIFFER" in {f.code for f in validate(spec).findings}


# ------------------------------------------------------- what holds it together


@pytest.mark.parametrize("ratio", [15, 21, 33])
def test_the_tie_bolts_pass_through_the_thing_they_clamp(ratio):
    """The bill of materials orders six of them and both end plates are
    drilled for them.  The barrel they clamp was not, so the exported gearbox
    was a stack of parts whose bolts landed on solid wall - which nothing in
    the app noticed, because nothing was looking at the barrel.
    """
    import math

    from cycloidgen.export.solid import ring_housing

    spec = preset(ratio)
    assert spec.housing_bolt_count, "this preset has no tie bolts to check"

    drilled = ring_housing(spec).val().Volume()
    plain = ring_housing(
        spec.model_copy(update={"housing_bolt_count": 0})).val().Volume()

    hole = (math.pi * (spec.housing_bolt_diameter / 2.0) ** 2
            * spec.barrel_height * spec.housing_bolt_count)
    assert plain - drilled == pytest.approx(hole, rel=0.02)


@pytest.mark.parametrize("ratio", [10, 15, 21, 29, 39, 59])
def test_no_preset_puts_its_bolts_where_there_is_no_wall(ratio):
    spec = preset(ratio)
    codes = [f.code for f in analyse(spec).report.findings]
    assert "HOUSING_BOLT_CLASH" not in codes


def test_a_bolt_that_breaks_into_the_pockets_is_an_error():
    """Inward: the bolt reaches the bore the discs run against."""
    spec = preset(21).model_copy(update={"housing_bolt_diameter": 9.0})
    finding = next(f for f in analyse(spec).report.findings
                   if f.code == "HOUSING_BOLT_CLASH")
    assert finding.severity is Severity.ERROR
    assert "pockets" in finding.message


def test_a_bolt_too_big_for_its_wall_is_an_error():
    """It breaks into the pockets and out through the rim at the same moment,
    because the circle is derived as the middle of the wall - which is why this
    is one question rather than an inner test and an outer one."""
    spec = preset(21)
    fat = spec.model_copy(update={"housing_bolt_diameter": spec.housing_wall})
    finding = next(f for f in analyse(fat).report.findings
                   if f.code == "HOUSING_BOLT_CLASH")
    assert finding.severity is Severity.ERROR


@pytest.mark.parametrize("ratio", [15, 21, 33])
def test_the_bolt_length_is_the_distance_it_has_to_span(ratio):
    """It used to be quoted off the disc stack.  When the barrel was lengthened
    to reach the plates it bolts to, the bill of materials did not follow - so
    the drive was ordering bolts seven millimetres short of the thing they pass
    through, and nothing compared the two.
    """
    from cycloidgen.export.bom import bom_items
    from cycloidgen.viz.mesh import mesh_for_spec

    spec = preset(ratio)
    mesh = mesh_for_spec(spec)

    faces = []
    for part in mesh.parts:
        if part.group == "end_plates":
            z = mesh.vertices[part.vertices][:, 2]
            faces += [float(z.min()), float(z.max())]
    assert max(faces) - min(faces) == pytest.approx(spec.tie_bolt_length)

    stated = next(i for i in bom_items(analyse(spec)) if i.part == "Tie bolt")
    assert f"{spec.tie_bolt_length:.0f} mm under the head" in stated.size


@pytest.mark.parametrize("ratio", [15, 21, 33])
def test_the_bolts_are_drawn_where_the_holes_are(ratio):
    """Bought, so they are in the picture and the STEP assembly and not in the
    per-part export - the same treatment the bearings get."""
    from cycloidgen.export.solid import build_assembly, parts, tie_bolts

    spec = preset(ratio)
    assert "tie_bolts" not in parts(spec)
    assert "tie_bolts" in {c.name for c in build_assembly(spec).children}

    bounds = tie_bolts(spec).val().BoundingBox()
    assert bounds.zmin == pytest.approx(spec.tie_bolt_bottom)
    assert bounds.zlen == pytest.approx(spec.tie_bolt_length)
    # inside the clearance holes they run in, not filling them
    assert bounds.xmax < spec.housing_bolt_radius + spec.housing_bolt_diameter / 2.0
