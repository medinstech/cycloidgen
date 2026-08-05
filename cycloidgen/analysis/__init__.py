"""Engineering analysis: contact stress, efficiency, bearings.

``analyse`` runs everything and folds the results back into the same
:class:`~cycloidgen.core.validate.Report` the geometry checks use, so the UI and
the PDF only ever deal with one list of findings.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.spec import PROCESS_POSITION_TOLERANCE, GearSpec
from ..core.validate import Report, Severity, validate
from .bearings import BearingChoice, select_bearings
from .efficiency import EfficiencyResult, analyse_efficiency
from .mass import MassResult, analyse_mass
from .mechanics import ContactResult, analyse_contacts, torque_capacity
from .stiffness import (
    StiffnessResult,
    TransmissionErrorResult,
    analyse_stiffness,
    analyse_transmission_error,
)
from .thermal import ThermalResult, analyse_thermal

__all__ = ["DesignAnalysis", "analyse"]


@dataclass
class DesignAnalysis:
    spec: GearSpec
    report: Report
    contact: ContactResult
    efficiency: EfficiencyResult
    stiffness: StiffnessResult
    transmission_error: TransmissionErrorResult
    thermal: ThermalResult
    mass: MassResult
    bearings: list[BearingChoice]
    torque_capacity_Nm: float

    @property
    def ok(self) -> bool:
        return self.report.ok

    @property
    def power_density_Nm_per_kg(self) -> float:
        return self.mass.power_density_Nm_per_kg(self.torque_capacity_with_clearance_Nm)

    @property
    def pin_safety_factor_with_clearance(self) -> float:
        """Ring-pin safety factor once clearance is allowed to concentrate load.

        The headline factor comes from the ideal rigid-disc share-out.  Clearance
        keeps the low-lever-arm contacts out of mesh, so the pins that do touch
        carry :attr:`StiffnessResult.load_concentration` times their ideal share,
        and Hertzian pressure goes as the square root of load.
        """
        return self.contact.pin_safety_factor / math.sqrt(
            max(self.stiffness.load_concentration, 1.0))

    @property
    def torque_capacity_with_clearance_Nm(self) -> float:
        """Torque capacity derated for the same effect."""
        return self.torque_capacity_Nm / max(self.stiffness.load_concentration, 1.0)


def analyse(spec: GearSpec) -> DesignAnalysis:
    """Geometry checks plus the full load/efficiency/bearing study."""
    rep = validate(spec)
    contact = analyse_contacts(spec)
    eff = analyse_efficiency(spec)
    stiff = analyse_stiffness(spec)
    te = analyse_transmission_error(spec)
    therm = analyse_thermal(spec, efficiency=eff)
    mass = analyse_mass(spec)
    bearings = select_bearings(spec, contact.eccentric_bearing_load_N,
                               contact.max_output_force_N)
    capacity = torque_capacity(spec, contact=contact)

    if contact.pin_safety_factor < 1.0:
        rep.add(Severity.WARNING, "HERTZ_STRESS_RING",
                "Ring pin contact pressure exceeds the allowable for the softer "
                f"material; the drive is good for about {capacity:.2f} Nm out.",
                contact.max_pin_pressure_MPa, contact.pin_pressure_allow_MPa)
    elif contact.pin_safety_factor < 1.5:
        rep.add(Severity.WARNING, "HERTZ_STRESS_MARGIN",
                "Ring pin contact pressure leaves less than 1.5x margin.",
                contact.max_pin_pressure_MPa, contact.pin_pressure_allow_MPa)

    if contact.output_safety_factor < 1.0:
        rep.add(Severity.WARNING, "HERTZ_STRESS_OUTPUT",
                "Output pin contact pressure exceeds the allowable; enlarge the "
                "pins or add more of them.",
                contact.max_output_pressure_MPa, contact.pin_pressure_allow_MPa)

    if eff.efficiency < 0.5:
        rep.add(Severity.WARNING, "LOW_EFFICIENCY",
                "Predicted efficiency below 50%. Rolling ring pins and output "
                "bushings are the two biggest wins.", 100 * eff.efficiency, 50.0)

    # ---- stiffness, lost motion, and what clearance does to load sharing ----
    rep.add(Severity.INFO, "TORSIONAL_STIFFNESS",
            f"Torsional stiffness at the output: "
            f"{stiff.contact_only_Nm_per_arcmin:.3f} Nm/arcmin of mesh in series "
            f"with {stiff.structure_Nm_per_arcmin:.3f} of structure. Elastic "
            f"wind-up at {spec.output_torque_Nm:g} Nm is "
            f"{stiff.windup_arcmin:.2f} arcmin.",
            stiff.stiffness_Nm_per_arcmin)

    softest = stiff.structure.softest
    if stiff.structure_Nm_per_arcmin < stiff.contact_only_Nm_per_arcmin:
        rep.add(Severity.WARNING, "STRUCTURAL_COMPLIANCE",
                f"Most of the give in this drive is not in the mesh: the parts "
                f"around it are worth {stiff.structure_Nm_per_arcmin:.3f} "
                f"Nm/arcmin against the contacts' "
                f"{stiff.contact_only_Nm_per_arcmin:.3f}. First to give way "
                f"outside the mesh: {softest}. Stiffening the mesh - a harder "
                f"disc, a thicker stack - cannot get past that.",
                stiff.structure_Nm_per_arcmin, stiff.contact_only_Nm_per_arcmin)
    else:
        rep.add(Severity.INFO, "STRUCTURAL_COMPLIANCE",
                f"The mesh is the softer half, which is the way round you want "
                f"it: {stiff.structure_Nm_per_arcmin:.3f} Nm/arcmin of structure "
                f"around {stiff.contact_only_Nm_per_arcmin:.3f} of contact. "
                f"First to give way outside the mesh: {softest}.",
                stiff.structure_Nm_per_arcmin, stiff.contact_only_Nm_per_arcmin)

    lost_severity = Severity.WARNING if stiff.lost_motion_arcmin > 60.0 else Severity.INFO
    rep.add(lost_severity, "LOST_MOTION",
            f"Backlash at the output: {stiff.lost_motion_ring_arcmin:.1f} arcmin "
            f"from the profile clearance and {stiff.lost_motion_output_arcmin:.1f} "
            f"from the output holes. Tighten the process or the hole fit to cut it.",
            stiff.lost_motion_arcmin, 60.0)

    rep.add(Severity.INFO, "TRANSMISSION_ERROR",
            f"Ripple in the output angle at {spec.output_torque_Nm:g} Nm: "
            f"{te.peak_to_peak_arcmin:.2f} arcmin peak to peak, "
            f"{te.rms_arcmin:.2f} rms - {te.output_arcmin:.2f} from the output "
            f"pins handing load between each other every "
            f"{te.output_period_deg:.0f} deg of crank, {te.ring_arcmin:.2f} from "
            f"the ring mesh every {te.ring_period_deg:.0f} deg. Clearance take-up "
            f"and elastic deflection together; pin position and profile error "
            f"are not in it.", te.peak_to_peak_arcmin)

    # ---- where the pins actually are ----------------------------------------
    guide = PROCESS_POSITION_TOLERANCE[spec.process]
    if spec.position_tolerance <= 0.0:
        rep.add(Severity.INFO, "PIN_POSITION",
                f"Every pin is modelled exactly on its bolt circle, which no "
                f"ring is. {spec.process.value} typically holds about "
                f"{guide:.2f} mm true position; entering it under Manufacturing "
                f"reruns the load sharing over a batch of rings drawn from that "
                f"tolerance and reports what it costs.", 0.0, guide)
    elif stiff.position_interference_mm > 0.0:
        rep.add(Severity.WARNING, "PIN_POSITION",
                f"The position tolerance has eaten the clearance: at "
                f"{spec.position_tolerance:.3f} mm true position some rings put "
                f"a pin {1000 * stiff.position_interference_mm:.0f} um into the "
                f"disc, which is a drive that binds rather than one that turns. "
                f"Every figure here reads that pin as just touching, so they "
                f"are the optimistic version. Open the profile clearance or "
                f"hold the holes tighter.",
                spec.position_tolerance, spec.profile_clearance)
    else:
        rep.add(Severity.INFO, "PIN_POSITION",
                f"Over {stiff.rings_sampled} rings drawn at "
                f"{spec.position_tolerance:.3f} mm true position, the middle one "
                f"carries {stiff.load_concentration:.1f}x its ideal share and "
                f"the worst tenth {stiff.load_concentration_p90:.1f}x; stiffness "
                f"runs {stiff.stiffness_Nm_per_arcmin:.3f} Nm/arcmin down to "
                f"{stiff.stiffness_p10_Nm_per_arcmin:.3f} in the soft decile.",
                spec.position_tolerance, spec.profile_clearance)

    if stiff.load_concentration > 1.5:
        rep.add(Severity.WARNING, "LOAD_CONCENTRATION",
                f"Clearance keeps the low-lever-arm pins out of mesh, so about "
                f"{stiff.pins_engaged:.1f} of the {stiff.pins_engaged_ideal:.0f} "
                f"pins the ideal model loads actually carry. Peak pin force is "
                f"{stiff.load_concentration:.1f}x the ideal share, which derates "
                f"the torque capacity to "
                f"{capacity / stiff.load_concentration:.2f} Nm.",
                stiff.load_concentration, 1.5)

    # ---- sliding duty and heat ----------------------------------------------
    # PV is the wear limit, not a strength limit: a contact can be far inside its
    # stress allowable and still be finished in an afternoon.
    if therm.ring_pv_margin < 1.0:
        rep.add(Severity.WARNING, "PV_LIMIT_RING",
                f"Ring pin sliding duty is past the wear limit for "
                f"{spec.disc_mat.name} on {spec.pin_mat.name}: "
                f"{therm.ring_pressure_MPa:.2f} MPa at "
                f"{therm.ring_sliding_speed_m_s:.2f} m/s. The disc will wear "
                f"round long before it breaks - use rolling ring pins, or drop "
                f"the input speed.",
                therm.pv_ring_MPa_m_s, therm.pv_ring_limit_MPa_m_s)
    elif therm.ring_pv_margin < 2.0:
        rep.add(Severity.INFO, "PV_MARGIN_RING",
                "Ring pin sliding duty is inside the wear limit, but by less "
                "than 2x.", therm.pv_ring_MPa_m_s, therm.pv_ring_limit_MPa_m_s)

    if therm.output_pv_margin < 1.0:
        rep.add(Severity.WARNING, "PV_LIMIT_OUTPUT",
                "Output pin sliding duty is past the wear limit; bushings or "
                "rollers on the output pins fix this.",
                therm.pv_output_MPa_m_s, therm.pv_output_limit_MPa_m_s)

    # A warning, not an error: overheating is a duty-point problem, not a part
    # that cannot be made.  Slowing the drive down fixes it without touching the
    # geometry, so there is no reason to refuse to export the files.
    if therm.temperature_C > therm.temperature_limit_C:
        rep.add(Severity.WARNING, "OVERTEMP",
                f"{therm.loss_W:.1f} W of loss over {therm.cooling_area_mm2 / 100:.0f} "
                f"cm2 of housing puts the drive at {therm.temperature_C:.0f} C in "
                f"still air, past what {spec.disc_mat.name} tolerates. Raise the "
                f"efficiency, slow it down, or build it from something else.",
                therm.temperature_C, therm.temperature_limit_C)
    elif therm.temperature_rise_C > 0.6 * (therm.temperature_limit_C - spec.ambient_temp_C):
        rep.add(Severity.WARNING, "RUNNING_HOT",
                f"Predicted steady temperature {therm.temperature_C:.0f} C in still "
                f"air, against a {therm.temperature_limit_C:.0f} C limit.",
                therm.temperature_C, therm.temperature_limit_C)

    # ---- disc structure and rotating balance --------------------------------
    if mass.web_safety_factor < 1.0:
        rep.add(Severity.ERROR, "WEB_SHEAR",
                f"The {mass.min_web_mm:.2f} mm ligament beside the output holes "
                f"shears at this load. Move the bolt circle, add pins, or thicken "
                f"the disc.", mass.web_shear_MPa, mass.web_shear_allow_MPa)
    elif mass.web_safety_factor < 2.0:
        rep.add(Severity.WARNING, "WEB_SHEAR_MARGIN",
                f"Less than 2x margin on the {mass.min_web_mm:.2f} mm ligament "
                f"beside the output holes.",
                mass.web_shear_MPa, mass.web_shear_allow_MPa)

    if mass.unbalance_force_N > 0.5 * spec.output_torque_Nm * 1000.0 / max(
            spec.output_bolt_circle_radius, 1e-9):
        rep.add(Severity.WARNING, "UNBALANCE_FORCE",
                f"The orbiting disc throws {mass.unbalance_force_N:.0f} N at "
                f"{spec.input_rpm:g} rpm, comparable to the working load. Add a "
                f"counterweight or a second disc at 180 degrees.",
                mass.unbalance_force_N, 0.0)

    rep.add(Severity.INFO, "MASS",
            f"{mass.total_mass_g:.0f} g assembled, {mass.disc_mass_g:.0f} g per disc; "
            f"reflected inertia at the input "
            f"{mass.reflected_inertia_kg_mm2:.3f} kg mm2.",
            mass.total_mass_g)

    for choice in bearings:
        if choice.bearing is None and choice.note and "fixed pins" not in choice.note:
            rep.add(Severity.WARNING, "NO_BEARING_FITS",
                    f"{choice.role}: {choice.note}")
        elif choice.bearing is not None and choice.life_hours < 5000:
            rep.add(Severity.WARNING, "SHORT_BEARING_LIFE",
                    f"{choice.role} ({choice.bearing.designation}) L10 life is short.",
                    choice.life_hours, 5000.0)

    return DesignAnalysis(spec=spec, report=rep, contact=contact, efficiency=eff,
                          stiffness=stiff, transmission_error=te, thermal=therm,
                          mass=mass, bearings=bearings,
                          torque_capacity_Nm=capacity)
