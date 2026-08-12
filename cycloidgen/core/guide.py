"""How to choose each parameter, and what it costs to choose it wrong.

:mod:`cycloidgen.core.explain` answers the question a *finding* raises: this
check failed, why does that matter, what do I move.  That is the right answer
once something is already wrong, and it is no help at all to somebody looking at
forty-eight fields for the first time with nothing red yet.  A parameter panel
that only speaks up when it is unhappy teaches you the machine by punishing you.

So this is the other direction.  For each parameter: what it physically *is*,
how to pick it, and what picking it that way costs - because almost every one of
these is a trade rather than a preference, and the trade is the part that is
hard to find out.  A number that only goes one way is rare enough here to be
worth saying so explicitly when it happens.

Three fields, kept apart for the same reason ``Explanation`` keeps its three
apart.  ``what`` is the physical thing, so you know what you are holding.
``choosing`` is the rule, in terms of the other parameters rather than as a
range - a range is only meaningful against a size of drive, and this app spans
two orders of magnitude of them.  ``trade`` is what moves the other way, which
is what turns a value into a decision.

Declared rather than derived, on the same argument as the explanations: the
knowledge is in people's heads and in comments, and neither is reachable from
the panel.  ``tests/test_guide.py`` holds both ends - every field the UI shows
has an entry, and every entry names a field that exists on the spec - so a
parameter added without guidance fails the suite, in exactly the way a check
added without an explanation does.

The live half is not here.  Which checks a parameter currently moves, and how
close each is to its limit, comes from the analysis on screen; this module is
the part that does not change with the design.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["PARAMETERS", "ParameterGuide", "guide"]


@dataclass(frozen=True)
class ParameterGuide:
    """What a parameter is, how to choose it, and what that costs."""

    #: The physical thing, in one or two sentences.
    what: str
    #: How to pick it, in terms of the rest of the design.
    choosing: str
    #: What moves the other way.  Empty only where nothing does.
    trade: str = ""


PARAMETERS: dict[str, ParameterGuide] = {
    # ------------------------------------------------------ cycloid geometry --
    "lobes": ParameterGuide(
        "The number of lobes on the disc, N. The ring gets N+1 pins, and the "
        "reduction is one of those two numbers depending on which member the "
        "output comes off - N off the carrier, N+1 off the ring housing.",
        "Start from the reduction you need; off the carrier it is this number "
        "and off the ring it is one less than this number. Everything "
        "else here is then sized around it rather than the other way about.",
        "A high ratio is a shallow lobe: the contacts get flatter, the pressure "
        "angle rises, and more of the load goes into pushing the disc sideways "
        "into the cam instead of turning the output. Past about 40:1 the "
        "eccentricity has to come down to keep that in hand, and a small "
        "eccentricity is a small output hole margin and more lost motion."),
    "pin_circle_radius": ParameterGuide(
        "R, the radius the ring pin centres sit on. With the pin radius and the "
        "housing wall it sets how big the gearbox is across.",
        "This is the size knob: pick the drive's outside diameter and work back. "
        "Torque capacity climbs faster than linearly with it, so if a design is "
        "short of capacity and has room, this is the first thing to try.",
        "Everything gets bigger and heavier, and mass goes as the square. The "
        "orbiting disc also throws more unbalance force at the same speed."),
    "pin_radius": ParameterGuide(
        "Rr, the radius of each ring pin. It is the roller the disc flank runs "
        "on, and it sets the curvature of the contact.",
        "There is an optimum rather than a direction, and the app computes it: "
        "see the PIN_RADIUS_SUGGESTION note. Too small and the contact patch is "
        "tiny and the pressure high; too large and the flank curvature "
        "approaches the pin's and the profile undercuts.",
        "Growing the pins eats the space between them - past a point they "
        "overlap - and it pushes the profile toward undercut, which is a disc "
        "that cannot be cut rather than one that is merely stressed."),
    "eccentricity": ParameterGuide(
        "E, how far the cam throws the disc off the axis. It is the whole "
        "mechanism: the disc walks round the ring by exactly this much.",
        "Bounded above by the shortening coefficient K1 = E*Np/R, which has to "
        "stay under 1 and wants to be well under it. Larger E means deeper "
        "lobes, more torque and less lost motion.",
        "It is also the amplitude of the disc's orbit, so unbalance force goes "
        "up with it, and the output holes have to be 2E larger than the pins - "
        "which eats the web between them and can shear the disc."),

    # ------------------------------------------------------------------ disc --
    "disc_thickness": ParameterGuide(
        "How thick each cycloidal disc is. Contact length at every ring pin and "
        "every output pin at once.",
        "The cheapest fix for contact stress and for PV: both are load per unit "
        "length, so doubling the thickness halves them. Go here before making "
        "the drive wider.",
        "Length, mass and rotating inertia. A thick stack also loads the "
        "carrier pins further from their root, which is a bending moment on a "
        "cantilever and is what the output pin fatigue check is about."),
    "disc_count": ParameterGuide(
        "How many discs are stacked, each phased against the others - two at "
        "180 degrees, three at 120.",
        "Two, on anything that turns at speed. One disc is an unbalanced mass "
        "orbiting at input speed and it shakes the machine; the second cancels "
        "it. A third mostly buys transmission error rather than capacity.",
        "Length, mass and cost, and the discs are then *different parts* - each "
        "one's hole pattern is turned back against its lobes, so they are not "
        "interchangeable and the export writes them separately."),
    "disc_gap": ParameterGuide(
        "The axial clearance between stacked discs, so they do not rub on each "
        "other as they orbit in opposite directions.",
        "A millimetre is plenty on a printed drive and a few tenths on a "
        "machined one. It is a clearance, not a dimension anything is designed "
        "around.",
        "Only length. There is no reason to make it large."),
    "center_bore_diameter": ParameterGuide(
        "The hole through the middle of the disc. It is the *bearing* seat - "
        "what the cam bearing's outside diameter sits in - not the shaft size.",
        "Sized from the eccentric bearing you intend to use, and that from the "
        "crank reaction. Larger is a stiffer, longer-lived cam bearing.",
        "It eats the disc from the inside: the web between the bore and the "
        "output holes carries the whole output torque in shear, and that "
        "ligament is where a disc actually breaks."),

    # ------------------------------------------------------ output mechanism --
    "output_member": ParameterGuide(
        "Which of the two slow members turns the load: the carrier the output "
        "pins stand on, or the ring housing the pins sit in. Whichever one you "
        "do not pick is the one the gearbox is bolted down by.",
        "Off the carrier for a gearbox with a shaft end, which is what a "
        "machine expects and what the industrial drives are. Off the ring for "
        "a drive whose *outside* turns - a wheel, a pulley, a joint - which is "
        "what most printed micro drives are, and it is also the free extra "
        "tooth of reduction: the same parts give N+1 instead of N. It carries "
        "one real constraint, which is that the motor bolts to the member that "
        "stands still, so the mounting face moves to the other end of the "
        "drive when you change it.",
        "Off the ring the output is a turning barrel: it has no shaft end, so "
        "the load bolts to a face, and anything hung on it is carried by one "
        "bearing on the carrier's boss rather than by a coupling. The output "
        "also turns the same way as the input rather than against it, which "
        "matters if something downstream was counting on the reversal."),
    "output_pin_count": ParameterGuide(
        "How many pins carry the output torque out of the disc.",
        "More is better and it is the strongest single lever on transmission "
        "error - the output pins are nearly all of the ripple, so adding pins "
        "does more than stiffening anything. Six is a starting point, not a "
        "target.",
        "They have to fit on the bolt circle without their holes running into "
        "each other, and each hole is 2E larger than its pin, so the count is "
        "bounded by the eccentricity and the circle you put them on."),
    "output_pin_diameter": ParameterGuide(
        "How thick each output pin is. It is a cantilever off the carrier "
        "plate, loaded at the middle of the disc stack.",
        "Thick enough to survive bending *forever*, not just to hold: these see "
        "a fully reversed cycle every input revolution. The fatigue check is "
        "the binding one and it is far tighter than the static one.",
        "A thicker pin needs a bigger hole - pin plus 2E plus clearance - and "
        "that hole eats the disc web on both sides of it."),
    "output_bolt_circle_radius": ParameterGuide(
        "The circle the output pins stand on. It sets the lever arm the output "
        "torque is carried at.",
        "As large as the disc allows: force is torque over this radius, so "
        "moving it out drops every output pin load in proportion. Roughly 0.55 "
        "to 0.65 of the pin circle is the usable band.",
        "Out toward the rim and the holes break through into the lobes; in "
        "toward the middle and they run into the central bore. The web on "
        "whichever side is thinner is what fails."),
    "output_pins_are_rollers": ParameterGuide(
        "Whether each output pin carries a rotating bush or roller instead of "
        "rubbing directly in its hole.",
        "On, for anything that has to last. The pin/hole contact slides through "
        "every revolution and it is one of the two big sliding losses; a roller "
        "converts it and takes the contact out of the PV regime entirely.",
        "More parts, a bigger hole for the same pin, and a roller has to exist "
        "in the size the seat leaves - the schedule will say when none does."),

    # ------------------------------------------------------ housing and shaft --
    "housing_wall": ParameterGuide(
        "The wall thickness of the ring, measured outside the pin pockets. It "
        "also sets where the tie bolts run and how deep the bearing seats are.",
        "Thick enough that the ring does not breathe under load - the ring is "
        "one of the six compliance terms and on a printed drive it is often the "
        "softest of them. Six millimetres is a reasonable printed default.",
        "Diameter and mass, and both go up faster than the wall does because "
        "it is at the outside."),
    "input_shaft_diameter": ParameterGuide(
        "The shaft the cam is cut on and the motor drives.",
        "From the input torque - which is the output torque divided by the "
        "ratio, so it is usually small - and from the motor you are coupling "
        "to. With the motor driving the cam directly these have to be the same "
        "number.",
        "A fat shaft pushes the cam out, which pushes the bore out, which eats "
        "the disc web. It also sets the carrier boss and the bore of the "
        "outboard shaft support."),
    "eccentric_cam_diameter": ParameterGuide(
        "The outside of the eccentric cam - what the cam bearing sits on, or "
        "what the disc bore runs on directly when there is no bearing.",
        "Leave it automatic unless something outside the drive decides it. "
        "Automatic is the bore less a bearing wall, or the whole bore when no "
        "cam bearing is fitted.",
        "Setting it by hand is how a bearing ends up standing off its journal, "
        "which the fit check reports rather than absorbs."),
    "output_flange_thickness": ParameterGuide(
        "The carrier plate the output pins are pressed into and the boss stands "
        "on.",
        "Thick enough not to be the softest thing in the drive. It is rim-driven "
        "in the compliance model and it is a common surprise at the top of that "
        "table.",
        "Length and mass, and it moves the disc stack further from the output "
        "bearing."),

    # ----------------------------------------------------------- manufacturing --
    "process": ParameterGuide(
        "How the parts are made. Not a label: it decides surface finish, the "
        "clearances that are achievable, the fatigue surface factor and the "
        "position tolerance you can hold.",
        "Say how you will actually make it. Then press *Apply process defaults* "
        "if you want the clearances reset to that guide - changing this field "
        "alone deliberately does not rewrite numbers you may have chosen.",
        "Nothing directly, but it is load-bearing on four other answers, and a "
        "design analysed as machined and then printed is analysed wrong."),
    "offset_mode": ParameterGuide(
        "How the manufacturing clearance is taken out of the theoretical "
        "profile: by growing the generating roller, by shrinking the generating "
        "pin circle, or half of each.",
        "Equidistant is the safe default and gives an even gap all round. The "
        "pin-circle offset distributes the gap differently and pulls more pins "
        "into mesh at low torque, which is worth trying when load concentration "
        "is the complaint.",
        "They deliver the clearance at different places on the flank, so the "
        "lost motion and the load sharing are not the same between them."),
    "profile_clearance": ParameterGuide(
        "How much the disc is shrunk from the theoretical conjugate profile, "
        "per side, so it will actually turn.",
        "From the process, and no tighter than the process holds. It is the "
        "difference between a drive that turns and one that binds.",
        "It is also backlash: every micron of it is lost motion at the output, "
        "and it keeps the low-lever-arm pins out of mesh, which concentrates "
        "load on the few that are touching and derates the torque capacity."),
    "hole_clearance": ParameterGuide(
        "Added to the diameter of the output holes and the central bore so the "
        "pins and the bearing go in.",
        "From the process, like the profile clearance. These are running fits, "
        "not press fits - the carrier drilling template is the one that gets "
        "the press size.",
        "The output-hole share of it is lost motion, and it is usually the "
        "larger of the two contributions."),
    "position_tolerance": ParameterGuide(
        "The true-position tolerance on the pin holes, ring and carrier alike - "
        "stated the way a drawing states it, as a zone diameter.",
        "Enter what your shop actually holds. Zero is not optimism, it is a "
        "different question: it models a perfectly placed ring, which no ring "
        "is, and the answer is the one the app gave before tolerances existed.",
        "It is the sharpest constraint in the app. As it approaches the profile "
        "clearance the pins interfere and the drive binds, and it produces the "
        "missing half of transmission error."),
    "dxf_chord_tolerance": ParameterGuide(
        "How finely the curved profile is sampled when it is written out as a "
        "polyline - the largest gap between the chord and the true curve.",
        "Well inside your machine's own resolution. Five microns is fine for "
        "anything cut here.",
        "File size and how long a CAM package takes to chew on it. It has no "
        "effect on any computed number - the analysis uses the closed form, not "
        "the sampled one."),
    "stl_linear_tolerance": ParameterGuide(
        "How finely the solids are tessellated for STL.",
        "Fine enough that the lobes are not faceted at the size you print. It "
        "is a print-quality setting.",
        "File size and mesh handling time, and nothing else. STL is an output "
        "and no analysis reads it."),

    # --------------------------------------------------------------- materials --
    "disc_material": ParameterGuide(
        "What the cycloidal discs are made of. The most consequential material "
        "choice in the drive: the disc is at every contact.",
        "It sets the contact allowable, the PV limit, the temperature limit and "
        "whether there is a fatigue answer at all. Polymers get no fatigue "
        "number here, deliberately - printed-part fatigue turns on layer "
        "orientation far more than on tensile strength.",
        "The stiff, strong choices are heavier and harder to make. A printed "
        "disc is not a slightly worse steel one at the contacts: it is a "
        "different regime, and the PV checks are the ones that will say so."),
    "pin_material": ParameterGuide(
        "The ring pins and the output pins. Usually a hardened steel dowel "
        "whatever the rest of the drive is.",
        "The softer of the two materials at a contact sets the allowable, so "
        "there is rarely a reason to go below a bearing steel here - it is a "
        "bought part and it costs almost nothing.",
        "Essentially nothing. This is one of the few fields that only goes one "
        "way."),
    "housing_material": ParameterGuide(
        "The ring, the housing barrel, the end plates and the output carrier.",
        "It carries no contact, so it is chosen for stiffness, mass and "
        "temperature rather than for surface strength. It does set the "
        "structure's share of the compliance and the drive's temperature limit "
        "alongside the disc.",
        "Metal is stiff and heavy; a printed housing is most of why a printed "
        "drive measures softer than the mesh model alone suggests."),
    "shaft_material": ParameterGuide(
        "The input shaft and the eccentric cam cut on it.",
        "A steel. With no cam bearing the cam is also a sliding surface against "
        "the disc, and then the pair's PV limit is what decides whether it wears "
        "the bore oval.",
        "None worth counting - it is a small part of the mass."),
    "friction_coefficient": ParameterGuide(
        "The dry sliding coefficient at the rubbing contacts.",
        "With no lubricant this is used as-is, so it should be the pair you "
        "actually have. With one it is the value the computed film is compared "
        "against, and only matters where the film has failed.",
        "None - it is a statement about the materials, not a design choice. If "
        "it is doing too much work in your answer, the fix is a lubricant or "
        "rollers rather than a smaller number here."),
    "lubricant": ParameterGuide(
        "What is between the sliding surfaces. Sets the friction coefficient "
        "from a computed film thickness rather than from a guess.",
        "On a rough surface the film will not form whatever you choose, so pick "
        "for boundary friction - an EP or moly grease is worth about a factor "
        "of two on every sliding loss. On a ground or honed one the grade and "
        "its pressure-viscosity start to matter, because then a film is "
        "actually reachable.",
        "Nothing in the model. In the machine, a seal to keep it in and an "
        "interval to change it."),
    "surface_roughness_um": ParameterGuide(
        "RMS roughness of the sliding faces. Film thickness is measured against "
        "it, so this - not the lubricant - usually decides the regime.",
        "Leave it automatic to take a typical figure for the process, or enter "
        "what you measure. The return on improving it is a cliff rather than a "
        "slope: nothing happens until the film starts to clear the peaks, and "
        "then everything does.",
        "Finishing time and cost, and on a printed part it is not buyable at "
        "all - no grade sold builds a film that clears a layered flank."),
    "ring_pins_integral": ParameterGuide(
        "Whether the ring pins are formed with the housing instead of fitted "
        "into it as separate dowels.",
        "On, if the ring is printed: the pins come out with it, there is "
        "nothing to buy, nothing to press in and no pin position to hold - the "
        "tolerance that decides load sharing becomes the printer's rather than "
        "an assembly's. Off for a machined drive, where a hardened dowel in a "
        "pocket is both a better surface than the housing and replaceable.",
        "The contact is sliding and stays sliding - an integral pin cannot "
        "roll - so it gives up the largest saving in the machine. The pin is "
        "also the housing's material, which on a printed drive is the softest "
        "thing in the load path, and it cannot be changed without changing the "
        "housing with it."),
    "ring_pins_are_rollers": ParameterGuide(
        "Whether the ring pins turn in their pockets - needle rollers - instead "
        "of being fixed dowels.",
        "On, if the drive has to last. This is the largest single loss in the "
        "machine and the one contact that can never get a film while it is "
        "fixed: a stationary pin is dragged across rather than rolled, so it "
        "entrains at half the sliding speed.",
        "N+1 more rolling parts and pockets that have to hold them. A roller "
        "also has to exist in the size the pin leaves."),

    # ---------------------------------------------------------------- mounting --
    "motor_frame": ParameterGuide(
        "The motor that bolts to the input end plate: its bolt pattern, its "
        "register and its shaft.",
        "Pick the frame you are actually using. It cuts the register and the "
        "pattern into the plate - and NEMA patterns are a square, not a bolt "
        "circle, which is why this is a table rather than three numbers.",
        "A small drive can be narrower across than the motor bolted to it, and "
        "the pattern then runs off the plate. That is an error rather than a "
        "warning, because the plate would be wrong."),
    "motor_drives_the_shaft": ParameterGuide(
        "Whether the motor's own shaft *is* the input shaft, so the cam is "
        "bored to it, or whether there is a separate shaft and a coupling.",
        "On is the compact answer and it constrains the input shaft to the "
        "motor's. Off is the honest one whenever they differ - and it needs the "
        "shaft bearings fitted, because then the drive carries its own input.",
        "Off costs a coupling and length. On costs the freedom to size the "
        "shaft, and pairs the drive to one frame."),
    "housing_bolt_count": ParameterGuide(
        "Tie bolts through both end plates into the barrel.",
        "Enough to hold the joint closed under the ring's bursting load - six "
        "is a sensible default. Zero means the plates are held on by something "
        "this app is not drawing, which is a legitimate choice and not a "
        "mistake.",
        "Each one is a hole through the wall, so more bolts want more wall for "
        "them to miss the pin pockets in."),
    "housing_bolt_diameter": ParameterGuide(
        "The hole the tie bolts pass through, in both end plates and the "
        "barrel behind them.",
        "From the bolt you are using. It is the clearance hole rather than the "
        "thread, so it is the bolt's own diameter plus a working fit.",
        "It sets how much metal is left between the bolt circle and the pin "
        "pockets."),
    "output_boss_protrusion": ParameterGuide(
        "How far the output boss stands past the end plate. With the carrier "
        "as the output that is grip length for a coupling or a clamp hub; with "
        "the ring housing as the output it is the gap between the plate that "
        "turns and the base that does not.",
        "Off the carrier, long enough for whatever grips it - the output there "
        "is a boss on the axis rather than a bolt face, so this is the whole "
        "interface, and zero leaves it flush and ungrippable. Off the ring, "
        "enough that the turning plate clears the base and whatever is bolted "
        "through it; a few millimetres is plenty.",
        "Length either way, and off the carrier an overhung load further from "
        "the output bearing."),
    "output_bolt_count": ParameterGuide(
        "Bolts through the turning end plate, for a driven machine to attach "
        "to. Ring output only: with the carrier as the output the interface is "
        "the boss on the axis and this face carries the motor instead.",
        "The same count as the tie bolts unless you have a reason. The two "
        "patterns share one circle - the only radius on that plate with barrel "
        "wall behind it to thread into - and are held apart by half a pitch, "
        "which works exactly when the counts match or one divides the other. "
        "Zero draws none, for a drive whose output is attached some other way.",
        "Holes in the one plate that also carries the tie bolts, and a check "
        "that will stop you when the two patterns run into each other."),
    "output_bolt_diameter": ParameterGuide(
        "The clearance hole those bolts pass through.",
        "From the bolt you are using, like the tie bolts. It has to be smaller "
        "than the housing wall: the circle runs up the middle of that wall, so "
        "a bolt as wide as the wall has the ring-pin pockets on one side of it "
        "and open air on the other.",
        "It sets how much metal is left between an output bolt and the tie "
        "bolt beside it."),

    # ---------------------------------------------------------------- bearings --
    "cam_bearing_fitted": ParameterGuide(
        "Whether there is a needle bearing between the cam and the disc bore, "
        "or the bore runs straight on the cam.",
        "On, unless you have a reason. Off is a real and common choice on small "
        "printed drives, but it is a plain journal at nearly full input speed "
        "carrying the largest force in the machine - the textbook wear failure "
        "of this gearbox.",
        "Off saves a part and grows the cam to fill the bore, and pays the "
        "sliding coefficient at the fastest contact in the drive - on the order "
        "of thirty points of efficiency on a steel design."),
    "shaft_bearings_fitted": ParameterGuide(
        "Whether the drive carries its own input shaft, or hangs on the driving "
        "motor's bearings.",
        "On, unless the drive is bolted to a motor whose bearings you have "
        "checked. Off puts the whole crank reaction into the motor, and stepper "
        "bearings are sized to turn a shaft rather than to carry a gearbox.",
        "Off saves two bearings and some length. The load has not gone "
        "anywhere - something outside this app is taking it."),
    "output_bearing_fitted": ParameterGuide(
        "Whether the drive locates its own output flange, or the machine it "
        "drives does.",
        "On for a self-contained gearbox. Off is right when the output is "
        "bolted to something already running in its own bearings, and then that "
        "drag belongs to the machine rather than to this gearbox.",
        "Off leaves the flange located by something this app cannot see, and "
        "that something has to be up to it."),
    "cam_bearing": ParameterGuide(
        "Which bearing goes in the cam seat, or *auto* to let the sizing study "
        "choose.",
        "Auto takes the smallest catalogue part that fits the seat and reaches "
        "the required life. Name one when something outside the geometry "
        "decides - a bearing already in the drawer, or one your supplier "
        "stocks.",
        "A named part is checked against its seat, never quietly swapped: being "
        "told it does not fit is the point of asking for it by name."),
    "shaft_bearing": ParameterGuide(
        "The two input shaft supports, one in each end plate.",
        "As above - auto unless you are naming a part you have.",
        "Both supports take the same designation; they sit in the same "
        "diameter."),
    "output_bearing": ParameterGuide(
        "The main output bearing, between the carrier boss and the output end "
        "plate.",
        "As above. This is the one that carries the whole output reaction, so "
        "it is the one most worth naming if you have a preference.",
        "It seats on the boss, so its bore follows the boss diameter - which "
        "follows the input shaft."),
    "ring_pin_roller": ParameterGuide(
        "The needle roller on each ring pin. Only used when the ring pins are "
        "rollers.",
        "Auto, which takes the smallest that fits the pin and lasts.",
        "Nothing dimensional - it is a selection. What it can cost is "
        "availability: the seat here is the smallest in the drive and often "
        "nothing in the catalogue fits, in which case the schedule says so "
        "rather than drawing a roller to a guessed wall."),
    "output_pin_roller": ParameterGuide(
        "The roller or bush on each output pin. Only used when the output pins "
        "carry rollers.",
        "Auto, unless you are matching something you already have.",
        "Nothing dimensional. Worth knowing where it does bite: the pin is "
        "pressed into the carrier by its shank, which is the smaller diameter, "
        "and it is the shank the drilling template uses rather than the "
        "diameter the disc runs on."),
    "bearing_min_life_hours": ParameterGuide(
        "The L10 life a bearing has to reach before the sizing study will take "
        "it - and the line the short-life warning is measured against.",
        "From the duty: what the machine is for and how long it has to run. "
        "Five thousand hours is a reasonable general-purpose figure.",
        "Asking for more life makes the study pick bigger bearings, which need "
        "bigger seats, which push the geometry out."),

    # -------------------------------------------------------------------- duty --
    "input_rpm": ParameterGuide(
        "How fast the input turns. Output speed is this divided by the ratio.",
        "From the motor and the job. It is a duty point rather than a design "
        "dimension, and the fastest way to fix a wear or heat complaint without "
        "touching a single dimension.",
        "Sliding speed, and PV with it, are linear in this - so is the heat, "
        "and so is the unbalance force squared. A drive that is comfortable at "
        "500 rpm can be finished in an afternoon at 3000."),
    "output_torque_Nm": ParameterGuide(
        "The torque the drive is being asked to deliver. Every load in the app "
        "comes from this one number.",
        "The duty you are designing for, not the peak the drive could survive - "
        "the torque capacity is an output and is reported separately.",
        "It scales every contact force, every stress and every loss. If the "
        "checks are unhappy it is worth being sure this is the duty and not a "
        "stall figure."),
    "ambient_temp_C": ParameterGuide(
        "The air around the housing. The predicted running temperature is a "
        "rise added to this.",
        "The environment the drive actually lives in. Inside an enclosure is "
        "not room temperature.",
        "None on the mechanics, but it moves the running temperature one for "
        "one - and that sets the fatigue temperature factor, thins the "
        "lubricant, and is what the service-temperature check compares."),
}


def guide(name: str) -> ParameterGuide | None:
    """The guidance for one parameter, or ``None`` where there is none."""
    return PARAMETERS.get(name)
