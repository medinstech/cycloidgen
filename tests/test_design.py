"""The requirements-to-design search, the trade study, and undo/redo."""
from __future__ import annotations

import numpy as np
import pytest

from cycloidgen.analysis import analyse
from cycloidgen.core.profile import critical_radius, locus_curvature
from cycloidgen.core.spec import Process, preset
from cycloidgen.design import Objective, Requirements, optimise
from cycloidgen.design.optimize import _shaft_diameter, _latin_hypercube
from cycloidgen.design.sweep import (SWEEPABLE, suggested_range, sweep_parameter)
from cycloidgen.ui.history import SpecHistory


def _steel_requirements(**overrides) -> Requirements:
    """A duty a steel drive can comfortably meet, so the search has something
    to find."""
    base = dict(
        ratio=29, output_torque_Nm=20.0, input_rpm=1500,
        max_outer_diameter_mm=120.0, max_length_mm=60.0,
        process=Process.CNC, disc_material="Steel 4140 (hardened)",
        pin_material="Bearing steel 100Cr6",
        housing_material="Aluminium 7075-T6", shaft_material="Steel 1045",
        ring_pins_are_rollers=True, output_pins_are_rollers=True)
    base.update(overrides)
    return Requirements(**base)


# ------------------------------------------------------- closed-form curvature


def test_closed_form_critical_radius_matches_a_brute_force_search():
    """The undercut limit used to be a 40,000 point scan.  The design search
    calls it tens of thousands of times, so it is now solved outright - and it
    has to agree with what the scan said."""
    for R in (30.0, 50.0, 70.0):
        for lobes in (7, 15, 29, 59):
            for k1 in (0.15, 0.4, 0.65, 0.9):
                E = k1 * R / (lobes + 1)
                t = np.linspace(0.0, 2.0 * np.pi, 200_000, endpoint=False)
                worst = -locus_curvature(t, R, E, lobes).min()
                assert critical_radius(R, E, lobes) == pytest.approx(
                    1.0 / worst, rel=1e-4)


def test_critical_radius_collapses_at_the_cusp_limit():
    R, lobes = 50.0, 15
    assert critical_radius(R, 1.0 * R / (lobes + 1), lobes) == 0.0


# ------------------------------------------------------------------- sampling


def test_latin_hypercube_stratifies_every_column_independently():
    """Permuting the array instead of each column leaves every knob on the same
    stratum, which quietly collapses the search onto its own diagonal."""
    rng = np.random.default_rng(0)
    sample = _latin_hypercube(rng, 24, 6)
    assert sample.shape == (24, 6)
    assert sample.min() >= 0.0 and sample.max() <= 1.0
    for column in sample.T:                       # one point per stratum
        assert sorted(np.floor(column * 24).astype(int)) == list(range(24))
    # columns must not move together
    correlation = np.corrcoef(sample.T)
    off_diagonal = correlation[~np.eye(6, dtype=bool)]
    assert np.abs(off_diagonal).max() < 0.75


# ------------------------------------------------------------------- shafting


def test_shaft_sizing_grows_with_torque_and_never_goes_silly_small():
    small = _shaft_diameter(0.5, "Steel 1045", 45.0)
    large = _shaft_diameter(200.0, "Steel 1045", 45.0)
    assert large > small
    assert small >= 6.0                            # bending floor, not torsion
    assert _shaft_diameter(0.1, "Steel 1045", 200.0) >= 24.0   # scales with size


# ------------------------------------------------------------------ optimiser


def test_the_search_finds_designs_that_pass_every_check():
    result = optimise(_steel_requirements(), effort="quick")
    assert result.ok, result.tally.explain()
    for candidate in result.best:
        assert analyse(candidate.spec).report.ok


def test_results_honour_the_stated_envelope_and_margin():
    req = _steel_requirements()
    result = optimise(req, effort="quick")
    assert result.best
    for c in result.best:
        assert c.outer_diameter_mm <= req.max_outer_diameter_mm + 1e-6
        assert c.length_mm <= req.max_length_mm + 1e-6
        assert c.safety_factor >= req.min_safety_factor
        assert c.spec.ratio == req.ratio


def test_results_come_back_best_first():
    result = optimise(_steel_requirements(), effort="quick")
    scores = [c.score for c in result.best]
    assert scores == sorted(scores, reverse=True)


def test_compact_objective_produces_a_smaller_drive_than_capacity():
    small = optimise(_steel_requirements(objective=Objective.COMPACT), effort="quick")
    strong = optimise(_steel_requirements(objective=Objective.CAPACITY), effort="quick")
    assert small.ok and strong.ok
    assert small.best[0].outer_diameter_mm < strong.best[0].outer_diameter_mm


def test_a_hard_disc_count_is_respected():
    result = optimise(_steel_requirements(disc_count=3), effort="quick")
    assert result.ok
    assert all(c.spec.disc_count == 3 for c in result.best)


def test_an_impossible_requirement_explains_itself_instead_of_going_quiet():
    """An optimiser that returns nothing and says nothing is worse than useless."""
    result = optimise(_steel_requirements(max_outer_diameter_mm=25.0), effort="quick")
    assert not result.ok
    assert result.tally.counts
    # and it must name the lever the user can pull, not a downstream symptom
    assert "diameter" in result.tally.explain()


def test_an_unreachable_torque_blames_the_stress_margin():
    result = optimise(_steel_requirements(output_torque_Nm=4000.0), effort="quick")
    assert not result.ok
    assert "margin" in result.tally.explain()


def test_the_search_is_reproducible():
    a = optimise(_steel_requirements(), effort="quick", seed=7)
    b = optimise(_steel_requirements(), effort="quick", seed=7)
    assert [c.score for c in a.best] == [c.score for c in b.best]


def test_cancelling_stops_the_search():
    result = optimise(_steel_requirements(), effort="thorough",
                      cancelled=lambda: True)
    assert result.evaluations == 0


# ----------------------------------------------------------------- trade study


def test_a_sweep_walks_the_parameter_and_keeps_the_blocked_points():
    spec = preset(15)
    values = np.linspace(2.0, 9.0, 7)
    result = sweep_parameter(spec, "pin_radius", values)
    assert len(result.points) == 7
    assert [p.value for p in result.points] == pytest.approx(list(values))
    x, y = result.series("capacity_Nm")
    assert len(x) == len(y) <= 7
    assert all(np.isfinite(y))


def test_a_sweep_actually_changes_the_answer():
    spec = preset(15)
    result = sweep_parameter(spec, "disc_thickness", [4.0, 16.0])
    caps = [p.capacity_Nm for p in result.points if p.ok]
    assert len(caps) == 2
    assert caps[1] > caps[0]            # a thicker disc carries more


def test_integer_parameters_stay_integers():
    result = sweep_parameter(preset(15), "output_pin_count", [4.2, 5.8, 7.1])
    assert [p.value for p in result.points] == [4.0, 6.0, 7.0]


def test_sweeping_past_the_field_bounds_is_reported_not_raised():
    result = sweep_parameter(preset(15), "output_pin_count", [1.0, 6.0, 900.0])
    assert not result.points[0].ok and not result.points[2].ok
    assert result.points[1].ok


def test_a_sweep_can_be_cancelled():
    result = sweep_parameter(preset(15), "pin_radius", np.linspace(2, 9, 40),
                             cancelled=lambda: True)
    assert result.points == []


@pytest.mark.parametrize("field", list(SWEEPABLE))
def test_every_sweepable_field_has_a_usable_suggested_range(field):
    spec = preset(15)
    lo, hi, steps = suggested_range(spec, field)
    assert lo < hi
    assert 3 <= steps <= 81
    assert hasattr(spec, field)


def test_sweeping_something_that_is_not_a_parameter_is_an_error():
    with pytest.raises(ValueError):
        sweep_parameter(preset(15), "not_a_field", [1.0])


# --------------------------------------------------------------------- history


def test_history_walks_backwards_and_forwards():
    spec = preset(15)
    history = SpecHistory(spec)
    assert not history.can_undo and not history.can_redo

    spec.pin_radius = 3.0
    history.push(spec)
    spec.pin_radius = 2.0
    history.push(spec)
    assert history.can_undo

    assert history.undo().pin_radius == 3.0
    assert history.undo().pin_radius == 4.0
    assert not history.can_undo
    assert history.redo().pin_radius == 3.0
    assert history.redo().pin_radius == 2.0
    assert not history.can_redo


def test_a_new_edit_drops_the_redo_tail():
    spec = preset(15)
    history = SpecHistory(spec)
    for r in (3.0, 2.0):
        spec.pin_radius = r
        history.push(spec)
    history.undo()
    changed = history.current()
    changed.disc_thickness = 12.0
    history.push(changed)
    assert not history.can_redo


def test_pushing_the_same_state_twice_does_nothing():
    spec = preset(15)
    history = SpecHistory(spec)
    history.push(spec.model_copy(deep=True))
    assert len(history) == 1
    assert not history.can_undo


def test_history_is_bounded():
    spec = preset(15)
    history = SpecHistory(spec, limit=5)
    for i in range(30):
        spec.disc_thickness = 4.0 + i * 0.5
        history.push(spec)
    assert len(history) == 5
    assert history.current().disc_thickness == pytest.approx(4.0 + 29 * 0.5)


# ------------------------------------------------------------------------ CLI


def test_cli_search_reports_a_shortlist(capsys):
    from cycloidgen.__main__ import main
    code = main(["--optimise", "--ratio", "29", "--torque", "20", "--rpm", "1500",
                 "--max-od", "120", "--process", "CNC machined",
                 "--disc-material", "Steel 4140 (hardened)",
                 "--pin-material", "Bearing steel 100Cr6", "--rollers",
                 "--effort", "quick"])
    out = capsys.readouterr().out
    assert code == 0
    assert "capacity" in out and "taking #1" in out


def test_cli_search_that_finds_nothing_says_why(capsys):
    from cycloidgen.__main__ import main
    code = main(["--optimise", "--ratio", "29", "--torque", "500",
                 "--max-od", "40", "--effort", "quick"])
    assert code == 3
    assert "what stopped them" in capsys.readouterr().err


def test_cli_rejects_an_unknown_material(capsys):
    from cycloidgen.__main__ import main
    assert main(["--optimise", "--disc-material", "unobtainium"]) == 2
    assert "unknown material" in capsys.readouterr().err


def test_reset_starts_a_fresh_stack():
    history = SpecHistory(preset(15))
    spec = preset(15)
    spec.pin_radius = 3.0
    history.push(spec)
    history.reset(preset(29))
    assert not history.can_undo and not history.can_redo
    assert history.current().lobes == 29
