"""Appearance, workspace persistence and the checks filter.

These exercise the real window, so they need Qt and run headless.  Settings are
redirected into a temporary directory: a test suite that writes to the user's
actual preferences would silently rearrange their application.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from cycloidgen.core.validate import Severity

_USER_ROLE = 0x0100                                      # Qt.UserRole


@pytest.fixture(scope="module", autouse=True)
def isolated_settings(tmp_path_factory):
    """Send preferences to a scratch file for the duration of this module.

    Qt's own ``setDefaultFormat`` redirection is silently ignored for the
    ``QSettings(organisation, application)`` constructor on Windows, so these
    tests would otherwise read and rewrite the developer's real preferences
    while looking perfectly isolated.  The application reads one environment
    variable instead - see ``cycloidgen.ui.settings``.
    """
    from cycloidgen.ui.settings import ENV_VAR

    path = tmp_path_factory.mktemp("settings") / "cycloidgen.ini"
    previous = os.environ.get(ENV_VAR)
    os.environ[ENV_VAR] = str(path)
    yield path
    if previous is None:
        os.environ.pop(ENV_VAR, None)
    else:
        os.environ[ENV_VAR] = previous


@pytest.fixture(scope="module")
def app(isolated_settings):
    return QApplication.instance() or QApplication([])


def test_the_isolation_actually_isolates(isolated_settings):
    """If this fails, every other test in this file is writing to the user's
    real settings and silently rearranging their application."""
    from cycloidgen.ui.settings import app_settings

    settings = app_settings()
    assert Path(settings.fileName()) == Path(isolated_settings)
    settings.setValue("canary", 1)
    settings.sync()
    assert isolated_settings.exists()


def _pump(app, seconds: float = 2.0) -> None:
    """Run the loop until the background analysis has landed."""
    import time
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.sendPostedEvents()
        app.processEvents()
        time.sleep(0.01)


def _window(app, width: int = 1600):
    from cycloidgen.ui.main_window import MainWindow
    w = MainWindow()
    w.resize(width, 950)
    w.show()
    _pump(app)
    return w


def _settings() -> QSettings:
    from cycloidgen.ui.settings import app_settings
    return app_settings()


# ------------------------------------------------------------------ appearance


def test_appearance_switches_chrome_and_plots_together(app):
    """A figure on a light surface inside a dark window is the bug that
    following the desktop theme was meant to prevent."""
    from cycloidgen.report import plots
    from cycloidgen.ui import branding
    w = _window(app)
    try:
        for choice in ("dark", "light"):
            w._choose_appearance(choice)
            assert w.mode == choice
            # the figure takes the tone of the panel it is sitting in
            assert plots.theme()["surface"] == branding.palette(choice).raised
    finally:
        w.close()
        plots.set_theme("light")


def test_following_the_system_can_return_to_light(app):
    """The desktop theme is read once, before any stylesheet of ours lands.

    Reading it later reads back what *we* painted, so "follow system" would
    answer dark forever once dark had been chosen.
    """
    w = _window(app)
    try:
        system = w._system_mode
        w._choose_appearance("dark")
        assert w.mode == "dark"
        w._choose_appearance("system")
        assert w.mode == system
    finally:
        w.close()


def test_the_appearance_menu_behaves_as_one_radio_group(app):
    w = _window(app)
    try:
        for choice in ("dark", "light", "system"):
            w._choose_appearance(choice)
            checked = [k for k, a in w._appearance_actions.items() if a.isChecked()]
            assert checked == [choice]
    finally:
        w.close()


def test_appearance_survives_a_restart(app):
    w = _window(app)
    w._choose_appearance("dark")
    w.close()
    _pump(app, 0.3)

    w2 = _window(app)
    try:
        assert w2.appearance == "dark"
        assert w2.mode == "dark"
    finally:
        w2._choose_appearance("system")
        w2.close()


# ------------------------------------------------------------------- workspace


def test_tab_and_crank_come_back(app):
    w = _window(app)
    w.tabs.setCurrentIndex(3)
    w._crank_slider.setValue(137)
    _pump(app, 0.3)
    w.close()
    _pump(app, 0.3)

    w2 = _window(app)
    try:
        assert w2.tabs.currentIndex() == 3
        assert w2._crank_slider.value() == 137
        assert w2._crank == 137.0
    finally:
        w2.close()


def test_the_crank_drives_both_simulations(app):
    """One control, two views.  If they can drift apart, they will."""
    w = _window(app)
    try:
        w.tabs.setCurrentIndex(w._drawing_tab)
        _pump(app, 0.2)
        w._crank_slider.setValue(64)
        _pump(app, 0.3)
        assert w._view3d.view._crank == 64.0
        assert w._profile_view._crank == 64.0
    finally:
        w.close()


def test_the_drawing_is_not_redrawn_while_nobody_is_looking(app):
    """A hidden Agg canvas still honours ``draw_idle``.

    That is a full render of a figure nobody can see, on every animation
    frame - so the drawing is left behind and catches up when its tab comes
    back.  The 3D view is updated either way because its update is a float and
    a repaint request Qt drops for a hidden widget.
    """
    w = _window(app)
    try:
        w.tabs.setCurrentIndex(w._drawing_tab)
        _pump(app, 0.2)
        w.tabs.setCurrentIndex(w._outputs_tab)
        w._crank_slider.setValue(150)
        _pump(app, 0.2)
        assert w._view3d.view._crank == 150.0
        assert w._profile_stale

        w.tabs.setCurrentIndex(w._drawing_tab)
        assert w._profile_view._crank == 150.0
        assert not w._profile_stale
    finally:
        w.close()


def test_a_headless_platform_gets_the_software_renderer(app):
    """The guard that keeps this whole file from crashing the interpreter.

    ``QVTKRenderWindowInteractor`` asks its widget for a native window handle
    and hands it to OpenGL.  The offscreen platform has none, so it does not
    raise - it takes the process down with an access violation, which no `try`
    can catch.  The platform has to be checked before anything is constructed.
    """
    from cycloidgen.ui import view3d, view3d_vtk
    assert not view3d_vtk.available()

    w = _window(app)
    try:
        assert isinstance(w._view3d.view, view3d.AssemblyView)
        assert not hasattr(w._view3d.view, "set_section")   # hardware only
    finally:
        w.close()


def test_macos_is_refused_the_hardware_renderer(monkeypatch):
    """Same class of failure as the headless one, and worse in its symptom.

    VTK's Python widget builds its context on the handle ``winId()`` returns
    with ``WA_PaintOnScreen`` set, which Qt documents as X11-only; macOS views
    are layer-backed and have been mandatorily so since 10.14.  The first render
    blocks the main thread as the tab opens and the application dies with it -
    so, as with the offscreen platform, this cannot be discovered by trying.

    The escape hatch has to keep working in both directions: it is how the
    proper macOS widget will be developed, and how a support question gets
    answered without a rebuild.
    """
    import sys

    from cycloidgen.ui import view3d_vtk

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("CYCLOIDGEN_VTK", raising=False)
    assert not view3d_vtk.available()

    monkeypatch.setenv("CYCLOIDGEN_VTK", "1")
    assert view3d_vtk.available() is view3d_vtk._importable()

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("CYCLOIDGEN_VTK", "0")
    assert not view3d_vtk.available()


def test_the_crank_bar_is_hidden_where_it_would_do_nothing(app):
    """A control that does nothing where it is shown teaches people to ignore it."""
    w = _window(app)
    try:
        for tab in (w._drawing_tab, w._solid_tab):
            w.tabs.setCurrentIndex(tab)
            assert w._crank_bar.isVisible()
        w.tabs.setCurrentIndex(w._outputs_tab)
        assert not w._crank_bar.isVisible()
    finally:
        w.close()


def test_the_viewpoint_and_the_overlays_survive_a_restart(app):
    w = _window(app)
    w._view3d.view.set_camera_angles(123.0, -17.0)
    w._view3d._explode.setValue(40)
    w._view3d._groups["housing"].setChecked(False)
    w._overlay_boxes["trace"].setChecked(True)
    _pump(app, 0.3)
    w.close()
    _pump(app, 0.3)

    w2 = _window(app)
    try:
        assert w2._view3d.view.camera.azimuth == pytest.approx(123.0)
        assert w2._view3d.view.camera.elevation == pytest.approx(-17.0)
        assert w2._view3d._explode.value() == 40
        assert not w2._view3d._groups["housing"].isChecked()
        assert w2._overlay_boxes["trace"].isChecked()
        assert w2._overlays().trace
    finally:
        w2._view3d._groups["housing"].setChecked(True)
        w2._overlay_boxes["trace"].setChecked(False)
        w2.close()


def test_the_outputs_tab_lists_what_an_export_would_write(app):
    """The tab is a preview, so it has to be right before anything is written."""
    from cycloidgen.export.manifest import planned_files
    w = _window(app)
    try:
        outputs = w._outputs
        expected = len(planned_files(w.spec, outputs.selected_groups()))
        leaves = 0
        for i in range(outputs.tree.topLevelItemCount()):
            group = outputs.tree.topLevelItem(i)
            for j in range(group.childCount()):
                entry = group.child(j)
                leaves += entry.childCount() or 1
        assert leaves == len(planned_files(w.spec))
        assert expected > 0
    finally:
        w.close()


def test_the_split_is_remembered_as_a_proportion(app):
    """Storing pixels would hand a narrower screen most of its width to the
    parameter panel."""
    w = _window(app, width=1600)
    total = sum(w._splitter.sizes())
    w._splitter.setSizes([round(0.40 * total), total - round(0.40 * total)])
    _pump(app, 0.3)
    w.close()
    _pump(app, 0.3)

    stored = float(_settings().value("splitter_fraction"))
    assert stored == pytest.approx(0.40, abs=0.02)

    w2 = _window(app, width=1600)
    try:
        sizes = w2._splitter.sizes()
        assert sizes[0] / sum(sizes) == pytest.approx(0.40, abs=0.02)
    finally:
        w2.close()


def test_a_nonsense_stored_split_is_ignored(app):
    """A value from an older build should cost a default, not a broken window."""
    _settings().setValue("splitter_fraction", "not a number")
    w = _window(app)
    try:
        assert sum(w._splitter.sizes()) > 0
        assert all(s >= 0 for s in w._splitter.sizes())
    finally:
        w.close()
        _settings().remove("splitter_fraction")


def test_an_out_of_range_split_is_ignored(app):
    _settings().setValue("splitter_fraction", 1.4)
    w = _window(app)
    try:
        sizes = w._splitter.sizes()
        assert sizes[1] > 0, "the view panel must not be collapsed away"
    finally:
        w.close()
        _settings().remove("splitter_fraction")


# ------------------------------------------------------------------ animation


def test_the_animation_follows_whichever_view_is_on_screen(app):
    """Exporting a view the user is not looking at only makes them do it twice."""
    w = _window(app)
    try:
        w.tabs.setCurrentIndex(w._drawing_tab)
        w._overlay_boxes["trace"].setChecked(True)
        plan, options = w._animation_request()
        assert plan.view == "drawing"
        assert options["overlays"].trace
        assert options["theme"] == w.mode          # what you are looking at

        w.tabs.setCurrentIndex(w._solid_tab)
        w._view3d.view.set_camera_angles(77.0, 12.0)
        w._view3d._explode.setValue(30)
        w._view3d._groups["housing"].setChecked(False)
        plan, options = w._animation_request()
        assert plan.view == "assembly"
        assert options["azimuth"] == pytest.approx(77.0)
        assert options["elevation"] == pytest.approx(12.0)
        assert options["explode"] == pytest.approx(0.30)
        # The end plates start switched off, so what an animation leaves out is
        # whatever the tab is leaving out - not only what was clicked here.
        assert "housing" in options["hidden"]
        assert options["hidden"] == frozenset(w._view3d._hidden())
    finally:
        w._overlay_boxes["trace"].setChecked(False)
        w._view3d._groups["housing"].setChecked(True)
        w._view3d._explode.setValue(0)
        w.close()


def _run_worker(w, target, plan, cancel_at=None):
    """Drive the worker on this thread; ``run`` needs no event loop."""
    from cycloidgen.ui.main_window import AnimationWorker

    worker = AnimationWorker(w.spec.model_copy(deep=True), target, plan,
                             {"theme": "print"})
    seen, done, failed = [], [], []
    worker.progressed.connect(lambda i, n: seen.append(i))
    worker.done.connect(done.append)
    worker.failed.connect(failed.append)
    if cancel_at is not None:
        worker.progressed.connect(
            lambda i, _n: worker.cancel() if i == cancel_at else None)
    worker.run()
    return seen, done, failed


def test_the_animation_worker_reports_every_frame_and_the_file(app, tmp_path):
    from cycloidgen.export import animation

    w = _window(app)
    try:
        target = tmp_path / "motion.gif"
        plan = animation.plan(w.spec, pixels=120, frames=6)
        seen, done, failed = _run_worker(w, target, plan)
        assert seen == [1, 2, 3, 4, 5, 6]
        assert done == [str(target)] and not failed
        assert target.stat().st_size > 0
    finally:
        w.close()


def test_a_cancelled_animation_leaves_no_half_written_file(app, tmp_path):
    """Cancel has to mean nothing on disk, not a GIF that stops half way."""
    from cycloidgen.export import animation

    w = _window(app)
    try:
        target = tmp_path / "cancelled.gif"
        plan = animation.plan(w.spec, pixels=120, frames=40)
        seen, done, failed = _run_worker(w, target, plan, cancel_at=3)
        assert len(seen) < 40 and not done
        assert failed == [""]                      # cancelled, not broken
        assert not target.exists()
    finally:
        w.close()


# --------------------------------------------------------------------- filter


def test_the_filter_toggles_carry_counts(app):
    w = _window(app)
    try:
        labels = [b.text() for b in w._severity_filters.values()]
        assert any(t.startswith("Errors (") for t in labels)
        assert any(t.startswith("Warnings (") for t in labels)
        assert any(t.startswith("Notes (") for t in labels)
    finally:
        w.close()


def _visible(w) -> int:
    return sum(1 for i in range(w.findings.topLevelItemCount())
               if not w.findings.topLevelItem(i).isHidden())


def test_unchecking_a_severity_hides_only_that_severity(app):
    w = _window(app)
    try:
        total = w.findings.topLevelItemCount()
        assert _visible(w) == total

        w._severity_filters[Severity.INFO].setChecked(False)
        _pump(app, 0.2)
        assert _visible(w) < total
        # and nothing but notes went away
        for i in range(total):
            item = w.findings.topLevelItem(i)
            if item.isHidden():
                assert Severity(item.data(1, _USER_ROLE)) is Severity.INFO
        assert "showing" in w._findings_summary.text()

        w._severity_filters[Severity.INFO].setChecked(True)
        _pump(app, 0.2)
        assert _visible(w) == total
        assert w._findings_summary.text() == ""
    finally:
        w.close()


def test_the_filter_survives_a_restart(app):
    w = _window(app)
    w._severity_filters[Severity.INFO].setChecked(False)
    _pump(app, 0.2)
    w.close()
    _pump(app, 0.3)

    w2 = _window(app)
    try:
        assert not w2._severity_filters[Severity.INFO].isChecked()
        assert w2._severity_filters[Severity.ERROR].isChecked()
    finally:
        w2._severity_filters[Severity.INFO].setChecked(True)
        w2.close()


def test_hiding_the_selected_finding_clears_the_selection(app):
    """Otherwise the parameter highlight keeps pointing at an invisible row."""
    w = _window(app)
    try:
        for i in range(w.findings.topLevelItemCount()):
            item = w.findings.topLevelItem(i)
            stored = item.data(1, _USER_ROLE)
            if stored is not None and Severity(stored) is Severity.INFO:
                w.findings.setCurrentItem(item)
                break
        else:
            pytest.skip("this design produced no INFO findings")

        w._severity_filters[Severity.INFO].setChecked(False)
        _pump(app, 0.2)
        assert w.findings.currentItem() is None
    finally:
        w._severity_filters[Severity.INFO].setChecked(True)
        w.close()


# --------------------------------------------------------------------- chrome


def test_the_checks_list_cannot_be_squeezed_out_of_existence(app):
    """The stage is a tab widget whose pages ask for hundreds of pixels each.

    On a window that is merely a bit short the layout pays for them out of the
    only widget that will yield, and the checks list goes to zero - taking the
    answer to "is anything wrong with this design" with it, quietly, with no
    scrollbar to notice.
    """
    from cycloidgen.ui.main_window import _MIN_CHECKS_PX

    w = _window(app)
    try:
        w.resize(1100, 620)                       # deliberately cramped
        _pump(app, 0.4)
        assert w._checks_panel.height() >= _MIN_CHECKS_PX
        assert w._view_split.sizes()[1] >= _MIN_CHECKS_PX
    finally:
        w.close()


def test_the_checks_split_is_remembered(app):
    w = _window(app)
    total = sum(w._view_split.sizes())
    w._view_split.setSizes([round(0.55 * total), total - round(0.55 * total)])
    _pump(app, 0.3)
    w.close()
    _pump(app, 0.3)

    assert float(_settings().value("checks_fraction")) == pytest.approx(0.55, abs=0.03)
    w2 = _window(app)
    try:
        sizes = w2._view_split.sizes()
        assert sizes[0] / sum(sizes) == pytest.approx(0.55, abs=0.03)
    finally:
        w2.close()
        _settings().remove("checks_fraction")


def test_the_3d_view_is_themed_before_it_is_ever_shown(app):
    """It paints its own background, so a stylesheet does not reach it.

    Nothing told it the mode until the appearance was *changed*, which meant
    opening in dark mode gave a white viewport in a dark window.
    """
    w = _window(app)
    try:
        w._choose_appearance("dark")
        _pump(app, 0.3)
        assert w._view3d.view._mode == "dark"
    finally:
        w._choose_appearance("light")
        w.close()

    w2 = _window(app)                             # a fresh window, dark stored
    try:
        assert w2._view3d.view._mode == w2.mode
    finally:
        w2.close()


def test_the_plot_toolbar_carries_only_the_tools_that_apply(app):
    """Subplots and Customize can only make the picture disagree with the
    numbers beside it; Back and Forward walk a history a single-axes drawing
    barely has."""
    w = _window(app)
    try:
        assert [a.text() for a in w._plot_bar.actions() if a.text()] == \
            ["Home", "Pan", "Zoom", "Save"]
    finally:
        w.close()


def test_the_toolbar_icons_take_the_ink_of_the_theme(app):
    """matplotlib picks light or dark artwork off a QPalette that, under an
    application stylesheet, is not ours - it read black for every role and drew
    white icons onto the light theme's paper."""
    from cycloidgen.ui import branding

    w = _window(app)
    try:
        for mode in ("light", "dark"):
            w._choose_appearance(mode)
            _pump(app, 0.2)
            icon = next(a.icon() for a in w._plot_bar.actions()
                        if a.text() == "Home")
            image = icon.pixmap(24, 24).toImage()
            opaque = [image.pixelColor(x, y)
                      for x in range(image.width()) for y in range(image.height())
                      if image.pixelColor(x, y).alpha() > 200]
            assert opaque, "the icon rendered empty"
            # Within a step of the ink: compositing the tint through the
            # artwork's own alpha is what keeps the edges smooth, and it costs
            # a rounding unit on the channels.
            want = QColor(branding.palette(mode).ink)
            worst = max(max(abs(c.red() - want.red()),
                            abs(c.green() - want.green()),
                            abs(c.blue() - want.blue())) for c in opaque)
            assert worst <= 3, f"{mode}: icon ink is {worst} off"
    finally:
        w._choose_appearance("system")
        w.close()


def test_selecting_a_check_says_what_it_tests_and_what_to_change(app):
    """Highlighting the parameters says *where* to look and nothing about why."""
    from cycloidgen.core.explain import explain

    w = _window(app)
    try:
        assert "Select a check" in w._explain.toPlainText()

        chosen = None
        for i in range(w.findings.topLevelItemCount()):
            item = w.findings.topLevelItem(i)
            if item.data(0, _USER_ROLE):
                w.findings.setCurrentItem(item)
                chosen = item.data(0, _USER_ROLE)
                break
        assert chosen, "this design produced no findings to select"
        _pump(app, 0.2)

        shown = w._explain.toPlainText()
        detail = explain(chosen)
        assert chosen in shown                       # the code
        assert detail.title in shown
        assert detail.tests.split("\n")[0][:24] in shown
        assert detail.fix[:40] in shown
        assert w._highlighted, "the parameters should still be highlighted"
    finally:
        w.close()


def test_the_explanation_is_rebuilt_when_the_appearance_changes(app):
    """Its colours are baked into the markup, like every figure's are."""
    w = _window(app)
    try:
        for i in range(w.findings.topLevelItemCount()):
            item = w.findings.topLevelItem(i)
            if item.data(0, _USER_ROLE):
                w.findings.setCurrentItem(item)
                break
        w._choose_appearance("dark")
        _pump(app, 0.2)
        dark = w._explain.toHtml()
        w._choose_appearance("light")
        _pump(app, 0.2)
        light = w._explain.toHtml()
        assert dark != light
        from cycloidgen.ui import branding
        assert branding.palette("light").ink.lstrip("#") in light.lower()
    finally:
        w._choose_appearance("system")
        w.close()


# ---------------------------------------------------------------------- units


def test_switching_units_changes_the_view_and_not_the_design(app):
    """The trap this is really guarding.

    Narrowing a spin box's range makes Qt clamp whatever is in it, and a clamp
    emits ``valueChanged`` like any other edit - so switching to inches would
    find a 50 mm pin circle outside the new 0.197-19.685 range, pin it to the
    top and write 500 mm back into the design.  The drive would silently become
    a different drive for having been looked at in another unit.
    """
    w = _window(app)
    try:
        before = w.spec.model_dump_json()
        field = w._widgets["pin_circle_radius"]
        assert field.suffix() == " mm"

        w._choose_units("in")
        _pump(app, 0.3)
        assert field.suffix() == " in"
        # to within the field's own last place: it shows four decimals in
        # inches, and rounding the display is the whole point of the extra two
        assert field.value() == pytest.approx(50.0 / 25.4, abs=5e-5)
        assert w.spec.model_dump_json() == before

        # and back and forth, because a rounding drift shows up on repetition
        for _ in range(8):
            w._choose_units("mm")
            w._choose_units("in")
        w._choose_units("mm")
        _pump(app, 0.3)
        assert w.spec.model_dump_json() == before
    finally:
        w._choose_units("mm")
        w.close()


def test_an_edit_made_in_inches_is_stored_in_millimetres(app):
    w = _window(app)
    try:
        w._choose_units("in")
        _pump(app, 0.2)
        w._widgets["pin_circle_radius"].setValue(2.0)
        _pump(app, 0.3)
        assert w.spec.pin_circle_radius == pytest.approx(50.8)
    finally:
        w._choose_units("mm")
        w.close()


def test_the_clearances_keep_their_precision_in_inches(app):
    """0.22 mm is 0.00866 in. At the millimetre field's three decimals that
    rounds to 0.009, which is a 4% change in the quantity."""
    w = _window(app)
    try:
        w._choose_units("in")
        _pump(app, 0.2)
        clearance = w._widgets["profile_clearance"]
        assert clearance.decimals() == 5
        assert clearance.value() == pytest.approx(0.22 / 25.4, abs=5e-6)
    finally:
        w._choose_units("mm")
        w.close()


def test_the_readouts_follow_the_preference(app):
    w = _window(app)
    try:
        w._choose_units("in")
        _pump(app, 0.4)
        assert w._stats["od"].text().endswith(" in")
        assert w._stats["length"].text().endswith(" in")
        for i in range(w.findings.topLevelItemCount()):
            item = w.findings.topLevelItem(i)
            if item.data(0, _USER_ROLE) == "LOST_MOTION":
                # arcmin is not a length and must not have been converted
                assert float(item.text(3)) == pytest.approx(60.0)
    finally:
        w._choose_units("mm")
        w.close()


def test_the_unit_preference_survives_a_restart(app):
    w = _window(app)
    w._choose_units("in")
    _pump(app, 0.3)
    w.close()
    _pump(app, 0.3)

    w2 = _window(app)
    try:
        assert w2._unit.key == "in"
        assert w2._widgets["pin_circle_radius"].suffix() == " in"
    finally:
        w2._choose_units("mm")
        w2.close()


def test_the_preset_box_says_which_preset_this_actually_is(app):
    """It is read as much as it is used.  A chooser still claiming 15:1 over a
    21:1 design is not a small lie, and matching on the ratio alone would be the
    same lie one step quieter: a 21:1 with its pin radius changed is no longer
    the 21:1 preset."""
    from cycloidgen.core.spec import preset

    w = _window(app)
    try:
        # Start from a known preset: the window reopens on whatever design the
        # last session left, which is quite properly Custom more often than not.
        w._replace_spec(preset(15))
        _pump(app, 0.3)
        assert w._preset_box.currentText() == "15:1"

        w._replace_spec(preset(29))
        _pump(app, 0.3)
        assert w._preset_box.currentText() == "29:1"

        w._widgets["pin_radius"].setValue(w.spec.pin_radius + 0.5)
        _pump(app, 0.3)
        assert w._preset_box.currentText() == "Custom"

        # and choosing Custom does nothing rather than loading a preset
        before = w.spec.model_dump_json()
        w._preset_box.setCurrentIndex(0)
        w._apply_preset()
        _pump(app, 0.2)
        assert w.spec.model_dump_json() == before
    finally:
        w.close()


# ---------------------------------------------------------------- provenance


def test_a_saved_design_is_stamped_and_reopens_without_a_word(app, tmp_path,
                                                              monkeypatch):
    """The version goes in on save, and a file from *this* build says nothing.

    A warning that fires on the file you saved a minute ago is a warning people
    switch off.
    """
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    import cycloidgen
    from cycloidgen.core.spec import preset

    path = tmp_path / "design.json"
    said: list[str] = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(path), "")))
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(path), "")))
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: said.append(a[-1])))

    w = _window(app)
    try:
        w._replace_spec(preset(29))
        _pump(app, 0.3)
        w._save_spec()

        written = json.loads(path.read_text(encoding="utf-8"))
        assert written["version"] == cycloidgen.__version__
        assert written["spec"]["lobes"] == preset(29).lobes

        w._replace_spec(preset(15))
        _pump(app, 0.3)
        w._open_spec()
        _pump(app, 0.3)
        assert w.spec == preset(29)
        assert said == []
    finally:
        w.close()


def test_a_design_from_another_build_says_so_before_it_is_acted_on(app, tmp_path,
                                                                   monkeypatch):
    """Including one saved before files carried a version at all - which is
    every design anybody has saved from this app so far."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from cycloidgen.core.spec import preset

    path = tmp_path / "old.json"
    path.write_text(preset(21).model_dump_json(indent=2), encoding="utf-8")

    said: list[str] = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(path), "")))
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: said.append(a[-1])))

    w = _window(app)
    try:
        w._open_spec()
        _pump(app, 0.3)
        # It loads - the warning is about the numbers, not about the file
        assert w.spec == preset(21)
        assert len(said) == 1
        assert "may have moved" in said[0]
    finally:
        w.close()


def test_an_upgrade_between_sessions_is_reported_on_the_status_bar(app):
    """The dangerous case with nobody to ask: close 6.0, install 6.1, and the
    design that reopens is the one numbers were written down from."""
    from cycloidgen.core.spec import preset

    settings = _settings()
    settings.setValue("last_design", preset(29).model_dump_json())
    settings.setValue("last_design_version", "1.0.0")
    settings.sync()

    w = _window(app)
    try:
        assert w.spec == preset(29)
        assert "1.0.0" in w.statusBar().currentMessage()
    finally:
        w.close()
        settings.remove("last_design")
        settings.remove("last_design_version")
        settings.sync()


# ------------------------------------------------------------- reading surface


def test_every_number_in_the_header_says_what_it_is(app):
    """The strip used to be eight bare values - ``0.73 Nm  71%  98'  52 C``.

    A summary with no captions is one only the person who wrote it can read,
    and two of those are units that appear nowhere else on screen.
    """
    from cycloidgen.ui.main_window import _HEADER_STATS

    w = _window(app)
    try:
        assert len(w._stats) == len(_HEADER_STATS)
        for key, caption, tip in _HEADER_STATS:
            value = w._stats[key]
            assert value.text() not in ("", "-"), key
            cell = value.parent()
            captions = [c.text() for c in cell.findChildren(type(value))]
            assert caption in captions, key
            assert cell.toolTip() == tip, key
    finally:
        w.close()


def test_the_strip_follows_the_design(app):
    from cycloidgen.core.spec import preset

    w = _window(app)
    try:
        w._replace_spec(preset(29))
        _pump(app, 1.5)
        assert w._stats["ratio"].text() == "29:1"
        assert w._stats["mass"].text().endswith(" g")
        assert w._stats["efficiency"].text().endswith("%")
    finally:
        w.close()


def test_only_the_two_numbers_with_a_limit_are_ever_coloured(app):
    """Capacity against the torque this design is rated for, temperature
    against what its own materials allow.  Colouring the rest would mean
    inventing thresholds here that nothing else in the app agrees with."""
    from cycloidgen.core.spec import preset

    w = _window(app)
    try:
        # The 15:1 preset is rated for far more than it can carry, so capacity
        # is the one that should be flagged out of the box.
        w._replace_spec(preset(15))
        _pump(app, 1.5)
        assert w.analysis is not None
        capacity = w.analysis.torque_capacity_with_clearance_Nm
        assert capacity < w.spec.output_torque_Nm, "this test needs a short design"
        assert w._stats["capacity"].property("state") == "warning"

        # Ask it for a torque it can actually deliver and the flag clears.
        spec = w.spec.model_copy(deep=True)
        spec.output_torque_Nm = capacity / 2
        w._replace_spec(spec)
        _pump(app, 1.5)
        assert w._stats["capacity"].property("state") in ("", None)

        never = ("ratio", "od", "length", "mass", "efficiency", "backlash")
        assert all(w._stats[k].property("state") in ("", None) for k in never)
    finally:
        w.close()


def test_a_finding_is_readable_without_being_clicked(app):
    """The detail is a sentence, and it used to be a sentence with its end cut
    off - so the list was a set of codes you opened one at a time."""
    from PySide6.QtGui import QFontMetrics

    w = _window(app)
    try:
        _pump(app, 1.0)
        tree = w.findings
        assert tree.topLevelItemCount() > 0
        line = QFontMetrics(tree.font()).height()

        long_rows = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
                     if len(tree.topLevelItem(i).text(4)) > 90]
        assert long_rows, "no finding long enough to need wrapping"
        for item in long_rows:
            if item.isHidden():
                continue
            height = tree.visualItemRect(item).height()
            assert height > line * 1.5, (
                f"{item.text(1)} is {height} px tall for "
                f"{len(item.text(4))} characters - it is still on one line")
    finally:
        w.close()


def _narrow_until(app, w, hidden) -> int:
    """Shrink the window until ``hidden()`` goes true, and say where it did.

    Written as a search rather than as two magic widths, because the width at
    which either of these gives up is a *font* measurement - and the offscreen
    platform this file runs on has no fonts, so its idea of how wide the strip
    and the columns are is nothing like a real desktop's.  What is being tested
    is the order things yield in, which is the same on both.
    """
    width = 1900
    w.resize(width, 850)
    _pump(app, 0.4)
    while width > w.minimumWidth() + 40 and not hidden():
        width -= 100
        w.resize(width, 850)
        _pump(app, 0.25)
    return width


def test_the_explanation_panel_yields_to_the_list_on_a_narrow_window(app):
    """They are not equals: the list answers "is anything wrong with this",
    and the panel is a detail view of one row of it.  The layout's own answer
    to running out of width is to squeeze the detail column to nothing, which
    is the one arrangement where neither of them is any use."""
    from cycloidgen.ui.main_window import _DETAIL_COL, _MIN_DETAIL_PX

    w = _window(app, width=1900)
    try:
        assert w._explain.isVisible()
        _narrow_until(app, w, lambda: not w._explain.isVisible())
        assert not w._explain.isVisible(), \
            "the panel never yields, however narrow the window gets"
        # and the list keeps a readable detail rather than pushing it off the
        # side behind a horizontal scrollbar
        assert w.findings.columnWidth(_DETAIL_COL) >= _MIN_DETAIL_PX

        w.resize(1900, 950)
        _pump(app, 0.6)
        assert w._explain.isVisible()
    finally:
        w.close()
