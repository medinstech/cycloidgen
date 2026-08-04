"""Figures.

Mostly about honesty rather than appearance: a chart that magnifies a tenth of
a percent into a decisive-looking trend is telling the reader something untrue,
and on a trade-study chart that is the whole point of the chart.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pytest
from matplotlib.figure import Figure

from cycloidgen.core.spec import preset
from cycloidgen.design.sweep import sweep_parameter
from cycloidgen.report import plots


def test_a_nearly_flat_series_is_anchored_at_zero():
    fig = Figure()
    ax = fig.add_subplot(111)
    y = np.array([10.206, 10.210, 10.215])            # a 0.09 % span
    ax.plot([1, 2, 3], y)
    plots._anchor_axis(ax, y)
    assert ax.get_ylim()[0] == 0.0


def test_a_series_that_really_moves_keeps_its_own_range():
    fig = Figure()
    ax = fig.add_subplot(111)
    y = np.array([10.0, 60.0, 115.0])
    ax.plot([1, 2, 3], y)
    plots._anchor_axis(ax, y)
    assert ax.get_ylim()[0] > 0.0


def test_a_series_crossing_zero_is_left_alone():
    """Anchoring assumes a magnitude; a signed quantity is not one."""
    fig = Figure()
    ax = fig.add_subplot(111)
    y = np.array([-5.0, 0.0, 5.0])
    ax.plot([1, 2, 3], y)
    before = ax.get_ylim()
    plots._anchor_axis(ax, y)
    assert ax.get_ylim() == before


def test_the_force_figure_y_axis_starts_at_zero():
    """Ring pin load varies by a fraction of a percent over the mesh cycle."""
    fig = plots.force_figure(preset(15), Figure(), steps=24)
    assert fig.axes[0].get_ylim()[0] == 0.0


def test_sweep_figure_draws_four_panels_and_marks_the_current_design():
    spec = preset(15)
    result = sweep_parameter(spec, "pin_radius", np.linspace(3.0, 5.0, 5))
    fig = plots.sweep_figure(result, Figure())
    assert len(fig.axes) == 4
    for ax in fig.axes:
        assert ax.get_xlabel()
        assert ax.get_ylabel()


def test_sweep_figure_survives_a_range_where_everything_is_blocked():
    """The shaded-blocked path must not depend on there being good points."""
    result = sweep_parameter(preset(15), "pin_radius", [40.0, 60.0])
    assert all(not p.ok for p in result.points)
    fig = plots.sweep_figure(result, Figure())
    assert len(fig.axes) == 4


def test_profile_figure_can_draw_a_reference_underneath():
    a, b = preset(15), preset(29)
    fig = plots.profile_figure(a, Figure(), crank_deg=20.0, reference=b)
    ax = fig.axes[0]
    # the ghost outline is an extra line beyond the discs of the live design
    assert len(ax.lines) >= a.disc_count + 1
    limit = ax.get_xlim()[1]
    assert limit >= b.housing_outer_radius     # the frame must fit both


def test_the_print_theme_round_trips():
    plots.set_theme("dark")
    dark = plots.theme()["surface"]
    with plots.print_theme():
        assert plots.theme()["surface"] == "#ffffff"
    assert plots.theme()["surface"] == dark          # restored
    plots.set_theme("light")


def test_the_report_prints_on_white_not_on_the_app_paper():
    """The application's light mode is tinted so figures match their panel.
    A PDF is a print document: a tint on every figure is ink someone pays for
    and gains nothing on paper."""
    plots.set_theme("light")
    assert plots.theme()["surface"] != "#ffffff"
    with plots.print_theme():
        assert plots.theme()["surface"] == "#ffffff"


def test_a_figure_sits_on_the_same_tone_as_the_panel_around_it():
    """A white slab inside a tinted window is the thing the theme exists to
    prevent, so this pins the relationship rather than a literal colour."""
    from cycloidgen.ui import branding
    for mode in ("light", "dark"):
        plots.set_theme(mode)
        assert plots.theme()["surface"] == branding.palette(mode).raised
    plots.set_theme("light")


def test_the_series_keep_their_lightness_spread():
    """Contrast against the paper is only half the job; telling the three
    apart rests on their lightness differing, which is what survives when the
    hues do not."""
    from cycloidgen.ui.branding import contrast_ratio
    for mode in ("light", "dark"):
        plots.set_theme(mode)
        from itertools import combinations
        # Measured: 1.38/1.57/1.14 light, 1.07/1.07/1.14 dark.  The floor
        # guards against them collapsing onto one lightness, which is what
        # re-tuning them for background contrast would do.
        for a, b in combinations(plots.theme()["series"], 2):
            assert contrast_ratio(a, b) > 1.05
    plots.set_theme("light")


def test_an_unknown_theme_is_refused():
    with pytest.raises(ValueError):
        plots.set_theme("neon")
