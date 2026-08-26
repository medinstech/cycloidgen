"""Single source of truth for a cycloidal drive design.

Every other module consumes a ``GearSpec``.  All lengths are millimetres,
all angles radians unless a name says otherwise.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

# The motor lives in its own module because it is two separate facts - a face to
# bolt to and a torque against speed - and only the first of them is geometry.
# Re-exported here because every consumer already reaches for the spec, and a
# name that moves house is a name that breaks a dozen imports for no gain.
from .motor import (
    MOTOR_FRAMES,
    NO_MOTOR,
    MotorCurve,
    MotorFrame,
    MotorKind,
    curve_from,
)


class Material(BaseModel):
    """Elastic, strength and tribological data for one part."""

    name: str
    E_GPa: float = Field(gt=0, description="Young's modulus")
    nu: float = Field(gt=0, lt=0.5, description="Poisson's ratio")
    sigma_contact_MPa: float = Field(
        gt=0, description="allowable Hertzian contact pressure (rough, design guide)"
    )
    density_g_cm3: float = Field(gt=0)
    sigma_yield_MPa: float = Field(
        gt=0, description="yield (metals) or tensile strength (polymers)"
    )
    pv_limit_MPa_m_s: float = Field(
        gt=0,
        description="limiting PV for dry sliding against steel, projected-area "
                    "convention - the wear/melting limit, not a strength limit",
    )
    max_service_temp_C: float = Field(
        gt=0, description="continuous service temperature; polymers creep well below it"
    )
    sigma_ultimate_MPa: float = Field(
        gt=0, description="ultimate tensile strength"
    )
    fatigue_strength_MPa: float | None = Field(
        default=None,
        description="uncorrected fatigue strength for fully reversed bending - the "
                    "endurance limit where the material has one, otherwise the "
                    "strength at the life quoted in MATERIALS. None where no "
                    "defensible value exists, which is every polymer here",
    )

    @property
    def shear_allow_MPa(self) -> float:
        """Von Mises shear allowable."""
        return 0.577 * self.sigma_yield_MPa

    @property
    def has_fatigue_data(self) -> bool:
        """Whether a fatigue life can be estimated for this material at all.

        The alternative to answering "no" here is a number derived from a rule
        that was fitted to wrought metals, applied to a printed polymer whose
        fatigue behaviour depends on layer orientation more than on its tensile
        strength.  That is worse than silence.
        """
        return self.fatigue_strength_MPa is not None


#: Rough design-guide values.  Contact allowables for polymers are conservative
#: because they creep; the steel values assume a hardened, ground surface.  The
#: PV limits are dry-against-steel figures on the projected-area convention, so
#: they are only meaningful against a projected-area pressure - see
#: :mod:`cycloidgen.analysis.thermal`.  100Cr6's service temperature is the
#: dimensional-stability limit of standard bearing steel, not a strength limit.
#: Fatigue strengths are for fully reversed bending and **uncorrected** - the
#: specimen value, before surface, size, temperature and reliability are applied
#: in :mod:`cycloidgen.analysis.fatigue`.  Steels get the endurance limit they
#: actually have, which is why 100Cr6 is not 0.5*Sut: that rule stops holding
#: above about 1400 MPa and the limit flattens off near 700.  Aluminium and
#: bronze have no endurance limit at all, so those are strengths at 5e8 cycles
#: and a design that runs longer than that is outside them.  Polymers get
#: ``None``: printed-part fatigue turns on layer orientation, void content and
#: temperature far more than on tensile strength, and a Marin-corrected steel
#: rule applied to PLA would be a confident number with nothing behind it.
MATERIALS: dict[str, Material] = {
    m.name: m
    for m in [
        Material(name="PLA", E_GPa=3.5, nu=0.36, sigma_contact_MPa=25, density_g_cm3=1.24,
                 sigma_yield_MPa=50, pv_limit_MPa_m_s=0.03, max_service_temp_C=55,
                 sigma_ultimate_MPa=50),
        Material(name="PETG", E_GPa=2.1, nu=0.40, sigma_contact_MPa=30, density_g_cm3=1.27,
                 sigma_yield_MPa=50, pv_limit_MPa_m_s=0.04, max_service_temp_C=70,
                 sigma_ultimate_MPa=50),
        Material(name="ABS", E_GPa=2.2, nu=0.35, sigma_contact_MPa=24, density_g_cm3=1.04,
                 sigma_yield_MPa=40, pv_limit_MPa_m_s=0.05, max_service_temp_C=85,
                 sigma_ultimate_MPa=40),
        Material(name="PA12 (SLS)", E_GPa=1.7, nu=0.40, sigma_contact_MPa=35, density_g_cm3=1.01,
                 sigma_yield_MPa=48, pv_limit_MPa_m_s=0.12, max_service_temp_C=150,
                 sigma_ultimate_MPa=48),
        Material(name="Tough Resin (SLA)", E_GPa=2.7, nu=0.40, sigma_contact_MPa=30, density_g_cm3=1.18,
                 sigma_yield_MPa=45, pv_limit_MPa_m_s=0.04, max_service_temp_C=60,
                 sigma_ultimate_MPa=45),
        Material(name="POM (Delrin)", E_GPa=3.0, nu=0.38, sigma_contact_MPa=40, density_g_cm3=1.41,
                 sigma_yield_MPa=70, pv_limit_MPa_m_s=0.14, max_service_temp_C=90,
                 sigma_ultimate_MPa=70),
        Material(name="Aluminium 7075-T6", E_GPa=71.7, nu=0.33, sigma_contact_MPa=350, density_g_cm3=2.81,
                 sigma_yield_MPa=500, pv_limit_MPa_m_s=0.35, max_service_temp_C=150,
                 sigma_ultimate_MPa=572, fatigue_strength_MPa=159),
        Material(name="Bronze CuSn12", E_GPa=100.0, nu=0.34, sigma_contact_MPa=200, density_g_cm3=8.8,
                 sigma_yield_MPa=150, pv_limit_MPa_m_s=1.75, max_service_temp_C=200,
                 sigma_ultimate_MPa=280, fatigue_strength_MPa=90),
        Material(name="Steel 1045", E_GPa=205.0, nu=0.29, sigma_contact_MPa=800, density_g_cm3=7.85,
                 sigma_yield_MPa=450, pv_limit_MPa_m_s=1.0, max_service_temp_C=250,
                 sigma_ultimate_MPa=625, fatigue_strength_MPa=310),
        Material(name="Steel 4140 (hardened)", E_GPa=210.0, nu=0.29, sigma_contact_MPa=1400, density_g_cm3=7.85,
                 sigma_yield_MPa=900, pv_limit_MPa_m_s=1.4, max_service_temp_C=300,
                 sigma_ultimate_MPa=1100, fatigue_strength_MPa=550),
        Material(name="Bearing steel 100Cr6", E_GPa=210.0, nu=0.30, sigma_contact_MPa=1800, density_g_cm3=7.81,
                 sigma_yield_MPa=1600, pv_limit_MPa_m_s=1.8, max_service_temp_C=120,
                 sigma_ultimate_MPa=2000, fatigue_strength_MPa=700),
    ]
}


class Lubricant(BaseModel):
    """What is between the two surfaces, and what it does under pressure.

    Two properties decide whether a film forms at all.  **Viscosity** is the
    obvious one and it is quoted the way oils are actually sold - kinematic, in
    centistokes, at 40 and 100 C, which is what an ISO VG grade *is*.  Two points
    are enough to fit the temperature curve, and a lubricant's whole behaviour
    here turns on temperature: the drive heats itself, the oil thins, the film
    collapses, and the friction that caused it goes up again.

    The second is **pressure-viscosity**, ``alpha``.  At a loaded contact the oil
    sees a gigapascal or so and stiffens by orders of magnitude, and that - not
    its viscosity in the can - is what holds the surfaces apart.  An oil with a
    low alpha builds a thinner film at the same grade, which is why the synthetic
    entries here are not simply better than the mineral ones.

    ``boundary_mu`` is what the contact costs when the film has failed and the
    asperities are touching: the additive package, not the base oil, and the
    reason an EP grease is worth having in a drive that will spend its life in
    the mixed regime.
    """

    name: str
    viscosity_40C_cSt: float = Field(gt=0, description="kinematic; ISO VG is this number")
    viscosity_100C_cSt: float = Field(gt=0)
    density_g_cm3: float = Field(gt=0, description="to get dynamic viscosity from it")
    alpha_1_per_GPa: float = Field(
        gt=0, description="pressure-viscosity coefficient; what actually builds film"
    )
    boundary_mu: float = Field(
        gt=0, lt=1.0, description="friction once the film has gone and asperities touch"
    )
    max_temp_C: float = Field(gt=0, description="above this it degrades rather than thins")

    @property
    def forms_a_film(self) -> bool:
        """Whether asking for a film thickness means anything for this entry.

        ``False`` for dry, which is not a thin lubricant but the absence of one -
        there is no viscosity to put in the formula and a number would be an
        invention - and for a bonded dry film, which works by shearing at a low
        stress rather than by separating the surfaces.  Both go straight to their
        boundary coefficient, which for the dry entry is the design's own.
        """
        return self.name not in _NO_FILM


#: The lubricant field's value when there is nothing in there.  Dry is the
#: default and the honest one for most printed drives - people build them, run
#: them dry, and wear them out, which is what the PV checks are about.
DRY = "None (dry)"

#: Lubricants by what you would actually put in.  The greases are quoted by
#: their base oil, because that is what forms the film - the thickener holds it
#: in place and does not carry load.  Alphas are typical values for the chemistry
#: at room temperature: mineral oils run high, PAO synthetics lower, and that
#: difference is why a synthetic of the same grade builds a thinner film.
#: ``PTFE dry film`` is not a lubricant in this model's sense at all - it forms
#: no hydrodynamic film ever - but it has a low boundary coefficient, which is
#: the whole reason to use one, so it is here with the viscosity of the base it
#: is carried in and a flag that stops the film formula being applied to it.
LUBRICANTS: dict[str, Lubricant] = {
    lube.name: lube
    for lube in [
        Lubricant(name=DRY, viscosity_40C_cSt=1.0, viscosity_100C_cSt=1.0,
                  density_g_cm3=1.0, alpha_1_per_GPa=1.0, boundary_mu=0.12,
                  max_temp_C=1000.0),
        Lubricant(name="Grease NLGI 2 (lithium/mineral)", viscosity_40C_cSt=110.0,
                  viscosity_100C_cSt=11.0, density_g_cm3=0.89, alpha_1_per_GPa=22.0,
                  boundary_mu=0.11, max_temp_C=120.0),
        Lubricant(name="Grease NLGI 2 (PAO synthetic)", viscosity_40C_cSt=100.0,
                  viscosity_100C_cSt=14.0, density_g_cm3=0.85, alpha_1_per_GPa=15.0,
                  boundary_mu=0.10, max_temp_C=150.0),
        Lubricant(name="Grease NLGI 2 (EP, moly)", viscosity_40C_cSt=180.0,
                  viscosity_100C_cSt=15.0, density_g_cm3=0.90, alpha_1_per_GPa=23.0,
                  boundary_mu=0.06, max_temp_C=130.0),
        Lubricant(name="Oil ISO VG 32", viscosity_40C_cSt=32.0, viscosity_100C_cSt=5.4,
                  density_g_cm3=0.86, alpha_1_per_GPa=20.0, boundary_mu=0.11,
                  max_temp_C=100.0),
        Lubricant(name="Oil ISO VG 100", viscosity_40C_cSt=100.0, viscosity_100C_cSt=11.0,
                  density_g_cm3=0.88, alpha_1_per_GPa=22.0, boundary_mu=0.11,
                  max_temp_C=100.0),
        Lubricant(name="Oil ISO VG 220 (gear)", viscosity_40C_cSt=220.0,
                  viscosity_100C_cSt=19.0, density_g_cm3=0.89, alpha_1_per_GPa=24.0,
                  boundary_mu=0.08, max_temp_C=110.0),
        Lubricant(name="PTFE dry film", viscosity_40C_cSt=1.0, viscosity_100C_cSt=1.0,
                  density_g_cm3=2.2, alpha_1_per_GPa=1.0, boundary_mu=0.05,
                  max_temp_C=250.0),
    ]
}

#: Surfaces that never build a film whatever is put on them, by name.  Kept apart
#: from :data:`DRY` because "there is no oil" and "there is a solid film and no
#: oil" are different answers to the same contact.
_NO_FILM = {DRY, "PTFE dry film"}


#: What a bearing field says when the sizing study is to choose the part.
#: A sentinel rather than an empty string or ``None``: it is a value the user
#: picks from a list beside forty real designations, and "auto" is what that
#: entry has to be called for the list to make sense.
AUTOMATIC = "auto"

#: How far the input shaft stands out past the disc stack at each end, mm.
#: A modelling choice rather than a design input, but four modules were each
#: carrying their own copy of it with a comment pointing at a fifth, and the
#: bearings that sit on that overhang made the drift a fit question rather than
#: a mass one.
SHAFT_OVERHANG = 12.0

#: Axial gap between the output carrier's inner face and the first disc, mm.
#: Small and deliberate: a carrier face flush with the disc would put two
#: surfaces at the same height, which the software renderer cannot arbitrate.
CARRIER_DROP = 1.0


class OffsetMode(str, Enum):
    """How manufacturing clearance is introduced into the theoretical profile.

    Both levers have to *shrink* the disc to open a gap.  The disc reaches
    ``R - Rr + E`` from its own centre, so growing the generating roller and
    shrinking the generating pin circle each pull the profile inward; doing one
    of each is what ``BOTH`` means.  Get a sign wrong and the "clearance" is an
    interference instead.
    """

    EQUIDISTANT = "equidistant"   # grow the roller radius -> uniform normal offset
    PIN_CIRCLE = "pin_circle"     # shrink the pin circle radius -> radial shift
    BOTH = "both"                 # split evenly between the two


class OutputMember(str, Enum):
    """Which member the load is taken from - and so which one is bolted down.

    A cycloidal drive is a three-shaft machine, not a two-shaft one.  The crank
    is always the input, but the *other two* - the ring the pins sit in and the
    carrier the pins through the disc holes sit on - are interchangeable: ground
    either and the remaining one is the output.  Both are built and sold.

    The choice is not a labelling exercise.  It changes the reduction, because
    the two members do not turn at the same rate; it changes the direction,
    because only one of them turns against the crank; and it changes the drive,
    because the motor has to bolt to whichever member is standing still and the
    load to whichever one is not.  See :attr:`GearSpec.ratio` and the rate
    properties beside it for the first two, and the end plates for the third.
    """

    #: Ring bolted down, output off the carrier: the reduction is the lobe
    #: count and the output turns backwards.  The classic industrial layout.
    CARRIER = "output pin carrier"
    #: Carrier bolted down, output off the ring housing: the reduction is the
    #: *pin* count, one more, and the output turns with the input.  What most
    #: printed micro drives do, because the turning part is then the outside of
    #: the gearbox and a pulley or a wheel goes straight on it.
    RING = "ring housing"


class Process(str, Enum):
    FDM = "FDM 3D print"
    SLA = "SLA/resin print"
    SLS = "SLS print"
    CNC = "CNC machined"
    EDM = "Wire EDM / ground"


#: (profile clearance per side mm, hole clearance on diameter mm) design guides.
PROCESS_CLEARANCE: dict[Process, tuple[float, float]] = {
    Process.FDM: (0.22, 0.30),
    Process.SLA: (0.09, 0.12),
    Process.SLS: (0.15, 0.20),
    Process.CNC: (0.03, 0.03),
    Process.EDM: (0.012, 0.015),
}

#: True-position tolerance a process typically holds on a bolt circle of this
#: size, as the diameter of the tolerance zone - the way a drawing states it.
#:
#: Deliberately *not* applied by :meth:`GearSpec.apply_process_defaults`, unlike
#: the clearances.  A clearance is a dimension you choose and the model has
#: always had one; a position tolerance is a claim about what your machine
#: actually holds, and defaulting it to a guess would quietly derate every
#: design in the app on the strength of that guess.  It is a suggestion, offered
#: by the ``PIN_POSITION`` check, and it stays a suggestion until you enter it.
PROCESS_POSITION_TOLERANCE: dict[Process, float] = {
    Process.FDM: 0.30,
    Process.SLA: 0.12,
    Process.SLS: 0.25,
    Process.CNC: 0.05,
    Process.EDM: 0.02,
}

#: RMS surface roughness ``Rq`` in micrometres, by process.  Typical as-made
#: values for the *working* faces, and the number that decides whether a film
#: separates the surfaces or merely floats between the peaks: what matters is
#: film thickness measured against roughness, so a rough surface needs a thick
#: film to reach the same regime.
#:
#: This is where a printed drive loses.  A layered flank is not a slightly worse
#: ground one - it is two orders of magnitude rougher, and no lubricant sold will
#: build a film that clears it.  That is not a fixable defect, it is what the
#: process is, and the model says so rather than reporting a regime it cannot
#: reach.  Unlike the position tolerance this *is* defaulted from the process,
#: because a surface finish is not a claim about your machine: every process here
#: has one whether it is stated or not, and the alternative to a typical figure
#: is no lubrication answer at all.
PROCESS_ROUGHNESS_UM: dict[Process, float] = {
    Process.FDM: 15.0,
    Process.SLA: 3.0,
    Process.SLS: 12.0,
    Process.CNC: 1.6,
    Process.EDM: 0.4,
}


class GearSpec(BaseModel):
    """A complete, self-consistent cycloidal drive definition."""

    model_config = {"validate_assignment": True}

    # ---- core cycloid geometry ------------------------------------------------
    pin_circle_radius: float = Field(50.0, gt=0, description="R - ring pin bolt circle radius")
    pin_radius: float = Field(4.0, gt=0, description="Rr - ring pin radius")
    eccentricity: float = Field(1.5, gt=0, description="E - crank offset")
    lobes: int = Field(11, ge=3, le=200, description="N - lobes on the disc; ring pins = N+1")

    # ---- disc -----------------------------------------------------------------
    disc_thickness: float = Field(8.0, gt=0)
    disc_count: Literal[1, 2, 3] = 2
    disc_gap: float = Field(1.0, ge=0, description="axial gap between stacked discs")
    center_bore_diameter: float = Field(22.0, gt=0, description="eccentric bearing OD")

    # ---- output mechanism -----------------------------------------------------
    #
    # Which member the load comes off is the first question here, not the last:
    # it decides the reduction and the direction before any of the dimensions
    # below are read, and it decides which end of the drive the motor bolts to.
    output_member: OutputMember = Field(
        OutputMember.CARRIER,
        description="which member turns the load - the output pin carrier with "
                    "the ring housing bolted down, or the ring housing with the "
                    "carrier bolted down",
    )
    output_pin_count: int = Field(6, ge=3, le=24)
    output_pin_diameter: float = Field(6.0, gt=0)
    output_bolt_circle_radius: float = Field(30.0, gt=0)

    # ---- housing / shaft ------------------------------------------------------
    housing_wall: float = Field(6.0, gt=0)
    input_shaft_diameter: float = Field(10.0, gt=0)
    eccentric_cam_diameter: float | None = Field(
        None, description="cam OD; defaults to the bore less a 4 mm bearing wall"
    )
    output_flange_thickness: float = Field(6.0, gt=0)
    end_plate_thickness: float | None = Field(
        None,
        description="the two plates that close the housing and hold the shaft "
                    "supports and the output bearing; defaults to the housing wall",
    )
    output_hub_diameter: float | None = Field(
        None,
        description="boss on the output carrier: the main output bearing sits on "
                    "it and a shaft support sits in it; defaults to the shaft plus "
                    "20 mm, which is a bearing wall each side of both",
    )

    # ---- manufacturing --------------------------------------------------------
    process: Process = Process.FDM
    offset_mode: OffsetMode = OffsetMode.EQUIDISTANT
    profile_clearance: float = Field(0.22, ge=0, description="per-side clearance on the profile")
    hole_clearance: float = Field(0.30, ge=0, description="added to hole diameters")
    position_tolerance: float = Field(
        0.0, ge=0,
        description="true-position tolerance zone diameter on the pin holes, "
                    "ring and carrier alike; 0 models a perfectly placed ring",
    )
    dxf_chord_tolerance: float = Field(0.005, gt=0)
    stl_linear_tolerance: float = Field(0.05, gt=0)

    # ---- materials ------------------------------------------------------------
    disc_material: str = "PLA"
    pin_material: str = "Steel 1045"
    housing_material: str = Field(
        "PLA", description="ring, housing and output carrier - printed on most builds"
    )
    shaft_material: str = Field("Steel 1045", description="input/eccentric shaft")
    friction_coefficient: float = Field(
        0.12, gt=0, lt=1.0,
        description="dry sliding coefficient; used as-is when there is no "
                    "lubricant, and as the boundary value a film is compared "
                    "against when there is",
    )
    lubricant: str = Field(
        DRY,
        description="what is between the sliding surfaces; dry is the default, "
                    "so a design that says nothing about lubrication gets the "
                    "answer it always got",
    )
    surface_roughness_um: float | None = Field(
        None, gt=0,
        description="RMS roughness Rq of the sliding faces; defaults to a typical "
                    "figure for the process, because every process has one",
    )
    ring_pins_integral: bool = Field(
        False,
        description="ring pins formed with the housing instead of fitted as "
                    "separate dowels - the printed-drive case",
    )
    ring_pins_are_rollers: bool = Field(
        False, description="ring pins free to rotate (needle rollers) instead of fixed dowels"
    )
    output_pins_are_rollers: bool = Field(
        False, description="output pins carry rotating bushings/rollers"
    )

    # ---- which bearings this drive carries ------------------------------------
    #
    # Three of the five load paths can legitimately be built without a bearing of
    # their own, and plenty of drives are.  These are design decisions and not
    # display options: switching one off changes the geometry, the losses, the
    # bill of materials and what the drive asks of whatever it is bolted to.
    cam_bearing_fitted: bool = Field(
        True,
        description="needle bearing between the cam and the disc bore; off means "
                    "the bore runs directly on the cam, which is a plain journal "
                    "at nearly full input speed",
    )
    shaft_bearings_fitted: bool = Field(
        True,
        description="the drive carries its own input shaft; off means it hangs on "
                    "the driving motor's bearings, which then take the crank "
                    "reaction",
    )
    output_bearing_fitted: bool = Field(
        True,
        description="the drive carries its own output flange; off means the driven "
                    "machine locates it",
    )

    # ---- which bearing goes in each seat --------------------------------------
    #
    # ``AUTOMATIC`` leaves it to the sizing study, which takes the smallest
    # catalogue part that fits the seat and lasts the required life.  Name one
    # instead when the seat is not the only thing deciding: a bearing you already
    # have, one your supplier stocks, or simply a bigger one than the smallest
    # that will do.  A named part is *checked* against its seat rather than
    # quietly replaced - being told a bearing does not fit is the point of
    # asking for it by name.
    #
    # Deliberately plain strings with no validator.  A designation this build
    # does not know should cost a warning on one line of the schedule, not a
    # design file that will not load - which is what a validator would make of
    # opening tomorrow's saved design in today's application.
    cam_bearing: str = Field(AUTOMATIC, description="eccentric cam bearing")
    shaft_bearing: str = Field(AUTOMATIC, description="input shaft supports")
    output_bearing: str = Field(AUTOMATIC, description="main output bearing")
    ring_pin_roller: str = Field(AUTOMATIC, description="ring pin needle rollers")
    output_pin_roller: str = Field(AUTOMATIC, description="output pin rollers")

    # ---- how it bolts to the world --------------------------------------------
    #
    # Both ends, because a gearbox that cannot be attached to anything at either
    # end is a model of a gearbox.  The input face is a motor frame off the
    # table; the output face is whatever the driven machine wants, so it is
    # stated as a pattern rather than chosen from a list.
    motor_frame: str = Field(
        NO_MOTOR,
        description="motor bolted to the input end plate; 'None' for a plain "
                    "plate driven through a coupling",
    )
    motor_drives_the_shaft: bool = Field(
        True,
        description="the motor's own shaft is the input shaft, so the cam is "
                    "bored to it; off means a separate shaft and a coupling",
    )
    # The output end of this topology is a boss on the axis, not a face with a
    # bolt circle on it: what goes on there is a coupling, a pulley or a clamp
    # hub.  So what it needs is somewhere to grip, which it did not have - the
    # boss came out flush with the plate.
    output_boss_protrusion: float = Field(
        8.0, ge=0,
        description="how far the output boss stands past the end plate, for a "
                    "coupling to grip; 0 leaves it flush and ungrippable",
    )
    housing_bolt_count: int = Field(
        6, ge=0, le=24,
        description="tie bolts through both end plates into the barrel; 0 means "
                    "the plates are held on by something this app is not drawing",
    )
    housing_bolt_diameter: float = Field(4.5, gt=0)
    # A ring-output drive turns its housing, and a barrel has nowhere to grip:
    # the boss that is the whole output interface of the carrier-output layout
    # belongs to the *grounded* member here, so the load needs a face of its
    # own.  Only cut when the ring is the output, and half a pitch off the tie
    # bolts so the two patterns in that one plate miss each other.
    output_bolt_count: int = Field(
        6, ge=0, le=24,
        description="bolts a driven machine attaches to on the turning housing's "
                    "end plate; ring output only, and 0 draws none",
    )
    output_bolt_diameter: float = Field(4.5, gt=0)

    bearing_min_life_hours: float = Field(
        5000.0, gt=0,
        description="L10 life a bearing has to reach before the sizing study will "
                    "take it; also what the short-life warning is measured against",
    )

    # ---- duty -----------------------------------------------------------------
    input_rpm: float = Field(1000.0, gt=0)
    output_torque_Nm: float = Field(5.0, gt=0)
    ambient_temp_C: float = Field(20.0, gt=-273.0, description="air around the housing")

    # ---- what turns it --------------------------------------------------------
    #
    # Eight numbers off a datasheet, flat rather than nested, because the panel
    # writes spec fields straight and a dotted path would be a second way to
    # address one.  They are assembled into a :class:`MotorCurve` by the
    # property below and read from there by everything else, so the curve has no
    # state of its own to fall out of step.
    #
    # Three of them are shared between the two kinds and that sharing is
    # physical rather than a squeeze: both motors run off the same bus, both
    # datasheets print a winding resistance, and both have a current they will
    # hold all day - the driver setting for a stepper, the continuous rating for
    # a DC motor.  What is not shared is what the current *means*, which is why
    # a stepper's curve is already its continuous curve and a DC motor's is not.
    motor_kind: MotorKind = Field(
        MotorKind.NONE,
        description="which torque-speed curve the input follows; 'none' asks "
                    "nothing of the motor, which is what the app always did",
    )
    motor_supply_V: float = Field(24.0, gt=0, description="bus volts")
    motor_resistance_ohm: float = Field(
        1.5, gt=0,
        description="per phase on a stepper, terminal to terminal on a DC motor",
    )
    motor_rated_current_A: float = Field(
        1.5, gt=0,
        description="the driver setting on a stepper, the continuous rating on "
                    "a DC motor",
    )
    motor_holding_torque_Nm: float = Field(
        0.45, gt=0, description="stepper: both phases at rated current")
    motor_inductance_mH: float = Field(3.0, gt=0, description="stepper: per phase")
    motor_steps_per_rev: int = Field(
        200, ge=4, le=10000,
        description="stepper: full steps per revolution; 200 is 1.8 degrees",
    )
    motor_kv_rpm_per_V: float = Field(
        100.0, gt=0, description="DC: no-load speed per volt")

    # ---------------------------------------------------------------- derived --
    @computed_field  # type: ignore[prop-decorator]
    @property
    def pin_count(self) -> int:
        """Ring pins.  One more than the lobe count for a single-tooth-difference drive."""
        return self.lobes + 1

    # ---- how fast each body turns ---------------------------------------------
    #
    # All of the geometry in this app is modelled in the frame the ring housing
    # sits still in, because that is the frame the profile is generated in and
    # the frame the meshing was verified in.  Grounding the *carrier* instead
    # does not change a single relative motion in the drive - it adds one rigid
    # rotation to every part at once, and that is exactly what
    # :attr:`frame_spin` is.
    #
    # Everything below is per radian of crank angle, so the frame term appears
    # once and cancels wherever two bodies are compared with each other.  That
    # cancellation is the point: a relative speed is a fact about the mechanism
    # and must not depend on which member somebody bolted down, while an
    # absolute one must.
    @property
    def frame_spin(self) -> float:
        """Rigid rotation added to every part, per radian of crank angle.

        Zero with the ring grounded, which is how the model is built.  With the
        carrier grounded it is ``-1/N``, precisely cancelling the carrier's own
        rotation and setting the whole drive turning the other way underneath.
        """
        return 0.0 if self.output_member is OutputMember.CARRIER else -1.0 / self.lobes

    @property
    def shaft_spin(self) -> float:
        """The crank, per radian of crank angle.

        Negative: the disc centre runs to ``(E cos phi, -E sin phi)``, which is
        a clockwise walk, so the cam carrying it turns by ``-phi``.
        """
        return -1.0 + self.frame_spin

    @property
    def disc_spin(self) -> float:
        """The disc, per radian of crank angle.  ``+phi/N`` in the built frame."""
        return 1.0 / self.lobes + self.frame_spin

    @property
    def carrier_spin(self) -> float:
        """The output carrier: the disc's own rotation, and exactly it.

        The pins in the disc's holes are a coupling, not a gear - they pass the
        disc's rotation on at one to one and take out the orbit.  So this is
        :attr:`disc_spin` rather than a second law that would have to be kept
        in step with it.
        """
        return self.disc_spin

    @property
    def ring_spin(self) -> float:
        """The ring housing and the two plates bolted to it."""
        return self.frame_spin

    @property
    def output_spin(self) -> float:
        """Whichever of the two the load is taken from."""
        return (self.carrier_spin if self.output_member is OutputMember.CARRIER
                else self.ring_spin)

    @property
    def crank_rate(self) -> float:
        """Crank angle per unit *input* rotation.

        One with the ring grounded, where the crank is the input and nothing
        else moves under it.  With the carrier grounded the crank is already
        turning at ``(N+1)/N`` of the crank angle, so a given input speed buys
        proportionally less of it - and every sliding speed in the drive is
        stated per unit crank angle, so they all pass through here.
        """
        return 1.0 / abs(self.shaft_spin)

    @property
    def crank_relative_rate(self) -> float:
        """Disc against crank, per unit input speed.

        Two contacts turn out to be the same number and it is worth saying why.
        The cam bearing separates the disc from the crank, so it turns at their
        difference.  The output pins rub because the disc's centre walks a
        circle of radius E *in the carrier's frame*, and the carrier turns with
        the disc - so that walk is at the difference between the disc and the
        crank as well.  One rate, two contacts.

        It is ``1 + 1/N`` per crank radian and not ``1 - 1/N``: the disc turns
        the *opposite* way from the crank, so the two rates add.  Getting that
        backwards understates the fastest contact in the machine, and it
        understates it worst on the low ratios where it matters most.
        """
        return abs(self.disc_spin - self.shaft_spin) * self.crank_rate

    @property
    def disc_speed_ratio(self) -> float:
        """How fast the disc turns in the ground frame, per unit input speed.

        ``1/N`` with the ring grounded.  Zero with the carrier grounded, where
        the disc does not rotate at all - it only orbits - which is why a
        ring-output drive reflects less of the disc's inertia back to the motor.
        """
        return abs(self.disc_spin) * self.crank_rate

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ratio(self) -> int:
        """Reduction, from whichever member the output is taken off.

        With the **ring** grounded it is the lobe count, verified by meshing
        simulation: i == lobe count == pin_count - 1.

        With the **carrier** grounded it is the *pin* count, one more.  Not a
        coincidence and not an approximation: the two members are one tooth
        apart, so grounding the other one moves the reduction by exactly one.
        The extra tooth of reduction is free - the same parts, bolted down at
        the other end.
        """
        return self.lobes if self.output_member is OutputMember.CARRIER else self.pin_count

    @computed_field  # type: ignore[prop-decorator]
    @property
    def output_reverses(self) -> bool:
        """Whether the output turns against the input.

        It does off the carrier and does not off the ring, which is the other
        half of what grounding the other member buys you.  Derived from the two
        spins rather than stated, so it cannot disagree with the picture the 3D
        view draws from the same numbers.
        """
        return (self.output_spin < 0.0) != (self.shaft_spin < 0.0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def K1(self) -> float:
        """Trochoid shortening coefficient.  Must stay below 1."""
        return self.eccentricity * self.pin_count / self.pin_circle_radius

    @computed_field  # type: ignore[prop-decorator]
    @property
    def output_hole_diameter(self) -> float:
        """Verified exactly: the disc translates on a circle of radius E in the
        output carrier frame, so the hole must be the pin plus 2E."""
        return self.output_pin_diameter + 2 * self.eccentricity + self.hole_clearance

    @computed_field  # type: ignore[prop-decorator]
    @property
    def disc_outer_radius(self) -> float:
        return self.pin_circle_radius - self.pin_radius + self.eccentricity

    @computed_field  # type: ignore[prop-decorator]
    @property
    def housing_outer_radius(self) -> float:
        return self.pin_circle_radius + self.pin_radius + self.housing_wall

    @computed_field  # type: ignore[prop-decorator]
    @property
    def stack_height(self) -> float:
        n = self.disc_count
        return n * self.disc_thickness + (n - 1) * self.disc_gap

    @property
    def barrel_bottom(self) -> float:
        """Where the ring housing starts, with the first disc face at zero.

        Negative, and it has to be.  The output carrier hangs below the disc
        stack - a drop, then its own thickness - and the output end plate bolts
        to the barrel underneath *that*.  A barrel that stops at the discs
        leaves the carrier standing in the open with a gap between the housing
        and the plate it is supposed to be bolted to, which is a gearbox with a
        slot cut round it.

        The barrel was sized to the disc stack when the disc stack was all there
        was to enclose.  The end plates gave it something to reach.
        """
        return -(CARRIER_DROP + self.output_flange_thickness)

    @property
    def barrel_top(self) -> float:
        """Where the ring housing stops.

        The top of the disc stack, unless there is a frame - and then the same
        allowance the carrier gets at the other end, because the end cap is the
        carrier's mirror image and has to fit inside the barrel exactly as the
        carrier does.  A barrel that stopped at the discs would leave the cap
        standing proud of the housing it is meant to be inside, which is the
        same fault the carrier had before the barrel was lengthened for it.
        """
        if not self.ground_frame_fitted:
            return self.stack_height
        return self.stack_height + CARRIER_DROP + self.output_flange_thickness

    @property
    def barrel_height(self) -> float:
        """Length of the ring housing: the discs, and whatever is inside it at
        each end."""
        return self.barrel_top - self.barrel_bottom

    @computed_field  # type: ignore[prop-decorator]
    @property
    def output_rpm(self) -> float:
        return self.input_rpm / self.ratio

    # ---- effective (clearance-corrected) cutting geometry ---------------------
    @property
    def effective_R(self) -> float:
        """Pin circle radius the profile is *generated* with.

        Shrinking it moves the whole profile inward, which is what opens the
        radial clearance.  The pins themselves stay at
        :attr:`pin_circle_radius`; only the cutting geometry moves.
        """
        c = self.profile_clearance
        if self.offset_mode is OffsetMode.PIN_CIRCLE:
            return self.pin_circle_radius - c
        if self.offset_mode is OffsetMode.BOTH:
            return self.pin_circle_radius - c / 2
        return self.pin_circle_radius

    @property
    def effective_Rr(self) -> float:
        c = self.profile_clearance
        if self.offset_mode is OffsetMode.EQUIDISTANT:
            return self.pin_radius + c
        if self.offset_mode is OffsetMode.BOTH:
            return self.pin_radius + c / 2
        return self.pin_radius

    @property
    def cam_diameter(self) -> float:
        """Eccentric cam OD.  Leaves room for a 4 mm walled needle bearing by default.

        With no bearing fitted there is no wall to leave: the disc bore runs on
        the cam itself, so the cam is the nominal bore and ``hole_clearance`` -
        which the bore is opened by - becomes the running fit.  Keeping it 8 mm
        under would be a disc flopping about on a shaft.
        """
        if self.eccentric_cam_diameter is not None:
            return self.eccentric_cam_diameter
        if not self.cam_bearing_fitted:
            return max(self.center_bore_diameter, self.input_shaft_diameter + 2.0)
        return max(self.center_bore_diameter - 8.0, self.input_shaft_diameter + 2.0)

    @property
    def plate_thickness(self) -> float:
        """The two end plates that close the housing.

        The housing wall plus a couple of millimetres, because these are bearing
        housings and not covers: whatever goes in one has to fit *inside* it, and
        the thin-section balls that suit this size run 5 to 7 mm wide.  A plate
        at the bare wall could not hold the bearing the output seat asks for.
        """
        if self.end_plate_thickness is not None:
            return self.end_plate_thickness
        return self.housing_wall + 2.0

    @property
    def shaft_overhang(self) -> float:
        """How far the input shaft stands past the disc stack at each end.

        It has to reach through the carrier's boss, because a shaft support sits
        in there and a bearing on a shaft that stops short of it is not a
        bearing.  The fixed 12 mm this used to be predates the boss existing.
        """
        return max(SHAFT_OVERHANG,
                   CARRIER_DROP + self.output_flange_thickness
                   + self.plate_thickness + 3.0)

    @property
    def hub_diameter(self) -> float:
        """Output carrier boss: what the main output bearing sits *on*.

        Twenty over the shaft by default, which is a bearing wall each side of
        both bearings it separates - a support inside it on the shaft, the output
        bearing outside it in the end plate.  On the 10 mm default shaft that is
        30 mm, and 30 mm is a catalogue bore, so the two land on each other
        exactly rather than nearly.
        """
        if self.output_hub_diameter is not None:
            return self.output_hub_diameter
        return max(self.input_shaft_diameter + 20.0,
                   self.input_shaft_diameter + 2.0)

    @property
    def hub_bore(self) -> float:
        """Inside of the boss: the seat for the outboard shaft support.

        The hub less a 4 mm wall each side, which is the same allowance the cam
        makes for the bearing inside the disc bore.
        """
        return max(self.hub_diameter - 8.0, self.input_shaft_diameter + 1.0)

    @property
    def boss_bottom(self) -> float:
        """The far end of the carrier's boss.

        The output end plate's outer face, then however far the boss was asked
        to stand past it.  What is *at* that end differs: a coupling grips it
        when the carrier is the output, and the base the drive is bolted down
        by is on it when the carrier is the ground.
        """
        return (self.barrel_bottom - self.plate_thickness
                - self.output_boss_protrusion)

    @property
    def ground_frame_fitted(self) -> bool:
        """Whether the drive carries a frame the housing turns *inside*.

        Only when the ring is the output member, and then it is not an option
        but the shape of the machine.  A motor cannot bolt to a plate that
        turns, and with the ring as the output every plate on the housing does -
        so the grounded member has to become something you can bolt a motor to
        and hang a gearbox off, at both ends.

        What that frame is: the carrier plate, the output pins standing on it,
        an **end cap** the far end of those pins lands in, a boss on each of the
        two plates, and a base on the outside of the lower one.  It is one rigid
        body and the pins are what holds it together - which is the arrangement
        every printed micro drive of this kind uses, and it buys two things that
        are not cosmetic.  The housing is carried at *both* ends instead of
        hanging off one bearing, so it can take a moment.  And the output pins
        are beams rather than cantilevers, which is a factor of four off their
        bending stress.
        """
        return self.output_member is OutputMember.RING

    @property
    def end_cap_bottom(self) -> float:
        """Inner face of the end cap: a drop above the last disc.

        The same drop the carrier keeps below the first one, and for the same
        reason - two surfaces at one height is a fight the renderer cannot win -
        so the two plates are mirror images about the stack.
        """
        return self.stack_height + CARRIER_DROP

    @property
    def end_cap_top(self) -> float:
        """Outer face of the end cap, which is where the barrel ends."""
        return self.end_cap_bottom + self.output_flange_thickness

    @property
    def cap_boss_top(self) -> float:
        """The far end of the end cap's boss.

        Flush with the input end plate's outer face.  It does not stand proud
        the way the carrier's does: nothing grips this one, it is inside the
        frame, and its whole job is to hold the output bearing on its outside
        and the shaft support in its bore.
        """
        return self.barrel_top + self.plate_thickness

    @property
    def base_plate_bottom(self) -> float:
        """Outer face of the base: the face the motor bolts to."""
        return self.boss_bottom - self.plate_thickness

    @property
    def output_pins_are_supported_at_both_ends(self) -> bool:
        """Whether an output pin is a beam or a cantilever.

        A beam once there is an end cap for the far end of it to land in, which
        is the single biggest thing the frame buys: a pin loaded at mid-span
        carries ``F*L/4`` rather than the ``F*L`` of a cantilever off one plate.
        Everything that bends a pin reads this rather than assuming, because
        the assumption used to be wired in.
        """
        return self.ground_frame_fitted

    @property
    def output_face_bolt_radius(self) -> float:
        """Where a driven machine bolts to the turning housing.

        The tie bolts' own circle, because that is where the metal is: it is
        the one radius on that plate with the barrel wall behind it rather than
        the disc chamber, so a bolt lands in something.  The two patterns share
        a circle and are kept apart by angle instead - see
        :attr:`output_bolt_phase` - and when they cannot be, the
        ``OUTPUT_BOLT_CLASH`` check says so rather than the model quietly
        drawing one hole through another.
        """
        return self.housing_bolt_radius

    @property
    def output_bolt_phase(self) -> float:
        """Half a tie-bolt pitch, so the two circles interleave.

        Zero when there are no tie bolts to miss.  With the usual six of each
        this puts an output hole exactly between every pair of tie bolts, which
        is as far from them as the circle allows.
        """
        import math
        if not self.housing_bolt_count:
            return 0.0
        return math.pi / self.housing_bolt_count

    @property
    def motor_face(self) -> MotorFrame:
        """The face the motor bolts to, as the frame standard defines it.

        Named for the face rather than for the motor, because a motor is two
        facts and this is only the first of them.  The other one is
        :attr:`motor_curve`, and an analysis result carries the answer under
        ``motor`` - so leaving this called ``motor`` would have put two
        different objects behind one word on the two most-read classes here.
        """
        return MOTOR_FRAMES[self.motor_frame]

    @property
    def has_motor_face(self) -> bool:
        return self.motor_frame != NO_MOTOR

    @property
    def motor_curve(self) -> MotorCurve:
        """What the motor can deliver, against speed.

        Assembled on every read rather than cached: it is eight attribute reads
        and a dataclass, and a cache here would be a copy of the design that can
        disagree with the design.

        Independent of :attr:`has_motor_face` on purpose.  A face is what the
        drive bolts to and a curve is what turns the crank, and the two are
        genuinely separable - a motor driving through a coupling from somewhere
        else has a curve and no face, and a plate cut for a NEMA 17 says nothing
        about which NEMA 17 goes on it.
        """
        return curve_from(self)

    @property
    def motor_mounts_on_carrier(self) -> bool:
        """Whether the motor face is cut into the carrier's base instead of the
        input end plate.  It goes on whichever member does not turn."""
        return self.has_motor_face and self.ground_frame_fitted

    @property
    def grounded_part(self) -> str:
        """The part that is bolted to the world, named as the assembly names it."""
        return ("housing" if self.output_member is OutputMember.CARRIER
                else "output_flange")

    @property
    def output_part(self) -> str:
        """The part the load comes off, named as the assembly names it."""
        return ("output_flange" if self.output_member is OutputMember.CARRIER
                else "housing")

    @property
    def housing_bolt_radius(self) -> float:
        """Where the tie bolts run: through the wall, clear of the pin pockets.

        Halfway between the deepest a pocket cuts and the outside, so a bolt
        misses the pins whose plate it is holding on and still has metal round
        it on both sides.
        """
        return self.housing_outer_radius - self.housing_wall / 2.0

    @property
    def tie_bolt_bottom(self) -> float:
        """Where a tie bolt starts: the outer face of the output end plate."""
        return self.barrel_bottom - self.plate_thickness

    @property
    def tie_bolt_length(self) -> float:
        """Under the head: through one plate, the barrel, and the other plate.

        Off the barrel rather than off the disc stack, which is what the bill
        of materials used to say.  When the barrel was lengthened to reach the
        plates it bolts to, this did not follow it - so the drive was ordering
        bolts seven millimetres short of the thing they had to pass through.
        One property now, read by the bill of materials and by both renderers.
        """
        return self.barrel_height + 2.0 * self.plate_thickness

    @property
    def ring_pin_length(self) -> float:
        """A ring pin: the whole barrel, trapped between the two end plates.

        The same oversight as the tie bolt above, one part along.  A pocket is
        broached down the bore in one pass, so it runs the barrel's whole length
        - and a pin cut to the disc stack instead leaves seven millimetres of
        empty groove under it with nothing at the bottom but the end plate.
        Nothing holds it up there.  It slides down, and what it slides out of is
        the mesh: a third of its engagement gone, and an open pocket left at the
        top for a lobe to drop into.

        Axial location is the whole reason for the length.  Only the disc stack
        loads a pin, so this is not carrying capacity - it is the pin still being
        where the load is after an hour of running.
        """
        return self.barrel_height

    @property
    def output_pin_length(self) -> float:
        """An output pin: the carrier drop it crosses, then the discs it drives.

        It starts on the carrier face, which sits a drop below the first disc, so
        a pin cut to the disc stack alone arrives one drop short of the top of
        it.  On a two-disc drive that is the last disc driven over seven of its
        eight millimetres - and the bearing stress this app reports for that hole
        is computed over all eight.

        With a frame it crosses a second drop at the far end and goes *through*
        the end cap, which is what turns it from a cantilever into a beam and
        what holds the frame together: these are the drive's own tie bolts in
        that configuration, threaded into the carrier and headed on the outside
        of the cap.  The extra few millimetres of pin is the cheapest structure
        in the drive.
        """
        span = self.stack_height + CARRIER_DROP
        if self.ground_frame_fitted:
            span += CARRIER_DROP + self.output_flange_thickness
        return span

    @property
    def input_plate_bore(self) -> float:
        """The hole in the input end plate.

        The shaft support's seat normally.  With a frame it is the *output
        bearing's* seat instead: the end cap's boss comes up through this plate,
        the second main bearing rides on it, and the shaft support moves inside
        that boss - which is exactly what happens at the other end, one plate
        further out.  Two ends of one symmetrical frame.
        """
        return (self.output_bearing_seat_diameter if self.ground_frame_fitted
                else self.hub_bore)

    @property
    def output_bearing_seat_diameter(self) -> float:
        """Bore in the output end plate: what the main output bearing sits *in*.

        A housing wall out from the hub on each side, so the ring between them is
        the space the bearing has.  With the default shaft that is 30 mm on 42,
        and a 6806 is 30 on 42.
        """
        return self.hub_diameter + 2.0 * self.housing_wall

    @property
    def disc_phases(self) -> list[float]:
        """Crank phase of each disc in the stack: 180 deg for two, 120 deg for three."""
        import math
        return [2.0 * math.pi * i / self.disc_count for i in range(self.disc_count)]

    @property
    def disc_hole_phases(self) -> list[float]:
        """How far each disc's output-hole pattern is rotated against its lobes.

        A disc sitting on crank phase ``p`` must rotate by ``p/lobes`` to stay
        meshed with the ring, but every disc is coupled to the *same* output
        carrier and so must share the carrier's rotation.  The only way both hold
        is to pre-rotate the hole pattern by ``-p/lobes`` so it lands back on the
        carrier pins.

        Consequence: in a multi-disc stack the discs are **different parts**,
        unless :attr:`discs_are_identical`.
        """
        return [-p / self.lobes for p in self.disc_phases]

    @property
    def discs_are_identical(self) -> bool:
        """True when the hole pre-rotation happens to be a whole hole pitch.

        That needs ``output_pin_count`` to be a multiple of ``2*lobes``, which is
        usually far too many pins to be practical - so normally this is False.
        """
        import math
        if self.disc_count == 1:
            return True
        pitch = 2.0 * math.pi / self.output_pin_count
        return all(min(abs(ph % pitch), abs(ph % pitch - pitch)) < 1e-9
                   for ph in self.disc_hole_phases)

    @property
    def disc_mat(self) -> Material:
        return MATERIALS[self.disc_material]

    @property
    def pin_mat(self) -> Material:
        return MATERIALS[self.pin_material]

    @property
    def housing_mat(self) -> Material:
        return MATERIALS[self.housing_material]

    @property
    def shaft_mat(self) -> Material:
        return MATERIALS[self.shaft_material]

    @property
    def lube(self) -> Lubricant:
        """The lubricant, falling back to dry rather than raising.

        Same reasoning as the bearing designations: a saved design naming a
        lubricant this build does not know should cost a conservative answer,
        not a file that will not open.
        """
        return LUBRICANTS.get(self.lubricant, LUBRICANTS[DRY])

    @property
    def roughness_um(self) -> float:
        """RMS roughness of one sliding face, stated or typical for the process."""
        if self.surface_roughness_um is not None:
            return self.surface_roughness_um
        return PROCESS_ROUGHNESS_UM[self.process]

    @property
    def envelope_length(self) -> float:
        """Axial length of the assembled gearbox, end plate face to end plate face.

        The plates are part of the gearbox: they close it, they carry the shaft
        supports and the output bearing, and they are what it bolts to the world
        by.  Leaving them out of the envelope understated the length of every
        drive this app has ever sized.

        Stated as the barrel plus its two plates rather than as the same sum
        written out again, because the two have to agree: this was already
        counting the carrier's share of the length while the barrel itself
        stopped at the discs, so the app reported an envelope the geometry did
        not fill.

        A ring-output drive is longer by its base and the standoff the base
        needs - and the barrel itself is longer, because the end cap lives
        inside it.  The boss protrusion is not a face of the gearbox when the
        carrier is the output: it is a shaft end, and nobody counts a shaft
        end in a gearbox's length.  When the carrier is the *ground* that same
        protrusion is structure between two faces of the machine, with the
        plate you bolt it down by on the end of it.
        """
        length = self.barrel_height + 2.0 * self.plate_thickness
        if self.ground_frame_fitted:
            length += self.output_boss_protrusion + self.plate_thickness
        return length

    @property
    def cooling_area_mm2(self) -> float:
        """Outside surface the housing can shed heat through.

        Barrel plus the two end faces.  Whatever the gearbox is bolted to will
        conduct some heat away as well, which this deliberately ignores - it is
        the pessimistic, free-standing case.
        """
        import math
        r = self.housing_outer_radius
        return 2.0 * math.pi * r * self.envelope_length + 2.0 * math.pi * r * r

    # ---------------------------------------------------------------- helpers --
    @property
    def ring_pins_roll(self) -> bool:
        """Whether the ring contact actually rolls.

        Not the same as ``ring_pins_are_rollers``, which is what was *asked
        for*: a pin formed with the housing is not free to turn in it, however
        the two flags were set.  Derived rather than enforced by a validator,
        because a validator would have to fire on every route a spec arrives
        by - construction, assignment, ``model_copy``, a design file, a sweep -
        and ``model_copy`` does not run them at all.  A design that names both
        keeps the roller preference for when the pins stop being integral, and
        every consumer reads this instead.
        """
        return self.ring_pins_are_rollers and not self.ring_pins_integral

    @model_validator(mode="after")
    def _check_materials(self) -> GearSpec:
        for field in ("disc_material", "pin_material", "housing_material",
                      "shaft_material"):
            if getattr(self, field) not in MATERIALS:
                raise ValueError(f"unknown material {getattr(self, field)!r}")
        return self

    def apply_process_defaults(self) -> GearSpec:
        """Reset the two clearances to the design guide for the selected process."""
        prof, hole = PROCESS_CLEARANCE[self.process]
        self.profile_clearance = prof
        self.hole_clearance = hole
        return self


def preset(ratio: int) -> GearSpec:
    """Sensible starting points for prototype gearboxes, ratios 10:1 to 59:1."""
    table = {
        10: {"pin_circle_radius": 45.0, "pin_radius": 4.5, "eccentricity": 2.0, "output_bolt_circle_radius": 27.0, "center_bore_diameter": 22.0},
        15: {"pin_circle_radius": 50.0, "pin_radius": 4.0, "eccentricity": 1.6, "output_bolt_circle_radius": 30.0, "center_bore_diameter": 24.0},
        21: {"pin_circle_radius": 55.0, "pin_radius": 3.8, "eccentricity": 1.4, "output_bolt_circle_radius": 33.0, "center_bore_diameter": 26.0},
        29: {"pin_circle_radius": 60.0, "pin_radius": 3.5, "eccentricity": 1.1, "output_bolt_circle_radius": 36.0, "center_bore_diameter": 28.0},
        39: {"pin_circle_radius": 65.0, "pin_radius": 3.2, "eccentricity": 0.9, "output_bolt_circle_radius": 39.0, "center_bore_diameter": 30.0},
        59: {"pin_circle_radius": 70.0, "pin_radius": 3.0, "eccentricity": 0.7, "output_bolt_circle_radius": 42.0, "center_bore_diameter": 32.0},
    }
    closest = min(table, key=lambda k: abs(k - ratio))
    return GearSpec(lobes=ratio, **table[closest]).apply_process_defaults()
