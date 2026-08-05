"""Bearing sizing help for the three load paths in a cycloidal drive.

Catalogue values are nominal metric-series figures and are meant for first-pass
selection only; confirm against the manufacturer's data before ordering.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.spec import GearSpec

__all__ = ["CATALOGUE", "Bearing", "BearingChoice", "select_bearings"]


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

    @property
    def ok(self) -> bool:
        return self.bearing is not None and self.life_hours >= 1000.0


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


def _pick(bore_min: float, outer_max: float, width_max: float,
          load_N: float, rpm: float, kinds: tuple[str, ...]) -> Bearing | None:
    """Smallest catalogue bearing that fits the envelope and lasts 1000 h."""
    candidates = [
        b for b in CATALOGUE
        if b.kind in kinds
        and b.bore >= bore_min - 1e-6
        and b.outer <= outer_max + 1e-6
        and b.width <= width_max + 1e-6
        and _life_hours(b, load_N, rpm) >= 1000.0
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda b: (b.outer, b.width))


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
    b = _pick(spec.cam_diameter, spec.center_bore_diameter,
              spec.disc_thickness, eccentric_load_N, rpm, ("needle", "ball"))
    out.append(BearingChoice(
        role="Eccentric cam bearing", count=spec.disc_count,
        bearing=b, load_N=eccentric_load_N, speed_rpm=rpm,
        life_hours=_life_hours(b, eccentric_load_N, rpm) if b else 0.0,
        carries="the radial force the disc pushes back into the crank",
        seat=f"on the {spec.cam_diameter:.1f} mm cam, inside the "
             f"{spec.center_bore_diameter:.1f} mm disc bore",
        note=("" if b else
              "no catalogue bearing fits: enlarge the central bore or thicken the disc"),
    ))

    # 2. output pin rollers - optional, and the biggest single sliding loss
    if spec.output_pins_are_rollers:
        outer = spec.output_hole_diameter - 2 * spec.eccentricity
        b2 = _pick(spec.output_pin_diameter, outer, spec.disc_thickness,
                   output_pin_load_N, spec.input_rpm, ("needle",))
        out.append(BearingChoice(
            role="Output pin roller",
            count=spec.output_pin_count * spec.disc_count,
            bearing=b2, load_N=output_pin_load_N, speed_rpm=spec.input_rpm,
            life_hours=_life_hours(b2, output_pin_load_N, spec.input_rpm) if b2 else 0.0,
            carries="one pin's share of the output torque",
            seat=f"on each {spec.output_pin_diameter:.1f} mm output pin, one per "
                 f"disc, running in the {spec.output_hole_diameter:.1f} mm hole",
            note=("" if b2 else "no roller fits; use a plain bronze bushing instead"),
        ))
    else:
        out.append(BearingChoice(
            role="Output pin roller", count=0, bearing=None,
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
        b4 = _pick(0.0, outer, spec.stack_height, ring_pin_load_N,
                   roller_rpm, ("needle",))
        out.append(BearingChoice(
            role="Ring pin roller", count=spec.pin_count,
            bearing=b4, load_N=ring_pin_load_N, speed_rpm=roller_rpm,
            life_hours=_life_hours(b4, ring_pin_load_N, roller_rpm) if b4 else 0.0,
            carries="the lobe load as each tooth sweeps past",
            seat=f"over each ring pin, {2 * spec.pin_radius:.1f} mm OD working "
                 f"surface, {spec.stack_height:.1f} mm long",
            note=("" if b4 else
                  "no drawn-cup needle is this small: use a hardened sleeve turning "
                  "on a smaller pin, which is what most builds at this size do"),
        ))

    # 4. input shaft support - two of them, and until now nothing held the shaft
    # at all.  The cam sits between them, so each takes about half of what the
    # discs push back; an overhung cam loads the inner one far harder and this
    # does not model that.
    shaft_load = eccentric_load_N * spec.disc_count / 2.0
    b5 = _pick(spec.input_shaft_diameter,
               2.0 * (spec.pin_circle_radius - spec.pin_radius),
               spec.housing_wall * 2.0, shaft_load, spec.input_rpm, ("ball",))
    out.append(BearingChoice(
        role="Input shaft support", count=2,
        bearing=b5, load_N=shaft_load, speed_rpm=spec.input_rpm,
        life_hours=_life_hours(b5, shaft_load, spec.input_rpm) if b5 else 0.0,
        carries="half the crank reaction each, plus whatever the driving "
                "coupling adds",
        seat=f"in the housing end plates, on the {spec.input_shaft_diameter:.1f} mm "
             f"input shaft either side of the disc stack",
        note=("" if b5 else
              "nothing in the catalogue fits between the shaft and the pin circle: "
              "a deeper housing or a smaller shaft"),
    ))

    # 5. main output bearing - carries the external load, turns slowly
    radial = output_pin_load_N * spec.output_pin_count / 2.0
    b3 = _pick(spec.center_bore_diameter, spec.housing_outer_radius * 2.0,
               spec.housing_wall * 2.0, radial, spec.output_rpm, ("ball",))
    out.append(BearingChoice(
        role="Main output bearing", count=1,
        bearing=b3, load_N=radial, speed_rpm=spec.output_rpm,
        life_hours=_life_hours(b3, radial, spec.output_rpm) if b3 else 0.0,
        carries="whatever the machine hangs on the output flange",
        seat="between the output flange and the housing - a seat this app does "
             "not yet model, so treat the size as a first pass",
        note=("" if b3 else
              "consider a crossed-roller or a pair of angular contact bearings"),
    ))
    return out
