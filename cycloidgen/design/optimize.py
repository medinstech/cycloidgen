"""Search for the design that best meets a set of requirements.

Twenty-odd parameters with a dozen coupled constraints between them is not a
thing anyone should tune by hand, and the app used to ask exactly that: change a
number, watch a check turn red, change it back.  This module inverts the
problem.

How the search is shaped
------------------------
Nine free dimensions is too many to grid, so most of them are *derived* rather
than searched.  Good cycloidal geometry has strong internal relationships, and
following them cuts the search to six continuous knobs and two discrete ones:

* the eccentricity follows from the shortening coefficient, ``E = K1*R/(N+1)``,
  because ``K1`` - not ``E`` - is what actually governs the profile shape;
* the pin radius follows from the undercut limit, ``Rr = f*rho_c``, because the
  limit moves with every other parameter and a fixed ``Rr`` is meaningless
  without it.  The contact-stress optimum sits at ``f = 0.5``, so the search
  starts near there and finds out where it really wants to be;
* the central bore follows from the shaft, which follows from the torque;
* the output bolt circle is placed as a fraction of the band that is actually
  available between the bore and the disc root, so it cannot be put somewhere
  impossible;
* the output pin diameter is a fraction of the largest that still leaves webs.

Every one of those relationships is a *closed-form* screen costing microseconds,
so the search throws away the impossible candidates for free and spends its
evaluation budget only on geometry that could work.  Candidates that survive get
the fast analysis; the handful that win get the full one, and anything the full
analysis rejects is dropped rather than reported.

When nothing fits
-----------------
An optimiser that returns an empty list is useless.  This one counts *why* each
candidate died, so a search that finds nothing can still say "1,400 of 1,500
candidates were over your diameter limit" - which is the answer the user
actually needs.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field, model_validator

from ..analysis import DesignAnalysis, analyse
from ..analysis.efficiency import analyse_efficiency
from ..analysis.fatigue import output_pin_fatigue
from ..analysis.mass import analyse_mass
from ..analysis.mechanics import analyse_contacts, torque_capacity
from ..analysis.stiffness import analyse_stiffness
from ..core.profile import critical_radius
from ..core.spec import MATERIALS, GearSpec, OffsetMode, OutputMember, Process

__all__ = [
    "Candidate",
    "Objective",
    "OptimisationResult",
    "RejectionTally",
    "Requirements",
    "optimise",
    "requirements_from_spec",
]

#: Shaft diameters worth cutting a bearing seat for, mm.
_STANDARD_SHAFTS = (4, 5, 6, 8, 10, 12, 14, 16, 20, 25, 30, 35, 40)

#: Wall left between the eccentric bearing bore and the disc bore, mm.
_BEARING_WALL = 4.0

#: Thinnest web the search will leave anywhere in the disc, mm.  The checks warn
#: below 2 mm, so designing to exactly that would produce nothing but warnings.
_MIN_WEB = 2.2


class Objective(str, Enum):
    """What "best" means for this search."""

    BALANCED = "balanced"
    CAPACITY = "torque capacity"
    EFFICIENCY = "efficiency"
    COMPACT = "small and light"
    PRECISION = "stiffness and low backlash"


#: log-space weights on (capacity, efficiency, compactness, precision, lightness)
_WEIGHTS: dict[Objective, tuple[float, float, float, float, float]] = {
    Objective.BALANCED:   (0.6, 0.8, 0.4, 0.4, 0.3),
    Objective.CAPACITY:   (1.0, 0.2, 0.1, 0.0, 0.0),
    Objective.EFFICIENCY: (0.3, 2.0, 0.1, 0.0, 0.0),
    Objective.COMPACT:    (0.3, 0.2, 1.0, 0.0, 1.0),
    Objective.PRECISION:  (0.3, 0.2, 0.2, 1.5, 0.0),
}

#: Capacity past this multiple of the requirement stops earning score - a drive
#: three times stronger than it needs to be is just heavy.
_CAPACITY_CEILING = 2.0


class Requirements(BaseModel):
    """What the drive has to do, as opposed to what it is."""

    model_config = {"validate_assignment": True}

    ratio: int = Field(29, ge=3, le=200)
    output_member: OutputMember = Field(
        OutputMember.CARRIER,
        description="which member turns the load; it decides how many lobes a "
                    "given reduction needs, so the search has to know",
    )
    output_torque_Nm: float = Field(5.0, gt=0)
    input_rpm: float = Field(1000.0, gt=0)

    max_outer_diameter_mm: float = Field(120.0, gt=0)
    max_length_mm: float = Field(60.0, gt=0)
    housing_wall: float = Field(6.0, gt=0)

    process: Process = Process.FDM
    offset_mode: OffsetMode = OffsetMode.EQUIDISTANT
    disc_material: str = "PLA"
    pin_material: str = "Steel 1045"
    housing_material: str = "PLA"
    shaft_material: str = "Steel 1045"
    friction_coefficient: float = Field(0.12, gt=0, lt=1.0)
    ring_pins_are_rollers: bool = False
    output_pins_are_rollers: bool = False
    cam_bearing_fitted: bool = True
    shaft_bearings_fitted: bool = True
    output_bearing_fitted: bool = True
    ambient_temp_C: float = 20.0

    disc_count: Literal[0, 1, 2, 3] = Field(
        0, description="0 lets the search choose"
    )
    min_safety_factor: float = Field(1.5, gt=0, description="on ring contact stress")
    min_efficiency: float = Field(0.0, ge=0.0, lt=1.0)
    max_lost_motion_arcmin: float = Field(0.0, ge=0.0,
                                          description="0 = no limit")
    objective: Objective = Objective.BALANCED

    @property
    def lobes(self) -> int:
        """How many lobes this reduction needs.

        The requirement is a *reduction* and the disc is cut to a lobe count,
        and those are the same number only off the carrier.  Off the ring the
        reduction is the pin count, so a 30:1 wants twenty-nine lobes - and a
        search that took the two as interchangeable would quietly hand back a
        drive one tooth off what was asked for.
        """
        return (self.ratio if self.output_member is OutputMember.CARRIER
                else self.ratio - 1)

    @model_validator(mode="after")
    def _ratio_leaves_a_disc_to_cut(self) -> Requirements:
        """A three-lobed disc is the smallest the profile code will generate, so
        off the ring the smallest reduction is four rather than three.  Caught
        here, where the requirement is stated, instead of as a spec error two
        calls later that names a field the user never set."""
        if self.lobes < 3:
            raise ValueError(
                f"a {self.ratio}:1 off the {self.output_member.value} needs "
                f"{self.lobes} lobes, and the smallest disc is 3 - ask for "
                f"{4 if self.output_member is OutputMember.RING else 3}:1 or more")
        return self

    def base_spec(self) -> GearSpec:
        """A spec carrying every non-geometric decision the search must respect."""
        return GearSpec(
            lobes=self.lobes,
            output_member=self.output_member,
            process=self.process,
            offset_mode=self.offset_mode,
            disc_material=self.disc_material,
            pin_material=self.pin_material,
            housing_material=self.housing_material,
            shaft_material=self.shaft_material,
            friction_coefficient=self.friction_coefficient,
            ring_pins_are_rollers=self.ring_pins_are_rollers,
            output_pins_are_rollers=self.output_pins_are_rollers,
            cam_bearing_fitted=self.cam_bearing_fitted,
            shaft_bearings_fitted=self.shaft_bearings_fitted,
            output_bearing_fitted=self.output_bearing_fitted,
            input_rpm=self.input_rpm,
            output_torque_Nm=self.output_torque_Nm,
            ambient_temp_C=self.ambient_temp_C,
            housing_wall=self.housing_wall,
        ).apply_process_defaults()


def requirements_from_spec(spec: GearSpec,
                           objective: Objective = Objective.BALANCED) -> Requirements:
    """Prefill a search from a design the user already has open."""
    return Requirements(
        ratio=spec.ratio,
        output_member=spec.output_member,
        output_torque_Nm=spec.output_torque_Nm,
        input_rpm=spec.input_rpm,
        max_outer_diameter_mm=max(2.0 * spec.housing_outer_radius, 20.0),
        max_length_mm=max(spec.envelope_length, 10.0),
        housing_wall=spec.housing_wall,
        process=spec.process,
        offset_mode=spec.offset_mode,
        disc_material=spec.disc_material,
        pin_material=spec.pin_material,
        housing_material=spec.housing_material,
        shaft_material=spec.shaft_material,
        friction_coefficient=spec.friction_coefficient,
        ring_pins_are_rollers=spec.ring_pins_are_rollers,
        output_pins_are_rollers=spec.output_pins_are_rollers,
        cam_bearing_fitted=spec.cam_bearing_fitted,
        shaft_bearings_fitted=spec.shaft_bearings_fitted,
        output_bearing_fitted=spec.output_bearing_fitted,
        ambient_temp_C=spec.ambient_temp_C,
        disc_count=spec.disc_count,
        objective=objective,
    )


@dataclass
class Candidate:
    """One design the search evaluated, with the numbers it was ranked on."""

    spec: GearSpec
    score: float
    capacity_Nm: float                 # derated for clearance load concentration
    safety_factor: float
    efficiency: float
    outer_diameter_mm: float
    length_mm: float
    mass_g: float
    lost_motion_arcmin: float
    stiffness_Nm_per_arcmin: float
    temperature_C: float
    warnings: int = 0
    analysis: DesignAnalysis | None = None

    @property
    def margin(self) -> float:
        """How many times the required torque this design can actually take."""
        return self.capacity_Nm / max(self.spec.output_torque_Nm, 1e-9)


@dataclass
class RejectionTally:
    """Why candidates were thrown away - the answer when nothing fits."""

    counts: dict[str, int] = field(default_factory=dict)
    screened: int = 0
    evaluated: int = 0

    def hit(self, reason: str) -> None:
        self.counts[reason] = self.counts.get(reason, 0) + 1

    @property
    def worst(self) -> tuple[str, int] | None:
        if not self.counts:
            return None
        reason = max(self.counts, key=lambda k: self.counts[k])
        return reason, self.counts[reason]

    def explain(self) -> str:
        if not self.counts:
            return "no candidates were rejected"
        total = sum(self.counts.values())
        parts = sorted(self.counts.items(), key=lambda kv: -kv[1])[:4]
        return "; ".join(f"{n * 100 // max(total, 1)}% {reason}" for reason, n in parts)


@dataclass
class OptimisationResult:
    best: list[Candidate]
    tally: RejectionTally
    evaluations: int

    @property
    def ok(self) -> bool:
        return bool(self.best)


# --------------------------------------------------------------------- geometry


def _shaft_diameter(input_torque_Nm: float, material_name: str,
                    pin_circle_radius: float) -> float:
    """Smallest standard shaft that carries the torque with 2x on shear.

    Torsion alone always undersizes this shaft: it also reacts the eccentric's
    radial load in bending, and it has to carry a cam wide enough to hold a
    bearing.  Rather than model the span, the result is floored at 6 mm and at a
    fraction of the pin circle, which is what the answer comes out to anyway
    once bending is included.
    """
    mat = MATERIALS[material_name]
    allow = 0.577 * mat.sigma_yield_MPa / 2.0
    t_nmm = input_torque_Nm * 1000.0
    d_min = (16.0 * t_nmm / (math.pi * max(allow, 1e-6))) ** (1.0 / 3.0)
    d_min = max(d_min, 6.0, 0.12 * pin_circle_radius)
    for d in _STANDARD_SHAFTS:
        if d >= d_min:
            return float(d)
    return float(_STANDARD_SHAFTS[-1])


def _build(req: Requirements, base: GearSpec, R: float, k1: float, rr_frac: float,
           bolt_frac: float, pin_frac: float, thickness: float,
           output_pins: int, discs: int,
           tally: RejectionTally) -> GearSpec | None:
    """Turn the search vector into a spec, or say which rule it broke.

    Every rejection here is closed form.  Nothing sampled, nothing swept - this
    runs tens of thousands of times and has to stay free.
    """
    lobes = req.lobes
    pins = lobes + 1

    eccentricity = k1 * R / pins
    rho_c = critical_radius(R, eccentricity, lobes)
    if not math.isfinite(rho_c) or rho_c <= 0:
        tally.hit("shortening coefficient past the cusp limit")
        return None
    pin_radius = rr_frac * rho_c

    if pin_radius < 0.6:
        # Naming the symptom ("pins under 0.6 mm") would be true and useless:
        # the search already shrank the pin circle to fit the diameter budget,
        # so the budget is the thing the user can actually change.
        tally.hit("outer diameter too small to fit this ratio")
        return None
    # the disc reaches R - Rr + 2E from the housing axis, so 2E has to fit
    # inside the pin radius or the disc grinds the housing bore
    if pin_radius <= 2.0 * eccentricity * 1.03:
        tally.hit("disc would foul the housing bore (needs 2E < Rr)")
        return None
    if 2.0 * R * math.sin(math.pi / pins) <= 2.3 * pin_radius:
        tally.hit("ring pins would touch each other")
        return None

    outer_diameter = 2.0 * (R + pin_radius + req.housing_wall)
    if outer_diameter > req.max_outer_diameter_mm:
        tally.hit("over the outer diameter limit")
        return None

    if discs * thickness + (discs - 1) * base.disc_gap + base.output_flange_thickness \
            > req.max_length_mm:
        tally.hit("over the length limit")
        return None

    # ---- shaft, bore -------------------------------------------------------
    input_torque = req.output_torque_Nm / req.ratio / 0.5      # 0.5 = pessimistic
    shaft = _shaft_diameter(input_torque, req.shaft_material, R)
    bore = shaft + 2.0 * eccentricity + 2.0 * _BEARING_WALL

    # ---- output mechanism ---------------------------------------------------
    clearance = base.profile_clearance
    root = (R - clearance if req.offset_mode is OffsetMode.PIN_CIRCLE else
            R - clearance / 2 if req.offset_mode is OffsetMode.BOTH else R)
    root -= (pin_radius + clearance if req.offset_mode is OffsetMode.EQUIDISTANT else
             pin_radius + clearance / 2 if req.offset_mode is OffsetMode.BOTH
             else pin_radius)
    root -= eccentricity                              # disc root radius

    lo = bore / 2.0 + _MIN_WEB
    hi = root - _MIN_WEB
    if hi <= lo:
        tally.hit("no room between the bore and the disc rim for output holes")
        return None
    bolt_circle = lo + bolt_frac * (hi - lo)

    hole_r_max = min(bolt_circle - bore / 2.0 - _MIN_WEB,
                     root - bolt_circle - _MIN_WEB,
                     bolt_circle * math.sin(math.pi / output_pins) - 0.75)
    # The hole has to swallow the pin plus the full 2E orbit, so the smallest
    # useful hole is already large.  Rescale the search knob onto what is left
    # rather than rejecting: a knob that spends most of its range in impossible
    # territory just burns the sampling budget.
    hole_r_min = (2.0 + 2.0 * eccentricity + base.hole_clearance) / 2.0
    if hole_r_max <= hole_r_min:
        tally.hit("no room for an output pin thicker than 2 mm")
        return None
    hole_r = hole_r_min + pin_frac * (hole_r_max - hole_r_min)
    pin_diameter = 2.0 * hole_r - 2.0 * eccentricity - base.hole_clearance

    spec = base.model_copy(deep=True)
    try:
        spec.pin_circle_radius = R
        spec.pin_radius = pin_radius
        spec.eccentricity = eccentricity
        spec.disc_thickness = thickness
        spec.disc_count = discs
        spec.center_bore_diameter = bore
        spec.input_shaft_diameter = shaft
        spec.output_pin_count = output_pins
        spec.output_pin_diameter = pin_diameter
        spec.output_bolt_circle_radius = bolt_circle
    except Exception:                                  # a pydantic bound
        tally.hit("outside the allowed parameter range")
        return None
    return spec


# ---------------------------------------------------------------------- scoring


def _fast_metrics(spec: GearSpec) -> dict | None:
    """The numbers the ranking needs, without the parts of the analysis it doesn't.

    Skips the sampled geometry checks: the closed-form screen has already ruled
    out the geometry they would catch, and the finalists get the full analysis
    anyway.
    """
    contact = analyse_contacts(spec)
    if contact.max_pin_pressure_MPa <= 0:
        return None
    eff = analyse_efficiency(spec)
    # A coarse sweep and a short batch of rings: the search runs this tens of
    # thousands of times, and it is choosing *between* designs rather than
    # reporting one.  A position tolerance still has to be in it - it is what
    # decides the load sharing, and a search blind to it would happily pick a
    # design that only works on paper - but six rings is enough to rank by.
    stiff = analyse_stiffness(spec, steps=2, samples=6)
    mass = analyse_mass(spec)

    concentration = max(stiff.load_concentration, 1.0)
    return {
        "capacity": torque_capacity(spec, contact=contact) / concentration,
        "safety": contact.pin_safety_factor / math.sqrt(concentration),
        "efficiency": eff.efficiency,
        "mass_g": mass.total_mass_g,
        "lost": stiff.lost_motion_arcmin,
        "stiffness": stiff.stiffness_Nm_per_arcmin,
        "loss_W": eff.total_loss_W,
    }


def _score(req: Requirements, spec: GearSpec, m: dict,
           tally: RejectionTally) -> float | None:
    """Log-weighted multi-objective score, or ``None`` if a hard limit is broken.

    Weighting in log space means the reference value of each term only shifts
    the score by a constant, so the ranking depends on the weights alone and not
    on any arbitrary normalising constant.
    """
    margin = m["capacity"] / max(req.output_torque_Nm, 1e-9)
    if m["safety"] < req.min_safety_factor:
        tally.hit("not enough margin on contact stress")
        return None
    if req.min_efficiency and m["efficiency"] < req.min_efficiency:
        tally.hit("below the efficiency requirement")
        return None
    if req.max_lost_motion_arcmin and m["lost"] > req.max_lost_motion_arcmin:
        tally.hit("more backlash than allowed")
        return None
    # Output pins are cantilevers off the carrier plate, and the search will
    # happily buy compactness with thin ones: without this it returns designs
    # whose pins are past yield in bending, never mind fatigue.  Screened at
    # ambient rather than at the running temperature, which needs the thermal
    # solve - so this is the optimistic version and stage 3 confirms it.
    pin = output_pin_fatigue(spec, float(spec.ambient_temp_C))
    if pin.modelled and pin.safety_factor < 1.0:
        tally.hit("output pins fail in fatigue")
        return None

    wc, we, ws, wp, wm = _WEIGHTS[req.objective]
    od = 2.0 * spec.housing_outer_radius
    return (wc * math.log(min(margin, _CAPACITY_CEILING * req.min_safety_factor))
            + we * math.log(max(m["efficiency"], 1e-6))
            - ws * math.log(od)
            - wp * math.log(max(m["lost"], 0.05))
            - wm * math.log(max(m["mass_g"], 1.0)))


def _candidate(req: Requirements, spec: GearSpec, m: dict, score: float) -> Candidate:
    return Candidate(
        spec=spec,
        score=score,
        capacity_Nm=m["capacity"],
        safety_factor=m["safety"],
        efficiency=m["efficiency"],
        outer_diameter_mm=2.0 * spec.housing_outer_radius,
        length_mm=spec.envelope_length,
        mass_g=m["mass_g"],
        lost_motion_arcmin=m["lost"],
        stiffness_Nm_per_arcmin=m["stiffness"],
        temperature_C=req.ambient_temp_C + m["loss_W"] / max(
            12.0 * spec.cooling_area_mm2 * 1e-6, 1e-9),
    )


# ----------------------------------------------------------------------- search

#: (name, low, high) for each continuous knob, in the order the vector uses.
#: The search itself works in a unit cube; these map it onto useful geometry.
_KNOBS = (
    ("R_frac", 0.30, 1.00),      # of the radius the diameter budget allows
    ("k1", 0.25, 0.85),          # shortening coefficient
    ("rr_frac", 0.20, 0.80),     # of the undercut-limiting pin radius
    ("bolt_frac", 0.10, 0.90),   # across the band the bore and rim leave
    ("pin_frac", 0.05, 1.00),    # across the usable output pin sizes
    ("t_frac", 0.06, 1.00),      # of the length budget
)


def _map_knobs(unit: np.ndarray) -> np.ndarray:
    """Unit cube -> real knob values."""
    lo = np.array([k[1] for k in _KNOBS])
    hi = np.array([k[2] for k in _KNOBS])
    return lo + np.clip(unit, 0.0, 1.0) * (hi - lo)


def _latin_hypercube(rng: np.random.Generator, rows: int, cols: int) -> np.ndarray:
    """One stratified sample per knob, shuffled *per column*.

    Permuting the whole array instead only reorders rows, which leaves every
    knob on the same stratum and quietly reduces the search to the diagonal of
    its own parameter space.
    """
    strata = np.arange(rows)
    grid = np.stack([rng.permutation(strata) for _ in range(cols)], axis=1)
    return (grid + rng.random((rows, cols))) / rows


def optimise(req: Requirements,
             effort: str = "normal",
             progress: Callable[[int, int, str], None] | None = None,
             cancelled: Callable[[], bool] | None = None,
             seed: int = 12345) -> OptimisationResult:
    """Search for designs meeting ``req``, best first.

    ``effort`` is ``"quick"``, ``"normal"`` or ``"thorough"``.  ``progress`` is
    called as ``(done, total, message)``; ``cancelled`` is polled between
    candidates so a GUI can stop the search.
    """
    coarse, refine = {"quick": (10, 24), "normal": (26, 60),
                      "thorough": (60, 120)}.get(effort, (26, 60))

    base = req.base_spec()
    tally = RejectionTally()
    rng = np.random.default_rng(seed)

    disc_options = (req.disc_count,) if req.disc_count else (1, 2, 3)
    pin_options = (4, 5, 6, 7, 8, 10, 12)
    families = [(d, p) for d in disc_options for p in pin_options]

    # generous upper bounds; the closed-form screen trims what does not fit
    r_hi = req.max_outer_diameter_mm / 2.0 - req.housing_wall
    t_hi = req.max_length_mm - base.output_flange_thickness

    evaluations = 0
    total = len(families) * coarse + 3 * refine
    best_of_family: list[tuple[float, GearSpec, dict, tuple]] = []

    def evaluate(unit: np.ndarray, output_pins: int, discs: int):
        """Screen, analyse and score one point.  Returns (score, spec, metrics)."""
        nonlocal evaluations
        r_frac, k1, rr_frac, bolt_frac, pin_frac, t_frac = _map_knobs(unit)
        thickness = max(1.5, t_frac * t_hi / max(discs, 1))
        spec = _build(req, base, r_frac * r_hi, k1, rr_frac, bolt_frac, pin_frac,
                      thickness, output_pins, discs, tally)
        if spec is None:
            return None
        tally.screened += 1
        metrics = _fast_metrics(spec)
        evaluations += 1
        tally.evaluated += 1
        if metrics is None:
            tally.hit("analysis produced no contact")
            return None
        score = _score(req, spec, metrics, tally)
        if score is None:
            return None
        return score, spec, metrics

    # ---- stage 1: spread over every family ---------------------------------
    done = 0
    for discs, output_pins in families:
        if cancelled and cancelled():
            break
        # stratified rather than uniform: a small budget clumps badly otherwise
        samples = _latin_hypercube(rng, coarse, len(_KNOBS))
        family_best = None
        for row in samples:
            done += 1
            if progress and done % 8 == 0:
                progress(done, total, f"{discs} disc(s), {output_pins} output pins")
            got = evaluate(row, output_pins, discs)
            if got and (family_best is None or got[0] > family_best[0]):
                family_best = (got[0], got[1], got[2], (row.copy(), output_pins, discs))
        if family_best:
            best_of_family.append(family_best)

    best_of_family.sort(key=lambda item: -item[0])

    # ---- stage 2: pattern search around the best few -----------------------
    finalists: list[tuple[float, GearSpec, dict]] = []
    for score, spec, metrics, (vector, output_pins, discs) in best_of_family[:3]:
        if cancelled and cancelled():
            break
        x = vector.copy()
        best = (score, spec, metrics)
        step = 0.18
        budget = refine
        while step > 0.012 and budget > 0:
            improved = False
            for i in range(len(_KNOBS)):
                for delta in (step, -step):
                    if budget <= 0 or (cancelled and cancelled()):
                        break
                    trial = x.copy()
                    trial[i] = float(np.clip(trial[i] + delta, 0.0, 1.0))
                    budget -= 1
                    done += 1
                    if progress and done % 8 == 0:
                        progress(done, total, "refining")
                    got = evaluate(trial, output_pins, discs)
                    if got and got[0] > best[0]:
                        best = got
                        x = trial
                        improved = True
            if not improved:
                step *= 0.5
        finalists.append(best)

    finalists.extend((s, sp, m) for s, sp, m, _ in best_of_family[3:6])

    # ---- stage 3: confirm the finalists with the real analysis --------------
    out: list[Candidate] = []
    seen: set[tuple] = set()
    for score, spec, metrics in sorted(finalists, key=lambda item: -item[0]):
        key = (round(spec.pin_circle_radius, 2), round(spec.pin_radius, 3),
               round(spec.eccentricity, 3), spec.output_pin_count, spec.disc_count,
               round(spec.disc_thickness, 2))
        if key in seen:
            continue
        seen.add(key)
        full = analyse(spec)
        if not full.report.ok:
            tally.hit("failed a check the fast screen does not run")
            continue
        cand = _candidate(req, spec, metrics, score)
        cand.analysis = full
        cand.capacity_Nm = full.torque_capacity_with_clearance_Nm
        cand.safety_factor = full.pin_safety_factor_with_clearance
        cand.temperature_C = full.thermal.temperature_C
        cand.warnings = len(full.report.warnings)
        out.append(cand)

    if progress:
        progress(total, total, "done")
    return OptimisationResult(best=out, tally=tally, evaluations=evaluations)
