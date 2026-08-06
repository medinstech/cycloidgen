"""Parameter studies without the window: many designs in, one table out.

``sweep.py`` moves one parameter and reports four metrics, because that is what
a chart can carry.  This is the other shape of the same question - vary as many
parameters as you like, over the whole cross product, and get every headline
number for every combination as a table something else can read.

It exists for two jobs that the GUI is the wrong tool for.  The first is the
ordinary one: "which of these forty variants should I build", answered in a
spreadsheet rather than by clicking through forty designs.  The second is the
one the roadmap is waiting on - fitting this model's free constants against
measurements from real hardware.  That is a script over a grid, and it needs
the analysis to be callable and the results to be tabular; until both were
true, calibration was blocked on something other than a lathe.

Nothing here is new physics.  Every column is a number the app already
computes, named once in ``METRICS`` so a study, the CSV header and the
documentation cannot describe different tables.
"""
from __future__ import annotations

import csv
import itertools
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import UnionType
from typing import Literal, Union, get_args, get_origin

from .. import __version__
from ..analysis import DesignAnalysis, analyse
from ..core.spec import GearSpec

__all__ = [
    "METRICS",
    "Axis",
    "BatchPoint",
    "Metric",
    "as_text",
    "columns",
    "parse_axis",
    "run_batch",
    "write_csv",
]


@dataclass(frozen=True)
class Metric:
    """One column of the result table.

    ``of`` takes the whole analysis rather than a named sub-result, because
    several of the numbers worth studying are properties across two of them -
    torque capacity is derated by a stiffness result, and the outer diameter is
    a spec property rather than an analysis at all.
    """

    name: str
    unit: str
    of: Callable[[DesignAnalysis], float]
    note: str


#: Everything a study reports, per design.  Ordered the way a person reads a
#: drive: what it can do, then what it costs to do it, then how big it is.
#:
#: The first five are the five quantities the calibration plan measures on real
#: hardware - lost motion, torsional stiffness, efficiency, running temperature
#: and failure torque - and they are first for that reason.
METRICS: tuple[Metric, ...] = (
    Metric("torque_capacity_Nm", "Nm",
           lambda a: a.torque_capacity_with_clearance_Nm,
           "load to destruction, derated for clearance concentrating the load"),
    Metric("efficiency", "",
           lambda a: a.efficiency.efficiency,
           "output power over input power at the duty point"),
    Metric("lost_motion_arcmin", "arcmin",
           lambda a: a.stiffness.lost_motion_arcmin,
           "play at the output before it moves, torque reversed"),
    Metric("stiffness_Nm_per_arcmin", "Nm/arcmin",
           lambda a: a.stiffness.stiffness_Nm_per_arcmin,
           "torsional stiffness, contacts and structure together"),
    Metric("temperature_C", "C",
           lambda a: a.thermal.temperature_C,
           "steady-state running temperature at the housing"),

    Metric("safety_factor", "x",
           lambda a: a.pin_safety_factor_with_clearance,
           "margin on ring-pin contact stress"),
    Metric("transmission_error_arcmin", "arcmin",
           lambda a: a.transmission_error.peak_to_peak_arcmin,
           "ripple in output angle under load, peak to peak"),
    Metric("fatigue_safety_factor", "x",
           lambda a: a.fatigue.safety_factor,
           "worst infinite-life margin; nan where the material is not modelled"),
    Metric("max_pin_pressure_MPa", "MPa",
           lambda a: a.contact.max_pin_pressure_MPa,
           "peak Hertzian contact pressure at the ring mesh"),
    Metric("pv_ring_MPa_m_s", "MPa.m/s",
           lambda a: a.thermal.pv_ring_MPa_m_s,
           "pressure x velocity at the ring contact, against its own limit"),
    Metric("film_lambda_min", "",
           lambda a: _worst_film(a),
           "thinnest film over roughness of any sliding contact; below 1 the "
           "asperities carry the load"),
    Metric("input_torque_Nm", "Nm",
           lambda a: a.efficiency.input_torque_Nm,
           "what the motor has to turn to get the duty point out"),

    Metric("mass_g", "g",
           lambda a: a.mass.total_mass_g,
           "assembled mass of every made part"),
    Metric("outer_diameter_mm", "mm",
           lambda a: 2.0 * a.spec.housing_outer_radius,
           "across the housing"),
    Metric("length_mm", "mm",
           lambda a: a.spec.envelope_length,
           "barrel plus both end plates"),
)


def _worst_film(a: DesignAnalysis) -> float:
    """The sliding contact with the least to spare, which is the one that wears.

    Reported as ``nan`` rather than zero when nothing slides, because a drive on
    rollers has no film to be thin - that is a different answer from a film that
    has failed, and averaging the two together is how a study concludes that
    rollers are bad for lubrication.
    """
    ratios = [c.lambda_ratio for c in a.efficiency.lubrication.contacts if c.slides]
    return min(ratios) if ratios else float("nan")


@dataclass(frozen=True)
class Axis:
    """One parameter and the values a study puts it through."""

    field: str
    values: tuple[object, ...]

    def __len__(self) -> int:
        return len(self.values)


@dataclass
class BatchPoint:
    """One design in the grid: what it was set to, and what came back."""

    values: dict[str, object]
    ok: bool
    metrics: dict[str, float] = field(default_factory=dict)
    errors: tuple[str, ...] = ()


# --------------------------------------------------------------- the grid


def _leaf_types(annotation) -> set[type]:
    """The concrete types an annotation can actually hold.

    Walked rather than matched as text.  ``disc_count`` is ``Literal[1, 2, 3]``
    and holds integers while spelling neither ``int`` nor ``float``; a
    ``Literal`` of *strings* can spell one by accident, and one of the process
    names contains "print".  Sniffing the repr gets both of those wrong, in
    opposite directions, and the second one silently.
    """
    origin = get_origin(annotation)
    if origin is Literal:
        return {type(value) for value in get_args(annotation)}
    if origin in (Union, UnionType):
        found: set[type] = set()
        for arg in get_args(annotation):
            if arg is not type(None):           # Optional is the field, not a type
                found |= _leaf_types(arg)
        return found
    return {annotation} if isinstance(annotation, type) else set()


def _numeric_kind(annotation) -> type | None:
    """``int``, ``float``, or ``None`` where this field does not take a number.

    ``bool`` is deliberately not numeric even though Python says it is a subclass
    of ``int``: ``--vary ring_pins_are_rollers=0:1:2`` is not a study anybody
    meant to run, and the switch has its own two-valued reading.
    """
    leaves = _leaf_types(annotation)
    if not leaves or not leaves <= {int, float}:
        return None
    return float if float in leaves else int


def parse_axis(field_name: str, text: str) -> Axis:
    """One ``--vary`` argument: a field and either a value or a range.

    Numeric fields take ``lo:hi:steps`` as well as a plain number, because a
    grid is mostly ranges and writing out twenty-one values by hand is how a
    study ends up with nineteen.  Everything else - a material, a lubricant, a
    process, a bearing designation, a switch - takes its value literally, which
    it has to: half the names in those tables contain the separators any
    cleverer syntax would want to use.
    """
    if field_name not in GearSpec.model_fields:
        raise ValueError(f"{field_name!r} is not a parameter of a design")
    model_field = GearSpec.model_fields[field_name]
    kind = _numeric_kind(model_field.annotation)

    if kind is not None and ":" in text:
        parts = text.split(":")
        if len(parts) != 3:
            raise ValueError(f"{field_name}: a range is lo:hi:steps, not {text!r}")
        try:
            lo, hi = float(parts[0]), float(parts[1])
            steps = int(parts[2])
        except ValueError:
            raise ValueError(f"{field_name}: {text!r} is not a lo:hi:steps range") from None
        if steps < 1:
            raise ValueError(f"{field_name}: a range needs at least one step")
        if steps == 1:
            return Axis(field_name, (_as(kind, lo),))
        span = (hi - lo) / (steps - 1)
        return Axis(field_name,
                    tuple(_as(kind, lo + i * span) for i in range(steps)))

    if kind is not None:
        try:
            return Axis(field_name, (_as(kind, float(text)),))
        except ValueError:
            raise ValueError(f"{field_name}: {text!r} is not a number") from None

    return Axis(field_name, (_literal(model_field, text),))


def _as(kind: type, value: float) -> int | float:
    """A step of the range as the field takes it.

    A whole-number field gets whole numbers: a range across five steps rarely
    divides evenly, and 8.667 output pins is refused by the spec rather than
    rounded by it - so the study would come back as a column of blocked rows
    with nothing wrong with the design.
    """
    return round(value) if kind is int else float(value)


def _literal(model_field, text: str) -> object:
    """A non-numeric value as the field wants it.

    Booleans are the only ones worth interpreting, because ``--vary
    ring_pins_are_rollers=false`` reading as ``True`` - a non-empty string - is
    the kind of quiet wrong answer that makes a whole study meaningless.
    """
    if model_field.annotation is bool:
        lowered = text.strip().lower()
        if lowered in {"true", "yes", "on", "1"}:
            return True
        if lowered in {"false", "no", "off", "0"}:
            return False
        raise ValueError(f"{text!r} is not true or false")
    if isinstance(model_field.annotation, type) and issubclass(model_field.annotation, Enum):
        return model_field.annotation(text)
    return text


def merge_axes(axes: Iterable[Axis]) -> list[Axis]:
    """Fold repeats of the same field into one axis, in the order first seen.

    ``--vary`` is repeatable per field on purpose - a list separator cannot be
    chosen that no material or lubricant name already contains - so two of them
    naming the same field are two values of one axis rather than two axes, and
    reading them as two axes would silently square the grid.
    """
    merged: dict[str, list[object]] = {}
    for axis in axes:
        merged.setdefault(axis.field, []).extend(axis.values)
    return [Axis(name, tuple(values)) for name, values in merged.items()]


def columns(axes: Sequence[Axis]) -> list[str]:
    """The table's header: what was varied, whether it built, then the numbers."""
    return ([a.field for a in axes] + ["ok"]
            + [m.name for m in METRICS] + ["errors"])


def run_batch(base: GearSpec, axes: Sequence[Axis],
              progress: Callable[[int, int], None] | None = None,
              ) -> list[BatchPoint]:
    """Analyse ``base`` once for every combination of ``axes``.

    Designs that fail a check are kept rather than dropped, with their error
    codes, because where the feasible region *ends* is most of what a study is
    for - a table of only the designs that worked cannot show you that.  A
    combination the spec itself refuses, or one whose geometry is degenerate
    enough that the analysis raises, is kept the same way.
    """
    axes = list(axes)
    grid = list(itertools.product(*[a.values for a in axes])) if axes else [()]
    points: list[BatchPoint] = []

    for i, combination in enumerate(grid):
        values = {a.field: v for a, v in zip(axes, combination, strict=True)}
        trial = base.model_copy(deep=True)
        try:
            for name, value in values.items():
                setattr(trial, name, value)
        except Exception as exc:                 # outside the field's own bounds
            points.append(BatchPoint(values, ok=False,
                                     errors=(_short(exc),)))
            if progress:
                progress(i + 1, len(grid))
            continue

        try:
            a = analyse(trial)
        except Exception as exc:                 # degenerate geometry
            points.append(BatchPoint(values, ok=False, errors=(_short(exc),)))
        else:
            points.append(BatchPoint(
                values=values,
                ok=a.report.ok,
                metrics={m.name: _measure(m, a) for m in METRICS},
                errors=tuple(f.code for f in a.report.errors),
            ))
        if progress:
            progress(i + 1, len(grid))

    return points


def _measure(metric: Metric, a: DesignAnalysis) -> float:
    """One column, or ``nan`` where this design cannot answer for it.

    A metric that raises must not take the row with it: the row is still the
    honest answer for every other column, and a study that dies on design 340
    of 400 has cost more than the one number it could not produce.
    """
    try:
        return float(metric.of(a))
    except Exception:
        return float("nan")


def _short(exc: Exception) -> str:
    return str(exc).splitlines()[0][:80] if str(exc) else type(exc).__name__


# ---------------------------------------------------------------- the table


def write_csv(points: Sequence[BatchPoint], axes: Sequence[Axis],
              path: str | Path) -> Path:
    """The study as a CSV, with the build that produced it on the first line.

    The stamp is a ``#`` comment rather than a column: a constant repeated down
    four hundred rows is noise, and every reader that matters here skips
    comments on request - ``pandas.read_csv(path, comment="#")``.  It is not
    optional decoration.  Every number in this file is a model's answer, the
    model improves between releases, and a table of results found six months
    later with no idea which build made it is a table that has to be run again.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = columns(axes)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(f"# cycloidgen {__version__} - {len(points)} design(s), "
                     f"{len(axes)} varied parameter(s)\n")
        writer = csv.writer(handle)
        writer.writerow(header)
        for point in points:
            writer.writerow(
                [as_text(point.values.get(a.field)) for a in axes]
                + ["yes" if point.ok else "no"]
                + [as_text(point.metrics.get(m.name)) for m in METRICS]
                + ["; ".join(point.errors)])
    return path


def as_text(value: object) -> str:
    """A value as text, with floats short enough to read and long enough to use."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, float):
        return "" if value != value else f"{value:.6g}"     # nan is not a number
    return str(value)
