"""Declarative description of the parameter panel.

Keeping this as data means the window code never grows a widget-per-field block,
and a new spec field shows up in the UI by adding one line here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..analysis.bearings import CATALOGUE
from ..core.spec import (
    AUTOMATIC,
    LUBRICANTS,
    MATERIALS,
    MOTOR_FRAMES,
    OffsetMode,
    Process,
)

Kind = Literal["float", "int", "bool", "choice"]

#: What a bearing seat can be set to: let the study choose, or name a part.
#: Straight off the catalogue, so a bearing added to it appears in the panel
#: without anyone remembering to add it here as well.
_BEARINGS: tuple[str, ...] = (AUTOMATIC, *(b.designation for b in CATALOGUE))


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
              tip="0 = automatic: the bore less a 4 mm bearing wall, or the "
                  "whole bore when no cam bearing is fitted."),
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
              0.01, decimals=3,
              tip="Dry sliding coefficient. Used as-is with no lubricant; with "
                  "one it is what the film is compared against."),
        Field("lubricant", "Lubricant", "choice", choices=tuple(LUBRICANTS),
              tip="What is between the sliding surfaces. Sets the friction "
                  "coefficient from a film thickness rather than a guess - and "
                  "on a rough surface, from its boundary additives."),
        Field("surface_roughness_um", "Surface Rq", "float", 0, 100.0, 0.1,
              decimals=2, suffix=" um", zero_is_auto=True,
              tip="0 = automatic: a typical RMS roughness for the process. This "
                  "is what film thickness is measured against, so it decides "
                  "the lubrication regime more than the lubricant does."),
        Field("ring_pins_are_rollers", "Ring pins are rollers", "bool",
              tip="Needle rollers on the ring pins remove the largest loss."),
    ]),
    ("Mounting", [
        Field("motor_frame", "Motor", "choice", choices=tuple(MOTOR_FRAMES),
              tip="Bolt pattern, register and shaft of the motor on the input "
                  "end plate. 'None' leaves a plain plate."),
        Field("motor_drives_the_shaft", "Motor turns the cam", "bool",
              tip="On, the motor's own shaft is the input shaft. Off, there is "
                  "a separate shaft and a coupling between them."),
        Field("housing_bolt_count", "Tie bolts", "int", 0, 24, 1,
              tip="Through both end plates into the barrel. 0 draws none."),
        Field("housing_bolt_diameter", "Tie bolt", "float", 1, 20, 0.5,
              decimals=2, suffix=" mm"),
        Field("output_boss_protrusion", "Boss stands out", "float", 0, 100, 1,
              decimals=2, suffix=" mm",
              tip="How far the output boss stands past the end plate, for a "
                  "coupling to grip. 0 leaves it flush and ungrippable."),
    ]),
    ("Bearings", [
        Field("cam_bearing_fitted", "Cam bearing", "bool",
              tip="Off means the disc bore runs straight on the cam - a plain "
                  "journal at nearly full input speed, and the cam grows to "
                  "fill the bore."),
        Field("shaft_bearings_fitted", "Input shaft supports", "bool",
              tip="Off means the drive hangs on the driving motor's bearings, "
                  "which then take the crank reaction."),
        Field("output_bearing_fitted", "Main output bearing", "bool",
              tip="Off means the machine being driven locates the output "
                  "flange."),
        Field("cam_bearing", "Cam bearing size", "choice", choices=_BEARINGS,
              tip="'auto' takes the smallest that fits the seat and lasts. Name "
                  "one and it is checked against the seat, not swapped for one "
                  "that fits."),
        Field("shaft_bearing", "Shaft bearing size", "choice", choices=_BEARINGS),
        Field("output_bearing", "Output bearing size", "choice", choices=_BEARINGS),
        Field("ring_pin_roller", "Ring pin roller", "choice", choices=_BEARINGS,
              tip="Only used when the ring pins are rollers."),
        Field("output_pin_roller", "Output pin roller", "choice", choices=_BEARINGS,
              tip="Only used when the output pins carry rollers."),
        Field("bearing_min_life_hours", "Minimum L10 life", "float", 10, 1e6, 1000,
              decimals=0, suffix=" h",
              tip="What a bearing has to reach before the study will take it, "
                  "and what the short-life warning is measured against."),
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
    "PV_LIMIT_CAM": ("cam_bearing_fitted", "input_rpm", "disc_material"),
    # Roughness before lubricant, deliberately: on most builds here the surface
    # is what decides the regime and the grade cannot rescue it.
    "LUBRICATION_REGIME": ("surface_roughness_um", "lubricant", "process",
                           "ring_pins_are_rollers"),
    "MOTOR_SHAFT_MISMATCH": ("motor_frame", "input_shaft_diameter",
                             "motor_drives_the_shaft"),
    "MOTOR_FACE_CLASH": ("motor_frame", "housing_wall", "output_hub_diameter"),
    "MOTOR_RADIAL_LOAD": ("motor_frame", "shaft_bearings_fitted", "output_torque_Nm"),
    "BEARING_DOES_NOT_FIT": ("cam_bearing", "shaft_bearing", "output_bearing",
                             "eccentric_cam_diameter", "center_bore_diameter"),
    "BEARINGS_OMITTED": ("cam_bearing_fitted", "shaft_bearings_fitted",
                         "output_bearing_fitted"),
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


def codes_for_field(name: str) -> tuple[str, ...]:
    """Which checks a parameter moves - :data:`CODE_FIELDS` read backwards.

    The forward map answers "this check is unhappy, what do I change".  Read the
    other way it answers the question somebody editing a field actually has:
    *what am I about to affect*.  Derived rather than declared, because two
    copies of one relation is one copy too many - and this direction is only
    interesting when it stays in step with the direction that is maintained.
    """
    return tuple(code for code, names in CODE_FIELDS.items() if name in names)
