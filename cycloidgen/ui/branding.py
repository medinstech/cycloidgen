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

from PySide6.QtGui import QFont, QIcon, QPixmap

__all__ = [
    "BRAND_BLUE",
    "COMPANY",
    "COMPANY_URL",
    "ISSUES_URL",
    "MONO_FAMILIES",
    "PROJECT_URL",
    "RELEASES_URL",
    "TAGLINE",
    "Palette",
    "asset",
    "contrast_ratio",
    "logo_pixmap",
    "mono_font",
    "palette",
    "stylesheet",
    "window_icon",
]

COMPANY = "Medinstech"
COMPANY_URL = "https://medinstech.com"
TAGLINE = "Build the Future, Link by Link"

#: Where the project lives.  Declared here because the application needs them at
#: runtime and `pyproject.toml` is not readable from an installed wheel, let
#: alone from the frozen build - but they are the *same* addresses the package
#: metadata publishes, and `tests/test_branding.py` holds the two together so a
#: repository that moves cannot leave the Help menu pointing at the old one.
PROJECT_URL = "https://github.com/medinstech/cycloidgen"
ISSUES_URL = f"{PROJECT_URL}/issues"
RELEASES_URL = f"{PROJECT_URL}/releases"

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
        # Two generators write into this folder and they are not interchangeable:
        # the brand assets are trimmed from masters that are not in the tree,
        # the icon is drawn from the profile equations.  Naming the wrong one
        # sends whoever hit this looking for logos they were never given.
        tool = "make_icon" if _is_app_icon(name) else "make_assets"
        raise FileNotFoundError(f"missing asset {name!r}; run tools/{tool}.py")
    return path


def _is_app_icon(name: str) -> bool:
    return name.startswith("icon-") or name.endswith(".ico")


#: Monospace families in preference order, first one present wins.  Numbers in
#: a proportional face do not line up, and a column of unaligned magnitudes is a
#: column you have to read one row at a time - so every table of numbers in this
#: application asks for a fixed pitch.  Naming one family gets that on the
#: machine it was written on: ``Consolas`` is a Windows font, and asking for it
#: on Linux or macOS leaves Qt to substitute, which it does by *style hint* and
#: usually lands on something proportional-looking anyway.  One list per
#: platform's own good monospace, and the hint underneath as the last resort.
MONO_FAMILIES: tuple[str, ...] = (
    "Consolas",             # Windows
    "SF Mono", "Menlo",     # macOS
    "DejaVu Sans Mono", "Liberation Mono", "Noto Sans Mono",   # Linux
    "Courier New", "monospace",
)


def mono_font(point_size: int | None = None) -> QFont:
    """The application's fixed-pitch face, on whatever platform this is."""
    font = QFont()
    font.setFamilies(list(MONO_FAMILIES))
    font.setStyleHint(QFont.Monospace)
    font.setFixedPitch(True)
    if point_size is not None:
        font.setPointSize(point_size)
    return font


@lru_cache(maxsize=8)
def window_icon() -> QIcon:
    """The application's own icon: the disc, not the company mark.

    A cycloidal disc drawn from :func:`cycloidgen.core.profile.disc_profile` by
    ``tools/make_icon.py`` - the program's subject rather than its author, which
    is what someone scanning a task bar for this window is looking for.  The
    .ico carries a separately drawn image per size and Qt picks between them;
    the PNG is the fallback for a build where the .ico did not ship.
    """
    icon = QIcon()
    for name in ("cycloidgen.ico", "icon-256.png"):
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

#: Corners are eased, not square.  The first version of this chrome was
#: deliberately brutalist - every corner square, every edge a drawn rule, flat
#: blocks of the brand colour - on the argument that a tool for reading numbers
#: off a machine should not decorate.  Living with it said otherwise: at this
#: density the hard edges read as unfinished rather than as rigorous, and the
#: brand blue at full saturation on every group heading, tab and rule left
#: nowhere for the eye to rest.  So the structure is still drawn rather than
#: implied by shadow, but the corners are eased and the accent is spent only
#: where it means *this one*.
RADIUS = "5px"
#: Indicators, handles and anything under about 16 px, where 5 px would read as
#: a circle rather than as an eased corner.
RADIUS_SMALL = "3px"

#: One weight of line for structure.  A second, heavier one existed to mark
#: "important" edges and ended up on so many of them that it marked nothing.
HAIRLINE = "1px"
#: The exception: a focus ring has to be findable without being read, so it is
#: the one border allowed to be thicker than a hairline.
FOCUS = "2px"


def stylesheet(mode: str = "light") -> str:
    """Qt stylesheet for the whole application.

    Deliberately narrow in *scope*: it recolours and reshapes the native widgets
    rather than reimplementing them.  A stylesheet that redraws every control
    has to be re-tested against every Qt release and usually ends up less
    accessible than what it replaced.  Where a rule does displace native drawing
    - the combo arrow, the checkbox tick, the spin buttons - the glyph is
    supplied back, because dropping it is how a combo box ends up looking
    exactly like a line edit.

    Where the accent goes
    ---------------------
    Only where it means "this one": the primary action, the focused field, the
    selected row, the selected tab's underline, a ticked box, the filled part of
    a slider or a progress bar.  Everything structural - group borders, the
    header rule, table header underlines, the status bar, tooltips, splitters -
    is drawn in ``line``.  A saturated accent on every edge is not emphasis, it
    is a background colour that happens to be loud.
    """
    p = palette(mode)
    # Qt stylesheets take forward slashes on every platform, including Windows.
    tint = "dark" if p.is_dark else "light"
    down = (_ASSETS / f"chevron-down-{tint}.png").as_posix()
    up = (_ASSETS / f"chevron-up-{tint}.png").as_posix()
    tick = (_ASSETS / "tick.png").as_posix()
    # A hover that is not a selection: half a step, so a row under the pointer
    # and a row that is actually chosen do not look the same.
    hover = mix(p.raised, p.accent_wash, 0.55)

    return f"""
    QWidget {{
        background: {p.surface};
        color: {p.ink};
    }}
    QMainWindow::separator {{ background: {p.line}; width: {HAIRLINE};
                              height: {HAIRLINE}; }}

    /* A label must not paint its own background, or the generic QWidget rule
       above stamps a surface-coloured block over whatever it is sitting on -
       which is what put a dark rectangle behind every word in the header. */
    QLabel {{ background: transparent; }}
    QLabel:disabled {{ color: {p.ink_dim}; }}

    /* Brand header ---------------------------------------------------- */
    #BrandHeader {{
        background: {p.raised};
        border-bottom: {HAIRLINE} solid {p.line};
    }}
    #BrandProduct {{ color: {p.ink}; font-size: 16px; font-weight: 700; }}
    #BrandTagline {{ color: {p.ink_dim}; font-size: 11px; }}
    #BrandStatus {{ color: {p.ink}; font-size: 12px; font-weight: 600; }}

    /* The at-a-glance strip.  The caption is deliberately quiet and the value
       is not: the caption is read once, to learn what the column is, and the
       value is read every time the design changes.  Amber is spent only where
       a number has crossed a limit the analysis itself computes. */
    #StatCaption {{
        color: {p.ink_dim}; font-size: 9px; font-weight: 700;
        letter-spacing: 0.7px;
    }}
    #StatValue {{ color: {p.ink}; font-size: 13px; font-weight: 600; }}
    #StatValue[state="warning"] {{ color: {p.warning}; }}
    /* One hairline between columns.  Eight captions in a row, each wider than
       the number under it, read as one run of words - the eye has nothing to
       tell it where LOST MOTION stops and TEMPERATURE starts.  Styled here
       rather than set on the widget so it follows the theme with everything
       else. */
    #StatRule {{ background: {p.line}; }}
    /* The strip under the export buttons that says what this output is not.
       Amber ink on a hairline of the same colour, no fill: it has to be read
       on the hundredth session as well as the first, and a filled banner is
       decoration by the second.  It is also the one warning here that is not
       about a number crossing a limit, which is why it does not look like
       one. */
    #NoticeStrip {{
        color: {p.warning}; font-size: 10px;
        border: 1px solid {p.warning}; border-radius: 3px;
        padding: 5px 8px;
    }}
    #BrandFlag {{ color: {p.error}; font-size: 11px; font-weight: 700; }}

    /* Grouping: a card with its heading in the margin above it, rather than a
       filled badge sitting on the border.  The heading is a label, and a label
       painted in the primary action's colour claims to be a button. */
    QGroupBox {{
        background: {p.raised};
        border: {HAIRLINE} solid {p.line};
        border-radius: {RADIUS};
        margin-top: 17px;
        padding: 12px 10px 10px 10px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 3px;
        padding: 0 2px;
        background: transparent;
        color: {p.ink_dim};
        font-size: 11px;
        font-weight: 700;
    }}

    /* Inputs: recessed against the card they sit on. */
    QLineEdit, QAbstractSpinBox, QComboBox, QPlainTextEdit, QTextBrowser {{
        background: {p.surface};
        border: {HAIRLINE} solid {p.line};
        border-radius: {RADIUS};
        padding: 5px 8px;
        selection-background-color: {p.accent_fill};
        selection-color: {p.accent_text};
    }}
    QLineEdit:hover, QAbstractSpinBox:hover, QComboBox:hover {{
        border-color: {p.ink_dim};
    }}
    QLineEdit:focus, QAbstractSpinBox:focus, QComboBox:focus,
    QPlainTextEdit:focus {{
        border: {FOCUS} solid {p.accent};
        padding: 4px 7px;                    /* keeps the text from shifting */
    }}
    QLineEdit:disabled, QAbstractSpinBox:disabled, QComboBox:disabled {{
        color: {p.ink_dim}; background: {p.raised}; border-color: {p.line};
    }}

    QTextBrowser {{ background: {p.raised}; padding: 8px 10px; }}

    QComboBox::drop-down {{
        border: none; width: 22px; margin: 0;
    }}
    QComboBox::down-arrow {{ image: url({down}); width: 11px; height: 11px; }}
    QComboBox::down-arrow:disabled {{ image: none; }}
    QComboBox QAbstractItemView {{
        background: {p.raised};
        border: {HAIRLINE} solid {p.line};
        border-radius: {RADIUS};
        selection-background-color: {p.accent_wash};
        selection-color: {p.ink};
        padding: 3px;
        outline: none;
    }}

    /* Spin buttons.  Two stacked hit targets with no chrome of their own: the
       divider line they used to carry made them read as a separate control
       bolted to the side of the field. */
    QAbstractSpinBox {{ padding-right: 22px; }}
    QAbstractSpinBox:focus {{ padding-right: 21px; }}
    QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
        subcontrol-origin: border;
        background: transparent;
        border: none;
        border-radius: {RADIUS_SMALL};
        width: 19px;
        margin: 2px 2px 2px 0;
    }}
    QAbstractSpinBox::up-button {{ subcontrol-position: top right; }}
    QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; }}
    QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{
        background: {p.accent_wash};
    }}
    QAbstractSpinBox::up-arrow {{ image: url({up}); width: 9px; height: 9px; }}
    QAbstractSpinBox::down-arrow {{ image: url({down}); width: 9px; height: 9px; }}
    QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::down-arrow:disabled {{
        image: none;
    }}

    /* Buttons --------------------------------------------------------- */
    QPushButton {{
        background: {p.raised};
        border: {HAIRLINE} solid {p.line};
        border-radius: {RADIUS};
        padding: 6px 14px;
        color: {p.ink};
        font-weight: 600;
    }}
    QPushButton:hover {{ background: {hover}; border-color: {p.ink_dim}; }}
    QPushButton:pressed {{ background: {p.accent_wash}; }}
    QPushButton:disabled {{ color: {p.ink_dim}; border-color: {p.line};
                            background: {p.surface}; }}
    QPushButton:checked {{
        background: {p.accent_wash}; color: {p.ink};
        border-color: {p.accent};
    }}
    /* The one action a panel wants you to take, and the only filled block of
       brand colour left in the window.  Its border is the lighter `accent`, not
       the fill - on the dark surface the fill alone sits at 2.3:1 against the
       page, under the 3:1 floor for finding a control, and lightening the fill
       would wreck the white label on it.  The edge carries the boundary. */
    QPushButton[primary="true"] {{
        background: {p.accent_fill};
        color: {p.accent_text};
        border: {HAIRLINE} solid {p.accent};
        font-weight: 700;
    }}
    QPushButton[primary="true"]:hover {{ background: {p.accent_hover};
                                         color: {p.accent_text}; }}
    QPushButton[primary="true"]:pressed {{ background: {p.accent_pressed}; }}
    QPushButton[primary="true"]:disabled {{
        background: {p.line}; color: {p.ink_dim}; border-color: {p.line};
    }}

    /* Tabs: an underline marks the selected one.  A filled block does the same
       job and takes the brand colour into the middle of the window to do it. */
    QTabWidget::pane {{
        background: {p.raised};
        border: {HAIRLINE} solid {p.line};
        border-radius: {RADIUS};
        top: -1px;
    }}
    QTabBar {{ background: transparent; }}
    QTabBar::tab {{
        background: transparent;
        color: {p.ink_dim};
        border: none;
        border-bottom: {FOCUS} solid transparent;
        padding: 8px 14px;
        margin: 0 1px 2px 1px;
        font-weight: 600;
    }}
    QTabBar::tab:hover {{ color: {p.ink}; }}
    QTabBar::tab:selected {{
        color: {p.ink};
        border-bottom: {FOCUS} solid {p.accent};
    }}

    /* The matplotlib navigation bar.  It arrives as a bare QToolBar of icon
       buttons and otherwise looks like a control panel from a different
       application parked on top of the drawing. */
    QToolBar {{ background: transparent; border: none; spacing: 1px;
                padding: 2px 4px; }}
    QToolBar::separator {{ background: {p.line}; width: {HAIRLINE};
                           margin: 4px 6px; }}
    QToolButton {{
        background: transparent;
        border: {HAIRLINE} solid transparent;
        border-radius: {RADIUS_SMALL};
        padding: 4px;
    }}
    QToolButton:hover {{ background: {hover}; border-color: {p.line}; }}
    QToolButton:pressed, QToolButton:checked {{
        background: {p.accent_wash}; border-color: {p.accent};
    }}
    #PlotCoords {{ color: {p.ink_dim}; padding-right: 6px; }}

    /* Lists and trees ------------------------------------------------- */
    QTreeWidget, QTreeView, QListView {{
        background: {p.raised};
        border: {HAIRLINE} solid {p.line};
        border-radius: {RADIUS};
        alternate-background-color: {mix(p.raised, p.surface, 0.55)};
        outline: none;
    }}
    QTreeWidget::item, QTreeView::item {{ padding: 4px 2px; border: none; }}
    QTreeWidget::item:hover, QTreeView::item:hover {{ background: {hover}; }}
    QTreeWidget::item:selected, QTreeView::item:selected {{
        background: {p.accent_wash};
        color: {p.ink};
    }}
    QHeaderView::section {{
        background: {p.raised};
        color: {p.ink_dim};
        border: none;
        border-bottom: {HAIRLINE} solid {p.line};
        padding: 6px;
        font-weight: 600;
    }}
    QHeaderView::section:hover {{ color: {p.ink}; }}

    /* Progress, sliders, scrollbars ----------------------------------- */
    QProgressBar {{
        background: {p.surface};
        border: {HAIRLINE} solid {p.line};
        border-radius: {RADIUS};
        text-align: center;
        color: {p.ink};
        font-weight: 600;
        height: 16px;
    }}
    QProgressBar::chunk {{ background: {p.accent_fill};
                           border-radius: {RADIUS_SMALL}; margin: 1px; }}

    QSlider::groove:horizontal {{
        background: {p.line}; height: 4px; border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{ background: {p.accent_fill};
                                    border-radius: 2px; }}
    /* Solid, not a ring.  At crank zero there is no filled groove behind it,
       so a hollow handle is a small empty box floating at the end of a line. */
    QSlider::handle:horizontal {{
        background: {p.accent};
        border: none;
        width: 14px; height: 14px;
        margin: -5px 0;
        border-radius: 7px;
    }}
    QSlider::handle:horizontal:hover {{ background: {p.accent_hover}; }}
    QSlider::handle:horizontal:pressed {{ background: {p.accent_pressed}; }}

    QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0;
                           border: none; }}
    QScrollBar::handle:vertical {{ background: {p.line}; min-height: 28px;
                                   border-radius: {RADIUS_SMALL}; margin: 2px; }}
    QScrollBar::handle:vertical:hover {{ background: {p.ink_dim}; }}
    QScrollBar:horizontal {{ background: transparent; height: 11px;
                             border: none; }}
    QScrollBar::handle:horizontal {{ background: {p.line}; min-width: 28px;
                                     border-radius: {RADIUS_SMALL}; margin: 2px; }}
    QScrollBar::handle:horizontal:hover {{ background: {p.ink_dim}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

    /* Chrome ---------------------------------------------------------- */
    QMenuBar {{ background: {p.raised};
                border-bottom: {HAIRLINE} solid {p.line}; }}
    QMenuBar::item {{ padding: 6px 11px; margin: 2px 1px;
                      border-radius: {RADIUS_SMALL}; }}
    QMenuBar::item:selected {{ background: {p.accent_wash}; color: {p.ink}; }}
    QMenu {{ background: {p.raised}; border: {HAIRLINE} solid {p.line};
             border-radius: {RADIUS}; padding: 4px; }}
    QMenu::item {{ padding: 6px 24px 6px 20px; border-radius: {RADIUS_SMALL}; }}
    QMenu::item:selected {{ background: {p.accent_wash}; color: {p.ink}; }}
    QMenu::item:disabled {{ color: {p.ink_dim}; }}
    QMenu::separator {{ height: {HAIRLINE}; background: {p.line};
                        margin: 4px 8px; }}

    QStatusBar {{ background: {p.raised};
                  border-top: {HAIRLINE} solid {p.line};
                  color: {p.ink_dim}; }}
    QStatusBar::item {{ border: none; }}
    QToolTip {{
        background: {p.raised}; color: {p.ink};
        border: {HAIRLINE} solid {p.line}; border-radius: {RADIUS};
        padding: 5px 8px;
    }}
    QScrollArea {{ border: none; }}

    /* The handle is the gap between two panels, and both already draw their
       own border.  Filling it as well puts a third line between them. */
    QSplitter::handle {{ background: transparent; }}
    QSplitter::handle:hover {{ background: {p.accent_wash}; }}
    QSplitter::handle:horizontal {{ width: 7px; }}
    QSplitter::handle:vertical {{ height: 7px; }}

    /* Same trap as the combo: a styled indicator loses the tick along with the
       native drawing, leaving a filled square that does not read as "on". */
    QCheckBox {{ spacing: 7px; background: transparent; }}
    QCheckBox::indicator {{
        width: 15px; height: 15px;
        border: {HAIRLINE} solid {p.ink_dim};
        border-radius: {RADIUS_SMALL};
        background: {p.surface};
    }}
    QCheckBox::indicator:checked {{
        background: {p.accent_fill};
        border-color: {p.accent_fill};
        image: url({tick});
    }}
    QCheckBox::indicator:hover {{ border-color: {p.accent}; }}
    QCheckBox::indicator:disabled {{ background: {p.raised};
                                     border-color: {p.line}; }}
    """
