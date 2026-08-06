"""Lubrication regime: the film, and the friction coefficient it earns.

What this replaces
------------------
One number, ``spec.friction_coefficient``, used to carry efficiency, PV and
running temperature between them.  It is a reasonable dry figure and it is a
guess in every other case: it does not know how fast the surfaces are moving,
how hard they are pressed together, what is between them, or how hot it has got.

This module works the number out instead.  At each sliding contact it builds the
elastohydrodynamic film, measures it against the roughness of the surfaces it is
supposed to separate, and returns the friction coefficient that follows.  What
comes out is not a better guess but a different kind of answer: a **regime**,
with a film thickness and a lambda ratio behind it, that says *why* the contact
costs what it costs and what would change it.

The model
---------
1. **Viscosity at temperature.**  Walther / ASTM D341 through the two points
   every oil is sold with, 40 and 100 C.  Temperature matters more than anything
   else here and it is not an input: the drive heats itself, so the operating
   point is a fixed point, solved in :mod:`cycloidgen.analysis.thermal`.

2. **Film thickness.**  Dowson-Hamrock for a line contact,

       h_min / R' = 2.65 * U^0.7 * G^0.54 * W^-0.13

   with the speed, materials and load groups built from the entrainment
   velocity, the pressure-viscosity coefficient and the load per unit length.
   The contact is a line because every one of them here is a cylinder the width
   of the disc.

3. **Lambda.**  ``h_min`` over the composite RMS roughness.  This is the whole
   answer: a film is not thick or thin in micrometres, it is thick or thin
   *compared with the peaks it has to clear*.

4. **Friction.**  Boundary and full-film coefficients blended by how much load
   the asperities are still carrying.  The full-film value is a constant and
   deserves to be: an EHL contact shears its oil at a limiting stress that
   barely moves with speed or load, which is why measured traction coefficients
   sit in a narrow band.  The boundary value is the lubricant's, and it is the
   one worth choosing - it is the additive package, not the base oil.

What it says about this machine
-------------------------------
Mostly that fixed pins do not get a film.  A fixed ring pin is a stationary
surface with the disc flank sweeping across it, so the entrainment velocity is
half the sliding velocity - the contact is dragged, not rolled - and at the
loads in a cycloidal mesh the film comes out at a few tens of nanometres against
a roughness of hundreds.  That holds for ground steel and is not close for
anything printed, where the flank is two orders of magnitude rougher than the
best film any lubricant sold will build.

That is not a defect in the model.  It is why cycloidal drives that have to last
put needle rollers on the ring pins, and it is the quantitative form of a choice
this app previously offered as two different constants.  What lubricant to use
is still worth answering, because boundary friction is what an EP additive is
for: moly grease against dry is a factor of two on every sliding loss in the
drive, without a film ever forming.

Not modelled: starvation, grease channelling, thermal thinning inside the
contact, and the transient film at start-up.  All of them make it worse rather
than better, so a contact this module places in the boundary regime is there.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.spec import DRY, GearSpec, Lubricant, Material

__all__ = [
    "FULL_FILM_LAMBDA",
    "TRACTION_COEFFICIENT",
    "ContactFilm",
    "LubricationResult",
    "analyse_lubrication",
    "dynamic_viscosity_Pa_s",
    "film_thickness_um",
    "reduced_modulus_Pa",
]

#: Lambda above which the surfaces are fully separated and wear stops being a
#: wear-rate question.  The classical figure; below it some fraction of the load
#: is on the asperities.
FULL_FILM_LAMBDA = 3.0

#: Lambda below which the film carries nothing worth counting and the contact is
#: in boundary lubrication - additives and surface chemistry, not hydrodynamics.
BOUNDARY_LAMBDA = 0.5

#: Traction coefficient of a full elastohydrodynamic film in sliding.  A
#: constant, and one of the few in this app that deserves to be: the oil in a
#: loaded contact reaches a limiting shear stress of roughly 4% of the local
#: pressure and stays there, so measured traction barely moves with speed or
#: load.  This is *not* the same kind of number as the boundary coefficient,
#: which depends entirely on what is in the lubricant.
TRACTION_COEFFICIENT = 0.045

#: Kelvin at zero Celsius, for the viscosity fit, which is an absolute-temperature
#: correlation.
_KELVIN = 273.15

#: The 0.7 in Walther's equation.  Part of the correlation rather than a
#: modelling choice, and named so the formula reads as the published one.
_WALTHER_OFFSET = 0.7


@dataclass(frozen=True)
class ContactFilm:
    """One sliding contact, and what the lubricant does at it."""

    name: str
    #: ``False`` when the contact does not slide - a roller in place of a fixed
    #: pin, a needle between the cam and the bore.  Then there is no film to
    #: report rather than a thick one, the same way PV is not reported for a
    #: contact that rolls.
    slides: bool
    film_um: float
    roughness_um: float
    #: Film over composite roughness.  The number the regime is read from.
    lambda_ratio: float
    pressure_MPa: float
    entrainment_m_s: float
    sliding_speed_m_s: float
    mu: float

    @property
    def regime(self) -> str:
        if not self.slides:
            return "rolling"
        if self.lambda_ratio >= FULL_FILM_LAMBDA:
            return "full film"
        if self.lambda_ratio >= 1.0:
            return "mixed"
        if self.lambda_ratio >= BOUNDARY_LAMBDA:
            return "thin mixed"
        return "boundary"

    @property
    def separated(self) -> bool:
        """Whether the surfaces are actually apart.  Below this they touch."""
        return self.slides and self.lambda_ratio >= FULL_FILM_LAMBDA


@dataclass(frozen=True)
class LubricationResult:
    """The regime at every sliding contact, at one operating temperature."""

    lubricant: str
    temperature_C: float
    viscosity_cSt: float
    contacts: tuple[ContactFilm, ...]

    def __getitem__(self, name: str) -> ContactFilm:
        for c in self.contacts:
            if c.name == name:
                return c
        raise KeyError(name)

    @property
    def sliding(self) -> tuple[ContactFilm, ...]:
        return tuple(c for c in self.contacts if c.slides)

    @property
    def governing(self) -> ContactFilm | None:
        """The sliding contact with the least film to spare.

        The one to quote and the one to fix: a drive is no better lubricated
        than its thinnest film, and which contact that is moves with the design.
        """
        return min(self.sliding, key=lambda c: c.lambda_ratio, default=None)

    @property
    def forms_a_film(self) -> bool:
        """Whether any sliding contact is even partly carried by a film."""
        return any(c.lambda_ratio >= BOUNDARY_LAMBDA for c in self.sliding)


def dynamic_viscosity_Pa_s(lube: Lubricant, temperature_C: float) -> float:
    """Dynamic viscosity at temperature, through Walther / ASTM D341.

    ``log10(log10(nu + 0.7)) = A - B log10(T)`` in kelvin, fitted through the 40
    and 100 C points the lubricant is sold with.  It is an extrapolation outside
    them and a poor one far outside, so the temperature is clamped to a band
    either side rather than allowed to return a viscosity of zero at the top end
    or an absurd one at the bottom.
    """
    if not lube.forms_a_film:
        return 0.0
    t = min(max(temperature_C, -20.0), 200.0) + _KELVIN

    def w(nu: float) -> float:
        return math.log10(math.log10(nu + _WALTHER_OFFSET))

    t1, t2 = 40.0 + _KELVIN, 100.0 + _KELVIN
    b = (w(lube.viscosity_40C_cSt) - w(lube.viscosity_100C_cSt)) / (
        math.log10(t2) - math.log10(t1))
    a = w(lube.viscosity_40C_cSt) + b * math.log10(t1)
    nu = 10.0 ** (10.0 ** (a - b * math.log10(t))) - _WALTHER_OFFSET
    # cSt is mm^2/s; Pa s = mm^2/s * 1e-6 m^2/mm^2 * g/cm^3 * 1000 kg/m^3
    return max(nu, 1e-6) * lube.density_g_cm3 * 1e-3


def reduced_modulus_Pa(a: Material, b: Material) -> float:
    """``E'`` for a contact between two materials.

    The softer one dominates, which is why a steel pin on a printed disc is a
    printed-disc contact: the pin barely deflects and the polymer takes the whole
    conformity.  A larger contact patch at a lower pressure builds *more* film
    for the same load, so this cuts the other way from every strength check in
    the app - the soft drive is the one whose surfaces separate more easily, and
    it still loses, because its roughness is worse by more than its modulus
    helps.
    """
    return 2.0 / ((1.0 - a.nu ** 2) / (a.E_GPa * 1e9)
                  + (1.0 - b.nu ** 2) / (b.E_GPa * 1e9))


def film_thickness_um(eta_Pa_s: float, alpha_1_per_Pa: float, e_prime_Pa: float,
                      reduced_radius_m: float, entrainment_m_s: float,
                      load_per_length_N_m: float) -> float:
    """Dowson-Hamrock minimum film thickness for a line contact, micrometres.

    ``h_min / R' = 2.65 U^0.7 G^0.54 W^-0.13``.  Every group is dimensionless and
    the exponents are the published ones; the shape of it is the useful part.
    Speed enters at 0.7 and load at only -0.13, which is why slowing a drive down
    to save a marginal film does not work and speeding it up to build one does:
    film is made by entrainment, and load barely takes it away.
    """
    if min(eta_Pa_s, alpha_1_per_Pa, e_prime_Pa, reduced_radius_m,
           entrainment_m_s, load_per_length_N_m) <= 0.0:
        return 0.0
    u = eta_Pa_s * entrainment_m_s / (e_prime_Pa * reduced_radius_m)
    g = alpha_1_per_Pa * e_prime_Pa
    w = load_per_length_N_m / (e_prime_Pa * reduced_radius_m)
    h_over_r = 2.65 * u ** 0.7 * g ** 0.54 * w ** -0.13
    return h_over_r * reduced_radius_m * 1e6


def _asperity_load_fraction(lambda_ratio: float) -> float:
    """How much of the load the peaks are still carrying, 1 down to 0.

    An engineering blend rather than a contact-mechanics solution: full at the
    boundary limit, zero once the film clears the roughness by the classical
    factor of three, and squared in between so it falls away quickly near full
    film, which is the shape a Stribeck curve has.  Interpolating a load share is
    the honest bit - the two coefficients it interpolates between are the ones
    with evidence behind them.
    """
    if lambda_ratio <= BOUNDARY_LAMBDA:
        return 1.0
    if lambda_ratio >= FULL_FILM_LAMBDA:
        return 0.0
    span = (FULL_FILM_LAMBDA - lambda_ratio) / (FULL_FILM_LAMBDA - BOUNDARY_LAMBDA)
    return span ** 2


def _contact(name: str, spec: GearSpec, *, slides: bool, mat_a: Material,
             mat_b: Material, reduced_radius_mm: float, load_N: float,
             length_mm: float, sliding_m_s: float, entrainment_m_s: float,
             temperature_C: float, clearance_mm: float | None = None
             ) -> ContactFilm:
    """Build one contact's film and the friction coefficient that follows.

    ``clearance_mm`` is the radial gap the two parts leave each other, and it is
    a ceiling on the film: oil cannot hold surfaces further apart than they can
    get.  It only ever binds at a conforming contact, which is exactly where the
    Dowson-Hamrock formula is being asked to do something it was not derived for
    - a close-fitting journal has a reduced radius of metres and the formula will
    happily return a film thicker than the bore.  Capping it at the clearance is
    the physical statement that the shaft is floating in the middle of its hole,
    which is the best a journal can do and is a real answer rather than an
    extrapolated one.
    """
    lube = spec.lube
    # Two surfaces, each with its own roughness, and what matters is the pair.
    # Both are given the design's figure: the app has one process, and a drive
    # whose pins are ground and whose disc is printed is beyond what a single
    # process field can say.
    sigma = math.sqrt(2.0) * spec.roughness_um
    # Dry is the one entry whose boundary coefficient belongs to the design
    # rather than to the table: it *is* ``friction_coefficient``, which is what
    # keeps every unlubricated design's numbers exactly where they were.
    boundary_mu = spec.friction_coefficient if lube.name == DRY else lube.boundary_mu

    if not slides:
        return ContactFilm(name=name, slides=False, film_um=0.0, roughness_um=sigma,
                           lambda_ratio=float("inf"), pressure_MPa=0.0,
                           entrainment_m_s=0.0, sliding_speed_m_s=0.0, mu=0.0)

    projected = max(2.0 * reduced_radius_mm * length_mm, 1e-9)
    pressure = load_N / projected

    if not lube.forms_a_film:
        # Dry, or a bonded film that works by shearing rather than separating.
        # No hydrodynamics to report and none pretended: lambda is zero and the
        # coefficient is the boundary one, which for the dry entry is the
        # design's own number - so a design that says nothing about lubrication
        # gets exactly the answer it got before this module existed.
        return ContactFilm(name=name, slides=True, film_um=0.0, roughness_um=sigma,
                           lambda_ratio=0.0, pressure_MPa=pressure,
                           entrainment_m_s=entrainment_m_s,
                           sliding_speed_m_s=sliding_m_s, mu=boundary_mu)

    h = film_thickness_um(
        eta_Pa_s=dynamic_viscosity_Pa_s(lube, temperature_C),
        alpha_1_per_Pa=lube.alpha_1_per_GPa * 1e-9,
        e_prime_Pa=reduced_modulus_Pa(mat_a, mat_b),
        reduced_radius_m=max(reduced_radius_mm, 1e-9) * 1e-3,
        entrainment_m_s=entrainment_m_s,
        load_per_length_N_m=load_N / max(length_mm * 1e-3, 1e-9),
    )
    if clearance_mm is not None:
        h = min(h, clearance_mm * 1000.0)
    lam = h / max(sigma, 1e-9)
    f = _asperity_load_fraction(lam)
    return ContactFilm(name=name, slides=True, film_um=h, roughness_um=sigma,
                       lambda_ratio=lam, pressure_MPa=pressure,
                       entrainment_m_s=entrainment_m_s,
                       sliding_speed_m_s=sliding_m_s,
                       mu=f * boundary_mu + (1.0 - f) * TRACTION_COEFFICIENT)


def analyse_lubrication(spec: GearSpec, ring_load_N: float, output_load_N: float,
                        cam_load_N: float, ring_sliding_m_s: float,
                        output_sliding_m_s: float, cam_sliding_m_s: float,
                        temperature_C: float | None = None) -> LubricationResult:
    """The regime at each of the three sliding contacts.

    The loads and sliding speeds come from the caller because they come from the
    kinematic sweep, which :mod:`cycloidgen.analysis.thermal` has already run -
    doing it again here would double the cost of an analysis to recompute
    numbers that are on the table.

    Entrainment is half the sliding speed at every one of these contacts, and
    that is the physically important line in this function.  A fixed pin does not
    move, so the mean of the two surface velocities is half of their difference:
    the film is being built by one surface dragging oil under a stationary one,
    which is the worst case of the two ways to run a contact.  Put a roller there
    and both surfaces move together - the sliding goes to nearly nothing and the
    entrainment doubles - which is a better film and less of it needed.
    """
    t = temperature_C if temperature_C is not None else spec.ambient_temp_C
    length = spec.disc_thickness

    # ---- ring pin on the disc flank -----------------------------------------
    # R' is the pin's own radius, which is the flat-counterface equivalent.  The
    # disc flank is convex against the pin in the valleys and concave over the
    # crests, so the true film runs thinner than this at one end of the cycle and
    # thicker at the other; a single number for a contact that sweeps the whole
    # flank has to sit between them.
    ring = _contact(
        "Ring pin / disc flank", spec, slides=not spec.ring_pins_are_rollers,
        mat_a=spec.pin_mat, mat_b=spec.disc_mat,
        reduced_radius_mm=spec.pin_radius, load_N=ring_load_N, length_mm=length,
        sliding_m_s=ring_sliding_m_s, entrainment_m_s=ring_sliding_m_s / 2.0,
        temperature_C=t)

    # ---- output pin in its hole ---------------------------------------------
    # Conforming, so the radii subtract and R' comes out far larger than either -
    # a pin in a hole barely larger than it is nearly a journal.  That is worth
    # more film than any lubricant choice, and it is the reason this contact is
    # rarely the governing one.
    # In practice it is barely conforming at all: the hole has to clear the
    # eccentricity as well as the fit, so it is millimetres larger than the pin
    # and the reduced radius comes out only a little above the pin's own.
    r_pin = spec.output_pin_diameter / 2.0
    r_hole = spec.output_hole_diameter / 2.0
    out = _contact(
        "Output pin / disc hole", spec, slides=not spec.output_pins_are_rollers,
        mat_a=spec.pin_mat, mat_b=spec.disc_mat,
        reduced_radius_mm=_conforming_radius(r_pin, r_hole),
        load_N=output_load_N, length_mm=length, sliding_m_s=output_sliding_m_s,
        entrainment_m_s=output_sliding_m_s / 2.0, temperature_C=t,
        clearance_mm=r_hole - r_pin)

    # ---- disc bore on the cam ------------------------------------------------
    # Only a contact when there is no bearing in there.  Conforming again, and
    # the fastest-moving surface in the drive, so it is the one contact here with
    # a real chance of building a film - if the bore is finished well enough.
    # The bore is cut to the hole clearance, not to the nominal - which is the
    # whole gap this journal has, and with the cam grown to fill the bore it is
    # the *only* thing keeping the two apart.  Reading the nominal here would
    # make the two diameters equal and the reduced radius infinite.
    r_cam = spec.cam_diameter / 2.0
    r_bore = (spec.center_bore_diameter + spec.hole_clearance) / 2.0
    cam = _contact(
        "Disc bore / cam", spec, slides=not spec.cam_bearing_fitted,
        mat_a=spec.shaft_mat, mat_b=spec.disc_mat,
        reduced_radius_mm=_conforming_radius(r_cam, r_bore),
        load_N=cam_load_N, length_mm=length, sliding_m_s=cam_sliding_m_s,
        entrainment_m_s=cam_sliding_m_s / 2.0, temperature_C=t,
        clearance_mm=max(r_bore - r_cam, 1e-6))

    lube = spec.lube
    nu = 0.0
    if lube.forms_a_film:
        nu = dynamic_viscosity_Pa_s(lube, t) / (lube.density_g_cm3 * 1e-3)
    return LubricationResult(lubricant=spec.lubricant, temperature_C=t,
                             viscosity_cSt=nu, contacts=(ring, out, cam))


def _conforming_radius(r_inner: float, r_outer: float) -> float:
    """``R'`` for a shaft in a hole: the radii subtract rather than add.

    A pin in a hole a hundredth larger has a reduced radius of metres, not
    millimetres, and that is not an artefact - it is why a close fit is a better
    bearing.  It is also why this number cannot be trusted on its own: the film
    formula grows without bound as the fit closes up, and a real journal's film
    is bounded by the gap rather than by its curvature.  That bound is applied
    where the film is computed, and it is what keeps this honest.
    """
    gap = max(r_outer - r_inner, 1e-6)
    return r_inner * r_outer / gap
