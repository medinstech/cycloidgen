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

import weakref

import numpy as np
from vtkmodules.vtkCommonCore import vtkPoints
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
from vtkmodules.vtkCommonExecutionModel import vtkAlgorithm
from vtkmodules.vtkFiltersCore import vtkCleanPolyData, vtkPolyDataNormals

from . import tessellate
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


#: Cut faces, per mesh, keyed on the face's index in it.
#:
#: A rebuild asks for each part twice - once closed, for the section and the
#: topology, and once split, for the shading - and the second ask would
#: otherwise cut every cap again.  Keyed on the mesh *object*, which
#: :func:`~cycloidgen.viz.mesh.mesh_for_spec` already returns unchanged when the
#: geometry has not changed, so dragging a field that is not geometry costs
#: nothing here either.  Weak, so a mesh that has been dropped takes its
#: triangles with it.
#:
#: A mesh holds arrays and so cannot be a dictionary key itself.  It is keyed by
#: identity instead, and the weak reference beside each entry is what makes that
#: safe: ``id`` is reused the moment an object is collected, so the entry is
#: kept only while the mesh it was cut from is still the mesh at that address.
_CUT: dict[int, tuple[weakref.ref, dict[int, list[tuple[int, int, int]]]]] = {}


def _faces(mesh: Mesh, index: int) -> list[tuple[int, int, int]]:
    """The triangles of one face, cut once and remembered."""
    entry = _CUT.get(id(mesh))
    if entry is None or entry[0]() is not mesh:
        if len(_CUT) > 8:
            for key in [k for k, (ref, _) in _CUT.items() if ref() is None]:
                del _CUT[key]
        entry = _CUT[id(mesh)] = (weakref.ref(mesh), {})
    cache = entry[1]
    triangles = cache.get(index)
    if triangles is None:
        triangles = cache[index] = tessellate.triangulate(mesh.vertices,
                                                          mesh.loops[index])
    return triangles


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
    for index in range(part.facets.start, part.facets.stop):
        loops = mesh.loops[index]
        if len(loops) == 1 and len(loops[0]) <= 4:
            # Side walls: planar quads, and convex, so VTK renders them
            # directly.  This is most of the mesh and not cutting it up is most
            # of the build time.
            polys.InsertNextCell(len(loops[0]))
            for vertex in loops[0]:
                polys.InsertCellPoint(int(vertex) - start)
            continue
        # Everything else - the caps, with their bores and bolt circles - is
        # cut in `viz.tessellate`, which hands back indices into the mesh's own
        # vertices.  So the triangles go into the same cell array as the walls
        # and share their corners with them: there is no second copy of a
        # boundary here to append and merge afterwards.
        for triangle in _faces(mesh, index):
            polys.InsertNextCell(3)
            for vertex in triangle:
                polys.InsertCellPoint(vertex - start)

    surface = vtkPolyData()
    surface.SetPoints(points)
    surface.SetPolys(polys)
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
