"""3D solids and the assembled gearbox, via CadQuery/OCCT.

Parts are modelled in their own local frames and placed by the assembly, so each
one can also be exported on its own for printing.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path

import cadquery as cq

from ..analysis.bearings import (
    BearingPlacement,
    pin_shank_diameter,
    placements_for_spec,
)
from ..core import profile as prof
from ..core.spec import CARRIER_DROP, GearSpec
from ..viz.mesh import PART_COLOURS
from .manifest import disc_names

__all__ = [
    "bearing_solids",
    "build_assembly",
    "disc_solid",
    "eccentric_shaft",
    "output_flange",
    "parts",
    "ring_housing",
    "write_part_steps",
    "write_step",
    "write_stls",
]

#: Solid modelling uses a coarser sampling than DXF; OCCT slows sharply with
#: vertex count and the mesh tolerance dominates the result anyway.
_MAX_SOLID_POINTS = 1400


def _colour(group: str) -> cq.Color:
    """Part colour, from the same table the 3D viewer paints with.

    The viewer and the STEP file are meant to be recognisably the same gearbox.
    Two hand-written colour lists would agree on the day they were written and
    not for very long after that.
    """
    r, g, b = PART_COLOURS[group]
    return cq.Color(r / 255.0, g / 255.0, b / 255.0)


def _profile_points(spec: GearSpec) -> list[tuple[float, float]]:
    n = prof.sample_count_for_chord_tolerance(
        spec.effective_R, spec.effective_Rr, spec.eccentricity, spec.lobes,
        max(spec.stl_linear_tolerance, 1e-3), lo=360, hi=_MAX_SOLID_POINTS)
    p = prof.profile_from_spec(spec, n=int(n))
    return [(float(x), float(y)) for x, y in p.points]


def disc_solid(spec: GearSpec, hole_phase: float = 0.0) -> cq.Workplane:
    """One cycloidal disc: profile, central bore, output pin holes.

    ``hole_phase`` (radians) rotates the output-hole pattern against the lobes.
    Every disc past the first needs its own value - see
    :attr:`~cycloidgen.core.spec.GearSpec.disc_hole_phases` - because the discs
    are meshed at different angles but driven by one shared carrier.
    """
    pts = _profile_points(spec)
    disc = cq.Workplane("XY").polyline(pts).close().extrude(spec.disc_thickness)
    disc = disc.faces(">Z").workplane().hole(spec.center_bore_diameter + spec.hole_clearance)
    disc = (disc.faces(">Z").workplane()
            .polarArray(spec.output_bolt_circle_radius, math.degrees(hole_phase),
                        360, spec.output_pin_count)
            .hole(spec.output_hole_diameter))
    return disc


def ring_housing(spec: GearSpec) -> cq.Workplane:
    """Fixed ring: pins sit half-embedded in pockets on the bore."""
    h = spec.stack_height
    body = (cq.Workplane("XY")
            .circle(spec.housing_outer_radius)
            .circle(spec.pin_circle_radius)
            .extrude(h))
    pockets = (cq.Workplane("XY")
               .polarArray(spec.pin_circle_radius, 0, 360, spec.pin_count)
               .circle(spec.pin_radius)
               .extrude(h))
    return body.cut(pockets)


def ring_pins(spec: GearSpec, placements: Sequence[BearingPlacement] = ()) -> cq.Workplane:
    """The pins themselves, as a single multi-solid part.

    A pin carrying a roller shrinks to that roller's bore: the sleeve's OD is the
    surface the profile was cut against, so the pin cannot also have it.
    """
    shank = pin_shank_diameter(placements, "bearing_ring_pins", 2.0 * spec.pin_radius)
    return (cq.Workplane("XY")
            .polarArray(spec.pin_circle_radius, 0, 360, spec.pin_count)
            .circle(shank / 2.0)
            .extrude(spec.stack_height))


def eccentric_shaft(spec: GearSpec) -> cq.Workplane:
    """Input shaft with one eccentric cam per disc, phased around the axis."""
    overhang = spec.shaft_overhang
    shaft = (cq.Workplane("XY")
             .workplane(offset=-overhang)
             .circle(spec.input_shaft_diameter / 2.0)
             .extrude(spec.stack_height + 2 * overhang))
    z = 0.0
    for phase in spec.disc_phases:
        cx = spec.eccentricity * math.cos(phase)
        cy = -spec.eccentricity * math.sin(phase)
        cam = (cq.Workplane("XY").workplane(offset=z)
               .center(cx, cy)
               .circle(spec.cam_diameter / 2.0)
               .extrude(spec.disc_thickness))
        shaft = shaft.union(cam)
        z += spec.disc_thickness + spec.disc_gap
    return shaft


def output_flange(spec: GearSpec,
                  placements: Sequence[BearingPlacement] = ()) -> cq.Workplane:
    """Carrier plate, its output pins, and the boss the drive turns on.

    The boss is what makes the output bearing a real part rather than a line on
    a schedule: it stands out through the output end plate, carries that bearing
    on its outside, and holds the outboard shaft support on its inside.  Without
    it the flange was a plate floating on six pins.
    """
    plate_r = spec.output_bolt_circle_radius + spec.output_pin_diameter
    t = spec.output_flange_thickness
    shank = pin_shank_diameter(placements, "bearing_output_pins",
                               spec.output_pin_diameter)
    plate = cq.Workplane("XY").circle(plate_r).extrude(-t)
    hub = (cq.Workplane("XY").workplane(offset=-t)
           .circle(spec.hub_diameter / 2.0)
           .extrude(-spec.plate_thickness))
    pins = (cq.Workplane("XY")
            .polarArray(spec.output_bolt_circle_radius, 0, 360, spec.output_pin_count)
            .circle(shank / 2.0)
            .extrude(spec.stack_height))
    body = plate.union(hub).union(pins)
    # Bored through the lot in one go, from the far face of the boss: the shaft
    # passes through both and a two-diameter bore here would be a fit this app
    # has no reason to claim.
    return (body.faces("<Z").workplane()
            .circle(spec.hub_bore / 2.0)
            .cutThruAll())


def housing_end_plate(spec: GearSpec, bore: float) -> cq.Workplane:
    """One of the two plates that close the housing, as a flat ring.

    Same outside as the housing, because they bolt to it face to face.  What
    differs between the two is the hole: the input side is bored for the shaft
    support, the output side for the bearing the whole drive turns on.
    """
    return (cq.Workplane("XY")
            .circle(spec.housing_outer_radius)
            .circle(max(bore, 1e-3) / 2.0)
            .extrude(spec.plate_thickness))


def bearing_solids(spec: GearSpec,
                   placements: Sequence[BearingPlacement] | None = None
                   ) -> dict[str, cq.Workplane]:
    """The bearings as plain rings, keyed by part name.

    Rings, not races and rolling elements.  What the assembly has to answer is
    where a bearing goes and how much room it takes, and a modelled cage would
    add a few thousand faces to say nothing more about either.

    Built at their **assembled** height rather than in a part-local frame,
    because that is the one thing they share with the mesh: the two differ by a
    pure axial shift on some parts, and a ring built where it ends up needs only
    the host's turn and offset in the plane.
    """
    if placements is None:
        placements = placements_for_spec(spec)
    out: dict[str, cq.Workplane] = {}
    for placement in placements:
        body: cq.Workplane | None = None
        for r in placement.rings:
            ring = (cq.Workplane("XY").workplane(offset=r.z0)
                    .center(r.cx, r.cy)
                    .circle(placement.outer / 2.0)
                    .circle(placement.bore / 2.0)
                    .extrude(r.z1 - r.z0))
            body = ring if body is None else body.union(ring)
        if body is not None:
            out[placement.name] = body
    return out


def build_assembly(spec: GearSpec) -> cq.Assembly:
    """Full gearbox at crank angle zero, each disc on its own phase."""
    assy = cq.Assembly(name=f"cycloidal_{spec.ratio}to1")
    placements = placements_for_spec(spec)

    #: Where each part was put, so that a bearing can be placed against its host
    #: rather than have the same pose worked out a second time.  Only the planar
    #: part of it: the rings are already built at their assembled height.
    planar: dict[str, cq.Location] = {}
    identity = cq.Location(cq.Vector(0, 0, 0))

    assy.add(ring_housing(spec), name="housing", color=_colour("housing"))
    assy.add(ring_pins(spec, placements), name="ring_pins",
             color=_colour("ring_pins"))
    planar["housing"] = planar["ring_pins"] = identity

    z = 0.0
    for i, (phase, hole_phase) in enumerate(zip(spec.disc_phases,
                                                spec.disc_hole_phases,
                                                strict=True)):
        cx = spec.eccentricity * math.cos(phase)
        cy = -spec.eccentricity * math.sin(phase)
        rot = math.degrees(phase / spec.lobes)
        assy.add(disc_solid(spec, hole_phase), name=f"disc_{i + 1}",
                 loc=cq.Location(cq.Vector(cx, cy, z), cq.Vector(0, 0, 1), rot),
                 color=_colour("discs"))
        planar[f"disc_{i + 1}"] = cq.Location(cq.Vector(cx, cy, 0.0),
                                              cq.Vector(0, 0, 1), rot)
        z += spec.disc_thickness + spec.disc_gap

    assy.add(eccentric_shaft(spec), name="eccentric_shaft", color=_colour("shaft"))
    assy.add(output_flange(spec, placements), name="output_flange",
             loc=cq.Location(cq.Vector(0, 0, -CARRIER_DROP)),
             color=_colour("carrier"))
    planar["eccentric_shaft"] = planar["output_flange"] = identity

    # The plates close the housing, one on each face.  The output one sits
    # outboard of the carrier, so the boss passes through it and the pins stay
    # inside; the input one sits straight on top of the barrel.
    assy.add(housing_end_plate(spec, spec.hub_bore), name="input_end_plate",
             loc=cq.Location(cq.Vector(0, 0, spec.stack_height)),
             color=_colour("end_plates"))
    assy.add(housing_end_plate(spec, spec.output_bearing_seat_diameter),
             name="output_end_plate",
             loc=cq.Location(cq.Vector(
                 0, 0, -CARRIER_DROP - spec.output_flange_thickness
                 - spec.plate_thickness)),
             color=_colour("end_plates"))
    planar["input_end_plate"] = planar["output_end_plate"] = identity

    for name, body in bearing_solids(spec, placements).items():
        host = next(p.host for p in placements if p.name == name)
        assy.add(body, name=name, loc=planar[host], color=_colour("bearings"))
    return assy


def write_step(spec: GearSpec, path: str | Path) -> Path:
    """Export the whole gearbox as one STEP assembly."""
    path = Path(path)
    build_assembly(spec).export(str(path))
    return path


def parts(spec: GearSpec) -> dict[str, cq.Workplane]:
    """Every distinct part, each in its own frame, keyed by file name.

    One entry per *distinct* disc: the hole pattern differs between them unless
    ``output_pin_count`` happens to be a multiple of ``2*lobes``, and shipping
    one file for a stack of different parts is how a drive gets built wrong.

    Made parts only.  A bearing is bought, and an STL of one is a fit check at
    best and a part someone tries to print at worst; they are in the assembly,
    which is where fit is checked, and in the BOM, which is where you order them.
    """
    placements = placements_for_spec(spec)
    out = {
        "housing": ring_housing(spec),
        "ring_pins": ring_pins(spec, placements),
        "eccentric_shaft": eccentric_shaft(spec),
        "output_flange": output_flange(spec, placements),
        "input_end_plate": housing_end_plate(spec, spec.hub_bore),
        "output_end_plate": housing_end_plate(
            spec, spec.output_bearing_seat_diameter),
    }
    phases = (spec.disc_hole_phases[:1] if spec.discs_are_identical
              else spec.disc_hole_phases)
    for name, hole_phase in zip(disc_names(spec), phases, strict=True):
        out[name] = disc_solid(spec, hole_phase)
    return out


def write_part_steps(spec: GearSpec, directory: str | Path) -> list[Path]:
    """Export every part as its own STEP solid.

    The assembly file is for looking at and for checking fit.  These are for
    handing one part to a machine shop, or to a CAM package that would otherwise
    make you fish the body out of an assembly first.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, wp in parts(spec).items():
        out = directory / f"{name}.step"
        cq.exporters.export(wp.val(), str(out))
        written.append(out)
    return written


def write_stls(spec: GearSpec, directory: str | Path, prefix: str = "") -> list[Path]:
    """Export every part as its own STL - STL has no assembly structure."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    tol = spec.stl_linear_tolerance
    written: list[Path] = []
    for name, wp in parts(spec).items():
        out = directory / f"{prefix}{name}.stl"
        cq.exporters.export(wp.val(), str(out), tolerance=tol, angularTolerance=0.1)
        written.append(out)
    return written
