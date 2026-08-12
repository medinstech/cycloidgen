"""Turn a :class:`~cycloidgen.viz.mesh.Mesh` into VTK polydata, one per part.

Why VTK and not something new: CadQuery already ships it.  The kernel that
writes the STEP files brings ``vtkmodules`` with it, it is already collected by
the PyInstaller spec, and it is a real GPU renderer - depth buffer, smooth
shading, screen-space ambient occlusion, clipping planes.  Adding a second 3D
stack to get that would have been a dependency for something already installed.

This module holds the part of that which is *not* Qt: building the geometry.
It imports no widget, opens no window, and so can be tested on a machine with no
display, which is the only way the mesh-to-VTK translation gets checked at all.

One polydata per part, in the part's own local frame.  Nothing here is rebuilt
when the crank turns: every motion in a cycloidal drive is a rigid rotation
about Z plus a translation, so a frame costs one 4x4 per part and the geometry
stays on the card.
"""
from __future__ import annotations

import numpy as np
from vtkmodules.util.numpy_support import vtk_to_numpy
from vtkmodules.vtkCommonCore import vtkIdList, vtkPoints
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
from vtkmodules.vtkCommonExecutionModel import vtkAlgorithm
from vtkmodules.vtkFiltersCore import vtkCleanPolyData, vtkPolyDataNormals
from vtkmodules.vtkFiltersGeneral import vtkContourTriangulator

from .mesh import Mesh, Part

#: VTK stores points as 32-bit floats unless told otherwise.  At 50 mm that is
#: a resolution of about 3 nm, which sounds like plenty until you remember what
#: this geometry is carrying: profile clearances of a few tens of micrometres,
#: measured against a manufactured outline.  Keeping the pipeline in double
#: costs a few hundred kilobytes and removes the question entirely - and it is
#: what lets a test compare a VTK point against the mesh vertex it came from.
_DOUBLE = vtkAlgorithm.DOUBLE_PRECISION

__all__ = ["FEATURE_ANGLE", "closed_polydata", "feature_edges", "local_plane",
           "local_point", "part_polydata", "pose_matrix", "toward_eye"]

#: Edges sharper than this stay sharp; everything flatter is smoothed across.
#: A cylinder sampled at 24 sides has 15-degree creases and should read as
#: round; the join between a cylinder's wall and its end cap is 90 degrees and
#: must not.  Splitting at 30 gets both, and is why the pins stopped looking
#: like nuts.
FEATURE_ANGLE = 30.0


#: Angles to try the triangulator at, in degrees, when it comes out wrong at
#: the one it was given.  The failure is numerical rather than geometric - the
#: same disc succeeds on one hole phase and fails on the next - so turning the
#: face in its own plane is enough to clear it, and *which* angle clears it
#: differs per face.  Nothing here is special; they are spread and not multiples
#: of one another, so a case that is degenerate at one is unlikely to be at the
#: rest.
#:
#: The last four came out of a search rather than off a hat: every distinct
#: multi-hole face this app can draw - six ratios, both output members, every
#: motor frame, three tie-bolt counts - was triangulated at every angle on a
#: 0.7-degree grid, and these are the smallest set that covers all of them.
#: The six before them are kept in front so that a face which already worked
#: goes on being triangulated the way it was.
#:
#: A handful of faces have no clean angle at any rotation, and all of them are
#: the same thing: a small motor's bolt pattern overlapping the shaft-support
#: bore, so the loops genuinely cross and there is no face to fill.  Those
#: designs are already an export-blocking ``MOTOR_FACE_CLASH`` error.
_RETRY_ANGLES = (3.1, 11.3, 37.0, 61.7, 83.3, 127.9, 7.7, 118.3, 133.7, 135.1)

#: How much of a face's area may go missing before it is treated as a failure.
#: A correct triangulation matches the shoelace area to rounding; the failures
#: seen lose or double tenths of a percent, so anything in between is noise.
_AREA_TOLERANCE = 1e-6


def _polygon_area(points: np.ndarray) -> float:
    """Shoelace area of one closed loop, projected on XY."""
    x, y = points[:, 0], points[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def _triangulate_at(coords: np.ndarray, sizes: list[int]) -> vtkPolyData | None:
    """Run the triangulator over loops laid end to end in ``coords``."""
    pts = vtkPoints()
    pts.SetDataTypeToDouble()
    lines = vtkCellArray()
    start = 0
    for size in sizes:
        ids = [pts.InsertNextPoint(*coords[start + k]) for k in range(size)]
        lines.InsertNextCell(len(ids) + 1)
        for i in ids:
            lines.InsertCellPoint(i)
        lines.InsertCellPoint(ids[0])          # closed
        start += size

    contour = vtkPolyData()
    contour.SetPoints(pts)
    contour.SetLines(lines)
    # No output-precision knob on this one; it reuses the contour's own points,
    # which is why they are made double above rather than here.
    triangulator = vtkContourTriangulator()
    triangulator.SetInputData(contour)
    triangulator.Update()
    out = triangulator.GetOutput()
    return out if out.GetNumberOfCells() else None


def _measure(out: vtkPolyData) -> tuple[float, int, int]:
    """One pass over a triangulation: ``(area, boundary edges, over-shared)``.

    The area says whether the triangulator covered the face.  The edge counts
    say whether it covered it *once* and left the boundary where the loops put
    it - and those are not the same question, which is the whole reason this
    returns three numbers instead of one.  A face can come back with its area
    exactly right and a triangle missing, if the triangulator has also emitted
    another one twice; the area cancels and the hole does not.
    """
    area = 0.0
    edges: dict[tuple[int, int], int] = {}
    polys, ids = out.GetPolys(), vtkIdList()
    polys.InitTraversal()
    verts = vtk_to_numpy(out.GetPoints().GetData())
    while polys.GetNextCell(ids):
        n = ids.GetNumberOfIds()
        pid = [ids.GetId(k) for k in range(n)]
        area += _polygon_area(np.array([verts[i] for i in pid]))
        for k in range(n):
            a, b = pid[k], pid[(k + 1) % n]
            key = (a, b) if a < b else (b, a)
            edges[key] = edges.get(key, 0) + 1
    boundary = sum(1 for count in edges.values() if count == 1)
    over = sum(1 for count in edges.values() if count > 2)
    return area, boundary, over


def _triangulated(points: np.ndarray, loops) -> vtkPolyData | None:
    """Triangulate one planar face, holes and all.

    VTK has no polygon-with-holes cell - ``vtkPolygon`` is a simple polygon -
    so a disc end face, which is a lobed outline with a bore and six output
    holes in it, cannot be handed over as one cell.  ``vtkContourTriangulator``
    is the tool for exactly this: closed contours in, triangles out, inner
    loops cut away by the even-odd rule.

    It also gives up part way on some inputs, and says nothing about it.  This
    used to be accepted as long as it produced *any* triangles: one disc's top
    face came out 0.93% short - a hole in the surface, four boundary edges
    wide, on a part the section then could not cap - while the same disc's
    bottom face and the other disc were perfect.  So the result is checked
    against the loops it was built from, and a face that fails is tried again
    with the plane turned.

    Checked two ways, because the area alone is not enough.  A plate carrying
    two bolt circles and a bore - fourteen loops in one face - came back with
    its area exact to rounding and a triangle missing all the same: the
    triangulator had emitted a different one twice, and the two errors cancelled
    in a sum of absolute areas.  What that face is *for* is being closed, so the
    second test asks the topology directly - every edge either on a loop or
    shared by exactly two triangles - which is the same statement the watertight
    test makes about the finished part, made early enough to retry.

    The retry keeps the *connectivity* and throws the rotated coordinates away:
    the points come back from the original array, bit for bit, because they
    have to merge exactly with the wall vertices that share them.
    """
    sizes = [len(lp) for lp in loops]
    original = np.vstack([points[list(lp)] for lp in loops])
    perimeter = sum(sizes)

    want = _polygon_area(points[list(loops[0])])
    for loop in loops[1:]:
        want -= _polygon_area(points[list(loop)])

    best: vtkPolyData | None = None
    for angle in (0.0, *_RETRY_ANGLES):
        if angle:
            a = np.radians(angle)
            c, s = np.cos(a), np.sin(a)
            coords = original.copy()
            coords[:, 0] = original[:, 0] * c - original[:, 1] * s
            coords[:, 1] = original[:, 0] * s + original[:, 1] * c
        else:
            coords = original

        out = _triangulate_at(coords, sizes)
        if out is None:
            continue
        best = best or out

        got, boundary, over = _measure(out)
        if boundary != perimeter or over:
            continue
        if want <= 0.0 or abs(want - got) / want <= _AREA_TOLERANCE:
            return _with_points(out, original)

    # Every angle came up short.  The best of them is still a face, and a
    # missing sliver is better than a missing surface - but it leaves the part
    # unwatertight, which ``tests/test_viz.py`` asserts against so that this
    # cannot go unnoticed the way it did before.
    return _with_points(best, original) if best is not None else None


def _with_points(out: vtkPolyData, original: np.ndarray) -> vtkPolyData:
    """``out``'s triangles, over the coordinates they were built from.

    ``vtkContourTriangulator`` hands back the points it was given, in the order
    it was given them - asserted in ``tests/test_viz.py``, because the retry
    above depends on it to undo a rotation without touching a coordinate.
    """
    if out.GetNumberOfPoints() != len(original):
        return out                       # not the mapping we assumed; leave it
    pts = vtkPoints()
    pts.SetDataTypeToDouble()
    pts.SetNumberOfPoints(len(original))
    for i, (x, y, z) in enumerate(original):
        pts.SetPoint(i, x, y, z)
    rebuilt = vtkPolyData()
    rebuilt.SetPoints(pts)
    rebuilt.SetPolys(out.GetPolys())
    return rebuilt


def _surface(mesh: Mesh, part: Part) -> vtkPolyData:
    """One part's faces in its own frame, exactly as the mesh emitted them."""
    local = mesh.vertices[part.vertices]
    start = part.vertices.start

    points = vtkPoints()
    points.SetDataTypeToDouble()
    points.SetNumberOfPoints(len(local))
    for i, (x, y, z) in enumerate(local):
        points.SetPoint(i, x, y, z)

    polys = vtkCellArray()
    extra: list[vtkPolyData] = []
    for index in range(part.facets.start, part.facets.stop):
        loops = mesh.loops[index]
        if len(loops) == 1 and len(loops[0]) <= 4:
            # Side walls: planar quads, and convex, so VTK renders them
            # directly.  This is most of the mesh and skipping the triangulator
            # for it is most of the build time.
            polys.InsertNextCell(len(loops[0]))
            for vertex in loops[0]:
                polys.InsertCellPoint(int(vertex) - start)
            continue
        piece = _triangulated(mesh.vertices, loops)
        if piece is not None:
            extra.append(piece)

    surface = vtkPolyData()
    surface.SetPoints(points)
    surface.SetPolys(polys)

    if extra:
        from vtkmodules.vtkFiltersCore import vtkAppendPolyData
        append = vtkAppendPolyData()
        append.SetOutputPointsPrecision(_DOUBLE)
        append.AddInputData(surface)
        for piece in extra:
            append.AddInputData(piece)
        append.Update()
        surface = append.GetOutput()

    return surface


def closed_polydata(mesh: Mesh, part: Part) -> vtkPolyData:
    """One part as a watertight surface: coincident points merged.

    The faces are built face by face and each brings its own copy of every
    corner, so nothing shares an edge with its neighbour: geometrically the
    part is solid, topologically it is a heap of loose facets, and every edge
    in it is a boundary edge.

    That is not a cosmetic distinction.  ``vtkClipClosedSurface`` caps a
    *closed* surface and cannot cap this one, so a section came out with some
    parts reading as solid material and others as empty shells.  It also
    doubled the feature-edge set - every edge found twice, once from each of
    the two faces that should have been sharing it.

    Merging is exact rather than tolerant: these points are copies of the same
    vertex, not two vertices that happen to be close, and a tolerance here
    would start welding a thin wall to itself.
    """
    clean = vtkCleanPolyData()
    clean.SetInputData(_surface(mesh, part))
    clean.PointMergingOn()
    clean.SetTolerance(0.0)
    clean.ConvertLinesToPointsOff()
    clean.ConvertPolysToLinesOff()
    clean.ConvertStripsToPolysOff()
    clean.SetOutputPointsPrecision(_DOUBLE)
    clean.Update()
    return clean.GetOutput()


def part_polydata(mesh: Mesh, part: Part) -> vtkPolyData:
    """One part's geometry, shaded: merged, then split again where it creases.

    Built on :func:`closed_polydata` rather than on the loose facets, so the
    splitting below is the *only* thing separating any two points - which is
    what makes it a shading decision rather than an accident of how the faces
    were emitted.  Anything that needs the topology, rather than the shading,
    wants ``closed_polydata``: this surface is deliberately open again.
    """
    normals = vtkPolyDataNormals()
    normals.SetInputData(closed_polydata(mesh, part))
    normals.SetFeatureAngle(FEATURE_ANGLE)
    # Splitting is what gives a cylinder's end cap a hard edge against its
    # wall instead of a smeared one.  It duplicates the points along that
    # crease, which is why it comes last and why the closed surface is kept.
    normals.SplittingOn()
    normals.ConsistencyOn()
    normals.AutoOrientNormalsOff()             # the mesh is already wound out
    normals.ComputePointNormalsOn()
    normals.SetOutputPointsPrecision(_DOUBLE)
    normals.Update()
    return normals.GetOutput()


def feature_edges(polydata):
    """The edges worth drawing: silhouettes and creases, not the triangulation.

    Turning on "edges" in a renderer normally means *every* edge of every cell,
    and on this mesh that is a disaster: the end faces are triangulated to get
    their holes, so a disc arrives covered in the long thin triangles the
    triangulator happened to produce.  None of those are features of the part.

    What a mechanical drawing wants is where the surface actually turns a
    corner - the rim of a disc, the lip of a hole, the join between a cylinder
    and its end - and a 24-sided pin's own facets, at 15 degrees, must stay out
    of it.  ``vtkFeatureEdges`` above :data:`FEATURE_ANGLE` is exactly that
    set, and it is computed once per design because the part does not deform.

    Drawing the result is a separate problem - see :func:`toward_eye`.
    """
    from vtkmodules.vtkFiltersCore import vtkFeatureEdges

    edges = vtkFeatureEdges()
    edges.SetInputData(polydata)
    edges.SetFeatureAngle(FEATURE_ANGLE)
    edges.FeatureEdgesOn()
    edges.BoundaryEdgesOn()        # nothing should be open; if it is, show it
    edges.NonManifoldEdgesOff()
    edges.ManifoldEdgesOff()
    edges.ColoringOff()
    edges.Update()
    return edges.GetOutput()


#: How far the drawn edges are moved toward the viewer, as a fraction of their
#: own distance from it.  A thousandth is far more than enough to settle the
#: depth test and far less than the thinnest wall the mesh contains, which is
#: what keeps a far-side edge from surfacing through a near one.
EDGE_SHIFT = 0.001


def toward_eye(points: np.ndarray, eye, fraction: float = EDGE_SHIFT) -> np.ndarray:
    """Slide points along their own view rays, toward ``eye``.

    An edge lies exactly on the surface it came from, so the depth test cannot
    separate them and the lines vanish into the shading.  The obvious cures are
    both wrong here, and were both tried:

    * A **depth-buffer offset** is fixed in depth units while zooming magnifies
      only the screen, so a value that makes the lines visible from across the
      drive shows every hidden edge through the part once you lean in.
    * **Lifting along the surface normal** moves a line on a vertical wall
      *sideways*, and the rim of a disc ends up drawn beside the disc rather
      than on it - a halo, plainly visible at any real zoom.

    Moving a point toward the eye has neither problem, because a point slid
    along the ray it is already on **projects to exactly the same pixel**.  The
    picture does not move; only the depth does.  And because the shift is a
    fraction of the distance, it scales itself: closer in, the camera is nearer
    and the shift is smaller in the same proportion.
    """
    eye = np.asarray(eye, float)
    return points + fraction * (eye - points)


def local_point(pose, point) -> np.ndarray:
    """Carry a world-space point into a part's own frame."""
    angle, dx, dy, dz = pose
    a = np.radians(angle)
    c, s = np.cos(a), np.sin(a)
    inverse = np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]])
    return inverse @ (np.asarray(point, float) - np.array([dx, dy, dz]))


def local_plane(pose, origin, normal):
    """Carry a world-space plane into a part's own frame.

    The parts are stored unposed and placed by a transform on the actor, which
    is what keeps a frame cheap.  A section plane, though, is stated in the
    world - so to cut the *stored* geometry the plane has to be brought back
    through the same transform rather than the geometry pushed forward through
    it.  The normal rotates but does not translate.
    """
    angle = pose[0]
    a = np.radians(angle)
    c, s = np.cos(a), np.sin(a)
    inverse = np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]])
    return local_point(pose, origin), inverse @ np.asarray(normal, float)


def pose_matrix(mesh: Mesh, part: Part, phi: float, explode: float = 0.0):
    """The part's pose at crank angle ``phi`` as (degrees about Z, dx, dy, dz).

    Kept as plain numbers rather than a ``vtkTransform`` so that the motion law
    can be checked without VTK - it is the same law
    :meth:`Mesh.world_vertices` applies, and the two are compared in the tests.

    Including the frame: on a ring-output drive the whole assembly turns under
    itself, and the orbit offset is a vector in the frame being turned, so it
    has to be carried round with it rather than added afterwards.  Leaving it
    out here would have left the two renderers drawing different gearboxes from
    the same mesh - the software painter turning the housing and the hardware
    one holding it still.
    """
    frame = mesh.frame_spin * phi
    angle = part.spin * (phi + part.phase) + frame
    if part.orbits:
        dx = mesh.eccentricity * np.cos(phi + part.phase)
        dy = -mesh.eccentricity * np.sin(phi + part.phase)
        c, s = np.cos(frame), np.sin(frame)
        dx, dy = c * dx - s * dy, s * dx + c * dy
    else:
        dx = dy = 0.0
    return (np.degrees(angle), float(dx), float(dy),
            explode * part.explode * mesh.explode_span)
