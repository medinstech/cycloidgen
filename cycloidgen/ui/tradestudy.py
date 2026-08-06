"""The trade-study tab: move one parameter, watch the other four move.

The rest of the window answers questions about a single point in the design
space.  This answers the question that point cannot: *which way should I go?*
"""
from __future__ import annotations

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as Canvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavBar
from matplotlib.figure import Figure
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.spec import GearSpec
from ..design.sweep import SWEEPABLE, SweepResult, suggested_range, sweep_parameter
from ..report import plots
from .logpanel import logger

__all__ = ["TradeStudyTab"]

#: The widest bound these boxes realistically hold - a five-figure input speed
#: with the decimals the geometry ones need.  They are capped at all because Qt
#: sizes a spin box for its whole *range*, and 0..100000 asks for far more than
#: any sweep bound uses; the cap is measured against this rather than picked,
#: because a figure chosen by eye is how the steps box came to display 21 as
#: "2" - 70 px is not two digits once the arrows and the frame have had theirs.
_WIDEST_BOUND = "100000.000"

#: ...and what it may shrink to when the window is narrow.  Four figures is
#: every bound anyone sweeps here except an input speed, so the number is
#: whole on almost every design and scrolls within its box on the rest.
_NARROWEST_BOUND = "0000"

#: What the chart says before it is a chart.  It goes *in* the panel: a blank
#: white rectangle under a toolbar reads as a chart that failed to draw, and a
#: caption below it is read after that conclusion has been reached.
_EMPTY_CHART = ("Pick a parameter above and press Run.\n\n"
                "Four curves come back - torque capacity, efficiency, lost\n"
                "motion and mass - against the one thing you swept, on their\n"
                "own units. The dashed line is where the current design sits,\n"
                "and shaded bands are where designs stop passing their checks.")


def _size_box(box, widest: str) -> None:
    """Room for ``widest`` when there is width to spare, and room to shrink.

    Both halves matter and the old code only had one.  A maximum on its own is
    what clipped the steps box, because Qt takes the *smaller* of the size hint
    and the maximum - so capping at 70 px hid a digit.  But raising the cap and
    stopping there pushes the whole window's smallest usable size up with it,
    since this row cannot then compress: doing only that moved it from 1077 px
    to 1247.  A low minimum is what lets the row give way on a narrow window
    while still showing the whole number wherever there is room for it.

    The frame and the arrows are measured off the widget's own size hint rather
    than allowed for by a constant, since how much they take is the style's
    business and differs between platforms and themes.
    """
    metrics = box.fontMetrics()
    longest = max((box.textFromValue(box.minimum()),
                   box.textFromValue(box.maximum())), key=len)
    chrome = box.sizeHint().width() - metrics.horizontalAdvance(longest)
    # A box whose widest value is already short - the steps one holds two
    # digits - must not be given a floor wider than its ceiling.  Qt resolves
    # that by raising the ceiling to meet it, which is the opposite of what
    # either number was for.
    room = metrics.horizontalAdvance(widest)
    box.setMaximumWidth(room + chrome)
    box.setMinimumWidth(min(room, metrics.horizontalAdvance(_NARROWEST_BOUND))
                        + chrome)


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
        plots.placeholder_figure(_EMPTY_CHART, self._figure)
        layout.addWidget(NavBar(self._canvas, self))
        layout.addWidget(self._canvas, 1)

        self._note = QLabel()
        self._note.setWordWrap(True)
        layout.addWidget(self._note)

    def _build_controls(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Sweep"))
        self._field = QComboBox()
        for name, (label, unit) in SWEEPABLE.items():
            self._field.addItem(f"{label}" + (f" ({unit})" if unit else ""), name)
        # Without this the combo demands room for its longest entry, and the
        # whole tab inherits that as a minimum width the window can never go
        # below.
        self._field.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self._field.setMinimumContentsLength(16)
        self._field.setMinimumWidth(150)
        self._field.currentIndexChanged.connect(self._reset_range)
        row.addWidget(self._field, 1)

        # Every sweepable quantity is a positive length, count, speed or torque.
        # The old +/-1e6 range was not reachable by any of them and cost 210 px
        # per box, because Qt sizes a spin box to fit "-1000000.000".
        row.addWidget(QLabel("from"))
        self._lo = self._range_box()
        row.addWidget(self._lo)
        row.addWidget(QLabel("to"))
        self._hi = self._range_box()
        row.addWidget(self._hi)
        row.addWidget(QLabel("steps"))
        self._steps = QSpinBox()
        self._steps.setRange(3, 81)
        self._steps.setValue(21)
        _size_box(self._steps, "81")
        row.addWidget(self._steps)

        self._run_btn = QPushButton("Run")
        self._run_btn.setProperty("primary", "true")
        self._run_btn.clicked.connect(self._run)
        row.addWidget(self._run_btn)
        return row

    @staticmethod
    def _range_box() -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(0.0, 100_000.0)
        box.setDecimals(3)
        # No steppers on these two.  They are typed into - a range comes from
        # the suggestion or from a number you have in mind - and nobody drives
        # 27.5 anywhere useful in thousandths.  The arrows are a third of the
        # box's width each, and this row is what sets the whole window's
        # smallest usable size, so they are the most expensive thing in it that
        # nothing was using.  The steps box keeps its own: 21 to 22 is exactly
        # the kind of nudge a stepper is for.
        box.setButtonSymbols(QDoubleSpinBox.NoButtons)
        _size_box(box, _WIDEST_BOUND)
        return box

    def refresh_theme(self) -> None:
        """Redraw after an appearance change - the sweep, or the empty state.

        The figure's colours were fixed when it was drawn, so a live theme
        switch has to rebuild it or the panel keeps the old surface.  That is
        as true of the placeholder as of a chart: it is a figure like any
        other, and a white card left in a dark window is the exact defect
        following the desktop theme was meant to prevent.
        """
        if self._result is not None:
            plots.sweep_figure(self._result, self._figure)
        else:
            plots.placeholder_figure(_EMPTY_CHART, self._figure)
        self._canvas.draw_idle()

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
