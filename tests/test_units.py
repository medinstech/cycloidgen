"""The unit preference.

Everything inside the program is millimetres.  These tests hold the two claims
that makes worth anything: that switching the preference changes nothing but the
view, and that what leaves the program - a CAD file, a report - is millimetres
whatever the preference happens to be.
"""
from __future__ import annotations

import matplotlib
import pytest

matplotlib.use("Agg")

from cycloidgen.core.spec import preset
from cycloidgen.units import MM_PER_INCH, UNITS, unit


def test_millimetres_are_the_identity():
    mm = unit("mm")
    assert mm.show(12.5) == 12.5
    assert mm.store(12.5) == 12.5
    assert mm.decimals(3) == 3
    assert mm.text(120.0, 1) == "120.0 mm"


def test_inches_convert_and_carry_the_places_with_them():
    inch = unit("in")
    assert inch.show(25.4) == pytest.approx(1.0)
    assert inch.store(1.0) == pytest.approx(MM_PER_INCH)
    # 0.22 mm of clearance is 0.00866 in; three decimals would round it to 0.009
    assert inch.decimals(3) == 5
    # and the extra places arrive in the formatted text too
    assert inch.text(120.0, 1) == "4.724 in"


@pytest.mark.parametrize("key", sorted(UNITS))
@pytest.mark.parametrize("mm", [0.012, 0.22, 1.6, 50.0, 129.6])
def test_a_length_survives_the_round_trip(key, mm):
    u = unit(key)
    assert u.store(u.show(mm)) == pytest.approx(mm, rel=1e-12)


def test_an_unreadable_preference_costs_the_default_not_a_crash():
    """It comes out of a settings file an older or newer build may have written."""
    assert unit("furlongs").key == "mm"
    assert unit("").key == "mm"


def test_every_millimetre_field_is_a_length_and_nothing_else_is():
    """``Field.is_length`` is derived from the suffix rather than declared
    twice; this is the check that the derivation is the right one."""
    from cycloidgen.ui.fields import GROUPS

    for _group, fields in GROUPS:
        for f in fields:
            assert f.is_length == (f.suffix == " mm"), f.name
    lengths = {f.name for _g, fs in GROUPS for f in fs if f.is_length}
    assert "pin_circle_radius" in lengths and "profile_clearance" in lengths
    assert "input_rpm" not in lengths and "output_torque_Nm" not in lengths
    assert "lobes" not in lengths                      # its suffix is ":1"


# ------------------------------------------------------- what leaves the app


def test_a_figure_follows_the_preference():
    from cycloidgen.report import plots

    try:
        plots.set_units("in")
        fig = plots.profile_figure(preset(15))
        assert " in" in fig.axes[0].get_title()
    finally:
        plots.set_units("mm")


def test_but_a_document_is_always_millimetres():
    """The PDF is handed to someone else.  It must not carry the units the
    person who exported it happened to prefer."""
    from cycloidgen.report import plots

    try:
        plots.set_units("in")
        with plots.print_theme():
            fig = plots.profile_figure(preset(15))
        assert " mm" in fig.axes[0].get_title()
        # and the preference is still there afterwards
        assert plots._units == "in"
    finally:
        plots.set_units("mm")


def test_the_exported_geometry_is_millimetres_whatever_is_selected(tmp_path):
    """A CAD file whose units follow a preference is a CAD file nobody can
    trust, so the exporters never see the preference at all."""
    import json

    from cycloidgen.export import write_bundle
    from cycloidgen.report import plots

    try:
        plots.set_units("in")
        spec = preset(15)
        write_bundle(spec, tmp_path, groups={"drawings", "data"})
        report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
        assert report["spec"]["pin_circle_radius"] == pytest.approx(50.0)
        assert report["spec"]["profile_clearance"] == pytest.approx(0.22)
        # the drawing too: the disc reaches R - Rr + E = 47.6 from its centre
        svg = (tmp_path / "disc.svg").read_text(encoding="utf-8")
        assert "47." in svg or "-47." in svg
    finally:
        plots.set_units("mm")
