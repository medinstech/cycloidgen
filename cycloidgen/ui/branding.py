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

__all__ = ["BRAND_BLUE", "Palette", "palette", "stylesheet", "asset",
           "window_icon", "logo_pixmap", "contrast_ratio", "COMPANY",
           "COMPANY_URL", "TAGLINE"]

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
    h, l, s = colorsys.rgb_to_hls(*_to_rgb(colour))
    return _to_hex(colorsys.hls_to_rgb(h, min(1.0, l + amount), s))


def darken(colour: str, amount: float) -> str:
    h, l, s = colorsys.rgb_to_hls(*_to_rgb(colour))
    return _to_hex(colorsys.hls_to_rgb(h, max(0.0, l - amount), s))


def mix(colour: str, other: str, weight: float) -> str:
    """``weight`` of ``other`` blended into ``colour``."""
    a, b = _to_rgb(colour), _to_rgb(other)
    return _to_hex(tuple(x + (y - x) * weight for x, y in zip(a, b)))


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


_LIGHT = Palette(
    mode="light",
    surface="#fcfcfb",
    raised="#ffffff",
    ink="#0b0b0b",
    ink_dim="#52514e",
    line="#e2e1dc",
    accent=BRAND_BLUE,
    accent_fill=BRAND_BLUE,
    accent_text="#ffffff",
    accent_hover=darken(BRAND_BLUE, 0.06),
    accent_pressed=darken(BRAND_BLUE, 0.12),
    accent_wash=mix("#ffffff", BRAND_BLUE, 0.10),
    # Darker than the matching chart series, on purpose: these are drawn as
    # *text* in the checks list and the comparison table, and the chart values
    # only reach 2.7:1 and 3.2:1 against this surface.  A series colour is a
    # filled mark; a severity colour is a word someone has to read.
    error="#c0392b",
    warning="#966d09",
    ok="#14835b",
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


def stylesheet(mode: str = "light") -> str:
    """Qt stylesheet for the whole application.

    Deliberately narrow: it recolours and calms the native widgets rather than
    redrawing them.  A stylesheet that replaces every control is a stylesheet
    that has to be re-tested against every Qt release, and it usually ends up
    less accessible than what it replaced.
    """
    p = palette(mode)
    return f"""
    QWidget {{
        background: {p.surface};
        color: {p.ink};
    }}
    QMainWindow::separator {{ background: {p.line}; width: 1px; height: 1px; }}

    /* Brand header ---------------------------------------------------- */
    #BrandHeader {{
        background: {p.raised};
        border-bottom: 2px solid {p.accent};
    }}
    #BrandProduct {{ color: {p.ink}; font-size: 15px; font-weight: 600; }}
    #BrandTagline {{ color: {p.ink_dim}; font-size: 11px; }}

    /* Grouping -------------------------------------------------------- */
    QGroupBox {{
        background: {p.raised};
        border: 1px solid {p.line};
        border-radius: 6px;
        margin-top: 14px;
        padding: 10px 8px 8px 8px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 10px;
        padding: 0 5px;
        color: {p.accent};
    }}

    /* Inputs ---------------------------------------------------------- */
    QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QPlainTextEdit {{
        background: {p.raised};
        border: 1px solid {p.line};
        border-radius: 4px;
        padding: 3px 6px;
        selection-background-color: {p.accent_fill};
        selection-color: {p.accent_text};
    }}
    QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus,
    QPlainTextEdit:focus {{
        border: 1px solid {p.accent};
    }}
    QLineEdit:disabled, QDoubleSpinBox:disabled, QSpinBox:disabled,
    QComboBox:disabled {{ color: {p.ink_dim}; background: {p.surface}; }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox QAbstractItemView {{
        background: {p.raised};
        border: 1px solid {p.line};
        selection-background-color: {p.accent_fill};
        selection-color: {p.accent_text};
    }}

    /* Buttons --------------------------------------------------------- */
    QPushButton {{
        background: {p.raised};
        border: 1px solid {p.line};
        border-radius: 5px;
        padding: 5px 14px;
        color: {p.ink};
    }}
    QPushButton:hover {{ border-color: {p.accent}; }}
    QPushButton:pressed {{ background: {p.accent_wash}; }}
    QPushButton:disabled {{ color: {p.ink_dim}; border-color: {p.line}; }}
    QPushButton:checked {{
        background: {p.accent_fill}; color: {p.accent_text};
        border-color: {p.accent_fill};
    }}
    /* The one action a panel wants you to take, filled in the brand. */
    /* The border is the lighter `accent`, not the fill.  On the dark surface
       the fill only reaches 2.3:1 - lightening it to fix that would wreck the
       white label sitting on it, so the *edge* carries the boundary contrast
       instead and the fill is left alone. */
    QPushButton[primary="true"] {{
        background: {p.accent_fill};
        color: {p.accent_text};
        border: 1px solid {p.accent};
        font-weight: 600;
    }}
    QPushButton[primary="true"]:hover {{ background: {p.accent_hover}; }}
    QPushButton[primary="true"]:pressed {{ background: {p.accent_pressed}; }}
    QPushButton[primary="true"]:disabled {{
        background: {p.line}; color: {p.ink_dim}; border-color: {p.line};
    }}

    /* Tabs ------------------------------------------------------------ */
    QTabWidget::pane {{ border: 1px solid {p.line}; border-radius: 6px; top: -1px; }}
    QTabBar::tab {{
        background: transparent;
        color: {p.ink_dim};
        padding: 7px 15px;
        margin-right: 2px;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:hover {{ color: {p.ink}; }}
    QTabBar::tab:selected {{
        color: {p.accent};
        border-bottom: 2px solid {p.accent};
        font-weight: 600;
    }}

    /* Lists and trees ------------------------------------------------- */
    QTreeWidget, QTreeView, QListView {{
        background: {p.raised};
        border: 1px solid {p.line};
        border-radius: 6px;
        alternate-background-color: {p.surface};
    }}
    QTreeWidget::item {{ padding: 3px 2px; }}
    QTreeWidget::item:selected, QTreeView::item:selected {{
        background: {p.accent_wash};
        color: {p.ink};
    }}
    QHeaderView::section {{
        background: {p.surface};
        color: {p.ink_dim};
        border: none;
        border-bottom: 1px solid {p.line};
        padding: 5px 6px;
        font-weight: 600;
    }}

    /* Progress, sliders, scrollbars ----------------------------------- */
    QProgressBar {{
        background: {p.surface};
        border: 1px solid {p.line};
        border-radius: 4px;
        text-align: center;
        color: {p.ink_dim};
        height: 14px;
    }}
    QProgressBar::chunk {{ background: {p.accent_fill}; border-radius: 3px; }}

    QSlider::groove:horizontal {{
        background: {p.line}; height: 4px; border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        background: {p.accent};
        width: 14px; height: 14px;
        margin: -6px 0;
        border-radius: 7px;
    }}
    QSlider::handle:horizontal:hover {{ background: {p.accent_hover}; }}

    QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
    QScrollBar::handle:vertical {{
        background: {p.line}; border-radius: 5px; min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {p.ink_dim}; }}
    QScrollBar:horizontal {{ background: transparent; height: 11px; }}
    QScrollBar::handle:horizontal {{
        background: {p.line}; border-radius: 5px; min-width: 28px;
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

    /* Chrome ---------------------------------------------------------- */
    QMenuBar {{ background: {p.raised}; border-bottom: 1px solid {p.line}; }}
    QMenuBar::item:selected {{ background: {p.accent_wash}; }}
    QMenu {{ background: {p.raised}; border: 1px solid {p.line}; padding: 4px; }}
    QMenu::item {{ padding: 5px 24px 5px 20px; }}
    QMenu::item:selected {{ background: {p.accent_wash}; }}
    QMenu::separator {{ height: 1px; background: {p.line}; margin: 4px 8px; }}

    QStatusBar {{ background: {p.raised}; border-top: 1px solid {p.line};
                  color: {p.ink_dim}; }}
    QStatusBar::item {{ border: none; }}
    QToolTip {{
        background: {p.ink}; color: {p.surface};
        border: none; padding: 5px 7px;
    }}
    QScrollArea {{ border: none; }}
    QSplitter::handle {{ background: {p.line}; }}
    QCheckBox::indicator {{
        width: 15px; height: 15px;
        border: 1px solid {p.line}; border-radius: 3px;
        background: {p.raised};
    }}
    QCheckBox::indicator:checked {{
        background: {p.accent_fill}; border-color: {p.accent_fill};
    }}
    QCheckBox::indicator:hover {{ border-color: {p.accent}; }}
    """
