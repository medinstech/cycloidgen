"""The desktop application window."""
from __future__ import annotations

import json
import logging
import traceback
from pathlib import Path

import matplotlib

matplotlib.use("QtAgg")

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as Canvas
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QKeySequence, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, notice
from ..analysis import DesignAnalysis, analyse
from ..core.designfile import (
    design_dict,
    numbers_may_have_moved,
    provenance,
    spec_from_dict,
    written_by,
)
from ..core.explain import explain, margin
from ..core.guide import guide
from ..core.spec import GearSpec, OffsetMode, OutputMember, Process, preset
from ..core.validate import Severity
from ..export import animation, write_bundle
from ..export.manifest import group_keys
from ..report import plots
from ..units import Unit, unit
from . import branding
from .fields import CODE_FIELDS, GROUPS, Field, codes_for_field
from .history import SpecHistory
from .logpanel import LogPanel, logger
from .logpanel import install as install_logging
from .optimise_dialog import OptimiseDialog
from .outputs import OutputsTab
from .plotbar import PlotToolbar
from .settings import app_settings
from .tables import WrappingColumn
from .tradestudy import TradeStudyTab
from .view3d import Assembly3DTab

_MAX_RECENT = 8

#: Animation tick.  30 Hz, not 25: the drawing now costs about 10 ms a frame
#: instead of 25, so there is room for it, and the difference between 25 and 30
#: is the difference between a mechanism turning and a mechanism stepping.
_FRAME_MS = 33

#: Degrees of input per frame at 1x - one input revolution in four seconds.
_CRANK_STEP_DEG = 3.0

#: Input rpm the animation actually shows at 1x, derived from the two constants
#: above rather than written down beside them, because a rate stated twice is a
#: rate that ends up disagreeing with itself.  It came to 15.2 rpm while the
#: tooltip claimed "input revolutions per second", which is 60 - the control
#: had no honest answer to "1x of what?" for as long as it has existed.
_PLAYBACK_RPM_AT_1X = _CRANK_STEP_DEG / _FRAME_MS * 1000.0 / 360.0 * 60.0

#: The checks list never gets smaller than this.  Four rows and the filter
#: strip: enough to see that findings exist and what the worst one is.
_MIN_CHECKS_PX = 130

#: The checks list's columns.  DETAIL is the one that carries a sentence.
_DETAIL_COL = 4

#: The compare tab before there is anything to compare against.  Declared once
#: because it is set in two places - when the tab is built and whenever the
#: reference is cleared - and a state that describes itself differently
#: depending on how it was reached is a state nobody trusts.
_NOTHING_PINNED = (
    "Nothing pinned yet. Press <b>Pin as reference</b> to freeze the current "
    "design, then change things: this tab shows what moved and the drawing "
    "shows the old outline underneath.")

#: The at-a-glance strip, as ``(key, caption, tooltip)``.  Ordered the way a
#: drive is read: what it is, how big it is, then what it does and what that
#: costs.  Every one of them carries its own name, because a row of bare values
#: is a summary only its author can read - and the tooltip carries the sentence
#: that will not fit under a caption, since half of these are quantities with a
#: qualification attached rather than plain readings.
_HEADER_STATS: tuple[tuple[str, str, str], ...] = (
    ("ratio", "RATIO", "Reduction: input turns per output turn"),
    ("od", "OD", "Outside diameter, across the housing"),
    ("length", "LENGTH", "Envelope length: the barrel plus both end plates"),
    ("mass", "MASS", "Assembled mass of every made part"),
    ("capacity", "CAPACITY",
     "Torque capacity with clearance - derated for load concentrating on the "
     "few pins that are actually in mesh. Amber when it is under the torque "
     "this design is rated for."),
    ("efficiency", "EFFICIENCY",
     "Output power over input power at the duty point"),
    ("backlash", "LOST MOTION",
     "Play at the output before it moves, in arcminutes, with the torque "
     "reversed"),
    ("temperature", "TEMPERATURE",
     "Steady-state running temperature at the housing. Amber past the limit "
     "the materials in this design allow."),
)


def _severity_colours(mode: str) -> dict[Severity, QColor]:
    """Severity ink for the current surface.

    Taken from the theme rather than hard-coded, because these are read as
    words: the equivalent chart colours are tuned for filled marks and fall
    below the text contrast floor when used for a label.
    """
    p = branding.palette(mode)
    return {Severity.ERROR: QColor(p.error),
            Severity.WARNING: QColor(p.warning),
            Severity.INFO: QColor(p.ink_dim)}


def _section(label: str, dim: str, body: str) -> str:
    """One labelled block of the explanation panel."""
    return (f"<div style='color:{dim};font-size:10px;font-weight:700;"
            f"letter-spacing:.6px;margin-top:10px'>{label}</div>"
            f"<div style='margin-top:2px'>{body}</div>")


def _field_tooltip(field: Field) -> str:
    """Hover text for one parameter: what it is, and how to pick it.

    The panel is where the full answer lives, and the panel is at the other end
    of the window from the field being edited.  A tooltip is not a worse version
    of it - it is the same knowledge where the eye already is, and it costs no
    layout.  So this carries the first two parts and lets the panel keep the
    trade and the live check state, which are the parts worth crossing the
    window for.

    Two sources, and they are different kinds of fact rather than two copies of
    one.  ``Field.tip`` says how the *control* behaves - that zero means
    automatic here, that this one only applies when rollers are on - which is a
    property of the widget and belongs beside it.
    :mod:`cycloidgen.core.guide` says what the parameter is and how to choose
    it, which is engineering and would be the same in a command-line tool.
    """
    detail = guide(field.name)
    parts = []
    if detail is not None:
        parts.append(f"<p style='margin:0'>{detail.what}</p>")
        parts.append(f"<p style='margin:6px 0 0 0'>{detail.choosing}</p>")
    if field.tip:
        parts.append(f"<p style='margin:6px 0 0 0'><i>{field.tip}</i></p>")
    # Held to a readable measure: Qt lays a rich-text tooltip out at whatever
    # width the text wants, which for a paragraph is one very long line.
    return f"<div style='max-width:340px'>{''.join(parts)}</div>" if parts else ""


class ExportWorker(QThread):
    """Runs the export off the GUI thread - STEP/STL take about a second."""

    done = Signal(list)
    failed = Signal(str)

    def __init__(self, spec: GearSpec, directory: Path, groups: set[str]):
        super().__init__()
        self._spec, self._dir, self._groups = spec, directory, groups

    def run(self) -> None:
        try:
            logger.info("export started: %s (%s)", self._dir,
                        ", ".join(sorted(self._groups)))
            files = write_bundle(self._spec, self._dir, groups=self._groups)
            for path in files:
                logger.debug("wrote %s (%.0f kB)", path, path.stat().st_size / 1024)
            self.done.emit([str(p) for p in files])
        except Exception:
            logger.error("export failed\n%s", traceback.format_exc().rstrip())
            self.failed.emit(traceback.format_exc())


class AnimationWorker(QThread):
    """Renders the GIF off the GUI thread, a frame at a time.

    Several seconds of matplotlib on the GUI thread is a frozen window and a
    "not responding" title bar, and the one thing the user wants during it -
    how far along it is - is exactly what a blocked event loop cannot show.
    """

    progressed = Signal(int, int)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, spec: GearSpec, path: Path, plan: animation.Animation,
                 options: dict) -> None:
        super().__init__()
        self._spec, self._path, self._plan = spec, path, plan
        self._options = options
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _tick(self, done: int, total: int) -> None:
        # Raised inside the frame generator, which unwinds it through the GIF
        # writer: a half-written file is worse than none, and Pillow only
        # commits the frames it was given.
        if self._cancelled:
            raise InterruptedError("cancelled")
        self.progressed.emit(done, total)

    def run(self) -> None:
        try:
            logger.info("animation started: %s (%s)", self._path,
                        self._plan.describe())
            path = animation.write_gif(self._spec, self._path,
                                       animation=self._plan,
                                       progress=self._tick, **self._options)
            self.done.emit(str(path))
        except InterruptedError:
            self._path.unlink(missing_ok=True)
            logger.info("animation cancelled")
            self.failed.emit("")
        except Exception:
            logger.error("animation failed\n%s", traceback.format_exc().rstrip())
            self.failed.emit(traceback.format_exc())


class AnalysisWorker(QThread):
    """Re-analyses a design off the GUI thread.

    Each request carries a generation number.  The window only accepts a result
    whose generation is still the current one, so a slow analysis of a design
    the user has already moved past cannot overwrite a newer answer.
    """

    done = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, spec: GearSpec, generation: int) -> None:
        super().__init__()
        self._spec, self._generation = spec, generation

    def run(self) -> None:
        try:
            self.done.emit(self._generation, analyse(self._spec))
        except Exception as exc:
            logger.error("analysis failed for %s:1\n%s", self._spec.lobes,
                         traceback.format_exc().rstrip())
            self.failed.emit(self._generation, str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("cycloidgen - cycloidal drive generator")
        self.resize(1440, 940)

        # Built and hooked up before anything else, so a failure during start-up
        # lands somewhere the user can read instead of on a stderr they do not
        # have.
        self.log = LogPanel()
        install_logging(self.log)
        logger.info("cycloidgen starting")

        self._settings = app_settings()
        # A preset is nobody's saved work, so a fresh install has nothing to be
        # warned about.  Only a design that was actually restored can be stale.
        self._restored_session = False
        self._restored_from: str | None = None
        self.spec = self._restore_spec()
        self.analysis: DesignAnalysis | None = None
        self._pinned: GearSpec | None = None
        self._pinned_analysis: DesignAnalysis | None = None
        self._widgets: dict[str, QWidget] = {}
        self._rows: dict[str, tuple[QWidget, QWidget]] = {}
        self._groups: list[tuple[QGroupBox, list[str]]] = []
        self._updating = False
        self._crank = 0.0
        # The animation advances a float and rounds onto the integer slider, so
        # a quarter-speed run still moves rather than rounding its step to zero.
        self._crank_exact = 0.0
        self._profile_stale = False
        self._generation = 0
        self._last_codes: set[str] | None = None
        self._log_badge = 0
        self._splitter_restored = False
        # Numbers in a proportional face do not line up, and a column of
        # unaligned magnitudes is a column you have to read one row at a time.
        self._mono = branding.mono_font()
        self._workers: list[AnalysisWorker] = []
        self._history = SpecHistory(self.spec)
        self._highlighted: list[QWidget] = []
        # Which parameter the explanation panel is currently speaking about, or
        # None when it is the selected check's turn.
        self._focused_field: str | None = None

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(120)
        self._debounce.timeout.connect(self._recompute)

        self._anim = QTimer(self)
        self._anim.setInterval(_FRAME_MS)
        self._anim.timeout.connect(self._advance_crank)

        self.setWindowIcon(branding.window_icon())
        # Read the desktop's own theme once, before anything of ours is applied.
        # Asking again later reads back our stylesheet, so "follow system" would
        # answer with whatever we last painted and could never return to light.
        window = self.palette().color(QPalette.Window)
        self._system_mode = "dark" if window.lightness() < 128 else "light"
        self._unit: Unit = unit(str(self._settings.value("units", "mm")))
        plots.set_units(self._unit.key)
        self.appearance = self._settings.value("appearance", "system")
        if self.appearance not in ("system", "light", "dark"):
            self.appearance = "system"
        self.mode = self._resolve_mode(self.appearance)
        self._apply_theme_colours()

        self._build_ui()
        self._sync_preset_box()
        self._load_spec_into_widgets()
        self._recompute()

    # ------------------------------------------------------------------ build
    def _build_ui(self) -> None:
        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.addWidget(self._build_parameter_panel())
        self._splitter.addWidget(self._build_view_panel())
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([400, 1040])

        shell = QWidget()
        column = QVBoxLayout(shell)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._build_header())
        column.addWidget(self._splitter, 1)
        self.setCentralWidget(shell)

        self.setStatusBar(QStatusBar())
        self._build_status_link()
        self._build_menu()
        self._restore_workspace()

    # ----------------------------------------------------------- workspace
    def _restore_workspace(self) -> None:
        """Reopen on the layout the last session left.

        Each piece is restored independently and defensively: a stored value
        from an older build that no longer makes sense should cost a default,
        not a window that will not open.
        """
        settings = self._settings
        geometry = settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

        try:
            index = int(settings.value("tab", 0))
            if 0 <= index < self.tabs.count():
                self.tabs.setCurrentIndex(index)
        except (TypeError, ValueError):
            pass
        self._tab_changed(self.tabs.currentIndex())

        try:
            crank = int(settings.value("crank", 0))
        except (TypeError, ValueError):
            crank = 0
        self._crank_slider.setValue(max(0, min(359, crank)))
        self._view3d.restore_state()

        if self._restored_session and numbers_may_have_moved(self._restored_from):
            self._say(provenance(self._restored_from),
                      level=logging.WARNING, seconds=20)

    def showEvent(self, event) -> None:
        """Restore the split once the window actually has a size.

        Two things make this awkward, and both are worth knowing.  Applying it
        during construction cannot work - the splitter has not been laid out, so
        Qt rescales to a width the window does not have yet and then
        redistributes by stretch factor as soon as it is shown.  And a *pixel*
        split is the wrong thing to store anyway: reopen the window on a
        narrower screen and a remembered 600 px panel is most of it.

        So each split is stored as a fraction and reapplied on a zero timer,
        which runs after Qt has finished the layout pass this event belongs to.
        Both of them: the parameter panel against the views, and the views
        against the checks list.
        """
        super().showEvent(event)
        if self._splitter_restored:
            return
        self._splitter_restored = True
        QTimer.singleShot(0, self._restore_split)

    def _restore_split(self) -> None:
        self._apply_fraction(self._splitter, "splitter_fraction",
                             self._splitter.width())
        self._apply_fraction(self._view_split, "checks_fraction",
                             self._view_split.height())
        # A different key from the horizontal split this replaced: the stored
        # number used to be a share of *width* with the checks list first, and
        # restoring one of those into a vertical splitter would hand the whole
        # left panel to whichever pane the old fraction happened to favour.
        self._apply_fraction(self._explain_split, "explain_height_fraction",
                             self._explain_split.height())

    def _apply_fraction(self, splitter: QSplitter, key: str, total: int) -> None:
        """Give the first pane ``key`` of ``total``, if that is a sane thing to do."""
        try:
            fraction = float(self._settings.value(key, 0.0))
        except (TypeError, ValueError):
            return
        if not 0.05 <= fraction <= 0.95 or total <= 0:
            return
        first = round(fraction * total)
        splitter.setSizes([first, total - first])

    def _save_workspace(self) -> None:
        self._settings.setValue("geometry", self.saveGeometry())
        for splitter, key in ((self._splitter, "splitter_fraction"),
                              (self._view_split, "checks_fraction"),
                              (self._explain_split, "explain_height_fraction")):
            sizes = splitter.sizes()
            if sum(sizes) > 0:
                self._settings.setValue(key, sizes[0] / sum(sizes))
        self._settings.setValue("tab", self.tabs.currentIndex())
        self._settings.setValue("crank", self._crank_slider.value())
        self._view3d.save_state()

    def _build_header(self) -> QWidget:
        """A slim brand strip: the mark, the product, and the drive at a glance.

        Deliberately thin.  A tall banner on a tool whose whole job is showing a
        drawing and a table of numbers is space taken away from the work.
        """
        header = QFrame()
        header.setObjectName("BrandHeader")
        header.setFixedHeight(58)
        row = QHBoxLayout(header)
        row.setContentsMargins(14, 6, 14, 6)
        row.setSpacing(12)

        # The mark is a link, which is what a wordmark in the corner of an
        # application is everywhere else - and it was the one piece of chrome
        # that looked clickable and was not.
        self._logo = QLabel()
        self._logo.setPixmap(branding.logo_pixmap("wordmark", self.mode, height=34))
        self._logo.setToolTip(f"{branding.COMPANY} - {branding.TAGLINE}\n"
                              f"{branding.COMPANY_URL}")
        self._logo.setCursor(Qt.PointingHandCursor)
        self._logo.mousePressEvent = (
            lambda _event: self._open_url(branding.COMPANY_URL))
        row.addWidget(self._logo)

        self._header_rule = QFrame()
        self._header_rule.setFrameShape(QFrame.VLine)
        self._header_rule.setFixedWidth(1)
        self._header_rule.setStyleSheet(
            f"background: {branding.palette(self.mode).line};")
        row.addWidget(self._header_rule)

        product = QLabel("CYCLOIDGEN")
        product.setObjectName("BrandProduct")
        row.addWidget(product)

        tagline = QLabel("PARAMETRIC CYCLOIDAL DRIVE DESIGN")
        tagline.setObjectName("BrandTagline")
        row.addWidget(tagline)
        row.addStretch(1)

        row.addWidget(self._build_header_stats())

        self._header_flag = QLabel()
        self._header_flag.setObjectName("BrandFlag")
        row.addWidget(self._header_flag)
        return header

    def _build_header_stats(self) -> QWidget:
        """The drive at a glance, each number under the name of what it is.

        This row used to be eight bare values in one label - ``0.73 Nm  71%
        98'  52 C`` - which is a summary only the person who wrote it can read.
        Two of them are the same unit as nothing else on screen and one of them
        is an arcminute mark that reads as a stray apostrophe.
        """
        strip = QWidget()
        row = QHBoxLayout(strip)
        row.setContentsMargins(0, 0, 0, 0)
        # Tighter than the 18 px it was, because each column now has a rule of
        # its own to separate it and does not have to be held apart by air.
        row.setSpacing(0)

        self._stats: dict[str, QLabel] = {}
        for index, (key, caption, tip) in enumerate(_HEADER_STATS):
            if index:
                rule = QFrame()
                rule.setObjectName("StatRule")
                rule.setFixedWidth(1)
                row.addWidget(rule)

            cell = QWidget()
            column = QVBoxLayout(cell)
            column.setContentsMargins(11, 0, 11, 0)
            column.setSpacing(1)
            label = QLabel(caption)
            label.setObjectName("StatCaption")
            value = QLabel("-")
            value.setObjectName("StatValue")
            # Centred, not right-aligned.  Every caption here is wider than the
            # number under it - TEMPERATURE over "37 C" - so right-aligning both
            # hangs the value off the end of its own caption with a hand's width
            # of gap to its left, and it reads as belonging to the column next
            # door.  Centred, the pair is one object.
            for widget in (label, value):
                widget.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
                column.addWidget(widget)
            cell.setToolTip(tip)
            row.addWidget(cell)
            self._stats[key] = value
        return strip

    def _build_parameter_panel(self) -> QWidget:
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(8, 8, 8, 8)

        row = QHBoxLayout()
        row.addWidget(QLabel("PRESET"))
        self._preset_box = QComboBox()
        # A "custom" entry, because this box is read as much as it is used.
        # Loading a design, running the optimiser or nudging any parameter
        # leaves a drive that is no longer the preset the box last showed, and a
        # chooser that keeps claiming 15:1 over a 21:1 design is not a small lie.
        self._preset_box.addItem("Custom", None)
        for r in (10, 15, 21, 29, 39, 59):
            self._preset_box.addItem(f"{r}:1", r)
        self._preset_box.activated.connect(self._apply_preset)
        row.addWidget(self._preset_box, 1)
        layout.addLayout(row)

        self._optimise_btn = QPushButton("DESIGN FOR REQUIREMENTS")
        self._optimise_btn.setProperty("primary", "true")
        self._optimise_btn.setToolTip(
            "State the ratio, torque and envelope you need and let the app "
            "search for the geometry, instead of tuning it by hand.")
        self._optimise_btn.clicked.connect(self._optimise)
        layout.addWidget(self._optimise_btn)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter parameters...")
        self._filter.setClearButtonEnabled(True)
        self._filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self._filter)

        for title, fields in GROUPS:
            box = QGroupBox(title.upper())
            form = QFormLayout(box)
            form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            form.setHorizontalSpacing(10)
            form.setVerticalSpacing(7)
            for f in fields:
                w = self._make_widget(f)
                self._widgets[f.name] = w
                w.setToolTip(_field_tooltip(f))
                if isinstance(w, QCheckBox):
                    # A lone indicator in the field column reads as orphaned,
                    # and the label beside it is not clickable.  Put the text
                    # on the box and let it span.
                    w.setText(f.label)
                    form.addRow(w)
                    self._rows[f.name] = (w, w)
                else:
                    label = QLabel(f.label)
                    form.addRow(label, w)
                    self._rows[f.name] = (label, w)
            layout.addWidget(box)
            self._groups.append((box, [f.name for f in fields]))

        self._align_label_column()

        # One connection rather than an event filter per widget: the panel wants
        # to know which parameter the user is *looking at*, and focus is that
        # question already answered by Qt for every widget kind at once.
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._focus_changed)

        btn = QPushButton("APPLY PROCESS DEFAULTS")
        btn.setToolTip("Reset both clearances to the guide values for the "
                       "selected manufacturing process.")
        btn.clicked.connect(self._apply_process_defaults)
        layout.addWidget(btn)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(380)
        self._param_scroll = scroll

        # Selecting a finding highlights the parameters it is about.  That says
        # *where* to look and nothing about why, which is the half of the answer
        # the checks were always missing - the relation being tested, the
        # physics behind it and which way to move the knob lived in the comments
        # beside each check, where the person who needs them cannot reach them.
        #
        # It answers two questions, though, and it used to sit beside only one
        # of them.  Clicking a parameter in this panel put its explanation in
        # the far opposite corner of the window - the reply arrived as far from
        # the question as the layout allowed.  Under the parameters it is beside
        # the control you just touched, and still one glance from the checks
        # list, which now has the full width it wanted anyway.
        self._explain = QTextBrowser()
        self._explain.setOpenExternalLinks(False)
        self._explain.setMinimumHeight(120)

        self._explain_split = QSplitter(Qt.Vertical)
        self._explain_split.addWidget(scroll)
        self._explain_split.addWidget(self._explain)
        self._explain_split.setStretchFactor(0, 1)
        self._explain_split.setCollapsible(0, False)
        self._explain_split.setSizes([620, 280])
        return self._explain_split

    def _align_label_column(self) -> None:
        """Give every group the same label column width.

        QFormLayout sizes its label column to the longest label *in that
        layout*, so each group lands on its own alignment and the panel reads as
        a stack of unrelated forms.  One shared width turns it back into a
        column.
        """
        labels = [row[0] for name, row in self._rows.items()
                  if row[0] is not row[1]]
        if not labels:
            return
        width = max(label.sizeHint().width() for label in labels)
        for label in labels:
            label.setMinimumWidth(width)

    def _make_widget(self, f: Field) -> QWidget:
        # Numbers are set right, against the unit.  The field grows to the panel
        # width and a left-set value leaves "2" adrift at the far end of a
        # 200 px box while "13.00 mm" starts in the same place - so the column
        # cannot be scanned, which is the only reason to have a column.
        if f.kind == "float":
            w = QDoubleSpinBox()
            w.setRange(f.minimum, f.maximum)
            w.setSingleStep(f.step)
            w.setDecimals(f.decimals)
            w.setSuffix(f.suffix)
            w.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if f.is_length:
                self._configure_length(w, f)
            w.valueChanged.connect(lambda _v, n=f.name: self._on_change(n))
        elif f.kind == "int":
            w = QSpinBox()
            w.setRange(int(f.minimum), int(f.maximum))
            w.setSingleStep(int(f.step))
            w.setSuffix(f.suffix)
            w.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            w.valueChanged.connect(lambda _v, n=f.name: self._on_change(n))
        elif f.kind == "bool":
            w = QCheckBox()
            w.toggled.connect(lambda _v, n=f.name: self._on_change(n))
        else:
            w = QComboBox()
            w.addItems(list(f.choices))
            w.currentTextChanged.connect(lambda _v, n=f.name: self._on_change(n))
        return w

    def _build_view_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)

        self.tabs = QTabWidget()
        self._fig_profile = Figure(figsize=(6.4, 6.4), dpi=100)
        self._canvas_profile = Canvas(self._fig_profile)
        self._profile_view = plots.ProfileView(self._fig_profile)
        page = QWidget()
        pv = QVBoxLayout(page)
        # One strip, not two.  Four tool buttons and four checkboxes each had a
        # row of their own, and each row ran three quarters empty across a
        # window this wide - while the drawing underneath is a circle in a
        # letterbox, so *height* is the only dimension it is short of. Folding
        # them together spends the width that was going spare on the dimension
        # that was not.
        self._plot_bar = PlotToolbar(self._canvas_profile, page, mode=self.mode)
        # A QToolBar expands by default, so on its own row nobody noticed; put
        # something beside it and it takes the whole strip and pushes that
        # something to the far edge, where it reads as belonging to nothing.
        self._plot_bar.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        strip = QHBoxLayout()
        strip.setContentsMargins(0, 0, 0, 0)
        strip.addWidget(self._plot_bar)
        strip.addLayout(self._build_overlay_row())
        pv.addLayout(strip)
        pv.addWidget(self._canvas_profile, 1)
        self._drawing_tab = self.tabs.addTab(page, "DRAWING")

        self._view3d = Assembly3DTab()
        # The viewer paints its own background rather than taking one from the
        # stylesheet, and it starts on light.  Nothing told it otherwise until
        # the appearance was *changed*, so opening in dark mode gave a white
        # viewport in a dark window - and it looked like the 3D tab had failed.
        self._view3d.refresh_theme(self.mode)
        self._solid_tab = self.tabs.addTab(self._view3d, "3D")
        self.tabs.setTabToolTip(self._solid_tab,
                                "The assembled drive, turning on the same crank "
                                "as the drawing.")

        self._fig_force = Figure(figsize=(6.4, 3.6), dpi=100)
        self._canvas_force = Canvas(self._fig_force)
        self.tabs.addTab(self._canvas_force, "LOADS")

        self._fig_loss = Figure(figsize=(6.4, 3.0), dpi=100)
        self._canvas_loss = Canvas(self._fig_loss)
        self._canvas_loss.setMaximumHeight(320)     # three bars need no more
        loss_page = QWidget()
        lv = QVBoxLayout(loss_page)
        lv.addWidget(self._canvas_loss)
        self._loss_note = QLabel()
        self._loss_note.setWordWrap(True)
        self._loss_note.setContentsMargins(12, 4, 12, 4)
        lv.addWidget(self._loss_note)
        lv.addStretch(1)
        self.tabs.addTab(loss_page, "EFFICIENCY")

        self._datasheet = QTreeWidget()
        self._datasheet.setHeaderLabels(["QUANTITY", "VALUE", "NOTE"])
        self._datasheet.setColumnWidth(0, 260)
        self._datasheet.setColumnWidth(1, 150)
        self.tabs.addTab(self._datasheet, "DATASHEET")

        self._trade = TradeStudyTab()
        self.tabs.addTab(self._trade, "TRADE STUDY")

        self._compare_page = self._build_compare_tab()
        self.tabs.addTab(self._compare_page, "COMPARE")

        self._outputs = OutputsTab()
        self._outputs.export_requested.connect(self._start_export)
        self._outputs_tab = self.tabs.addTab(self._outputs, "OUTPUTS")
        self.tabs.setTabToolTip(self._outputs_tab,
                                "Every file an export writes, what it is for, "
                                "and where it goes.")

        self._log_tab = self.tabs.addTab(self.log, "LOG")
        self.tabs.setTabToolTip(self._log_tab,
                                "Everything the app would otherwise print to a "
                                "terminal you do not have.")
        self.log.problem.connect(self._flag_log)
        self.tabs.currentChanged.connect(self._tab_changed)

        self._checks_panel = QWidget()
        checks_layout = QVBoxLayout(self._checks_panel)
        checks_layout.setContentsMargins(0, 4, 0, 0)
        checks_layout.setSpacing(4)
        checks_layout.addLayout(self._build_findings_filter())

        self.findings = QTreeWidget()
        self.findings.setHeaderLabels(
            ["", "CHECK", "VALUE", "LIMIT", "DETAIL"])
        self.findings.setRootIsDecorated(False)
        self.findings.currentItemChanged.connect(self._finding_selected)
        header = self.findings.header()
        # The severity and code columns are measured against their contents
        # once per fill rather than held at a number chosen once: a fixed
        # 210 px for the code kept 40 px the detail needed on every window, and
        # on a narrow one the four fixed columns added up to more than the list
        # had - so the detail was pushed off the side behind a horizontal
        # scrollbar.  Measured, not `ResizeToContents`: that mode makes the
        # view report a minimum width wide enough for its columns, which
        # propagates out to the whole window and stops the main splitter being
        # dragged where it used to go.
        for col in (2, 3):
            header.setSectionResizeMode(col, QHeaderView.Interactive)
        for col, width in ((2, 78), (3, 78)):
            self.findings.setColumnWidth(col, width)
            self.findings.headerItem().setTextAlignment(col, Qt.AlignRight)
        header.setStretchLastSection(True)

        # The detail is a sentence, not a field.  These messages run to a
        # hundred characters - "Contact stress is lowest near a 6.17 mm pin
        # radius for this pin circle, eccentricity and lobe count" - and no
        # column that also leaves room for the code and two numbers will ever
        # show one on a line.  So every row ended in an ellipsis and the list
        # became a set of codes you had to click one at a time to read, which
        # is the opposite of a list you can scan.  It wraps now, and rows take
        # the height their own text needs.
        self.findings.setWordWrap(True)
        self.findings.setUniformRowHeights(False)
        self.findings.setItemDelegate(WrappingColumn(self.findings, _DETAIL_COL))

        # The list gets the whole width.  The explanation panel used to sit
        # beside it and is under the parameters now - see
        # :meth:`_build_parameter_panel` for why.
        checks_layout.addWidget(self.findings, 1)

        # The crank lives under the tab strip rather than inside the drawing,
        # because it drives the 3D view as well: one control, two simulations,
        # and no chance of the two disagreeing about where the mechanism is.
        stage = QWidget()
        stage_column = QVBoxLayout(stage)
        stage_column.setContentsMargins(0, 0, 0, 0)
        stage_column.setSpacing(4)
        stage_column.addWidget(self.tabs, 1)
        self._crank_bar = self._build_crank_bar()
        stage_column.addWidget(self._crank_bar)

        # A fixed 190 px strip cut the last row in half and left the datasheet
        # scrolling in a box a third of the window.  Let the user decide - but
        # not down to nothing.  The stage is a tab widget whose pages ask for
        # several hundred pixels each, so on a window that is merely a bit short
        # the layout pays for them out of the only widget that will yield: the
        # checks list.  Losing it costs the answer to "is anything wrong with
        # this design", which is the question the application exists to answer,
        # and it goes quietly - there is no scrollbar to notice.
        self._checks_panel.setMinimumHeight(_MIN_CHECKS_PX)
        self._view_split = QSplitter(Qt.Vertical)
        self._view_split.addWidget(stage)
        self._view_split.addWidget(self._checks_panel)
        self._view_split.setStretchFactor(0, 1)
        self._view_split.setCollapsible(0, False)
        self._view_split.setCollapsible(1, False)
        self._view_split.setSizes([620, 260])
        layout.addWidget(self._view_split, 1)

        row = QHBoxLayout()
        self._export_btn = QPushButton("EXPORT ALL FILES")
        self._export_btn.setProperty("primary", "true")
        self._export_btn.clicked.connect(lambda: self._export(True))
        row.addWidget(self._export_btn)
        self._export_2d_btn = QPushButton("EXPORT WITHOUT SOLIDS")
        self._export_2d_btn.setToolTip(
            "Everything except the solids - STEP, STL and 3MF: drawings, the "
            "report and "
            "the animation. Skips the CAD kernel, which is most of the wait.")
        self._export_2d_btn.clicked.connect(lambda: self._export(False))
        row.addWidget(self._export_2d_btn)
        row.addStretch(1)
        self._pin_btn = QPushButton("PIN AS REFERENCE")
        self._pin_btn.setToolTip("Keep this design to compare later changes "
                                 "against. It shows as a ghost on the drawing.")
        self._pin_btn.clicked.connect(self._pin_reference)
        row.addWidget(self._pin_btn)
        layout.addLayout(row)
        layout.addWidget(self._build_notice_strip())
        return panel

    def _build_notice_strip(self) -> QWidget:
        """What this tool does not claim, under the buttons that produce it.

        It used to be in Help ▸ About only, which is a dialog nobody opens and
        the wrong place for the one paragraph here that carries a consequence.
        Under the export buttons it is in front of the person about to press
        one, and it is not dismissible: a disclaimer with a close button is a
        disclaimer that is shown once.

        Deliberately quiet - a hairline, the warning ink, one line of text.  A
        banner that shouts gets read as decoration by the second session, and
        this has to still be legible on the hundredth.
        """
        strip = QLabel(f"{notice.HEADLINE.upper()}  ·  {notice.SHORT}")
        strip.setObjectName("NoticeStrip")
        strip.setWordWrap(True)
        strip.setToolTip(notice.FULL.replace("\n\n", "\n\n"))
        return strip

    def _build_crank_bar(self) -> QWidget:
        """Crank angle, playback and speed - shared by the drawing and the 3D view."""
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(2, 0, 2, 0)
        row.addWidget(QLabel("CRANK"))
        self._crank_slider = QSlider(Qt.Horizontal)
        self._crank_slider.setRange(0, 359)
        self._crank_slider.valueChanged.connect(self._on_crank)
        row.addWidget(self._crank_slider, 1)
        self._crank_label = QLabel("0 deg")
        self._crank_label.setMinimumWidth(56)
        row.addWidget(self._crank_label)

        self._play = QPushButton("ROTATE")
        self._play.setCheckable(True)
        self._play.toggled.connect(self._toggle_animation)
        row.addWidget(self._play)

        # "PLAYBACK", not "SPEED": the design has a speed too, it is on the
        # drawing, and it is nothing to do with this control.
        row.addWidget(QLabel("PLAYBACK"))
        self._speed_box = QComboBox()
        for label, factor in (("0.25x", 0.25), ("0.5x", 0.5), ("1x", 1.0),
                              ("2x", 2.0), ("4x", 4.0)):
            self._speed_box.addItem(label, factor)
        self._speed_box.setCurrentIndex(2)
        self._speed_box.setMaximumWidth(80)
        self._speed_box.setToolTip(
            f"How fast the picture turns, in wall-clock time. 1x turns the "
            f"input once every {60.0 / _PLAYBACK_RPM_AT_1X:.0f} seconds "
            f"({_PLAYBACK_RPM_AT_1X:.1f} rpm on screen).\n\n"
            f"This is not the design's speed. What the drive would really run "
            f"at is on the drawing, off the Input speed parameter.")
        self._speed_box.currentIndexChanged.connect(self._show_playback_rate)
        row.addWidget(self._speed_box)

        # The multiplier alone cannot answer "1x of what?", and a tooltip only
        # answers it to someone who already suspects there is a question.
        self._speed_note = QLabel()
        self._speed_note.setToolTip(self._speed_box.toolTip())
        row.addWidget(self._speed_note)
        self._show_playback_rate()
        return bar

    def _show_playback_rate(self) -> None:
        """Say what the multiplier comes to, beside the multiplier."""
        rpm = _PLAYBACK_RPM_AT_1X * float(self._speed_box.currentData())
        self._speed_note.setText(f"{rpm:.0f} rpm shown")

    def _build_overlay_row(self) -> QHBoxLayout:
        """What the drawing shows on top of the outlines.

        All four come off the same kinematics as the checks and the datasheet,
        so the picture cannot tell a different story from the numbers.  They are
        toggles because a sixty-pin drive with everything on is unreadable.
        """
        row = QHBoxLayout()
        row.setContentsMargins(12, 0, 4, 0)
        row.addWidget(QLabel("OVERLAYS"))
        self._overlay_boxes: dict[str, QCheckBox] = {}
        for key, label, default, tip in (
            ("contacts", "Contacts", True,
             "Where the disc touches each ring pin, sized by the share of load "
             "it carries."),
            ("forces", "Forces", True,
             "Contact force to scale, against the worst force over a whole "
             "lobe pitch - so an arrow that grows means the load grew."),
            ("trace", "Trace", False,
             "The path one point on the disc rim travels over a full output "
             "revolution."),
            ("labels", "Pin numbers", False, "Number the ring pins."),
        ):
            box = QCheckBox(label)
            box.setToolTip(tip)
            box.setChecked(bool(self._settings.value(f"overlay_{key}", default,
                                                     type=bool)))
            box.toggled.connect(lambda on, k=key: self._toggle_overlay(k, on))
            row.addWidget(box)
            self._overlay_boxes[key] = box
        row.addStretch(1)
        return row

    def _overlays(self) -> plots.Overlays:
        return plots.Overlays(**{k: b.isChecked()
                                 for k, b in self._overlay_boxes.items()})

    def _toggle_overlay(self, key: str, on: bool) -> None:
        self._settings.setValue(f"overlay_{key}", on)
        self._profile_view.set_overlays(self._overlays())
        self._canvas_profile.draw_idle()

    def _build_findings_filter(self) -> QHBoxLayout:
        """Severity toggles carrying their own counts.

        A design routinely produces a dozen findings of which ten are notes, and
        the two that block an export sit somewhere in the middle of them.  The
        counts are on the toggles rather than in a summary line so that the
        answer to "is anything wrong" is legible without reading the list.
        """
        row = QHBoxLayout()
        row.setContentsMargins(2, 2, 2, 0)
        row.addWidget(QLabel("CHECKS"))

        self._severity_filters: dict[Severity, QCheckBox] = {}
        for severity, label in ((Severity.ERROR, "Errors"),
                                (Severity.WARNING, "Warnings"),
                                (Severity.INFO, "Notes")):
            box = QCheckBox(label)
            box.setChecked(bool(self._settings.value(
                f"show_{severity.value}", True, type=bool)))
            colour = self._severity[severity].name()
            box.setStyleSheet(f"QCheckBox {{ color: {colour}; }}")
            box.toggled.connect(
                lambda checked, s=severity: self._toggle_severity(s, checked))
            row.addWidget(box)
            self._severity_filters[severity] = box

        row.addStretch(1)
        self._findings_summary = QLabel()
        self._findings_summary.setObjectName("BrandTagline")
        row.addWidget(self._findings_summary)
        return row

    def _toggle_severity(self, severity: Severity, checked: bool) -> None:
        self._settings.setValue(f"show_{severity.value}", checked)
        self._apply_findings_filter()

    def _apply_findings_filter(self) -> None:
        """Hide rather than rebuild, so the current selection survives."""
        shown = total = 0
        for i in range(self.findings.topLevelItemCount()):
            item = self.findings.topLevelItem(i)
            stored = item.data(1, Qt.UserRole)
            if stored is None:                         # the "no findings" row
                continue
            severity = Severity(stored)
            total += 1
            show = self._severity_filters[severity].isChecked()
            item.setHidden(not show)
            shown += show
        current = self.findings.currentItem()
        if current is not None and current.isHidden():
            self.findings.setCurrentItem(None)
        self._findings_summary.setText(
            "" if shown == total else f"showing {shown} of {total}")

    def _build_compare_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._compare_note = QLabel(_NOTHING_PINNED)
        self._compare_note.setWordWrap(True)
        layout.addWidget(self._compare_note)

        self._compare = QTreeWidget()
        self._compare.setHeaderLabels(["Quantity", "Reference", "Current", "Change"])
        self._compare.setRootIsDecorated(False)
        self._compare.setAlternatingRowColors(True)
        for col, width in ((0, 260), (1, 140), (2, 140), (3, 140)):
            self._compare.setColumnWidth(col, width)
        layout.addWidget(self._compare, 1)
        # Something has to hold the space while the table is away, or the note
        # stretches down the page and stops reading as one sentence.
        self._compare_gap = QWidget()
        layout.addWidget(self._compare_gap, 1)

        row = QHBoxLayout()
        clear = QPushButton("Clear reference")
        clear.clicked.connect(self._clear_reference)
        row.addWidget(clear)
        swap = QPushButton("Go back to the reference")
        swap.setToolTip("Load the pinned design back into the parameters.")
        swap.clicked.connect(self._restore_reference)
        row.addWidget(swap)
        row.addStretch(1)
        layout.addLayout(row)
        self._compare_buttons = (clear, swap)
        self._show_reference(False)
        return page

    def _show_reference(self, pinned: bool) -> None:
        """Put the tab into its "nothing pinned" state, or take it out of it.

        An empty table with its column headings still on it reads as a table
        whose contents failed to arrive, and two buttons that act on a
        reference are a puzzle when there is no reference: pressing either does
        nothing, and nothing is the same thing a broken button does.
        """
        self._compare.setVisible(pinned)
        self._compare_gap.setVisible(not pinned)
        for button in self._compare_buttons:
            button.setEnabled(pinned)

    def _build_menu(self) -> None:
        m = self.menuBar().addMenu("&File")
        for text, slot, key in (
            ("&Open design...", self._open_spec, QKeySequence.Open),
            ("&Save design...", self._save_spec, QKeySequence.Save),
            ("&Export all files...", lambda: self._export(True), "Ctrl+E"),
            ("Export &animation...", self._export_animation, "Ctrl+Shift+E"),
        ):
            a = QAction(text, self)
            a.setShortcut(key)
            a.triggered.connect(slot)
            m.addAction(a)
        self._recent_menu = m.addMenu("Open &recent")
        self._rebuild_recent_menu()
        m.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        m.addAction(quit_action)

        e = self.menuBar().addMenu("&Edit")
        self._undo_action = QAction("&Undo", self)
        self._undo_action.setShortcut(QKeySequence.Undo)
        self._undo_action.triggered.connect(self._undo)
        e.addAction(self._undo_action)
        self._redo_action = QAction("&Redo", self)
        self._redo_action.setShortcuts([QKeySequence.Redo, QKeySequence("Ctrl+Y")])
        self._redo_action.triggered.connect(self._redo)
        e.addAction(self._redo_action)
        self._update_history_actions()

        d = self.menuBar().addMenu("&Design")
        opt = QAction("Design for &requirements...", self)
        opt.setShortcut("Ctrl+R")
        opt.triggered.connect(self._optimise)
        d.addAction(opt)
        pin = QAction("&Pin as reference", self)
        pin.setShortcut("Ctrl+P")
        pin.triggered.connect(self._pin_reference)
        d.addAction(pin)

        v = self.menuBar().addMenu("&View")
        appearance = v.addMenu("&Appearance")
        self._appearance_actions: dict[str, QAction] = {}
        for key, label in (("system", "Follow &system"),
                           ("light", "&Light"),
                           ("dark", "&Dark")):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(self.appearance == key)
            action.triggered.connect(
                lambda _checked=False, k=key: self._choose_appearance(k))
            appearance.addAction(action)
            self._appearance_actions[key] = action

        units = v.addMenu("&Units")
        self._unit_actions: dict[str, QAction] = {}
        for key, label in (("mm", "&Millimetres"), ("in", "&Inches (decimal)")):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(self._unit.key == key)
            action.triggered.connect(
                lambda _checked=False, k=key: self._choose_units(k))
            units.addAction(action)
            self._unit_actions[key] = action

        h = self.menuBar().addMenu("&Help")
        # Where the project lives, from inside the application.  It is an
        # installed desktop tool as often as a checkout, and from there the
        # repository, the issue tracker and the release notes were reachable
        # only by knowing the address already.
        for label, url in (
            ("&Project on GitHub", branding.PROJECT_URL),
            ("&Report an issue", branding.ISSUES_URL),
            ("Release &notes", branding.RELEASES_URL),
            (f"&{branding.COMPANY} on the web", branding.COMPANY_URL),
        ):
            action = QAction(label, self)
            action.setStatusTip(url)
            action.triggered.connect(lambda _checked=False, u=url: self._open_url(u))
            h.addAction(action)
        h.addSeparator()

        about = QAction("&About cycloidgen", self)
        about.triggered.connect(self._about)
        h.addAction(about)

    def _open_url(self, url: str) -> None:
        """Hand a link to the desktop, and say so where it can be read back.

        Through the log as well as the browser: a link that silently does
        nothing - no browser configured, a locked-down machine - is otherwise
        indistinguishable from a menu entry that is not wired up.
        """
        if QDesktopServices.openUrl(QUrl(url)):
            self._say(f"opened {url}", seconds=4)
        else:
            self._say(f"could not open {url}", level=logging.WARNING, seconds=8)

    def _about(self) -> None:
        p = branding.palette(self.mode)
        box = QMessageBox(self)
        box.setWindowTitle("About cycloidgen")
        box.setIconPixmap(branding.logo_pixmap("mark", self.mode, height=72))
        box.setTextFormat(Qt.RichText)
        # The disclaimer used to be the last paragraph of the informative text,
        # in the dim ink, under three links - the least-read position in the
        # dialog, for the one paragraph in it that carries a consequence.  It is
        # in the primary text now, boxed, above the links rather than below
        # them.  A one-cell table because Qt's rich text honours cell borders
        # and does not reliably honour a border on a div.
        #
        # It also only ever disclaimed *the numbers*.  The geometry needed
        # saying too: the parts are built from the closed-form profile, and a
        # STEP file that looks finished is the easiest thing here to mistake for
        # a drawing that has been checked.
        box.setText(
            f"<h3 style='margin:0'>cycloidgen {__version__}</h3>"
            f"<p style='color:{p.ink_dim};margin-top:2px'>"
            f"Parametric cycloidal drive design, analysis and CAD export.</p>"
            f"<table cellpadding='8' cellspacing='0' width='100%' "
            f"style='border:1px solid {p.warning}'>"
            f"<tr><td style='border:1px solid {p.warning}'>"
            f"<b style='color:{p.warning}'>{notice.HEADLINE}.</b> "
            f"<span style='color:{p.ink}'>"
            f"{notice.FULL.replace(chr(10) + chr(10), ' ')}</span>"
            f"</td></tr></table>")
        box.setInformativeText(
            f"<p>A <a href='{branding.COMPANY_URL}' style='color:{p.accent}'>"
            f"{branding.COMPANY}</a> tool. <i>{branding.TAGLINE}</i></p>"
            f"<p><a href='{branding.PROJECT_URL}' style='color:{p.accent}'>"
            f"Source and documentation</a> &middot; "
            f"<a href='{branding.ISSUES_URL}' style='color:{p.accent}'>"
            f"Report an issue</a> &middot; "
            f"<a href='{branding.RELEASES_URL}' style='color:{p.accent}'>"
            f"Release notes</a></p>")
        # Without this the links are blue text that does nothing when clicked,
        # which is worse than plain text: it looks like the dialog is broken.
        box.setTextInteractionFlags(Qt.TextBrowserInteraction)
        box.exec()

    # --------------------------------------------------------------- theme
    def _resolve_mode(self, appearance: str) -> str:
        """Turn a preference into the mode to actually paint."""
        if appearance in ("light", "dark"):
            return appearance
        return self._system_mode

    def _apply_theme_colours(self) -> None:
        """Paint chrome and plots from one decision.

        They have to move together: a figure drawn on the light surface inside a
        dark window is the exact thing following the desktop theme was meant to
        avoid, and it is what happens if only half of this runs.
        """
        plots.set_theme(self.mode)
        self.log.set_theme(self.mode)
        self._severity = _severity_colours(self.mode)
        accent = branding.palette(self.mode).accent
        self._highlight_css = f"border: 1px solid {accent}; border-radius: 3px;"
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(branding.stylesheet(self.mode))

    def _choose_appearance(self, appearance: str) -> None:
        """Menu handler: keep the three entries behaving as one radio group."""
        for key, action in self._appearance_actions.items():
            action.setChecked(key == appearance)
        self._set_appearance(appearance)

    def _set_appearance(self, appearance: str) -> None:
        """Switch theme live, without a restart."""
        self.appearance = appearance
        self._settings.setValue("appearance", appearance)
        mode = self._resolve_mode(appearance)
        if mode == self.mode:
            return
        self.mode = mode
        self._apply_theme_colours()

        # Matplotlib bakes its colours in at draw time, so every figure has to
        # be rebuilt - restyling the canvas would leave the old ink on it.
        self._logo.setPixmap(branding.logo_pixmap("wordmark", self.mode, height=34))
        self._header_rule.setStyleSheet(
            f"background: {branding.palette(self.mode).line};")
        # Its accent is baked into the markup rather than taken from a
        # stylesheet, so it is the one piece of chrome a restyle cannot reach.
        self._refresh_status_link()
        for severity, box in self._severity_filters.items():
            box.setStyleSheet(f"QCheckBox {{ color: {self._severity[severity].name()}; }}")
        self._plot_bar.apply_theme(self.mode)
        self._show_explanation()
        self._view3d.refresh_theme(self.mode)
        self._draw_profile()
        if self.analysis is not None:
            plots.force_figure(self.spec, self._fig_force)
            self._canvas_force.draw_idle()
            plots.loss_figure(self.analysis, self._fig_loss)
            self._canvas_loss.draw_idle()
            self._fill_findings()
            self._fill_compare()
        self._trade.refresh_theme()
        self._say(f"appearance: {appearance}", seconds=3)

    # --------------------------------------------------------------- units
    def _choose_units(self, key: str) -> None:
        """Menu handler: keep the entries behaving as one radio group."""
        for name, action in self._unit_actions.items():
            action.setChecked(name == key)
        self._set_units(key)

    def _set_units(self, key: str) -> None:
        """Change what lengths are shown in.  The design itself does not move.

        Every widget is reconfigured and then reloaded *from the spec*, rather
        than having its displayed number converted in place.  Converting in
        place would round the value into the new unit and round it back out
        again on the way home, so a design would drift by a rounding unit every
        time somebody toggled the menu.  The spec is millimetres and stays the
        source of truth; only the view of it changes.
        """
        if key == self._unit.key:
            return
        self._unit = unit(key)
        self._settings.setValue("units", key)
        plots.set_units(key)
        # Guarded, and this is the whole reason the guard exists.  Narrowing a
        # spin box's range makes Qt clamp whatever is in it, and a clamp emits
        # `valueChanged` like any other edit - so switching to inches would take
        # a 50 mm pin circle, find it outside the new 0.197-19.685 range, pin it
        # to the top and write 500 mm back into the design.  The user's drive
        # would silently become a different drive for having looked at it in
        # another unit.
        self._updating = True
        try:
            for name, widget in self._widgets.items():
                field = self._field(name)
                if field is not None and field.is_length:
                    self._configure_length(widget, field)
        finally:
            self._updating = False
        self._load_spec_into_widgets()
        self._draw_profile()
        if self.analysis is not None:
            self._fill_findings()
            self._fill_datasheet()
            self._fill_compare()
            self._show_explanation()
            self._set_header_status()
        self._say(f"units: {self._unit.suffix.strip()}", seconds=3)

    def _field(self, name: str) -> Field | None:
        return next((f for _, fs in GROUPS for f in fs if f.name == name), None)

    def _configure_length(self, widget: QWidget, field: Field) -> None:
        """Point a spin box at the current unit: range, step, decimals, suffix."""
        u = self._unit
        widget.setRange(u.show(field.minimum), u.show(field.maximum))
        widget.setSingleStep(u.show(field.step))
        widget.setDecimals(u.decimals(field.decimals))
        widget.setSuffix(u.suffix)

    def _length(self, mm: float, decimals: int = 2) -> str:
        """A length for display, in whatever unit is selected."""
        return self._unit.text(mm, decimals)

    # ------------------------------------------------------------------- log
    def _build_status_link(self) -> None:
        """Say, in the status bar, where the status bar's messages go.

        The bar and the LOG tab are not two copies of one thing - the bar is the
        last line and forgets it after five seconds, the tab is the record - but
        that is not visible from either of them, and two places showing similar
        text reads as one of them being redundant.  A permanent link on the
        right of the bar makes them one feature with two ends: this is the
        latest, the whole of it is through here.
        """
        self._log_link = QLabel()
        self._log_link.setToolTip("Every message this bar has shown, kept.")
        self._log_link.linkActivated.connect(
            lambda _href: self.tabs.setCurrentIndex(self._log_tab))
        self._refresh_status_link()
        self.statusBar().addPermanentWidget(self._log_link)

    def _refresh_status_link(self) -> None:
        accent = branding.palette(self.mode).accent
        badge = " " + "!" * self._log_badge if self._log_badge else ""
        self._log_link.setText(
            f"<a href='#' style='color:{accent};text-decoration:none'>"
            f"history in LOG{badge}</a>")

    def _say(self, message: str, *, level: int = logging.INFO,
             seconds: int = 5) -> None:
        """Put a message on the status bar *and* keep it in the log.

        The status bar is where the user looks and the log is where it survives;
        a message that only goes to the status bar is gone in five seconds and
        was never recoverable.
        """
        self.statusBar().showMessage(message, seconds * 1000)
        logger.log(level, message)

    def _flag_log(self, level: str) -> None:
        """Mark the tab when something goes wrong on a panel nobody is watching.

        The mark only ever escalates.  A warning arriving after an error must
        not quietly downgrade the badge - the error is still unread.
        """
        if self.tabs.currentIndex() == self._log_tab:
            return
        self._log_badge = max(self._log_badge, 2 if level != "WARNING" else 1)
        self.tabs.setTabText(self._log_tab, "LOG " + "!" * self._log_badge)
        self._refresh_status_link()

    def _tab_changed(self, index: int) -> None:
        if index == self._log_tab:
            self._log_badge = 0
            self.tabs.setTabText(self._log_tab, "LOG")
            self._refresh_status_link()
        # The crank means nothing on a table of numbers, and a control that does
        # nothing where it is shown teaches people to ignore it.
        self._crank_bar.setVisible(index in (self._drawing_tab, self._solid_tab))
        if index == self._drawing_tab and self._profile_stale:
            self._profile_view.set_crank(self._crank)
            self._canvas_profile.draw_idle()
            self._profile_stale = False

    # ----------------------------------------------------------------- state
    def _restore_spec(self) -> GearSpec:
        """Reopen on the design the last session was working on.

        Which build left it is remembered beside it, because an upgrade happens
        between the two halves of this: the session that saved it was running
        one version and the session reading it is running another.  The status
        bar is told once the window has one, in ``_restore_workspace``.
        """
        saved = self._settings.value("last_design")
        if saved:
            try:
                spec = GearSpec.model_validate_json(saved)
            except Exception:
                pass
            else:
                stored = self._settings.value("last_design_version")
                self._restored_session = True
                self._restored_from = stored if isinstance(stored, str) else None
                return spec
        return preset(15)

    def _load_spec_into_widgets(self) -> None:
        self._updating = True
        try:
            for _, fields in GROUPS:
                for f in fields:
                    w = self._widgets[f.name]
                    v = getattr(self.spec, f.name)
                    if isinstance(w, QCheckBox):
                        w.setChecked(bool(v))
                    elif isinstance(w, QComboBox):
                        w.setCurrentText(v.value if hasattr(v, "value") else str(v))
                    elif isinstance(w, QSpinBox):
                        w.setValue(int(v))
                    else:
                        shown = 0.0 if v is None else float(v)
                        if f.is_length:
                            shown = self._unit.show(shown)
                        w.setValue(shown)
            # A pin formed with the housing cannot turn in it, so the roller
            # box is greyed rather than left to look like it does something.
            # Its value is kept, not cleared: it is the preference to go back
            # to when the pins stop being integral, and `spec.ring_pins_roll`
            # is what the analysis reads either way.
            rollers = self._widgets.get("ring_pins_are_rollers")
            if rollers is not None:
                rollers.setEnabled(not self.spec.ring_pins_integral)
        finally:
            self._updating = False

    def _on_change(self, name: str) -> None:
        if self._updating:
            return
        w = self._widgets[name]
        field = next(f for _, fs in GROUPS for f in fs if f.name == name)
        if isinstance(w, QCheckBox):
            value = w.isChecked()
        elif isinstance(w, QComboBox):
            text = w.currentText()
            if name == "process":
                value = Process(text)
            elif name == "offset_mode":
                value = OffsetMode(text)
            else:
                value = text
        elif isinstance(w, QSpinBox):
            value = w.value()
        else:
            value = w.value()
            if field.is_length:
                # Back to millimetres before it touches the spec.  The zero
                # test comes after, because zero is zero in either unit and
                # dividing it first would only invite a rounding question.
                value = self._unit.store(value)
            if field.zero_is_auto and value == 0.0:
                value = None

        try:
            setattr(self.spec, name, value)
        except Exception as exc:                      # pydantic bound violation
            self._say(f"{name}: {exc}", level=logging.WARNING, seconds=4)
            self._load_spec_into_widgets()
            return
        self._history.push(self.spec)
        self._update_history_actions()
        self._sync_preset_box()
        self._debounce.start()

    def _replace_spec(self, spec: GearSpec, *, record: bool = True) -> None:
        """Swap the whole design - a preset, a file, an optimiser result."""
        self.spec = spec
        if record:
            self._history.push(spec)
        self._update_history_actions()
        self._sync_preset_box()
        self._load_spec_into_widgets()
        self._recompute()

    def _apply_preset(self) -> None:
        ratio = self._preset_box.currentData()
        if ratio is None:                             # the "custom" entry
            return
        self._replace_spec(preset(int(ratio)))

    def _sync_preset_box(self) -> None:
        """Point the box at the preset this design *is*, or at Custom.

        Matched on the whole preset rather than on the ratio alone: a 21:1 that
        has had its pin radius changed is not the 21:1 preset any more, and
        saying it is would be the same lie one step quieter.
        """
        index = 0
        for i in range(1, self._preset_box.count()):
            ratio = self._preset_box.itemData(i)
            if ratio == self.spec.lobes and preset(ratio) == self.spec:
                index = i
                break
        blocked = self._preset_box.blockSignals(True)
        self._preset_box.setCurrentIndex(index)
        self._preset_box.blockSignals(blocked)

    def _apply_process_defaults(self) -> None:
        self.spec.apply_process_defaults()
        self._replace_spec(self.spec)

    # --------------------------------------------------------------- history
    def _undo(self) -> None:
        spec = self._history.undo()
        if spec is not None:
            self._replace_spec(spec, record=False)

    def _redo(self) -> None:
        spec = self._history.redo()
        if spec is not None:
            self._replace_spec(spec, record=False)

    def _update_history_actions(self) -> None:
        self._undo_action.setEnabled(self._history.can_undo)
        self._redo_action.setEnabled(self._history.can_redo)

    # ------------------------------------------------------------- filtering
    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        by_name = {f.name: f for _, fs in GROUPS for f in fs}
        for box, names in self._groups:
            visible = 0
            for name in names:
                f = by_name[name]
                match = (not needle or needle in f.label.lower()
                         or needle in name.lower() or needle in f.tip.lower())
                label, widget = self._rows[name]
                label.setVisible(match)
                widget.setVisible(match)
                visible += bool(match)
            box.setVisible(visible > 0)

    # ------------------------------------------------------------- computing
    def _recompute(self) -> None:
        """Kick off an analysis; the drawing updates immediately either way."""
        self._draw_profile()
        self._generation += 1
        worker = AnalysisWorker(self.spec.model_copy(deep=True), self._generation)
        worker.done.connect(self._analysis_ready)
        worker.failed.connect(self._analysis_failed)
        worker.finished.connect(lambda w=worker: self._retire(w))
        self._workers.append(worker)
        worker.start()

    def _retire(self, worker: AnalysisWorker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        worker.deleteLater()

    def _analysis_failed(self, generation: int, message: str) -> None:
        if generation == self._generation:
            self._say(f"analysis failed: {message}", level=logging.ERROR, seconds=6)

    def _analysis_ready(self, generation: int, analysis: DesignAnalysis) -> None:
        if generation != self._generation:
            return                                    # a newer design is pending
        self.analysis = analysis

        plots.force_figure(self.spec, self._fig_force)
        self._canvas_force.draw_idle()
        plots.loss_figure(self.analysis, self._fig_loss)
        self._canvas_loss.draw_idle()
        self._fill_findings()
        self._show_explanation()
        self._fill_datasheet()
        self._fill_compare()
        self._log_findings()
        self._trade.set_spec(self.spec)
        self._outputs.set_spec(self.spec)
        self._outputs.set_blocked([f.code for f in analysis.report.errors])

        s, a = self.spec, self.analysis
        self._export_btn.setEnabled(a.report.ok)
        self._export_2d_btn.setEnabled(a.report.ok)
        e = a.efficiency

        def contact_kind(rolling: bool) -> str:
            return "rolling" if rolling else "fixed, sliding contact"

        self._loss_note.setText(
            f"Ring pins: {contact_kind(s.ring_pins_roll)}"
            f"{', formed with the housing' if s.ring_pins_integral else ''}.   "
            f"Output pins: {contact_kind(s.output_pins_are_rollers)}.   "
            f"{e.input_torque_Nm:.3f} Nm in at {s.input_rpm:g} rpm delivers "
            f"{e.output_power_W:.2f} W of the {e.input_power_W:.2f} W supplied. "
            f"Losses scale with the friction coefficient, so lubrication and rolling "
            f"elements move this number further than any geometry change.")
        self._set_header_status()
        if not a.report.ok:
            self.statusBar().showMessage(
                "Export blocked: " + ", ".join(f.code for f in a.report.errors))

    def _set_header_status(self) -> None:
        """The drive at a glance, in the brand strip.

        Two of the eight are coloured, and only two, because only two of them
        have a limit the analysis itself computes: whether the drive can carry
        the torque it is rated for, and whether it stays under the temperature
        its own materials allow.  Colouring the rest would mean inventing
        thresholds here that nothing else in the app would agree with.
        """
        s, a = self.spec, self.analysis
        if a is None:
            return
        decimals = 0 if self._unit.key == "mm" else 1
        capacity = a.torque_capacity_with_clearance_Nm
        self._set_stat("ratio", f"{s.ratio}:1")
        self._set_stat("od", self._length(2 * s.housing_outer_radius, decimals))
        self._set_stat("length", self._length(s.envelope_length, decimals))
        self._set_stat("mass", f"{a.mass.total_mass_g:.0f} g")
        self._set_stat("capacity", f"{capacity:.2f} Nm",
                       warn=capacity < s.output_torque_Nm)
        self._set_stat("efficiency", f"{100 * a.efficiency.efficiency:.0f}%")
        self._set_stat("backlash", f"{a.stiffness.lost_motion_arcmin:.0f}'")
        self._set_stat("temperature", f"{a.thermal.temperature_C:.0f} C",
                       warn=a.thermal.temperature_C > a.thermal.temperature_limit_C)

        self._header_flag.setText("" if a.report.ok else "EXPORT BLOCKED")

    def _set_stat(self, key: str, text: str, *, warn: bool = False) -> None:
        """One cell of the strip, restyled only when its state actually moves.

        ``unpolish``/``polish`` is what makes a dynamic property take effect,
        and it is not free - doing it on every cell on every keystroke of a spin
        box is a full restyle of the strip eight times over.
        """
        label = self._stats[key]
        label.setText(text)
        state = "warning" if warn else ""
        if label.property("state") != state:
            label.setProperty("state", state)
            label.style().unpolish(label)
            label.style().polish(label)

    def _draw_profile(self) -> None:
        """Rebuild both simulations for a *new design*.

        Only the design goes through here.  A change of crank angle goes through
        :meth:`_sync_crank`, which moves the artists that already exist rather
        than making new ones - that is the whole reason the animation keeps up.
        """
        self._profile_view.set_design(self.spec, reference=self._pinned,
                                      overlays=self._overlays())
        self._profile_view.set_crank(self._crank)
        self._canvas_profile.draw_idle()
        self._view3d.set_spec(self.spec)
        self._view3d.set_crank(self._crank)

    def _fill_findings(self) -> None:
        # The list is rebuilt on every analysis, which is every nudge of a spin
        # box, and clearing it drops the selection - so the check you were
        # reading about vanished the moment you started acting on it.  Keep the
        # code and put the cursor back on it if it is still there.
        keep = getattr(self, "_selected_code", None)
        self.findings.clear()
        assert self.analysis is not None
        counts = {Severity.ERROR: 0, Severity.WARNING: 0, Severity.INFO: 0}
        for f in self.analysis.report.findings:
            item = QTreeWidgetItem([
                f.severity.value.upper(), f.code,
                self._finding_number(f, f.value),
                self._finding_number(f, f.limit),
                f.message])
            item.setForeground(0, self._severity[f.severity])
            # Top, not centre.  A row is as tall as its wrapped detail, and a
            # code floating in the middle of four lines of prose reads as
            # belonging to the middle line rather than to the row.
            for col in (0, 1):
                item.setTextAlignment(col, Qt.AlignLeft | Qt.AlignTop)
            for col in (2, 3):
                item.setTextAlignment(col, Qt.AlignRight | Qt.AlignTop)
                item.setFont(col, self._mono)
            item.setData(0, Qt.UserRole, f.code)
            # The value, not the enum member: Qt stores this in a QVariant and
            # hands back a plain str.  Severity is a str enum so a dict lookup
            # would happen to work anyway - which is exactly the kind of
            # accident that stops working when the enum stops being a str.
            item.setData(1, Qt.UserRole, f.severity.value)
            item.setToolTip(4, f.message)          # the column truncates
            self.findings.addTopLevelItem(item)
            counts[f.severity] += 1
        if not self.analysis.report.findings:
            self.findings.addTopLevelItem(
                QTreeWidgetItem(["", "", "", "", "No findings."]))

        # Measured here rather than left to a `ResizeToContents` header mode,
        # which would make the view demand a minimum width wide enough for its
        # own columns and push that all the way out to the window.
        for col in (0, 1):
            self.findings.resizeColumnToContents(col)

        for severity, label in ((Severity.ERROR, "Errors"),
                                (Severity.WARNING, "Warnings"),
                                (Severity.INFO, "Notes")):
            box = self._severity_filters[severity]
            box.setText(f"{label} ({counts[severity]})")
            box.setEnabled(counts[severity] > 0)
        self._apply_findings_filter()

        if keep is not None:
            for i in range(self.findings.topLevelItemCount()):
                item = self.findings.topLevelItem(i)
                if item.data(0, Qt.UserRole) == keep and not item.isHidden():
                    self.findings.setCurrentItem(item)
                    break

    def _finding_number(self, finding, value: float | None) -> str:
        """A finding's value or limit, in the selected unit.

        Which findings carry a length is not guessed - the explanation beside
        each check already declares the unit its numbers are in, so the checks
        list and the explanation panel cannot disagree about what a column
        means.
        """
        if value is None:
            return ""
        detail = explain(finding.code)
        if detail is not None and detail.unit == "mm":
            return f"{self._unit.show(value):.4g}"
        return f"{value:.4g}"

    def _log_findings(self) -> None:
        """Record checks that appear or clear, at their own severity.

        Only on change.  Dragging a spin box re-analyses every 120 ms, and a log
        that repeats the same fifteen findings on every tick is a log nobody
        reads.
        """
        assert self.analysis is not None
        report = self.analysis.report
        codes = {f.code for f in report.findings}
        if codes == self._last_codes:
            return
        appeared = codes - (self._last_codes or set())
        cleared = (self._last_codes or set()) - codes
        first_run = self._last_codes is None
        self._last_codes = codes

        for f in report.findings:
            if f.code not in appeared:
                continue
            level = {Severity.ERROR: logging.ERROR,
                     Severity.WARNING: logging.WARNING}.get(f.severity, logging.INFO)
            margin = ""
            if f.value is not None and f.limit is not None:
                margin = f"  [{f.value:.4g} vs limit {f.limit:.4g}]"
            logger.log(level, "%s: %s%s", f.code, f.message, margin)
        if cleared and not first_run:
            logger.info("cleared: %s", ", ".join(sorted(cleared)))
        if not report.ok:
            logger.error("export blocked by %s",
                         ", ".join(f.code for f in report.errors))

    def _finding_selected(self, current: QTreeWidgetItem | None, _prev=None) -> None:
        """Point at the parameters the selected check is about, and say why."""
        for w in self._highlighted:
            w.setStyleSheet("")
        self._highlighted.clear()
        self._selected_code = None if current is None else current.data(0, Qt.UserRole)
        self._show_explanation()
        if current is None:
            return
        code = self._selected_code
        first = None
        for name in CODE_FIELDS.get(code, ()):
            row = self._rows.get(name)
            if row is None:
                continue
            _label, widget = row
            widget.setStyleSheet(self._highlight_css)
            self._highlighted.append(widget)
            first = first or widget
        if first is not None:
            self._param_scroll.ensureWidgetVisible(first, 0, 60)

    def _focus_changed(self, _old, new) -> None:
        """Follow the focus into the parameter panel, and back out of it.

        The panel has two things worth saying and they belong to two different
        moments. Once something is wrong, the useful text is the check's: what
        failed and what to move. Before anything is wrong - which is where
        somebody meeting forty-eight fields starts - the useful text is the
        parameter's, and nothing was offering it.

        Focus decides which, because focus is where the user is looking. The
        tree's selection is left alone: clicking into a field the check has just
        highlighted is following its advice, not abandoning it, and the check
        comes back the moment focus leaves.
        """
        name = next((n for n, w in self._widgets.items() if w is new), None)
        if name == self._focused_field:
            return
        self._focused_field = name
        self._show_explanation()

    def _show_explanation(self) -> None:
        """Render whichever of the two the user is looking at, or the prompt.

        Rebuilt rather than restyled, because the colours are baked into the
        markup - the same reason every figure is rebuilt on a theme change.
        """
        if self._focused_field is not None:
            self._show_parameter_guide(self._focused_field)
            return
        p = branding.palette(self.mode)
        code = getattr(self, "_selected_code", None)
        finding = None
        if self.analysis is not None and code is not None:
            finding = next((f for f in self.analysis.report.findings
                            if f.code == code), None)
        detail = explain(code) if code else None
        if detail is None or finding is None:
            self._explain.setHtml(
                f"<div style='color:{p.ink_dim};font-size:12px'>"
                f"Select a check to see what it tests, why it matters, and "
                f"which parameter moves it &mdash; or click into any parameter "
                f"to see what it is, how to choose it, and what that costs."
                f"</div>")
            return

        ink, dim, accent = p.ink, p.ink_dim, self._severity[finding.severity].name()
        parts = [
            f"<div style='color:{accent};font-size:10px;font-weight:700;"
            f"letter-spacing:.6px'>{finding.severity.value.upper()} &middot; "
            f"{finding.code}</div>",
            f"<div style='color:{ink};font-size:14px;font-weight:600;"
            f"margin:2px 0 8px 0'>{detail.title}</div>",
        ]

        reading = self._reading_line(finding, detail)
        if reading:
            parts.append(f"<div style='color:{ink};font-size:12px;"
                         f"margin-bottom:8px'>{reading}</div>")

        parts.append(_section("TESTS", dim,
                              f"<code style='color:{ink};font-size:12px'>"
                              f"{detail.tests}</code>"))
        parts.append(_section("WHY", dim,
                              f"<span style='color:{ink};font-size:12px'>"
                              f"{detail.why}</span>"))
        parts.append(_section("WHAT TO CHANGE", dim,
                              f"<span style='color:{ink};font-size:12px'>"
                              f"{detail.fix}</span>"))

        labels = [self._rows[n][0].text() for n in CODE_FIELDS.get(code, ())
                  if n in self._rows and self._rows[n][0] is not self._rows[n][1]]
        if labels:
            parts.append(_section("HIGHLIGHTED", dim,
                                  f"<span style='color:{ink};font-size:12px'>"
                                  f"{', '.join(labels)}</span>"))
        self._explain.setHtml("".join(parts))

    def _show_parameter_guide(self, name: str) -> None:
        """What this parameter is, how to choose it, and what it is moving now.

        The last part is the one the declaration cannot carry: which checks this
        field feeds is a fixed relation, but how close each of them currently
        sits to its limit belongs to the design on screen. So the prose comes
        from :mod:`cycloidgen.core.guide` and the state comes from the analysis,
        and a parameter that is about to break something says so before it is
        moved rather than after.
        """
        p = branding.palette(self.mode)
        detail = guide(name)
        field = next((f for _, fs in GROUPS for f in fs if f.name == name), None)
        if detail is None or field is None:
            self._explain.setHtml("")
            return
        ink, dim = p.ink, p.ink_dim
        group = next((t for t, fs in GROUPS if any(f.name == name for f in fs)), "")

        parts = [
            f"<div style='color:{dim};font-size:10px;font-weight:700;"
            f"letter-spacing:.6px'>PARAMETER &middot; {group.upper()}</div>",
            f"<div style='color:{ink};font-size:14px;font-weight:600;"
            f"margin:2px 0 8px 0'>{field.label}</div>",
            _section("WHAT IT IS", dim,
                     f"<span style='color:{ink};font-size:12px'>"
                     f"{detail.what}</span>"),
            _section("CHOOSING IT", dim,
                     f"<span style='color:{ink};font-size:12px'>"
                     f"{detail.choosing}</span>"),
        ]
        if detail.trade:
            parts.append(_section(
                "WHAT IT COSTS", dim,
                f"<span style='color:{ink};font-size:12px'>{detail.trade}</span>"))

        codes = codes_for_field(name)
        if codes:
            raised = {f.code: f for f in (self.analysis.report.findings
                                          if self.analysis else ())}
            live = [c for c in codes if c in raised]
            rows = []
            for code in live:
                f = raised[code]
                colour = self._severity[f.severity].name()
                rows.append(f"<div style='margin-bottom:2px'>"
                            f"<span style='color:{colour};font-size:11px;"
                            f"font-weight:700'>{f.severity.value.upper()}</span> "
                            f"<code style='color:{ink};font-size:11px'>{code}"
                            f"</code></div>")
            quiet = len(codes) - len(live)
            if quiet:
                rows.append(f"<div style='color:{dim};font-size:11px'>"
                            f"and {quiet} more not raised on this design</div>")
            parts.append(_section("WHAT IT MOVES", dim, "".join(rows)))
        self._explain.setHtml("".join(parts))

    def _reading_line(self, finding, detail) -> str:
        """Value against limit, and how many times clear of it - when that means
        something.  See :func:`cycloidgen.core.explain.margin` for when it does
        not."""
        if finding.value is None:
            return ""
        # The explanation declares millimetres; the reader may have asked for
        # inches.  Convert both numbers, and the label with them.
        shown, limit = finding.value, finding.limit
        if detail.unit == "mm":
            shown = self._unit.show(shown)
            limit = None if limit is None else self._unit.show(limit)
            suffix = self._unit.suffix
        else:
            suffix = f" {detail.unit}" if detail.unit else ""
        text = f"<b>{shown:.4g}</b>{suffix}"
        if limit is not None:
            # A check with no side to be on still compares against something -
            # the suggested pin radius, the pin count that would make the discs
            # interchangeable - and hiding it loses the more useful of the two
            # numbers.
            word = {"below": " a limit of", "above": " a minimum of"}.get(
                detail.keep, "")
            text += f" against{word} <b>{limit:.4g}</b>{suffix}"
        times = margin(finding)
        if times is not None:
            side = "clear of it" if times >= 1.0 else "over it"
            shown = times if times >= 1.0 else 1.0 / times
            text += f" &mdash; {shown:.2f}x {side}"
        return text

    def _fill_datasheet(self) -> None:
        """The numbers you would put on a spec sheet, in one place."""
        a = self.analysis
        assert a is not None
        s, st, th, m = self.spec, a.stiffness, a.thermal, a.mass
        te = a.transmission_error
        self._datasheet.clear()
        sections = [
            ("Ratings", [
                ("Reduction", f"{s.ratio}:1",
                 ("ring fixed, output from the disc pin holes"
                  if s.output_member is OutputMember.CARRIER else
                  "carrier fixed, output from the ring housing")
                 + " - the output turns "
                 + ("against the input" if s.output_reverses
                    else "with the input")),
                ("Rated output torque", f"{s.output_torque_Nm:.2f} Nm", "as entered"),
                ("Torque capacity (ideal share)", f"{a.torque_capacity_Nm:.2f} Nm",
                 "every pin carrying its ideal share"),
                ("Torque capacity (with clearance)",
                 f"{a.torque_capacity_with_clearance_Nm:.2f} Nm",
                 f"derated {st.load_concentration:.2f}x for load concentration"),
                ("Safety factor", f"{a.pin_safety_factor_with_clearance:.2f}",
                 "on ring contact stress, with clearance"),
                ("Efficiency", f"{100 * a.efficiency.efficiency:.1f} %",
                 "upper bound - seals and churning not modelled"),
                ("Power density",
                 f"{a.power_density_Nm_per_kg:.2f} Nm/kg", "capacity per assembled mass"),
            ]),
            ("Precision", [
                ("Torsional stiffness",
                 f"{st.stiffness_Nm_per_arcmin:.3f} Nm/arcmin",
                 f"{st.contact_only_Nm_per_arcmin:.3f} mesh in series with "
                 f"{st.structure_Nm_per_arcmin:.3f} structure"),
                ("Softest part outside the mesh",
                 f"{min(k for _n, k in st.structure.items):.2f} Nm/arcmin",
                 f"the {st.structure.softest}"),
                ("Lost motion", f"{st.lost_motion_arcmin:.1f} arcmin",
                 f"{st.lost_motion_ring_arcmin:.1f} profile + "
                 f"{st.lost_motion_output_arcmin:.1f} holes"),
                ("Wind-up at rated torque", f"{st.windup_arcmin:.2f} arcmin", "elastic"),
                ("Total backlash", f"{st.backlash_total_arcmin:.1f} arcmin",
                 "lost motion plus wind-up"),
                ("Transmission error",
                 f"{te.peak_to_peak_arcmin:.3f} arcmin p-p",
                 f"{te.rms_arcmin:.3f} rms"
                 + ("" if st.tolerance_was_sampled
                    else "; no manufacturing error in it")),
                *([("Spread over the batch",
                    f"{st.stiffness_p10_Nm_per_arcmin:.3f} Nm/arcmin soft decile",
                    f"{st.rings_sampled} rings at {s.position_tolerance:.3f} mm "
                    f"true position; TE up to {te.worst_ring_arcmin:.3f} arcmin")]
                  if st.tolerance_was_sampled else []),
                ("Pins carrying load",
                 f"{st.pins_engaged:.1f} of {st.pins_engaged_ideal:.0f}",
                 "clearance keeps the rest out of mesh"),
            ]),
            ("Thermal and wear", [
                ("Power lost", f"{th.loss_W:.2f} W", "at the rated duty point"),
                ("Steady temperature", f"{th.temperature_C:.0f} C",
                 f"still air, {th.temperature_limit_C:.0f} C limit"),
                ("Ring pin PV",
                 f"{th.pv_ring_MPa_m_s:.3f} / {th.pv_ring_limit_MPa_m_s:.3f} MPa m/s",
                 f"margin {th.ring_pv_margin:.2f}x"),
                ("Output pin PV",
                 f"{th.pv_output_MPa_m_s:.3f} / {th.pv_output_limit_MPa_m_s:.3f} MPa m/s",
                 f"margin {th.output_pv_margin:.2f}x"),
            ]),
            ("Mass and inertia", [
                ("Assembled mass", f"{m.total_mass_g:.0f} g", ""),
                ("Disc mass", f"{m.disc_mass_g:.1f} g", f"x{s.disc_count}"),
                ("Reflected inertia", f"{m.reflected_inertia_kg_mm2:.4f} kg mm2",
                 "seen at the input shaft"),
                ("Residual unbalance", f"{m.unbalance_force_N:.1f} N",
                 f"couple {m.unbalance_couple_Nmm:.1f} Nmm at {s.input_rpm:g} rpm"),
                ("Thinnest disc web", self._length(m.min_web_mm),
                 f"shear safety factor {m.web_safety_factor:.1f}"),
            ]),
            ("Envelope", [
                ("Outer diameter", self._length(2 * s.housing_outer_radius), ""),
                ("Overall length", self._length(s.envelope_length),
                 "barrel and both end plates"
                 + (", plus the base it is bolted down by - and the barrel is "
                    "longer, because the end cap is inside it"
                    if s.ground_frame_fitted else "")),
                ("Output speed", f"{s.output_rpm:.1f} rpm",
                 f"at {s.input_rpm:g} rpm in, turning "
                 + ("the other way" if s.output_reverses else "the same way")),
            ]),
        ]
        for title, rows in sections:
            parent = QTreeWidgetItem([title, "", ""])
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            self._datasheet.addTopLevelItem(parent)
            for name, value, note in rows:
                child = QTreeWidgetItem([name, value, note])
                child.setFont(1, self._mono)
                child.setToolTip(2, note)
                parent.addChild(child)
            parent.setExpanded(True)

    # --------------------------------------------------------------- compare
    def _pin_reference(self) -> None:
        if self.analysis is None:
            return
        self._pinned = self.spec.model_copy(deep=True)
        self._pinned_analysis = self.analysis
        self._draw_profile()
        self._fill_compare()
        self.tabs.setCurrentWidget(self._compare_page)
        self._say(f"pinned {self.spec.ratio}:1, "
                  f"{2 * self.spec.housing_outer_radius:.1f} mm OD as the "
                  f"comparison reference", seconds=4)

    def _clear_reference(self) -> None:
        self._pinned = None
        self._pinned_analysis = None
        # Through the same path the tab is built on rather than clearing it by
        # hand here, which is how this came to have a second, shorter wording
        # of the empty state that only appeared if you had pinned something
        # first and then changed your mind.
        self._fill_compare()
        self._draw_profile()

    def _restore_reference(self) -> None:
        if self._pinned is not None:
            self._replace_spec(self._pinned.model_copy(deep=True))

    def _fill_compare(self) -> None:
        self._compare.clear()
        if self._pinned_analysis is None or self.analysis is None:
            self._show_reference(False)
            self._compare_note.setText(_NOTHING_PINNED)
            return
        self._show_reference(True)
        ref, cur = self._pinned_analysis, self.analysis
        self._compare_note.setText(
            f"Reference: {self._pinned.ratio}:1, "
            f"{2 * self._pinned.housing_outer_radius:.1f} mm OD. "
            f"Green is better, red is worse, on the quantity's own terms.")

        rows = [
            ("Torque capacity", "Nm", ref.torque_capacity_with_clearance_Nm,
             cur.torque_capacity_with_clearance_Nm, True),
            ("Safety factor", "", ref.pin_safety_factor_with_clearance,
             cur.pin_safety_factor_with_clearance, True),
            ("Efficiency", "%", 100 * ref.efficiency.efficiency,
             100 * cur.efficiency.efficiency, True),
            ("Torsional stiffness", "Nm/arcmin", ref.stiffness.stiffness_Nm_per_arcmin,
             cur.stiffness.stiffness_Nm_per_arcmin, True),
            ("Lost motion", "arcmin", ref.stiffness.lost_motion_arcmin,
             cur.stiffness.lost_motion_arcmin, False),
            ("Transmission error", "arcmin",
             ref.transmission_error.peak_to_peak_arcmin,
             cur.transmission_error.peak_to_peak_arcmin, False),
            ("Outer diameter", "mm", 2 * self._pinned.housing_outer_radius,
             2 * self.spec.housing_outer_radius, False),
            ("Overall length", "mm", self._pinned.envelope_length,
             self.spec.envelope_length, False),
            ("Assembled mass", "g", ref.mass.total_mass_g, cur.mass.total_mass_g, False),
            ("Power density", "Nm/kg", ref.power_density_Nm_per_kg,
             cur.power_density_Nm_per_kg, True),
            ("Running temperature", "C", ref.thermal.temperature_C,
             cur.thermal.temperature_C, False),
            ("Power lost", "W", ref.efficiency.total_loss_W,
             cur.efficiency.total_loss_W, False),
            ("Errors", "", len(ref.report.errors), len(cur.report.errors), False),
            ("Warnings", "", len(ref.report.warnings), len(cur.report.warnings), False),
        ]
        for name, dimension, before, after, higher_better in rows:
            # A length row is stored in millimetres like everything else, so it
            # converts here rather than at the twenty places that build it.
            if dimension == "mm":
                before, after = self._unit.show(before), self._unit.show(after)
                dimension = self._unit.suffix.strip()
            delta = after - before
            if abs(before) > 1e-12:
                text = f"{delta:+.3g} {dimension} ({100 * delta / abs(before):+.1f} %)"
            else:
                text = f"{delta:+.3g} {dimension}"
            item = QTreeWidgetItem([name, f"{before:.4g} {dimension}".strip(),
                                    f"{after:.4g} {dimension}".strip(), text.strip()])
            if abs(delta) > 1e-9:
                better = (delta > 0) == higher_better
                item.setForeground(3, QColor("#1baf7a" if better else "#c0392b"))
            self._compare.addTopLevelItem(item)

    # ------------------------------------------------------------- optimiser
    def _optimise(self) -> None:
        dialog = OptimiseDialog(self.spec, self)
        if dialog.exec() and dialog.chosen is not None:
            if self.analysis is not None and self._pinned is None:
                self._pinned = self.spec.model_copy(deep=True)
                self._pinned_analysis = self.analysis
            self._replace_spec(dialog.chosen)
            self._say("loaded the optimiser's design; the previous one is pinned "
                      "as the comparison reference", seconds=8)

    # ------------------------------------------------------------- animation
    def _on_crank(self, value: int) -> None:
        self._crank = float(value)
        if not self._anim.isActive():
            self._crank_exact = self._crank
        self._crank_label.setText(f"{value} deg")
        self._sync_crank()

    def _sync_crank(self) -> None:
        """Move both simulations to the current angle.

        The 3D view only repaints if it is on screen, and matplotlib is asked
        for a redraw only when its canvas is: a hidden canvas still honours
        ``draw_idle`` with a full Agg render, which is ten milliseconds a frame
        spent drawing something nobody is looking at.
        """
        self._view3d.set_crank(self._crank)
        if self._canvas_profile.isVisible():
            self._profile_view.set_crank(self._crank)
            self._canvas_profile.draw_idle()
            self._profile_stale = False
        else:
            self._profile_stale = True

    def _advance_crank(self) -> None:
        """Advance over the *mechanism's* period, not the input shaft's.

        One input revolution does not put the drive back where it started: the
        disc and the carrier have moved on by 360/lobes, which is exactly the
        jump that used to appear every time the loop restarted.  The period is
        `lobes` input turns - one output revolution - and wrapping there is
        seamless because every part really is back at its starting pose.

        The slider still reads 0-359, because that is the crank angle and it is
        what the user set; it is driven without its signal so that its own
        wrap-around does not feed the unwrapped angle back in.
        """
        step = _CRANK_STEP_DEG * float(self._speed_box.currentData())
        self._crank_exact = (self._crank_exact + step) % (360.0 * self.spec.lobes)
        self._crank = self._crank_exact

        blocked = self._crank_slider.blockSignals(True)
        self._crank_slider.setValue(int(self._crank_exact) % 360)
        self._crank_slider.blockSignals(blocked)
        self._crank_label.setText(f"{int(self._crank_exact) % 360} deg")
        self._sync_crank()

    def _toggle_animation(self, on: bool) -> None:
        self._play.setText("STOP" if on else "ROTATE")
        self._anim.start() if on else self._anim.stop()

    # ---------------------------------------------------------------- files
    def _save_spec(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save design", f"cycloidal_{self.spec.ratio}to1.json",
            "Design files (*.json)")
        if path:
            Path(path).write_text(
                json.dumps(design_dict(self.spec), indent=2), encoding="utf-8")
            self._remember_recent(path)
            self._say(f"saved {path}", seconds=4)

    def _open_spec(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open design", "",
                                              "Design files (*.json)")
        if path:
            self._load_path(path)

    def _load_path(self, path: str) -> None:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            spec = spec_from_dict(data)               # design, report or bare spec
        except Exception as exc:
            logger.error("could not open %s: %s", path, exc)
            QMessageBox.critical(self, "Could not open", str(exc))
            return
        self._history.reset(spec)
        self._replace_spec(spec, record=False)
        self._remember_recent(path)
        self._say(f"opened {path}", seconds=4)

        written = written_by(data)
        if numbers_may_have_moved(written):
            # A file somebody went and opened is one they are about to act on,
            # so this is worth stopping for.  The session restore is not, and
            # says the same thing on the status bar instead: that design is
            # their own unfinished work rather than something handed over, and
            # a modal on every launch after an upgrade is how people learn to
            # dismiss the one that mattered without reading it.
            QMessageBox.information(self, "Saved by a different version",
                                    provenance(written))

    def _recent_files(self) -> list[str]:
        stored = self._settings.value("recent_files") or []
        if isinstance(stored, str):
            stored = [stored]
        return [p for p in stored if Path(p).exists()]

    def _remember_recent(self, path: str) -> None:
        files = [p for p in self._recent_files() if Path(p) != Path(path)]
        files.insert(0, path)
        self._settings.setValue("recent_files", files[:_MAX_RECENT])
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        self._recent_menu.clear()
        files = self._recent_files()
        if not files:
            empty = QAction("(nothing yet)", self)
            empty.setEnabled(False)
            self._recent_menu.addAction(empty)
            return
        for path in files:
            action = QAction(Path(path).name, self)
            action.setToolTip(path)
            action.triggered.connect(lambda _checked=False, p=path: self._load_path(p))
            self._recent_menu.addAction(action)

    def _export(self, solids: bool) -> None:
        """The two quick buttons.  The Outputs tab is the considered route."""
        groups = set(group_keys())
        if not solids:
            groups.discard("solids")
        directory = QFileDialog.getExistingDirectory(
            self, "Export into folder", self._outputs.destination)
        if not directory:
            return
        self._outputs.set_destination(directory)
        self._start_export(Path(directory) / f"cycloidal_{self.spec.ratio}to1",
                           groups)

    def _start_export(self, target: Path, groups: set[str]) -> None:
        if self.analysis is None or not self.analysis.report.ok:
            QMessageBox.warning(self, "Blocked",
                                "Fix the errors in the checks list before exporting.")
            return
        if not groups:
            return
        if not self._notice_accepted(target):
            return

        self._export_target = Path(target)
        self._progress = QProgressDialog("Generating files...", "", 0, 0, self)
        self._progress.setCancelButton(None)
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.show()

        self._worker = ExportWorker(self.spec.model_copy(deep=True),
                                    self._export_target, groups)
        self._worker.done.connect(self._export_done)
        self._worker.failed.connect(self._export_failed)
        self._worker.start()

    def _notice_accepted(self, target: Path) -> bool:
        """Ask before writing, and say what is being written.

        Before rather than after, because after is a notification and this is a
        decision: the files are the thing that leaves the app, gets emailed to
        a shop and outlives the session that made them.  Every export, with no
        "do not show again" - the box is one keystroke and the day it stops
        appearing is the day it stops being true that somebody was told.

        The same words are on the strip under the buttons, in `NOTICE.txt`
        beside the parts, and on the terminal after a headless run.  All four
        read `cycloidgen.notice`.
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Export")
        box.setText(f"<b>{notice.HEADLINE}</b>")
        box.setInformativeText(
            notice.FULL.replace("\n\n", "<br><br>")
            + f"<br><br>Writing to <code>{target}</code>.")
        box.setTextFormat(Qt.RichText)
        write = box.addButton("Export", QMessageBox.AcceptRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.setDefaultButton(write)
        box.exec()
        if box.clickedButton() is not write:
            self._say("export cancelled")
            return False
        return True

    def _export_done(self, files: list[str]) -> None:
        self._progress.close()
        folder = self._export_target
        self._outputs.show_written(folder, [Path(f) for f in files])
        self._say(f"wrote {len(files)} files to {folder}", seconds=6)
        QMessageBox.information(
            self, "Export complete",
            f"{len(files)} files written to\n{folder}\n\n"
            f"The Outputs tab lists them with sizes; double-click one to open it.")

    def _export_failed(self, message: str) -> None:
        self._progress.close()
        QMessageBox.critical(self, "Export failed", message[-2000:])

    # ------------------------------------------------------------- animation
    def _animation_request(self) -> tuple[animation.Animation, dict]:
        """The plan and the render options for whatever view is on screen.

        On the 3D tab that is the assembly from the angle, explode and part
        visibility currently set; anywhere else it is the drawing with the
        overlays currently ticked.  Exporting a view the user is not looking at,
        from a viewpoint they did not choose, only produces a file they have to
        make a second time.
        """
        if self.tabs.currentIndex() == self._solid_tab:
            return (animation.plan(self.spec, view="assembly"),
                    {"theme": self.mode, **self._view3d.render_options()})
        return (animation.plan(self.spec, view="drawing"),
                {"theme": self.mode, "overlays": self._overlays()})

    def _export_animation(self) -> None:
        plan, options = self._animation_request()
        folder = Path(self._outputs.destination or Path.home())
        path, _ = QFileDialog.getSaveFileName(
            self, "Export animation",
            str(folder / f"cycloidal_{self.spec.ratio}to1_{plan.view}.gif"),
            "Animated GIF (*.gif)")
        if not path:
            return

        self._anim_progress = QProgressDialog(
            f"Rendering the {plan.view}: {plan.describe()}.",
            "Cancel", 0, plan.frames, self)
        self._anim_progress.setWindowTitle("Export animation")
        self._anim_progress.setWindowModality(Qt.WindowModal)
        self._anim_progress.setMinimumDuration(0)
        self._anim_progress.setValue(0)

        self._anim_worker = AnimationWorker(self.spec.model_copy(deep=True),
                                            Path(path), plan, options)
        self._anim_worker.progressed.connect(self._animation_progress)
        self._anim_worker.done.connect(self._animation_done)
        self._anim_worker.failed.connect(self._animation_failed)
        self._anim_progress.canceled.connect(self._anim_worker.cancel)
        self._anim_worker.start()

    def _animation_progress(self, done: int, _total: int) -> None:
        # One tick is still in flight when Cancel is pressed, and a progress
        # dialog told to advance after it has been reset puts itself back on
        # screen.
        if not self._anim_progress.wasCanceled():
            self._anim_progress.setValue(done)

    def _animation_done(self, path: str) -> None:
        self._anim_progress.reset()
        written = Path(path)
        size = written.stat().st_size / 1024
        self._say(f"wrote {written} ({size:.0f} kB)", seconds=6)
        QMessageBox.information(
            self, "Animation written",
            f"{written}\n\n{size:.0f} kB. It loops for ever - drop it straight "
            f"into a document, a chat or an issue.")

    def _animation_failed(self, message: str) -> None:
        self._anim_progress.reset()
        if not message:                               # cancelled, not broken
            self._say("animation cancelled", seconds=4)
            return
        QMessageBox.critical(self, "Animation failed", message[-2000:])

    # ---------------------------------------------------------------- close
    def closeEvent(self, event) -> None:
        self._settings.setValue("last_design", self.spec.model_dump_json())
        self._settings.setValue("last_design_version", __version__)
        self._save_workspace()
        for worker in list(self._workers):
            worker.wait(2000)
        # The animation is the one job long enough to still be running here, and
        # a QThread destroyed while running takes the process with it.
        rendering = getattr(self, "_anim_worker", None)
        if rendering is not None and rendering.isRunning():
            rendering.cancel()
            rendering.wait(3000)
        super().closeEvent(event)
