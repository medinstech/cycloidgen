"""The trade-study tab: move one parameter, watch the other four move.

The rest of the window answers questions about a single point in the design
space.  This answers the question that point cannot: *which way should I go?*
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel,
                               QProgressBar, QPushButton, QSpinBox, QVBoxLayout,
                               QWidget)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as Canvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavBar
from matplotlib.figure import Figure

import numpy as np

from ..core.spec import GearSpec
from ..design.sweep import SWEEPABLE, SweepResult, suggested_range, sweep_parameter
from ..report import plots
from .logpanel import logger

__all__ = ["TradeStudyTab"]


class _Worker(QThread):
    tick = Signal(int, int)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, spec: GearSpec, field: str, values) -> None:
        super().__init__()
        self._spec, self._field, self._values = spec, field, values
        self._stop = False

    def cancel(self) -> None:
        self._stop = True

    def run(self) -> None:
        logger.info("sweep: %s over %.4g..%.4g in %d steps", self._field,
                    self._values[0], self._values[-1], len(self._values))
        try:
            result = sweep_parameter(
                self._spec, self._field, self._values,
                progress=lambda d, t: self.tick.emit(d, t),
                cancelled=lambda: self._stop)
        except Exception as exc:                       # pragma: no cover - GUI path
            import traceback
            logger.error("sweep failed\n%s", traceback.format_exc().rstrip())
            self.failed.emit(str(exc))
            return
        blocked = result.blocked
        if blocked:
            logger.warning("sweep: %d of %d designs blocked, from %s = %.4g",
                           len(blocked), len(result.points), self._field,
                           blocked[0].value)
        logger.info("sweep: %d design(s) analysed", len(result.points))
        self.done.emit(result)


class TradeStudyTab(QWidget):
    """Pick a parameter, pick a range, get four curves."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._spec: GearSpec | None = None
        self._worker: _Worker | None = None
        self._result: SweepResult | None = None

        layout = QVBoxLayout(self)
        layout.addLayout(self._build_controls())

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._figure = Figure(figsize=(7.2, 5.0), dpi=100)
        self._canvas = Canvas(self._figure)
        layout.addWidget(NavBar(self._canvas, self))
        layout.addWidget(self._canvas, 1)

        self._note = QLabel("Pick a parameter and press Run. The dashed line is "
                            "where the current design sits.")
        self._note.setWordWrap(True)
        layout.addWidget(self._note)

    def _build_controls(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Sweep"))
        self._field = QComboBox()
        for name, (label, unit) in SWEEPABLE.items():
            self._field.addItem(f"{label}" + (f" ({unit})" if unit else ""), name)
        self._field.currentIndexChanged.connect(self._reset_range)
        row.addWidget(self._field, 1)

        row.addWidget(QLabel("from"))
        self._lo = QDoubleSpinBox(); self._lo.setRange(-1e6, 1e6); self._lo.setDecimals(3)
        row.addWidget(self._lo)
        row.addWidget(QLabel("to"))
        self._hi = QDoubleSpinBox(); self._hi.setRange(-1e6, 1e6); self._hi.setDecimals(3)
        row.addWidget(self._hi)
        row.addWidget(QLabel("steps"))
        self._steps = QSpinBox(); self._steps.setRange(3, 81); self._steps.setValue(21)
        row.addWidget(self._steps)

        self._run_btn = QPushButton("Run")
        self._run_btn.setProperty("primary", "true")
        self._run_btn.clicked.connect(self._run)
        row.addWidget(self._run_btn)
        return row

    # ------------------------------------------------------------------ state
    def set_spec(self, spec: GearSpec) -> None:
        """Follow the main window's design; the plot stays until re-run."""
        first = self._spec is None
        self._spec = spec
        if first:
            self._reset_range()

    def _reset_range(self) -> None:
        if self._spec is None:
            return
        lo, hi, steps = suggested_range(self._spec, self._field.currentData())
        self._lo.setValue(lo)
        self._hi.setValue(hi)
        self._steps.setValue(steps)

    # -------------------------------------------------------------- searching
    def _run(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            return
        if self._spec is None:
            return
        field = self._field.currentData()
        values = np.linspace(self._lo.value(), self._hi.value(), self._steps.value())

        self._progress.setVisible(True)
        self._progress.setRange(0, len(values))
        self._progress.setValue(0)
        self._run_btn.setText("Stop")
        self._note.setText(f"Analysing {len(values)} designs...")

        self._worker = _Worker(self._spec.model_copy(deep=True), field, values)
        self._worker.tick.connect(self._on_tick)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(lambda m: self._note.setText(f"Sweep failed: {m}"))
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_tick(self, done: int, total: int) -> None:
        self._progress.setValue(done)

    def _on_finished(self) -> None:
        self._worker = None
        self._progress.setVisible(False)
        self._run_btn.setText("Run")

    def _on_done(self, result: SweepResult) -> None:
        self._result = result
        plots.sweep_figure(result, self._figure)
        self._canvas.draw_idle()

        good = [p for p in result.points if p.ok]
        if not good:
            self._note.setText("Every design in that range fails a check.")
            return
        best_cap = max(good, key=lambda p: p.capacity_Nm)
        best_eff = max(good, key=lambda p: p.efficiency)
        lightest = min(good, key=lambda p: p.mass_g)
        self._note.setText(
            f"Over this range: most torque at {result.label} = "
            f"{best_cap.value:.3g} {result.unit} ({best_cap.capacity_Nm:.2f} Nm), "
            f"best efficiency at {best_eff.value:.3g} {result.unit} "
            f"({100 * best_eff.efficiency:.1f} %), lightest at "
            f"{lightest.value:.3g} {result.unit} ({lightest.mass_g:.0f} g). "
            f"{len(result.blocked)} of {len(result.points)} designs are blocked.")
