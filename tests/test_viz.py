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


#: Groups whose parts are bought rather than made: they are in the picture and
#: in the STEP assembly, and they get no file of their own in the per-part
#: export - an STL of a bearing or a cap screw is a thing to order, not to make.
BOUGHT_GROUPS = ("bearings", "fasteners")

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
    # `parts` is the made ones; the bearings and the tie bolts are bought, so
    # they get no STL of their own - but they are in the picture and in the
    # STEP assembly, so they are held to the same agreement as everything else.
    solids = {**solid.parts(s), **solid.bearing_solids(s),
              "tie_bolts": solid.tie_bolts(s)}
    for i, part in enumerate(mesh.parts):
        name = part.name
        if part.group == "discs" and s.discs_are_identical:
            name = "disc"
        expected = solids[name].val().Volume()
        assert volumes[i] == pytest.approx(expected, rel=0.03), part.name
    # ...and nothing is in one and not the other.  Stated against the export's
    # own part list rather than a count, which was a magic number that had to be
    # edited every time the gearbox grew a part - and would have been just as
    # happy with a part missing as with one added.
    # The bought groups are in the picture and in the STEP assembly but not in
    # the per-part export, so they are the ones this comparison leaves out.
    drawn = {p.name for p in mesh.parts if p.group not in BOUGHT_GROUPS}
    exported = set(solid.parts(s))
    if s.discs_are_identical:
        # One file for a stack of identical discs, but still a body each - and a
        # single disc is trivially identical to itself, so it takes this path too.
        exported = (exported - {"disc"}) | {f"disc_{i + 1}" for i in range(discs)}
    assert drawn == exported
    assert any(p.group == "bearings" for p in mesh.parts), \
        "the drive is drawn without any of its bearings"


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


def test_faces_of_one_part_are_painted_back_to_front(mesh):
    """Without a depth buffer the paint order *is* the depth test.

    Within a part, and only within it. A single global depth sort is what this
    used to assert and it is what put the ring pins on top of the end plate:
    one centroid cannot order a face that spans the whole depth of the drive
    against the small parts underneath it.
    """
    draw = render(mesh, 0.0, Camera.framing(mesh), 640, 480)
    assert np.all(draw.depths > 0.0)                  # nothing behind the camera
    for part in np.unique(draw.parts):
        depths = draw.depths[draw.parts == part]
        assert np.all(np.diff(depths) <= 1e-9), mesh.parts[part].name


def test_a_part_is_painted_in_one_go(mesh):
    """The two-level order only means anything if a part is contiguous: a part
    interleaved with another has no position in the part order at all."""
    draw = render(mesh, 0.0, Camera.framing(mesh), 640, 480)
    starts = np.flatnonzero(np.diff(draw.parts, prepend=-1))
    assert len(starts) == len(np.unique(draw.parts))


def _z_span(mesh, name):
    part = next(p for p in mesh.parts if p.name == name)
    z = mesh.vertices[part.vertices][:, 2]
    return float(z.min()), float(z.max())


@pytest.mark.parametrize("ratio", [15, 21, 29])
def test_the_barrel_reaches_both_end_plates(ratio):
    """A housing sized to the disc stack leaves a slot round the gearbox.

    The output carrier hangs below the discs - a drop, then its own thickness -
    and the output end plate bolts on underneath that. The barrel used to stop
    at the discs, so between it and the plate it is bolted to there was nothing
    at all: the carrier standing in the open with daylight round it.

    Checked against the *plates* rather than against a number, because the point
    is that the three parts meet. The envelope length was already counting the
    carrier's share while the barrel did not fill it, which is exactly the kind
    of disagreement two separate sums produce.
    """
    mesh = mesh_for_spec(preset(ratio))
    barrel = _z_span(mesh, "housing")
    below = _z_span(mesh, "output_end_plate")
    above = _z_span(mesh, "input_end_plate")

    assert barrel[0] == pytest.approx(below[1]), "gap under the barrel"
    assert barrel[1] == pytest.approx(above[0]), "gap over the barrel"
    # and it is genuinely longer than the discs it holds
    assert barrel[1] - barrel[0] > _z_span(mesh, "disc_1")[1] + 1e-9


@pytest.mark.parametrize("ratio", [15, 21, 29])
def test_the_envelope_is_the_length_the_geometry_occupies(ratio):
    """The number on the header bar against the parts it claims to measure."""
    spec = preset(ratio)
    mesh = mesh_for_spec(spec)
    z = mesh.vertices[:, 2]
    plates = [_z_span(mesh, n) for n in ("input_end_plate", "output_end_plate")]
    assert max(p[1] for p in plates) - min(p[0] for p in plates) == pytest.approx(
        spec.envelope_length)
    # nothing but the shaft is allowed to stand outside the plates
    outside = (z < min(p[0] for p in plates) - 1e-6) | (
        z > max(p[1] for p in plates) + 1e-6)
    parts_outside = {mesh.parts[i].name for i in range(len(mesh.parts))
                     if outside[mesh.parts[i].vertices].any()}
    assert parts_outside <= {"eccentric_shaft", "output_flange"}, parts_outside


SEALED_GROUPS = ("discs", "ring_pins", "shaft", "carrier", "bearings")


def _painted(mesh, draw):
    """Paint the draw list in order and return the part index at each pixel.

    The list is an ordering, and an ordering is only wrong where it puts the
    wrong thing in front of your eye - so this checks the picture rather than
    the permutation. Holes are composited through a mask rather than filled with
    background, which is what ``QPainter`` does with one path and the fill rule.
    """
    from PIL import Image, ImageDraw

    width, height = draw.size
    out = np.full((height, width), -1, np.int32)
    for loops, part in zip(draw.loops, draw.parts, strict=True):
        img = Image.new("1", (width, height), 0)
        pen = ImageDraw.Draw(img)
        pen.polygon([tuple(p) for p in loops[0]], fill=1)
        for hole in loops[1:]:
            pen.polygon([tuple(p) for p in hole], fill=0)
        out[np.array(img, bool)] = part
    return out


@pytest.mark.parametrize("phi", [0.0, 1.3, 2.7])
def test_a_closed_gearbox_looks_closed(mesh, phi):
    """The bug this ordering exists for: the guts showing through the lid.

    With the housing and both end plates on, the drive is a closed cylinder with
    two bores in it. A little of the inside is genuinely visible down those
    bores; what is not acceptable is ring pins and discs painted across the top
    face, which is what a single global depth sort produced - the end plate's
    centroid sits at the middle of the drive while the near pins are in front of
    it, so they went down last.

    The bound is deliberately loose. This is not a claim that the painter's
    algorithm is exact - it is not, and the module says so - only that the shell
    is no longer transparent.
    """
    draw = render(mesh, phi, Camera.framing(mesh), 480, 360)
    groups = np.array([p.group for p in mesh.parts])
    painted = _painted(mesh, draw)
    body = painted >= 0
    sealed = np.isin(groups[np.where(body, painted, 0)], SEALED_GROUPS) & body
    assert body.sum() > 10_000
    assert sealed.sum() / body.sum() < 0.02


def test_hiding_a_group_removes_exactly_that_group(mesh):
    """Every part of it, and nothing else.

    Checked on a group with more than one part in it - the two end plates - so
    that hiding the first and leaving the rest on screen cannot pass.
    """
    camera = Camera.framing(mesh)
    everything = render(mesh, 0.2, camera, 640, 480)
    without = render(mesh, 0.2, camera, 640, 480, hidden={"end_plates"})
    housing = [i for i, p in enumerate(mesh.parts) if p.group == "end_plates"]
    assert len(housing) > 1, "this design has only one end plate to hide"
    shown = np.isin(everything.parts, housing)
    assert shown.sum() > 0
    assert not np.isin(without.parts, housing).any()
    assert len(without) == len(everything) - shown.sum()


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


def _same_geometry(a, b) -> bool:
    return (a.vertices.shape == b.vertices.shape
            and np.allclose(a.vertices, b.vertices)
            and [len(f) for f in a.loops] == [len(f) for f in b.loops])


@pytest.mark.parametrize("field", sorted(preset(15).model_fields))
def test_an_unchanged_fingerprint_means_an_unchanged_mesh(field):
    """The cache key is a hand-written list of fields, so it is checked.

    Leaving a field out of :func:`mesh_fingerprint` would serve a stale mesh -
    the picture would quietly stop matching the design, which is the one thing
    the 3D view must never do.  The other direction is allowed: a field that
    changes the key without changing the mesh only costs a rebuild.
    """
    from enum import Enum

    from cycloidgen.analysis.bearings import BY_NAME, CATALOGUE
    from cycloidgen.core.spec import AUTOMATIC, MATERIALS, MOTOR_FRAMES
    from cycloidgen.viz.mesh import mesh_fingerprint

    base = preset(15)
    base.disc_count = 2
    other = base.model_copy(deep=True)
    value = getattr(other, field)
    if isinstance(value, bool):
        setattr(other, field, not value)
    elif isinstance(value, Enum):
        # `offset_mode` reaches the mesh through effective_R and effective_Rr,
        # which is exactly the kind of indirection a hand-written key misses.
        setattr(other, field, next(v for v in type(value) if v != value))
    elif isinstance(value, int | float):
        setattr(other, field, value + 1 if isinstance(value, int)
                else value * 1.1 + 0.05)
    elif value is None:
        setattr(other, field, 12.0)          # eccentric_cam_diameter: auto -> set
    elif isinstance(value, str) and value in MATERIALS:
        setattr(other, field, next(m for m in MATERIALS if m != value))
    elif isinstance(value, str) and value in MOTOR_FRAMES:
        # The frame decides a bolt pattern that is drawn in the plate, so the
        # key has to move with it.
        setattr(other, field, next(m for m in MOTOR_FRAMES if m != value))
    elif isinstance(value, str) and (value == AUTOMATIC or value in BY_NAME):
        # Naming a bearing for a seat changes what is drawn there, so the key
        # has to move with it.  Without this branch the five bearing fields
        # skipped, which is the quietest way for a cache key to go wrong.
        setattr(other, field, next(b.designation for b in CATALOGUE
                                   if b.designation != value))
    else:
        pytest.skip(f"{field} is not a value this test knows how to move")

    if mesh_fingerprint(base) == mesh_fingerprint(other):
        assert _same_geometry(build_mesh(base), build_mesh(other)), (
            f"{field} changes the mesh but not the fingerprint")


# ------------------------------------------------------------------- the VTK
# bridge.  Geometry only - no render window, so this runs without a display.


def _inside(polygon: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Ray casting in the plane: which of ``points`` fall inside ``polygon``."""
    x, y = points[:, 0], points[:, 1]
    px, py = polygon[:, 0], polygon[:, 1]
    qx, qy = np.roll(px, -1), np.roll(py, -1)
    inside = np.zeros(len(points), dtype=bool)
    for x0, y0, x1, y1 in zip(px, py, qx, qy, strict=True):
        if y0 == y1:
            continue
        crosses = ((y0 > y) != (y1 > y)) & (
            x < x0 + (y - y0) * (x1 - x0) / (y1 - y0))
        inside ^= crosses
    return inside


def test_the_vtk_triangulation_keeps_every_hole_open(mesh):
    """VTK has no polygon-with-holes cell, so the caps are triangulated.

    A triangulation that quietly filled the bore, or dropped one of the bolt
    holes, would look almost right and be wrong by the area of a hole - and the
    hardware view is the one people look at.

    Stated as the property itself rather than as total surface area, which was
    the cheap proxy for it until it stopped being equivalent: with a dozen holes
    in one face the triangulator emits some overlapping coplanar triangles, so
    the areas differ by a fraction of a percent while every hole is still open.
    Overlapping triangles in one plane are invisible; a filled hole is not.
    """
    from cycloidgen.viz.vtkbridge import part_polydata

    for part in mesh.parts:
        polydata = part_polydata(mesh, part)
        assert polydata.GetNumberOfCells() > 0, part.name

        centres = np.array([
            np.mean([polydata.GetPoint(polydata.GetCell(c).GetPointId(i))
                     for i in range(polydata.GetCell(c).GetNumberOfPoints())],
                    axis=0)
            for c in range(polydata.GetNumberOfCells())])

        for index in range(part.facets.start, part.facets.stop):
            loops = mesh.loops[index]
            if len(loops) == 1:
                continue
            z = mesh.vertices[loops[0][0]][2]
            on_plane = centres[np.isclose(centres[:, 2], z, atol=1e-9)]
            for hole in loops[1:]:
                shape = mesh.vertices[hole][:, :2]
                # A hair inside, so a triangle that merely touches the rim of a
                # hole is not read as filling it.
                shrunk = shape.mean(axis=0) + 0.8 * (shape - shape.mean(axis=0))
                assert not _inside(shrunk, on_plane[:, :2]).any(), \
                    f"{part.name}: a hole was triangulated over"

        # ...and nothing was dropped either, which the area still catches at a
        # tolerance far below one hole.
        expected = float(np.linalg.norm(_face_areas(mesh)[part.facets], axis=1).sum())
        from vtkmodules.vtkFiltersCore import vtkMassProperties, vtkTriangleFilter
        triangles = vtkTriangleFilter()
        triangles.SetInputData(polydata)
        triangles.Update()
        properties = vtkMassProperties()
        properties.SetInputData(triangles.GetOutput())
        properties.Update()
        assert properties.GetSurfaceArea() == pytest.approx(expected, rel=0.01), \
            part.name


def test_the_drawn_edges_are_features_and_not_the_triangulation(mesh):
    """"Edges" must not mean "every triangle".

    The end faces are triangulated to get their holes, so drawing every cell
    edge covers a disc in the long thin triangles the triangulator happened to
    produce - none of which are edges of the part.  Stated exactly: a drawn
    edge has to be an edge of one of the mesh's own loops.  A triangulation
    edge joins two loop vertices that are not neighbours, and is caught here.
    """
    from cycloidgen.viz.vtkbridge import feature_edges, part_polydata

    part = next(p for p in mesh.parts if p.group == "discs")
    edges = feature_edges(part_polydata(mesh, part))
    assert edges.GetNumberOfCells() > 0

    def key(point):
        return tuple(np.round(point, 6))

    real = set()
    for index in range(part.facets.start, part.facets.stop):
        for loop in mesh.loops[index]:
            points = mesh.vertices[loop]
            for a, b in zip(points, np.roll(points, -1, axis=0), strict=True):
                real.add(frozenset((key(a), key(b))))

    for cell in range(edges.GetNumberOfCells()):
        points = edges.GetCell(cell).GetPoints()
        pair = frozenset((key(points.GetPoint(0)), key(points.GetPoint(1))))
        assert pair in real, "an edge that is not an edge of the part"


def test_shifting_an_edge_toward_the_eye_leaves_its_picture_alone(mesh):
    """The property the whole edge-drawing approach rests on.

    An edge lies exactly on the surface it came from, so it has to be moved to
    win the depth test - and any move that changes where it *projects* draws
    the line beside the edge instead of on it, which is what a lift along the
    surface normal does to a vertical wall.  Sliding along the view ray cannot:
    the point stays on the ray, so it stays on its pixel.
    """
    from vtkmodules.util.numpy_support import vtk_to_numpy

    from cycloidgen.viz.vtkbridge import feature_edges, part_polydata, toward_eye

    part = next(p for p in mesh.parts if p.group == "ring_pins")
    edges = feature_edges(part_polydata(mesh, part))
    points = vtk_to_numpy(edges.GetPoints().GetData())
    eye = np.array([180.0, -240.0, 160.0])

    shifted = toward_eye(points, eye, 0.02)
    to_eye = eye - points
    # Collinear with the ray to the eye: same direction, so same pixel.
    assert np.allclose(np.cross(to_eye, shifted - points), 0.0, atol=1e-9)
    # ...and nearer the eye than it was, which is the point of the exercise.
    assert np.all(np.linalg.norm(eye - shifted, axis=1)
                  < np.linalg.norm(to_eye, axis=1))


def test_a_point_round_trips_through_a_part_frame(mesh):
    """`local_point` is the inverse of the pose the actor is given."""
    from cycloidgen.viz.vtkbridge import local_point, pose_matrix

    world = np.array([37.0, -12.0, 5.5])
    for part in mesh.parts:
        pose = pose_matrix(mesh, part, 0.8, explode=0.25)
        angle, dx, dy, dz = pose
        c, s = np.cos(np.radians(angle)), np.sin(np.radians(angle))
        forward = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
        back = local_point(pose, world)
        assert np.allclose(forward @ back + [dx, dy, dz], world, atol=1e-9), \
            part.name


def test_a_section_plane_survives_the_trip_into_a_part_frame(mesh):
    """The cut is stated in the world; the geometry is stored unposed.

    Cutting the stored geometry means carrying the plane backwards through the
    pose.  Getting that inverse wrong puts the cut somewhere else on every part
    that turns, and only on the ones that turn - which is exactly the kind of
    bug that looks fine at crank zero.
    """
    from cycloidgen.viz.vtkbridge import local_plane, pose_matrix

    origin, normal = (0.0, 3.0, 0.0), (0.0, -1.0, 0.0)
    phi = 1.1
    for part in mesh.parts:
        pose = pose_matrix(mesh, part, phi, explode=0.3)
        local_origin, local_normal = local_plane(pose, origin, normal)

        angle, dx, dy, dz = pose
        c, s = np.cos(np.radians(angle)), np.sin(np.radians(angle))
        forward = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
        # A point on the plane in the part's frame must land on the plane
        # again once the part is placed.
        world = forward @ local_origin + np.array([dx, dy, dz])
        assert np.dot(np.array(normal), world - np.array(origin)) == \
            pytest.approx(0.0, abs=1e-9), part.name
        assert np.allclose(forward @ local_normal, normal, atol=1e-9), part.name


def test_the_vtk_pose_is_the_same_motion_law_as_the_mesh(spec, mesh):
    """Two ways of placing a part; they have to agree exactly.

    The software view transforms the vertices and the hardware view hands VTK a
    rotation and a translation.  If those ever diverge, the two 3D views show
    different mechanisms and only one of them is the one being exported.
    """
    from cycloidgen.viz.vtkbridge import pose_matrix

    phi = 1.3
    world = mesh.world_vertices(phi, explode=0.4)
    for part in mesh.parts:
        angle, dx, dy, dz = pose_matrix(mesh, part, phi, explode=0.4)
        radians = np.radians(angle)
        c, s = np.cos(radians), np.sin(radians)
        local = mesh.vertices[part.vertices]
        placed = np.column_stack([
            local[:, 0] * c - local[:, 1] * s + dx,
            local[:, 0] * s + local[:, 1] * c + dy,
            local[:, 2] + dz,
        ])
        assert np.allclose(placed, world[part.vertices], atol=1e-9), part.name


# ------------------------------------------------------- watertight surfaces
#
# The module docstring above has claimed since it was written that every part
# is a closed surface.  Nothing checked it on the VTK side, and none of them
# were: the faces are emitted one at a time, each with its own copy of every
# corner, so no face shared an edge with its neighbour and every edge in the
# assembly was a boundary edge.  `vtkClipClosedSurface` caps a *closed* surface
# and could not cap any of them, which is what put half a sectioned gearbox on
# screen as solid material and the other half as empty shells.

WATERTIGHT_CASES = [10, 15, 21, 29, 39, 59]


def _loop_area(points: np.ndarray) -> float:
    """Shoelace area of one closed loop, projected on XY."""
    x, y = points[:, 0], points[:, 1]
    return 0.5 * abs(float(np.sum(x * np.roll(y, -1) - y * np.roll(x, -1))))


def _edge_counts(polydata) -> tuple[int, int]:
    """``(holes, non-manifold edges)`` in one part."""
    from vtkmodules.vtkFiltersCore import vtkFeatureEdges, vtkTriangleFilter

    triangles = vtkTriangleFilter()
    triangles.SetInputData(polydata)
    triangles.Update()

    def count(boundary: bool, nonmanifold: bool) -> int:
        edges = vtkFeatureEdges()
        edges.SetInputConnection(triangles.GetOutputPort())
        edges.SetBoundaryEdges(boundary)
        edges.SetNonManifoldEdges(nonmanifold)
        edges.FeatureEdgesOff()
        edges.ManifoldEdgesOff()
        edges.Update()
        return edges.GetOutput().GetNumberOfCells()

    return count(True, False), count(False, True)


@pytest.mark.parametrize("ratio", WATERTIGHT_CASES)
def test_every_part_is_watertight_once_built_for_vtk(ratio):
    """No holes, and no edge with more than two faces on it.

    Not the same statement as
    :func:`test_every_part_is_a_closed_surface` above, which is why that one
    passed throughout.  It weighs the mesh's own facet loops, and those cancel:
    a face is *declared* whether or not the triangulator managed to fill it.
    This one asks the built surface, and so sees a face that came out with a
    sliver missing and two prisms that both kept the face they meet on.
    """
    from cycloidgen.viz.vtkbridge import closed_polydata

    mesh = build_mesh(preset(ratio))
    faults = []
    for part in mesh.parts:
        holes, nonmanifold = _edge_counts(closed_polydata(mesh, part))
        if holes or nonmanifold:
            faults.append(f"{part.name}: {holes} hole edges, "
                          f"{nonmanifold} non-manifold")
    assert not faults, "; ".join(faults)


@pytest.mark.parametrize("ratio", [15, 21, 29])
def test_a_face_is_cut_into_triangles_that_cover_it_exactly(ratio):
    """The check the old triangulator did not do for itself.

    ``vtkContourTriangulator`` could stop part way and report nothing about it,
    and one disc's top face came back 0.93% short that way while the same face
    on the other disc was exact. The cutting is ours now and this asks it the
    same three questions the suite asks of a finished part: the whole area, no
    triangle laid on another, and a boundary exactly as long as the loops.
    """
    from cycloidgen.viz.tessellate import triangulate

    mesh = build_mesh(preset(ratio))
    for index, loops in enumerate(mesh.loops):
        if len(loops) == 1 and len(loops[0]) <= 4:
            continue                      # a side-wall quad, handed over whole
        want = _loop_area(mesh.vertices[list(loops[0])])
        for loop in loops[1:]:
            want -= _loop_area(mesh.vertices[list(loop)])
        if want <= 0.0:
            continue

        triangles = triangulate(mesh.vertices, loops)
        got = sum(_loop_area(mesh.vertices[list(t)]) for t in triangles)
        assert got == pytest.approx(want, rel=1e-9),             f"facet {index} lost {100 * (want - got) / want:.3f}% of its area"

        directed = [e for a, b, c in triangles
                    for e in ((a, b), (b, c), (c, a))]
        assert len(set(directed)) == len(directed), f"facet {index} folds"
        boundary = [e for e in directed if (e[1], e[0]) not in set(directed)]
        assert len(boundary) == sum(len(loop) for loop in loops)


def test_the_triangles_are_the_mesh_s_own_vertices():
    """What lets a cap share its corners with the walls that meet it.

    The face is cut as *indices*, so a corner of a triangle is the same vertex
    the wall below it uses rather than a copy of it that has to be merged back
    afterwards - and no coordinate is rotated, written out and read back on the
    way, which is where a face would pick up a rounding error and stop merging.
    """
    from cycloidgen.viz.tessellate import triangulate

    mesh = build_mesh(preset(21))
    for loops in mesh.loops:
        if len(loops) == 1 and len(loops[0]) <= 4:
            continue
        allowed = {int(v) for loop in loops for v in loop}
        for triangle in triangulate(mesh.vertices, loops):
            assert set(triangle) <= allowed


# ------------------------------------------------------------- integral pins
#
# A pocket and the pin that fills it are one shape read from either side, so
# the whole difference between a housing that takes dowels and one printed with
# its pins on is which arc of the same circle the bore follows.


def test_integral_pins_leave_the_bore_smaller_than_the_pin_circle():
    """Pockets take material out of the housing; integral pins put it in.

    The plain pin circle sits between the two, which is the check that the
    arcs are complementary rather than both bulging the same way.
    """
    from cycloidgen.viz.mesh import pocketed_bore

    spec = preset(21)
    R, Rr, n = spec.pin_circle_radius, spec.pin_radius, spec.pin_count

    def area(loop):
        x, y = loop[:, 0], loop[:, 1]
        return 0.5 * abs(float(np.dot(x, np.roll(y, -1))
                               - np.dot(y, np.roll(x, -1))))

    pocketed = area(pocketed_bore(R, Rr, n))
    integral = area(pocketed_bore(R, Rr, n, integral=True))
    plain = np.pi * R * R
    assert integral < plain < pocketed


def test_integral_pins_are_not_a_separate_part():
    """No mesh part, no exported solid, no line on the bill of materials."""
    from cycloidgen.analysis import analyse
    from cycloidgen.export.bom import bom_items
    from cycloidgen.export.solid import parts

    spec = preset(21).model_copy(update={"ring_pins_integral": True})
    assert "ring_pins" not in [p.name for p in build_mesh(spec).parts]
    assert "ring_pins" not in parts(spec)
    assert not [i for i in bom_items(analyse(spec)) if "Ring pin" in i.part]


def test_integral_pins_move_their_mass_into_the_housing():
    """The steel dowels become housing, in the housing's own material."""
    from cycloidgen.analysis import analyse

    loose = analyse(preset(21))
    formed = analyse(preset(21).model_copy(
        update={"ring_pins_integral": True}))

    assert formed.mass.housing_mass_g > loose.mass.housing_mass_g
    assert formed.mass.pins_mass_g < loose.mass.pins_mass_g
    # lighter overall, because the housing is the softer, lighter material -
    # which is the reason to want them on a printed drive
    assert formed.mass.total_mass_g < loose.mass.total_mass_g


def test_an_integral_pin_cannot_roll_however_the_spec_was_built():
    """`model_copy` runs no validators, so this cannot be enforced by one.

    The flag stays as the preference it is - it comes back when the pins stop
    being integral - and everything that asks about the contact asks
    ``ring_pins_roll``.
    """
    from cycloidgen.analysis import analyse

    spec = preset(21).model_copy(update={"ring_pins_integral": True,
                                         "ring_pins_are_rollers": True})
    assert spec.ring_pins_are_rollers is True
    assert spec.ring_pins_roll is False

    rolling = analyse(preset(21).model_copy(
        update={"ring_pins_are_rollers": True}))
    sliding = analyse(spec)
    assert sliding.efficiency.efficiency < rolling.efficiency.efficiency
    assert sliding.thermal.pv_ring_MPa_m_s > rolling.thermal.pv_ring_MPa_m_s
