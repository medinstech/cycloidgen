"""Live 3D of the assembled drive: geometry and rendering maths, no Qt.

Split deliberately.  :mod:`~cycloidgen.viz.mesh` turns a spec into polygons and
:mod:`~cycloidgen.viz.scene` turns polygons plus a camera into a sorted, shaded
draw list of 2D screen coordinates.  Neither imports Qt, so both are testable
without a display, and the same draw list is painted by the desktop viewer and
by matplotlib for the PDF report.
"""
from __future__ import annotations

from .mesh import PART_COLOURS, Mesh, Part, build_mesh
from .scene import Camera, DrawList, render

__all__ = ["PART_COLOURS", "Camera", "DrawList", "Mesh", "Part", "build_mesh", "render"]
