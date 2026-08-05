"""The parts the contact model used to call rigid.

:mod:`cycloidgen.analysis.stiffness` used to solve the two contact stages and
say so plainly: everything else - housing, shaft, carrier plate, pins in bending
- taken as rigid, and the answer an upper bound.  That was the largest known
error in the model, and it was not a small one: putting these springs in costs a
printed drive nearly half its stiffness and a ground steel one nine tenths.

This module supplies the missing springs.  Each is a closed form off the
geometry the app already has, each says what it assumes, and each is reported on
its own line so that a number nobody believes can be argued with rather than
guessed at.

Where the torque actually goes
------------------------------
Hold the input and twist the output.  The load leaves the output flange, crosses
the carrier pins into the discs, crosses the discs to their rims, and goes out
through the ring pins into the housing and its mounting face.  Every part on
that path is a spring in series:

===============  ===========================================================
Part             Modelled as
===============  ===========================================================
Carrier plate    an annulus in in-plane torsion, bolt circle to rim
Output pins      cantilevers off the plate, in bending and in shear
Disc body        an annulus in in-plane torsion, holes out to the rim
Housing          a barrel in torsion, picking the load up along the stack
Input shaft      a bar in torsion, divided by the square of the ratio
===============  ===========================================================

The ring pins are missing from that table on purpose.  They sit half-buried in
pockets cut to their own radius, supported along their whole length, so they do
not act as beams - what gives is the *seat*, and a seat is a contact.  It is
modelled where the other contacts are.

Two of these need their assumption stated out loud, because the geometry does
not decide it:

* **The carrier plate is rim-driven.** Its centre bore is clearance for the
  input shaft passing through, not a hub, so the output is taken off its face
  near the rim and the torque crosses only the 6 mm or so between the bolt
  circle and the edge.  That is stiff.  A drive that instead takes its output
  from a hub on the axis makes the torque cross the whole plate inward, and the
  ``1/r**2`` in the formula below is brutal about it: the same plate is an order
  of magnitude softer that way.  If that is the drive you are building, this
  number is optimistic and the fix is a thicker plate or a proper hub.
* **The load reaches the carrier pins at the middle of the stack.**  A pin
  really carries each disc at its own height, and the discs share one carrier,
  so a rigorous treatment would let the far disc shed load to the near one
  through the pin's own bending.  Taking the load at the centroid of the stack
  instead is one spring rather than a coupled set, and it is exact for the
  single-disc case that has nothing to couple.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..core import profile as prof
from ..core.spec import GearSpec, Material

__all__ = [
    "PartStiffness",
    "StructureStiffness",
    "analyse_parts",
    "annulus_torsion_stiffness",
    "barrel_torsion_stiffness",
    "cantilever_stiffness",
    "series_stiffness",
    "shear_modulus",
]


def series_stiffness(*stiffnesses: float) -> float:
    """Springs end to end: compliances add, so the reciprocals do.

    ``inf`` is the identity - a part modelled as rigid contributes nothing - and
    a zero anywhere makes the whole thing zero, which is what a stage with no
    contact carrying load actually is.
    """
    compliance = 0.0
    for k in stiffnesses:
        if k <= 0.0:
            return 0.0
        if math.isfinite(k):
            compliance += 1.0 / k
    return 1.0 / compliance if compliance > 0.0 else math.inf


def shear_modulus(mat: Material) -> float:
    """G in MPa, from E and Poisson's ratio for an isotropic material."""
    return mat.E_GPa * 1000.0 / (2.0 * (1.0 + mat.nu))


def annulus_torsion_stiffness(G_MPa: float, thickness_mm: float,
                              r_inner_mm: float, r_outer_mm: float) -> float:
    """Torsional stiffness of a flat annulus loaded in its own plane, Nmm/rad.

    A plate carrying torque between two radii is in pure shear, and the shear
    stress at radius r is ``T / (2*pi*r**2*t)``.  Integrating the resulting
    ``d(theta)/dr = tau / (G*r)`` between the two radii gives

        theta = T / (4*pi*G*t) * (1/r_i**2 - 1/r_o**2)

    which is dominated by whichever radius is *smaller*: torque funnelled into a
    small hub is what makes plates feel soft, and the same plate driven near its
    rim is stiff.  That is the whole story of the carrier plate assumption.
    """
    r_i, r_o = min(r_inner_mm, r_outer_mm), max(r_inner_mm, r_outer_mm)
    if r_i <= 0.0 or r_o <= r_i or G_MPa <= 0.0 or thickness_mm <= 0.0:
        return math.inf
    compliance = (1.0 / r_i ** 2 - 1.0 / r_o ** 2) / (4.0 * math.pi * G_MPa * thickness_mm)
    return 1.0 / compliance if compliance > 0.0 else math.inf


def barrel_torsion_stiffness(G_MPa: float, polar_moment_mm4: float,
                             length_mm: float) -> float:
    """Torsional stiffness of a prismatic bar or tube, ``G*J/L``, Nmm/rad."""
    if length_mm <= 0.0 or polar_moment_mm4 <= 0.0 or G_MPa <= 0.0:
        return math.inf
    return G_MPa * polar_moment_mm4 / length_mm


def cantilever_stiffness(E_MPa: float, nu: float, diameter_mm: float,
                         length_mm: float) -> float:
    """Tip stiffness of a round cantilever, N/mm, bending *and* shear.

    The shear term is not a refinement here.  These pins are stubby - a 6 mm pin
    reaching 8 mm out of a carrier - and at that aspect ratio shear is a quarter
    of the deflection again.  Timoshenko's coefficient for a solid circle,
    ``6(1+nu)/(7+6nu)``, is exact enough to be worth using over a round number.
    """
    if diameter_mm <= 0.0 or E_MPa <= 0.0:
        return math.inf
    if length_mm <= 0.0:
        return math.inf
    r = diameter_mm / 2.0
    area = math.pi * r * r
    second_moment = 0.25 * math.pi * r ** 4
    G = E_MPa / (2.0 * (1.0 + nu))
    kappa = 6.0 * (1.0 + nu) / (7.0 + 6.0 * nu)
    flexibility = (length_mm ** 3 / (3.0 * E_MPa * second_moment)
                   + length_mm / (kappa * G * area))
    return 1.0 / flexibility if flexibility > 0.0 else math.inf


@dataclass
class StructureStiffness:
    """What each part outside the contacts is worth, Nm/arcmin at the output.

    Reported one part at a time on purpose.  A single "everything else" number
    would be a number to distrust; six named ones say which part to make thicker,
    and the softest of them is usually a surprise.
    """

    ring_seat_Nm_per_arcmin: float
    housing_Nm_per_arcmin: float
    disc_body_Nm_per_arcmin: float
    output_pin_Nm_per_arcmin: float
    carrier_plate_Nm_per_arcmin: float
    input_shaft_Nm_per_arcmin: float

    #: Display names, in the order the torque meets them on its way out of the
    #: drive - starting at the flange you bolt the load to.  The input shaft is
    #: last because it is on a branch of its own, not on that path.
    NAMES = (("carrier_plate_Nm_per_arcmin", "carrier plate"),
             ("output_pin_Nm_per_arcmin", "carrier pins"),
             ("disc_body_Nm_per_arcmin", "disc body"),
             ("ring_seat_Nm_per_arcmin", "ring pin seats"),
             ("housing_Nm_per_arcmin", "housing"),
             ("input_shaft_Nm_per_arcmin", "input shaft"))

    @property
    def items(self) -> list[tuple[str, float]]:
        """``(name, stiffness)`` for every part, in torque-path order."""
        return [(label, getattr(self, field)) for field, label in self.NAMES]

    @property
    def total_Nm_per_arcmin(self) -> float:
        return series_stiffness(*(k for _label, k in self.items))

    @property
    def softest(self) -> str:
        """The part that gives way first - the one worth making thicker."""
        return min(self.items, key=lambda kv: kv[1])[0]


@dataclass
class PartStiffness:
    """Springs for the parts outside the contacts, in their own natural units.

    Torsional terms are Nmm/rad **at the output**, which is where the whole
    model refers everything; ``output_pin_N_per_mm`` is one pin's tip stiffness,
    because turning that into a torsional stiffness needs the moment arms of the
    pins that are actually carrying and only the contact solve knows those.
    """

    housing_Nmm_per_rad: float
    disc_body_Nmm_per_rad: float          # the whole stack, discs in parallel
    carrier_plate_Nmm_per_rad: float
    input_shaft_Nmm_per_rad: float        # already referred to the output
    output_pin_N_per_mm: float            # one pin, at the load plane


def analyse_parts(spec: GearSpec) -> PartStiffness:
    """Every structural spring in the torque path, off the geometry."""
    housing_G = shear_modulus(spec.housing_mat)

    # ---- housing barrel -----------------------------------------------------
    # Annulus from the pin bore out to the skin, less the half-round pockets the
    # pins sit in - they are cut at the bore, where the material earns the most.
    r_i, r_o = spec.pin_circle_radius, spec.housing_outer_radius
    polar = 0.5 * math.pi * (r_o ** 4 - r_i ** 4)
    polar -= spec.pin_count * (0.5 * math.pi * spec.pin_radius ** 2) * r_i ** 2
    # The ring picks the reaction up along the stack and carries it to a face at
    # one end, so the average length under load is half the stack, not all of it.
    housing = barrel_torsion_stiffness(housing_G, max(polar, 1e-9),
                                       max(spec.stack_height / 2.0, 1e-9))

    # ---- disc body ----------------------------------------------------------
    # Each disc carries the torque from its rim in to the output holes.  An
    # annulus is generous about a part with a ring of holes through it at the
    # inner radius, which is the same place the formula is most sensitive.
    root_r = prof.profile_from_spec(spec, n=2000).root_radius
    disc_body = spec.disc_count * annulus_torsion_stiffness(
        shear_modulus(spec.disc_mat), spec.disc_thickness,
        spec.output_bolt_circle_radius, root_r)

    # ---- carrier plate ------------------------------------------------------
    # Rim-driven; see the module docstring for what that assumes and costs.
    plate = annulus_torsion_stiffness(
        housing_G, spec.output_flange_thickness,
        spec.output_bolt_circle_radius,
        spec.output_bolt_circle_radius + spec.output_pin_diameter)

    # ---- input shaft --------------------------------------------------------
    # With the input held, the crank still takes the input torque, and a crank
    # that gives way lets the output turn by its rotation over the ratio.  Both
    # the torque and the angle are divided by the ratio, so the compliance
    # referred to the output is divided by the *square* of it - which is why a
    # shaft that would be hopeless as an output shaft is fine as an input one.
    overhang = 12.0                                   # as modelled in export.solid
    shaft_polar = 0.5 * math.pi * (spec.input_shaft_diameter / 2.0) ** 4
    shaft = barrel_torsion_stiffness(shear_modulus(spec.shaft_mat), shaft_polar,
                                     spec.stack_height + 2.0 * overhang)
    shaft *= float(spec.ratio) ** 2

    # ---- carrier pins -------------------------------------------------------
    pin = cantilever_stiffness(spec.pin_mat.E_GPa * 1000.0, spec.pin_mat.nu,
                               spec.output_pin_diameter,
                               max(spec.stack_height / 2.0, 1e-9))

    return PartStiffness(housing_Nmm_per_rad=housing,
                         disc_body_Nmm_per_rad=disc_body,
                         carrier_plate_Nmm_per_rad=plate,
                         input_shaft_Nmm_per_rad=shaft,
                         output_pin_N_per_mm=pin)
