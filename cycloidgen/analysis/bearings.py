"""Bearing sizing help for the three load paths in a cycloidal drive.

Catalogue values are nominal metric-series figures and are meant for first-pass
selection only; confirm against the manufacturer's data before ordering.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.spec import GearSpec

__all__ = ["CATALOGUE", "Bearing", "BearingChoice", "select_bearings"]


@dataclass(frozen=True)
class Bearing:
    designation: str
    bore: float
    outer: float
    width: float
    C_kN: float          # basic dynamic load rating
    C0_kN: float         # basic static load rating
    kind: str            # "ball" or "needle"

    @property
    def life_exponent(self) -> float:
        return 3.0 if self.kind == "ball" else 10.0 / 3.0


CATALOGUE: list[Bearing] = [
    # thin section, 6800 series
    Bearing("6800", 10, 19, 5, 1.74, 0.915, "ball"),
    Bearing("6801", 12, 21, 5, 1.92, 1.06, "ball"),
    Bearing("6802", 15, 24, 5, 2.08, 1.27, "ball"),
    Bearing("6803", 17, 26, 5, 2.21, 1.43, "ball"),
    Bearing("6804", 20, 32, 7, 4.03, 2.32, "ball"),
    Bearing("6805", 25, 37, 7, 4.36, 2.90, "ball"),
    Bearing("6806", 30, 42, 7, 4.62, 3.35, "ball"),
    Bearing("6807", 35, 47, 7, 4.94, 4.00, "ball"),
    Bearing("6808", 40, 52, 7, 5.07, 4.30, "ball"),
    # 6900 series
    Bearing("6900", 10, 22, 6, 2.70, 1.27, "ball"),
    Bearing("6901", 12, 24, 6, 2.89, 1.46, "ball"),
    Bearing("6902", 15, 28, 7, 4.36, 2.24, "ball"),
    Bearing("6903", 17, 30, 7, 4.62, 2.55, "ball"),
    Bearing("6904", 20, 37, 9, 6.37, 3.65, "ball"),
    Bearing("6905", 25, 42, 9, 7.02, 4.30, "ball"),
    Bearing("6906", 30, 47, 9, 7.28, 5.00, "ball"),
    # 6000 series
    Bearing("6000", 10, 26, 8, 4.62, 1.96, "ball"),
    Bearing("6001", 12, 28, 8, 5.10, 2.36, "ball"),
    Bearing("6002", 15, 32, 9, 5.59, 2.85, "ball"),
    Bearing("6003", 17, 35, 10, 6.37, 3.25, "ball"),
    Bearing("6004", 20, 42, 12, 9.36, 5.00, "ball"),
    Bearing("6005", 25, 47, 12, 10.1, 5.85, "ball"),
    Bearing("6006", 30, 55, 13, 13.3, 8.30, "ball"),
    # drawn cup needle rollers, compact and stiff - ideal for the eccentric
    Bearing("HK0808", 8, 12, 8, 4.10, 3.60, "needle"),
    Bearing("HK1010", 10, 14, 10, 5.60, 5.60, "needle"),
    Bearing("HK1212", 12, 16, 12, 7.00, 7.50, "needle"),
    Bearing("HK1512", 15, 21, 12, 10.5, 11.0, "needle"),
    Bearing("HK1612", 16, 22, 12, 10.8, 11.6, "needle"),
    Bearing("HK2020", 20, 26, 20, 16.5, 20.0, "needle"),
    Bearing("HK2520", 25, 32, 20, 19.6, 25.5, "needle"),
    Bearing("HK3020", 30, 37, 20, 21.6, 30.0, "needle"),
]


@dataclass
class BearingChoice:
    role: str
    bearing: Bearing | None
    load_N: float
    speed_rpm: float
    life_hours: float
    note: str

    @property
    def ok(self) -> bool:
        return self.bearing is not None and self.life_hours >= 1000.0


def _life_hours(b: Bearing, load_N: float, rpm: float) -> float:
    if load_N <= 0 or rpm <= 0:
        return float("inf")
    ratio = (b.C_kN * 1000.0) / load_N
    return (10 ** 6 / (60.0 * rpm)) * ratio ** b.life_exponent


def _pick(bore_min: float, outer_max: float, width_max: float,
          load_N: float, rpm: float, kinds: tuple[str, ...]) -> Bearing | None:
    """Smallest catalogue bearing that fits the envelope and lasts 1000 h."""
    candidates = [
        b for b in CATALOGUE
        if b.kind in kinds
        and b.bore >= bore_min - 1e-6
        and b.outer <= outer_max + 1e-6
        and b.width <= width_max + 1e-6
        and _life_hours(b, load_N, rpm) >= 1000.0
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda b: (b.outer, b.width))


def select_bearings(spec: GearSpec, eccentric_load_N: float,
                    output_pin_load_N: float) -> list[BearingChoice]:
    """Suggest bearings for the eccentric, the output pins and the output shaft."""
    out: list[BearingChoice] = []

    # 1. eccentric cam bearing - highest speed, sits inside the disc bore
    rpm = spec.input_rpm * (1.0 - 1.0 / spec.ratio)
    b = _pick(spec.input_shaft_diameter, spec.center_bore_diameter,
              spec.disc_thickness, eccentric_load_N, rpm, ("needle", "ball"))
    out.append(BearingChoice(
        role="Eccentric cam bearing (one per disc)",
        bearing=b, load_N=eccentric_load_N, speed_rpm=rpm,
        life_hours=_life_hours(b, eccentric_load_N, rpm) if b else 0.0,
        note=("fits the disc bore" if b else
              "no catalogue bearing fits: enlarge the central bore or thicken the disc"),
    ))

    # 2. output pin bushings - optional, they cut the biggest sliding loss
    if spec.output_pins_are_rollers:
        bore = spec.output_pin_diameter
        outer = spec.output_hole_diameter - 2 * spec.eccentricity
        b2 = _pick(bore, outer, spec.disc_thickness, output_pin_load_N,
                   spec.input_rpm, ("needle",))
        out.append(BearingChoice(
            role="Output pin roller", bearing=b2, load_N=output_pin_load_N,
            speed_rpm=spec.input_rpm,
            life_hours=_life_hours(b2, output_pin_load_N, spec.input_rpm) if b2 else 0.0,
            note=("" if b2 else "no roller fits; use a plain bronze bushing instead"),
        ))
    else:
        out.append(BearingChoice(
            role="Output pin roller", bearing=None, load_N=output_pin_load_N,
            speed_rpm=spec.input_rpm, life_hours=float("inf"),
            note="fixed pins selected - sliding contact, expect lower efficiency",
        ))

    # 3. main output bearing - carries the external load, turns slowly
    radial = output_pin_load_N * spec.output_pin_count / 2.0
    b3 = _pick(spec.center_bore_diameter, spec.housing_outer_radius * 2.0,
               spec.housing_wall * 2.0, radial, spec.output_rpm, ("ball",))
    out.append(BearingChoice(
        role="Main output bearing", bearing=b3, load_N=radial,
        speed_rpm=spec.output_rpm,
        life_hours=_life_hours(b3, radial, spec.output_rpm) if b3 else 0.0,
        note=("" if b3 else "consider a crossed-roller or a pair of angular contact bearings"),
    ))
    return out
