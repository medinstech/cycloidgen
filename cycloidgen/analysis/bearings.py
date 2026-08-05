"""Bearing sizing help for the three load paths in a cycloidal drive.

Catalogue values are nominal metric-series figures and are meant for first-pass
selection only; confirm against the manufacturer's data before ordering.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ..core.spec import AUTOMATIC, CARRIER_DROP, SHAFT_OVERHANG, GearSpec

__all__ = ["CATALOGUE", "Bearing", "BearingChoice", "BearingPlacement", "BearingRing",
           "bearing_placements", "bearing_schedule", "pin_shank_diameter",
           "placements_for_spec", "select_bearings"]


@dataclass(frozen=True)
class Bearing:
    designation: str
    bore: float
    outer: float
    width: float
    C_kN: float          # basic dynamic load rating
    C0_kN: float         # basic static load rating
    kind: str            # "ball" or "needle"

    @property
    def life_exponent(self) -> float:
        return 3.0 if self.kind == "ball" else 10.0 / 3.0


CATALOGUE: list[Bearing] = [
    # thin section, 6800 series
    Bearing("6800", 10, 19, 5, 1.74, 0.915, "ball"),
    Bearing("6801", 12, 21, 5, 1.92, 1.06, "ball"),
    Bearing("6802", 15, 24, 5, 2.08, 1.27, "ball"),
    Bearing("6803", 17, 26, 5, 2.21, 1.43, "ball"),
    Bearing("6804", 20, 32, 7, 4.03, 2.32, "ball"),
    Bearing("6805", 25, 37, 7, 4.36, 2.90, "ball"),
    Bearing("6806", 30, 42, 7, 4.62, 3.35, "ball"),
    Bearing("6807", 35, 47, 7, 4.94, 4.00, "ball"),
    Bearing("6808", 40, 52, 7, 5.07, 4.30, "ball"),
    # 6900 series
    Bearing("6900", 10, 22, 6, 2.70, 1.27, "ball"),
    Bearing("6901", 12, 24, 6, 2.89, 1.46, "ball"),
    Bearing("6902", 15, 28, 7, 4.36, 2.24, "ball"),
    Bearing("6903", 17, 30, 7, 4.62, 2.55, "ball"),
    Bearing("6904", 20, 37, 9, 6.37, 3.65, "ball"),
    Bearing("6905", 25, 42, 9, 7.02, 4.30, "ball"),
    Bearing("6906", 30, 47, 9, 7.28, 5.00, "ball"),
    # 6000 series
    Bearing("6000", 10, 26, 8, 4.62, 1.96, "ball"),
    Bearing("6001", 12, 28, 8, 5.10, 2.36, "ball"),
    Bearing("6002", 15, 32, 9, 5.59, 2.85, "ball"),
    Bearing("6003", 17, 35, 10, 6.37, 3.25, "ball"),
    Bearing("6004", 20, 42, 12, 9.36, 5.00, "ball"),
    Bearing("6005", 25, 47, 12, 10.1, 5.85, "ball"),
    Bearing("6006", 30, 55, 13, 13.3, 8.30, "ball"),
    # drawn cup needle rollers, compact and stiff - ideal for the eccentric
    Bearing("HK0808", 8, 12, 8, 4.10, 3.60, "needle"),
    Bearing("HK1010", 10, 14, 10, 5.60, 5.60, "needle"),
    Bearing("HK1212", 12, 16, 12, 7.00, 7.50, "needle"),
    Bearing("HK1512", 15, 21, 12, 10.5, 11.0, "needle"),
    Bearing("HK1612", 16, 22, 12, 10.8, 11.6, "needle"),
    Bearing("HK2020", 20, 26, 20, 16.5, 20.0, "needle"),
    Bearing("HK2520", 25, 32, 20, 19.6, 25.5, "needle"),
    Bearing("HK3020", 30, 37, 20, 21.6, 30.0, "needle"),
    # The narrow end of the same series.  Without these the catalogue had a hole
    # exactly where a cycloidal drive needs one: an eccentric cam is 15-25 mm on
    # any drive worth building, the bearing on it can be no wider than the disc,
    # and every needle in that bore range here was 20 mm wide against an 8 mm
    # disc.  Nothing fitted, which read as "this design is impossible" when it
    # only meant "this list is short".
    Bearing("HK1812", 18, 24, 12, 11.4, 12.5, "needle"),
    Bearing("HK2012", 20, 26, 12, 12.6, 14.0, "needle"),
    Bearing("HK2212", 22, 28, 12, 13.2, 15.2, "needle"),
    Bearing("HK2512", 25, 32, 12, 14.8, 17.5, "needle"),
    Bearing("HK1808", 18, 24, 8, 8.60, 9.30, "needle"),
    Bearing("HK2008", 20, 26, 8, 9.20, 10.2, "needle"),
    Bearing("HK2508", 25, 32, 8, 10.8, 12.6, "needle"),
]


@dataclass
class BearingChoice:
    role: str
    bearing: Bearing | None
    load_N: float
    speed_rpm: float
    life_hours: float
    note: str
    #: How many of this one the drive needs.  In the role string it reads as
    #: prose and cannot be counted, priced or put on a drawing.
    count: int = 1
    #: What it holds, and against what.  A part number with no load path beside
    #: it is the thing this module used to hand over.
    carries: str = ""
    #: Where it sits, said in terms of the geometry the app already exports.
    seat: str = ""
    #: Whether this drive has a bearing part here at all.  A path left without
    #: one on purpose - fixed pins, a plain cam - and one where nothing in the
    #: catalogue fits are different answers, and only the second is a problem.
    #: A field rather than a phrase in the note, because reading the note is how
    #: the quantities went wrong once already.
    fitted: bool = True
    #: Whether the *load* leaves this gearbox.  Separate from ``fitted`` and not
    #: the same question: a plain cam has no bearing but the drive still carries
    #: the force, sliding; a drive hung on its motor's bearings does not carry it
    #: at all.  Only the second needs whatever is on the other end to be up to it.
    carried_elsewhere: bool = False
    #: What is wrong with the part in this seat, if anything: a named bearing
    #: that does not go in, a designation this build does not know, a bore
    #: standing off the shaft it is meant to be pressed onto.  Empty otherwise.
    #: Separate from ``note``, which is advice for a seat nothing fits at all -
    #: "no catalogue bearing fits, open the bore" is unhelpful when the real
    #: answer is "the one you asked for is 2 mm too wide".
    problem: str = ""
    #: Whether the part physically goes in the seat.  See :class:`_Filled`.
    fits: bool = True


def _life_hours(b: Bearing, load_N: float, rpm: float) -> float:
    if load_N <= 0 or rpm <= 0:
        return float("inf")
    ratio = (b.C_kN * 1000.0) / load_N
    return (10 ** 6 / (60.0 * rpm)) * ratio ** b.life_exponent


def _roller_rpm(spec: GearSpec) -> float:
    """How fast a ring pin roller turns, rev/min.

    Not the input speed: the roller only turns as fast as the disc flank drags
    its surface.  One lobe passes each pin every input revolution, and the arc
    swept over the pin in that time is about the lobe pitch, so the surface
    travel per input revolution is a lobe pitch and the roller turns that
    divided by its own circumference.  Rough, and it only sets the L10 life
    exponent's input rather than any stress.
    """
    circumference = 2.0 * math.pi * spec.pin_radius
    if circumference <= 0:
        return 0.0
    lobe_pitch = 2.0 * math.pi * spec.pin_circle_radius / max(spec.pin_count, 1)
    return spec.input_rpm * lobe_pitch / circumference


def _stacked(width: float, length: float) -> int:
    """How many of a roller it takes to cover a working length.

    A roller that *is* a working surface - a ring pin sleeve, an output pin
    bushing - has to be as long as the surface the disc runs on, and the widths
    in the catalogue do not care what your stack height is.  One per pin is the
    answer only when one happens to reach; otherwise it is the answer that
    leaves a builder with a pin loose in its pocket for most of its length.
    """
    if width <= 0.0:
        return 1
    return max(1, math.ceil(length / width - 1e-9))


#: Every catalogue part by designation, for the seats where one is named.
BY_NAME: dict[str, Bearing] = {b.designation: b for b in CATALOGUE}


@dataclass(frozen=True)
class _Seat:
    """What a seat will take, and what the drive asks of whatever goes in it."""

    bore_min: float
    outer_max: float
    width_max: float
    load_N: float
    rpm: float
    kinds: tuple[str, ...]
    #: What the bore goes on, named, so a bearing standing off it can say what
    #: to turn the shaft or cam to.
    journal: str = ""

    def misfit(self, b: Bearing) -> str:
        """Why ``b`` will not go in, in one clause.  Empty when it will."""
        if b.bore < self.bore_min - 1e-6:
            return (f"its {b.bore:g} mm bore is smaller than the "
                    f"{self.bore_min:.1f} mm it has to sit on")
        if b.outer > self.outer_max + 1e-6:
            return (f"its {b.outer:g} mm outside is larger than the "
                    f"{self.outer_max:.1f} mm it has to sit in")
        if b.width > self.width_max + 1e-6:
            return (f"it is {b.width:g} mm wide against {self.width_max:.1f} mm "
                    f"of room")
        return ""

    def standoff(self, b: Bearing) -> str:
        """A bore larger than what it sits on: a fit, but a loose one."""
        gap = b.bore - self.bore_min
        if self.journal and self.bore_min > 0.0 and gap > 0.05:
            return (f"its {b.bore:g} mm bore stands {gap:.2f} mm off the "
                    f"{self.bore_min:.1f} mm {self.journal}; turn the {self.journal} "
                    f"to {b.bore:g} mm or it is a press fit onto nothing")
        return ""


def _pick(seat: _Seat, min_life_hours: float) -> Bearing | None:
    """Smallest catalogue bearing that fits the seat and lasts long enough."""
    candidates = [
        b for b in CATALOGUE
        if b.kind in seat.kinds
        and not seat.misfit(b)
        and _life_hours(b, seat.load_N, seat.rpm) >= min_life_hours
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda b: (b.outer, b.width))


@dataclass(frozen=True)
class _Filled:
    """What went into a seat, and what has to be said about it."""

    bearing: Bearing | None
    problem: str = ""
    #: Whether it physically goes in.  A part that does not is still reported -
    #: you asked for it by name and want to know which dimension is wrong - but
    #: it is not drawn, because the drawing would have to shrink it to the seat
    #: to fit it in, and a picture of a part at a size it is not is worse than
    #: no picture at all.  A bore standing off its shaft is a *loose* fit, not a
    #: failed one, so that stays drawn.
    fits: bool = True


def _fill(seat: _Seat, named: str, min_life_hours: float) -> _Filled:
    """The bearing for one seat, and whatever has to be said about it.

    A named part is taken as given and then checked; it is never swapped for one
    that fits, because "this is the bearing I have" is exactly the case where a
    silent substitution is useless.
    """
    if not named or named == AUTOMATIC:
        # The standoff is checked here too, not only for named parts: the sizing
        # study takes any bore at or above what it sits on, so a hand-set cam
        # diameter between two catalogue sizes has always been able to come back
        # with a bearing that does not touch it, and say nothing.
        chosen = _pick(seat, min_life_hours)
        return _Filled(chosen, seat.standoff(chosen) if chosen else "")
    chosen = BY_NAME.get(named)
    if chosen is None:
        return _Filled(None, f"{named!r} is not a designation this build knows; "
                             f"leave it on {AUTOMATIC} or pick one from the list")
    if chosen.kind not in seat.kinds:
        return _Filled(chosen, f"{named} is a {chosen.kind} bearing and this seat "
                               f"wants " + " or ".join(seat.kinds), fits=False)
    reason = seat.misfit(chosen)
    if reason:
        return _Filled(chosen, f"{named} does not fit: {reason}", fits=False)
    return _Filled(chosen, seat.standoff(chosen))


def select_bearings(spec: GearSpec, eccentric_load_N: float,
                    output_pin_load_N: float,
                    ring_pin_load_N: float = 0.0) -> list[BearingChoice]:
    """The whole bearing schedule: every rolling interface, counted and placed.

    Five roles, not three.  The two that used to be missing are the ones a
    builder notices first: nothing supported the input shaft, and the ring pin
    rollers - a switch that already changes the efficiency and the PV duty - were
    never sized.  A schedule that skips a load path reads as if that path did not
    need a bearing.
    """
    out: list[BearingChoice] = []

    # 1. eccentric cam bearing - highest relative speed in the drive
    #
    # The bore goes on the *cam*, not on the shaft.  Sized against the shaft it
    # was possible to be handed a bearing whose bore was smaller than the cam it
    # had to sit on - and the default cam is the bore less 8 mm precisely to
    # leave room for this bearing's wall, so the two numbers were never
    # interchangeable.
    rpm = spec.input_rpm * (1.0 - 1.0 / spec.ratio)
    if not spec.cam_bearing_fitted:
        out.append(BearingChoice(
            role="Eccentric cam bearing", fitted=False, count=0, bearing=None,
            load_N=eccentric_load_N, speed_rpm=rpm, life_hours=float("inf"),
            carries="the radial force the disc pushes back into the crank",
            seat=f"none - the {spec.center_bore_diameter:.1f} mm disc bore runs "
                 f"straight on the cam",
            note="No cam bearing: the bore is a plain journal at nearly the "
                 "input speed, so this contact is wear-limited rather than "
                 "life-limited - see the PV check.",
        ))
    else:
        cam = _fill(_Seat(spec.cam_diameter, spec.center_bore_diameter,
                             spec.disc_thickness, eccentric_load_N, rpm,
                             ("needle", "ball"), journal="cam"),
                    spec.cam_bearing, spec.bearing_min_life_hours)
        b, why = cam.bearing, cam.problem
        out.append(BearingChoice(
            role="Eccentric cam bearing", count=spec.disc_count,
            bearing=b, load_N=eccentric_load_N, speed_rpm=rpm,
            life_hours=_life_hours(b, eccentric_load_N, rpm) if b else 0.0,
            carries="the radial force the disc pushes back into the crank",
            seat=f"on the {spec.cam_diameter:.1f} mm cam, inside the "
                 f"{spec.center_bore_diameter:.1f} mm disc bore",
            problem=why, fits=cam.fits,
            note=("" if (b or why) else
                  "no catalogue bearing fits: enlarge the central bore or "
                  "thicken the disc"),
        ))

    # 2. output pin rollers - optional, and the biggest single sliding loss
    if spec.output_pins_are_rollers:
        # As with the ring pins, the roller's OD *is* the working pin: the hole
        # is cut to the diameter the disc runs on, so the sleeve takes that
        # surface and the pin proper shrinks to its bore.  Asking for a bore of
        # a full pin diameter as well - which is what the hole less twice the
        # eccentricity comes to - was asking for a ring with no wall, and it is
        # why nothing has ever been selected here.
        outer = spec.output_pin_diameter
        outpin = _fill(_Seat(0.0, outer, spec.disc_thickness, output_pin_load_N,
                               spec.input_rpm, ("needle",)),
                       spec.output_pin_roller, spec.bearing_min_life_hours)
        b2, why2 = outpin.bearing, outpin.problem
        per_seat = _stacked(b2.width, spec.disc_thickness) if b2 else 1
        out.append(BearingChoice(
            role="Output pin roller",
            count=spec.output_pin_count * spec.disc_count * per_seat,
            bearing=b2, load_N=output_pin_load_N, speed_rpm=spec.input_rpm,
            life_hours=_life_hours(b2, output_pin_load_N, spec.input_rpm) if b2 else 0.0,
            carries="one pin's share of the output torque",
            seat=f"over each output pin, {spec.output_pin_diameter:g} mm OD "
                 f"working surface running in the "
                 f"{spec.output_hole_diameter:.1f} mm hole, one per disc"
                 + (f" - {per_seat} of them end to end to cover the "
                    f"{spec.disc_thickness:g} mm disc" if per_seat > 1 else ""),
            problem=why2, fits=outpin.fits,
            note=("" if (b2 or why2) else
                  "no drawn-cup needle is this small: a bronze bushing here "
                  "means turning the pin down to suit it, and by how much "
                  "is a diameter this app does not choose for you"),
        ))
    else:
        out.append(BearingChoice(
            role="Output pin roller", fitted=False, count=0, bearing=None,
            load_N=output_pin_load_N, speed_rpm=spec.input_rpm,
            life_hours=float("inf"),
            carries="nothing - the pin rubs directly in the hole",
            seat="",
            note="fixed pins selected - sliding contact, expect lower efficiency",
        ))

    # 3. ring pin rollers - the other switch that was changing the physics
    # without ever being given a part.
    if spec.ring_pins_are_rollers:
        # The roller's OD *is* the working pin: the profile is cut to the radius
        # the disc actually touches, so the sleeve has to live inside it and the
        # pin proper shrinks to whatever is left of the bore.
        outer = 2.0 * spec.pin_radius
        roller_rpm = _roller_rpm(spec)
        ringpin = _fill(_Seat(0.0, outer, spec.stack_height, ring_pin_load_N,
                               roller_rpm, ("needle",)),
                        spec.ring_pin_roller, spec.bearing_min_life_hours)
        b4, why4 = ringpin.bearing, ringpin.problem
        per_pin = _stacked(b4.width, spec.stack_height) if b4 else 1
        out.append(BearingChoice(
            role="Ring pin roller", count=spec.pin_count * per_pin,
            bearing=b4, load_N=ring_pin_load_N, speed_rpm=roller_rpm,
            life_hours=_life_hours(b4, ring_pin_load_N, roller_rpm) if b4 else 0.0,
            carries="the lobe load as each tooth sweeps past",
            seat=f"over each ring pin, {2 * spec.pin_radius:.1f} mm OD working "
                 f"surface, {spec.stack_height:.1f} mm long"
                 + (f" - {per_pin} of them end to end per pin" if per_pin > 1 else ""),
            problem=why4, fits=ringpin.fits,
            note=("" if (b4 or why4) else
                  "no drawn-cup needle is this small: use a hardened sleeve "
                  "turning on a smaller pin, which is what most builds at "
                  "this size do"),
        ))

    # 4. input shaft support - two of them, and until now nothing held the shaft
    # at all.  The cam sits between them, so each takes about half of what the
    # discs push back; an overhung cam loads the inner one far harder and this
    # does not model that.
    shaft_load = eccentric_load_N * spec.disc_count / 2.0
    if not spec.shaft_bearings_fitted:
        out.append(BearingChoice(
            role="Input shaft support", fitted=False, carried_elsewhere=True,
            count=0, bearing=None,
            load_N=shaft_load, speed_rpm=spec.input_rpm, life_hours=float("inf"),
            carries="nothing here - the driving motor's own bearings take the "
                    "crank reaction",
            seat="none - the drive hangs on the motor face",
            note=f"No shaft bearings: the driving motor takes "
                 f"{eccentric_load_N * spec.disc_count:.0f} N of radial load it "
                 f"was not necessarily bought to take, so check its rating.",
        ))
    else:
        shaft = _fill(_Seat(spec.input_shaft_diameter,
                               2.0 * (spec.pin_circle_radius - spec.pin_radius),
                               spec.housing_wall * 2.0, shaft_load, spec.input_rpm,
                               ("ball",), journal="input shaft"),
                      spec.shaft_bearing, spec.bearing_min_life_hours)
        b5, why5 = shaft.bearing, shaft.problem
        out.append(BearingChoice(
            role="Input shaft support", count=2,
            bearing=b5, load_N=shaft_load, speed_rpm=spec.input_rpm,
            life_hours=_life_hours(b5, shaft_load, spec.input_rpm) if b5 else 0.0,
            carries="half the crank reaction each, plus whatever the driving "
                    "coupling adds",
            seat=f"in the housing end plates, on the "
                 f"{spec.input_shaft_diameter:.1f} mm input shaft either side of "
                 f"the disc stack",
            problem=why5, fits=shaft.fits,
            note=("" if (b5 or why5) else
                  "nothing in the catalogue fits between the shaft and the "
                  "pin circle: a deeper housing or a smaller shaft"),
        ))

    # 5. main output bearing - carries the external load, turns slowly
    radial = output_pin_load_N * spec.output_pin_count / 2.0
    if not spec.output_bearing_fitted:
        out.append(BearingChoice(
            role="Main output bearing", fitted=False, carried_elsewhere=True,
            count=0, bearing=None,
            load_N=radial, speed_rpm=spec.output_rpm, life_hours=float("inf"),
            carries="nothing here - the driven machine locates the output flange",
            seat="none - the flange is carried by whatever it bolts to",
            note=f"No output bearing: the driven machine has to locate the "
                 f"flange and take {radial:.0f} N of radial load, and a flange "
                 f"free to tilt loads the output pins unevenly.",
        ))
    else:
        output = _fill(_Seat(spec.center_bore_diameter,
                               spec.housing_outer_radius * 2.0,
                               spec.housing_wall * 2.0, radial, spec.output_rpm,
                               ("ball",)),
                       spec.output_bearing, spec.bearing_min_life_hours)
        b3, why3 = output.bearing, output.problem
        out.append(BearingChoice(
            role="Main output bearing", count=1,
            bearing=b3, load_N=radial, speed_rpm=spec.output_rpm,
            life_hours=_life_hours(b3, radial, spec.output_rpm) if b3 else 0.0,
            carries="whatever the machine hangs on the output flange",
            seat="between the output flange and the housing - the only seat this "
                 "app does not model, so this one is not drawn in the 3D view or "
                 "the STEP either, and the size is a first pass",
            problem=why3, fits=output.fits,
            note=("" if (b3 or why3) else
                  "consider a crossed-roller or a pair of angular contact "
                  "bearings"),
        ))
    return out


def bearing_schedule(spec: GearSpec, contact=None) -> list[BearingChoice]:
    """The schedule from a spec alone, working the loads out on the way.

    :func:`select_bearings` takes the loads because that is what it needs; every
    caller then has to know which three numbers off the contact study to hand
    it, and there are now four callers.  One wiring site is enough.
    """
    if contact is None:
        from .mechanics import analyse_contacts
        contact = analyse_contacts(spec)
    return select_bearings(spec, contact.eccentric_bearing_load_N,
                           contact.max_output_force_N,
                           ring_pin_load_N=contact.max_pin_force_N)


# ------------------------------------------------------------------- placement


@dataclass(frozen=True)
class BearingRing:
    """One physical bearing: where its axis is, and the span it occupies."""

    cx: float
    cy: float
    z0: float
    z1: float


@dataclass(frozen=True)
class BearingPlacement:
    """Every bearing of one role that moves as a single rigid body.

    ``host`` names the part it travels with, by the name that part carries in
    the assembly - so the ring centres are in *that* part's frame, and neither
    the mesh nor the STEP assembly has to restate a motion law it already has.
    """

    name: str
    label: str
    role: str
    bore: float
    outer: float
    rings: tuple[BearingRing, ...]
    host: str
    catalogue: str = ""

    @property
    def count(self) -> int:
        return len(self.rings)


def placements_for_spec(spec: GearSpec) -> tuple[BearingPlacement, ...]:
    """Where this design's bearings sit, loads and selection included."""
    return tuple(bearing_placements(spec, bearing_schedule(spec)))


def pin_shank_diameter(placements: Sequence[BearingPlacement], name: str,
                       nominal: float) -> float:
    """What is left of a pin once a roller has taken its outside.

    A roller's OD *is* the working surface - the disc profile, or the output
    hole, was cut to that diameter - so the pin under it is the roller's bore
    and not the nominal size.  Everything that draws the pin or drills its seat
    has to agree about which of the two it means, and this is where they agree.
    """
    sleeve = next((p for p in placements if p.name == name), None)
    return sleeve.bore if sleeve is not None else nominal


def _span(z0: float, z1: float, width: float) -> tuple[float, float]:
    """Centre a bearing ``width`` long in the seat between ``z0`` and ``z1``."""
    if width >= z1 - z0:
        return z0, z1
    middle = 0.5 * (z0 + z1)
    return middle - width / 2.0, middle + width / 2.0


def _courses(z0: float, z1: float, width: float) -> list[tuple[float, float]]:
    """Lay rollers end to end from ``z0`` until the working surface is covered.

    The last one is cut off at the end of the seat rather than allowed to stand
    past it.  It is drawn short because it *is* short of a whole part: a stack
    height is not obliged to be a multiple of a catalogue width, and pretending
    otherwise would put a roller out in the air past the housing face.
    """
    if width <= 0.0:
        return [(z0, z1)]
    out, z = [], z0
    while z < z1 - 1e-9:
        out.append((z, min(z + width, z1)))
        z += width
    return out or [(z0, z1)]


def bearing_placements(spec: GearSpec,
                       choices: Sequence[BearingChoice]) -> list[BearingPlacement]:
    """The schedule again, in millimetres: where each bearing physically sits.

    The schedule says where a bearing goes in words, and words are what left the
    question open - "on the input shaft either side of the disc stack" is a
    description, not a place.  This is the same selection as geometry, so the 3D
    view and the STEP assembly can draw it, and so that a picture and a schedule
    that disagree is not a thing that can happen.

    Two rules decide what appears:

    * **The diameters are the picked part's**, wherever one was picked.  Drawing
      the seat to its own limits instead would show a bearing a couple of
      millimetres bigger than the one you will hold in your hand.
    * **A bearing is drawn only when both working diameters are known.**  That is
      what leaves the ring pin rollers out when no drawn cup is small enough:
      the schedule's answer there is a sleeve turning on a smaller pin, and how
      much smaller is not something this app has decided.  A guessed wall
      thickness would be inventing the part.

    The main output bearing is deliberately absent, and that is an answer rather
    than a gap.  It seats between the output flange and the housing, and the
    model has neither a flange hub nor a housing end plate for it to sit in;
    placing it would mean inventing both.  Its schedule note says the same.
    """
    # A part that does not go in its seat is not drawn.  It is still on the
    # schedule with the dimension that is wrong beside it - you asked for it by
    # name and that is what you need to know - but drawing it would mean shrinking
    # it to the seat to make it fit, and a picture of a part at a size it is not
    # is worse than no picture.
    by_role = {c.role: c for c in choices if c.fits}
    out: list[BearingPlacement] = []
    thickness = spec.disc_thickness
    pitch = thickness + spec.disc_gap

    # 1. Eccentric cam bearing.  Pressed into the disc bore and running on the
    # cam, so it turns with the disc - and the disc's own centre *is* the cam
    # centre, which is why the ring sits at the origin of that frame.
    cam = by_role.get("Eccentric cam bearing")
    if cam is not None and cam.bearing is not None:
        for i in range(spec.disc_count):
            z0, z1 = _span(i * pitch, i * pitch + thickness, cam.bearing.width)
            out.append(BearingPlacement(
                name=f"bearing_cam_{i + 1}",
                label=f"Cam bearing {i + 1}" if spec.disc_count > 1 else "Cam bearing",
                role=cam.role, catalogue=cam.bearing.designation,
                bore=cam.bearing.bore, outer=cam.bearing.outer,
                rings=(BearingRing(0.0, 0.0, z0, z1),), host=f"disc_{i + 1}"))

    # 2. Output pin rollers.  They ride on the carrier's pins, so they turn with
    # the carrier, and like the ring pin sleeves they take the pin's outside -
    # the hole is cut to the diameter the disc runs on.
    roller = by_role.get("Output pin roller")
    if roller is not None and roller.bearing is not None:
        # The carrier's pins start at the plate and run one stack height, which
        # leaves them a carrier drop short of the top disc; a roller may not
        # stand off the end of the pin it is on.
        pin_z0, pin_z1 = -CARRIER_DROP, spec.stack_height - CARRIER_DROP
        rings: list[BearingRing] = []
        for i in range(spec.disc_count):
            low = max(i * pitch, pin_z0)
            high = min(i * pitch + thickness, pin_z1)
            if high <= low:
                continue
            for z0, z1 in _courses(low, high, roller.bearing.width):
                for k in range(spec.output_pin_count):
                    angle = 2.0 * math.pi * k / spec.output_pin_count
                    rings.append(BearingRing(
                        spec.output_bolt_circle_radius * math.cos(angle),
                        spec.output_bolt_circle_radius * math.sin(angle), z0, z1))
        if rings:
            out.append(BearingPlacement(
                name="bearing_output_pins", label="Output pin rollers",
                role=roller.role, catalogue=roller.bearing.designation,
                bore=roller.bearing.bore, outer=spec.output_pin_diameter,
                rings=tuple(rings), host="output_flange"))

    # 3. Ring pin rollers.  The sleeve's OD is the working pin surface - the
    # profile is cut to the radius the disc touches - so it takes the pin's
    # outside and the pin proper shrinks to whatever is left of the bore.  Drawn
    # only when a catalogue needle fits, for the reason in the docstring.
    ring = by_role.get("Ring pin roller")
    if ring is not None and ring.bearing is not None:
        rings = []
        for z0, z1 in _courses(0.0, spec.stack_height, ring.bearing.width):
            for k in range(spec.pin_count):
                angle = 2.0 * math.pi * k / spec.pin_count
                rings.append(BearingRing(spec.pin_circle_radius * math.cos(angle),
                                         spec.pin_circle_radius * math.sin(angle),
                                         z0, z1))
        # Hosted on the pins rather than the housing.  Nothing presses a sleeve
        # into the ring - it rides on the pin - so pulling the pins out of an
        # exploded view has to take their sleeves with them.
        out.append(BearingPlacement(
            name="bearing_ring_pins", label="Ring pin rollers", role=ring.role,
            catalogue=ring.bearing.designation, bore=ring.bearing.bore,
            outer=2.0 * spec.pin_radius, rings=tuple(rings), host="ring_pins"))

    # 4. Input shaft supports.  Each sits against the end of the drive and grows
    # outward along the shaft: one on the housing face, one on the outboard face
    # of the carrier.  What holds their outer rings is an end plate the model
    # does not have, so they are hosted on the housing - which is where that
    # plate would be, and which keeps them still while the shaft pulls out of
    # them in an exploded view.  A support the drawn shaft is too short to carry
    # is left out rather than moved somewhere it would fit.
    support = by_role.get("Input shaft support")
    if support is not None and support.bearing is not None:
        width = support.bearing.width
        outboard = -CARRIER_DROP - spec.output_flange_thickness
        candidates = [(spec.stack_height, spec.stack_height + width),
                      (outboard - width, outboard)]
        shaft = (-SHAFT_OVERHANG, spec.stack_height + SHAFT_OVERHANG)
        rings = [BearingRing(0.0, 0.0, z0, z1) for z0, z1 in candidates
                 if shaft[0] <= z0 and z1 <= shaft[1]]
        if rings:
            out.append(BearingPlacement(
                name="bearing_shaft_supports", label="Input shaft supports",
                role=support.role, catalogue=support.bearing.designation,
                bore=support.bearing.bore, outer=support.bearing.outer,
                rings=tuple(rings), host="housing"))

    return out
