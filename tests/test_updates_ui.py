"""The update conversation: consent, the schedule, and what each "no" means.

The module underneath is tested in ``tests/test_update.py`` and never touches
the network there.  Neither does this: :func:`cycloidgen.update.latest` is
replaced throughout, so what is exercised here is the *policy* - when a request
would be made, and what is done with the answer - which is the half where a
mistake is a mistake about the user rather than about a protocol.

Settings are redirected into a scratch file, for the reason
``tests/test_workspace.py`` gives at length: on Windows Qt's own redirection
does not apply to the constructor this application uses, so a test that looks
isolated would be rewriting the developer's real preferences.

The one thing that would be worst to get wrong is first: an application that
asks GitHub anything before the user has been asked whether it may.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMenu,
    QPushButton,
    QTextBrowser,
    QWidget,
)

from cycloidgen import __version__, update
from cycloidgen.ui import updates
from cycloidgen.ui.updates import UpdateDialog, Updater


@pytest.fixture(scope="module", autouse=True)
def isolated_settings(tmp_path_factory):
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


@pytest.fixture
def updater(app, monkeypatch):
    """A fresh updater over an empty preference store."""
    monkeypatch.delenv(update.ENV_VAR, raising=False)
    window = QWidget()
    made = Updater(window)
    for key in (updates.MODE_KEY, updates.CHECKED_KEY, updates.SKIPPED_KEY):
        made._settings.remove(key)
    yield made
    window.deleteLater()


def _release(version: str, **kwargs) -> update.Release:
    fields = {"page": "https://example.invalid/r", "notes": "- a change"}
    fields.update(kwargs)
    return update.Release(version=version, **fields)


def _never_called():
    raise AssertionError("a request was made when none should have been")


# ----------------------------------------------------------------- consent --

def test_nothing_is_asked_of_github_before_the_user_is_asked(updater, monkeypatch):
    """The property this whole design exists for.

    A tool that phones home the first time it is opened and offers an opt-out
    afterwards has already done the thing the user might have objected to.
    """
    monkeypatch.setattr(update, "latest", _never_called)
    assert not updater.answered
    assert not updater.enabled
    updater.check(explicit=False)
    updater.shutdown()


def test_the_answer_is_remembered_either_way(updater):
    updater.enabled = True
    assert updater.answered and updater.enabled
    updater.enabled = False
    # "No" is an answer, not an absence of one: it must not be re-asked next
    # time the application starts.
    assert updater.answered and not updater.enabled


def test_a_second_updater_reads_the_same_answer(updater, app):
    updater.enabled = True
    other = Updater(QWidget())
    assert other.answered and other.enabled


def test_nothing_is_raised_where_there_is_nobody_to_answer_it(updater,
                                                              monkeypatch):
    """The bug this guard exists for, and it is not a small one.

    The first-run question is modal and raised on a timer rather than by a
    click. Under `QT_QPA_PLATFORM=offscreen` there is nobody to dismiss it, so
    it does not fail - it hangs: a test suite that never finishes, and a release
    job that sits at its own gate until the runner times out half an hour in,
    having tested nothing. It did exactly that once, which is why this is here.
    """
    assert updates.unattended(), "these tests are supposed to run offscreen"
    monkeypatch.setattr(update, "latest", _never_called)
    monkeypatch.setattr(updater, "_ask_consent",
                        lambda: pytest.fail("a modal question with no user"))
    updater.start()
    QApplication.processEvents()


def test_the_menu_still_works_where_the_timer_does_not(updater, monkeypatch):
    """Off-screen suppresses what nobody asked for, not what somebody clicked."""
    asked = []
    monkeypatch.setattr(update, "latest", lambda: asked.append(True))
    updater.enabled = True
    updater.check(explicit=True)
    updater.shutdown()
    assert asked == [True]


# ---------------------------------------------------------------- schedule --

def test_a_check_that_has_never_run_is_due(updater):
    assert updater._due()


def test_a_check_from_this_morning_is_not_due_again(updater):
    updater._settings.setValue(
        updates.CHECKED_KEY,
        datetime.now(timezone.utc).isoformat(timespec="seconds"))
    assert not updater._due()


def test_a_check_from_last_week_is_due(updater):
    stale = datetime.now(timezone.utc) - timedelta(days=7)
    updater._settings.setValue(updates.CHECKED_KEY,
                               stale.isoformat(timespec="seconds"))
    assert updater._due()


@pytest.mark.parametrize("stored", ["", "yesterday", "2026-13-45", "0"])
def test_an_unreadable_timestamp_costs_a_check_and_not_a_crash(updater, stored):
    """A preferences file is a text file somebody can edit."""
    updater._settings.setValue(updates.CHECKED_KEY, stored)
    assert updater._due()


def test_a_naive_timestamp_is_still_comparable(updater):
    """Written with an offset, but read defensively: comparing an aware datetime
    with a naive one raises, and it would raise during start-up."""
    naive = (datetime.now(timezone.utc) - timedelta(days=7)).replace(tzinfo=None)
    updater._settings.setValue(updates.CHECKED_KEY, naive.isoformat())
    assert updater._due()


# ------------------------------------------------------------------ answers --

def test_being_up_to_date_says_nothing_when_nobody_asked(updater, monkeypatch):
    told = []
    monkeypatch.setattr(updater, "_tell", lambda *a, **k: told.append(a))
    monkeypatch.setattr(updater, "_offer", lambda r: told.append(("offered", r)))
    updater._explicit = False
    updater._found(_release(__version__))
    assert told == []


def test_being_up_to_date_answers_a_question_that_was_asked(updater, monkeypatch):
    """A menu entry that answers with nothing is one that looks unwired."""
    told = []
    monkeypatch.setattr(updater, "_tell", lambda message, **k: told.append(message))
    updater._explicit = True
    updater._found(_release(__version__))
    assert len(told) == 1 and __version__ in told[0]


def test_a_failed_background_check_is_a_log_line_and_not_a_dialog(updater,
                                                                  monkeypatch):
    told = []
    monkeypatch.setattr(updater, "_tell", lambda *a, **k: told.append(a))
    updater._explicit = False
    updater._check_failed("could not reach GitHub")
    assert told == []


def test_a_failed_check_that_was_asked_for_is_reported(updater, monkeypatch):
    told = []
    monkeypatch.setattr(updater, "_tell", lambda message, **k: told.append(message))
    updater._explicit = True
    updater._check_failed("could not reach GitHub")
    assert len(told) == 1 and "could not reach GitHub" in told[0]


def test_a_successful_check_is_recorded_even_when_there_is_nothing_to_say(
        updater, monkeypatch):
    """Otherwise a machine already on the newest version checks every start-up."""
    monkeypatch.setattr(updater, "_tell", lambda *a, **k: None)
    updater._settings.remove(updates.CHECKED_KEY)
    updater._explicit = False
    updater._found(_release(__version__))
    assert not updater._due()


# --------------------------------------------------------------------- skip --

def test_a_skipped_version_is_not_offered_again(updater, monkeypatch):
    offered = []
    monkeypatch.setattr(updater, "_offer", offered.append)
    updater._settings.setValue(updates.SKIPPED_KEY, "99.0.0")
    updater._explicit = False
    updater._found(_release("99.0.0"))
    assert offered == []


def test_skipping_one_version_does_not_skip_the_next(updater, monkeypatch):
    """The difference between "not this one" and "stop asking"."""
    offered = []
    monkeypatch.setattr(updater, "_offer", offered.append)
    updater._settings.setValue(updates.SKIPPED_KEY, "99.0.0")
    updater._explicit = False
    updater._found(_release("99.0.1"))
    assert [r.version for r in offered] == ["99.0.1"]


def test_asking_from_the_menu_overrides_a_skip(updater, monkeypatch):
    """The user asked the question again; the old "not this one" answered a
    different one."""
    offered = []
    monkeypatch.setattr(updater, "_offer", offered.append)
    updater._settings.setValue(updates.SKIPPED_KEY, "99.0.0")
    updater._explicit = True
    updater._found(_release("99.0.0"))
    assert [r.version for r in offered] == ["99.0.0"]


# --------------------------------------------------------------------- menu --

def test_the_menu_carries_both_entries_and_the_checkmark_follows(updater):
    menu = QMenu()
    updater.enabled = True
    updater.add_to_menu(menu)
    labels = [a.text() for a in menu.actions()]
    assert any("Check for &updates" in text for text in labels)
    auto = next(a for a in menu.actions() if a.isCheckable())
    assert auto.isChecked()

    # Set from anywhere - the first-run question included - and the menu agrees.
    updater.enabled = False
    assert not auto.isChecked()


def test_the_environment_disables_the_entries_visibly(app, monkeypatch):
    """Greyed out and explained, rather than present and silently inert."""
    monkeypatch.setenv(update.ENV_VAR, "1")
    updater = Updater(QWidget())
    menu = QMenu()
    updater.add_to_menu(menu)
    assert menu.actions()
    for action in menu.actions():
        assert not action.isEnabled()
        assert update.ENV_VAR in action.statusTip()


def test_the_environment_stops_the_startup_path(app, monkeypatch):
    monkeypatch.setenv(update.ENV_VAR, "1")
    monkeypatch.setattr(update, "latest", _never_called)
    updater = Updater(QWidget())
    assert not updater.available
    updater.start()
    updater.check(explicit=False)
    updater.shutdown()


# ------------------------------------------------------------------- dialog --

def _text_of(dialog, kind) -> str:
    return " ".join(widget.text() for widget in dialog.findChildren(kind))


def test_the_dialog_names_both_versions(app, monkeypatch):
    """"7.8.0 is available" is only half of it: the reader has to know what
    they are on to know whether they care."""
    monkeypatch.setattr(update, "route", lambda *a, **k: "pip")
    dialog = UpdateDialog(_release("99.0.0"), None)
    said = _text_of(dialog, QLabel)
    assert "99.0.0" in said and __version__ in said
    dialog.deleteLater()


def test_a_pip_install_is_never_offered_an_installer(app, monkeypatch):
    """Two copies of the application is the outcome that has to be impossible."""
    monkeypatch.setattr(update, "route", lambda *a, **k: "pip")
    release = update.release_from_payload({
        "tag_name": "99.0.0",
        "assets": [{"name": "cycloidgen_v99.0.0_Setup.exe", "size": 1,
                    "browser_download_url": "https://example.invalid/s.exe"}],
    })
    dialog = UpdateDialog(release, None)
    assert dialog.asset is None
    assert "install" not in _text_of(dialog, QPushButton).lower()
    # And it says the thing that is actually true of a wheel.
    assert "pip install --upgrade cycloidgen" in _text_of(dialog, QLabel)
    dialog.deleteLater()


def test_a_release_with_no_installer_falls_back_to_the_page(app, monkeypatch):
    """A frozen Windows build, and a release published without a setup.exe."""
    monkeypatch.setattr(update, "route", lambda *a, **k: "installer")
    dialog = UpdateDialog(_release("99.0.0"), None)
    assert dialog.asset is None
    assert dialog._route == "download"
    dialog.deleteLater()


def test_every_button_records_a_choice(app, monkeypatch):
    monkeypatch.setattr(update, "route", lambda *a, **k: "pip")
    dialog = UpdateDialog(_release("99.0.0"), None)
    assert dialog.choice == UpdateDialog.LATER      # closing it changes nothing
    for choice in (UpdateDialog.SKIP, UpdateDialog.PAGE, UpdateDialog.LATER):
        dialog.choice = UpdateDialog.LATER
        dialog._choose(choice)
        assert dialog.choice == choice
    dialog.deleteLater()


def test_long_release_notes_are_cut_rather_than_shown_whole(app, monkeypatch):
    monkeypatch.setattr(update, "route", lambda *a, **k: "pip")
    dialog = UpdateDialog(_release("99.0.0", notes="line\n" * 20000), None)
    browser = dialog.findChild(QTextBrowser)
    assert browser is not None
    assert len(browser.toPlainText()) < updates._NOTES_LIMIT + 100
    dialog.deleteLater()
