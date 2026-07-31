"""The "design this for me" dialog.

You state what the drive has to do; the search comes back with the geometry.
The results table deliberately shows the trade-offs side by side rather than a
single winner, because "best" depends on which column you care about and the
optimiser only knows what it was told.

When nothing meets the requirements the dialog says which constraint did the
killing.  An empty table with no explanation is the one outcome that would make
this worse than tuning by hand.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.spec import MATERIALS, GearSpec, OffsetMode, Process
from ..design import (
    Candidate,
    Objective,
    OptimisationResult,
    Requirements,
    optimise,
    requirements_from_spec,
)
from .logpanel import logger

__all__ = ["OptimiseDialog"]

_EFFORTS = (("Quick (~3 s)", "quick"),
            ("Normal (~8 s)", "normal"),
            ("Thorough (~20 s)", "thorough"))


class _Worker(QThread):
    """Runs the search off the GUI thread and reports progress back."""

    tick = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, req: Requirements, effort: str) -> None:
        super().__init__()
        self._req, self._effort = req, effort
        self._stop = False

    def cancel(self) -> None:
        self._stop = True

    def run(self) -> None:
        r = self._req
        logger.info("search: %s:1, %g Nm out at %g rpm, under %g x %g mm, "
                    "%s disc in a %s housing, optimising for %s (%s effort)",
                    r.ratio, r.output_torque_Nm, r.input_rpm,
                    r.max_outer_diameter_mm, r.max_length_mm, r.disc_material,
                    r.housing_material, r.objective.value, self._effort)
        try:
            result = optimise(self._req, effort=self._effort,
                              progress=lambda d, t, m: self.tick.emit(d, t, m),
                              cancelled=lambda: self._stop)
        except Exception as exc:                       # pragma: no cover - GUI path
            import traceback
            logger.error("search failed\n%s", traceback.format_exc().rstrip())
            self.failed.emit(str(exc))
            return

        if result.best:
            logger.info("search: %d design(s) from %d candidates",
                        len(result.best), result.evaluations)
            for i, c in enumerate(result.best, 1):
                logger.info("  #%d  OD %.1f  len %.1f  %.2f Nm (%.2fx)  "
                            "eff %.1f%%  %.0f g  backlash %.1f'  %.0f C  %d warn",
                            i, c.outer_diameter_mm, c.length_mm, c.capacity_Nm,
                            c.margin, 100 * c.efficiency, c.mass_g,
                            c.lost_motion_arcmin, c.temperature_C, c.warnings)
        else:
            logger.warning("search: nothing met the requirements after %d "
                           "candidates - %s", result.evaluations,
                           result.tally.explain())
        self.done.emit(result)


class OptimiseDialog(QDialog):
    """Requirements in, ranked designs out."""

    def __init__(self, spec: GearSpec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Design for requirements")
        self.resize(1080, 660)
        self.chosen: GearSpec | None = None
        self._worker: _Worker | None = None
        self._result: OptimisationResult | None = None

        self._req = requirements_from_spec(spec)
        outer = QHBoxLayout(self)
        outer.addWidget(self._build_form(), 0)
        outer.addLayout(self._build_results(), 1)
        self._load()

    # ------------------------------------------------------------------ build
    def _build_form(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(330)
        layout = QVBoxLayout(panel)

        duty = QGroupBox("Duty")
        f = QFormLayout(duty)
        self._ratio = QSpinBox()
        self._ratio.setRange(3, 200)
        self._ratio.setSuffix(" :1")
        self._torque = QDoubleSpinBox()
        self._torque.setRange(0.01, 10000)
        self._torque.setDecimals(2)
        self._torque.setSuffix(" Nm")
        self._rpm = QDoubleSpinBox()
        self._rpm.setRange(1, 30000)
        self._rpm.setDecimals(0)
        self._rpm.setSuffix(" rpm")
        f.addRow("Reduction", self._ratio)
        f.addRow("Output torque", self._torque)
        f.addRow("Input speed", self._rpm)
        layout.addWidget(duty)

        env = QGroupBox("Envelope")
        f = QFormLayout(env)
        self._max_od = QDoubleSpinBox()
        self._max_od.setRange(10, 2000)
        self._max_od.setDecimals(1)
        self._max_od.setSuffix(" mm")
        self._max_len = QDoubleSpinBox()
        self._max_len.setRange(5, 2000)
        self._max_len.setDecimals(1)
        self._max_len.setSuffix(" mm")
        self._wall = QDoubleSpinBox()
        self._wall.setRange(1, 100)
        self._wall.setDecimals(1)
        self._wall.setSuffix(" mm")
        self._discs = QComboBox()
        self._discs.addItem("Let the search choose", 0)
        for n in (1, 2, 3):
            self._discs.addItem(f"{n} disc" + ("s" if n > 1 else ""), n)
        f.addRow("Max outer diameter", self._max_od)
        f.addRow("Max length", self._max_len)
        f.addRow("Housing wall", self._wall)
        f.addRow("Discs", self._discs)
        layout.addWidget(env)

        build = QGroupBox("Build")
        f = QFormLayout(build)
        self._process = QComboBox()
        self._process.addItems([p.value for p in Process])
        self._offset = QComboBox()
        self._offset.addItems([m.value for m in OffsetMode])
        self._disc_mat = QComboBox()
        self._disc_mat.addItems(list(MATERIALS))
        self._pin_mat = QComboBox()
        self._pin_mat.addItems(list(MATERIALS))
        self._house_mat = QComboBox()
        self._house_mat.addItems(list(MATERIALS))
        self._shaft_mat = QComboBox()
        self._shaft_mat.addItems(list(MATERIALS))
        self._ring_rollers = QCheckBox("Ring pins are rollers")
        self._out_rollers = QCheckBox("Output pins carry rollers")
        f.addRow("Process", self._process)
        f.addRow("Clearance as", self._offset)
        f.addRow("Disc", self._disc_mat)
        f.addRow("Pins", self._pin_mat)
        f.addRow("Housing", self._house_mat)
        f.addRow("Shaft", self._shaft_mat)
        f.addRow("", self._ring_rollers)
        f.addRow("", self._out_rollers)
        layout.addWidget(build)

        goal = QGroupBox("Goal")
        f = QFormLayout(goal)
        self._objective = QComboBox()
        for o in Objective:
            self._objective.addItem(o.value, o)
        self._sf = QDoubleSpinBox()
        self._sf.setRange(0.5, 10.0)
        self._sf.setSingleStep(0.1)
        self._sf.setDecimals(2)
        self._sf.setToolTip("Required margin on ring contact stress, after "
                            "clearance is allowed to concentrate the load.")
        self._min_eff = QDoubleSpinBox()
        self._min_eff.setRange(0, 99)
        self._min_eff.setDecimals(0)
        self._min_eff.setSuffix(" %")
        self._max_lost = QDoubleSpinBox()
        self._max_lost.setRange(0, 600)
        self._max_lost.setDecimals(0)
        self._max_lost.setSuffix(" arcmin")
        self._max_lost.setToolTip("0 = no limit")
        self._effort = QComboBox()
        for label, key in _EFFORTS:
            self._effort.addItem(label, key)
        self._effort.setCurrentIndex(1)
        f.addRow("Optimise for", self._objective)
        f.addRow("Min safety factor", self._sf)
        f.addRow("Min efficiency", self._min_eff)
        f.addRow("Max lost motion", self._max_lost)
        f.addRow("Search effort", self._effort)
        layout.addWidget(goal)

        layout.addStretch(1)
        self._run_btn = QPushButton("Search")
        self._run_btn.setProperty("primary", "true")
        self._run_btn.setDefault(True)
        self._run_btn.clicked.connect(self._run)
        layout.addWidget(self._run_btn)
        return panel

    def _build_results(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        self._status = QLabel("Set the requirements and press Search.")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._table = QTreeWidget()
        self._table.setHeaderLabels([
            "Design", "OD", "Length", "Capacity", "Margin", "Efficiency",
            "Mass", "Lost motion", "Stiffness", "Temp", "Warn"])
        self._table.setRootIsDecorated(False)
        self._table.setAlternatingRowColors(True)
        for col, width in enumerate((250, 62, 62, 78, 62, 74, 64, 84, 82, 58, 46)):
            self._table.setColumnWidth(col, width)
        self._table.itemSelectionChanged.connect(self._selection_changed)
        self._table.itemDoubleClicked.connect(lambda *_: self._accept_selected())
        layout.addWidget(self._table, 1)

        self._detail = QLabel()
        self._detail.setWordWrap(True)
        self._detail.setTextFormat(Qt.RichText)
        layout.addWidget(self._detail)

        self._buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self._apply_btn = self._buttons.addButton("Use this design",
                                                  QDialogButtonBox.AcceptRole)
        self._apply_btn.setEnabled(False)
        self._buttons.accepted.connect(self._accept_selected)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)
        return layout

    # ------------------------------------------------------------------ state
    def _load(self) -> None:
        r = self._req
        self._ratio.setValue(r.ratio)
        self._torque.setValue(r.output_torque_Nm)
        self._rpm.setValue(r.input_rpm)
        self._max_od.setValue(r.max_outer_diameter_mm)
        self._max_len.setValue(r.max_length_mm)
        self._wall.setValue(r.housing_wall)
        self._discs.setCurrentIndex(
            [0, 1, 2, 3].index(r.disc_count) if r.disc_count in (0, 1, 2, 3) else 0)
        self._process.setCurrentText(r.process.value)
        self._offset.setCurrentText(r.offset_mode.value)
        self._disc_mat.setCurrentText(r.disc_material)
        self._pin_mat.setCurrentText(r.pin_material)
        self._house_mat.setCurrentText(r.housing_material)
        self._shaft_mat.setCurrentText(r.shaft_material)
        self._ring_rollers.setChecked(r.ring_pins_are_rollers)
        self._out_rollers.setChecked(r.output_pins_are_rollers)
        self._sf.setValue(r.min_safety_factor)
        self._min_eff.setValue(100 * r.min_efficiency)
        self._max_lost.setValue(r.max_lost_motion_arcmin)

    def _collect(self) -> Requirements:
        return Requirements(
            ratio=self._ratio.value(),
            output_torque_Nm=self._torque.value(),
            input_rpm=self._rpm.value(),
            max_outer_diameter_mm=self._max_od.value(),
            max_length_mm=self._max_len.value(),
            housing_wall=self._wall.value(),
            process=Process(self._process.currentText()),
            offset_mode=OffsetMode(self._offset.currentText()),
            disc_material=self._disc_mat.currentText(),
            pin_material=self._pin_mat.currentText(),
            housing_material=self._house_mat.currentText(),
            shaft_material=self._shaft_mat.currentText(),
            ring_pins_are_rollers=self._ring_rollers.isChecked(),
            output_pins_are_rollers=self._out_rollers.isChecked(),
            disc_count=self._discs.currentData(),
            min_safety_factor=self._sf.value(),
            min_efficiency=self._min_eff.value() / 100.0,
            max_lost_motion_arcmin=self._max_lost.value(),
            objective=self._objective.currentData(),
        )

    # -------------------------------------------------------------- searching
    def _run(self) -> None:
        if self._worker is not None:                 # second press = cancel
            self._worker.cancel()
            self._run_btn.setEnabled(False)
            return
        try:
            req = self._collect()
        except Exception as exc:
            self._status.setText(f"Those requirements do not make sense: {exc}")
            return

        self._table.clear()
        self._detail.clear()
        self._apply_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)
        self._status.setText("Searching...")
        self._run_btn.setText("Stop")

        self._worker = _Worker(req, self._effort.currentData())
        self._worker.tick.connect(self._on_tick)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_tick(self, done: int, total: int, message: str) -> None:
        self._progress.setRange(0, total)
        self._progress.setValue(done)
        self._status.setText(f"Searching - {message}")

    def _on_failed(self, message: str) -> None:
        self._status.setText(f"Search failed: {message}")

    def _on_finished(self) -> None:
        self._worker = None
        self._progress.setVisible(False)
        self._run_btn.setText("Search")
        self._run_btn.setEnabled(True)

    def _on_done(self, result: OptimisationResult) -> None:
        self._result = result
        if not result.best:
            self._status.setText(
                f"Nothing met those requirements after {result.evaluations} "
                f"candidates. What stopped them: {result.tally.explain()}. "
                f"Loosen the envelope, drop the torque, or pick a stronger "
                f"disc material.")
            return

        self._status.setText(
            f"{len(result.best)} design(s) from {result.evaluations} candidates, "
            f"best first. Every one passes all checks; the columns are what they "
            f"trade against each other.")
        for cand in result.best:
            self._table.addTopLevelItem(_row(cand))
        self._table.setCurrentItem(self._table.topLevelItem(0))

    # -------------------------------------------------------------- selection
    def _current(self) -> Candidate | None:
        item = self._table.currentItem()
        if item is None or self._result is None:
            return None
        index = self._table.indexOfTopLevelItem(item)
        if 0 <= index < len(self._result.best):
            return self._result.best[index]
        return None

    def _selection_changed(self) -> None:
        cand = self._current()
        self._apply_btn.setEnabled(cand is not None)
        if cand is None:
            self._detail.clear()
            return
        s = cand.spec
        warnings = "; ".join(f.code for f in cand.analysis.report.warnings) \
            if cand.analysis else ""
        self._detail.setText(
            f"<b>R</b> {s.pin_circle_radius:.2f} mm &middot; "
            f"<b>Rr</b> {s.pin_radius:.2f} mm &middot; "
            f"<b>E</b> {s.eccentricity:.3f} mm &middot; "
            f"<b>K1</b> {s.K1:.3f} &middot; "
            f"bore {s.center_bore_diameter:.1f} mm on a "
            f"{s.input_shaft_diameter:.0f} mm shaft &middot; "
            f"{s.output_pin_count} x {s.output_pin_diameter:.1f} mm output pins on a "
            f"{s.output_bolt_circle_radius:.1f} mm circle"
            + (f"<br><span style='color:#b8860b'>warnings: {warnings}</span>"
               if warnings else ""))

    def _accept_selected(self) -> None:
        cand = self._current()
        if cand is None:
            return
        self.chosen = cand.spec
        self.accept()

    def reject(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait(3000)
        super().reject()


def _row(c: Candidate) -> QTreeWidgetItem:
    s = c.spec
    return QTreeWidgetItem([
        f"{s.ratio}:1  {s.disc_count}x{s.disc_thickness:.1f} mm  R{s.pin_circle_radius:.0f}",
        f"{c.outer_diameter_mm:.1f}",
        f"{c.length_mm:.1f}",
        f"{c.capacity_Nm:.2f} Nm",
        f"{c.margin:.2f}x",
        f"{100 * c.efficiency:.1f} %",
        f"{c.mass_g:.0f} g",
        f"{c.lost_motion_arcmin:.1f}'",
        f"{c.stiffness_Nm_per_arcmin:.2f}",
        f"{c.temperature_C:.0f} C",
        str(c.warnings),
    ])
