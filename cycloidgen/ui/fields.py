"""Declarative description of the parameter panel.

Keeping this as data means the window code never grows a widget-per-field block,
and a new spec field shows up in the UI by adding one line here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..core.spec import MATERIALS, OffsetMode, Process

Kind = Literal["float", "int", "bool", "choice"]


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: Kind
    minimum: float = 0.0
    maximum: float = 1e6
    step: float = 0.1
    decimals: int = 3
    suffix: str = ""
    choices: tuple[str, ...] = ()
    tip: str = ""
    zero_is_auto: bool = False

    @property
    def is_length(self) -> bool:
        """Whether this field is a length, and so follows the unit preference.

        Derived from the suffix rather than declared beside it.  A second
        declaration of the same fact is a second thing to forget: the suffix is
        already the field's statement of what it measures, and a millimetre
        field that did not say ``mm`` would be wrong on its own terms.
        ``tests/test_units.py`` checks the derivation against every field.
        """
        return self.suffix.strip() == "mm"


GROUPS: list[tuple[str, list[Field]]] = [
    ("Cycloid geometry", [
        Field("lobes", "Lobes / ratio", "int", 3, 200, 1, suffix=":1",
              tip="Ring pins are one more than the lobe count; the reduction "
                  "equals the lobe count."),
        Field("pin_circle_radius", "Pin circle R", "float", 5, 500, 0.5,
              decimals=2, suffix=" mm"),
        Field("pin_radius", "Pin radius Rr", "float", 0.2, 100, 0.1, decimals=2,
              suffix=" mm"),
        Field("eccentricity", "Eccentricity E", "float", 0.05, 20, 0.05, decimals=2,
              suffix=" mm"),
    ]),
    ("Disc", [
        Field("disc_thickness", "Thickness", "float", 0.5, 200, 0.5, decimals=2, suffix=" mm"),
        Field("disc_count", "Disc count", "int", 1, 3, 1),
        Field("disc_gap", "Axial gap", "float", 0, 50, 0.25, decimals=2, suffix=" mm"),
        Field("center_bore_diameter", "Central bore", "float", 2, 300, 0.5, decimals=2,
              suffix=" mm"),
    ]),
    ("Output mechanism", [
        Field("output_pin_count", "Pin count", "int", 3, 24, 1),
        Field("output_pin_diameter", "Pin diameter", "float", 1, 60, 0.5, decimals=2,
              suffix=" mm"),
        Field("output_bolt_circle_radius", "Bolt circle", "float", 3, 400, 0.5,
              decimals=2, suffix=" mm"),
        Field("output_pins_are_rollers", "Pins carry rollers", "bool",
              tip="Rolling output pins remove most of the second-biggest loss."),
    ]),
    ("Housing and shaft", [
        Field("housing_wall", "Housing wall", "float", 1, 100, 0.5, decimals=2, suffix=" mm"),
        Field("input_shaft_diameter", "Input shaft", "float", 2, 200, 0.5, decimals=2,
              suffix=" mm"),
        Field("eccentric_cam_diameter", "Eccentric cam OD", "float", 0, 300, 0.5,
              decimals=2, suffix=" mm", zero_is_auto=True,
              tip="0 = automatic: the bore less a 4 mm bearing wall."),
        Field("output_flange_thickness", "Output flange", "float", 1, 100, 0.5,
              decimals=2, suffix=" mm"),
    ]),
    ("Manufacturing", [
        Field("process", "Process", "choice",
              choices=tuple(p.value for p in Process)),
        Field("offset_mode", "Clearance as", "choice",
              choices=tuple(m.value for m in OffsetMode),
              tip="Equidistant grows the roller; pin circle shifts the ring."),
        Field("profile_clearance", "Profile clearance", "float", 0, 2, 0.01,
              decimals=3, suffix=" mm"),
        Field("hole_clearance", "Hole clearance", "float", 0, 2, 0.01,
              decimals=3, suffix=" mm"),
        Field("position_tolerance", "Pin position", "float", 0, 2, 0.01,
              decimals=3, suffix=" mm",
              tip="True-position zone diameter on the pin holes, ring and "
                  "carrier alike. Zero models a perfectly placed ring; enter "
                  "what your shop holds to see what it costs."),
        Field("dxf_chord_tolerance", "DXF tolerance", "float", 0.0005, 0.5,
              0.001, decimals=4, suffix=" mm"),
        Field("stl_linear_tolerance", "STL tolerance", "float", 0.005, 1.0, 0.01,
              decimals=3, suffix=" mm"),
    ]),
    ("Materials", [
        Field("disc_material", "Disc", "choice", choices=tuple(MATERIALS)),
        Field("pin_material", "Pins", "choice", choices=tuple(MATERIALS)),
        Field("housing_material", "Housing", "choice",
              choices=tuple(MATERIALS),
              tip="Also the output flange. Sets the mass and the temperature "
                  "limit of the structure."),
        Field("shaft_material", "Shaft", "choice", choices=tuple(MATERIALS)),
        Field("friction_coefficient", "Friction", "float", 0.01, 0.9,
              0.01, decimals=3),
        Field("ring_pins_are_rollers", "Ring pins are rollers", "bool",
              tip="Needle rollers on the ring pins remove the largest loss."),
    ]),
    ("Duty", [
        Field("input_rpm", "Input speed", "float", 1, 30000, 50, decimals=1,
              suffix=" rpm"),
        Field("output_torque_Nm", "Output torque", "float", 0.01, 10000, 0.5,
              decimals=3, suffix=" Nm"),
        Field("ambient_temp_C", "Ambient", "float", -50, 200, 5,
              decimals=1, suffix=" C",
              tip="Sets the baseline the predicted running temperature is "
                  "added to."),
    ]),
]

#: Which parameters a finding is actually about, so the checks list can point at
#: the thing to change instead of leaving the user to guess.  Codes not listed
#: here simply do not highlight anything.
CODE_FIELDS: dict[str, tuple[str, ...]] = {
    "K1_TOO_HIGH": ("eccentricity", "pin_circle_radius", "lobes"),
    "K1_HIGH": ("eccentricity", "pin_circle_radius"),
    "UNDERCUT": ("pin_radius", "eccentricity"),
    "UNDERCUT_MARGIN": ("pin_radius", "eccentricity"),
    "PIN_RADIUS_SUGGESTION": ("pin_radius",),
    "PROFILE_SELF_INTERSECT": ("pin_radius", "eccentricity", "lobes"),
    "PROFILE_INTERFERENCE": ("profile_clearance", "offset_mode"),
    "CLEARANCE_NOT_DELIVERED": ("profile_clearance", "offset_mode"),
    "PIN_OVERLAP": ("pin_radius", "pin_circle_radius", "lobes"),
    "PIN_SPACING": ("pin_radius", "pin_circle_radius"),
    "HOLE_HITS_BORE": ("output_bolt_circle_radius", "center_bore_diameter",
                       "output_pin_diameter"),
    "THIN_INNER_WEB": ("output_bolt_circle_radius", "center_bore_diameter"),
    "HOLE_BREAKS_RIM": ("output_bolt_circle_radius", "output_pin_diameter"),
    "THIN_OUTER_WEB": ("output_bolt_circle_radius", "output_pin_diameter"),
    "OUTPUT_HOLES_OVERLAP": ("output_pin_count", "output_pin_diameter",
                             "output_bolt_circle_radius"),
    "OUTPUT_HOLE_SPACING": ("output_pin_count", "output_pin_diameter"),
    "ECCENTRIC_TIGHT": ("center_bore_diameter", "input_shaft_diameter"),
    "CLEARANCE_DEFICIT": ("profile_clearance", "process"),
    "HOLE_CLEARANCE_DEFICIT": ("hole_clearance", "process"),
    "DISCS_DIFFER": ("output_pin_count", "disc_count"),
    "SINGLE_DISC_UNBALANCE": ("disc_count", "input_rpm"),
    "UNBALANCE_FORCE": ("disc_count", "input_rpm"),
    "PRESSURE_ANGLE": ("eccentricity", "pin_circle_radius"),
    "HERTZ_STRESS_RING": ("disc_thickness", "pin_radius", "disc_material",
                          "output_torque_Nm"),
    "HERTZ_STRESS_MARGIN": ("disc_thickness", "pin_radius", "disc_material"),
    "HERTZ_STRESS_OUTPUT": ("output_pin_diameter", "output_pin_count",
                            "disc_thickness"),
    "LOW_EFFICIENCY": ("ring_pins_are_rollers", "output_pins_are_rollers",
                       "friction_coefficient"),
    "SHORT_BEARING_LIFE": ("center_bore_diameter", "disc_thickness", "input_rpm"),
    "NO_BEARING_FITS": ("center_bore_diameter", "input_shaft_diameter",
                        "disc_thickness"),
    "TORSIONAL_STIFFNESS": ("disc_thickness", "disc_material"),
    "STRUCTURAL_COMPLIANCE": ("output_pin_diameter", "housing_material",
                              "output_flange_thickness", "housing_wall"),
    "TRANSMISSION_ERROR": ("output_pin_count", "disc_count", "disc_thickness"),
    "LOST_MOTION": ("profile_clearance", "hole_clearance", "process"),
    "LOAD_CONCENTRATION": ("profile_clearance", "offset_mode", "process"),
    "PIN_POSITION": ("position_tolerance", "profile_clearance", "process"),
    "PV_LIMIT_RING": ("ring_pins_are_rollers", "input_rpm", "disc_material"),
    "PV_MARGIN_RING": ("ring_pins_are_rollers", "input_rpm"),
    "PV_LIMIT_OUTPUT": ("output_pins_are_rollers", "output_pin_diameter"),
    "OVERTEMP": ("input_rpm", "ring_pins_are_rollers", "housing_material"),
    "RUNNING_HOT": ("input_rpm", "ring_pins_are_rollers", "housing_wall"),
    "WEB_SHEAR": ("output_bolt_circle_radius", "disc_thickness", "disc_material"),
    "WEB_SHEAR_MARGIN": ("output_bolt_circle_radius", "disc_thickness"),
    # Process is in these because surface finish is the cheapest fatigue move
    # there is, and it is not obvious that a manufacturing choice belongs to a
    # strength check at all until you have seen the factor of three.
    "FATIGUE_LIFE": ("output_pin_diameter", "output_pin_count", "disc_thickness",
                     "pin_material", "process"),
    "FATIGUE_MARGIN": ("output_pin_diameter", "output_pin_count", "process"),
    "FATIGUE_NOT_MODELLED": ("disc_material", "pin_material"),
    "TOOL_RADIUS": ("pin_radius", "process"),
    "MASS": ("disc_thickness", "housing_wall", "housing_material"),
}
