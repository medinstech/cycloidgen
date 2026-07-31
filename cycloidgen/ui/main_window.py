"""The desktop application window."""
from __future__ import annotations

import json
import logging
import traceback
from pathlib import Path

import matplotlib

matplotlib.use("QtAgg")

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as Canvas  # noqa: E402
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavBar  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from PySide6.QtCore import QSettings, Qt, QThread, QTimer, Signal  # noqa: E402
from PySide6.QtGui import (QAction, QColor, QKeySequence, QPalette)  # noqa: E402
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox,  # noqa: E402
                               QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QProgressDialog, QPushButton, QScrollArea,
                               QSlider, QSpinBox, QSplitter, QStatusBar,
                               QTabWidget, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ..analysis import DesignAnalysis, analyse
from ..core.spec import GearSpec, OffsetMode, Process, preset
from ..core.validate import Severity
from ..export import write_bundle
from ..report import plots
from .fields import CODE_FIELDS, GROUPS, Field
from .history import SpecHistory
from .logpanel import LogPanel, install as install_logging, logger
from .optimise_dialog import OptimiseDialog
from .tradestudy import TradeStudyTab

SEVERITY_COLOR = {
    Severity.ERROR: QColor("#c0392b"),
    Severity.WARNING: QColor("#b8860b"),
    Severity.INFO: QColor("#52514e"),
}

#: Highlight left on a parameter that a selected finding points at.
_HIGHLIGHT = "border: 1px solid #eb6834; border-radius: 3px;"

_MAX_RECENT = 8


class ExportWorker(QThread):
    """Runs the export off the GUI thread - STEP/STL take about a second."""

    done = Signal(list)
    failed = Signal(str)

    def __init__(self, spec: GearSpec, directory: Path, solids: bool):
        super().__init__()
        self._spec, self._dir, self._solids = spec, directory, solids

    def run(self) -> None:
        try:
            logger.info("export started: %s (%s)", self._dir,
                        "all files" if self._solids else "drawings only")
            files = write_bundle(self._spec, self._dir, self._solids)
            for path in files:
                logger.debug("wrote %s (%.0f kB)", path, path.stat().st_size / 1024)
            self.done.emit([str(p) for p in files])
        except Exception:
            logger.error("export failed\n%s", traceback.format_exc().rstrip())
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

        self._settings = QSettings("cycloidgen", "cycloidgen")
        self.spec = self._restore_spec()
        self.analysis: DesignAnalysis | None = None
        self._pinned: GearSpec | None = None
        self._pinned_analysis: DesignAnalysis | None = None
        self._widgets: dict[str, QWidget] = {}
        self._rows: dict[str, tuple[QWidget, QWidget]] = {}
        self._groups: list[tuple[QGroupBox, list[str]]] = []
        self._updating = False
        self._crank = 0.0
        self._generation = 0
        self._last_codes: set[str] | None = None
        self._log_badge = 0
        self._workers: list[AnalysisWorker] = []
        self._history = SpecHistory(self.spec)
        self._highlighted: list[QWidget] = []

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(120)
        self._debounce.timeout.connect(self._recompute)

        self._anim = QTimer(self)
        self._anim.setInterval(40)
        self._anim.timeout.connect(self._advance_crank)

        # follow the desktop theme so the plots do not sit on a white slab
        # inside a dark window
        window = self.palette().color(QPalette.Window)
        plots.set_theme("dark" if window.lightness() < 128 else "light")

        self._build_ui()
        self._load_spec_into_widgets()
        self._recompute()

    # ------------------------------------------------------------------ build
    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_parameter_panel())
        splitter.addWidget(self._build_view_panel())
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([400, 1040])
        self.setCentralWidget(splitter)

        self.setStatusBar(QStatusBar())
        self._build_menu()
        geometry = self._settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

    def _build_parameter_panel(self) -> QWidget:
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(8, 8, 8, 8)

        row = QHBoxLayout()
        row.addWidget(QLabel("Preset"))
        self._preset_box = QComboBox()
        for r in (10, 15, 21, 29, 39, 59):
            self._preset_box.addItem(f"{r}:1", r)
        self._preset_box.setCurrentIndex(1)
        self._preset_box.activated.connect(self._apply_preset)
        row.addWidget(self._preset_box, 1)
        layout.addLayout(row)

        self._optimise_btn = QPushButton("Design for requirements...")
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
            box = QGroupBox(title)
            form = QFormLayout(box)
            form.setLabelAlignment(Qt.AlignRight)
            for f in fields:
                w = self._make_widget(f)
                self._widgets[f.name] = w
                if f.tip:
                    w.setToolTip(f.tip)
                label = QLabel(f.label)
                form.addRow(label, w)
                self._rows[f.name] = (label, w)
            layout.addWidget(box)
            self._groups.append((box, [f.name for f in fields]))

        btn = QPushButton("Apply process defaults")
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
        return scroll

    def _make_widget(self, f: Field) -> QWidget:
        if f.kind == "float":
            w = QDoubleSpinBox()
            w.setRange(f.minimum, f.maximum)
            w.setSingleStep(f.step)
            w.setDecimals(f.decimals)
            w.setSuffix(f.suffix)
            w.valueChanged.connect(lambda _v, n=f.name: self._on_change(n))
        elif f.kind == "int":
            w = QSpinBox()
            w.setRange(int(f.minimum), int(f.maximum))
            w.setSingleStep(int(f.step))
            w.setSuffix(f.suffix)
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
        page = QWidget()
        pv = QVBoxLayout(page)
        pv.addWidget(NavBar(self._canvas_profile, page))
        pv.addWidget(self._canvas_profile, 1)

        crank_row = QHBoxLayout()
        crank_row.addWidget(QLabel("Crank"))
        self._crank_slider = QSlider(Qt.Horizontal)
        self._crank_slider.setRange(0, 359)
        self._crank_slider.valueChanged.connect(self._on_crank)
        crank_row.addWidget(self._crank_slider, 1)
        self._crank_label = QLabel("0 deg")
        self._crank_label.setMinimumWidth(56)
        crank_row.addWidget(self._crank_label)
        self._play = QPushButton("Rotate")
        self._play.setCheckable(True)
        self._play.toggled.connect(self._toggle_animation)
        crank_row.addWidget(self._play)
        pv.addLayout(crank_row)
        self.tabs.addTab(page, "Drawing")

        self._fig_force = Figure(figsize=(6.4, 3.6), dpi=100)
        self._canvas_force = Canvas(self._fig_force)
        self.tabs.addTab(self._canvas_force, "Loads")

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
        self.tabs.addTab(loss_page, "Efficiency")

        self._datasheet = QTreeWidget()
        self._datasheet.setHeaderLabels(["Quantity", "Value", "Note"])
        self._datasheet.setColumnWidth(0, 260)
        self._datasheet.setColumnWidth(1, 150)
        self.tabs.addTab(self._datasheet, "Datasheet")

        self._trade = TradeStudyTab()
        self.tabs.addTab(self._trade, "Trade study")

        self._compare_page = self._build_compare_tab()
        self.tabs.addTab(self._compare_page, "Compare")

        self._log_tab = self.tabs.addTab(self.log, "Log")
        self.tabs.setTabToolTip(self._log_tab,
                                "Everything the app would otherwise print to a "
                                "terminal you do not have.")
        self.log.problem.connect(self._flag_log)
        self.tabs.currentChanged.connect(self._tab_changed)
        layout.addWidget(self.tabs, 1)

        self.findings = QTreeWidget()
        self.findings.setHeaderLabels(["", "Check", "Detail", "Value", "Limit"])
        self.findings.setRootIsDecorated(False)
        self.findings.setMaximumHeight(190)
        self.findings.currentItemChanged.connect(self._finding_selected)
        header = self.findings.header()
        for col, width in ((0, 70), (1, 190), (3, 80), (4, 80)):
            self.findings.setColumnWidth(col, width)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(2, header.ResizeMode.Stretch)
        layout.addWidget(self.findings)

        row = QHBoxLayout()
        self._export_btn = QPushButton("Export all files...")
        self._export_btn.clicked.connect(lambda: self._export(True))
        row.addWidget(self._export_btn)
        self._export_2d_btn = QPushButton("Export drawings only")
        self._export_2d_btn.clicked.connect(lambda: self._export(False))
        row.addWidget(self._export_2d_btn)
        row.addStretch(1)
        self._pin_btn = QPushButton("Pin as reference")
        self._pin_btn.setToolTip("Keep this design to compare later changes "
                                 "against. It shows as a ghost on the drawing.")
        self._pin_btn.clicked.connect(self._pin_reference)
        row.addWidget(self._pin_btn)
        layout.addLayout(row)
        return panel

    def _build_compare_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._compare_note = QLabel(
            "Nothing pinned yet. Press <b>Pin as reference</b> to freeze the "
            "current design, then change things: this tab shows what moved and "
            "the drawing shows the old outline underneath.")
        self._compare_note.setWordWrap(True)
        layout.addWidget(self._compare_note)

        self._compare = QTreeWidget()
        self._compare.setHeaderLabels(["Quantity", "Reference", "Current", "Change"])
        self._compare.setRootIsDecorated(False)
        self._compare.setAlternatingRowColors(True)
        for col, width in ((0, 260), (1, 140), (2, 140), (3, 140)):
            self._compare.setColumnWidth(col, width)
        layout.addWidget(self._compare, 1)

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
        return page

    def _build_menu(self) -> None:
        m = self.menuBar().addMenu("&File")
        for text, slot, key in (
            ("&Open design...", self._open_spec, QKeySequence.Open),
            ("&Save design...", self._save_spec, QKeySequence.Save),
            ("&Export all files...", lambda: self._export(True), "Ctrl+E"),
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

    # ------------------------------------------------------------------- log
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
        self.tabs.setTabText(self._log_tab, "Log !" + "!" * (self._log_badge - 1))

    def _tab_changed(self, index: int) -> None:
        if index == self._log_tab:
            self._log_badge = 0
            self.tabs.setTabText(self._log_tab, "Log")

    # ----------------------------------------------------------------- state
    def _restore_spec(self) -> GearSpec:
        """Reopen on the design the last session was working on."""
        saved = self._settings.value("last_design")
        if saved:
            try:
                return GearSpec.model_validate_json(saved)
            except Exception:
                pass
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
                        w.setValue(0.0 if v is None else float(v))
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
        self._debounce.start()

    def _replace_spec(self, spec: GearSpec, *, record: bool = True) -> None:
        """Swap the whole design - a preset, a file, an optimiser result."""
        self.spec = spec
        if record:
            self._history.push(spec)
        self._update_history_actions()
        self._load_spec_into_widgets()
        self._recompute()

    def _apply_preset(self) -> None:
        self._replace_spec(preset(int(self._preset_box.currentData())))

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
        self._fill_datasheet()
        self._fill_compare()
        self._log_findings()
        self._trade.set_spec(self.spec)

        s, a = self.spec, self.analysis
        self._export_btn.setEnabled(a.report.ok)
        self._export_2d_btn.setEnabled(a.report.ok)
        e = a.efficiency

        def contact_kind(rolling: bool) -> str:
            return "rolling" if rolling else "fixed, sliding contact"

        self._loss_note.setText(
            f"Ring pins: {contact_kind(s.ring_pins_are_rollers)}.   "
            f"Output pins: {contact_kind(s.output_pins_are_rollers)}.   "
            f"{e.input_torque_Nm:.3f} Nm in at {s.input_rpm:g} rpm delivers "
            f"{e.output_power_W:.2f} W of the {e.input_power_W:.2f} W supplied. "
            f"Losses scale with the friction coefficient, so lubrication and rolling "
            f"elements move this number further than any geometry change.")
        self.statusBar().showMessage(
            f"{s.ratio}:1   OD {2 * s.housing_outer_radius:.1f} mm   "
            f"stack {s.stack_height:.1f} mm   {a.mass.total_mass_g:.0f} g   "
            f"efficiency {100 * a.efficiency.efficiency:.1f}%   "
            f"capacity {a.torque_capacity_with_clearance_Nm:.2f} Nm   "
            f"backlash {a.stiffness.lost_motion_arcmin:.0f}'   "
            f"{a.thermal.temperature_C:.0f} C"
            + ("" if a.report.ok else "   -   EXPORT BLOCKED, fix the errors below"))

    def _draw_profile(self) -> None:
        plots.profile_figure(self.spec, self._fig_profile, crank_deg=self._crank,
                             reference=self._pinned)
        self._canvas_profile.draw_idle()

    def _fill_findings(self) -> None:
        self.findings.clear()
        assert self.analysis is not None
        for f in self.analysis.report.findings:
            item = QTreeWidgetItem([
                f.severity.value.upper(), f.code, f.message,
                f"{f.value:.4g}" if f.value is not None else "",
                f"{f.limit:.4g}" if f.limit is not None else ""])
            item.setForeground(0, SEVERITY_COLOR[f.severity])
            item.setData(0, Qt.UserRole, f.code)
            self.findings.addTopLevelItem(item)
        if not self.analysis.report.findings:
            self.findings.addTopLevelItem(QTreeWidgetItem(["", "", "No findings.", "", ""]))

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
        """Point at the parameters the selected check is actually about."""
        for w in self._highlighted:
            w.setStyleSheet("")
        self._highlighted.clear()
        if current is None:
            return
        code = current.data(0, Qt.UserRole)
        first = None
        for name in CODE_FIELDS.get(code, ()):
            row = self._rows.get(name)
            if row is None:
                continue
            _label, widget = row
            widget.setStyleSheet(_HIGHLIGHT)
            self._highlighted.append(widget)
            first = first or widget
        if first is not None:
            self._param_scroll.ensureWidgetVisible(first, 0, 60)

    def _fill_datasheet(self) -> None:
        """The numbers you would put on a spec sheet, in one place."""
        a = self.analysis
        assert a is not None
        s, st, th, m = self.spec, a.stiffness, a.thermal, a.mass
        self._datasheet.clear()
        sections = [
            ("Ratings", [
                ("Reduction", f"{s.ratio}:1", "ring fixed, output from the disc"),
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
                 "contacts only; housing and shaft taken as rigid"),
                ("Lost motion", f"{st.lost_motion_arcmin:.1f} arcmin",
                 f"{st.lost_motion_ring_arcmin:.1f} profile + "
                 f"{st.lost_motion_output_arcmin:.1f} holes"),
                ("Wind-up at rated torque", f"{st.windup_arcmin:.2f} arcmin", "elastic"),
                ("Total backlash", f"{st.backlash_total_arcmin:.1f} arcmin",
                 "lost motion plus wind-up"),
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
                ("Thinnest disc web", f"{m.min_web_mm:.2f} mm",
                 f"shear safety factor {m.web_safety_factor:.1f}"),
            ]),
            ("Envelope", [
                ("Outer diameter", f"{2 * s.housing_outer_radius:.1f} mm", ""),
                ("Overall length", f"{s.envelope_length:.1f} mm",
                 "disc stack plus output flange"),
                ("Output speed", f"{s.output_rpm:.1f} rpm", ""),
            ]),
        ]
        for title, rows in sections:
            parent = QTreeWidgetItem([title, "", ""])
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            self._datasheet.addTopLevelItem(parent)
            for name, value, note in rows:
                parent.addChild(QTreeWidgetItem([name, value, note]))
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
        self._compare.clear()
        self._compare_note.setText("Nothing pinned.")
        self._draw_profile()

    def _restore_reference(self) -> None:
        if self._pinned is not None:
            self._replace_spec(self._pinned.model_copy(deep=True))

    def _fill_compare(self) -> None:
        self._compare.clear()
        if self._pinned_analysis is None or self.analysis is None:
            return
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
        for name, unit, before, after, higher_better in rows:
            delta = after - before
            if abs(before) > 1e-12:
                text = f"{delta:+.3g} {unit} ({100 * delta / abs(before):+.1f} %)"
            else:
                text = f"{delta:+.3g} {unit}"
            item = QTreeWidgetItem([name, f"{before:.4g} {unit}".strip(),
                                    f"{after:.4g} {unit}".strip(), text.strip()])
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
        self._crank_label.setText(f"{value} deg")
        self._draw_profile()

    def _advance_crank(self) -> None:
        self._crank_slider.setValue(int((self._crank_slider.value() + 4) % 360))

    def _toggle_animation(self, on: bool) -> None:
        self._play.setText("Stop" if on else "Rotate")
        self._anim.start() if on else self._anim.stop()

    # ---------------------------------------------------------------- files
    def _save_spec(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save design", f"cycloidal_{self.spec.ratio}to1.json",
            "Design files (*.json)")
        if path:
            Path(path).write_text(self.spec.model_dump_json(indent=2), encoding="utf-8")
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
            data = data.get("spec", data)             # accept a full report too
            spec = GearSpec.model_validate(data)
        except Exception as exc:
            logger.error("could not open %s: %s", path, exc)
            QMessageBox.critical(self, "Could not open", str(exc))
            return
        self._history.reset(spec)
        self._replace_spec(spec, record=False)
        self._remember_recent(path)
        self._say(f"opened {path}", seconds=4)

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
        if self.analysis is None or not self.analysis.report.ok:
            QMessageBox.warning(self, "Blocked",
                                "Fix the errors in the checks list before exporting.")
            return
        directory = QFileDialog.getExistingDirectory(self, "Export into folder")
        if not directory:
            return

        target = Path(directory) / f"cycloidal_{self.spec.ratio}to1"
        self._progress = QProgressDialog("Generating files...", "", 0, 0, self)
        self._progress.setCancelButton(None)
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.show()

        self._worker = ExportWorker(self.spec.model_copy(deep=True), target, solids)
        self._worker.done.connect(self._export_done)
        self._worker.failed.connect(self._export_failed)
        self._worker.start()

    def _export_done(self, files: list[str]) -> None:
        self._progress.close()
        self._say(f"wrote {len(files)} files to {Path(files[0]).parent}", seconds=6)
        QMessageBox.information(
            self, "Export complete",
            f"{len(files)} files written to\n{Path(files[0]).parent}")

    def _export_failed(self, message: str) -> None:
        self._progress.close()
        QMessageBox.critical(self, "Export failed", message[-2000:])

    # ---------------------------------------------------------------- close
    def closeEvent(self, event) -> None:
        self._settings.setValue("last_design", self.spec.model_dump_json())
        self._settings.setValue("geometry", self.saveGeometry())
        for worker in list(self._workers):
            worker.wait(2000)
        super().closeEvent(event)
