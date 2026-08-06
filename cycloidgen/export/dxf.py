"""DXF output, laid out for CAM rather than for looking at.

The profile goes out as a closed LWPOLYLINE sampled to the chord tolerance in the
spec.  Splines are more compact but far less portable between CAM packages.
"""
from __future__ import annotations

from pathlib import Path

import ezdxf
import numpy as np

from ..analysis.bearings import pin_shank_diameter, placements_for_spec
from ..core import profile as prof
from ..core.spec import GearSpec
from .manifest import disc_names

__all__ = ["write_dxf", "write_part_dxfs"]

LAYERS = {
    "DISC_PROFILE": 3,
    "DISC_BORE": 1,
    "OUTPUT_HOLES": 5,
    "RING_PINS": 2,
    "HOUSING": 7,
    "PITCH": 8,
    # The plates carry two hole patterns that answer to different drawings - the
    # tie bolts are ours, the motor pattern is the motor maker's - and a shop
    # drilling one wants to be able to switch the other off.
    "BOLTS": 6,
    "MOTOR": 4,
}


def _new_doc() -> tuple:
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4  # millimetres
    for name, color in LAYERS.items():
        doc.layers.add(name=name, color=color)
    return doc, doc.modelspace()


def _title(msp, spec: GearSpec, text: str, radius: float) -> None:
    msp.add_text(text, height=max(radius / 30.0, 1.2),
                 dxfattribs={"layer": "HOUSING"}
                 ).set_placement((-radius, -radius - radius / 12.0))


def _cross(msp, c: tuple[float, float], size: float = 2.0) -> None:
    """Centre mark, which is what a hole is drilled from.

    A circle says where the metal is not; the crosshair says where the point
    goes.  Cheap to add and the difference between a file you can cut and a file
    you can also set up by hand from.
    """
    msp.add_line((c[0] - size, c[1]), (c[0] + size, c[1]), dxfattribs={"layer": "PITCH"})
    msp.add_line((c[0], c[1] - size), (c[0], c[1] + size), dxfattribs={"layer": "PITCH"})


def _polar(radius: float, count: int) -> list[tuple[float, float]]:
    """``count`` points on ``radius``, starting at zero - the way every array in
    this app is built, so a DXF cannot land the pattern the solid does not."""
    return [(radius * np.cos(2.0 * np.pi * k / count),
             radius * np.sin(2.0 * np.pi * k / count)) for k in range(count)]


def _end_plate(spec: GearSpec, directory: Path, name: str, bore: float,
               motor_face: bool = False) -> Path:
    """One of the two plates that close the housing, as a drilling drawing.

    Both are the housing outside diameter on the same tie-bolt circle; what
    differs is the hole in the middle - shaft support one end, the bearing the
    whole drive turns on at the other - and whether a motor bolts to the face.
    Everything here is read from the same properties
    :func:`~cycloidgen.export.solid.housing_end_plate` extrudes, including the
    rule that a register smaller than the bore is not a feature but a bore that
    has already swallowed it.
    """
    doc, msp = _new_doc()
    r = spec.housing_outer_radius
    msp.add_circle((0, 0), r, dxfattribs={"layer": "HOUSING"})
    msp.add_circle((0, 0), max(bore, 1e-3) / 2.0, dxfattribs={"layer": "DISC_BORE"})
    _cross(msp, (0.0, 0.0), size=max(bore / 2.0, 1.0) + 3.0)

    note = f"{name.replace('_', ' ')}  OD {2 * r:g}  bore {bore:g}"

    if spec.housing_bolt_count:
        msp.add_circle((0, 0), spec.housing_bolt_radius,
                       dxfattribs={"layer": "PITCH", "linetype": "DASHED"})
        for c in _polar(spec.housing_bolt_radius, spec.housing_bolt_count):
            msp.add_circle(c, spec.housing_bolt_diameter / 2.0,
                           dxfattribs={"layer": "BOLTS"})
            _cross(msp, c)
        note += (f"  |  {spec.housing_bolt_count} x {spec.housing_bolt_diameter:g} "
                 f"tie on BC {2 * spec.housing_bolt_radius:g}")

    if motor_face and spec.has_motor_face:
        frame = spec.motor
        if frame.pilot_diameter > bore:
            msp.add_circle((0, 0), frame.pilot_diameter / 2.0,
                           dxfattribs={"layer": "MOTOR"})
            note += f"  |  register {frame.pilot_diameter:g} x {frame.pilot_depth:g} deep"
        # A NEMA pattern is a *square*, so its bolts do not sit on the bolt
        # circle a polar array would put them on - stating one as the other is
        # the mistake this table exists to stop anybody making.
        if frame.square:
            h = frame.bolt_span / 2.0
            holes = [(sx * h, sy * h) for sx in (-1, 1) for sy in (-1, 1)]
            pattern = f"{frame.bolt_span:g} square"
        else:
            holes = _polar(frame.bolt_span / 2.0, frame.bolt_count)
            pattern = f"BC {frame.bolt_span:g}"
        for c in holes:
            msp.add_circle(c, frame.bolt_diameter / 2.0, dxfattribs={"layer": "MOTOR"})
            _cross(msp, c)
        note += (f"  |  {frame.name}: {len(holes)} x {frame.bolt_diameter:g} "
                 f"on {pattern}")

    _title(msp, spec, note, r)
    out = directory / f"{name}.dxf"
    doc.saveas(out)
    return out


def write_dxf(spec: GearSpec, path: str | Path) -> Path:
    """Write disc, ring and housing geometry to a single DXF."""
    path = Path(path)
    doc, msp = _new_doc()

    p = prof.profile_from_spec(spec)
    msp.add_lwpolyline(p.points, close=True, dxfattribs={"layer": "DISC_PROFILE"})

    bore_r = (spec.center_bore_diameter + spec.hole_clearance) / 2.0
    msp.add_circle((0, 0), bore_r, dxfattribs={"layer": "DISC_BORE"})

    # Each disc in a stack carries its hole pattern at a different angle, so a
    # multi-disc drive needs one layer per disc - they are different parts.
    hole_r = spec.output_hole_diameter / 2.0
    for disc_index, hole_phase in enumerate(spec.disc_hole_phases):
        layer = ("OUTPUT_HOLES" if spec.discs_are_identical
                 else f"OUTPUT_HOLES_DISC{disc_index + 1}")
        if layer not in doc.layers:
            doc.layers.add(name=layer, color=LAYERS["OUTPUT_HOLES"] + disc_index)
        for k in range(spec.output_pin_count):
            a = 2.0 * np.pi * k / spec.output_pin_count + hole_phase
            c = (spec.output_bolt_circle_radius * np.cos(a),
                 spec.output_bolt_circle_radius * np.sin(a))
            msp.add_circle(c, hole_r, dxfattribs={"layer": layer})
        if spec.discs_are_identical:
            break

    for k in range(spec.pin_count):
        a = 2.0 * np.pi * k / spec.pin_count
        c = (spec.pin_circle_radius * np.cos(a), spec.pin_circle_radius * np.sin(a))
        msp.add_circle(c, spec.pin_radius, dxfattribs={"layer": "RING_PINS"})

    msp.add_circle((0, 0), spec.pin_circle_radius,
                   dxfattribs={"layer": "PITCH", "linetype": "DASHED"})
    msp.add_circle((0, 0), spec.housing_outer_radius, dxfattribs={"layer": "HOUSING"})

    msp.add_text(
        f"cycloidal drive  i={spec.ratio}:1  N={spec.lobes} lobes / {spec.pin_count} pins  "
        f"R={spec.pin_circle_radius} Rr={spec.pin_radius} E={spec.eccentricity}  "
        f"clearance={spec.profile_clearance} ({spec.offset_mode.value})",
        height=2.0,
        dxfattribs={"layer": "HOUSING"},
    ).set_placement((-spec.housing_outer_radius, -spec.housing_outer_radius - 8))

    doc.saveas(path)
    return path


def write_part_dxfs(spec: GearSpec, directory: str | Path) -> list[Path]:
    """One DXF per part, each on its own origin and nothing else in the file.

    ``disc.dxf`` is a drawing: every part of the drive on separate layers, for
    reading.  These are for cutting - a laser, waterjet or CAM job wants one
    closed outline and its holes, not the assembly it belongs to.  Each disc in
    a stack gets its own file, because their hole patterns differ.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    p = prof.profile_from_spec(spec)
    bore_r = (spec.center_bore_diameter + spec.hole_clearance) / 2.0
    hole_r = spec.output_hole_diameter / 2.0

    identical = spec.discs_are_identical
    phases = spec.disc_hole_phases[:1] if identical else spec.disc_hole_phases
    for name, hole_phase in zip(disc_names(spec), phases, strict=True):
        doc, msp = _new_doc()
        msp.add_lwpolyline(p.points, close=True, dxfattribs={"layer": "DISC_PROFILE"})
        msp.add_circle((0, 0), bore_r, dxfattribs={"layer": "DISC_BORE"})
        for k in range(spec.output_pin_count):
            a = 2.0 * np.pi * k / spec.output_pin_count + hole_phase
            msp.add_circle((spec.output_bolt_circle_radius * np.cos(a),
                            spec.output_bolt_circle_radius * np.sin(a)),
                           hole_r, dxfattribs={"layer": "OUTPUT_HOLES"})
        _title(msp, spec, f"{name}  i={spec.ratio}:1  holes at "
                          f"{np.degrees(hole_phase):+.3f} deg", p.outer_radius)
        out = directory / f"{name}.dxf"
        doc.saveas(out)
        written.append(out)

    # ---- ring plate: the housing bore and its pin pockets -------------------
    doc, msp = _new_doc()
    msp.add_circle((0, 0), spec.housing_outer_radius, dxfattribs={"layer": "HOUSING"})
    msp.add_circle((0, 0), spec.pin_circle_radius, dxfattribs={"layer": "DISC_BORE"})
    for k in range(spec.pin_count):
        a = 2.0 * np.pi * k / spec.pin_count
        msp.add_circle((spec.pin_circle_radius * np.cos(a),
                        spec.pin_circle_radius * np.sin(a)),
                       spec.pin_radius, dxfattribs={"layer": "RING_PINS"})
    _title(msp, spec, f"ring plate  {spec.pin_count} pins  "
                      f"BC {2 * spec.pin_circle_radius:g}",
           spec.housing_outer_radius)
    out = directory / "ring_plate.dxf"
    doc.saveas(out)
    written.append(out)

    # ---- carrier drilling template -----------------------------------------
    doc, msp = _new_doc()
    plate_r = spec.output_bolt_circle_radius + spec.output_pin_diameter
    # A pin carrying a roller is pressed in by its shank, not by the diameter the
    # disc runs on - drilling the working size would leave nothing to press.
    shank = pin_shank_diameter(placements_for_spec(spec), "bearing_output_pins",
                               spec.output_pin_diameter)
    msp.add_circle((0, 0), plate_r, dxfattribs={"layer": "HOUSING"})
    msp.add_circle((0, 0), (spec.input_shaft_diameter + 1.0) / 2.0,
                   dxfattribs={"layer": "DISC_BORE"})
    msp.add_circle((0, 0), spec.output_bolt_circle_radius,
                   dxfattribs={"layer": "PITCH", "linetype": "DASHED"})
    for c in _polar(spec.output_bolt_circle_radius, spec.output_pin_count):
        # the pin is a press fit in the carrier, so this is the pin size, not
        # the running hole in the disc
        msp.add_circle(c, shank / 2.0, dxfattribs={"layer": "OUTPUT_HOLES"})
        _cross(msp, c)
    _title(msp, spec, f"output carrier  {spec.output_pin_count} x "
                      f"{shank:g} press fit  "
                      f"BC {2 * spec.output_bolt_circle_radius:g}", plate_r)
    out = directory / "output_carrier.dxf"
    doc.saveas(out)
    written.append(out)

    # ---- the two plates that close the housing ------------------------------
    # New made parts as of the end plates, and the only ones whose whole job is
    # a hole pattern: a bolt circle and a motor face are things you drill, and
    # a STEP file is not something you can drill from.
    written.append(_end_plate(spec, directory, "input_end_plate",
                              spec.hub_bore, motor_face=True))
    written.append(_end_plate(spec, directory, "output_end_plate",
                              spec.output_bearing_seat_diameter))
    return written
