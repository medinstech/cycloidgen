"""Single source of truth for a cycloidal drive design.

Every other module consumes a ``GearSpec``.  All lengths are millimetres,
all angles radians unless a name says otherwise.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator


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
    friction_coefficient: float = Field(0.12, gt=0, lt=1.0)
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

    # ---- duty -----------------------------------------------------------------
    input_rpm: float = Field(1000.0, gt=0)
    output_torque_Nm: float = Field(5.0, gt=0)
    ambient_temp_C: float = Field(20.0, gt=-273.0, description="air around the housing")

    # ---------------------------------------------------------------- derived --
    @computed_field  # type: ignore[prop-decorator]
    @property
    def pin_count(self) -> int:
        """Ring pins.  One more than the lobe count for a single-tooth-difference drive."""
        return self.lobes + 1

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ratio(self) -> int:
        """Reduction with the ring fixed and output taken from the disc pin holes.

        Verified by meshing simulation: i == lobe count == pin_count - 1.
        """
        return self.lobes

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
    def envelope_length(self) -> float:
        """Axial length of the assembled gearbox, flange face to housing face."""
        return self.stack_height + self.output_flange_thickness

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
