"""Bill of materials: what you actually have to make or buy.

The drawings say what the parts are; this says how many, out of what, how heavy,
and - for the bought items - what to order.  It is generated from the same
analysis as everything else, so the bearing designations here are the ones the
sizing study picked, not a guess made later.

The multi-disc trap shows up here too: when the discs are different parts they
get separate lines with their own hole-pattern offsets, because a BOM that says
"cycloidal disc x2" is an invitation to make the same part twice and jam the
drive.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

from ..analysis import DesignAnalysis
from ..analysis.bearings import pin_diameters

__all__ = ["BomItem", "bom_items", "write_bom_csv"]


@dataclass(frozen=True)
class BomItem:
    """One line of the bill of materials."""

    part: str
    quantity: int
    material: str
    size: str
    mass_each_g: float
    source: str          # "make" or "buy"
    note: str = ""

    @property
    def mass_total_g(self) -> float:
        return self.quantity * self.mass_each_g


def _pin_mass(diameter: float, length: float, density_g_cm3: float) -> float:
    volume_mm3 = math.pi * (diameter / 2.0) ** 2 * length
    return volume_mm3 * 1e-3 * density_g_cm3


def bom_items(a: DesignAnalysis) -> list[BomItem]:
    """Every part in the assembly, made and bought."""
    s, m = a.spec, a.mass
    items: list[BomItem] = []

    # ---- discs --------------------------------------------------------------
    if s.disc_count == 1 or s.discs_are_identical:
        items.append(BomItem(
            part="Cycloidal disc", quantity=s.disc_count, material=s.disc_material,
            size=f"{2 * s.disc_outer_radius:.1f} dia x {s.disc_thickness:g} mm",
            mass_each_g=m.disc_mass_g, source="make",
            note=("all discs identical" if s.disc_count > 1 else "")))
    else:
        for i, phase in enumerate(s.disc_hole_phases, start=1):
            degrees = math.degrees(phase)
            note = ("reference hole pattern - NOT interchangeable with the others"
                    if abs(degrees) < 1e-9 else
                    f"hole pattern rotated {degrees:+.3f} deg - NOT interchangeable")
            items.append(BomItem(
                part=f"Cycloidal disc {i}", quantity=1, material=s.disc_material,
                size=f"{2 * s.disc_outer_radius:.1f} dia x {s.disc_thickness:g} mm",
                mass_each_g=m.disc_mass_g, source="make", note=note))

    # ---- made parts ---------------------------------------------------------
    items.append(BomItem(
        part="Ring housing", quantity=1, material=s.housing_material,
        size=f"{2 * s.housing_outer_radius:.1f} dia x {s.barrel_height:g} mm",
        mass_each_g=m.housing_mass_g, source="make",
        note=f"{s.pin_count} "
             + ("pins formed with it" if s.ring_pins_integral else "pin pockets")
             + f" on a {2 * s.pin_circle_radius:g} mm circle"))

    items.append(BomItem(
        part="Housing end plate", quantity=2, material=s.housing_material,
        size=f"{2 * s.housing_outer_radius:.1f} dia x {s.plate_thickness:g} mm",
        mass_each_g=m.plates_mass_g / 2.0, source="make",
        note=f"input side bored {s.hub_bore:.1f} for the shaft support, output "
             f"side {s.output_bearing_seat_diameter:.1f} for the output bearing "
             f"- they are not interchangeable"))

    items.append(BomItem(
        part="Output flange / carrier", quantity=1, material=s.housing_material,
        size=f"{2 * (s.output_bolt_circle_radius + s.output_pin_diameter):.1f} dia "
             f"x {s.output_flange_thickness:g} mm",
        mass_each_g=m.flange_mass_g, source="make",
        note=f"{s.output_pin_count} pin seats on a "
             f"{2 * s.output_bolt_circle_radius:g} mm circle"))

    items.append(BomItem(
        part="Eccentric input shaft", quantity=1, material=s.shaft_material,
        size=f"{s.input_shaft_diameter:g} mm dia, {s.disc_count} cam(s) "
             f"{s.cam_diameter:g} mm at {s.eccentricity:g} mm offset",
        mass_each_g=m.shaft_mass_g, source="make",
        note="cams phased "
             + ", ".join(f"{math.degrees(p):.0f}" for p in s.disc_phases) + " deg"))

    # ---- bought pins --------------------------------------------------------
    # Both at their own length and their own diameter, neither of which is what
    # this used to quote.  A dowel ordered wrong is not a fit that can be
    # adjusted at assembly, it is the wrong part - and the diameter was the
    # worse of the two: under a roller the pin *is* the roller's bore, so a
    # rollered 15:1 was ordering 14 mm dowels for an 8 mm hole.
    ring_pin_d, output_pin_d = pin_diameters(s)

    # Nothing to order when the pins are the housing.  A line here for a part
    # that arrives already attached to another line is how a build ends up with
    # twenty-two dowels and nowhere to put them.
    if not s.ring_pins_integral:
        ring_pin_mass = _pin_mass(ring_pin_d, s.ring_pin_length,
                                  s.pin_mat.density_g_cm3)
        items.append(BomItem(
            part="Ring pin (dowel)", quantity=s.pin_count,
            material=s.pin_material,
            size=f"{ring_pin_d:g} mm dia x {s.ring_pin_length:g} mm",
            mass_each_g=ring_pin_mass, source="buy",
            note=("carries a roller" if ring_pin_d < 2 * s.pin_radius else
                  "free to rotate" if s.ring_pins_are_rollers else "fixed")
                 + ", captive between the two end plates"))

    output_pin_mass = _pin_mass(output_pin_d, s.output_pin_length,
                                s.pin_mat.density_g_cm3)
    items.append(BomItem(
        part="Output pin (dowel)", quantity=s.output_pin_count,
        material=s.pin_material,
        size=f"{output_pin_d:g} mm dia x {s.output_pin_length:g} mm",
        mass_each_g=output_pin_mass, source="buy",
        note=(f"carries a roller running in {s.output_hole_diameter:.3f} mm holes"
              if output_pin_d < s.output_pin_diameter else
              f"runs in {s.output_hole_diameter:.3f} mm holes")))

    # ---- fasteners ----------------------------------------------------------
    if s.housing_bolt_count:
        items.append(BomItem(
            part="Tie bolt", quantity=s.housing_bolt_count, material=s.pin_material,
            size=f"{s.housing_bolt_diameter:g} mm clearance, about "
                 f"{s.tie_bolt_length:.0f} mm under the head",
            mass_each_g=0.0, source="buy",
            note=f"through both end plates into the barrel, on a "
                 f"{2 * s.housing_bolt_radius:.1f} mm circle"))

    if s.has_motor_face:
        frame = s.motor
        pattern = (f"{frame.bolt_span:g} mm square" if frame.square
                   else f"{frame.bolt_span:g} mm circle")
        items.append(BomItem(
            part="Motor bolt", quantity=frame.bolt_count, material=s.pin_material,
            size=f"{frame.bolt_diameter:g} mm clearance",
            mass_each_g=0.0, source="buy",
            note=f"{frame.name} pattern, {pattern}, into the input end plate"))

    # ---- bearings -----------------------------------------------------------
    for choice in a.bearings:
        if choice.bearing is None or not choice.count:
            continue
        b = choice.bearing
        life = ("-" if choice.life_hours == float("inf")
                else f"L10 {choice.life_hours:,.0f} h")
        items.append(BomItem(
            part=choice.role, quantity=choice.count, material="bearing steel",
            size=f"{b.designation} ({b.bore:g}x{b.outer:g}x{b.width:g})",
            mass_each_g=0.0, source="buy",
            note=f"{choice.seat}; {choice.load_N:.0f} N at "
                 f"{choice.speed_rpm:.0f} rpm, {life}"))

    return items


def write_bom_csv(a: DesignAnalysis, path: str | Path) -> Path:
    """Write the bill of materials as CSV."""
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Part", "Qty", "Material", "Size", "Mass each (g)",
                         "Mass total (g)", "Make/Buy", "Note"])
        for item in bom_items(a):
            writer.writerow([
                item.part, item.quantity, item.material, item.size,
                f"{item.mass_each_g:.2f}" if item.mass_each_g else "",
                f"{item.mass_total_g:.2f}" if item.mass_each_g else "",
                item.source, item.note])
        writer.writerow([])
        writer.writerow(["Assembled mass (g)", f"{a.mass.total_mass_g:.1f}"])
    return path
