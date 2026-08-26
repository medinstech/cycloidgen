"""Polygon meshes of the assembled drive, built in plain numpy.

Why not tessellate the CadQuery solids?  Two reasons, and both matter.  The
first is that the viewer has to work in a build without OCCT: the
drawings-and-report path already does, and a 3D tab that dragged a 1.2 GB kernel
in behind it would quietly undo that.  The second is drift.  A mesh generated
from the same closed-form profile the drawing uses cannot disagree with the
drawing; a tessellation of a separately-built solid can, and the disagreement
would show up as a picture that is subtly not the part you are exporting.

Polygons, not triangles
-----------------------
The renderer is a painter's-algorithm rasteriser, so a face costs one draw call
whatever its vertex count.  A disc end face with its bore and six output holes
is *one* call as a polygon-with-holes and would be several hundred as triangles.
That is the whole reason the mesh keeps faces as loops.

Winding
-------
Every loop is stored counter-clockwise seen from +Z.  Side-wall quads built from
a counter-clockwise loop come out with their normals pointing away from the
material, which is what lets the renderer cull back faces instead of needing a
depth buffer.  Hole loops are reversed where they are *drawn* so that both the
odd-even and the non-zero fill rule punch a hole rather than filling it in.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass

import numpy as np

from ..analysis.bearings import (
    BearingPlacement,
    pin_shank_diameter,
    placements_for_spec,
)
from ..core import profile as prof
from ..core.spec import CARRIER_DROP, GearSpec

__all__ = [
    "EDGE_SHADE",
    "PART_COLOURS",
    "PART_GROUPS",
    "TIE_BOLT_NOMINAL",
    "Mesh",
    "Part",
    "build_mesh",
    "mesh_fingerprint",
    "mesh_for_spec",
    "placements_for_spec",
    "pocketed_bore",
]

#: One palette for the parts, shared with the STEP assembly in
#: :mod:`cycloidgen.export.solid`.  The viewer and the exported file are meant to
#: be recognisably the same gearbox; two hand-written colour lists would not stay
#: that way.
PART_COLOURS: dict[str, tuple[int, int, int]] = {
    "housing": (166, 166, 179),
    "ring_pins": (217, 140, 38),
    "discs": (77, 166, 217),
    "shaft": (115, 115, 128),
    "carrier": (140, 191, 115),
    "bearings": (150, 128, 200),
    "end_plates": (140, 140, 156),
    "fasteners": (92, 92, 102),
}

#: How dark a part's drawn edges are, as a fraction of the part's own colour.
#:
#: An edge belongs to the part, not to the window: it is the line a shaded
#: drawing puts round a face, and drawing it in the *theme's* ink instead made
#: the dark theme paint pure white haloes round every ring pin.  Taking it from
#: the part means one rule that needs no theme, and it is the rule the software
#: painter already followed - the two renderers were disagreeing about this,
#: which is exactly the kind of drift a shared constant is for.
#:
#: Darker than the 0.62 a section cap uses, so an edge still reads where it
#: crosses one.
EDGE_SHADE = 0.45

#: A tie bolt's shank against the clearance hole it passes through.  The hole is
#: the design's number and the bolt is what goes in it: drawn at the hole size a
#: bolt fills it exactly, which is a press fit and not what anybody ordered.
TIE_BOLT_NOMINAL = 0.88

#: Human names for the visibility toggles, in assembly order.
#:
#: The end plates are their own group rather than more of the housing, for two
#: reasons that happen to agree.  Taking the covers off to look inside is a
#: different thing from taking the barrel away, so it wants its own switch.  And
#: a group of several parts must not share its name with one of them - the
#: renderer takes groups and part names in one set - which is what would have
#: happened if the plates had joined "housing".
PART_GROUPS: tuple[tuple[str, str], ...] = (
    ("housing", "Housing"),
    ("end_plates", "End plates"),
    ("ring_pins", "Ring pins"),
    ("discs", "Discs"),
    ("shaft", "Shaft"),
    ("carrier", "Carrier"),
    ("bearings", "Bearings"),
    ("fasteners", "Tie bolts"),
)

#: How far each group travels in an exploded view, as a multiple of the explode
#: distance.  Assembly order along the axis: the carrier comes off the bottom,
#: the shaft pulls out of the top, the discs come out in between.  A stack gets
#: one step per disc, so a two-disc drive comes apart as two discs and not as
#: one thicker one.
#: A bearing has no entry of its own: it travels with the part it turns with, so
#: that a cam bearing comes off in its disc's bore rather than being left behind
#: on the shaft, which is neither where it is pressed nor where it would go.
_EXPLODE = {"carrier": -1.0, "housing": 0.0, "ring_pins": 0.62,
            "discs": 1.25, "shaft": 2.6, "bearings": 0.0, "end_plates": 0.0,
            # Out along their own axis, which is how a drawing pulls a bolt.
            "fasteners": 3.2}
_EXPLODE_PER_DISC = 0.45

#: Segments on a bearing ring.  The floor matters more than it looks: both loops
#: of a ring are inscribed polygons, so the faceting error does *not* cancel
#: between them, and the enclosed volume is short by the same fraction a solid
#: cylinder would be.  Twenty sides keeps that inside the 3% the mesh is checked
#: against the exported solid at.
_BEARING_SEGMENTS = (20, 28)

#: And the same arithmetic for a tie bolt, which is a plain cylinder: an
#: inscribed twelve-sided prism encloses 4.5% less than the bolt it stands for,
#: which is past the 3% the mesh is held to against the exported solid.  There
#: are only a handful of them, so this is cheap.
_BOLT_SEGMENTS = 24


# --------------------------------------------------------------------- loops --


def _signed_area(pts: np.ndarray) -> float:
    x, y = pts[:, 0], pts[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _ccw(pts: np.ndarray) -> np.ndarray:
    """Force a loop counter-clockwise, which is the convention everything else assumes."""
    return pts if _signed_area(pts) > 0.0 else pts[::-1].copy()


def _circle(cx: float, cy: float, r: float, segments: int) -> np.ndarray:
    a = np.linspace(0.0, 2.0 * np.pi, segments, endpoint=False)
    return np.column_stack([cx + r * np.cos(a), cy + r * np.sin(a)])


def pocketed_bore(R: float, Rr: float, count: int, *,
                  bore_segments: int = 5, pocket_segments: int = 9,
                  integral: bool = False) -> np.ndarray:
    """The housing bore, with the ring pins cut out of it or grown into it.

    The pins sit half-embedded in the bore, so a plain circular bore would pass
    through them.  Two solids occupying the same space is not just wrong, it is
    *visibly* wrong: with no depth buffer the renderer decides which of two
    coincident surfaces is in front by comparing face centroids, and the answer
    flickers as the model turns.  Cutting the real pockets removes the overlap
    instead of trying to arbitrate it.

    The pin circle meets the bore circle at ``+-beta`` from the pin's own angle,
    where ``2*R^2*(1 - cos beta) == Rr^2``; between those two points the boundary
    follows the pin outward, and between pins it follows the bore.

    With ``integral`` the pins are the housing rather than parts fitted into it,
    and the boundary takes the *other* arc between the same two points - the one
    bulging inward, which is the half of the pin that stood proud of the pocket.
    Same circle, same intersections, the complementary side of each: a pocket
    and the pin that fills it are one shape described from either side.
    """
    pitch = 2.0 * np.pi / count
    cos_beta = 1.0 - Rr * Rr / (2.0 * R * R)
    if cos_beta <= -1.0:
        return _circle(0.0, 0.0, R + Rr, 96)
    beta = math.acos(min(1.0, cos_beta))
    if 2.0 * beta >= pitch:
        # Pockets that reach into each other are not a bore any more.  The
        # design is already flagged (PIN_OVERLAP) and the user is probably
        # mid-drag; draw a bore clear of the pins rather than a self-crossing
        # loop the renderer would make nonsense of.
        return _circle(0.0, 0.0, R + Rr, 96)

    # Entry and exit angles of the pocket arc, in the pin's own frame.  Both
    # land past +-pi/2 because the bore cuts slightly more than half the pin
    # away, and sweeping from the negative one *upwards* is the half that bulges
    # outward - the material side.
    theta = math.atan2(R * math.sin(beta), R * (math.cos(beta) - 1.0))

    pieces: list[np.ndarray] = []
    for k in range(count):
        a = pitch * k
        # Both arcs start at the intersection ``a - beta`` and end at
        # ``a + beta``, which is what keeps the loop continuous and wound the
        # same way; they differ in which side of the pin they go round.  Local
        # 0 is radially outward, so sweeping up through it takes the outward
        # half and sweeping down through -pi takes the inward one.
        local = (np.linspace(-theta, theta - 2.0 * math.pi, pocket_segments)
                 if integral else np.linspace(-theta, theta, pocket_segments))
        pocket = np.column_stack([Rr * np.cos(local), Rr * np.sin(local)])
        c, s = math.cos(a), math.sin(a)
        pieces.append(pocket @ np.array([[c, s], [-s, c]]) + [R * c, R * s])

        span = np.linspace(a + beta, a + pitch - beta, bore_segments)
        pieces.append(R * np.column_stack([np.cos(span), np.sin(span)]))
    return _without_repeats(np.vstack(pieces))


def _without_repeats(loop: np.ndarray, snap: float = 1e-9) -> np.ndarray:
    """Drop a point that stands where the one before it already stands.

    The pocket arc and the bore arc meet at the intersection, and each computes
    that point for itself: the same point to fourteen decimal places and not to
    the fifteenth.  Twice per pin, so a 21:1 bore carried forty-four of them.

    Geometrically they cost nothing, which is why they went unnoticed.  What
    they cost is *edges*: a segment with no length has no direction, so the wall
    above it is a quad of no area and the cap's boundary runs through a corner
    that is not one.  Whether that survives being merged back together is then
    up to whoever built the mesh library - VTK 9.6 keeps the two points apart
    and 9.3 does not, and the second one leaves a hole in the housing for every
    pin.  Two points that are the same point should be one point.
    """
    keep = np.ones(len(loop), dtype=bool)
    previous = 0
    for i in range(1, len(loop)):
        if abs(loop[i, 0] - loop[previous, 0]) < snap \
                and abs(loop[i, 1] - loop[previous, 1]) < snap:
            keep[i] = False
        else:
            previous = i
    if len(loop) > 1 and abs(loop[previous, 0] - loop[0, 0]) < snap \
            and abs(loop[previous, 1] - loop[0, 1]) < snap:
        keep[previous] = False              # and where the loop closes
    return loop[keep]


# ---------------------------------------------------------------------- mesh --


@dataclass(frozen=True)
class Part:
    """One rigid body, its slice of the mesh, and how it moves with the crank.

    All motion in a cycloidal drive is planar: a rotation about Z and, for the
    discs, a centre that walks a circle of radius E.  ``spin`` is the rotation
    per radian of crank angle and ``phase`` is where this part sits in the
    stack, so ``angle = spin * (phi + phase)``.
    """

    name: str
    label: str
    group: str
    colour: tuple[int, int, int]
    vertices: slice
    facets: slice
    spin: float = 0.0
    phase: float = 0.0
    orbits: bool = False
    explode: float = 0.0


@dataclass(frozen=True)
class Mesh:
    """Every part of one design as loops of vertex indices.

    ``vertices`` are in each part's *local* frame; :meth:`world_vertices` puts
    them where the crank angle says they belong.  The flattened outer-loop
    arrays exist so that per-face depth and near-plane rejection are one
    ``reduceat`` each rather than a Python loop over a few thousand faces.
    """

    vertices: np.ndarray                        # (V, 3)
    loops: tuple[tuple[np.ndarray, ...], ...]   # per face: outer loop, then holes
    facet_part: np.ndarray                      # (F,) index into parts
    normal_ref: np.ndarray                      # (F, 3) three vertices spanning the face
    outer_flat: np.ndarray                      # every outer loop, concatenated
    outer_starts: np.ndarray                    # (F,) where each starts in outer_flat
    outer_counts: np.ndarray                    # (F,)
    parts: tuple[Part, ...]
    eccentricity: float
    explode_span: float
    #: Rotation added to the *whole* assembly per radian of crank angle, so that
    #: the grounded member is the one standing still on screen.
    #:
    #: Every part's own ``spin`` is stated in the frame the geometry is built
    #: in, which is the one the ring housing sits still in.  That is right for a
    #: carrier-output drive and wrong for a ring-output one by exactly one rigid
    #: rotation - so this is that rotation, applied once at the end, rather than
    #: a second set of spins that would have to be kept in step with the first.
    #: It falls out that the orbit gets it too, which it must: relative to a
    #: grounded carrier the disc's centre still walks a circle, but the circle
    #: is walked at a different rate and from a turning frame.
    frame_spin: float = 0.0

    @property
    def facet_count(self) -> int:
        return len(self.loops)

    def world_vertices(self, phi: float = 0.0, explode: float = 0.0) -> np.ndarray:
        """Place every part for crank angle ``phi`` (radians).

        ``explode`` is a fraction: 1.0 pulls the assembly apart by
        :attr:`explode_span`, which is scaled off the drive so the same slider
        works for a 40 mm drive and a 200 mm one.
        """
        out = np.empty_like(self.vertices)
        for p in self.parts:
            local = self.vertices[p.vertices]
            angle = p.spin * (phi + p.phase) + self.frame_spin * phi
            c, s = math.cos(angle), math.sin(angle)
            xy = local[:, :2] @ np.array([[c, -s], [s, c]]).T
            if p.orbits:
                # The orbit offset is a vector in the built frame, so it turns
                # with the frame as well - added before the frame rotation
                # rather than after, which is what taking the whole angle above
                # would have done to it.
                orbit = phi + p.phase
                off = np.array([self.eccentricity * math.cos(orbit),
                                -self.eccentricity * math.sin(orbit)])
                f = self.frame_spin * phi
                cf, sf = math.cos(f), math.sin(f)
                xy = xy + np.array([cf * off[0] - sf * off[1],
                                    sf * off[0] + cf * off[1]])
            out[p.vertices, :2] = xy
            out[p.vertices, 2] = local[:, 2] + explode * p.explode * self.explode_span
        return out

    def sample_world(self, explode: float = 0.0, steps: int = 5) -> np.ndarray:
        """Every vertex at several crank angles.

        Framing and sizing both want "how big does this get while it turns",
        not "how big is it right now" - otherwise the view creeps as the
        eccentric comes round.
        """
        return np.vstack([self.world_vertices(a, explode)
                          for a in np.linspace(0.0, 2.0 * np.pi, steps,
                                               endpoint=False)])

    def bounds(self, explode: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
        """Axis-aligned box over a whole revolution, so framing does not jitter."""
        pts = self.sample_world(explode)
        return pts.min(axis=0), pts.max(axis=0)


class _Builder:
    """Accumulates vertices and faces, one part at a time."""

    def __init__(self) -> None:
        self._blocks: list[np.ndarray] = []
        self._loops: list[tuple[np.ndarray, ...]] = []
        self._facet_part: list[int] = []
        self._n = 0
        self._current = -1
        self.parts: list[Part] = []

    @contextmanager
    def part(self, name: str, label: str, group: str,
             colour: tuple[int, int, int], explode: float | None = None, **motion):
        v0, f0 = self._n, len(self._loops)
        self._current = len(self.parts)
        yield
        self.parts.append(Part(name=name, label=label, group=group, colour=colour,
                               vertices=slice(v0, self._n),
                               facets=slice(f0, len(self._loops)),
                               explode=_EXPLODE[group] if explode is None else explode,
                               **motion))

    def _points(self, xy: np.ndarray, z: float) -> np.ndarray:
        block = np.empty((len(xy), 3))
        block[:, :2] = xy
        block[:, 2] = z
        self._blocks.append(block)
        index = np.arange(self._n, self._n + len(xy), dtype=np.int32)
        self._n += len(xy)
        return index

    def facet(self, *loops: np.ndarray) -> None:
        self._loops.append(tuple(np.ascontiguousarray(lp, dtype=np.int32)
                                 for lp in loops))
        self._facet_part.append(self._current)

    def cap(self, outer: np.ndarray, holes, z: float, *, up: bool) -> None:
        """One face in the plane ``z`` with any number of holes, normal +Z when
        ``up``.

        For the exposed part of a face where two stacked prisms meet: the rest
        of it is inside the solid and must not be emitted, or four faces end up
        sharing the ring where they touch.  It takes *holes* rather than one
        inner loop because what a prism is capped by is not always an annulus -
        the base of a ring-output carrier is covered by the boss standing on it
        and pierced by the motor's bolts, and a cap that only knew about the
        boss left every one of those bolt holes open at the top.
        """
        o = self._points(_ccw(np.asarray(outer, float)), z)
        h = [self._points(_ccw(np.asarray(loop, float)), z) for loop in holes]
        if up:
            self.facet(o, *[loop[::-1] for loop in h])
        else:
            self.facet(o[::-1], *h)

    def ring(self, outer: np.ndarray, inner: np.ndarray, z: float, *,
             up: bool) -> None:
        """:meth:`cap` with the one hole that is usually all it takes."""
        self.cap(outer, (inner,), z, up=up)

    def prism(self, outer: np.ndarray, holes, z0: float, z1: float, *,
              cap_bottom: bool = True, cap_top: bool = True) -> None:
        """Extrude a polygon with holes between two planes.

        A cap can be left off where this prism is stacked on another and the
        face between them is interior to the union.  Leaving one on is not a
        cosmetic error - it is a wall inside the solid, and a solid with a wall
        inside it is not closed, which is what the section has to cap.
        """
        loops = [_ccw(np.asarray(outer, float))]
        loops += [_ccw(np.asarray(h, float)) for h in holes]
        bottom = [self._points(lp, z0) for lp in loops]
        top = [self._points(lp, z1) for lp in loops]

        # End caps.  Reversing the outer loop on the bottom face turns its
        # normal to -Z; the holes are then wound the other way from whichever
        # boundary they sit inside.
        if cap_bottom:
            self.facet(bottom[0][::-1], *bottom[1:])
        if cap_top:
            self.facet(top[0], *[h[::-1] for h in top[1:]])

        for i in range(len(loops)):
            b, t = bottom[i], top[i]
            if i:                          # a hole's wall faces into the hole
                b, t = b[::-1], t[::-1]
            nxt = np.roll(np.arange(len(b)), -1)
            for quad in np.column_stack([b, b[nxt], t[nxt], t]):
                self.facet(quad)

    def cylinder(self, cx: float, cy: float, r: float, z0: float, z1: float,
                 segments: int) -> None:
        self.prism(_circle(cx, cy, r, segments), (), z0, z1)

    def build(self, spec: GearSpec) -> Mesh:
        outer = [lp[0] for lp in self._loops]
        counts = np.array([len(o) for o in outer], dtype=np.int32)
        starts = np.zeros(len(counts), dtype=np.int32)
        np.cumsum(counts[:-1], out=starts[1:])
        return Mesh(
            vertices=np.vstack(self._blocks),
            loops=tuple(self._loops),
            facet_part=np.array(self._facet_part, dtype=np.int32),
            # Three vertices spread around the loop rather than three adjacent
            # ones: on a finely sampled profile, neighbours are nearly collinear
            # and the cross product of two almost-parallel edges is noise.
            normal_ref=np.array([[o[0], o[len(o) // 3], o[2 * len(o) // 3]]
                                 for o in outer], dtype=np.int32),
            outer_flat=np.concatenate(outer).astype(np.int32),
            outer_starts=starts,
            outer_counts=counts,
            parts=tuple(self.parts),
            eccentricity=spec.eccentricity,
            explode_span=spec.stack_height + spec.output_flange_thickness + 14.0,
            frame_spin=spec.frame_spin,
        )


# ------------------------------------------------------------------- builders --


def _tint(colour: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(int(np.clip(round(c * factor), 0, 255)) for c in colour)  # type: ignore[return-value]


def _subtract_spans(spans, cuts, *, eps: float = 1e-9):
    """Remove ``cuts`` from a list of ``(z0, z1)`` intervals."""
    for c0, c1 in cuts:
        kept = []
        for z0, z1 in spans:
            if c1 <= z0 or c0 >= z1:
                kept.append((z0, z1))
                continue
            if z0 < c0 - eps:
                kept.append((z0, c0))
            if c1 + eps < z1:
                kept.append((c1, z1))
        spans = kept
    return spans


def _profile_segments(spec: GearSpec) -> int:
    """Enough samples that the lobes read as lobes, capped so 200:1 still draws.

    Unlike the DXF this is a picture, so the chord tolerance that governs the
    exported geometry is the wrong criterion - a screen pixel is the right one,
    and eight points per lobe is comfortably inside it at any sane zoom.
    """
    return int(np.clip(8 * spec.lobes, 160, 520))


def tie_bolt_holes(spec: GearSpec) -> list[np.ndarray]:
    """The tie-bolt circle, as loops to cut.

    Used by the barrel as well as by the plates, which is the point of it being
    a function.  The bill of materials orders these bolts and both end plates
    were drilled for them; the barrel they clamp was not, so the drive exported
    as a stack of parts that could not be bolted together.
    """
    r = spec.housing_bolt_diameter / 2.0
    return [_circle(spec.housing_bolt_radius * math.cos(a),
                    spec.housing_bolt_radius * math.sin(a), r, 12)
            for a in (2.0 * np.pi * k / max(spec.housing_bolt_count, 1)
                      for k in range(spec.housing_bolt_count))]


def motor_bolt_holes(spec: GearSpec) -> list[np.ndarray]:
    """A motor's bolt pattern, as loops to cut.

    NEMA patterns are a *square*.  Drawing them on a circle of the same size
    puts all four holes somewhere the motor has nothing, which would look
    entirely plausible and be entirely wrong.

    A function rather than four lines inside the plate builder because the
    pattern moves: it is cut into the input end plate on a carrier-output drive
    and into the carrier's own base on a ring-output one, and it has to be the
    same pattern in both places.
    """
    if not spec.has_motor_face:
        return []
    frame = spec.motor_face
    rb = frame.bolt_diameter / 2.0
    if frame.square:
        half = frame.bolt_span / 2.0
        return [_circle(sx * half, sy * half, rb, 12)
                for sx in (-1.0, 1.0) for sy in (-1.0, 1.0)]
    return [_circle(frame.bolt_span / 2.0 * math.cos(a),
                    frame.bolt_span / 2.0 * math.sin(a), rb, 12)
            for a in (2.0 * np.pi * k / max(frame.bolt_count, 1)
                      for k in range(frame.bolt_count))]


def output_face_bolt_holes(spec: GearSpec) -> list[np.ndarray]:
    """What a driven machine bolts to on a turning housing, as loops to cut.

    Empty unless the ring is the output member: on a carrier-output drive the
    interface is the boss on the axis and this face carries the motor instead.
    """
    if not spec.ground_frame_fitted or not spec.output_bolt_count:
        return []
    r = spec.output_bolt_diameter / 2.0
    return [_circle(spec.output_face_bolt_radius * math.cos(a),
                    spec.output_face_bolt_radius * math.sin(a), r, 12)
            for a in (spec.output_bolt_phase + 2.0 * np.pi * k / spec.output_bolt_count
                      for k in range(spec.output_bolt_count))]


def _plate_bolt_holes(spec: GearSpec, motor_face: bool) -> list[np.ndarray]:
    """Every hole through an end plate: the tie bolts, and whichever pattern the
    outside face carries.

    ``motor_face`` marks the input-side plate.  Which pattern goes in it is the
    spec's answer and not this argument's: the motor's when the housing is
    bolted down, the driven machine's when the housing is what turns.
    """
    holes = tie_bolt_holes(spec)
    if not motor_face:
        return holes
    if spec.ground_frame_fitted:
        return holes + output_face_bolt_holes(spec)
    return holes + motor_bolt_holes(spec)


def _pilot_recess(spec: GearSpec, bore: float) -> float:
    """How deep the motor's register is cut, or zero when the bore is already it.

    A spigot no bigger than the hole it goes into needs no recess: the bore is
    the register.  That is the default here rather than a contrivance - a NEMA
    17 pilots at 22 mm and the shaft support seat happens to be 22 mm too.

    Zero as well wherever the motor is not: on a ring-output drive the face this
    is asked about turns, and a register in it would centre nothing.
    """
    if not spec.has_motor_face or spec.motor_face.pilot_diameter <= bore:
        return 0.0
    return min(spec.motor_face.pilot_depth, spec.plate_thickness / 2.0)


def build_mesh(spec: GearSpec,
               placements: Sequence[BearingPlacement] | None = None) -> Mesh:
    """Every part of ``spec`` as a polygon mesh, in assembly order.

    ``placements`` is worked out from the spec when it is not supplied; passing
    it in is how :func:`mesh_for_spec` avoids sizing the bearings twice.
    """
    if placements is None:
        placements = placements_for_spec(spec)
    b = _Builder()
    stack = spec.stack_height
    # Ring pins are small and there are a lot of them, so the segment count is
    # spent where it shows: a twelve-sided pin still reads as round, and a
    # ten-sided one is visibly a nut.  The floor is what stops a 200:1 drive
    # from turning its two hundred pins into the entire frame budget.
    pin_segments = int(np.clip(560 // max(spec.pin_count, 1), 12, 24))

    with b.part("housing", "Ring housing", "housing", PART_COLOURS["housing"]):
        # Down past the disc stack to cover the carrier and land on the output
        # end plate, and up past it to cover the end cap where there is one:
        # the barrel is what the two plates bolt to, so it has to reach both of
        # them, and it is what the frame turns inside.  The pockets run its
        # whole length, which is what a bore broached in one setup looks like
        # and is why this is one prism.
        b.prism(_circle(0.0, 0.0, spec.housing_outer_radius, 96),
                (pocketed_bore(spec.pin_circle_radius, spec.pin_radius,
                               spec.pin_count,
                               integral=spec.ring_pins_integral),
                 *tie_bolt_holes(spec)),
                spec.barrel_bottom, spec.barrel_top)

    # A pin carrying a roller loses its outside to it - drawn at full size it
    # would be inside its own sleeve.
    pin_r = pin_shank_diameter(placements, "bearing_ring_pins",
                               2.0 * spec.pin_radius) / 2.0

    # The pockets run the barrel's whole length, so the pins do too: they are
    # held up by the input end plate and stopped by the output one, and a pin
    # cut to the disc stack has seven millimetres of empty groove to fall into.
    #
    # Nothing to draw when they are integral: the bore above already has them,
    # and a part with no facets in it would still reach the bill of materials
    # and the visibility row as a thing you could order and switch off.
    if not spec.ring_pins_integral:
        with b.part("ring_pins", "Ring pins", "ring_pins",
                    PART_COLOURS["ring_pins"]):
            for k in range(spec.pin_count):
                a = 2.0 * np.pi * k / spec.pin_count
                b.cylinder(spec.pin_circle_radius * math.cos(a),
                           spec.pin_circle_radius * math.sin(a),
                           pin_r, spec.barrel_bottom, spec.barrel_top,
                           pin_segments)

    outline = prof.profile_from_spec(spec, n=_profile_segments(spec)).points
    bore_r = (spec.center_bore_diameter + spec.hole_clearance) / 2.0
    hole_r = spec.output_hole_diameter / 2.0
    z = 0.0
    for i, (phase, hole_phase) in enumerate(zip(spec.disc_phases,
                                                spec.disc_hole_phases,
                                                strict=True)):
        holes = [_circle(0.0, 0.0, bore_r, 32)]
        for k in range(spec.output_pin_count):
            a = 2.0 * np.pi * k / spec.output_pin_count + hole_phase
            holes.append(_circle(spec.output_bolt_circle_radius * math.cos(a),
                                 spec.output_bolt_circle_radius * math.sin(a),
                                 hole_r, 24))
        # Each disc a shade lighter than the one below it.  They sit on
        # different crank phases and are different parts; a stack painted in one
        # flat colour reads as a single thick disc.
        label = f"Disc {i + 1}" if spec.disc_count > 1 else "Disc"
        with b.part(f"disc_{i + 1}", label, "discs",
                    _tint(PART_COLOURS["discs"], 1.0 - 0.16 * i),
                    explode=_EXPLODE["discs"] + _EXPLODE_PER_DISC * i,
                    spin=1.0 / spec.lobes, phase=phase, orbits=True):
            b.prism(outline, holes, z, z + spec.disc_thickness)
        z += spec.disc_thickness + spec.disc_gap

    # The shaft turns *backwards* against the crank angle: the disc centre runs
    # to (E cos phi, -E sin phi), which is a clockwise walk, so the cam that
    # carries it has to be rotated by -phi.
    cams = []
    z = 0.0
    for phase in spec.disc_phases:
        cams.append((z, z + spec.disc_thickness, phase))
        z += spec.disc_thickness + spec.disc_gap

    # A cam wide enough to swallow the shaft leaves the shaft's own barrel
    # inside solid metal, where it is both invisible and counted twice by
    # anything that measures the mesh.  Cut those spans out.  When the cam is
    # only just larger than the shaft - `cam_diameter` falls back to
    # `input_shaft_diameter + 2` - the shaft pokes out of it and the barrel is
    # real geometry, so the test has to be made and not assumed.
    shaft_r = spec.input_shaft_diameter / 2.0
    cam_r = spec.cam_diameter / 2.0
    spans = [(-spec.shaft_overhang, stack + spec.shaft_overhang)]
    if cam_r >= shaft_r + spec.eccentricity:
        spans = _subtract_spans(spans, [(z0, z1) for z0, z1, _ in cams])

    with b.part("eccentric_shaft", "Eccentric shaft", "shaft",
                PART_COLOURS["shaft"], spin=-1.0):
        for z0, z1 in spans:
            b.cylinder(0.0, 0.0, shaft_r, z0, z1, 28)
        for z0, z1, phase in cams:
            b.cylinder(spec.eccentricity * math.cos(phase),
                       -spec.eccentricity * math.sin(phase), cam_r, z0, z1, 32)

    # A carrier drop below the disc stack, exactly as the STEP assembly places
    # it: a carrier face flush with the first disc would be two surfaces at the
    # same height, which is a fight the renderer cannot win.
    drop = CARRIER_DROP
    plate_r = spec.output_bolt_circle_radius + spec.output_pin_diameter
    hub_r = spec.hub_diameter / 2.0
    bore_r = spec.hub_bore / 2.0
    plate_bottom = -drop - spec.output_flange_thickness
    with b.part("output_flange", "Output carrier", "carrier",
                PART_COLOURS["carrier"], spin=1.0 / spec.lobes):
        # The plate and the boss below it are one part, and where they meet
        # only the ring outside the boss is a surface of it.  Emitting both
        # touching faces put four of them on the bore circle - the plate's
        # underside, the boss's top, and the two halves of the bore wall - and
        # a solid with an internal wall cannot be capped by the section.
        b.prism(_circle(0.0, 0.0, plate_r, 72),
                (_circle(0.0, 0.0, bore_r, 28),), plate_bottom, -drop,
                cap_bottom=False)
        b.ring(_circle(0.0, 0.0, plate_r, 72), _circle(0.0, 0.0, hub_r, 40),
               plate_bottom, up=False)
        # The boss the drive turns on: the output bearing rides its outside and
        # a shaft support sits in its bore.  Its top is inside the plate, and so
        # is its bottom whenever there is a base under it.
        boss_bottom = spec.boss_bottom
        b.prism(_circle(0.0, 0.0, hub_r, 40), (_circle(0.0, 0.0, bore_r, 28),),
                boss_bottom, plate_bottom, cap_top=False,
                cap_bottom=not spec.ground_frame_fitted)
        if spec.ground_frame_fitted:
            # The base the gearbox is bolted down by, on the end of the boss.
            # Housing-sized, because it is the face of the machine at that end
            # and because a NEMA pattern needs the width.
            base_outer = _circle(0.0, 0.0, spec.housing_outer_radius, 96)
            motor_holes = motor_bolt_holes(spec)
            floor = spec.base_plate_bottom
            recess = _pilot_recess(spec, spec.hub_bore)
            if recess:
                # Two prisms, and the step between them emitted only where it is
                # actually exposed: the recess is wider than the bore, so all
                # that shows is the ring between the two.  Capping both prisms
                # instead would bury a wall inside the solid, and a solid with a
                # wall inside it is not something the section plane can cap.
                pilot = _circle(0.0, 0.0, spec.motor_face.pilot_diameter / 2.0, 48)
                b.prism(base_outer, (pilot, *motor_holes), floor, floor + recess,
                        cap_top=False)
                b.ring(pilot, _circle(0.0, 0.0, bore_r, 28), floor + recess,
                       up=False)
                floor += recess
            b.prism(base_outer, (_circle(0.0, 0.0, bore_r, 28), *motor_holes),
                    floor, boss_bottom, cap_top=False,
                    cap_bottom=not recess)
            # The base's top: covered by the boss standing on it, and pierced by
            # the motor's bolts, which pass right through and so are open at
            # this end too.
            b.cap(base_outer, (_circle(0.0, 0.0, hub_r, 40), *motor_holes),
                  boss_bottom, up=True)
        shank = pin_shank_diameter(placements, "bearing_output_pins",
                                   spec.output_pin_diameter)
        # Up to the top of the stack, not up by the height of it: the pin leaves
        # the carrier face a drop below the first disc, so a stack-high pin stops
        # a drop short of the last one.  With a frame it carries on through the
        # end cap, which is what makes it a beam.
        for k in range(spec.output_pin_count):
            a = 2.0 * np.pi * k / spec.output_pin_count
            b.cylinder(spec.output_bolt_circle_radius * math.cos(a),
                       spec.output_bolt_circle_radius * math.sin(a),
                       shank / 2.0, -drop, -drop + spec.output_pin_length, 20)

    # The end cap: the carrier's mirror image at the far end of those pins, and
    # the reason they are pins in a frame rather than a cantilever.  Its own
    # part, because it comes off in an exploded view the way the carrier does -
    # and off the *other* way, since that is the direction it is assembled from.
    if spec.ground_frame_fitted:
        cap_r = plate_r
        cap_hub_r = spec.hub_diameter / 2.0
        cap_bore = _circle(0.0, 0.0, bore_r, 28)
        pin_holes = [
            _circle(spec.output_bolt_circle_radius * math.cos(a),
                    spec.output_bolt_circle_radius * math.sin(a),
                    (shank + spec.hole_clearance) / 2.0, 20)
            for a in (2.0 * np.pi * k / spec.output_pin_count
                      for k in range(spec.output_pin_count))]
        with b.part("end_cap", "End cap", "carrier",
                    _tint(PART_COLOURS["carrier"], 0.86),
                    explode=-_EXPLODE["carrier"],
                    spin=1.0 / spec.lobes):
            b.prism(_circle(0.0, 0.0, cap_r, 72), (cap_bore, *pin_holes),
                    spec.end_cap_bottom, spec.end_cap_top, cap_top=False)
            # The boss stands on it, so only the ring outside the boss is a
            # surface of this plate - and the pin holes are open through it.
            b.cap(_circle(0.0, 0.0, cap_r, 72),
                  (_circle(0.0, 0.0, cap_hub_r, 40), *pin_holes),
                  spec.end_cap_top, up=True)
            b.prism(_circle(0.0, 0.0, cap_hub_r, 40), (cap_bore,),
                    spec.end_cap_top, spec.cap_boss_top, cap_bottom=False)

    # The two plates that close the housing.  They do not move, they are the
    # same colour as the barrel they bolt to, and they are why the shaft
    # supports and the output bearing have somewhere to be.
    for name, label, bore, z0, apart, motor in (
            ("input_end_plate", "Input end plate", spec.input_plate_bore,
             spec.barrel_top, 2.0, True),
            ("output_end_plate", "Output end plate",
             spec.output_bearing_seat_diameter,
             plate_bottom - spec.plate_thickness, -1.6, False)):
        # Each comes off its own face rather than staying with the barrel: they
        # are bolted on, and an exploded view that leaves them there is showing
        # a housing nobody can assemble.
        with b.part(name, label, "end_plates", PART_COLOURS["end_plates"],
                    explode=apart):
            bolts = _plate_bolt_holes(spec, motor)
            outer = _circle(0.0, 0.0, spec.housing_outer_radius, 96)
            top = z0 + spec.plate_thickness
            bore_loop = _circle(0.0, 0.0, max(bore, 1e-3) / 2.0, 48)
            recess = (_pilot_recess(spec, bore)
                      if motor and not spec.ground_frame_fitted else 0.0)
            if recess:
                # A register is a step, not a hole: the outer face is bored to
                # the motor's spigot for the first couple of millimetres and to
                # the bearing seat after that, so it takes two prisms.
                #
                # And the face where those two meet is *interior* everywhere the
                # upper one covers, which is everywhere: the recess is wider
                # than the bore under it, so the whole of the upper prism's
                # underside is against the lower one. Capping both - which is
                # what this did - buried a full annular wall inside the plate,
                # left every bolt hole crossing it non-manifold, and so cost the
                # section its cap on the one part a motor bolts to. All that is
                # really exposed is the step itself, the ring between the
                # spigot's bore and the shaft support's.
                pilot = _circle(0.0, 0.0, spec.motor_face.pilot_diameter / 2.0, 48)
                b.prism(outer, (pilot, *bolts), top - recess, top,
                        cap_bottom=False)
                b.ring(pilot, bore_loop, top - recess, up=False)
                top -= recess
            b.prism(outer, (bore_loop, *bolts), z0, top, cap_top=not recess)

    # Bearings last, and each one takes the motion of the part it was placed
    # against rather than restating it.  Two copies of "how does a disc move"
    # would agree today and drift by the first change to either.
    hosts = {p.name: p for p in b.parts}
    for placement in placements:
        host = hosts[placement.host]
        segments = int(np.clip(700 // max(placement.count, 1), *_BEARING_SEGMENTS))
        with b.part(placement.name, placement.label, "bearings",
                    PART_COLOURS["bearings"], explode=host.explode,
                    spin=host.spin, phase=host.phase, orbits=host.orbits):
            for r in placement.rings:
                b.prism(_circle(r.cx, r.cy, placement.outer / 2.0, segments),
                        (_circle(r.cx, r.cy, placement.bore / 2.0, segments),),
                        r.z0, r.z1)

    # The bolts that hold the two plates on.  Bought, like the bearings, so
    # they are in the picture and in the bill of materials and not in the
    # per-part export - a STEP file of a cap screw is a thing to order.
    if spec.housing_bolt_count:
        shank = TIE_BOLT_NOMINAL * spec.housing_bolt_diameter
        z0 = spec.tie_bolt_bottom
        z1 = z0 + spec.tie_bolt_length
        with b.part("tie_bolts", "Tie bolts", "fasteners",
                    PART_COLOURS["fasteners"]):
            for a in (2.0 * np.pi * k / spec.housing_bolt_count
                      for k in range(spec.housing_bolt_count)):
                cx = spec.housing_bolt_radius * math.cos(a)
                cy = spec.housing_bolt_radius * math.sin(a)
                b.prism(_circle(cx, cy, shank / 2.0, _BOLT_SEGMENTS), (),
                        z0, z1)

    return b.build(spec)


def mesh_fingerprint(spec: GearSpec,
                     placements: Sequence[BearingPlacement] | None = None) -> tuple:
    """Everything :func:`build_mesh` reads, and nothing else.

    Keying the cache on the whole serialised spec would be safe and useless:
    changing the input speed, the rated torque or a material produces a new key
    and rebuilds a mesh that is identical, and on the hardware view that is a
    fresh upload to the card for nothing.

    The bearings are the exception to "nothing else", and they are in here as
    their *outcome* rather than as the fields that decide it.  Which bearing
    gets drawn depends on the load, so on the torque, the speed and the
    materials - and listing those by hand is how the key would come to be wrong.
    The chosen sizes cannot be wrong about themselves.

    The risk of listing fields by hand is leaving one out and then serving a
    stale mesh, so ``tests/test_viz.py`` perturbs every field of ``GearSpec`` in
    turn and requires that an unchanged fingerprint really does mean an
    unchanged mesh.
    """
    if placements is None:
        placements = placements_for_spec(spec)
    return (
        spec.effective_R, spec.effective_Rr, spec.eccentricity, spec.lobes,
        spec.pin_circle_radius, spec.pin_radius,
        spec.disc_thickness, spec.disc_count, spec.disc_gap,
        spec.center_bore_diameter, spec.hole_clearance,
        spec.output_pin_count, spec.output_pin_diameter,
        spec.output_bolt_circle_radius, spec.output_flange_thickness,
        spec.housing_outer_radius, spec.input_shaft_diameter, spec.cam_diameter,
        spec.plate_thickness, spec.hub_diameter, spec.hub_bore,
        spec.output_bearing_seat_diameter, spec.output_boss_protrusion,
        spec.input_plate_bore, spec.barrel_top, spec.output_pin_length,
        spec.end_cap_bottom, spec.end_cap_top, spec.cap_boss_top,
        spec.shaft_overhang, spec.housing_bolt_count, spec.housing_bolt_diameter,
        spec.housing_bolt_radius, spec.motor_frame,
        # Decides both the bore's shape and whether there is a pins part at all.
        spec.ring_pins_integral,
        # Which member turns: it moves the motor pattern off one part and onto
        # another, grows the carrier a base, and sets the whole assembly
        # spinning the other way - so it changes the mesh three times over.
        spec.output_member, spec.frame_spin, spec.ground_frame_fitted,
        spec.output_bolt_count, spec.output_bolt_diameter,
        tuple(placements),
    )


_CACHE: dict[tuple, Mesh] = {}


def mesh_for_spec(spec: GearSpec) -> Mesh:
    """:func:`build_mesh` memoised on the geometry.

    The viewer asks for a mesh whenever the design changes, and most design
    changes are not geometry.  Returning the *same object* for the same geometry
    is what lets the 3D view skip re-uploading unchanged parts.
    """
    placements = placements_for_spec(spec)
    key = mesh_fingerprint(spec, placements)
    mesh = _CACHE.get(key)
    if mesh is None:
        if len(_CACHE) >= 4:               # dragging a spin box makes a new key a
            _CACHE.clear()                 # frame; this is a cache, not a history
        mesh = _CACHE[key] = build_mesh(spec, placements)
    return mesh
