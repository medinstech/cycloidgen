"""Mass, inertia, rotating unbalance and the disc's own structure.

Everything here comes off the sampled profile rather than off a cylinder
approximation: the disc is a lobed annulus with a bore and a ring of holes
through it, and treating it as a solid disc overstates its mass by a third.

Three questions get answered:

* **How heavy is it, and what does that buy?**  Torque capacity per kilogram is
  the number that actually compares a cycloidal drive against the planetary it
  is competing with.
* **What does the crank have to throw around?**  A disc orbiting at radius E is
  an unbalanced mass, and the force it develops goes as the *square* of input
  speed - which is why one disc is fine at 200 rpm and shakes itself apart at
  4000.  Two discs at 180 degrees cancel the force but leave a couple.
* **Will the web hold?**  Output pin load has to cross the ligament between the
  hole and the nearest free surface.  That ligament is the thinnest structural
  member in the whole drive and nothing else in the app looks at it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..core import profile as prof
from ..core.spec import GearSpec
from .bearings import pin_diameters

__all__ = ["MassResult", "analyse_mass"]

_MM3_TO_CM3 = 1e-3


@dataclass
class MassResult:
    """Mass properties and the disc web check."""

    disc_mass_g: float                 # one disc
    disc_volume_cm3: float
    total_mass_g: float
    housing_mass_g: float               # the barrel alone
    plates_mass_g: float                # both end plates together
    pins_mass_g: float
    shaft_mass_g: float
    flange_mass_g: float

    disc_inertia_kg_mm2: float         # about its own centre
    reflected_inertia_kg_mm2: float    # whole stack, seen at the input shaft

    unbalance_force_N: float           # residual, at the rated input speed
    unbalance_couple_Nmm: float
    balanced: bool

    web_shear_MPa: float
    web_shear_allow_MPa: float
    hole_bearing_MPa: float
    min_web_mm: float

    @property
    def web_safety_factor(self) -> float:
        return (self.web_shear_allow_MPa / self.web_shear_MPa
                if self.web_shear_MPa > 0 else float("inf"))

    def power_density_Nm_per_kg(self, torque_capacity_Nm: float) -> float:
        kg = self.total_mass_g / 1000.0
        return torque_capacity_Nm / kg if kg > 0 else 0.0


def _disc_section(spec: GearSpec) -> tuple[float, float]:
    """Cross-sectional area and polar second moment of one disc, mm^2 and mm^4."""
    p = prof.profile_from_spec(spec, n=4000)
    area = p.area()
    polar = p.polar_second_moment()

    bore_r = (spec.center_bore_diameter + spec.hole_clearance) / 2.0
    area -= math.pi * bore_r ** 2
    polar -= 0.5 * math.pi * bore_r ** 4

    hole_r = spec.output_hole_diameter / 2.0
    d = spec.output_bolt_circle_radius
    hole_area = math.pi * hole_r ** 2
    # parallel axis: each hole sits a bolt-circle radius off the disc centre
    hole_polar = 0.5 * math.pi * hole_r ** 4 + hole_area * d * d
    area -= spec.output_pin_count * hole_area
    polar -= spec.output_pin_count * hole_polar

    return max(area, 0.0), max(polar, 0.0)


def analyse_mass(spec: GearSpec) -> MassResult:
    """Mass, inertia, unbalance and the disc web stress."""
    area, polar = _disc_section(spec)
    t = spec.disc_thickness
    n = spec.disc_count

    rho_disc = spec.disc_mat.density_g_cm3
    rho_house = spec.housing_mat.density_g_cm3
    rho_pin = spec.pin_mat.density_g_cm3
    rho_shaft = spec.shaft_mat.density_g_cm3

    disc_volume = area * t                                    # mm^3
    disc_mass = disc_volume * _MM3_TO_CM3 * rho_disc          # g

    # ---- the rest of the parts ---------------------------------------------
    h = spec.stack_height
    ring_area = math.pi * (spec.housing_outer_radius ** 2 - spec.pin_circle_radius ** 2)
    pocket_area = spec.pin_count * 0.5 * math.pi * spec.pin_radius ** 2
    # Every hole through the barrel, not just the ones the pins sit in: the tie
    # bolts run its whole length too, and a mass model that knows about one set
    # and not the other is describing a different part from the one the exporter
    # writes.
    bolt_area = (spec.housing_bolt_count * math.pi
                 * (spec.housing_bolt_diameter / 2.0) ** 2)
    # The barrel is longer than the disc stack: it reaches down past the carrier
    # to the output end plate it bolts to.  The pins are not - they only have to
    # span the discs - which is why these two lengths are different.
    # Integral pins are the housing, so the barrel gains the half-moons it
    # would otherwise have had cut out of it - and gains them in the *housing's*
    # material, which on a printed drive is the whole point of the option and
    # is lighter than the steel dowels it replaces.
    pins_in_barrel = pocket_area if spec.ring_pins_integral else -pocket_area
    housing_mass = (max(ring_area + pins_in_barrel - bolt_area, 0.0)
                    * spec.barrel_height * _MM3_TO_CM3 * rho_house)

    # Each pin at its own length and its own diameter, and neither length is the
    # disc stack: a ring pin spans the barrel it is trapped in, an output pin the
    # drop it crosses plus the discs it drives.  Weighing both off
    # ``stack_height`` was the same assumption the bill of materials was making,
    # and it is 41% light on the ring pins of a 21:1.
    ring_pin_d, output_pin_d = pin_diameters(spec)
    pins_volume = (0.0 if spec.ring_pins_integral else
                   spec.pin_count * math.pi * (ring_pin_d / 2.0) ** 2
                   * spec.ring_pin_length)
    pins_volume += (spec.output_pin_count * math.pi * (output_pin_d / 2.0) ** 2
                    * spec.output_pin_length)
    pins_mass = pins_volume * _MM3_TO_CM3 * rho_pin

    shaft_volume = math.pi * (spec.input_shaft_diameter / 2.0) ** 2 * (h + 2 * spec.shaft_overhang)
    cam_extra = n * math.pi * ((spec.cam_diameter / 2.0) ** 2
                               - (spec.input_shaft_diameter / 2.0) ** 2) * t
    shaft_mass = (shaft_volume + max(cam_extra, 0.0)) * _MM3_TO_CM3 * rho_shaft

    plate_r = spec.output_bolt_circle_radius + spec.output_pin_diameter
    flange_volume = math.pi * plate_r ** 2 * spec.output_flange_thickness
    # Plus the boss the drive turns on, bored through for the shaft, and less
    # that same bore through the plate.
    flange_volume += math.pi * ((spec.hub_diameter / 2.0) ** 2
                                - (spec.hub_bore / 2.0) ** 2) * spec.plate_thickness
    flange_volume -= math.pi * (spec.hub_bore / 2.0) ** 2 * spec.output_flange_thickness
    # And, on a ring-output drive, the base on the end of that boss - the plate
    # the whole gearbox is bolted down by.  It is housing-sized and as thick as
    # an end plate, so on a small drive it is a fifth of the assembled mass;
    # leaving it out would report a gearbox lighter than the one exported.
    if spec.mount_base_fitted:
        flange_volume += math.pi * (spec.housing_outer_radius ** 2
                                    - (spec.hub_bore / 2.0) ** 2) * spec.plate_thickness
        if spec.has_motor_face:
            frame = spec.motor
            flange_volume -= (frame.bolt_count * math.pi
                              * (frame.bolt_diameter / 2.0) ** 2
                              * spec.plate_thickness)
    flange_mass = max(flange_volume, 0.0) * _MM3_TO_CM3 * rho_house

    # The two plates that close the housing.  They are part of the gearbox and
    # were simply not weighed: on the 21:1 preset they are a third of it.
    #
    # Reported beside the barrel rather than folded into it.  They are a separate
    # part with its own line on the bill of materials, and while the two were one
    # number that line had to quote zero - a made part that weighs nothing.
    outer_area = math.pi * spec.housing_outer_radius ** 2
    # The output bolts go through one of the two, so they come off once - the
    # same accounting the tie bolts get for going through both.
    output_bolt_area = (spec.output_bolt_count * math.pi
                        * (spec.output_bolt_diameter / 2.0) ** 2
                        if spec.mount_base_fitted else 0.0)
    plates_volume = (2.0 * outer_area
                     - math.pi * (spec.hub_bore / 2.0) ** 2
                     - math.pi * (spec.output_bearing_seat_diameter / 2.0) ** 2
                     - 2.0 * bolt_area          # the tie bolts go through both
                     - output_bolt_area
                     ) * spec.plate_thickness
    plates_mass = max(plates_volume, 0.0) * _MM3_TO_CM3 * rho_house

    total = (n * disc_mass + housing_mass + plates_mass + pins_mass
             + shaft_mass + flange_mass)

    # ---- inertia ------------------------------------------------------------
    # kg*mm^2:  g/cm^3 * mm^4 * 1e-3 (cm^3/mm^3) / 1e3 (kg/g) = 1e-6
    disc_inertia = polar * t * rho_disc * 1e-6
    m_disc_kg = disc_mass / 1000.0
    # Each disc orbits at radius E - at the input speed exactly, whichever
    # member is grounded, because the orbit is the crank's own motion seen from
    # the axis - and spins at `disc_speed_ratio` of the input.  That second term
    # is 1/N off the carrier and *zero* off the ring, where the disc does not
    # rotate in the ground frame at all: a ring-output drive reflects only the
    # orbiting mass back to the motor.
    reflected = n * (m_disc_kg * spec.eccentricity ** 2
                     + disc_inertia * spec.disc_speed_ratio ** 2)

    # ---- unbalance ----------------------------------------------------------
    omega = spec.input_rpm * 2.0 * math.pi / 60.0
    single = m_disc_kg * (spec.eccentricity / 1000.0) * omega ** 2   # N, one disc
    phases = np.asarray(spec.disc_phases)
    resultant = float(np.hypot(np.cos(phases).sum(), np.sin(phases).sum()))
    force = single * resultant
    # Evenly phased discs cancel the force but leave a couple: equal and opposite
    # forces a disc pitch apart.  N in, mm arms, so the sum is already Nmm.
    pitch = t + spec.disc_gap
    offsets = (np.arange(n) - (n - 1) / 2.0) * pitch
    couple = float(np.hypot((single * np.cos(phases) * offsets).sum(),
                            (single * np.sin(phases) * offsets).sum()))

    # ---- disc web -----------------------------------------------------------
    hole_r = spec.output_hole_diameter / 2.0
    bore_r = (spec.center_bore_diameter + spec.hole_clearance) / 2.0
    p = prof.profile_from_spec(spec, n=4000)
    web_inner = spec.output_bolt_circle_radius - hole_r - bore_r
    web_outer = p.root_radius - (spec.output_bolt_circle_radius + hole_r)
    web_side = (2.0 * spec.output_bolt_circle_radius
                * math.sin(math.pi / spec.output_pin_count)) - 2.0 * hole_r
    min_web = min(web_inner, web_outer, web_side)

    # the pin's share of torque has to shear out through the thinnest ligament
    # on both sides of the hole
    from ..core.kinematics import output_loads, output_sweep_angles
    peak = 0.0
    # over the output stage's own period, which is about twice a lobe pitch -
    # the window this used to sweep, and so half the cycle the peak is in
    for phi in output_sweep_angles(spec.lobes, spec.output_pin_count, 48):
        f = output_loads(spec, float(phi), spec.output_torque_Nm * 1000.0 / n).forces
        if f.size:
            peak = max(peak, float(f.max()))
    shear_area = max(2.0 * min_web * t, 1e-9)
    web_shear = peak / shear_area
    hole_bearing = peak / max(spec.output_pin_diameter * t, 1e-9)

    return MassResult(
        disc_mass_g=disc_mass,
        disc_volume_cm3=disc_volume * _MM3_TO_CM3,
        total_mass_g=total,
        housing_mass_g=housing_mass,
        plates_mass_g=plates_mass,
        pins_mass_g=pins_mass,
        shaft_mass_g=shaft_mass,
        flange_mass_g=flange_mass,
        disc_inertia_kg_mm2=disc_inertia,
        reflected_inertia_kg_mm2=reflected,
        unbalance_force_N=force,
        unbalance_couple_Nmm=couple,
        balanced=resultant < 1e-9,
        web_shear_MPa=web_shear,
        web_shear_allow_MPa=spec.disc_mat.shear_allow_MPa,
        hole_bearing_MPa=hole_bearing,
        min_web_mm=min_web,
    )
