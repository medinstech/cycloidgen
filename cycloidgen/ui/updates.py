"""Asking the user about updates, and doing the part they say yes to.

:mod:`cycloidgen.update` knows how to find out whether there is a newer version
and how to fetch it.  This is the half that decides *when* to ask, what to show,
and what a "no" means - which is the half where the mistakes are made.

The shape of it, and the reasoning:

**Consent before the first request, not a setting to find afterwards.**  A
desktop tool that phones home the first time it is opened, and offers an opt-out
in a menu the user has not read yet, has already done the thing they might have
objected to.  So the first run asks, in plain words, once.  Until it is answered
nothing is sent, and the answer is a preference like any other - Help ▸ Check
for updates automatically flips it either way for as long as the install lives.

**A "no" that is remembered.**  Three of them, and they are different questions.
*Not now* asks again tomorrow.  *Skip this version* means this particular release
is not wanted and nothing more is said about it until a newer one appears.  Off
means stop asking entirely.  A prompt that cannot be dismissed permanently is a
prompt people learn to click through, and then the one that matters goes the
same way.

**Quiet when it was not asked for, loud when it was.**  The daily background
check says nothing unless there is something to say: no dialog for "you are up
to date", none for a request that failed, because the user did not ask and a
failure they did not cause is not their problem.  The menu entry is the opposite
- it reports every outcome, failures included, because a check that was asked
for and answers with nothing is indistinguishable from one that is not wired up.

Nothing here reaches into the window.  What this needs from it - a line on the
status bar, a link opened, the application closed - goes out as a signal, the
same way :class:`~cycloidgen.ui.outputs.OutputsTab` asks for an export.  The
Help menu entries are built here too, so the window adds them and is not also
responsible for keeping the checkmark honest.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, update
from ..update import Asset, Cancelled, Release, UpdateError
from .logpanel import logger
from .settings import app_settings

__all__ = ["CHECKED_KEY", "MODE_KEY", "SKIPPED_KEY", "UpdateDialog",
           "Updater", "unattended"]

#: Preference keys.  Flat and prefixed, like every other key this application
#: stores - see :mod:`cycloidgen.ui.settings`.
MODE_KEY = "update_check"          # "" (never asked), "on" or "off"
CHECKED_KEY = "update_checked"     # when the last check actually reached GitHub
SKIPPED_KEY = "update_skipped"     # a version the user asked not to hear about

#: How often the background check runs.  Once a day: releases here are weeks
#: apart, and the only thing a shorter interval buys is a larger share of an
#: hourly rate limit shared by everyone behind the same address.
INTERVAL = timedelta(days=1)

#: Long enough after the window appears that the first paint is done and the
#: user has the application in front of them rather than a busy cursor.  The
#: request runs on a thread either way; this is about not competing with
#: start-up for the disk and the interpreter.
STARTUP_DELAY_MS = 4000

#: The notes are a changelog section and can run long.  Roughly two screens of
#: the dialog, after which the release page has the rest.
_NOTES_LIMIT = 4000

#: Qt platform plugins that mean there is no screen and nobody in front of it.
#: The test suite runs on ``offscreen`` and so do both CI workflows.
_UNATTENDED = ("offscreen", "minimal", "vnc")


def unattended() -> bool:
    """Is there anyone here to answer a question?

    This exists because of the one way an update check can do real damage: the
    first-run question is modal, it is raised on a timer rather than by a click,
    and a modal dialog with nobody to dismiss it does not fail - it *hangs*.
    Under ``QT_QPA_PLATFORM=offscreen`` that is a test suite that never finishes
    and a release job that sits at its own gate until the runner times out, half
    an hour in, having tested nothing.

    Asked of the platform plugin rather than of the environment variable,
    because ``-platform offscreen`` on the command line sets one and not the
    other, and the plugin is the thing that decides whether a window is drawn.
    """
    app = QApplication.instance()
    if app is None:                        # no application, so certainly no user
        return True
    return app.platformName().lower() in _UNATTENDED


class _CheckWorker(QThread):
    """Asks GitHub, off the GUI thread.

    On a connection that drops packets rather than refusing them this takes the
    full timeout - ten seconds of a frozen window, during start-up, for a
    background errand nobody requested.
    """

    found = Signal(object)          # a Release
    failed = Signal(str)

    def run(self) -> None:
        try:
            self.found.emit(update.latest())
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:                       # never take the window down
            logger.debug("update check failed unexpectedly", exc_info=True)
            self.failed.emit(str(exc))


class _DownloadWorker(QThread):
    """Fetches the installer, off the GUI thread, cancellably."""

    progressed = Signal(int, int)
    done = Signal(str)
    failed = Signal(str)
    stopped = Signal()

    def __init__(self, asset: Asset) -> None:
        super().__init__()
        self._asset = asset
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            path = update.download(self._asset,
                                   progress=self.progressed.emit,
                                   cancelled=lambda: self._cancelled)
            self.done.emit(str(path))
        except Cancelled:
            logger.info("update download cancelled")
            self.stopped.emit()
        except UpdateError as exc:
            logger.error("update download failed: %s", exc)
            self.failed.emit(str(exc))
        except Exception as exc:
            logger.error("update download failed", exc_info=True)
            self.failed.emit(str(exc))


class UpdateDialog(QDialog):
    """"There is a newer version", and the three things that can be done about it.

    A dialog rather than a message box because the release notes belong in it.
    "7.8.0 is available" is not enough to decide on: the answer to "should I
    install this in the middle of a job" is in what changed, and sending the
    reader to a browser to find out is how the question gets postponed for good.
    """

    #: What the user chose, read by the caller after ``exec``.
    INSTALL, PAGE, SKIP, LATER = "install", "page", "skip", "later"

    def __init__(self, release: Release, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.release = release
        self.choice = self.LATER
        self._route = update.route()
        # The installer route needs a file to fetch.  A release published
        # without one, or an architecture nothing is built for, falls back to
        # the page rather than offering a button that cannot work.
        self._asset = release.asset_for() if self._route == "installer" else None
        if self._route == "installer" and self._asset is None:
            self._route = "download"

        self.setWindowTitle("Update available")
        self.setModal(True)

        column = QVBoxLayout(self)
        column.setSpacing(10)

        headline = QLabel(f"<b>cycloidgen {release.version} is available.</b><br>"
                          f"You are running {__version__}.")
        headline.setTextFormat(Qt.RichText)
        column.addWidget(headline)

        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        body = release.notes or "The release page has the notes for this version."
        if len(body) > _NOTES_LIMIT:
            body = body[:_NOTES_LIMIT].rstrip() + "\n\n…"
        # Rendered as Markdown, which is what GitHub stores and what the
        # changelog is written in.  Shown raw it is a wall of `##` and
        # backticks, which is less readable than the plain text it was made of.
        notes.setMarkdown(body)
        notes.setMinimumHeight(200)
        column.addWidget(notes, 1)

        how = QLabel(update.instruction(self._route))
        how.setWordWrap(True)
        # Selectable so the pip command can be copied rather than retyped, which
        # is the difference between an instruction and a working one.
        how.setTextInteractionFlags(Qt.TextSelectableByMouse)
        column.addWidget(how)

        column.addLayout(self._buttons())
        self.resize(560, 480)

    @property
    def asset(self) -> Asset | None:
        """The file to fetch, when the choice was :data:`INSTALL`."""
        return self._asset

    def _buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        skip = QPushButton("Skip this version")
        skip.setToolTip("Say nothing more until a version after "
                        f"{self.release.version} is published")
        skip.clicked.connect(lambda: self._choose(self.SKIP))
        row.addWidget(skip)
        row.addStretch(1)

        later = QPushButton("Not now")
        later.clicked.connect(lambda: self._choose(self.LATER))
        row.addWidget(later)

        installs = self._route == "installer"
        if installs:
            page = QPushButton("Release page")
            page.clicked.connect(lambda: self._choose(self.PAGE))
            row.addWidget(page)
        primary = QPushButton("Download and install" if installs
                              else "Open the release page")
        primary.setDefault(True)
        primary.clicked.connect(
            lambda: self._choose(self.INSTALL if installs else self.PAGE))
        row.addWidget(primary)
        return row

    def _choose(self, choice: str) -> None:
        self.choice = choice
        self.accept()


class Updater(QObject):
    """The whole update conversation, kept out of the main window.

    Owns the preference, the schedule, the two workers, the dialogs and the two
    Help menu entries.  The window calls :meth:`add_to_menu` while it builds the
    menu bar, :meth:`start` once the window is up, and :meth:`shutdown` on the
    way out; everything else happens in here.
    """

    #: Something to put on the status bar: message, logging level, seconds.
    announced = Signal(str, int, int)
    #: Hand this address to the desktop.
    link = Signal(str)
    #: The installer is running and wants this process gone.
    finished_with_window = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._window = parent
        self._settings = app_settings()
        self._check: _CheckWorker | None = None
        self._download: _DownloadWorker | None = None
        self._progress: QProgressDialog | None = None
        self._auto_action: QAction | None = None
        self._explicit = False

    # ------------------------------------------------------------ preference
    @property
    def answered(self) -> bool:
        """Has the user been asked whether to check at all?"""
        return self._mode in ("on", "off")

    @property
    def enabled(self) -> bool:
        return self._mode == "on"

    @enabled.setter
    def enabled(self, on: bool) -> None:
        self._settings.setValue(MODE_KEY, "on" if on else "off")
        if self._auto_action is not None:
            self._auto_action.setChecked(on)

    @property
    def available(self) -> bool:
        """Can this copy check at all?  ``CYCLOIDGEN_NO_UPDATE_CHECK`` says no."""
        return not update.disabled()

    @property
    def _mode(self) -> str:
        return str(self._settings.value(MODE_KEY, "") or "")

    def _due(self) -> bool:
        stamp = self._settings.value(CHECKED_KEY, "")
        if not stamp:
            return True
        try:
            last = datetime.fromisoformat(str(stamp))
        except ValueError:                 # a stored value from a build that is gone
            return True
        # Written with an offset, but read defensively: a preferences file
        # edited by hand is a plausible source of a naive timestamp, and the
        # comparison below raises rather than degrades if one gets through.
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - last >= INTERVAL

    # ------------------------------------------------------------------ menu
    def add_to_menu(self, menu) -> None:
        """Put the two entries on the Help menu and keep them in step.

        Built here rather than in the window so that the checkmark cannot drift
        from the preference: everything that changes the setting - the menu, the
        first-run question - goes through the same property.
        """
        check = QAction("Check for &updates...", self._window)
        check.setStatusTip("Ask GitHub whether a newer version has been published")
        check.triggered.connect(lambda: self.check(explicit=True))
        menu.addAction(check)

        auto = QAction("Check for updates &automatically", self._window)
        auto.setCheckable(True)
        auto.setChecked(self.enabled)
        auto.setStatusTip("Ask once a day, and say so only when there is a "
                          "newer version")
        auto.triggered.connect(self._toggle_auto)
        menu.addAction(auto)
        self._auto_action = auto

        if not self.available:
            # Turned off by the environment, so the entries stay visible and
            # explain themselves rather than silently doing nothing.
            for action in (check, auto):
                action.setEnabled(False)
                action.setStatusTip(f"Turned off by {update.ENV_VAR}")

    def _toggle_auto(self, on: bool) -> None:
        self.enabled = on
        logger.info("automatic update checks %s", "on" if on else "off")
        self._say("checking for updates once a day" if on
                  else "automatic update checks off", seconds=4)
        if on and self._due():
            self.check(explicit=False)

    # ----------------------------------------------------------------- start
    def start(self) -> None:
        """The one call the window makes at start-up.

        Deferred rather than immediate: a question in front of somebody who has
        just opened the application, before they have seen it, is a question
        about a program they have not met yet.
        """
        if not self.available:
            logger.debug("update checks are off: %s is set", update.ENV_VAR)
            return
        if unattended():
            logger.debug("no display, so nothing is asked and nothing is checked")
            return
        QTimer.singleShot(STARTUP_DELAY_MS, self._start_now)

    def _start_now(self) -> None:
        if not self.answered:
            self._ask_consent()
        elif self.enabled and self._due():
            self.check(explicit=False)

    def _ask_consent(self) -> None:
        """The first-run question.  Asked once, in words that say what happens."""
        box = QMessageBox(self._window)
        box.setWindowTitle("Check for updates?")
        box.setIcon(QMessageBox.Question)
        box.setText("Should cycloidgen check for new versions?")
        box.setInformativeText(
            "Once a day it would ask GitHub which version is the latest, and tell "
            "you only if a newer one exists. Nothing about your designs, your "
            "machine or your files is sent - it is a request for a version "
            "number.\n\n"
            "The analysis models change between releases, so a build that has "
            "fallen behind can quietly disagree with the current one about the "
            "same design.\n\n"
            "You can change this at any time in Help ▸ Check for updates "
            "automatically.")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.Yes)
        box.button(QMessageBox.Yes).setText("Yes, check for updates")
        box.button(QMessageBox.No).setText("No, do not check")
        wanted = box.exec() == QMessageBox.Yes
        self.enabled = wanted
        logger.info("update checks %s", "enabled" if wanted else "disabled")
        if wanted:
            self.check(explicit=False)

    # ----------------------------------------------------------------- check
    def check(self, *, explicit: bool) -> None:
        """Ask GitHub.  ``explicit`` is the difference between the menu and the timer.

        An explicit check reports every outcome and ignores a previously skipped
        version: the user asked the question again, so the earlier "not this
        one" is not an answer to it.
        """
        if not self.available:
            if explicit:
                self._tell(f"Update checks are turned off by {update.ENV_VAR}.")
            return
        if self._check is not None:
            if explicit:
                self._say("already checking for updates", seconds=4)
            return

        self._explicit = explicit
        if explicit:
            self._say("checking for updates...", seconds=4)
        worker = _CheckWorker(self)
        worker.found.connect(self._found)
        worker.failed.connect(self._check_failed)
        worker.finished.connect(self._retire_check)
        self._check = worker
        worker.start()

    def _retire_check(self) -> None:
        worker, self._check = self._check, None
        if worker is not None:
            worker.deleteLater()

    def _found(self, release: Release) -> None:
        self._settings.setValue(
            CHECKED_KEY, datetime.now(timezone.utc).isoformat(timespec="seconds"))
        explicit, self._explicit = self._explicit, False

        if not release.is_newer_than():
            logger.info("cycloidgen %s is current (latest published: %s)",
                        __version__, release.version)
            if explicit:
                self._tell(f"cycloidgen {__version__} is the current version.")
            return

        skipped = str(self._settings.value(SKIPPED_KEY, "") or "")
        if not explicit and skipped == release.version:
            logger.info("update %s is available and was skipped", release.version)
            return

        logger.info("update available: %s", release.version)
        self._offer(release)

    def _check_failed(self, message: str) -> None:
        explicit, self._explicit = self._explicit, False
        # A log line only when nobody asked.  A background errand that failed is
        # not an event in the user's day.
        logger.log(logging.WARNING if explicit else logging.INFO,
                   "update check failed: %s", message)
        if explicit:
            self._tell(f"Could not check for updates.\n\n{message}",
                       icon=QMessageBox.Warning)

    # ----------------------------------------------------------------- offer
    def _offer(self, release: Release) -> None:
        dialog = UpdateDialog(release, self._window)
        dialog.exec()
        if dialog.choice == UpdateDialog.SKIP:
            self._settings.setValue(SKIPPED_KEY, release.version)
            self._say(f"skipping {release.version}; a later release will still "
                      f"be offered", seconds=8)
        elif dialog.choice == UpdateDialog.PAGE:
            self.link.emit(release.page)
        elif dialog.choice == UpdateDialog.INSTALL and dialog.asset is not None:
            self._fetch(dialog.asset)

    # -------------------------------------------------------------- download
    def _fetch(self, asset: Asset) -> None:
        self._progress = QProgressDialog(f"Downloading {asset.name}...", "Cancel",
                                         0, max(asset.size, 1), self._window)
        self._progress.setWindowTitle("Update")
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.setValue(0)

        worker = _DownloadWorker(asset)
        worker.progressed.connect(self._downloading)
        worker.done.connect(self._downloaded)
        worker.failed.connect(self._download_failed)
        worker.stopped.connect(self._download_stopped)
        self._progress.canceled.connect(worker.cancel)
        self._download = worker
        worker.start()
        logger.info("downloading %s (%.0f MB)", asset.name, asset.size / 1e6)

    def _downloading(self, done: int, total: int) -> None:
        if self._progress is None or self._progress.wasCanceled():
            return
        if total and self._progress.maximum() != total:
            self._progress.setMaximum(total)
        self._progress.setValue(done)
        self._progress.setLabelText(
            f"Downloading the installer - {done / 1e6:.0f} of {total / 1e6:.0f} MB")

    def _close_progress(self) -> None:
        self._download = None
        if self._progress is not None:
            self._progress.reset()
            self._progress = None

    def _download_stopped(self) -> None:
        self._close_progress()
        self._say("update download cancelled", seconds=5)

    def _download_failed(self, message: str) -> None:
        self._close_progress()
        self._tell(f"The update could not be downloaded.\n\n{message}\n\n"
                   "The release page has the installer if you would rather fetch "
                   "it yourself.", icon=QMessageBox.Warning)

    def _downloaded(self, path: str) -> None:
        self._close_progress()
        installer = Path(path)

        box = QMessageBox(self._window)
        box.setWindowTitle("Install the update")
        box.setIcon(QMessageBox.Question)
        box.setText("The installer is ready.")
        box.setInformativeText(
            "cycloidgen will close and the installer will start. Windows asks for "
            "permission first, and - because this build is not signed - "
            "SmartScreen may warn: More info → Run anyway.\n\n"
            "Your preferences, recent files and saved designs are kept.\n\n"
            f"{installer}")
        box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        box.button(QMessageBox.Ok).setText("Close and install")
        box.setDefaultButton(QMessageBox.Ok)
        if box.exec() != QMessageBox.Ok:
            self._say(f"the installer is at {installer}", seconds=15)
            return

        try:
            update.launch(installer)
        except UpdateError as exc:
            self._tell(f"The installer could not be started.\n\n{exc}\n\n"
                       f"It is at {installer} and can be run by hand.",
                       icon=QMessageBox.Warning)
            return
        except OSError as exc:
            # A refused UAC prompt arrives here, and a refusal is a decision
            # rather than a fault: say where the file is and leave the window up.
            logger.info("the installer was not started: %s", exc)
            self._say(f"the installer was not started; it is at {installer}",
                      level=logging.WARNING, seconds=15)
            return
        logger.info("installer started; closing")
        self.finished_with_window.emit()

    # ------------------------------------------------------------------ misc
    def _say(self, message: str, *, level: int = logging.INFO,
             seconds: int = 5) -> None:
        self.announced.emit(message, level, seconds)

    def _tell(self, message: str, *, icon=QMessageBox.Information) -> None:
        box = QMessageBox(self._window)
        box.setWindowTitle("Updates")
        box.setIcon(icon)
        box.setText(message)
        box.exec()

    def shutdown(self) -> None:
        """Let the threads finish before the window that owns them goes away.

        A QThread destroyed while it is running takes the process with it, and
        both of these sit on a socket with a ten-second timeout.
        """
        if self._download is not None and self._download.isRunning():
            self._download.cancel()
            self._download.wait(3000)
        if self._check is not None and self._check.isRunning():
            self._check.wait(3000)
