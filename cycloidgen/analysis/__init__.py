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
from .efficiency import EfficiencyResult
from .fatigue import FatigueResult, analyse_fatigue
from .lubrication import FULL_FILM_LAMBDA, LubricationResult
from .mass import MassResult, analyse_mass
from .mechanics import ContactResult, analyse_contacts, torque_capacity
from .stiffness import (
    StiffnessResult,
    TransmissionErrorResult,
    analyse_stiffness,
    analyse_transmission_error,
)
from .thermal import ThermalResult, solve_operating_point

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
    fatigue: FatigueResult
    bearings: list[BearingChoice]
    torque_capacity_Nm: float

    @property
    def lubrication(self) -> LubricationResult:
        """The film behind the friction coefficients, at the running temperature.

        Lives on the efficiency result because that is what computed it, and is
        surfaced here because it is an answer in its own right rather than an
        intermediate: the regime is what says whether the drive wears.
        """
        return self.efficiency.lubrication

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
    stiff = analyse_stiffness(spec)
    te = analyse_transmission_error(spec)
    # Efficiency and temperature come out together, because with a lubricant in
    # the design they decide each other: friction heats the oil, the hot oil
    # stops holding the surfaces apart, and that is more friction.
    eff, therm = solve_operating_point(spec)
    mass = analyse_mass(spec)
    # At the running temperature, not the ambient: the drive heats itself and
    # fatigue strength goes down with it.
    fatigue = analyse_fatigue(spec, mass.web_shear_MPa, mass.min_web_mm,
                              temperature_C=therm.temperature_C)
    bearings = select_bearings(spec, contact.eccentric_bearing_load_N,
                               contact.max_output_force_N,
                               ring_pin_load_N=contact.max_pin_force_N)
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

    # The cam journal only exists as a sliding contact when no bearing is fitted
    # there, and then it is the hardest-worked one in the drive: the largest
    # single force, rubbing at nearly the input speed.
    if therm.cam_pv_margin < 1.0:
        rep.add(Severity.WARNING, "PV_LIMIT_CAM",
                f"With no cam bearing the disc bore is a plain journal on the "
                f"cam, and its duty is past the wear limit for "
                f"{spec.disc_mat.name} on {spec.shaft_mat.name}: "
                f"{therm.cam_pressure_MPa:.2f} MPa at "
                f"{therm.cam_sliding_speed_m_s:.2f} m/s, "
                f"{1.0 / max(therm.cam_pv_margin, 1e-9):.0f}x over. This is the "
                f"fastest contact in the drive and it will wear the bore oval "
                f"long before anything breaks. Fit the bearing, or run a bronze "
                f"bushing and drop the speed.",
                therm.pv_cam_MPa_m_s, therm.pv_cam_limit_MPa_m_s)

    # ---- what is between the surfaces ---------------------------------------
    # The regime, not the coefficient: a friction number on its own says what the
    # drive costs and not why, and the why is the part you can do something
    # about.  Reported on every design, because "there is no film and there was
    # never going to be one" is an answer and the app used to give none.
    lub = eff.lubrication
    worst_film = lub.governing
    if worst_film is None:
        rep.add(Severity.INFO, "LUBRICATION_REGIME",
                "Nothing in this drive slides: rolling elements at every contact "
                "the model tracks, so there is no film to build and lubrication "
                "is the bearings' own business rather than a design choice here.")
    elif spec.lube.forms_a_film:
        needed = FULL_FILM_LAMBDA * worst_film.roughness_um
        if worst_film.lambda_ratio < 1.0:
            rep.add(Severity.WARNING, "LUBRICATION_REGIME",
                    f"{spec.lubricant} does not separate the surfaces at the "
                    f"{worst_film.name.lower()}: {1000 * worst_film.film_um:.0f} nm "
                    f"of film against {1000 * worst_film.roughness_um:.0f} nm of "
                    f"roughness is lambda {worst_film.lambda_ratio:.2f}, which is "
                    f"boundary lubrication - the peaks are touching and the "
                    f"additives are carrying the contact, not the oil. It still "
                    f"earns its place: mu is {worst_film.mu:.3f} against "
                    f"{spec.friction_coefficient:.3f} dry. Clearing the peaks "
                    f"would need {needed:.1f} um of film, so the lever is the "
                    f"surface rather than the grade - or rollers, which change "
                    f"the contact instead of lubricating it.",
                    worst_film.lambda_ratio, 1.0)
        else:
            rep.add(Severity.INFO, "LUBRICATION_REGIME",
                    f"{spec.lubricant} at {lub.temperature_C:.0f} C "
                    f"({lub.viscosity_cSt:.0f} cSt) puts the "
                    f"{worst_film.name.lower()} in the {worst_film.regime} regime: "
                    f"{1000 * worst_film.film_um:.0f} nm of film over "
                    f"{1000 * worst_film.roughness_um:.0f} nm of roughness, lambda "
                    f"{worst_film.lambda_ratio:.2f}, mu {worst_film.mu:.3f}. That "
                    f"is the thinnest film in the drive; the others have more.",
                    worst_film.lambda_ratio, FULL_FILM_LAMBDA)
    else:
        rep.add(Severity.INFO, "LUBRICATION_REGIME",
                f"Running dry, so every sliding contact is at the design's own "
                f"{spec.friction_coefficient:.3f} and wear is governed by PV "
                f"rather than by a film. At {spec.roughness_um:.1f} um Rq a film "
                f"would have to reach "
                f"{FULL_FILM_LAMBDA * math.sqrt(2.0) * spec.roughness_um:.1f} um "
                f"to separate these surfaces, which is out of reach of anything "
                f"pourable on a {spec.process.value} finish - so on this "
                f"build the lubricant to choose is the one with the lowest "
                f"boundary friction, not the thickest.",
                spec.friction_coefficient)

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

    # ---- and whether it survives being turned, not just being loaded --------
    # A separate question from WEB_SHEAR above, off the same stress: that one
    # asks whether the ligament holds, this one whether it keeps holding.
    worst = fatigue.worst
    if not fatigue.modelled:
        rep.add(Severity.INFO, "FATIGUE_NOT_MODELLED",
                f"No fatigue check: {spec.disc_mat.name} has no fatigue strength "
                f"in the table, and printed-polymer fatigue depends on layer "
                f"orientation and void content far more than on tensile "
                f"strength. At {spec.input_rpm:g} rpm the disc web and the "
                f"output pins see a fully reversed cycle every input "
                f"revolution - {fatigue.cycles_per_hour:,.0f} an hour - so this "
                f"is a real question that this app is not answering.")
    elif worst is not None and worst.safety_factor < 1.0:
        rep.add(Severity.ERROR, "FATIGUE_LIFE",
                f"The {worst.part} does not survive being turned: "
                f"{worst.alternating_MPa:.1f} MPa fully reversed against a "
                f"corrected fatigue strength of {worst.strength_MPa:.1f} MPa. "
                f"It is a crack after "
                f"{fatigue.hours_to_ten_million:.0f}-odd hours, not a part that "
                f"holds at its rated torque - which it does. Thicken the "
                f"section, drop the load, or use a material with more fatigue "
                f"strength rather than more yield.",
                worst.alternating_MPa, worst.strength_MPa)
    elif worst is not None and worst.safety_factor < 1.5:
        rep.add(Severity.WARNING, "FATIGUE_MARGIN",
                f"Less than 1.5x on fatigue at the {worst.part}: "
                f"{worst.alternating_MPa:.1f} MPa fully reversed against "
                f"{worst.strength_MPa:.1f} MPa corrected. Fatigue strengths "
                f"scatter more than static ones, so this is a thinner margin "
                f"than the same number would be on yield.",
                worst.alternating_MPa, worst.strength_MPa)
    elif worst is not None:
        basis = (f"a {fatigue.finite_life_cycles:.0g}-cycle strength, not an "
                 f"endurance limit - past that this says nothing"
                 if fatigue.finite_life_basis else "an endurance limit")
        rep.add(Severity.INFO, "FATIGUE_LIFE",
                f"Fully reversed duty: {worst.safety_factor:.1f}x at the "
                f"{worst.part}, the tighter of the two. "
                f"{fatigue.cycles_per_hour:,.0f} cycles an hour at "
                f"{spec.input_rpm:g} rpm, so ten million of them in "
                f"{fatigue.hours_to_ten_million:.0f} hours. Against {basis}, "
                f"at {fatigue.temperature_C:.0f} C and 99% reliability.",
                worst.safety_factor, 1.0)

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

    # ---- what holds it together ---------------------------------------------
    #
    # The tie bolts run the length of the barrel, in the band of wall between
    # the ring-pin pockets and the outside.  Nothing asked whether that band
    # exists: the bill of materials orders the bolts and both plates are
    # drilled for them, so a design where they cut into the pockets or off the
    # rim exported as a gearbox that cannot be assembled, and said nothing.
    # One question, not two.  The circle is derived as the middle of the wall,
    # so a bolt too big for that wall breaks *into the pockets and off the rim
    # at the same moment* - asking about the two sides separately would have
    # been an inner test and an outer branch that could never run.
    if spec.housing_bolt_count and \
            spec.housing_bolt_diameter >= spec.housing_wall:
        rep.add(Severity.ERROR, "HOUSING_BOLT_CLASH",
                f"A {spec.housing_bolt_diameter:g} mm tie bolt does not fit in a "
                f"{spec.housing_wall:g} mm housing wall. It runs up the middle of "
                f"that wall, so at this size it breaks into the ring-pin pockets "
                f"on one side and out through the rim on the other. Thicken the "
                f"wall or use a smaller bolt.",
                spec.housing_bolt_diameter, spec.housing_wall)

    # The output face's own bolts, which exist only on a ring-output drive: the
    # turning member there is a barrel, and a barrel has nowhere to grip, so the
    # load bolts to the end plate.  They share the tie bolts' circle because
    # that is the one radius on that plate with barrel wall behind it to thread
    # into - so the two patterns are kept apart by angle, and whether that
    # actually works depends on two counts the user sets independently.
    if spec.mount_base_fitted and spec.output_bolt_count:
        if spec.output_bolt_diameter >= spec.housing_wall:
            rep.add(Severity.ERROR, "OUTPUT_BOLT_CLASH",
                    f"A {spec.output_bolt_diameter:g} mm output bolt does not fit "
                    f"in a {spec.housing_wall:g} mm housing wall. It lands on the "
                    f"middle of that wall, so at this size there is nothing "
                    f"behind it but the ring-pin pockets on one side and open "
                    f"air on the other. Thicken the wall or use a smaller bolt.",
                    spec.output_bolt_diameter, spec.housing_wall)
        elif spec.housing_bolt_count:
            ties = [2.0 * math.pi * j / spec.housing_bolt_count
                    for j in range(spec.housing_bolt_count)]
            outs = [spec.output_bolt_phase + 2.0 * math.pi * k / spec.output_bolt_count
                    for k in range(spec.output_bolt_count)]
            closest = min(min(abs(o - t) % (2.0 * math.pi),
                              2.0 * math.pi - abs(o - t) % (2.0 * math.pi))
                          for o in outs for t in ties)
            gap = 2.0 * spec.output_face_bolt_radius * math.sin(closest / 2.0)
            metal = gap - (spec.output_bolt_diameter
                           + spec.housing_bolt_diameter) / 2.0
            if metal <= 0.0:
                rep.add(Severity.ERROR, "OUTPUT_BOLT_CLASH",
                        f"The {spec.output_bolt_count} output bolts and the "
                        f"{spec.housing_bolt_count} tie bolts share one circle "
                        f"and at these counts they run into each other. Match "
                        f"the counts, or make one of them a multiple of the "
                        f"other, so the two patterns interleave.",
                        metal, 0.0)
            elif metal < 1.5:
                rep.add(Severity.WARNING, "OUTPUT_BOLT_CLASH",
                        f"Only {metal:.2f} mm of metal between an output bolt "
                        f"and the tie bolt beside it on the same circle.",
                        metal, 1.5)

    # Not "has no bearing" - a plain cam has none and the drive still carries
    # that force, sliding, which the PV check is there for.  This is the narrower
    # question of a load leaving the gearbox for something on the other end of it.
    # ---- what it bolts to ---------------------------------------------------
    if spec.has_motor_face:
        frame = spec.motor
        if spec.motor_drives_the_shaft and \
                abs(frame.shaft_diameter - spec.input_shaft_diameter) > 1e-6:
            # A warning rather than an error: every file this exports is still
            # right - the cam is bored to the shaft the design states.  What is
            # wrong is the pairing, and that is fixed by buying a different
            # motor as easily as by redrawing anything.
            rep.add(Severity.WARNING, "MOTOR_SHAFT_MISMATCH",
                    f"The {frame.name} turns a {frame.shaft_diameter:g} mm shaft "
                    f"and this drive is built around a "
                    f"{spec.input_shaft_diameter:g} mm one. With the motor "
                    f"driving the cam directly they have to be the same shaft: "
                    f"set the input shaft to {frame.shaft_diameter:g} mm, or turn "
                    f"off 'motor drives the shaft' and put a coupling in.",
                    spec.input_shaft_diameter, frame.shaft_diameter)

        # The bolts have to land in the plate, clear of the bore and inside the
        # rim - a pattern that misses the metal is a motor that cannot be bolted
        # on, and nothing else in the app would notice.
        reach = frame.bolt_circle_diameter / 2.0
        # Named for the plate it is actually cut into.  The two are the same
        # size and the same bore, so this is one check either way - but a
        # message that says "input end plate" to somebody looking at a base is
        # a message that sends them to the wrong parameter.
        face = ("carrier's base" if spec.motor_mounts_on_carrier
                else "input end plate")
        if reach - frame.bolt_diameter / 2.0 < spec.hub_bore / 2.0:
            rep.add(Severity.ERROR, "MOTOR_FACE_CLASH",
                    f"The {frame.name} bolt pattern falls into the "
                    f"{spec.hub_bore:.1f} mm bore of the {face} - there "
                    f"is no metal there to bolt to. A smaller frame, or a "
                    f"narrower carrier boss.",
                    2.0 * reach, spec.hub_bore)
        elif reach + frame.bolt_diameter / 2.0 > spec.housing_outer_radius:
            rep.add(Severity.ERROR, "MOTOR_FACE_CLASH",
                    f"The {frame.name} bolt pattern runs off the edge of a "
                    f"{2 * spec.housing_outer_radius:.1f} mm plate. The drive is "
                    f"smaller across than the motor it is being bolted to.",
                    2.0 * reach, 2.0 * spec.housing_outer_radius)

        if not spec.shaft_bearings_fitted:
            crank = contact.eccentric_bearing_load_N * spec.disc_count
            if crank > frame.max_radial_N:
                rep.add(Severity.WARNING, "MOTOR_RADIAL_LOAD",
                        f"With no shaft bearings the {frame.name} carries the "
                        f"whole crank reaction, {crank:.0f} N, against a typical "
                        f"{frame.max_radial_N:.0f} N for that frame. Fit the "
                        f"shaft bearings or use a bigger motor - and check your "
                        f"own datasheet, because these vary by a factor of two "
                        f"between makers.",
                        crank, frame.max_radial_N)

    external = [c for c in bearings if c.carried_elsewhere]
    if external:
        rep.add(Severity.INFO, "BEARINGS_OMITTED",
                "This drive does not carry every load path itself: "
                + ", ".join(c.role.lower() for c in external)
                + " left out. " + " ".join(c.note for c in external if c.note)
                + " The load has not gone anywhere - something this app cannot "
                  "see is taking it, and that something has to be up to it.",
                float(len(external)))

    # A load path left out on purpose and one where nothing in the catalogue fits
    # are different answers.  Reading them apart used to mean looking for a
    # substring in the note, which is the same trick that got the BOM quantities
    # wrong; `fitted` says it outright.
    for choice in bearings:
        if choice.problem:
            rep.add(Severity.WARNING, "BEARING_DOES_NOT_FIT",
                    f"{choice.role}: {choice.problem}.")
        elif choice.fitted and choice.bearing is None and choice.note:
            rep.add(Severity.WARNING, "NO_BEARING_FITS",
                    f"{choice.role}: {choice.note}")
        if choice.bearing is not None and \
                choice.life_hours < spec.bearing_min_life_hours:
            # Only reachable for a bearing asked for by name: the sizing study
            # will not return one under this line, which is why the two numbers
            # have to be the same one.  They were 1000 and 5000, so a bearing
            # could be selected and then complained about in the same breath.
            rep.add(Severity.WARNING, "SHORT_BEARING_LIFE",
                    f"{choice.role} ({choice.bearing.designation}) reaches "
                    f"{choice.life_hours:,.0f} h against the "
                    f"{spec.bearing_min_life_hours:,.0f} h this design asks for.",
                    choice.life_hours, spec.bearing_min_life_hours)

    return DesignAnalysis(spec=spec, report=rep, contact=contact, efficiency=eff,
                          stiffness=stiff, transmission_error=te, thermal=therm,
                          mass=mass, fatigue=fatigue, bearings=bearings,
                          torque_capacity_Nm=capacity)
