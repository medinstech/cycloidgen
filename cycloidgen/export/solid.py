"""3D solids and the assembled gearbox, via CadQuery/OCCT.

Parts are modelled in their own local frames and placed by the assembly, so each
one can also be exported on its own for printing.
"""
from __future__ import annotations

import math
from pathlib import Path

import cadquery as cq

from ..core import profile as prof
from ..core.spec import GearSpec

__all__ = [
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


def ring_pins(spec: GearSpec) -> cq.Workplane:
    """The pins themselves, as a single multi-solid part."""
    return (cq.Workplane("XY")
            .polarArray(spec.pin_circle_radius, 0, 360, spec.pin_count)
            .circle(spec.pin_radius)
            .extrude(spec.stack_height))


def eccentric_shaft(spec: GearSpec) -> cq.Workplane:
    """Input shaft with one eccentric cam per disc, phased around the axis."""
    overhang = 12.0
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


def output_flange(spec: GearSpec) -> cq.Workplane:
    """Carrier plate carrying the output pins that ride in the disc holes."""
    plate_r = spec.output_bolt_circle_radius + spec.output_pin_diameter
    t = spec.output_flange_thickness
    plate = (cq.Workplane("XY").circle(plate_r).extrude(-t)
             .faces("<Z").workplane().hole(spec.input_shaft_diameter + 1.0))
    pins = (cq.Workplane("XY")
            .polarArray(spec.output_bolt_circle_radius, 0, 360, spec.output_pin_count)
            .circle(spec.output_pin_diameter / 2.0)
            .extrude(spec.stack_height))
    return plate.union(pins)


def build_assembly(spec: GearSpec) -> cq.Assembly:
    """Full gearbox at crank angle zero, each disc on its own phase."""
    assy = cq.Assembly(name=f"cycloidal_{spec.ratio}to1")

    assy.add(ring_housing(spec), name="housing", color=cq.Color(0.65, 0.65, 0.70))
    assy.add(ring_pins(spec), name="ring_pins", color=cq.Color(0.85, 0.55, 0.15))

    z = 0.0
    for i, (phase, hole_phase) in enumerate(zip(spec.disc_phases,
                                                spec.disc_hole_phases,
                                                strict=True)):
        cx = spec.eccentricity * math.cos(phase)
        cy = -spec.eccentricity * math.sin(phase)
        rot = math.degrees(phase / spec.lobes)
        assy.add(disc_solid(spec, hole_phase), name=f"disc_{i + 1}",
                 loc=cq.Location(cq.Vector(cx, cy, z), cq.Vector(0, 0, 1), rot),
                 color=cq.Color(0.30, 0.65, 0.85))
        z += spec.disc_thickness + spec.disc_gap

    assy.add(eccentric_shaft(spec), name="eccentric_shaft",
             color=cq.Color(0.45, 0.45, 0.50))
    assy.add(output_flange(spec), name="output_flange",
             loc=cq.Location(cq.Vector(0, 0, -1.0)),
             color=cq.Color(0.55, 0.75, 0.45))
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
    """
    out = {
        "housing": ring_housing(spec),
        "ring_pins": ring_pins(spec),
        "eccentric_shaft": eccentric_shaft(spec),
        "output_flange": output_flange(spec),
    }
    if spec.discs_are_identical:
        out["disc"] = disc_solid(spec, spec.disc_hole_phases[0])
    else:
        for i, hole_phase in enumerate(spec.disc_hole_phases):
            out[f"disc_{i + 1}"] = disc_solid(spec, hole_phase)
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
