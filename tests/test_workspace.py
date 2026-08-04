"""Appearance, workspace persistence and the checks filter.

These exercise the real window, so they need Qt and run headless.  Settings are
redirected into a temporary directory: a test suite that writes to the user's
actual preferences would silently rearrange their application.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
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
        assert options["hidden"] == {"housing"}
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
