"""The application icon, and that it is still the disc it claims to be.

The icon is not a picture somebody drew: ``tools/make_icon.py`` renders it from
:func:`cycloidgen.core.profile.disc_profile`, the same call the STEP export
cuts the part with.  That is the whole point of it - the icon cannot drift away
from the geometry - and it is also the thing a committed PNG cannot prove on its
own.  So this checks the shipped bytes against what the tool draws today, and
checks the tool against the profile.

It also holds the design rule that makes the small sizes legible: each size is
drawn at that size, with the lobes and the holes graded for it, rather than
resampled down from one master.  A 256 disc reduced to 16 is grey soup, and grey
soup in a task bar is what the whole exercise is against.
"""
from __future__ import annotations

import pathlib
import sys
from itertools import pairwise

import numpy as np
import pytest
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "cycloidgen" / "ui" / "assets"

# The generator is a tool rather than part of the package - it has no business
# being installed with the application - so it is imported off its own path.
sys.path.insert(0, str(ROOT / "tools"))
import make_icon

#: Resampling is not bit-exact across Pillow releases, so the shipped frames are
#: compared to freshly drawn ones by mean channel difference rather than by
#: equality.  A regenerated icon lands near zero; the brand mark that used to be
#: here scores in the tens.
DRIFT = 2.0


def _mean_difference(a: Image.Image, b: Image.Image) -> float:
    return float(np.abs(np.asarray(a.convert("RGBA"), float)
                        - np.asarray(b.convert("RGBA"), float)).mean())


# ------------------------------------------------------------- what shipped --


def test_the_icon_ships_in_every_form_the_platforms_ask_for():
    """Three files, because no two of these platforms read the same one.

    Windows takes the .ico and nothing else, the Linux desktops want a PNG at
    the size their hicolor directory declares, and the macOS .icns is built at
    package time from the 1024 - which has to *be* 1024, or the Dock shows a
    256 blown up.
    """
    ico = Image.open(ASSETS / "cycloidgen.ico")
    assert sorted(ico.ico.sizes()) == [(s, s) for s in make_icon.ICON_SIZES]
    for size in (256, 1024):
        png = Image.open(ASSETS / f"icon-{size}.png")
        assert png.size == (size, size)
        assert png.mode == "RGBA", "the tile has to be cut out of its corners"


def test_every_size_is_drawn_at_that_size_and_not_reduced_to_it():
    """The .ico frames are what the tool renders, size by size.

    Fails if somebody regenerates the icon by resampling one master into the
    rest - which is the failure this is all arranged to avoid, and which looks
    perfectly fine until you see it at 16 px next to a window title.
    """
    ico = Image.open(ASSETS / "cycloidgen.ico")
    for size in make_icon.ICON_SIZES:
        shipped = ico.ico.getimage((size, size))
        assert _mean_difference(shipped, make_icon.render(size)) < DRIFT, size


def test_the_committed_pngs_are_the_same_icon():
    for size in (256, 1024):
        shipped = Image.open(ASSETS / f"icon-{size}.png")
        assert _mean_difference(shipped, make_icon.render(size)) < DRIFT, size


def test_the_window_icon_is_the_disc_rather_than_the_company_mark():
    """What the application actually loads, not what is on disk beside it.

    An icon that is the company logo says who wrote the program and nothing
    about what it does; this is the check that a brand refresh cannot put it
    back by writing over ``cycloidgen.ico``.
    """
    pytest.importorskip("PySide6")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from cycloidgen.ui import branding

    QApplication.instance() or QApplication([])
    icon = branding.window_icon()
    assert not icon.isNull()

    from PySide6.QtGui import QImage

    drawn = icon.pixmap(256, 256).toImage().convertToFormat(QImage.Format_RGBA8888)
    shipped = Image.frombytes("RGBA", (drawn.width(), drawn.height()),
                              drawn.constBits().tobytes())
    assert _mean_difference(shipped, make_icon.render(256)) < DRIFT
    mark = Image.open(ASSETS / "mark-blue.png")
    assert _mean_difference(shipped, mark) > DRIFT * 4


# --------------------------------------------------------- what it is drawn from


def test_the_outline_is_the_profile_the_application_cuts():
    """Not traced by hand, and not a flower with the right number of petals.

    Every point of the drawn outline sits at exactly the pin radius from the
    pin-centre locus, which is the defining property of the conjugate profile -
    the same one ``tests/test_profile.py`` holds the geometry to.
    """
    from cycloidgen.core.profile import distance_to_polyline, pin_locus

    for _, grade in make_icon.GRADES:
        ecc, pin = make_icon.disc_geometry(grade.lobes, grade.k1, grade.rr)
        # Taken unrotated - `upright` is a rigid turn and distances do not care,
        # but the locus it is measured against would have to be turned with it.
        pts = make_icon.disc_points(grade.lobes, grade.k1, grade.rr, samples=720,
                                    upright=False)
        # ...and scaled: the drawn outline is normalised to unit outer radius.
        scale = 1.0 / np.hypot(*make_icon.disc_profile(
            np.linspace(0, 2 * np.pi, 720, endpoint=False), 1.0, pin, ecc,
            grade.lobes).T).max()

        locus = pin_locus(np.linspace(0, 2 * np.pi, 4000), 1.0, ecc,
                          grade.lobes) * scale
        distance = distance_to_polyline(pts, locus)
        assert np.allclose(distance, pin * scale, atol=1e-4), grade


def test_the_disc_has_the_lobes_its_grade_says_and_one_of_them_points_up():
    """Counted off the outline, so a sign slip that flattens it is caught."""
    for _, grade in make_icon.GRADES:
        pts = make_icon.disc_points(grade.lobes, grade.k1, grade.rr)
        r = np.hypot(pts[:, 0], pts[:, 1])
        crests = np.sum((r > np.roll(r, 1)) & (r >= np.roll(r, -1)))
        assert crests == grade.lobes, grade
        assert r.max() == pytest.approx(1.0)
        # The tallest point is straight up: a lobe on the vertical axis is the
        # difference between a drawn mark and a screenshot of a mesh.
        assert pts[int(np.argmax(r))][1] == pytest.approx(1.0, abs=1e-6)


def test_the_grades_spend_detail_in_one_direction_only():
    """Smaller means fewer lobes, deeper lobes, and less inside them.

    Written down because the temptation, every time, is to put one more hole
    into the 24 px - and a hole two pixels across is not a hole, it is a smudge
    that costs the disc its outline.
    """
    ordered = sorted(make_icon.GRADES, key=lambda item: item[0])
    for (_, small), (_, large) in pairwise(ordered):
        assert small.lobes <= large.lobes
        assert small.k1 >= large.k1                  # deeper, to survive the scale
        assert small.span >= large.span              # and larger in its tile
        assert small.holes <= large.holes
    assert make_icon.grade_for(16).holes == 0
    assert make_icon.grade_for(256).holes > 0


def test_the_icon_is_legible_on_a_light_task_bar_and_a_dark_one():
    """One asset for both, which is what the tile is for.

    A bare blue disc is the brand colour against whatever the desktop happens
    to be; on a dark task bar that is 2.8:1 and the shape disappears.  The tile
    carries its own contrast, so only the pair inside it has to be checked.
    """
    pytest.importorskip("PySide6")
    from cycloidgen.ui.branding import BRAND_BLUE, BRAND_PAPER, contrast_ratio

    assert make_icon.BRAND_BLUE == BRAND_BLUE
    assert make_icon.BRAND_PAPER == BRAND_PAPER
    assert contrast_ratio(BRAND_PAPER, BRAND_BLUE) >= 4.5


def test_the_tile_is_cut_out_of_its_corners():
    """A square icon in a row of rounded ones is a badge, not an application."""
    icon = make_icon.render(256)
    alpha = np.asarray(icon)[:, :, 3]
    assert alpha[0, 0] == 0 and alpha[-1, -1] == 0
    assert alpha[128, 0] == 255 and alpha[128, -1] == 255
