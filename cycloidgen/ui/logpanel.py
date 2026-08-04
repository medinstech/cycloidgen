"""Everything the app would otherwise print where nobody is looking.

A desktop user has no terminal.  Until now the app's diagnostics went three
different places and two of them were invisible: transient status-bar messages
that vanish after four seconds, modal dialogs for export failures, and plain
stderr for everything else - warnings from matplotlib, OCCT complaints, and any
exception raised on a worker thread, none of which reach the window at all.

This collects all of it in one place, in order, with timestamps, and keeps it.

Threading
---------
The analysis, export, optimiser and sweep all run on their own threads and all
log from there.  A ``logging.Handler`` must therefore never touch a widget
directly, so records cross into the GUI thread through a Qt signal, which Qt
queues for us.  Writing to the text box from a worker thread would eventually
corrupt it in ways that look like anything but the real cause.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import logging
import sys
import traceback
import warnings

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import branding

__all__ = ["LogPanel", "install", "logger"]

#: The application's own logger.  Library loggers are left alone; their noise
#: arrives through the stderr tee instead.
logger = logging.getLogger("cycloidgen")

_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


def _colours(mode: str) -> dict[str, str]:
    """Level ink for the current surface.

    Hard-coding these was a mistake worth naming: the light-surface INFO grey is
    ``#52514e``, which on the dark surface is 1.6:1 against the background.  The
    whole point of this panel is that it can be read.
    """
    from .branding import palette

    p = palette(mode)
    return {"DEBUG": p.ink_dim if p.is_dark else "#8a8a84",
            "INFO": p.ink if p.is_dark else p.ink_dim,
            "WARNING": p.warning,
            "ERROR": p.error,
            "CRITICAL": p.error}

#: Lines kept before the oldest are dropped.  A long optimiser run can produce
#: thousands; an unbounded box would quietly grow forever.
_MAX_LINES = 5000


class _Bridge(QObject):
    """Carries records from whatever thread produced them into the GUI thread."""

    message = Signal(str, str, str)          # level, timestamp, text


class _Handler(logging.Handler):
    def __init__(self, bridge: _Bridge) -> None:
        super().__init__()
        self._bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        try:
            stamp = _dt.datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
            self._bridge.message.emit(record.levelname, stamp, self.format(record))
        except Exception:                    # a broken logger must not kill the app
            pass


class _StderrTee:
    """Mirrors stderr into the panel while leaving the real stream alone.

    Deliberately not routed through ``logging``: the root logger may well have a
    stderr handler of its own, and feeding stderr back into it is an infinite
    loop that presents as a hang.
    """

    def __init__(self, original, bridge: _Bridge) -> None:
        self._original = original
        self._bridge = bridge
        self._buffer = ""

    def write(self, text: str) -> int:
        if self._original is not None:
            with contextlib.suppress(Exception):
                self._original.write(text)
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                stamp = _dt.datetime.now().strftime("%H:%M:%S")
                self._bridge.message.emit("WARNING", stamp, line.rstrip())
        return len(text)

    def flush(self) -> None:
        if self._original is not None:
            with contextlib.suppress(Exception):
                self._original.flush()

    def isatty(self) -> bool:
        return False


class LogPanel(QWidget):
    """Read-only log view with a level filter and a way to get the text out."""

    #: Raised when something at or above WARNING arrives, so the window can put
    #: a marker on the tab of a panel the user is not currently looking at.
    problem = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._records: list[tuple[str, str, str]] = []
        self._threshold = "INFO"
        self._mode = "light"
        self._colours = _colours(self._mode)
        self.errors = 0
        self.warnings = 0

        layout = QVBoxLayout(self)
        layout.addLayout(self._build_controls())

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(_MAX_LINES)
        self._view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._view.setFont(branding.mono_font(9))
        layout.addWidget(self._view, 1)

        self._summary = QLabel("Nothing logged yet.")
        layout.addWidget(self._summary)

        self._bridge = _Bridge()
        self._bridge.message.connect(self._append, Qt.QueuedConnection)

    # ------------------------------------------------------------------ build
    def _build_controls(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Show"))
        self._level = QComboBox()
        self._level.addItems(_LEVELS)
        self._level.setCurrentText("INFO")
        self._level.currentTextChanged.connect(self._set_threshold)
        row.addWidget(self._level)

        self._follow = QCheckBox("Follow")
        self._follow.setChecked(True)
        self._follow.setToolTip("Scroll to the newest line as it arrives.")
        row.addWidget(self._follow)
        row.addStretch(1)

        for text, slot, tip in (
            ("Copy", self._copy, "Copy the visible log to the clipboard"),
            ("Save...", self._save, "Write the visible log to a file"),
            ("Clear", self.clear, "Empty the log"),
        ):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            row.addWidget(button)
        return row

    # ------------------------------------------------------------------ input
    def handler(self) -> logging.Handler:
        """A logging handler that feeds this panel."""
        handler = _Handler(self._bridge)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.setLevel(logging.DEBUG)
        return handler

    def bridge(self) -> _Bridge:
        return self._bridge

    def _append(self, level: str, stamp: str, text: str) -> None:
        self._records.append((level, stamp, text))
        if len(self._records) > _MAX_LINES * 2:
            del self._records[:_MAX_LINES]
        if level == "ERROR" or level == "CRITICAL":
            self.errors += 1
        elif level == "WARNING":
            self.warnings += 1
        if _LEVELS.index(self._threshold) <= _rank(level):
            self._write(level, stamp, text)
        self._summary.setText(
            f"{len(self._records)} entries - {self.errors} error(s), "
            f"{self.warnings} warning(s)")
        if _rank(level) >= _LEVELS.index("WARNING"):
            self.problem.emit(level)

    def _write(self, level: str, stamp: str, text: str) -> None:
        colour = QColor(self._colours.get(level, self._colours["INFO"]))
        cursor = self._view.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = cursor.charFormat()
        fmt.setForeground(colour)
        cursor.setCharFormat(fmt)
        for i, line in enumerate(text.splitlines() or [""]):
            prefix = f"{stamp}  {level:<7} " if i == 0 else " " * 18
            cursor.insertText(f"{prefix}{line}\n")
        if self._follow.isChecked():
            self._view.verticalScrollBar().setValue(
                self._view.verticalScrollBar().maximum())

    # ----------------------------------------------------------------- output
    def _set_threshold(self, level: str) -> None:
        self._threshold = level
        self._rebuild()

    def _rebuild(self) -> None:
        self._view.clear()
        floor = _LEVELS.index(self._threshold)
        for level, stamp, text in self._records:
            if _rank(level) >= floor:
                self._write(level, stamp, text)

    def set_theme(self, mode: str) -> None:
        """Re-ink the log for a new surface, keeping every record."""
        if mode == self._mode:
            return
        self._mode = mode
        self._colours = _colours(mode)
        self._rebuild()

    def text(self) -> str:
        return self._view.toPlainText()

    def _copy(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.text())
        logger.info("log copied to the clipboard")

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save log", "cycloidgen.log",
                                              "Log files (*.log *.txt)")
        if path:
            from pathlib import Path
            Path(path).write_text(self.text(), encoding="utf-8")
            logger.info("log written to %s", path)

    def clear(self) -> None:
        self._records.clear()
        self.errors = self.warnings = 0
        self._view.clear()
        self._summary.setText("Nothing logged yet.")


def _rank(level: str) -> int:
    try:
        return _LEVELS.index(level)
    except ValueError:                       # CRITICAL and anything custom
        return len(_LEVELS) - 1


def install(panel: LogPanel, *, capture_stderr: bool = True) -> None:
    """Route the app's diagnostics into ``panel``.

    Also catches the two things that otherwise disappear silently in a GUI: a
    warning raised anywhere in the process, and an exception that escapes a
    worker thread.
    """
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for existing in list(logger.handlers):
        logger.removeHandler(existing)
    logger.addHandler(panel.handler())

    def show_warning(message, category, filename, lineno, file=None, line=None):
        logger.warning("%s: %s  (%s:%s)", category.__name__, message,
                       filename, lineno)

    warnings.showwarning = show_warning

    def excepthook(kind, value, tb):
        logger.error("unhandled %s: %s\n%s", kind.__name__, value,
                     "".join(traceback.format_exception(kind, value, tb)).rstrip())

    sys.excepthook = excepthook

    import threading

    def thread_excepthook(args):
        logger.error("unhandled %s on thread %s: %s\n%s",
                     args.exc_type.__name__,
                     getattr(args.thread, "name", "?"), args.exc_value,
                     "".join(traceback.format_exception(
                         args.exc_type, args.exc_value,
                         args.exc_traceback)).rstrip())

    threading.excepthook = thread_excepthook

    if capture_stderr and sys.stderr is not None:
        sys.stderr = _StderrTee(sys.stderr, panel.bridge())
