"""Camera, projection and face ordering: polygons in, screen polygons out.

There is no depth buffer.  Faces are back-face culled and painted from the back
forward, which is the oldest trick in the book and buys a renderer with no GPU,
no shader, no context to lose on a remote desktop, and a result that can be
checked on a machine with no display at all.

Ordering, in two levels
-----------------------
A single depth sort over every face in the scene is not enough, and the reason
is worth writing down because the note here used to say it was.  The old
argument was that no two parts share space, so nothing can be occluded out of
order.  Not sharing space is not the same as not being *inside* something: the
housing and its end plates enclose the discs, the pins and the shaft, and a
centroid is one number for a face that may span the whole depth of the scene.
The end plate's top face has its centroid at the middle of the drive while the
front ring pins sit nearer than that, so the pins were painted over the lid -
guts visible through a closed gearbox, which is what it looked like.

So the sort is two-level, and each level is chosen for a reason that holds:

* **Within a part, by centroid.**  A convex-ish solid with its back faces
  removed cannot occlude itself out of order, which is the part of the old
  argument that was true.  Measured against a real per-pixel depth buffer, a
  single part on its own comes out at 0.00% disagreement.

* **Between parts, by the nearest point of the part.**  Back-face culling
  leaves a surface that lies entirely in front of whatever that part encloses,
  so its nearest point orders it correctly against its own contents - which is
  exactly the housing-over-the-internals case.

Against a true z-buffer that takes the assembled view from about 9% of pixels
showing the wrong surface to under 2%.  In the *exploded* view it is a wash
either way, because parts pulled apart are no longer nested and there is no
correct part order to find; that is a stated limit rather than a fixed one.  A
per-pixel buffer would settle all of it and costs about sixty times the
projection, which is not a trade this renderer exists to make.

The output is deliberately Qt-free: the desktop viewer paints it with
``QPainter`` and the PDF report draws the same list with matplotlib.
"""
from __future__ import annotations

import math
from collections.abc import Container
from dataclasses import dataclass, replace

import numpy as np

from .mesh import Mesh

__all__ = ["Camera", "DrawList", "render"]


def _unit(v) -> np.ndarray:
    v = np.asarray(v, float)
    n = float(np.linalg.norm(v))
    return v / n if n > 0.0 else v


#: Light direction in *camera* axes (right, up, forward), so it travels with the
#: viewer.  A light fixed in world space is the one that leaves you dragging the
#: model around in the dark looking for the lit side.
_LIGHT = _unit([-0.38, 0.50, -1.0])

#: Elevation is clamped short of the pole: straight down the axis the up vector
#: and the view direction are parallel and the camera basis collapses.
_MAX_ELEVATION = 88.0


@dataclass(frozen=True)
class Camera:
    """An orbit camera.  Immutable - the movement helpers return a new one."""

    target: tuple[float, float, float] = (0.0, 0.0, 0.0)
    azimuth: float = 38.0            # degrees about +Z
    elevation: float = 26.0          # degrees above the XY plane
    distance: float = 240.0
    fov_deg: float = 32.0

    def eye(self) -> np.ndarray:
        az, el = math.radians(self.azimuth), math.radians(self.elevation)
        offset = np.array([math.cos(el) * math.cos(az),
                           math.cos(el) * math.sin(az),
                           math.sin(el)])
        return np.asarray(self.target, float) + self.distance * offset

    def basis(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Right, up and forward, in world coordinates.  Z is up in the world."""
        forward = _unit(np.asarray(self.target, float) - self.eye())
        right = _unit(np.cross(forward, [0.0, 0.0, 1.0]))
        return right, np.cross(right, forward), forward

    def orbited(self, d_azimuth: float, d_elevation: float) -> Camera:
        return replace(
            self, azimuth=(self.azimuth + d_azimuth) % 360.0,
            elevation=float(np.clip(self.elevation + d_elevation,
                                    -_MAX_ELEVATION, _MAX_ELEVATION)))

    def zoomed(self, factor: float, *, span: float = 1.0) -> Camera:
        """Dolly in or out, bounded so the camera cannot end up inside the drive."""
        return replace(self, distance=float(
            np.clip(self.distance * factor, 0.35 * span, 40.0 * span)))

    def panned(self, dx_px: float, dy_px: float, height_px: int) -> Camera:
        """Slide the target across the screen plane by a pixel offset."""
        if height_px <= 0:
            return self
        right, up, _ = self.basis()
        scale = 2.0 * self.distance * math.tan(math.radians(self.fov_deg) / 2.0)
        shift = (-dx_px * right + dy_px * up) * scale / height_px
        return replace(self, target=tuple(np.asarray(self.target, float) + shift))

    @classmethod
    def framing(cls, mesh: Mesh, *, explode: float = 0.0, azimuth: float = 38.0,
                elevation: float = 26.0, fov_deg: float = 32.0,
                margin: float = 1.05) -> Camera:
        """A camera that holds the whole assembly, at any crank angle.

        Fitted to the geometry rather than to a box around it.  Both shortcuts
        are noticeably wrong on a gearbox: a bounding *sphere* is sized by a
        diagonal nothing can be seen across, and the bounding *box* corners
        stick out well beyond a round housing at any azimuth off the axes.
        Either way the drive ends up small in the middle of a panel of
        background.  Projecting the vertices themselves costs a millisecond,
        once, when the design changes.
        """
        points = mesh.sample_world(explode)
        centre = (points.min(axis=0) + points.max(axis=0)) / 2.0
        provisional = cls(target=tuple(centre), azimuth=azimuth,
                          elevation=elevation, fov_deg=fov_deg)
        right, up, forward = provisional.basis()

        rel = points - centre
        half = np.maximum(np.abs(rel @ right), np.abs(rel @ up))
        # A point behind the centre needs less distance, one in front needs
        # more; `- rel @ forward` is that correction.
        needed = half / math.tan(math.radians(fov_deg) / 2.0) - rel @ forward
        return cls(target=tuple(centre), azimuth=azimuth, elevation=elevation,
                   fov_deg=fov_deg, distance=max(margin * float(needed.max()), 1e-6))


@dataclass(frozen=True)
class DrawList:
    """Screen-space polygons, already ordered back to front.

    ``loops[i]`` is one face: its outer boundary first, then any holes, each an
    ``(n, 2)`` array of pixel coordinates.  Holes are wound against the outer
    boundary, so both the odd-even and the non-zero fill rule cut them out - the
    desktop viewer uses one and matplotlib the other.
    """

    loops: list[tuple[np.ndarray, ...]]
    colours: np.ndarray            # (n, 3) uint8, aligned with loops
    parts: np.ndarray              # (n,) index into Mesh.parts
    depths: np.ndarray             # (n,) distance to the face centroid
    size: tuple[int, int]

    def __len__(self) -> int:
        return len(self.loops)


def render(mesh: Mesh, phi: float, camera: Camera, width: int, height: int, *,
           explode: float = 0.0, hidden: Container[str] = (),
           ambient: float = 0.30) -> DrawList:
    """Project ``mesh`` at crank angle ``phi`` into a painter's-order draw list.

    ``hidden`` names part groups *or individual parts* to leave out.  Hiding the
    housing is the first thing anyone does with a gearbox viewer, and that is a
    group; but "the bearings" is not one thing you want to see or not see - the
    cam bearing sits inside a bore and the shaft supports sit out in the open,
    and looking at one usually means putting the others away.  Both live in the
    same set because a part and a group can never share a name.
    """
    world = mesh.world_vertices(phi, explode)
    eye = camera.eye()
    right, up, forward = camera.basis()

    rel = world - eye
    depth = rel @ forward
    near = max(camera.distance * 1e-3, 1e-9)
    focal = 0.5 * height / math.tan(math.radians(camera.fov_deg) / 2.0)

    v0 = world[mesh.normal_ref[:, 0]]
    edge_a = world[mesh.normal_ref[:, 1]] - v0
    edge_b = world[mesh.normal_ref[:, 2]] - v0
    normals = np.cross(edge_a, edge_b)
    lengths = np.linalg.norm(normals, axis=1)
    normals = normals / np.maximum(lengths, 1e-12)[:, None]

    keep = ((normals * (v0 - eye)).sum(axis=1) < 0.0) & (lengths > 1e-12)
    if hidden:
        shown = np.array([p.group not in hidden and p.name not in hidden
                          for p in mesh.parts])
        keep &= shown[mesh.facet_part]

    # Depth per face, and rejection of anything crossing the near plane.  Both
    # are one pass over the flattened outer loops: a Python loop over a few
    # thousand faces on every frame is the difference between an animation and a
    # slideshow.
    flat = depth[mesh.outer_flat]
    near_depth = np.minimum.reduceat(flat, mesh.outer_starts)
    keep &= near_depth > near
    centre_depth = np.add.reduceat(flat, mesh.outer_starts) / mesh.outer_counts

    order = np.flatnonzero(keep)
    # Two-level sort - see the module docstring for why one level is not enough.
    # The part key is computed over the faces that survived culling, because a
    # part is ordered by the surface it is actually showing rather than by the
    # side of it facing away.
    part_near = np.full(len(mesh.parts), np.inf)
    np.minimum.at(part_near, mesh.facet_part[order], near_depth[order])
    # lexsort takes the primary key last: parts furthest away first, and inside
    # each part the faces furthest away first.
    order = order[np.lexsort((-centre_depth[order],
                              -part_near[mesh.facet_part[order]]))]

    inverse = focal / np.maximum(depth, near)
    screen = np.column_stack([0.5 * width + (rel @ right) * inverse,
                              0.5 * height - (rel @ up) * inverse])

    facing = np.column_stack([normals @ right, normals @ up, normals @ forward])
    intensity = ambient + (1.0 - ambient) * np.clip(facing @ _LIGHT, 0.0, 1.0)
    base = np.array([p.colour for p in mesh.parts], float)[mesh.facet_part]
    colours = np.clip(base * intensity[:, None], 0.0, 255.0).astype(np.uint8)

    return DrawList(
        loops=[tuple(screen[loop] for loop in mesh.loops[i]) for i in order],
        colours=colours[order],
        parts=mesh.facet_part[order],
        depths=centre_depth[order],
        size=(width, height),
    )
