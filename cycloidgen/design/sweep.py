"""Sweep one parameter and watch everything else move.

A design is a compromise between four things that fight each other - how much
torque it takes, how efficiently it runs, how much play it has and how big it
is - and the interesting question is almost never "what does this parameter do
to *one* of them" but "what does it cost me in the other three".

So a sweep here reports all four, on their own real units, over whatever range
of one parameter you ask for.  No normalising, no composite index: four honest
curves you can read a trade-off off.

Kept out of the UI on purpose - it is ordinary computation and it should be
testable without starting a window.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from ..analysis import analyse
from ..core.spec import GearSpec

__all__ = [
    "SWEEPABLE",
    "SweepPoint",
    "SweepResult",
    "suggested_range",
    "sweep_parameter",
]

#: Parameters worth sweeping, with the label and unit the plots should use.
#: Only continuous geometry and duty - sweeping a material or an enum is a
#: comparison, not a trade study.
SWEEPABLE: dict[str, tuple[str, str]] = {
    "pin_circle_radius": ("Pin circle radius R", "mm"),
    "pin_radius": ("Pin radius Rr", "mm"),
    "eccentricity": ("Eccentricity E", "mm"),
    "lobes": ("Lobes (= ratio)", ":1"),
    "disc_thickness": ("Disc thickness", "mm"),
    "disc_count": ("Disc count", ""),
    "center_bore_diameter": ("Central bore", "mm"),
    "output_pin_count": ("Output pin count", ""),
    "output_pin_diameter": ("Output pin diameter", "mm"),
    "output_bolt_circle_radius": ("Output bolt circle", "mm"),
    "profile_clearance": ("Profile clearance", "mm"),
    "hole_clearance": ("Hole clearance", "mm"),
    "housing_wall": ("Housing wall", "mm"),
    "input_rpm": ("Input speed", "rpm"),
    "output_torque_Nm": ("Output torque", "Nm"),
    "friction_coefficient": ("Friction coefficient", ""),
}

#: Fields that only make sense as whole numbers.
_INTEGER_FIELDS = {"lobes", "disc_count", "output_pin_count"}


@dataclass(frozen=True)
class SweepPoint:
    """One evaluated design along the sweep."""

    value: float
    ok: bool
    capacity_Nm: float = float("nan")
    safety_factor: float = float("nan")
    efficiency: float = float("nan")
    lost_motion_arcmin: float = float("nan")
    stiffness_Nm_per_arcmin: float = float("nan")
    mass_g: float = float("nan")
    outer_diameter_mm: float = float("nan")
    temperature_C: float = float("nan")
    errors: tuple[str, ...] = ()


@dataclass
class SweepResult:
    field: str
    label: str
    unit: str
    current: float
    points: list[SweepPoint]

    def series(self, name: str) -> tuple[np.ndarray, np.ndarray]:
        """``(x, y)`` for one metric, with blocked designs left out."""
        xs, ys = [], []
        for p in self.points:
            if not p.ok:
                continue
            xs.append(p.value)
            ys.append(getattr(p, name))
        return np.asarray(xs, float), np.asarray(ys, float)

    @property
    def blocked(self) -> list[SweepPoint]:
        return [p for p in self.points if not p.ok]


def suggested_range(spec: GearSpec, field: str) -> tuple[float, float, int]:
    """A range worth looking at: roughly half to double the current value.

    Integer fields get their own sensible spans instead, because "half the lobe
    count" is a different gearbox, not a variation of this one.
    """
    current = float(getattr(spec, field))
    if field == "lobes":
        return max(3.0, current - 8), current + 8, 17
    if field == "disc_count":
        return 1.0, 3.0, 3
    if field == "output_pin_count":
        return max(3.0, current - 4), min(24.0, current + 6), int(
            min(24.0, current + 6) - max(3.0, current - 4)) + 1
    if field == "friction_coefficient":
        return 0.02, 0.4, 21
    lo = max(current * 0.55, 1e-4)
    return lo, current * 1.75, 21


def sweep_parameter(spec: GearSpec, field: str, values: Sequence[float],
                    progress: Callable[[int, int], None] | None = None,
                    cancelled: Callable[[], bool] | None = None) -> SweepResult:
    """Re-analyse ``spec`` with ``field`` set to each of ``values``.

    Designs that fail a check are kept in the result as blocked points rather
    than dropped, so the plots can show where the feasible band ends - which is
    usually the most useful thing on the chart.
    """
    if field not in SWEEPABLE:
        raise ValueError(f"{field!r} is not a sweepable parameter")
    label, unit = SWEEPABLE[field]
    points: list[SweepPoint] = []

    for i, raw in enumerate(values):
        if cancelled and cancelled():
            break
        value = round(float(raw)) if field in _INTEGER_FIELDS else float(raw)
        trial = spec.model_copy(deep=True)
        try:
            setattr(trial, field, int(value) if field in _INTEGER_FIELDS else value)
        except Exception:                        # outside the field's own bounds
            points.append(SweepPoint(value=value, ok=False, errors=("out of range",)))
            continue

        try:
            a = analyse(trial)
        except Exception as exc:                 # degenerate geometry
            points.append(SweepPoint(value=value, ok=False, errors=(str(exc)[:60],)))
            continue

        points.append(SweepPoint(
            value=value,
            ok=a.report.ok,
            capacity_Nm=a.torque_capacity_with_clearance_Nm,
            safety_factor=a.pin_safety_factor_with_clearance,
            efficiency=a.efficiency.efficiency,
            lost_motion_arcmin=a.stiffness.lost_motion_arcmin,
            stiffness_Nm_per_arcmin=a.stiffness.stiffness_Nm_per_arcmin,
            mass_g=a.mass.total_mass_g,
            outer_diameter_mm=2.0 * trial.housing_outer_radius,
            temperature_C=a.thermal.temperature_C,
            errors=tuple(f.code for f in a.report.errors),
        ))
        if progress:
            progress(i + 1, len(values))

    return SweepResult(field=field, label=label, unit=unit,
                       current=float(getattr(spec, field)), points=points)
