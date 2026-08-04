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
from vtkmodules.vtkCommonCore import vtkPoints
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
from vtkmodules.vtkFiltersCore import vtkPolyDataNormals
from vtkmodules.vtkFiltersGeneral import vtkContourTriangulator

from .mesh import Mesh, Part

__all__ = ["FEATURE_ANGLE", "part_polydata", "pose_matrix"]

#: Edges sharper than this stay sharp; everything flatter is smoothed across.
#: A cylinder sampled at 24 sides has 15-degree creases and should read as
#: round; the join between a cylinder's wall and its end cap is 90 degrees and
#: must not.  Splitting at 30 gets both, and is why the pins stopped looking
#: like nuts.
FEATURE_ANGLE = 30.0


def _triangulated(points: np.ndarray, loops) -> vtkCellArray | None:
    """Triangulate one planar face, holes and all.

    VTK has no polygon-with-holes cell - ``vtkPolygon`` is a simple polygon -
    so a disc end face, which is a lobed outline with a bore and six output
    holes in it, cannot be handed over as one cell.  ``vtkContourTriangulator``
    is the tool for exactly this: closed contours in, triangles out, inner
    loops cut away by the even-odd rule.  Checked against the shoelace area of
    the same loops in ``tests/test_viz.py``.
    """
    pts = vtkPoints()
    lines = vtkCellArray()
    for loop in loops:
        ids = [pts.InsertNextPoint(*points[i]) for i in loop]
        lines.InsertNextCell(len(ids) + 1)
        for i in ids:
            lines.InsertCellPoint(i)
        lines.InsertCellPoint(ids[0])          # closed

    contour = vtkPolyData()
    contour.SetPoints(pts)
    contour.SetLines(lines)
    triangulator = vtkContourTriangulator()
    triangulator.SetInputData(contour)
    triangulator.Update()
    out = triangulator.GetOutput()
    return out if out.GetNumberOfCells() else None


def part_polydata(mesh: Mesh, part: Part) -> vtkPolyData:
    """One part's geometry in its own frame, with vertex normals."""
    local = mesh.vertices[part.vertices]
    start = part.vertices.start

    points = vtkPoints()
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
        append.AddInputData(surface)
        for piece in extra:
            append.AddInputData(piece)
        append.Update()
        surface = append.GetOutput()

    # Merges the duplicate points the triangulated faces bring with them and
    # gives every vertex a normal, so the cylinders shade as cylinders.
    normals = vtkPolyDataNormals()
    normals.SetInputData(surface)
    normals.SetFeatureAngle(FEATURE_ANGLE)
    normals.SplittingOn()
    normals.ConsistencyOn()
    normals.AutoOrientNormalsOff()             # the mesh is already wound out
    normals.ComputePointNormalsOn()
    normals.Update()
    return normals.GetOutput()


def pose_matrix(mesh: Mesh, part: Part, phi: float, explode: float = 0.0):
    """The part's pose at crank angle ``phi`` as (degrees about Z, dx, dy, dz).

    Kept as plain numbers rather than a ``vtkTransform`` so that the motion law
    can be checked without VTK - it is the same law
    :meth:`Mesh.world_vertices` applies, and the two are compared in the tests.
    """
    angle = part.spin * (phi + part.phase)
    if part.orbits:
        dx = mesh.eccentricity * np.cos(phi + part.phase)
        dy = -mesh.eccentricity * np.sin(phi + part.phase)
    else:
        dx = dy = 0.0
    return (np.degrees(angle), float(dx), float(dy),
            explode * part.explode * mesh.explode_span)
