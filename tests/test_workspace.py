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
    w = _window(app)
    try:
        w._choose_appearance("dark")
        assert w.mode == "dark"
        assert plots.theme()["surface"] == "#1a1a19"

        w._choose_appearance("light")
        assert w.mode == "light"
        assert plots.theme()["surface"] == "#fcfcfb"
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
