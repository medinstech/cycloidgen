"""Parameter studies: the grid, the table, and the ways a study goes wrong.

A study is worth less than the confidence people put in it, so the failures
here matter more than the happy path.  A grid that silently squares itself, a
blocked design quietly dropped, or one bad row taking the other three hundred
down are all ways to produce a table that looks complete and is not.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

import pytest

import cycloidgen
from cycloidgen.core.spec import preset
from cycloidgen.design.batch import (
    METRICS,
    Axis,
    columns,
    merge_axes,
    parse_axis,
    run_batch,
    write_csv,
)

# ------------------------------------------------------------------ the axes


def test_a_numeric_field_takes_a_value_or_a_range():
    assert parse_axis("disc_thickness", "8").values == (8.0,)
    axis = parse_axis("disc_thickness", "6:14:5")
    assert axis.values == (6.0, 8.0, 10.0, 12.0, 14.0)


def test_a_whole_number_field_gets_whole_numbers():
    """Five steps across a span rarely divide evenly, and the spec refuses
    8.667 output pins rather than rounding them - so a study asked for in good
    faith would come back as a column of blocked rows with nothing wrong with
    the design."""
    assert parse_axis("output_pin_count", "8:16:3").values == (8, 12, 16)
    assert parse_axis("output_pin_count", "8:16:4").values == (8, 11, 13, 16)
    assert all(isinstance(v, int) for v in parse_axis("lobes", "10:20:3").values)


def test_a_field_whose_type_never_says_int_can_still_be_one():
    """``disc_count`` is ``Literal[1, 2, 3]``.

    It holds integers while spelling neither ``int`` nor ``float``, so a type
    check that reads the annotation as text gets it wrong - and one of the
    process names contains "print", which gets it wrong the other way and
    silently.
    """
    assert parse_axis("disc_count", "2").values == (2,)
    assert parse_axis("process", "FDM 3D print").values == ("FDM 3D print",)


def test_a_range_of_one_step_is_the_bottom_of_it():
    """Rather than a division by zero, which is what ``(hi-lo)/(steps-1)`` is."""
    assert parse_axis("disc_thickness", "6:14:1").values == (6.0,)


def test_a_field_that_is_allowed_to_be_unset_is_still_numeric():
    """``surface_roughness_um`` is ``float | None`` and defaults to unset.

    It is also the field a lubrication study varies first, so reading its type
    off the current value rather than off the annotation would refuse exactly
    the sweep the feature exists for.
    """
    axis = parse_axis("surface_roughness_um", "0.2:3.2:3")
    assert axis.values == (0.2, 1.7, 3.2)


def test_a_named_thing_is_taken_literally():
    """Materials, lubricants and bearing designations are other people's names.

    Half of them contain the characters any list or range syntax would want,
    so they are never parsed - which is also why ``--vary`` repeats instead of
    taking a separated list.
    """
    assert parse_axis("lubricant", "Grease NLGI 2 (EP, moly)").values == \
        ("Grease NLGI 2 (EP, moly)",)
    assert parse_axis("disc_material", "Steel 1045").values == ("Steel 1045",)


def test_a_switch_reads_as_a_switch():
    """``false`` is a non-empty string, and a non-empty string is ``True``."""
    assert parse_axis("ring_pins_are_rollers", "true").values == (True,)
    assert parse_axis("ring_pins_are_rollers", "false").values == (False,)
    assert parse_axis("ring_pins_are_rollers", "no").values == (False,)
    with pytest.raises(ValueError):
        parse_axis("ring_pins_are_rollers", "maybe")


@pytest.mark.parametrize("field, text", [
    ("nonsense", "3"),                     # not a parameter at all
    ("disc_thickness", "6:14"),            # a range wants three parts
    ("disc_thickness", "six"),             # not a number
    ("disc_thickness", "6:14:0"),          # no steps
])
def test_a_study_that_cannot_be_read_says_so_before_it_runs(field, text):
    with pytest.raises(ValueError):
        parse_axis(field, text)


def test_two_values_of_one_field_are_one_axis_and_not_two():
    """The bug this prevents multiplies the grid instead of extending it.

    Two axes of one value each is one design; one axis of two values is two.
    Both run without complaint, and only one of them is the study that was
    asked for.
    """
    axes = merge_axes([parse_axis("disc_count", "1"), parse_axis("disc_count", "2")])
    assert len(axes) == 1
    assert axes[0].values == (1, 2)


# ------------------------------------------------------------------ the grid


def test_the_grid_is_every_combination():
    axes = [Axis("disc_count", (1, 2)), Axis("output_pin_count", (8, 10, 12))]
    points = run_batch(preset(21), axes)
    assert len(points) == 6
    seen = {(p.values["disc_count"], p.values["output_pin_count"]) for p in points}
    assert seen == {(1, 8), (1, 10), (1, 12), (2, 8), (2, 10), (2, 12)}


def test_no_axes_is_one_design_rather_than_none():
    points = run_batch(preset(15), [])
    assert len(points) == 1
    assert points[0].metrics["mass_g"] > 0


def test_a_blocked_design_stays_in_the_table():
    """Where the feasible band *ends* is most of what a study is for.

    A table of only the designs that worked cannot show you that, and looks
    exactly like a table where everything worked.
    """
    points = run_batch(preset(21), [Axis("disc_thickness", (8.0, 30.0))])
    assert len(points) == 2
    blocked = [p for p in points if not p.ok]
    assert blocked, "a 30 mm disc on this design should fail something"
    assert blocked[0].errors, "a blocked design has to say what blocked it"
    # and it still carries its numbers, because they are why it was blocked
    assert blocked[0].metrics["torque_capacity_Nm"] > 0


def test_a_value_the_spec_refuses_is_a_row_and_not_a_crash():
    """One impossible combination in a grid of four hundred must not end the run."""
    points = run_batch(preset(21), [Axis("pin_radius", (3.0, -1.0))])
    assert len(points) == 2
    assert points[0].ok
    assert not points[1].ok and points[1].errors


def test_a_metric_that_cannot_answer_gives_nan_and_keeps_the_row():
    """A drive on rollers has no sliding film to be thin.

    That is a different answer from a film that has failed, so it comes back
    as ``nan`` rather than as zero - a study that averaged the two would
    conclude that rollers are bad for lubrication.
    """
    spec = preset(21).model_copy(update={"ring_pins_are_rollers": True,
                                         "output_pins_are_rollers": True})
    point = run_batch(spec, [])[0]
    assert math.isnan(point.metrics["film_lambda_min"])
    assert point.metrics["efficiency"] > 0        # the rest of the row survives


def test_every_declared_metric_is_produced():
    """``METRICS`` is the one declaration of the table, so nothing may be missing."""
    point = run_batch(preset(15), [])[0]
    assert set(point.metrics) == {m.name for m in METRICS}
    assert all(m.unit is not None and m.note for m in METRICS)


def test_the_study_agrees_with_a_direct_analysis():
    """The grid must not be its own second opinion about the same design."""
    from cycloidgen.analysis import analyse

    spec = preset(21)
    point = run_batch(spec, [])[0]
    a = analyse(spec)
    assert point.metrics["efficiency"] == pytest.approx(a.efficiency.efficiency)
    assert point.metrics["mass_g"] == pytest.approx(a.mass.total_mass_g)
    assert point.metrics["temperature_C"] == pytest.approx(a.thermal.temperature_C)


def test_progress_is_reported_once_per_design():
    seen: list[tuple[int, int]] = []
    run_batch(preset(15), [Axis("disc_count", (1, 2, 3))],
              progress=lambda done, of: seen.append((done, of)))
    assert seen == [(1, 3), (2, 3), (3, 3)]


# ----------------------------------------------------------------- the table


def test_the_csv_header_is_the_declared_table(tmp_path: Path):
    axes = [Axis("disc_count", (1, 2))]
    points = run_batch(preset(21), axes)
    path = write_csv(points, axes, tmp_path / "study.csv")

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[1].split(",") == columns(axes)


def test_the_csv_says_which_build_produced_it(tmp_path: Path):
    """Every number in it is a model's answer and the model moves between
    releases; a table found six months later with no build on it is a table
    that has to be run again."""
    axes = [Axis("disc_count", (1, 2))]
    path = write_csv(run_batch(preset(21), axes), axes, tmp_path / "study.csv")

    first = path.read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith("#")
    assert cycloidgen.__version__ in first


def test_the_csv_reads_back_with_the_stamp_skipped(tmp_path: Path):
    """The documented way to read one, with nothing installed."""
    axes = [Axis("disc_count", (1, 2, 3))]
    points = run_batch(preset(21), axes)
    path = write_csv(points, axes, tmp_path / "study.csv")

    with path.open(encoding="utf-8") as handle:
        next(handle)                                    # the stamp
        rows = list(csv.DictReader(handle))
    assert len(rows) == 3
    assert [r["disc_count"] for r in rows] == ["1", "2", "3"]
    assert all(r["ok"] in ("yes", "no") for r in rows)
    assert float(rows[0]["mass_g"]) > 0


def test_a_nan_is_an_empty_cell_rather_than_the_word(tmp_path: Path):
    """``nan`` in a spreadsheet column turns the whole column into text."""
    spec = preset(21).model_copy(update={"ring_pins_are_rollers": True,
                                         "output_pins_are_rollers": True})
    points = run_batch(spec, [])
    path = write_csv(points, [], tmp_path / "study.csv")

    with path.open(encoding="utf-8") as handle:
        next(handle)
        row = next(csv.DictReader(handle))
    assert row["film_lambda_min"] == ""
    assert float(row["efficiency"]) > 0


def test_the_folder_is_made_rather_than_demanded(tmp_path: Path):
    axes = [Axis("disc_count", (1,))]
    path = write_csv(run_batch(preset(15), axes), axes,
                     tmp_path / "studies" / "one.csv")
    assert path.exists()
