"""What the app says it is not, and that it says it everywhere.

Four places carry this: the strip under the export buttons, the box that asks
before an export is written, the About dialog, and the ``NOTICE.txt`` that goes
into the folder with the parts. The risk with four copies is not that one of
them disappears - somebody would notice - but that one of them softens, and a
disclaimer that is weaker in the place it is actually read is worse than none.
So they are all held to the same string.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cycloidgen import notice
from cycloidgen.core.spec import preset
from cycloidgen.export import manifest, write_bundle


def test_the_notice_names_both_halves_of_what_is_unverified():
    """The numbers *and* the geometry.

    It used to disclaim only the numbers, which is the smaller half: a STEP
    file that looks finished is the easiest thing here to mistake for a drawing
    that has been checked.
    """
    assert "not a certification" in notice.FULL
    assert "not a checked drawing" in notice.FULL
    assert "tolerance stack" in notice.FULL
    assert "calibrated against measured hardware" in notice.FULL
    assert "prototype" in notice.SHORT and "prototype" in notice.FULL


def test_the_file_says_which_build_wrote_it():
    from cycloidgen import __version__

    text = notice.file_text("Cycloidal drive, 21:1.")
    assert notice.HEADLINE.upper() in text
    assert "Cycloidal drive, 21:1." in text
    assert f"cycloidgen {__version__}" in text
    assert max(len(line) for line in text.splitlines()) <= 78


# ------------------------------------------------------------------ the bundle


def test_every_bundle_carries_the_notice_whatever_is_selected():
    """Including the halves of it that are not the report.

    Somebody who exports drawings only is exactly the person who takes a DXF
    straight to a laser cutter.
    """
    spec = preset(15)
    for groups in ({"drawings"}, {"solids"}, {"data"}, {"animation"},
                   set(manifest.group_keys())):
        planned = [name for _, name in manifest.planned_files(spec, groups)]
        assert "NOTICE.txt" in planned, groups


def test_asking_for_nothing_writes_nothing_at_all():
    """A notice with no parts beside it is not a bundle."""
    assert manifest.planned_files(preset(15), set()) == []


def test_the_notice_lands_on_disk_with_the_drawings(tmp_path):
    written = write_bundle(preset(15), tmp_path, groups={"drawings"})
    target = tmp_path / "NOTICE.txt"
    assert target in written
    text = target.read_text(encoding="utf-8")
    assert notice.FULL.split("\n\n")[0].split(",")[0] in text.replace("\n", " ")
    assert "15:1" in text


def test_the_notice_is_not_a_group_anyone_can_untick():
    """It is written whatever is chosen, so it cannot be one of the choices."""
    keys = {group.key for group in manifest.GROUPS}
    assert "notice" not in keys
    (entry,) = manifest.always_written()
    assert entry.where == "NOTICE.txt"
    # and it is not returned by the per-group query the Outputs tab draws from,
    # or it would appear under every group in the tree
    for key in keys:
        assert entry not in manifest.outputs_for({key})


# ---------------------------------------------------------------------- the UI


@pytest.fixture(scope="module", autouse=True)
def isolated_settings(tmp_path_factory):
    """Preferences to a scratch file, so this module cannot rearrange a desktop."""
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
def window(isolated_settings):
    from PySide6.QtWidgets import QApplication

    from cycloidgen.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    # The first analysis lands on a worker thread, and until it does the window
    # has no report - which is a different refusal from the one under test.
    deadline = time.monotonic() + 10.0
    while win.analysis is None and time.monotonic() < deadline:
        app.sendPostedEvents()
        app.processEvents()
        time.sleep(0.01)
    yield win
    win.close()
    app.processEvents()


def test_the_window_carries_the_notice_where_the_export_buttons_are(window):
    """Not in Help ▸ About, which is a dialog nobody opens."""
    from PySide6.QtWidgets import QLabel

    strips = [w for w in window.findChildren(QLabel)
              if w.objectName() == "NoticeStrip"]
    assert len(strips) == 1
    assert notice.SHORT in strips[0].text()
    assert notice.HEADLINE.upper() in strips[0].text()
    assert strips[0].toolTip() == notice.FULL


def test_the_strip_cannot_be_closed(window):
    """A disclaimer with a close button is a disclaimer shown once."""
    from PySide6.QtWidgets import QLabel, QPushButton

    strip = next(w for w in window.findChildren(QLabel)
                 if w.objectName() == "NoticeStrip")
    assert not strip.findChildren(QPushButton)


def test_an_export_asks_before_it_writes_and_a_refusal_writes_nothing(
        window, monkeypatch, tmp_path):
    """The box comes before the files, so it is a decision and not a receipt."""
    from cycloidgen.ui import main_window as mw

    assert window.analysis is not None and window.analysis.report.ok
    asked: list[Path] = []
    monkeypatch.setattr(mw.MainWindow, "_notice_accepted",
                        lambda self, target: asked.append(target) or False)
    started: list[object] = []
    monkeypatch.setattr(mw, "ExportWorker",
                        lambda *args: started.append(args))

    window._start_export(tmp_path / "bundle", {"drawings"})

    assert asked == [tmp_path / "bundle"]
    assert not started, "a refused notice still started an export"
    assert not list(tmp_path.iterdir())
