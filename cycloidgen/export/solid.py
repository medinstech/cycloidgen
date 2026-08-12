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
from ..viz.mesh import PART_COLOURS, TIE_BOLT_NOMINAL
from .manifest import disc_names

__all__ = [
    "bearing_solids",
    "build_assembly",
    "disc_solid",
    "eccentric_shaft",
    "end_cap",
    "output_flange",
    "parts",
    "ring_housing",
    "tie_bolts",
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
    """Fixed ring: pins sit half-embedded in pockets on the bore.

    It runs from the output end plate's face up to the input one's, which is
    lower than the disc stack at the output end - the carrier hangs under the
    discs and the barrel has to cover it.  Sized to the stack alone it left a
    slot round the gearbox where the carrier was.

    With ``ring_pins_integral`` the same circles are added instead of removed.
    A pocket and the pin that fills it are one shape read from either side, so
    the whole difference between a housing that takes dowels and one that is
    printed with its pins on is ``cut`` against ``union``.
    """
    z0, h = spec.barrel_bottom, spec.barrel_height
    body = (cq.Workplane("XY").workplane(offset=z0)
            .circle(spec.housing_outer_radius)
            .circle(spec.pin_circle_radius)
            .extrude(h))
    pins = (cq.Workplane("XY").workplane(offset=z0)
            .polarArray(spec.pin_circle_radius, 0, 360, spec.pin_count)
            .circle(spec.pin_radius)
            .extrude(h))
    body = body.union(pins) if spec.ring_pins_integral else body.cut(pins)

    # The bolts that hold the plates on have to pass through the thing they are
    # clamping.  Both plates were drilled for them and the bill of materials
    # orders them; the barrel was not, so the exported assembly was a gearbox
    # whose six tie bolts land on solid wall.
    if spec.housing_bolt_count:
        bolts = (cq.Workplane("XY").workplane(offset=z0)
                 .polarArray(spec.housing_bolt_radius, 0, 360,
                             spec.housing_bolt_count)
                 .circle(spec.housing_bolt_diameter / 2.0)
                 .extrude(h))
        body = body.cut(bolts)
    return body


def ring_pins(spec: GearSpec, placements: Sequence[BearingPlacement] = ()) -> cq.Workplane:
    """The pins themselves, as a single multi-solid part.

    A pin carrying a roller shrinks to that roller's bore: the sleeve's OD is the
    surface the profile was cut against, so the pin cannot also have it.

    Barrel length, from the output plate's face to the input plate's, because
    that is what holds them in - see :attr:`GearSpec.ring_pin_length`.
    """
    shank = pin_shank_diameter(placements, "bearing_ring_pins", 2.0 * spec.pin_radius)
    return (cq.Workplane("XY")
            .workplane(offset=spec.barrel_bottom)
            .polarArray(spec.pin_circle_radius, 0, 360, spec.pin_count)
            .circle(shank / 2.0)
            .extrude(spec.ring_pin_length))


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


def _motor_pattern(wp: cq.Workplane, spec: GearSpec) -> cq.Workplane:
    """Drill a motor's bolt pattern from whichever face ``wp`` is on.

    NEMA frames put four bolts on a *square*; metric flanges use a circle.
    Which of the two it is comes off the frame rather than being assumed here,
    for the reason the table exists at all - four holes drawn on a circle of the
    same size land where a NEMA motor has nothing.
    """
    frame = spec.motor
    if frame.square:
        return wp.rarray(frame.bolt_span, frame.bolt_span, 2, 2).hole(
            frame.bolt_diameter)
    return wp.polarArray(frame.bolt_span / 2.0, 0, 360, frame.bolt_count).hole(
        frame.bolt_diameter)


def output_flange(spec: GearSpec,
                  placements: Sequence[BearingPlacement] = ()) -> cq.Workplane:
    """Carrier plate, its output pins, the boss, and - on a ring-output drive -
    the base the whole gearbox is bolted down by.

    The boss is what makes the output bearing a real part rather than a line on
    a schedule: it stands out through the output end plate, carries that bearing
    on its outside, and holds the outboard shaft support on its inside.  Without
    it the flange was a plate floating on six pins.

    What is on the *end* of that boss depends on which member turns.  Off the
    carrier, nothing: the boss is the output shaft end and a coupling grips it.
    Off the ring, this part is the one that stands still, so it is what the
    drive is mounted by - the boss ends in a plate the size of the housing with
    the motor's pattern in it, and the protrusion that used to be grip length
    becomes the standoff that keeps that plate clear of the turning one.

    One part rather than a base bolted to a carrier, because it is one rigid
    body: everything here is grounded together, and a joint drawn across it
    would be a joint with no load to carry and a fastener pattern to invent.
    """
    plate_r = spec.output_bolt_circle_radius + spec.output_pin_diameter
    t = spec.output_flange_thickness
    shank = pin_shank_diameter(placements, "bearing_output_pins",
                               spec.output_pin_diameter)
    plate = cq.Workplane("XY").circle(plate_r).extrude(-t)
    hub = (cq.Workplane("XY").workplane(offset=-t)
           .circle(spec.hub_diameter / 2.0)
           .extrude(-(spec.plate_thickness + spec.output_boss_protrusion)))
    pins = (cq.Workplane("XY")
            .polarArray(spec.output_bolt_circle_radius, 0, 360, spec.output_pin_count)
            .circle(shank / 2.0)
            .extrude(spec.output_pin_length))
    body = plate.union(hub).union(pins)

    if spec.ground_frame_fitted:
        # This part is modelled in its *own* frame, with the carrier's top face
        # at zero - the assembly then drops it by the carrier drop.  So an
        # assembled height has to be lifted by that drop to be used here, and
        # the base was not: it came out one millimetre below the boss it stands
        # on, which is a part in two pieces.  The volume was right, which is why
        # nothing caught it, and a printer would have made two.
        base = (cq.Workplane("XY")
                .workplane(offset=spec.base_plate_bottom + CARRIER_DROP)
                .circle(spec.housing_outer_radius)
                .extrude(spec.plate_thickness))
        if spec.has_motor_face:
            frame = spec.motor
            # The register first, and only where the spigot is wider than the
            # bore already through here - a motor that pilots on 22 mm into a
            # 22 mm bore is already located by it.
            if frame.pilot_diameter > spec.hub_bore:
                base = (base.faces("<Z").workplane()
                        .circle(frame.pilot_diameter / 2.0)
                        .cutBlind(-min(frame.pilot_depth,
                                       spec.plate_thickness / 2.0)))
            base = _motor_pattern(base.faces("<Z").workplane(), spec)
        body = body.union(base)

    # Bored through the lot in one go, from the far face: the shaft passes
    # through all of it and a two-diameter bore here would be a fit this app has
    # no reason to claim.
    return (body.faces("<Z").workplane()
            .circle(spec.hub_bore / 2.0)
            .cutThruAll())


def end_cap(spec: GearSpec, placements: Sequence[BearingPlacement] = ()) -> cq.Workplane:
    """The carrier's mirror image at the far end of the output pins.

    It exists only on a ring-output drive, and it is what makes that drive a
    frame rather than a cantilever.  Three things come out of putting a second
    plate on the far end of the pins:

    * the pins are supported at both ends, so they carry ``F*L/4`` instead of
      ``F*L`` - the single biggest structural change in this app;
    * the housing gets a second bearing, so it can take a moment instead of
      hanging off one;
    * the pins become the frame's own fasteners, threaded into the carrier and
      headed on the outside of this plate, so there is nothing else to hold the
      two grounded plates together.

    Same plate radius as the carrier, because it is the same plate seen from the
    other end - and that radius is comfortably inside the barrel bore, which it
    has to be: this part lives *inside* the housing that turns around it.
    """
    plate_r = spec.output_bolt_circle_radius + spec.output_pin_diameter
    shank = pin_shank_diameter(placements, "bearing_output_pins",
                               spec.output_pin_diameter)
    plate = (cq.Workplane("XY").workplane(offset=spec.end_cap_bottom)
             .circle(plate_r)
             .extrude(spec.output_flange_thickness))
    # The boss the second output bearing rides on, and the outboard shaft
    # support sits in.  It reaches exactly through the input end plate and stops
    # flush with it: nothing grips this one, unlike the carrier's.
    boss = (cq.Workplane("XY").workplane(offset=spec.end_cap_top)
            .circle(spec.hub_diameter / 2.0)
            .extrude(spec.cap_boss_top - spec.end_cap_top))
    # Clearance for the pins, not a press fit: they are located by the carrier
    # at the other end, and a plate pressed onto six pins cannot be assembled.
    # Cut as explicit cylinders rather than drilled from a selected face - the
    # highest face of this part is the top of the boss, and a pattern drilled
    # from there at the bolt circle radius starts outside the metal.
    pins = (cq.Workplane("XY").workplane(offset=spec.end_cap_bottom)
            .polarArray(spec.output_bolt_circle_radius, 0, 360,
                        spec.output_pin_count)
            .circle((shank + spec.hole_clearance) / 2.0)
            .extrude(spec.output_flange_thickness))
    bore = (cq.Workplane("XY").workplane(offset=spec.end_cap_bottom)
            .circle(spec.hub_bore / 2.0)
            .extrude(spec.cap_boss_top - spec.end_cap_bottom))
    return plate.union(boss).cut(pins).cut(bore)


def housing_end_plate(spec: GearSpec, bore: float,
                      motor_face: bool = False) -> cq.Workplane:
    """One of the two plates that close the housing.

    Same outside as the housing, because they bolt to it face to face.  What
    differs between them is the hole - the input side is bored for the shaft
    support, the output side for the bearing the whole drive turns on - and what
    is cut into the outside of it.

    ``motor_face`` marks the *input-side* plate rather than promising a motor:
    what that face is for depends on which member turns.  With the housing
    grounded it is where the motor bolts on.  With the housing as the output it
    is the face that turns, so the motor has gone to the carrier's base and this
    is what the driven machine bolts to instead - the same plate, the opposite
    end of the power flow.
    """
    plate = (cq.Workplane("XY")
             .circle(spec.housing_outer_radius)
             .circle(max(bore, 1e-3) / 2.0)
             .extrude(spec.plate_thickness))

    if spec.housing_bolt_count:
        plate = (plate.faces(">Z").workplane()
                 .polarArray(spec.housing_bolt_radius, 0, 360,
                             spec.housing_bolt_count)
                 .hole(spec.housing_bolt_diameter))

    if motor_face and spec.ground_frame_fitted:
        if spec.output_bolt_count:
            plate = (plate.faces(">Z").workplane()
                     .polarArray(spec.output_face_bolt_radius,
                                 math.degrees(spec.output_bolt_phase), 360,
                                 spec.output_bolt_count)
                     .hole(spec.output_bolt_diameter))
    elif motor_face and spec.has_motor_face:
        frame = spec.motor
        # The register first: a shallow recess on the outside face that the
        # motor's spigot drops into, and the only thing that actually centres it
        # - four clearance holes on their own leave it free to sit anywhere
        # inside them.
        if frame.pilot_diameter > bore:
            plate = (plate.faces(">Z").workplane()
                     .circle(frame.pilot_diameter / 2.0)
                     .cutBlind(-frame.pilot_depth))
        plate = _motor_pattern(plate.faces(">Z").workplane(), spec)
    return plate


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


def tie_bolts(spec: GearSpec) -> cq.Workplane:
    """The bolts themselves, as one multi-solid part.

    Bought, like the bearings and the pins, so they are in the assembly and not
    in the per-part export: a STEP file of a cap screw is a thing to order, not
    a thing to make.  Drawn at the nominal size rather than at the clearance
    hole, because that is the bolt - the gap round it is the fit.

    Shank only, and deliberately.  Where the head sits is a design decision this
    app has not been given - proud, counterbored, or threaded into a blind hole
    - and the one face it would land on is the input plate's outside, which is
    where a motor bolts on.  A head standing proud there is an interference; a
    counterbore is a change to a part this app dimensions for a shop to make.
    Drawing a head we cannot place correctly is worse than drawing the shank we
    can, and the bill of materials is what you order from.
    """
    shank = TIE_BOLT_NOMINAL * spec.housing_bolt_diameter
    return (cq.Workplane("XY").workplane(offset=spec.tie_bolt_bottom)
            .polarArray(spec.housing_bolt_radius, 0, 360, spec.housing_bolt_count)
            .circle(shank / 2.0)
            .extrude(spec.tie_bolt_length))


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
    planar["housing"] = identity
    if not spec.ring_pins_integral:
        assy.add(ring_pins(spec, placements), name="ring_pins",
                 color=_colour("ring_pins"))
        planar["ring_pins"] = identity

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

    # The end cap, on a ring-output drive: the far end of the output pins, and
    # the second thing the housing turns on.  Built at its assembled height, so
    # it needs no placement of its own.
    if spec.ground_frame_fitted:
        assy.add(end_cap(spec, placements), name="end_cap",
                 color=_colour("carrier"))
        planar["end_cap"] = identity

    # The plates close the housing, one on each face.  The output one sits
    # outboard of the carrier, so the boss passes through it and the pins stay
    # inside; the input one sits straight on top of the barrel - which reaches
    # past the discs to cover the end cap when there is one.
    assy.add(housing_end_plate(spec, spec.input_plate_bore, motor_face=True),
             name="input_end_plate",
             loc=cq.Location(cq.Vector(0, 0, spec.barrel_top)),
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

    if spec.housing_bolt_count:
        assy.add(tie_bolts(spec), name="tie_bolts", color=_colour("fasteners"))
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
        "eccentric_shaft": eccentric_shaft(spec),
        "output_flange": output_flange(spec, placements),
        "input_end_plate": housing_end_plate(spec, spec.input_plate_bore,
                                             motor_face=True),
        "output_end_plate": housing_end_plate(
            spec, spec.output_bearing_seat_diameter),
    }
    if spec.ground_frame_fitted:
        out["end_cap"] = end_cap(spec, placements)
    # Integral pins are not a part, so there is no file for them.  The bundle
    # is declared from this dict, so leaving an empty one in would put a solid
    # in the manifest that the housing already contains.
    if not spec.ring_pins_integral:
        out["ring_pins"] = ring_pins(spec, placements)
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
