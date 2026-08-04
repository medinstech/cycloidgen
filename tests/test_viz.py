"""The 3D mesh and the renderer that draws it.

Two things are worth testing here and they are not the obvious ones.  A picture
cannot be asserted, but the *geometry behind it* can: every part is a closed,
correctly-oriented surface, it encloses the same volume as the solid that gets
exported, and it moves by the motion law the rest of the application was
verified against.  Get any of those wrong and the viewer shows a plausible
gearbox that is not the one being exported.
"""
from __future__ import annotations

import numpy as np
import pytest

from cycloidgen.core import kinematics as kin
from cycloidgen.core.spec import preset
from cycloidgen.export import solid
from cycloidgen.viz import build_mesh
from cycloidgen.viz.mesh import PART_COLOURS, mesh_for_spec, pocketed_bore
from cycloidgen.viz.scene import Camera, render


@pytest.fixture(scope="module")
def spec():
    s = preset(15)
    s.disc_count = 2
    return s


@pytest.fixture(scope="module")
def mesh(spec):
    return build_mesh(spec)


def _face_areas(mesh) -> np.ndarray:
    """Vector area of every face: magnitude is the area, direction the normal.

    Summing the loops of one face is what makes a face with holes come out
    right - the holes are wound against their boundary, so their contribution
    subtracts.
    """
    out = np.zeros((mesh.facet_count, 3))
    for i, loops in enumerate(mesh.loops):
        for loop in loops:
            p = mesh.vertices[loop]
            out[i] += 0.5 * np.cross(p, np.roll(p, -1, axis=0)).sum(axis=0)
    return out


def _part_volumes(mesh) -> np.ndarray:
    """Divergence theorem on planar faces: ``V = 1/3 * sum(p0 . vectorArea)``.

    Indexed by part rather than by name.  The mesh is an *assembly*, so a
    two-disc stack holds two disc bodies; the exporter deals in *distinct
    parts*, and when the two discs happen to be identical it writes one file for
    both.  Summing by name would silently compare one solid against two.
    """
    areas = _face_areas(mesh)
    volumes = np.zeros(len(mesh.parts))
    for i, loops in enumerate(mesh.loops):
        p0 = mesh.vertices[loops[0][0]]
        volumes[mesh.facet_part[i]] += float(p0 @ areas[i]) / 3.0
    return volumes


# ------------------------------------------------------------------- geometry


def test_every_part_is_a_closed_surface(mesh):
    """The vector areas of a closed, consistently wound surface cancel exactly.

    This is the single strongest statement available about a mesh without
    rendering it: it catches a missing end cap, a side wall built for the wrong
    number of edges, and a loop wound the wrong way round - each of which
    produces a picture that looks nearly right from one angle and wrong from
    the other.
    """
    areas = _face_areas(mesh)
    for part in mesh.parts:
        residual = np.linalg.norm(areas[part.facets].sum(axis=0))
        scale = np.abs(areas[part.facets]).sum()
        assert residual / scale < 1e-9, f"{part.name} is not closed"


@pytest.mark.parametrize("ratio,discs", [(15, 2), (10, 1), (29, 3)])
def test_mesh_volume_matches_the_exported_solid(ratio, discs):
    """The viewer and the STEP file must be the same gearbox.

    Tolerance is faceting, not modelling: every circle in the mesh is an
    inscribed polygon, so a twelve-sided ring pin encloses about 1% less than
    the cylinder it stands for.  Anything past a few percent is a part built
    differently in the two places.
    """
    s = preset(ratio)
    s.disc_count = discs
    mesh = build_mesh(s)
    volumes = _part_volumes(mesh)
    solids = solid.parts(s)
    for i, part in enumerate(mesh.parts):
        name = part.name
        if part.group == "discs" and s.discs_are_identical:
            name = "disc"
        expected = solids[name].val().Volume()
        assert volumes[i] == pytest.approx(expected, rel=0.03), part.name
    assert len(mesh.parts) == 4 + discs


def test_the_ring_pockets_keep_the_pins_out_of_the_housing(spec):
    """Half-embedded pins in a plain circular bore would share space with it.

    With no depth buffer, two surfaces in the same place are arbitrated by
    comparing face centroids, and the answer flips as the model turns.  The
    bore is cut around the pins instead: no point of it may lie inside a pin.
    """
    loop = pocketed_bore(spec.pin_circle_radius, spec.pin_radius, spec.pin_count)
    angles = 2.0 * np.pi * np.arange(spec.pin_count) / spec.pin_count
    centres = spec.pin_circle_radius * np.column_stack([np.cos(angles), np.sin(angles)])
    gap = np.linalg.norm(loop[:, None, :] - centres[None, :, :], axis=2).min(axis=1)
    assert gap.min() >= spec.pin_radius - 1e-9


def test_overlapping_pockets_fall_back_to_a_clear_bore():
    """A design already flagged by PIN_OVERLAP must not produce a crossed loop."""
    loop = pocketed_bore(20.0, 9.0, 24)
    radii = np.hypot(loop[:, 0], loop[:, 1])
    assert np.allclose(radii, radii[0])          # a plain circle, not a tangle


# --------------------------------------------------------------------- motion


def test_the_discs_move_by_the_verified_motion_law(spec, mesh):
    """The 3D view has to use the same pose law the meshing sweep verified.

    ``core.kinematics`` is the module that was checked against a full-revolution
    meshing simulation.  If the viewer computes its own version of "where is the
    disc", nothing keeps the two in step.
    """
    phi = 0.9
    world = mesh.world_vertices(phi)
    for i, part in enumerate(p for p in mesh.parts if p.group == "discs"):
        local = mesh.vertices[part.vertices]
        expected = kin.to_world(local[:, :2], phi + spec.disc_phases[i],
                                spec.eccentricity, spec.lobes)
        assert np.allclose(world[part.vertices, :2], expected, atol=1e-9)


def test_the_carrier_turns_at_the_output_speed(spec, mesh):
    """One input revolution must move the carrier by exactly one lobe pitch."""
    carrier = next(p for p in mesh.parts if p.group == "carrier")
    local = mesh.vertices[carrier.vertices][:, :2]
    turned = mesh.world_vertices(2.0 * np.pi)[carrier.vertices][:, :2]
    angle = 2.0 * np.pi / spec.lobes
    c, s = np.cos(angle), np.sin(angle)
    assert np.allclose(turned, local @ np.array([[c, -s], [s, c]]).T, atol=1e-9)


def test_exploding_moves_the_parts_apart_and_nothing_else(mesh):
    lo, hi = mesh.bounds(0.0)
    lo_x, hi_x = mesh.bounds(1.0)
    assert hi_x[2] - lo_x[2] > 2.0 * (hi[2] - lo[2])     # along the axis
    assert hi_x[0] - lo_x[0] == pytest.approx(hi[0] - lo[0])    # and only there


# ------------------------------------------------------------------ rendering


def test_the_frame_holds_the_whole_drive_at_every_crank_angle(mesh):
    """A view that has to be re-fitted as the eccentric comes round is not a fit."""
    camera = Camera.framing(mesh)
    for crank in np.linspace(0.0, 2.0 * np.pi, 8, endpoint=False):
        draw = render(mesh, float(crank), camera, 800, 800)
        points = np.vstack([loops[0] for loops in draw.loops])
        assert points.min() >= 0.0
        assert points.max() <= 800.0


def test_only_front_faces_survive(mesh):
    """Back-face culling is what makes a painter's-algorithm renderer correct.

    Every drawn polygon must wind the same way on screen; a back face that
    slipped through would wind the other way and paint over the front of the
    part it belongs to.
    """
    draw = render(mesh, 0.3, Camera.framing(mesh), 640, 480)
    assert len(draw) > 200
    for loop in (loops[0] for loops in draw.loops):
        x, y = loop[:, 0], loop[:, 1]
        area = float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
        assert area <= 1e-9        # screen y points down, so front faces are CW


def test_faces_are_painted_back_to_front(mesh):
    """Without a depth buffer the paint order *is* the depth test."""
    draw = render(mesh, 0.0, Camera.framing(mesh), 640, 480)
    assert np.all(draw.depths > 0.0)                  # nothing behind the camera
    assert np.all(np.diff(draw.depths) <= 1e-9)       # farthest first


def test_hiding_a_group_removes_exactly_that_group(mesh):
    camera = Camera.framing(mesh)
    everything = render(mesh, 0.2, camera, 640, 480)
    without = render(mesh, 0.2, camera, 640, 480, hidden={"housing"})
    housing = next(i for i, p in enumerate(mesh.parts) if p.group == "housing")
    assert (everything.parts == housing).sum() > 0
    assert (without.parts == housing).sum() == 0
    assert len(without) == len(everything) - (everything.parts == housing).sum()


def test_the_viewer_and_the_step_file_agree_on_part_colours():
    """One palette, so a part is the same colour in the window and in the file."""
    import cadquery as cq
    for group, (r, g, b) in PART_COLOURS.items():
        colour = solid._colour(group)
        assert isinstance(colour, cq.Color)
        assert colour.toTuple()[:3] == pytest.approx(
            (r / 255.0, g / 255.0, b / 255.0), abs=1e-6)


def test_the_mesh_cache_is_keyed_on_the_design_not_the_object():
    """``GearSpec`` is mutable, so identity says nothing about the geometry."""
    s = preset(15)
    first = mesh_for_spec(s)
    assert mesh_for_spec(s) is first
    s.pin_radius += 0.5
    assert mesh_for_spec(s) is not first
