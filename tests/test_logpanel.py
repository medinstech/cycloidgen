"""The in-app log.

Needs a QApplication, so it runs headless.  Worth the fragility: this panel is
the only place a GUI user can see a worker-thread traceback, and if it silently
stops collecting nobody finds out until something has already gone wrong.
"""
from __future__ import annotations

import logging
import os
import sys
import warnings

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cycloidgen.ui.logpanel import LogPanel, install, logger


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(app):
    p = LogPanel()
    handler = p.handler()
    logger.addHandler(handler)
    previous = logger.level, logger.propagate
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    yield p
    logger.removeHandler(handler)
    logger.setLevel(previous[0])
    logger.propagate = previous[1]


def _pump(app, times: int = 3) -> None:
    """The handler crosses threads through a queued signal, so let Qt deliver."""
    for _ in range(times):
        app.sendPostedEvents()
        app.processEvents()


def test_records_reach_the_panel(app, panel):
    logger.info("hello %s", "world")
    _pump(app)
    assert "hello world" in panel.text()
    assert "INFO" in panel.text()


def test_counts_split_errors_from_warnings(app, panel):
    logger.warning("careful")
    logger.error("broken")
    logger.error("also broken")
    _pump(app)
    assert panel.warnings == 1
    assert panel.errors == 2


def test_the_level_filter_hides_and_restores_without_losing_anything(app, panel):
    logger.info("chatter")
    logger.error("the actual problem")
    _pump(app)
    assert "chatter" in panel.text()

    panel._set_threshold("ERROR")
    assert "chatter" not in panel.text()
    assert "the actual problem" in panel.text()

    panel._set_threshold("INFO")             # filtering must not discard records
    assert "chatter" in panel.text()


def test_a_traceback_keeps_its_shape(app, panel):
    try:
        raise ValueError("deliberate")
    except ValueError:
        logger.error("it failed\n%s", "Traceback:\n  line one\n  line two")
    _pump(app)
    text = panel.text()
    assert "it failed" in text
    assert "line one" in text and "line two" in text


def test_problem_signal_fires_only_above_info(app, panel):
    seen: list[str] = []
    panel.problem.connect(seen.append)
    logger.info("fine")
    _pump(app)
    assert seen == []
    logger.warning("not fine")
    logger.error("worse")
    _pump(app)
    assert seen == ["WARNING", "ERROR"]


def test_clear_resets_the_counters(app, panel):
    logger.error("boom")
    _pump(app)
    panel.clear()
    assert panel.text() == ""
    assert panel.errors == 0 and panel.warnings == 0


def test_install_captures_warnings_and_stderr(app):
    p = LogPanel()
    original_stderr = sys.stderr
    original_showwarning = warnings.showwarning
    original_hook = sys.excepthook
    try:
        install(p)
        warnings.warn("a library grumbling", stacklevel=1)
        sys.stderr.write("something wrote to stderr\n")
        _pump(app)
        text = p.text()
        assert "a library grumbling" in text
        assert "something wrote to stderr" in text
    finally:
        sys.stderr = original_stderr
        warnings.showwarning = original_showwarning
        sys.excepthook = original_hook
        for h in list(logger.handlers):
            logger.removeHandler(h)


def test_the_stderr_tee_still_writes_to_the_real_stream(app):
    """Mirroring stderr must not swallow it - the CLI still needs it."""
    import io

    from cycloidgen.ui.logpanel import _StderrTee

    p = LogPanel()
    sink = io.StringIO()
    tee = _StderrTee(sink, p.bridge())
    tee.write("passed through\n")
    _pump(app)
    assert sink.getvalue() == "passed through\n"
    assert "passed through" in p.text()


def test_the_panel_is_bounded(app, panel):
    from cycloidgen.ui.logpanel import _MAX_LINES
    for i in range(_MAX_LINES * 2 + 200):
        panel._append("INFO", "00:00:00", f"line {i}")
    assert len(panel._records) <= _MAX_LINES * 2
    assert panel._view.blockCount() <= _MAX_LINES + 1
