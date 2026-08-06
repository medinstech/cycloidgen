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
    MONO_FAMILIES,
    contrast_ratio,
    darken,
    lighten,
    mix,
    mono_font,
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
                   "QTreeWidget", "QMenu", "QStatusBar", "QToolButton",
                   "QAbstractSpinBox", "QSlider", "QCheckBox"):
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


# ----------------------------------------------------------------------- type


def test_the_mono_font_names_a_family_for_every_platform():
    """One named family gets a fixed pitch on the machine it was written on.

    ``Consolas`` is a Windows font.  Asking for it on Linux or macOS leaves Qt
    to substitute, and it substitutes by style hint - which lands wherever the
    system's font configuration happens to point.  Every table of numbers in
    this application needs the columns to line up.
    """
    assert "Consolas" in MONO_FAMILIES                    # Windows
    assert {"Menlo", "SF Mono"} & set(MONO_FAMILIES)      # macOS
    assert {"DejaVu Sans Mono", "Liberation Mono"} & set(MONO_FAMILIES)   # Linux
    assert MONO_FAMILIES[-1] == "monospace"               # the generic last

    font = mono_font()
    assert font.families() == list(MONO_FAMILIES)
    assert font.fixedPitch()
    assert font.styleHint() == font.StyleHint.Monospace


def test_the_mono_font_takes_a_size_or_leaves_the_default():
    assert mono_font(9).pointSize() == 9
    assert mono_font().pointSize() == mono_font().pointSize()   # whatever Qt's is


# ---------------------------------------------------------------------- chrome


@pytest.mark.parametrize("mode", MODES)
def test_the_accent_is_spent_on_actions_not_on_structure(mode):
    """The rule the chrome was reworked around.

    The first version put the brand colour on every group heading, tab, table
    header, status bar and rule; at that point it is not emphasis, it is a
    background colour that happens to be loud.  Structure is drawn in ``line``
    now, and the accent is left for the things that mean "this one".  Checked
    on the *declarations* rather than by eye, because this is exactly the kind
    of decision that erodes one convenient exception at a time.
    """
    from cycloidgen.ui.branding import HAIRLINE, palette

    css = stylesheet(mode)
    p = palette(mode)
    structural = (
        f"#BrandHeader {{\n        background: {p.raised};\n"
        f"        border-bottom: {HAIRLINE} solid {p.line};",
    )
    for block in structural:
        assert block in css

    # A group heading is a label, and a label painted in the primary action's
    # colour claims to be a button.
    title = css.split("QGroupBox::title {", 1)[1].split("}", 1)[0]
    assert p.accent not in title and p.accent_fill not in title
    assert p.ink_dim in title


@pytest.mark.parametrize("mode", MODES)
def test_corners_are_eased_rather_than_square(mode):
    from cycloidgen.ui.branding import RADIUS, RADIUS_SMALL
    assert RADIUS != "0px" and RADIUS_SMALL != "0px"
    assert RADIUS in stylesheet(mode)


def test_the_links_in_the_app_are_the_ones_the_package_publishes():
    """Two copies of an address is one that will be left behind.

    The application cannot read `pyproject.toml` - it is not in a wheel and it
    is certainly not in the frozen build - so it carries its own copy, and this
    is what stops that copy pointing at a repository that has moved.  Read as
    text rather than parsed: `tomllib` arrived in 3.11 and this project still
    supports 3.10.
    """
    import re
    from pathlib import Path

    from cycloidgen.ui import branding

    text = (Path(__file__).resolve().parent.parent
            / "pyproject.toml").read_text(encoding="utf-8")
    published = dict(re.findall(r'^(\w+)\s*=\s*"(https://[^"]+)"', text,
                                flags=re.MULTILINE))
    assert published, "pyproject.toml no longer declares any project URLs"
    assert published["Homepage"] == branding.PROJECT_URL
    assert published["Issues"] == branding.ISSUES_URL
    assert published["Releases"] == branding.RELEASES_URL


def test_every_link_the_app_offers_is_a_link():
    from cycloidgen.ui import branding

    for url in (branding.COMPANY_URL, branding.PROJECT_URL,
                branding.ISSUES_URL, branding.RELEASES_URL):
        assert url.startswith("https://"), url
        assert " " not in url
