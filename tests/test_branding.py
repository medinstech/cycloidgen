"""The brand palette.

Contrast is the part of a theme that is easy to get wrong and impossible to
notice once you are used to looking at it, so it is asserted rather than
eyeballed.  The floors are WCAG 2.1 AA: 4.5:1 for text, 3:1 for the boundary of
a control you are meant to be able to find.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from cycloidgen.ui.branding import (
    BRAND_BLUE,
    contrast_ratio,
    darken,
    lighten,
    mix,
    palette,
    stylesheet,
)

MODES = ("light", "dark")
TEXT_FLOOR = 4.5
COMPONENT_FLOOR = 3.0


@pytest.mark.parametrize("mode", MODES)
def test_body_text_is_readable(mode):
    p = palette(mode)
    assert contrast_ratio(p.ink, p.surface) >= 7.0        # AAA for primary text
    assert contrast_ratio(p.ink, p.raised) >= 7.0
    assert contrast_ratio(p.ink_dim, p.surface) >= TEXT_FLOOR
    assert contrast_ratio(p.ink_dim, p.raised) >= TEXT_FLOOR


@pytest.mark.parametrize("mode", MODES)
def test_accent_is_readable_as_text_on_both_surfaces(mode):
    p = palette(mode)
    assert contrast_ratio(p.accent, p.surface) >= TEXT_FLOOR
    assert contrast_ratio(p.accent, p.raised) >= TEXT_FLOOR


@pytest.mark.parametrize("mode", MODES)
def test_labels_on_filled_brand_controls_are_readable(mode):
    """Every state of a primary button, not just the resting one."""
    p = palette(mode)
    for fill in (p.accent_fill, p.accent_hover, p.accent_pressed):
        assert contrast_ratio(p.accent_text, fill) >= TEXT_FLOOR, fill


@pytest.mark.parametrize("mode", MODES)
def test_a_filled_control_can_be_found_against_the_page(mode):
    """The fill or its border has to carry the boundary.

    On the dark surface the fill alone is 2.3:1, which is why the primary
    button is drawn with the lighter accent as its edge.
    """
    p = palette(mode)
    best = max(contrast_ratio(p.accent_fill, p.surface),
               contrast_ratio(p.accent, p.surface))
    assert best >= COMPONENT_FLOOR


@pytest.mark.parametrize("mode", MODES)
def test_selection_wash_keeps_its_text_readable(mode):
    p = palette(mode)
    assert contrast_ratio(p.ink, p.accent_wash) >= TEXT_FLOOR


@pytest.mark.parametrize("mode", MODES)
def test_severity_colours_are_readable_as_text(mode):
    """These are words in the checks list, not swatches.

    The equivalent chart series colours only reach 2.7:1 and 3.2:1 on the light
    surface, which is fine for a filled mark and not fine for a label.
    """
    p = palette(mode)
    for name in ("error", "warning", "ok"):
        colour = getattr(p, name)
        assert contrast_ratio(colour, p.surface) >= TEXT_FLOOR, f"{name} {colour}"
        assert contrast_ratio(colour, p.raised) >= TEXT_FLOOR, f"{name} {colour}"


def test_light_mode_uses_the_brand_colour_unmodified():
    """Nothing about a light surface requires compromising the brand."""
    p = palette("light")
    assert p.accent == BRAND_BLUE
    assert p.accent_fill == BRAND_BLUE


def test_dark_mode_splits_the_accent_in_two():
    p = palette("dark")
    assert p.accent != p.accent_fill
    # readable as text...
    assert contrast_ratio(p.accent, p.surface) >= TEXT_FLOOR
    # ...while the fill stays dark enough for white to sit on it
    assert contrast_ratio("#ffffff", p.accent_fill) > contrast_ratio("#ffffff", p.accent)


def test_the_data_palette_is_left_alone():
    """Chart colours answer to discrimination, not to the brand.

    If this ever fails, someone has pushed the brand blue into the series
    palette and quietly undone its colour-blind separation.
    """
    from cycloidgen.report import plots
    for mode in MODES:
        plots.set_theme(mode)
        assert BRAND_BLUE not in plots.theme()["series"]
    plots.set_theme("light")


# ------------------------------------------------------------------- helpers


def test_lighten_and_darken_move_the_right_way():
    assert contrast_ratio(lighten(BRAND_BLUE, 0.2), "#ffffff") < \
        contrast_ratio(BRAND_BLUE, "#ffffff")
    assert contrast_ratio(darken(BRAND_BLUE, 0.2), "#ffffff") > \
        contrast_ratio(BRAND_BLUE, "#ffffff")


def test_lighten_and_darken_clamp():
    assert lighten("#ffffff", 0.5) == "#ffffff"
    assert darken("#000000", 0.5) == "#000000"


def test_mix_interpolates():
    assert mix("#000000", "#ffffff", 0.0) == "#000000"
    assert mix("#000000", "#ffffff", 1.0) == "#ffffff"
    assert mix("#000000", "#ffffff", 0.5) == "#808080"


def test_contrast_ratio_endpoints():
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio("#123456", "#123456") == pytest.approx(1.0)


@pytest.mark.parametrize("mode", MODES)
def test_the_stylesheet_is_complete(mode):
    """A stray ``{p.foo}`` would render literally instead of raising."""
    css = stylesheet(mode)
    assert "{" in css and "}" in css
    assert "{p." not in css
    assert palette(mode).accent in css
    for widget in ("QPushButton", "QTabBar::tab", "QGroupBox", "QProgressBar",
                   "QTreeWidget", "QMenu", "QStatusBar"):
        assert widget in css


def test_an_unknown_mode_is_refused():
    with pytest.raises(ValueError):
        palette("midnight")


def test_the_shipped_assets_are_present():
    from cycloidgen.ui.branding import asset
    for name in ("mark-blue.png", "mark-white.png", "wordmark-blue.png",
                 "wordmark-white.png", "cycloidgen.ico"):
        assert asset(name).stat().st_size > 0


def test_a_missing_asset_says_how_to_regenerate_it():
    from cycloidgen.ui.branding import asset
    with pytest.raises(FileNotFoundError, match="make_assets"):
        asset("no-such-logo.png")
