"""The requirements dialog, and whether it can be made to fit on a screen.

Needs a QApplication, so it runs headless.  Offscreen Qt has no fonts and draws
every label as tofu, which makes it useless for judging how something *looks* -
but sizes are computed from metrics rather than glyphs, and a layout's minimum
height is exactly the kind of thing that goes wrong on somebody else's monitor
and never on the one it was written on.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QScrollArea

from cycloidgen.core.spec import GearSpec
from cycloidgen.ui.optimise_dialog import OptimiseDialog

#: The shortest screen this has to work on, less the room a title bar and a
#: taskbar take: a 1366x768 laptop, which is still the second most common panel
#: there is, and what a 1080p screen at 150% scaling reports as its *logical*
#: height (720).
SHORT_SCREEN = 660


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(app):
    d = OptimiseDialog(GearSpec())
    yield d
    d.deleteLater()


def test_the_dialog_can_be_made_short_enough_to_fit_a_laptop(dialog):
    """The bug this is here for: it could not.

    Four group boxes and a button came to 832 px of minimum height, a dialog
    inherits the minimum of what is in it, and so this one could not be sized
    below 885 px with its frame on.  On anything shorter the button box went off
    the bottom of the screen and stayed there - dragging the edge did nothing,
    because the window was already as small as it was allowed to be.
    """
    assert dialog.minimumSizeHint().height() <= SHORT_SCREEN, (
        "the dialog cannot be shrunk to fit a short screen, so whatever is at "
        "the bottom of it cannot be reached")


def test_the_form_is_what_scrolls(dialog):
    """Rather than the results table, which is the half that can afford to
    stretch, or the dialog as a whole, which would put a scrollbar around the
    buttons and defeat the point."""
    area = dialog.findChild(QScrollArea)
    assert area is not None, "the requirements form is no longer scrollable"
    assert area.widgetResizable(), \
        "a fixed-size widget in a scroll area keeps its own minimum width"
    # Its content is genuinely taller than a short screen - if that stops being
    # true the scroll area is guarding nothing and this test is asserting
    # nothing either.
    assert area.widget().minimumSizeHint().height() > SHORT_SCREEN


def test_both_buttons_that_end_the_dialog_stay_out_of_the_scrolled_part(dialog):
    """Search, and the accept/cancel box.

    Scrolling the primary action out of sight would have fixed the reaching
    problem by handing it to the button the dialog exists to have pressed.
    """
    area = dialog.findChild(QScrollArea)
    scrolled = area.widget()
    for name, button in (("Search", dialog._run_btn),
                         ("button box", dialog._buttons)):
        assert not scrolled.isAncestorOf(button), \
            f"{name} is inside the scrolled area and can be scrolled away"


def test_the_dialog_does_not_open_larger_than_the_screen(dialog):
    """`resize` is a request.  It used to ask for 660 px and get 854, because a
    layout minimum overrides it silently - so the number in the source said one
    thing and every window said another."""
    available = dialog.screen().availableGeometry()
    assert dialog.size().height() <= available.height()
    assert dialog.size().width() <= available.width()
