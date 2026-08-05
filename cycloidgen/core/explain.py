"""What each check is testing, why it matters, and what to change.

A finding already carries a verdict, a value and a limit.  What it cannot carry
is the *reason* - the relation being tested, the physics it is protecting, and
which knob moves it.  That knowledge existed only in the comments beside each
check, where the person who most needs it cannot reach it.

Declared here rather than parsed out of docstrings.  One check function often
raises two codes at different thresholds, several are raised from
:mod:`cycloidgen.analysis` rather than from :mod:`cycloidgen.core.validate`, and
a docstring is prose that nobody is obliged to keep in any particular shape - so
scraping it would be a guess that quietly rots.  A declaration is a promise, and
``tests/test_explain.py`` holds both ends of it: every code the application can
emit has an entry, and every entry names a code that something can actually
emit.  The codes are found by parsing the source for the calls that raise them,
so adding a check without explaining it fails the suite.

The three fields are deliberately separate.  ``tests`` is the relation, in the
notation the README uses; ``why`` is what goes wrong physically when it fails;
``fix`` is what to change and in which direction.  Merging them produces a
paragraph that answers none of the three questions well.
"""
from __future__ import annotations

from dataclasses import dataclass

from .validate import Finding

__all__ = ["EXPLANATIONS", "Explanation", "explain", "margin"]

#: With ``R`` the ring-pin circle radius, ``Rr`` the pin radius, ``E`` the
#: eccentricity, ``N`` the lobe count and ``Np = N+1`` the pin count - the same
#: symbols the README and the profile module use.


@dataclass(frozen=True)
class Explanation:
    """Why a check exists, in three parts."""

    title: str
    #: The relation being tested, as an expression.
    tests: str
    #: What physically goes wrong when it fails.
    why: str
    #: What to change, and which way.
    fix: str
    #: Which side of the limit the design wants to be on: ``"below"``,
    #: ``"above"``, or ``""`` when the finding is a reading rather than a test.
    keep: str = "below"
    #: The unit ``value`` and ``limit`` are in, for the readout.
    unit: str = ""


EXPLANATIONS: dict[str, Explanation] = {
    # ------------------------------------------------------------- profile --
    "K1_TOO_HIGH": Explanation(
        "Shortening coefficient out of range",
        "K1 = E*Np/R  <  1",
        "K1 is how far the eccentricity carries the pin-centre locus relative to "
        "its own radius. At 1 the locus develops cusps and beyond it the "
        "envelope has no single-valued solution, so there is no profile to cut.",
        "Reduce the eccentricity, or raise the pin circle radius. More lobes at "
        "the same E and R also raises K1, because Np is in the numerator."),
    "K1_HIGH": Explanation(
        "Shortening coefficient high",
        "K1 = E*Np/R  <  0.75",
        "Approaching 1 the lobes come to a point: the profile's radius of "
        "curvature at the tip collapses, and with it the equivalent contact "
        "radius that sets Hertzian pressure.",
        "Lower the eccentricity or raise the pin circle radius. This is a "
        "guide, not a wall - a stiff steel drive can live above it."),
    "UNDERCUT": Explanation(
        "Pin radius past the undercut limit",
        "Rr_eff  <  rho_c,  the tightest concave radius of the pin-centre locus",
        "A roller larger than the tightest hollow it has to roll into cannot "
        "reach the bottom of it. The envelope folds back through itself and the "
        "generated outline is not a curve any process can produce.",
        "Reduce the pin radius, or reduce the eccentricity - rho_c opens up as "
        "E falls. The clearance is included: a large profile clearance in "
        "equidistant mode grows the *generating* roller and can trip this on "
        "geometry that is fine without it."),
    "UNDERCUT_MARGIN": Explanation(
        "Close to the undercut limit",
        "Rr_eff  <  0.85 * rho_c",
        "The last 15% is eaten by the clearance you build to and by the "
        "tolerance you actually hold, neither of which the ideal geometry "
        "knows about.",
        "Same lever as UNDERCUT: a smaller pin radius or less eccentricity."),
    "PIN_RADIUS_SUGGESTION": Explanation(
        "Pin radius away from the stress optimum",
        "R_eq = Rr*(1 - Rr/rho_c),  which peaks at Rr = rho_c/2",
        "Contact stress falls as the equivalent contact radius grows, and R_eq "
        "is a parabola in Rr - so a bigger pin is not monotonically better. Past "
        "half the critical radius the profile's own curvature tightens faster "
        "than the pin grows, and the contact gets sharper again.",
        "Move the pin radius toward the suggested value. It is a note, not a "
        "fault: pin availability and ring strength are real constraints too.",
        keep="", unit="mm"),
    "PROFILE_SELF_INTERSECT": Explanation(
        "Outline crosses itself",
        "no two segments of the sampled outline intersect",
        "The generated curve doubles back through itself. There is no solid "
        "with that boundary, so nothing downstream - DXF, STEP, mesh - means "
        "anything.",
        "Almost always undercut in disguise: reduce the pin radius or the "
        "eccentricity. Check UNDERCUT first, it names the same cause with a "
        "number attached.", keep=""),
    "PROFILE_INTERFERENCE": Explanation(
        "Disc overlaps the ring pins",
        "min over the pins of (distance to the manufactured profile - Rr)  >=  0",
        "Measured against the profile that will actually be cut, not the "
        "theoretical one. Negative means the disc and a pin want the same space "
        "at the nominal mesh position: it cannot be assembled, let alone turn.",
        "Raise the profile clearance, and check the offset mode - it decides "
        "whether the clearance shrinks the disc or grows it.",
        keep="above", unit="mm"),
    "CLEARANCE_NOT_DELIVERED": Explanation(
        "Requested clearance does not reach the part",
        "measured gap  >=  0.25 * profile_clearance",
        "Asking for clearance and getting it are different things: the offset "
        "mode decides how much of the request survives into the geometry, and "
        "the gap is measured here rather than assumed.",
        "Try the equidistant mode, which gives every pin the same normal gap, "
        "or raise the clearance until the measured gap is what you wanted.",
        keep="above", unit="mm"),

    # ------------------------------------------------------------ ring pins --
    "PIN_OVERLAP": Explanation(
        "Ring pins intersect",
        "pitch = 2*R*sin(pi/Np)  >  2*Rr",
        "Adjacent pins occupy the same material. The ring cannot be drilled, "
        "never mind assembled.",
        "Smaller pins, a larger pin circle, or fewer lobes.",
        keep="above", unit="mm"),
    "PIN_SPACING": Explanation(
        "Little material between ring pins",
        "pitch = 2*R*sin(pi/Np)  >  2.2*Rr",
        "The web between two pin holes carries the ring's hoop load and is "
        "what stops a pressed pin from splitting the housing out.",
        "Smaller pins, a larger pin circle, or fewer lobes - as "
        "PIN_OVERLAP, with more room asked for.",
        keep="above", unit="mm"),

    # --------------------------------------------------------- output holes --
    "HOLE_HITS_BORE": Explanation(
        "Output holes break into the bore",
        "bolt_circle - hole_r - bore_r  >  0",
        "The output pin holes and the central bearing bore intersect, so there "
        "is no disc between them - the part falls into pieces at the first cut.",
        "Move the bolt circle outward, shrink the central bore, or use smaller "
        "output pins.", keep="above", unit="mm"),
    "THIN_INNER_WEB": Explanation(
        "Thin web between holes and bore",
        "bolt_circle - hole_r - bore_r  >  2 mm",
        "That ligament carries the whole output torque into the bore boss, and "
        "it is loaded in shear on a printed part with layer lines across it.",
        "Move the bolt circle outward, or shrink the bore.",
        keep="above", unit="mm"),
    "HOLE_BREAKS_RIM": Explanation(
        "Output holes break through the rim",
        "root_radius - (bolt_circle + hole_r)  >  0",
        "The holes open into the cycloidal flank, which destroys the mesh "
        "surface the drive works through.",
        "Move the bolt circle inward, or use smaller output pins.",
        keep="above", unit="mm"),
    "THIN_OUTER_WEB": Explanation(
        "Thin rim outside the output holes",
        "root_radius - (bolt_circle + hole_r)  >  2 mm",
        "The rim between a hole and the profile root is the thinnest loaded "
        "section on the disc, and it sees the contact force directly.",
        "Move the bolt circle inward, or use smaller output pins.",
        keep="above", unit="mm"),
    "OUTPUT_HOLES_OVERLAP": Explanation(
        "Output holes overlap each other",
        "2*bolt_circle*sin(pi/n) - 2*hole_r  >  0,  n output pins",
        "Adjacent holes merge into one slot, so nothing locates the disc "
        "against the carrier.",
        "Fewer output pins, smaller pins, or a larger bolt circle. Remember the "
        "hole is the pin plus 2E plus the fit - the eccentricity is in there.",
        keep="above", unit="mm"),
    "OUTPUT_HOLE_SPACING": Explanation(
        "Thin web between output holes",
        "2*bolt_circle*sin(pi/n) - 2*hole_r  >  1.5 mm",
        "The web between two holes is what carries load from one pin to the "
        "next around the disc.",
        "Fewer or smaller output pins, or a larger bolt circle.",
        keep="above", unit="mm"),
    "ECCENTRIC_TIGHT": Explanation(
        "No room for the eccentric bearing",
        "center_bore  >  input_shaft + 2*E",
        "The cam is offset from the shaft by E, so it needs E of extra radius on "
        "each side before a bearing has anywhere to sit.",
        "Enlarge the central bore, use a thinner input shaft, or reduce the "
        "eccentricity.", keep="above", unit="mm"),

    # ----------------------------------------------------------- machining --
    "TOOL_RADIUS": Explanation(
        "Smallest concave radius on the profile",
        "cutter diameter  <  2 * rho_tool",
        "A milling cutter leaves its own radius in every inside corner, so any "
        "cutter bigger than the tightest hollow will not reach the bottom of "
        "it - the profile comes out fuller than drawn and the drive binds.",
        "Choose a cutter under the stated diameter, or wire EDM the profile. "
        "Raising the pin radius opens the hollows up.", keep="", unit="mm"),
    "CLEARANCE_DEFICIT": Explanation(
        "Profile clearance below the process guide",
        "profile_clearance  >=  0.5 * the guide for this process",
        "Every process has a repeatability floor. Asking for a tighter fit than "
        "it can hold does not produce a tighter drive, it produces one that "
        "binds on the tolerance.",
        "Raise the clearance, or select a process that holds it - Apply process "
        "defaults sets both clearances to the guide.",
        keep="above", unit="mm"),
    "HOLE_CLEARANCE_DEFICIT": Explanation(
        "Hole clearance below the process guide",
        "hole_clearance  >=  0.5 * the guide for this process",
        "The output pins have to slide in their holes through every revolution. "
        "Below the process floor they seize instead.",
        "Raise the hole clearance, or select a process that holds it.",
        keep="above", unit="mm"),

    # ---------------------------------------------------------- disc stack --
    "DISCS_DIFFER": Explanation(
        "The discs in the stack are different parts",
        "output_pin_count is a multiple of 2*N",
        "A disc on crank phase p must turn by p/N to stay meshed, but every disc "
        "drives the same carrier and so must share its rotation. The only way "
        "both hold is to pre-rotate each hole pattern by -p/N - which makes the "
        "discs distinct parts unless that rotation lands on a whole hole pitch.",
        "Nothing to fix; it is a fact about the stack. It is worth knowing "
        "before you machine one disc and copy it.", keep="", unit=""),

    # ------------------------------------------------------------ dynamics --
    "SINGLE_DISC_UNBALANCE": Explanation(
        "One disc at speed",
        "disc_count  >  1  above 500 rpm",
        "A single orbiting disc is an unbalanced rotating mass; the force grows "
        "with the square of speed and goes straight into the input bearing.",
        "Use two discs at 180 degrees, or add a counterweight to the shaft.",
        keep="", unit="rpm"),
    "UNBALANCE_FORCE": Explanation(
        "Unbalance comparable to the working load",
        "m*E*omega^2  <  half the tangential working load",
        "The orbiting mass throws a rotating force that the bearings carry all "
        "the time, whether or not the drive is transmitting torque.",
        "A second disc at 180 degrees cancels most of it; a counterweight on "
        "the shaft cancels the rest. Slowing the input helps as the square.",
        keep="", unit="N"),
    "PRESSURE_ANGLE": Explanation(
        "Pressure angle at the worst-loaded contact",
        "angle between the contact normal and the tangential direction  <  55 deg",
        "Only the tangential component of a contact force makes torque. The "
        "rest is radial load pushing the disc off its bearing and the pins out "
        "of the ring. Measured at the most loaded contact, because contacts "
        "near the disc centre have a steep angle and carry nothing.",
        "Lower the eccentricity or raise the pin circle radius - both flatten "
        "the worst angle.", unit="deg"),

    # ------------------------------------------------------- contact stress --
    "HERTZ_STRESS_RING": Explanation(
        "Ring pin contact pressure past the allowable",
        "peak Hertzian line-contact pressure  <  the softer material's allowable",
        "Two cylinders in line contact concentrate the whole pin force into a "
        "strip a fraction of a millimetre wide. The softer of disc and pin sets "
        "the limit, and on a printed drive that is always the disc.",
        "Thicker discs spread the load along the pin; a pin radius nearer the "
        "optimum widens the contact; a harder disc material raises the "
        "allowable. Less output torque works too.", unit="MPa"),
    "HERTZ_STRESS_MARGIN": Explanation(
        "Less than 1.5x margin on ring contact",
        "peak Hertzian pressure  <  allowable / 1.5",
        "The ideal model shares load evenly over the engaged pins. Clearance "
        "does not, and the derating for that is applied separately - so a bare "
        "1.0 here is not really 1.0.",
        "Thicker discs, a pin radius nearer the optimum, or a harder "
        "disc material - the same three levers as HERTZ_STRESS_RING.",
        unit="MPa"),
    "HERTZ_STRESS_OUTPUT": Explanation(
        "Output pin contact pressure past the allowable",
        "peak Hertzian pressure at the pin/hole contact  <  allowable",
        "Only the half of the output pins with a favourable lever arm can push, "
        "so the working set is smaller than the count suggests.",
        "Larger output pins, more of them, or a thicker disc. Bushings on the "
        "pins raise the allowable by changing what the disc runs against.",
        unit="MPa"),

    # ------------------------------------------- efficiency and compliance --
    "LOW_EFFICIENCY": Explanation(
        "Predicted efficiency below 50%",
        "eta = output power / input power  >  50%",
        "Loss here is sliding friction at the ring and output contacts. It "
        "scales directly with the friction coefficient, so a dry printed drive "
        "on fixed pins is mostly heat.",
        "Rolling ring pins and output bushings are the two biggest wins - "
        "either replaces a sliding coefficient with a rolling one an order "
        "smaller. Lubrication moves the same number.",
        keep="above", unit="%"),
    "TORSIONAL_STIFFNESS": Explanation(
        "Torsional stiffness at the output",
        "the mesh contacts and the structure around them, in series",
        "How far the output turns under load before the input has moved at all. "
        "Both halves are counted: the Hertzian contacts at the ring and output "
        "pins, and the parts they are mounted in - the pin seats, the carrier "
        "pins in bending, the plate, the disc body, the housing and the shaft.",
        "Which lever works depends on which half is softer, and the finding "
        "says which. Joints, fits and fasteners are still not modelled, so a "
        "real drive measures softer than this - treat it as a comparison "
        "between designs rather than a promise.",
        keep="", unit="Nm/arcmin"),
    "STRUCTURAL_COMPLIANCE": Explanation(
        "Where the give actually is",
        "structure stiffness  >  contact stiffness",
        "A cycloidal drive is sold on its mesh, but the mesh is only as good as "
        "what holds it. Ring pins bed into their housing pockets, carrier pins "
        "stand off the plate as cantilevers, the plate and the disc carry "
        "torque across themselves, and the crank winds up. On a printed drive "
        "those add up to more give than the contacts have.",
        "Read the softest part off the finding and go at that one. Fatter "
        "carrier pins are usually the biggest single win - a cantilever goes as "
        "the fourth power of diameter - followed by a stiffer housing material, "
        "which is what the pin seats and the carrier plate are made of.",
        keep="above", unit="Nm/arcmin"),
    "TRANSMISSION_ERROR": Explanation(
        "Ripple in the output angle under load",
        "peak-to-peak of the loaded rotation through the mesh cycle",
        "Lost motion is the play before the output moves; this is what the "
        "output does once it *is* moving. Turning the drive hands load from one "
        "contact to the next, and both the gap that has to be taken up and the "
        "deflection under load change at the handover - so the output leads and "
        "lags the exact ratio by this band. It is what limits contouring "
        "accuracy, and unlike lost motion you cannot preload it out.",
        "More output pins is the biggest lever, because the output stage is "
        "usually most of it and more pins make each handover smaller. A tighter "
        "hole fit and a phased multi-disc stack take out much of the rest. Note "
        "what does *not* work: a stiffer disc material leaves the clearance term "
        "untouched and puts the load on fewer pins, which can make it worse.",
        keep="", unit="arcmin"),
    "LOST_MOTION": Explanation(
        "Backlash at the output",
        "lost motion  <  60 arcmin",
        "The angle the output turns through before the input picks it up: the "
        "profile clearance and the output hole fit, each converted to an output "
        "angle. It is the number that decides whether the drive can position.",
        "A tighter process cuts the profile share; a tighter hole fit cuts the "
        "other. The split between the two is in the finding's own message, so "
        "you can tell which one to spend on.", unit="arcmin"),
    "PIN_POSITION": Explanation(
        "Where the pins actually are",
        "true-position tolerance  <  the clearance it has to fit inside",
        "Everything else in the app places the pins exactly, and with a uniform "
        "clearance that means they all come into mesh together. Real holes are "
        "off by a few hundredths, and that is enough to decide which pins "
        "arrive first and carry the load alone. Past the point where the "
        "tolerance is comparable to the clearance the pins interfere and the "
        "drive binds instead of turning.",
        "Enter what your process actually holds - the finding names the guide "
        "value for the one selected. Then either open the profile clearance so "
        "the position error fits inside it, or hold the holes tighter: a "
        "drilled and reamed ring plate is worth an order of magnitude over a "
        "printed one.", unit="mm"),
    "LOAD_CONCENTRATION": Explanation(
        "Clearance concentrates the load on a few pins",
        "peak pin force / ideal share  <  1.5",
        "With an equidistant offset every pin starts the same gap away from "
        "contact, and a contact with a short lever arm needs far more rotation "
        "to close it. So at low torque a handful of pins carry everything, and "
        "the torque capacity is derated by this factor.",
        "A tighter profile clearance pulls more pins in, as does more torque. "
        "The pin_circle offset mode distributes the gap differently and is "
        "worth trying."),

    # ------------------------------------------------------- wear and heat --
    "PV_LIMIT_RING": Explanation(
        "Ring pin sliding duty past the wear limit",
        "p*v  <  the PV limit for this material pair",
        "PV is a wear limit, not a strength limit: a contact can sit far inside "
        "its stress allowable and still be worn round in an afternoon. On the "
        "projected-area convention, which is what the material table uses.",
        "Rolling ring pins remove the sliding entirely and are the real fix. "
        "Otherwise drop the input speed, or move to a material pair with a "
        "higher PV.", unit="MPa m/s"),
    "PV_MARGIN_RING": Explanation(
        "Less than 2x margin on ring pin wear",
        "p*v  <  the PV limit / 2",
        "Inside the limit, but the limit itself is a design-guide figure for "
        "dry running against steel, not a certified value.",
        "Rolling ring pins remove the sliding term entirely; otherwise drop the "
        "input speed, which moves v directly.", unit="MPa m/s"),
    "PV_LIMIT_OUTPUT": Explanation(
        "Output pin sliding duty past the wear limit",
        "p*v at the pin/hole contact  <  the PV limit for the pair",
        "The output pins slide in their holes through every revolution, over a "
        "path set by the eccentricity, and the holes are in the disc material.",
        "Bushings or rollers on the output pins fix this directly. Larger or "
        "more numerous pins drop the pressure term.", unit="MPa m/s"),
    "BEARING_DOES_NOT_FIT": Explanation(
        "The bearing named for a seat will not go in it",
        "bore >= what it sits on, outside <= what it sits in, width <= the room",
        "A bearing asked for by name is checked against its seat and never "
        "quietly swapped for one that fits, because 'this is the bearing I "
        "have' is exactly the case where a substitution is useless. A bore "
        "larger than the shaft or cam it goes on is reported too: that is a fit, "
        "but a loose one, and a press fit onto nothing is not a fit at all.",
        "Turn the journal to the bearing's bore, open the housing around it, or "
        "put the seat back on automatic and take what the study picks."),
    "PV_LIMIT_CAM": Explanation(
        "Cam journal sliding duty past the wear limit",
        "p*v at the cam/bore contact  <  the PV limit for the pair",
        "With no cam bearing fitted, the disc bore is a plain journal running "
        "straight on the eccentric cam. That contact carries the largest single "
        "force in the drive and rubs at nearly the input speed, which makes it "
        "the hardest-worked sliding pair in the machine - the bore wears oval "
        "long before any part is close to breaking.",
        "Fit the cam bearing. If it has to stay plain, a bronze bushing in the "
        "bore and a lower input speed are what make it survivable.",
        unit="MPa m/s"),
    "BEARINGS_OMITTED": Explanation(
        "Load paths this drive does not carry itself",
        "-",
        "A cycloidal drive has five rolling interfaces and three of them can be "
        "left to something else: the cam can run plain, the input shaft can hang "
        "on the driving motor's own bearings, and the output flange can be "
        "located by the machine it drives. All three are ordinary ways to build "
        "one. None of them makes the load go away - it moves somewhere this app "
        "cannot see, and the thing it moves to has to be up to it.",
        "Nothing, if that is the design. The schedule says what is carrying each "
        "omitted path and how hard; check that against the motor's radial load "
        "rating or the machine's own bearings."),
    "OVERTEMP": Explanation(
        "Past the material's service temperature",
        "T = ambient + loss / (h*A)  <  the disc material's service limit",
        "Free convection off the housing barrel and its two end faces, with no "
        "credit for conduction into whatever it is bolted to - the pessimistic, "
        "free-standing case. Polymers creep well below this line.",
        "Raise the efficiency (rolling elements), slow the input down, or build "
        "it from something with more headroom.", unit="C"),
    "RUNNING_HOT": Explanation(
        "Using most of the temperature headroom",
        "temperature rise  <  60% of the gap between ambient and the limit",
        "Inside the limit at the stated ambient, with little left for a warm "
        "room or an enclosure.",
        "Raise the efficiency with rolling elements, slow the input down, "
        "or pick a material with more headroom. Note that the ambient is "
        "a parameter: an enclosed drive is not running in 20 C air.",
        unit="C"),

    # ---------------------------------------------------- disc and bearings --
    "FATIGUE_LIFE": Explanation(
        "Fully reversed duty on the disc web and the output pins",
        "alternating stress  <  corrected fatigue strength  (Goodman)",
        "Every other strength check in this app asks whether a part survives "
        "its peak load once. These two are loaded and unloaded once per input "
        "revolution - the disc web because the load sweeps a whole turn around "
        "it, the output pins because the push rotates about them - so they are "
        "asked whether they survive doing that forever. A part can sit well "
        "inside its yield stress and still crack, because a crack starts at a "
        "stress that would never yield the section.",
        "Thicken the ligament or the pin, share the load over more output pins, "
        "or change material for fatigue strength rather than for yield - they "
        "are not the same ranking. A better surface finish is the cheapest "
        "move: fatigue cracks start at the surface, so a ground disc and a "
        "printed one differ by a factor of three on the same alloy.",
        keep="above", unit="MPa"),

    "FATIGUE_MARGIN": Explanation(
        "Thin margin on fully reversed duty",
        "alternating stress  <  corrected fatigue strength / 1.5",
        "Fatigue strengths scatter far more than static ones - the published "
        "figure is a mean, and this check has already taken 99% reliability off "
        "it. A margin that would be comfortable on yield is not comfortable "
        "here.",
        "Same moves as the fatigue check itself: a thicker section, more output "
        "pins, or a better surface.",
        keep="above", unit="MPa"),

    "FATIGUE_NOT_MODELLED": Explanation(
        "No fatigue check for this material",
        "reported rather than tested",
        "The disc web and the output pins see a fully reversed cycle every "
        "input revolution, which is a real question for any material. It is not "
        "answered for polymers: printed-part fatigue turns on layer "
        "orientation, void content and temperature far more than on tensile "
        "strength, and the classical correction was fitted to wrought metals. A "
        "number produced that way would be confident and unfounded.",
        "Nothing to change in the design. If the drive is meant to run "
        "continuously rather than intermittently, test a printed part rather "
        "than trusting any calculation - including this one's silence.",
        keep=""),

    "WEB_SHEAR": Explanation(
        "The ligament beside the output holes shears",
        "shear stress  <  0.577 * yield  (von Mises)",
        "Output pin load crosses the ligament between a hole and the nearest "
        "free surface. That ligament is the thinnest structural path on the "
        "disc, and it is the one that fails first.",
        "Move the bolt circle to open the thinner side, add output pins to "
        "share the load, or thicken the disc.", unit="MPa"),
    "WEB_SHEAR_MARGIN": Explanation(
        "Less than 2x margin on the ligament",
        "shear stress  <  0.577 * yield / 2",
        "A static check on a section that sees a fully reversed cycle every "
        "input revolution, so the static margin is not the whole story.",
        "Move the bolt circle to open the thinner side, add output pins, "
        "or thicken the disc - the ligament grows with all three.",
        unit="MPa"),
    "MASS": Explanation(
        "Assembled mass and reflected inertia",
        "reflected inertia = disc inertia / ratio^2, seen at the input",
        "What the motor has to accelerate. The reduction divides it by the "
        "square of the ratio, which is why a heavy output stage matters less "
        "than it looks.",
        "Thinner discs and walls, or a lighter housing material.",
        keep="", unit="g"),
    "NO_BEARING_FITS": Explanation(
        "No catalogue bearing fits",
        "a metric-series bearing exists within the available envelope",
        "The bore, the shaft and the disc thickness together leave no room for "
        "a standard bearing in that position.",
        "Enlarge the central bore, thin the shaft, or thicken the disc. Fixed "
        "pins with no bearing are a legitimate answer for a slow drive.",
        keep="", unit=""),
    "SHORT_BEARING_LIFE": Explanation(
        "Bearing L10 life is short",
        "L10 = (C/P)^p * 10^6 / (60*rpm)  >  5000 h",
        "Nominal catalogue life at the rated duty point, for a purely radial "
        "load. Misalignment and combined loading are not modelled and both cut "
        "it further.",
        "A larger bearing, a lower input speed, or less load - which for the "
        "eccentric bearing means less output torque.",
        keep="above", unit="h"),
}


def explain(code: str) -> Explanation | None:
    """The explanation for a check code, or ``None`` if there is not one."""
    return EXPLANATIONS.get(code)


def margin(finding: Finding) -> float | None:
    """How many times over the limit a finding sits, or ``None``.

    A ratio only means something when both numbers are positive and the check
    has a side it wants to be on.  A clearance measured as -0.4 mm is a real
    reading and a useless denominator, and a reading like MASS has no limit to
    be a multiple of - so those get no ratio rather than a misleading one.
    """
    detail = EXPLANATIONS.get(finding.code)
    if detail is None or not detail.keep:
        return None
    if finding.value is None or finding.limit is None:
        return None
    if finding.value <= 0.0 or finding.limit <= 0.0:
        return None
    if detail.keep == "below":
        return finding.limit / finding.value
    return finding.value / finding.limit
