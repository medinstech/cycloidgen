"""Fatigue: the parts that are loaded and unloaded once per input revolution.

Everything else in this package asks whether a part survives its peak load once.
That is the wrong question for two of them.  The drive's whole working life is
spent turning, and turning is what makes a load cycle: a part that is
comfortable at its peak stress can still be finished in an afternoon at a stress
it would never yield at.

Which parts, and why those
--------------------------
**The disc web.**  The ligament beside the output holes carries the pin load
across.  The disc turns at one ratio-th of the input while the load direction
goes round once per input revolution, so relative to the metal the load sweeps a
full turn every input revolution.  Each ligament is loaded, unloaded, loaded the
other way: fully reversed, ``R = -1``, no mean stress to speak of.

**The output pins.**  A pin is fixed in the flange and pushed by the disc.  The
push rotates around it once per input revolution, which is rotating bending -
the textbook fully reversed case, and the reason the classical rotating-beam
test is built the way it is.

**Not the ring pins.**  They see a one-way pulse as each lobe passes, and what
kills them is surface pitting rather than a crack through the section.  That is
contact fatigue, a different model with a different strength, and it is not in
here - see :mod:`cycloidgen.analysis.mechanics` for what is.

The model and its limits
------------------------
Infinite-life design, which is the only sensible target at these speeds: at
1500 rpm a drive passes ten million cycles in four and a half days, so anything
finite is spent almost immediately.  The specimen strength in
:data:`~cycloidgen.core.spec.MATERIALS` is corrected the classical way, and each
factor is a real derating rather than a decoration:

* **Surface.**  Fatigue cracks start at the surface, so how the part was made
  matters more here than anywhere else in this app.  A wire-EDM'd disc and a
  printed one differ by a factor of three.
* **Size.**  Bigger sections have more material at peak stress and more places
  for a crack to start.  Only for bending and torsion, which is what these are.
* **Temperature**, from the thermal solve rather than assumed - the drive heats
  itself, and strength falls with it.
* **Reliability.**  The published strengths are means; half of a population of
  specimens fails below one.  99% is used, which costs 19%.

Then Goodman for whatever mean stress there is, which for both of these is
almost none - it is in the arithmetic so that the one case with a mean (a
preloaded pin) does not read as if it had not.

**Aluminium and bronze have no endurance limit.**  Their numbers are strengths
at 5e8 cycles and the check says so: a drive expected to outlive that is outside
the model, not inside it with a margin.

**Polymers get no number at all.**  Printed-part fatigue turns on layer
orientation, void content and temperature far more than on tensile strength, and
a steel rule applied to PLA would be a confident answer with nothing behind it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.spec import GearSpec, Process

__all__ = [
    "FatigueResult",
    "PartFatigue",
    "analyse_fatigue",
    "endurance_limit",
    "output_pin_fatigue",
    "size_factor",
    "surface_factor",
]

#: Reliability factor for 99% survival.  The published strengths are means, so
#: without this the answer is "half of them last this long".
RELIABILITY_99 = 0.814

#: Surface finish factor ``ka = a * Sut^b``, Sut in MPa, by how the part is made.
#: Machined and ground are the classical wrought-metal fits.  The printed
#: processes are not in that table at all - a layered part has a surface that is
#: also a stack of notches - so they carry a flat, deliberately harsh factor,
#: which only ever applies to a metal printed part because polymers get no
#: fatigue number in the first place.
_SURFACE_FIT: dict[Process, tuple[float, float]] = {
    Process.EDM: (1.58, -0.085),      # ground
    Process.CNC: (4.51, -0.265),      # machined / cold drawn
}
_SURFACE_FLAT: dict[Process, float] = {
    Process.FDM: 0.35,
    Process.SLA: 0.40,
    Process.SLS: 0.45,
}

#: Cycles behind the strengths of materials that have no endurance limit.
FINITE_LIFE_CYCLES = 5e8


def surface_factor(process: Process, sigma_ultimate_MPa: float) -> float:
    """Marin surface factor ``ka``, capped at 1: no finish is better than polished."""
    if process in _SURFACE_FIT:
        a, b = _SURFACE_FIT[process]
        return min(a * sigma_ultimate_MPa ** b, 1.0)
    return _SURFACE_FLAT[process]


def size_factor(diameter_mm: float) -> float:
    """Marin size factor ``kb`` for bending and torsion, mm.

    Below 8 mm the fit runs above 1 and is not evidence that a small part is
    stronger than a specimen, so it is held there.
    """
    d = max(diameter_mm, 1e-6)
    if d <= 2.79:
        return 1.0
    if d <= 51.0:
        return min(1.24 * d ** -0.107, 1.0)
    if d <= 254.0:
        return 1.51 * d ** -0.157
    return 0.6


def _temperature_factor(temperature_C: float) -> float:
    """Marin temperature factor ``kd``, from the running temperature.

    Flat to 100 C and then falling, which is the shape of the wrought-steel data.
    Above the material's service temperature the answer is not a derated fatigue
    strength but a different check, and there is one - see
    :mod:`cycloidgen.analysis.thermal`.
    """
    if temperature_C <= 100.0:
        return 1.0
    return max(1.0 - 0.0006 * (temperature_C - 100.0), 0.5)


def endurance_limit(spec: GearSpec, temperature_C: float, diameter_mm: float,
                    material=None, loading: str = "bending") -> float:
    """Corrected fatigue strength for one part, MPa.  Zero when there is no data.

    ``loading`` picks the load factor ``kc``: bending is the reference case and
    shear is weaker, because a shear crack sees the full range at every point of
    the section rather than only at the extreme fibre.
    """
    mat = material if material is not None else spec.disc_mat
    if mat.fatigue_strength_MPa is None:
        return 0.0
    kc = 0.577 if loading == "shear" else 1.0
    return (surface_factor(spec.process, mat.sigma_ultimate_MPa)
            * size_factor(diameter_mm)
            * kc
            * _temperature_factor(temperature_C)
            * RELIABILITY_99
            * mat.fatigue_strength_MPa)


@dataclass
class PartFatigue:
    """One part's alternating stress against what it can take forever."""

    part: str
    alternating_MPa: float
    mean_MPa: float
    strength_MPa: float          # corrected, for the loading this part sees
    ultimate_MPa: float
    modelled: bool               # False when the material has no fatigue data

    @property
    def safety_factor(self) -> float:
        """Goodman.  Infinite when nothing is being asked of the part."""
        if not self.modelled or self.strength_MPa <= 0:
            return float("inf")
        if self.alternating_MPa <= 0 and self.mean_MPa <= 0:
            return float("inf")
        denominator = (self.alternating_MPa / self.strength_MPa
                       + max(self.mean_MPa, 0.0) / max(self.ultimate_MPa, 1e-9))
        return 1.0 / denominator if denominator > 0 else float("inf")


@dataclass
class FatigueResult:
    """Fully reversed duty on the parts that see one, over the whole drive."""

    parts: list[PartFatigue]
    cycles_per_hour: float
    hours_to_ten_million: float
    #: True when the strength behind this is a finite-life figure rather than a
    #: true endurance limit, which is the case for aluminium and bronze.
    finite_life_basis: bool
    finite_life_cycles: float
    temperature_C: float

    @property
    def modelled(self) -> bool:
        return any(p.modelled for p in self.parts)

    @property
    def worst(self) -> PartFatigue | None:
        candidates = [p for p in self.parts if p.modelled]
        return min(candidates, key=lambda p: p.safety_factor) if candidates else None

    @property
    def safety_factor(self) -> float:
        worst = self.worst
        return worst.safety_factor if worst is not None else float("inf")

    @property
    def ok(self) -> bool:
        return self.safety_factor >= 1.0


def _peak_output_pin_force(spec: GearSpec) -> float:
    """Worst force on one output pin over the output stage's own period, N.

    A lobe pitch is about half that period, so sweeping one used to miss the
    worst pin on drives where the peak fell in the other half.
    """
    from ..core.kinematics import output_loads, output_sweep_angles

    torque_per_disc = spec.output_torque_Nm * 1000.0 / spec.disc_count
    peak = 0.0
    for phi in output_sweep_angles(spec.lobes, spec.output_pin_count, 48):
        forces = output_loads(spec, float(phi), torque_per_disc).forces
        if forces.size:
            peak = max(peak, float(forces.max()))
    return peak


def output_pin_fatigue(spec: GearSpec, temperature_C: float) -> PartFatigue:
    """Rotating bending on one output pin.

    A cantilever, and not by assumption: :func:`cycloidgen.export.solid.output_flange`
    extrudes the pins from one plate and nothing catches their free ends, so that
    is the part this app tells you to make.  A design that captures them in a
    second plate is a different and much better part, and this does not know
    about it.

    Every disc in the stack pushes the same pin at its own plane, so the root
    moment is the sum of those and not one disc's force at the middle of the
    stack: with three discs the outermost has five times the arm of the innermost
    and the total is nowhere near the average.

    Separate from :func:`analyse_fatigue` because the design search screens on
    it, and screening on the whole fatigue result would mean sampling the disc
    profile for every candidate.
    """
    pin_mat = spec.pin_mat
    force_per_disc = _peak_output_pin_force(spec)
    pitch = spec.disc_thickness + spec.disc_gap
    arms = [i * pitch + 0.5 * spec.disc_thickness for i in range(spec.disc_count)]
    diameter = spec.output_pin_diameter
    section_modulus = math.pi * diameter ** 3 / 32.0
    bending = force_per_disc * sum(arms) / max(section_modulus, 1e-9)
    return PartFatigue(
        part="output pin",
        alternating_MPa=bending,
        mean_MPa=0.0,
        strength_MPa=endurance_limit(spec, temperature_C, diameter,
                                     material=pin_mat, loading="bending"),
        ultimate_MPa=pin_mat.sigma_ultimate_MPa,
        modelled=pin_mat.has_fatigue_data,
    )


def analyse_fatigue(spec: GearSpec, web_shear_MPa: float, min_web_mm: float,
                    temperature_C: float | None = None) -> FatigueResult:
    """Fully reversed duty on the disc web and the output pins.

    The web stress and thickness come from
    :func:`~cycloidgen.analysis.mass.analyse_mass` - the same numbers, asked a
    different question.  Passed in rather than recomputed for two reasons: the
    profile sampling behind them is the most expensive thing in the package, and
    a fatigue factor that disagreed with the static check about how hard the web
    is working would be a bug nobody could see.
    """
    temperature = (temperature_C if temperature_C is not None
                   else float(spec.ambient_temp_C))
    disc_mat, pin_mat = spec.disc_mat, spec.pin_mat

    # ---- the disc web -------------------------------------------------------
    # The ligament thickness is what carries the load and what a size factor is
    # about, so it stands in for the diameter of a round section.
    web_strength = endurance_limit(spec, temperature, min_web_mm,
                                   material=disc_mat, loading="shear")
    web = PartFatigue(
        part="disc web",
        # Fully reversed: the load sweeps a whole turn around the disc every
        # input revolution, so the peak static stress *is* the amplitude.
        alternating_MPa=web_shear_MPa,
        mean_MPa=0.0,
        strength_MPa=web_strength,
        ultimate_MPa=disc_mat.sigma_ultimate_MPa,
        modelled=disc_mat.has_fatigue_data,
    )

    pin = output_pin_fatigue(spec, temperature)

    cycles_per_hour = spec.input_rpm * 60.0
    return FatigueResult(
        parts=[web, pin],
        cycles_per_hour=cycles_per_hour,
        hours_to_ten_million=1e7 / cycles_per_hour if cycles_per_hour > 0 else float("inf"),
        finite_life_basis=any(
            m.fatigue_strength_MPa is not None and m.name in _FINITE_LIFE_MATERIALS
            for m in (disc_mat, pin_mat)),
        finite_life_cycles=FINITE_LIFE_CYCLES,
        temperature_C=temperature,
    )


#: The materials whose quoted strength is a finite-life figure rather than a true
#: endurance limit.  Named rather than inferred: "is it a steel" is not a
#: property of the table, and guessing it from the name is how a new entry
#: quietly gets the wrong basis.
_FINITE_LIFE_MATERIALS = frozenset({"Aluminium 7075-T6", "Bronze CuSn12"})
