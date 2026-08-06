"""Switching parts off in the 3D tab, one bearing at a time.

A group toggle is enough for the housing: there is one of it and you either
want to see through it or you do not.  It is not enough for the bearings.  A
drive has four or five, in four different places, and the thing you are usually
trying to do - look at the cam bearing down the disc bore - means putting the
others away rather than putting all of them away.

These run headless against the software view, which is the one that renders
without a GL context.  What they assert is the *draw list*, not a picture: a
part is hidden when none of its faces are handed to the painter.
"""
from __future__ import annotations

import math
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cycloidgen.core.spec import Process, preset
from cycloidgen.ui.view3d import Assembly3DTab, AssemblyView
from cycloidgen.viz.mesh import mesh_for_spec
from cycloidgen.viz.scene import Camera, render


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _spec():
    spec = preset(21)
    spec.process = Process.CNC
    spec.apply_process_defaults()
    spec.disc_material = "Steel 4140 (hardened)"
    spec.pin_material = "Bearing steel 100Cr6"
    return spec


def _faces_by_part(spec, hidden=()):
    """How many faces each part contributes to one frame."""
    mesh = mesh_for_spec(spec)
    draw = render(mesh, 0.4, Camera.framing(mesh), 640, 480, hidden=hidden)
    counts = dict.fromkeys((p.name for p in mesh.parts), 0)
    for index in draw.parts:
        counts[mesh.parts[index].name] += 1
    return counts


def _bearings(spec):
    return [p.name for p in mesh_for_spec(spec).parts if p.group == "bearings"]


def test_hiding_one_bearing_leaves_the_others_alone():
    """The whole point of the control: not all of them, one of them."""
    spec = _spec()
    names = _bearings(spec)
    assert len(names) > 1, "this design has nothing to tell apart"

    everything = _faces_by_part(spec)
    assert all(everything[n] for n in names)

    without = _faces_by_part(spec, hidden={names[0]})
    assert without[names[0]] == 0
    for other in names[1:]:
        assert without[other] == everything[other], other
    # ...and nothing that is not a bearing moved either.
    for name, count in everything.items():
        if name not in names:
            assert without[name] == count, name


def test_a_part_name_and_a_group_name_can_share_one_set():
    """Groups and single parts go into ``hidden`` together, so a name that means
    both has to mean the same thing either way.

    Two of them do: the housing and the ring pins are each a group of exactly one
    part, named the same as it.  That is fine - hiding the group and hiding the
    part are the same instruction.  A group of *several* parts sharing a name
    with one of them would not be, and is what this rules out.
    """
    spec = _spec()
    mesh = mesh_for_spec(spec)
    names = {p.name for p in mesh.parts}
    for group in {p.group for p in mesh.parts} & names:
        members = [p.name for p in mesh.parts if p.group == group]
        assert members == [group], group


def test_the_menu_lists_the_bearings_this_design_has(app):
    tab = Assembly3DTab()
    spec = _spec()
    tab.set_spec(spec)
    labels = [a.text() for a in tab._bearing_menu.menu().actions()]
    mesh = mesh_for_spec(spec)
    assert labels == [p.label for p in mesh.parts if p.group == "bearings"]
    assert tab._bearing_menu.isEnabled()
    assert all(a.isChecked() for a in tab._bearing_menu.menu().actions())


def test_a_bearing_put_away_stays_away_across_a_design_change(app):
    """The names are stable, so changing preset and coming back must not
    quietly put a part you had hidden back on the screen."""
    tab = Assembly3DTab()
    tab.set_spec(_spec())
    first = tab._bearing_menu.menu().actions()[0]
    first.setChecked(False)
    hidden = sorted(tab._hidden_parts)
    assert len(hidden) == 1

    tab.set_spec(preset(29))
    tab.set_spec(_spec())
    assert sorted(tab._hidden_parts) == hidden
    assert not tab._bearing_menu.menu().actions()[0].isChecked()


def test_the_hidden_bearings_reach_the_animation_export(app):
    """`render_options` is what an exported animation is drawn with; a bearing
    switched off on screen has to be off in the file too."""
    tab = Assembly3DTab()
    tab.set_spec(_spec())
    tab._bearing_menu.menu().actions()[0].setChecked(False)
    tab._groups["housing"].setChecked(False)
    hidden = tab.render_options()["hidden"]
    assert "housing" in hidden
    assert next(iter(tab._hidden_parts)) in hidden


def test_the_view_itself_was_told_and_not_only_the_menu(app):
    """The checkbox state and the renderer are two different things."""
    tab = Assembly3DTab()
    spec = _spec()
    tab.set_spec(spec)
    name = _bearings(spec)[0]
    action = next(a for a in tab._bearing_menu.menu().actions()
                  if a.text() == next(p.label for p in mesh_for_spec(spec).parts
                                      if p.name == name))
    action.setChecked(False)

    view = tab.view
    if not isinstance(view, AssemblyView):
        pytest.skip("the hardware view is up; its actors are checked by eye")
    draw = render(mesh_for_spec(spec), 0.0, view.camera, 320, 240,
                  hidden=view._hidden)
    mesh = mesh_for_spec(spec)
    assert all(mesh.parts[i].name != name for i in draw.parts)


def test_the_state_survives_being_saved_and_restored(app, tmp_path, monkeypatch):
    from cycloidgen.ui.settings import ENV_VAR

    monkeypatch.setenv(ENV_VAR, str(tmp_path / "cycloidgen.ini"))
    spec = _spec()

    tab = Assembly3DTab()
    tab.set_spec(spec)
    name = _bearings(spec)[0]
    tab._set_part_visible(name, False)
    tab._groups["shaft"].setChecked(False)
    tab.save_state()

    other = Assembly3DTab()
    other.restore_state()
    other.set_spec(spec)
    assert name in other._hidden_parts
    assert not other._groups["shaft"].isChecked()
    assert other._groups["bearings"].isChecked()          # the group is still on
    counts = _faces_by_part(spec, hidden=other.render_options()["hidden"])
    assert counts[name] == 0
    assert counts[_bearings(spec)[1]] > 0


def test_hiding_the_group_still_takes_every_bearing_with_it():
    """The per-part menu is an addition to the group switch, not a replacement."""
    spec = _spec()
    counts = _faces_by_part(spec, hidden={"bearings"})
    assert all(counts[n] == 0 for n in _bearings(spec))
    assert counts["housing"] > 0
    assert math.isfinite(sum(counts.values()))


def test_the_tab_opens_with_the_end_plates_off(app):
    """With them on, the first thing a design tool shows is a closed cylinder.

    Not hidden from anyone - the checkbox is visibly unticked and one click
    away - but the default starts where the work is.  The bolts go with them:
    six fasteners floating where the plates they hold on are not is a stranger
    picture than either.
    """
    from cycloidgen.ui.view3d import _HIDDEN_BY_DEFAULT

    tab = Assembly3DTab()
    tab.set_spec(_spec())
    assert not tab._groups["end_plates"].isChecked()
    assert tab._groups["housing"].isChecked()
    assert not tab._groups["fasteners"].isChecked()
    assert "end_plates" in tab.render_options()["hidden"]
    assert "fasteners" in tab.render_options()["hidden"]

    counts = _faces_by_part(_spec(), hidden=tab.render_options()["hidden"])
    plates = [p.name for p in mesh_for_spec(_spec()).parts
              if p.group == "end_plates"]
    assert plates and all(counts[n] == 0 for n in plates)
    assert set(_HIDDEN_BY_DEFAULT) == {"end_plates", "fasteners"}


def test_taking_the_plates_back_off_hidden_survives_a_restart(app, tmp_path,
                                                              monkeypatch):
    """A stored empty list means "everything on", not "no preference" - reading
    it as the latter put the plates back every time you switched them on."""
    from cycloidgen.ui.settings import ENV_VAR
    from cycloidgen.ui.view3d import _HIDDEN_BY_DEFAULT

    monkeypatch.setenv(ENV_VAR, str(tmp_path / "cycloidgen.ini"))
    tab = Assembly3DTab()
    tab.set_spec(_spec())
    for group in _HIDDEN_BY_DEFAULT:
        tab._groups[group].setChecked(True)
    assert tab._hidden() == []
    tab.save_state()

    other = Assembly3DTab()
    other.restore_state()
    assert all(other._groups[g].isChecked() for g in _HIDDEN_BY_DEFAULT)
