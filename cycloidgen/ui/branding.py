"""Medinstech brand identity, applied to the application chrome.

Where the brand colour goes, and where it does not
--------------------------------------------------
The brand blue is ``#0d00ff`` - fully saturated, and deliberately loud.  It is
used here for *chrome*: primary actions, the selected tab, focus rings,
selection, progress.  Those are places where one colour has to say "this one",
and loud is exactly right.

It is **not** used for data.  The chart palette in
:mod:`cycloidgen.report.plots` was chosen so that its three series stay
distinguishable to a colour-blind reader and keep their contrast against both
surfaces; dropping a fourth, far more saturated hue into it would undo that for
no gain but familiarity.  A chart is read, not admired.  The two palettes are
related by hue and separated by job.

Contrast
--------
``#0d00ff`` is dark enough that white sits on it at 8.6:1, so filled brand
buttons carry white text.  The same colour *as* text needs a light surface: on
the dark surface it falls to 2.8:1, well under the 4.5:1 floor, so dark mode
uses a lightened tint instead.  :func:`contrast_ratio` and the accompanying test
keep those pairs honest rather than asserted.
"""
from __future__ import annotations

import colorsys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PySide6.QtGui import QIcon, QPixmap

__all__ = [
    "BRAND_BLUE",
    "COMPANY",
    "COMPANY_URL",
    "TAGLINE",
    "Palette",
    "asset",
    "contrast_ratio",
    "logo_pixmap",
    "palette",
    "stylesheet",
    "window_icon",
]

COMPANY = "Medinstech"
COMPANY_URL = "https://medinstech.com"
TAGLINE = "Build the Future, Link by Link"

#: Sampled from the brand masters, not eyeballed from a screenshot.
BRAND_BLUE = "#0d00ff"
#: The near-white the brand uses behind the mark; a hair cooler than paper.
BRAND_PAPER = "#f6f5ff"

_ASSETS = Path(__file__).resolve().parent / "assets"


# ------------------------------------------------------------------- colour --


def _to_rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}" for c in rgb)


def lighten(colour: str, amount: float) -> str:
    """Move a colour toward white in HLS, keeping its hue and saturation."""
    hue, lightness, sat = colorsys.rgb_to_hls(*_to_rgb(colour))
    return _to_hex(colorsys.hls_to_rgb(hue, min(1.0, lightness + amount), sat))


def darken(colour: str, amount: float) -> str:
    hue, lightness, sat = colorsys.rgb_to_hls(*_to_rgb(colour))
    return _to_hex(colorsys.hls_to_rgb(hue, max(0.0, lightness - amount), sat))


def mix(colour: str, other: str, weight: float) -> str:
    """``weight`` of ``other`` blended into ``colour``."""
    a, b = _to_rgb(colour), _to_rgb(other)
    return _to_hex(tuple(x + (y - x) * weight for x, y in zip(a, b, strict=True)))


def _relative_luminance(colour: str) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in _to_rgb(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG contrast ratio, 1.0 (invisible) to 21.0 (black on white)."""
    a, b = _relative_luminance(foreground), _relative_luminance(background)
    lo, hi = sorted((a, b))
    return (hi + 0.05) / (lo + 0.05)


@dataclass(frozen=True)
class Palette:
    """Chrome colours for one appearance mode."""

    mode: str
    surface: str            # window background
    raised: str             # panels, group boxes, inputs
    ink: str                # primary text
    ink_dim: str            # secondary text
    line: str               # borders and separators

    # The accent has two jobs that pull in opposite directions, so it is two
    # colours.  As *text* on this surface it must be light enough to read; as a
    # *fill* under white text it must stay dark enough for the white to read.
    # One value cannot do both on a dark surface - it lands at 3.4:1 either way.
    accent: str             # text, borders, the selected tab
    accent_fill: str        # filled buttons and progress
    accent_text: str        # text placed on accent_fill
    accent_hover: str
    accent_pressed: str
    accent_wash: str        # selection and hover backgrounds
    error: str
    warning: str
    ok: str

    @property
    def is_dark(self) -> bool:
        return self.mode == "dark"


#: The light surface is paper, not a lightbox.  White is the absence of a
#: decision; this is white carrying a little of the brand's own hue, which is
#: where ``BRAND_PAPER`` came from in the first place - it is the tone behind
#: the logo.  The raised surface *is* that tone, and the page sits a shade
#: below it so panels read as raised without a shadow.
_LIGHT = Palette(
    mode="light",
    surface=mix("#ffffff", BRAND_BLUE, 0.07),      # #eeedff
    raised=mix("#ffffff", BRAND_BLUE, 0.04),       # #f5f5ff, the brand paper
    ink=mix("#0b0b0b", BRAND_BLUE, 0.07),
    ink_dim=mix("#52514e", BRAND_BLUE, 0.12),
    line=mix(mix("#ffffff", BRAND_BLUE, 0.07), mix("#0b0b0b", BRAND_BLUE, 0.07), 0.16),
    accent=BRAND_BLUE,
    accent_fill=BRAND_BLUE,
    accent_text="#ffffff",
    accent_hover=darken(BRAND_BLUE, 0.06),
    accent_pressed=darken(BRAND_BLUE, 0.12),
    # Deeper than it was: on a tinted page a 10% wash is nearly the page
    # itself, and a selection you cannot see is not a selection.
    accent_wash=mix("#ffffff", BRAND_BLUE, 0.20),
    # Darker than the matching chart series, on purpose: these are drawn as
    # *text* in the checks list and the comparison table, and the chart values
    # only reach 2.7:1 and 3.2:1 against this surface.  A series colour is a
    # filled mark; a severity colour is a word someone has to read.  They are
    # darker again for the tinted page, which is dimmer than the white it
    # replaced and so gives dark text less to work against.
    error="#c0392b",
    warning="#886308",
    ok="#137a55",
)

#: On the dark surface the brand blue as text reaches only 2.8:1, so ``accent``
#: is lightened until it clears the 4.5:1 floor.  ``accent_fill`` stays near the
#: brand, because it is the white sitting *on* it that has to be legible - and
#: lightening the fill is precisely what would ruin that.
_DARK = Palette(
    mode="dark",
    surface="#1a1a19",
    raised="#232322",
    ink="#ffffff",
    ink_dim="#c3c2b7",
    line="#3a3a36",
    accent=lighten(BRAND_BLUE, 0.24),
    accent_fill=lighten(BRAND_BLUE, 0.06),
    accent_text="#ffffff",
    accent_hover=lighten(BRAND_BLUE, 0.12),
    accent_pressed=BRAND_BLUE,
    accent_wash=mix("#232322", BRAND_BLUE, 0.28),
    # Checked against `raised`, not just `surface`: panels sit a shade lighter
    # than the window, so the raised surface is the harder of the two and the
    # one a findings list actually renders on.
    error="#e26457",
    warning="#eda100",
    ok="#199e70",
)


def palette(mode: str) -> Palette:
    if mode == "dark":
        return _DARK
    if mode == "light":
        return _LIGHT
    raise ValueError(f"unknown appearance mode {mode!r}")


# ------------------------------------------------------------------ assets --


def asset(name: str) -> Path:
    path = _ASSETS / name
    if not path.exists():
        raise FileNotFoundError(f"missing brand asset {name!r}; run tools/make_assets.py")
    return path


@lru_cache(maxsize=8)
def window_icon() -> QIcon:
    icon = QIcon()
    for name in ("cycloidgen.ico", "mark-blue.png"):
        candidate = _ASSETS / name
        if candidate.exists():
            icon.addFile(str(candidate))
    return icon


def logo_pixmap(kind: str = "wordmark", mode: str = "light",
                height: int = 26) -> QPixmap:
    """A logo scaled to ``height``, tinted for the surface it will sit on."""
    tint = "white" if mode == "dark" else "blue"
    pixmap = QPixmap(str(asset(f"{kind}-{tint}.png")))
    if pixmap.isNull():                                   # pragma: no cover
        return pixmap
    from PySide6.QtCore import Qt
    return pixmap.scaledToHeight(height, Qt.SmoothTransformation)


# -------------------------------------------------------------- stylesheet --

#: Nothing is rounded.  A radius is a softening gesture, and this is a tool for
#: reading numbers off a machine: every corner is square and every edge is a
#: line you can see.  The brand mark is flat, heavy and single-colour; the
#: chrome follows it rather than decorating around it.
RADIUS = "0px"

#: Structure is drawn, not implied by shadow.  One hairline for ordinary
#: separation, one heavy rule for anything that divides the window.
HAIRLINE = "1px"
RULE = "2px"


def stylesheet(mode: str = "light") -> str:
    """Qt stylesheet for the whole application.

    Deliberately narrow in *scope*: it recolours and squares off the native
    widgets rather than reimplementing them.  A stylesheet that redraws every
    control has to be re-tested against every Qt release and usually ends up
    less accessible than what it replaced.  Where a rule does displace native
    drawing - the combo arrow, the checkbox tick, the spin buttons - the glyph
    is supplied back, because dropping it is how a combo box ends up looking
    exactly like a line edit.
    """
    p = palette(mode)
    # Qt stylesheets take forward slashes on every platform, including Windows.
    tint = "dark" if p.is_dark else "light"
    down = (_ASSETS / f"chevron-down-{tint}.png").as_posix()
    up = (_ASSETS / f"chevron-up-{tint}.png").as_posix()
    tick = (_ASSETS / "tick.png").as_posix()

    return f"""
    QWidget {{
        background: {p.surface};
        color: {p.ink};
    }}
    QMainWindow::separator {{ background: {p.line}; width: {RULE}; height: {RULE}; }}

    /* A label must not paint its own background, or the generic QWidget rule
       above stamps a surface-coloured block over whatever it is sitting on -
       which is what put a dark rectangle behind every word in the header. */
    QLabel {{ background: transparent; }}

    /* Brand header ---------------------------------------------------- */
    #BrandHeader {{
        background: {p.raised};
        border-bottom: 3px solid {p.accent};
    }}
    #BrandProduct {{ color: {p.ink}; font-size: 17px; font-weight: 800; }}
    #BrandTagline {{ color: {p.ink_dim}; font-size: 11px; }}
    #BrandStatus {{ color: {p.ink}; font-size: 12px; font-weight: 700; }}

    /* Grouping -------------------------------------------------------- */
    QGroupBox {{
        background: {p.surface};
        border: {HAIRLINE} solid {p.line};
        border-left: {RULE} solid {p.accent};
        border-radius: {RADIUS};
        margin-top: 15px;
        padding: 12px 8px 8px 8px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 0px;
        padding: 2px 7px;
        background: {p.accent_fill};
        color: {p.accent_text};
        font-weight: 800;
    }}

    /* Inputs ---------------------------------------------------------- */
    QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QPlainTextEdit {{
        background: {p.raised};
        border: {HAIRLINE} solid {p.line};
        border-radius: {RADIUS};
        padding: 4px 6px;
        selection-background-color: {p.accent_fill};
        selection-color: {p.accent_text};
    }}
    QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus,
    QPlainTextEdit:focus {{
        border: {RULE} solid {p.accent};
        padding: 3px 5px;                    /* keeps the text from shifting */
    }}
    QLineEdit:disabled, QDoubleSpinBox:disabled, QSpinBox:disabled,
    QComboBox:disabled {{ color: {p.ink_dim}; background: {p.surface}; }}

    QComboBox::drop-down {{
        border: none; border-left: {HAIRLINE} solid {p.line};
        width: 20px; margin: 0;
    }}
    QComboBox::down-arrow {{ image: url({down}); width: 13px; height: 13px; }}
    QComboBox::down-arrow:disabled {{ image: none; }}
    QComboBox QAbstractItemView {{
        background: {p.raised};
        border: {RULE} solid {p.accent};
        border-radius: {RADIUS};
        selection-background-color: {p.accent_fill};
        selection-color: {p.accent_text};
        outline: none;
    }}

    /* Spin buttons: narrow, flat, hard against the edge.  The native ones are
       wide bevelled blocks that eat a third of the field. */
    QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
        subcontrol-origin: border;
        background: transparent;
        border: none;
        border-left: {HAIRLINE} solid {p.line};
        width: 20px;
    }}
    QAbstractSpinBox::up-button {{ subcontrol-position: top right; }}
    QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; }}
    QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{
        background: {p.accent_wash};
    }}
    QAbstractSpinBox::up-arrow {{ image: url({up}); width: 13px; height: 13px; }}
    QAbstractSpinBox::down-arrow {{ image: url({down}); width: 13px; height: 13px; }}
    QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::down-arrow:disabled {{
        image: none;
    }}

    /* Buttons --------------------------------------------------------- */
    QPushButton {{
        background: {p.raised};
        border: {HAIRLINE} solid {p.ink_dim};
        border-radius: {RADIUS};
        padding: 6px 16px;
        color: {p.ink};
        font-weight: 700;
    }}
    QPushButton:hover {{ border-color: {p.accent}; color: {p.accent}; }}
    QPushButton:pressed {{ background: {p.accent_wash}; }}
    QPushButton:disabled {{ color: {p.ink_dim}; border-color: {p.line};
                            background: {p.surface}; }}
    QPushButton:checked {{
        background: {p.accent_fill}; color: {p.accent_text};
        border-color: {p.accent};
    }}
    /* The one action a panel wants you to take: a solid block of the brand.
       Its border is the lighter `accent`, not the fill - on the dark surface
       the fill alone sits at 2.3:1 against the page, under the 3:1 floor for
       finding a control, and lightening the fill would wreck the white label
       on it.  The edge carries the boundary instead. */
    QPushButton[primary="true"] {{
        background: {p.accent_fill};
        color: {p.accent_text};
        border: {RULE} solid {p.accent};
        padding: 5px 15px;
        font-weight: 800;
    }}
    QPushButton[primary="true"]:hover {{ background: {p.accent_hover};
                                         color: {p.accent_text}; }}
    QPushButton[primary="true"]:pressed {{ background: {p.accent_pressed}; }}
    QPushButton[primary="true"]:disabled {{
        background: {p.line}; color: {p.ink_dim}; border-color: {p.line};
    }}

    /* Tabs: the selected one is a filled block, not a tinted label. */
    QTabWidget::pane {{
        background: {p.raised};
        border: {HAIRLINE} solid {p.line};
        border-top: {RULE} solid {p.accent};
        border-radius: {RADIUS};
        top: -1px;
    }}
    QTabBar::tab {{
        background: {p.surface};
        color: {p.ink_dim};
        border: {HAIRLINE} solid {p.line};
        border-bottom: none;
        border-radius: {RADIUS};
        padding: 7px 16px;
        margin-right: 3px;
        font-weight: 700;
    }}
    QTabBar::tab:hover {{ color: {p.ink}; border-color: {p.ink_dim}; }}
    QTabBar::tab:selected {{
        background: {p.accent_fill};
        color: {p.accent_text};
        border-color: {p.accent};
    }}

    /* Lists and trees ------------------------------------------------- */
    QTreeWidget, QTreeView, QListView {{
        background: {p.raised};
        border: {HAIRLINE} solid {p.line};
        border-radius: {RADIUS};
        alternate-background-color: {p.surface};
        outline: none;
    }}
    QTreeWidget::item {{ padding: 4px 2px; border: none; }}
    QTreeWidget::item:selected, QTreeView::item:selected {{
        background: {p.accent_wash};
        color: {p.ink};
    }}
    QHeaderView::section {{
        background: {p.surface};
        color: {p.ink};
        border: none;
        border-bottom: {RULE} solid {p.accent};
        border-right: {HAIRLINE} solid {p.line};
        padding: 6px;
        font-weight: 800;
    }}

    /* Progress, sliders, scrollbars ----------------------------------- */
    QProgressBar {{
        background: {p.surface};
        border: {HAIRLINE} solid {p.ink_dim};
        border-radius: {RADIUS};
        text-align: center;
        color: {p.ink};
        font-weight: 700;
        height: 16px;
    }}
    QProgressBar::chunk {{ background: {p.accent_fill}; }}

    QSlider::groove:horizontal {{
        background: {p.line}; height: 5px; border-radius: {RADIUS};
    }}
    QSlider::sub-page:horizontal {{ background: {p.accent_fill}; }}
    QSlider::handle:horizontal {{
        background: {p.accent_fill};
        border: {RULE} solid {p.accent};
        width: 12px; height: 16px;
        margin: -7px 0;
        border-radius: {RADIUS};
    }}
    QSlider::handle:horizontal:hover {{ background: {p.accent_hover}; }}

    QScrollBar:vertical {{ background: {p.surface}; width: 12px; margin: 0;
                           border-left: {HAIRLINE} solid {p.line}; }}
    QScrollBar::handle:vertical {{ background: {p.ink_dim}; min-height: 30px;
                                   border-radius: {RADIUS}; }}
    QScrollBar::handle:vertical:hover {{ background: {p.accent}; }}
    QScrollBar:horizontal {{ background: {p.surface}; height: 12px;
                             border-top: {HAIRLINE} solid {p.line}; }}
    QScrollBar::handle:horizontal {{ background: {p.ink_dim}; min-width: 30px;
                                     border-radius: {RADIUS}; }}
    QScrollBar::handle:horizontal:hover {{ background: {p.accent}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

    /* Chrome ---------------------------------------------------------- */
    QMenuBar {{ background: {p.raised};
                border-bottom: {HAIRLINE} solid {p.line}; }}
    QMenuBar::item {{ padding: 6px 12px; font-weight: 700; }}
    QMenuBar::item:selected {{ background: {p.accent_fill};
                               color: {p.accent_text}; }}
    QMenu {{ background: {p.raised}; border: {RULE} solid {p.accent};
             border-radius: {RADIUS}; padding: 2px; }}
    QMenu::item {{ padding: 6px 26px 6px 22px; }}
    QMenu::item:selected {{ background: {p.accent_fill}; color: {p.accent_text}; }}
    QMenu::separator {{ height: {HAIRLINE}; background: {p.line}; margin: 4px 0; }}

    QStatusBar {{ background: {p.raised};
                  border-top: {RULE} solid {p.accent};
                  color: {p.ink_dim}; }}
    QStatusBar::item {{ border: none; }}
    QToolTip {{
        background: {p.ink}; color: {p.surface};
        border: {RULE} solid {p.accent}; border-radius: {RADIUS};
        padding: 5px 7px;
    }}
    QScrollArea {{ border: none; }}
    QSplitter::handle {{ background: {p.line}; }}
    QSplitter::handle:hover {{ background: {p.accent}; }}
    QSplitter::handle:horizontal {{ width: {RULE}; }}
    QSplitter::handle:vertical {{ height: {RULE}; }}

    /* Same trap as the combo: a styled indicator loses the tick along with the
       native drawing, leaving a filled square that does not read as "on". */
    QCheckBox {{ spacing: 7px; }}
    QCheckBox::indicator {{
        width: 15px; height: 15px;
        border: {RULE} solid {p.ink_dim};
        border-radius: {RADIUS};
        background: {p.raised};
    }}
    QCheckBox::indicator:checked {{
        background: {p.accent_fill};
        border-color: {p.accent};
        image: url({tick});
    }}
    QCheckBox::indicator:hover {{ border-color: {p.accent}; }}
    QCheckBox::indicator:disabled {{ background: {p.surface};
                                     border-color: {p.line}; }}
    """
