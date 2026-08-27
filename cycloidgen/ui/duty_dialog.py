"""Editing the duty cycle: a table, because a cycle is a list.

Every other parameter in this application is one number in one box, and the
panel is a flat declarative list because of it.  A duty cycle is not that shape
- it is however many rows the machine has moves - so it gets a dialog of its
own rather than a widget wedged into a column of spin boxes.

The table is the whole dialog on purpose.  What a cycle needs is somewhere to
type four numbers a few times over and see them add up, and the two things worth
computing while you type are the shares - which is what "for how long" actually
means once the rows are together - and whether the peak matches what the drive
is rated at, which is the one mistake that quietly invalidates the rest of the
datasheet.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.duty import DutyCycle, DutyPoint
from ..core.spec import GearSpec

__all__ = ["DutyDialog"]

#: What a new row starts as.  A hold, because it is the point people forget the
#: app can even represent, and starting on one says that it can.
_NEW_ROW = ("hold", 1.0, 0.0, 1.0)

_COLUMNS = ("What it does", "Output torque (Nm)", "Output speed (rpm)",
            "Lasts (s)", "Share")


class DutyDialog(QDialog):
    """Rows in, a :class:`DutyCycle` out."""

    def __init__(self, spec: GearSpec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Duty cycle")
        self._rated = spec.output_torque_Nm
        self.cycle: DutyCycle | None = None

        layout = QVBoxLayout(self)
        blurb = QLabel(
            "What the drive actually does, over time. Stress is taken from the "
            "worst point, temperature from the mean loss, bearing life from the "
            "cubic mean load, and the motor has to make the peak and survive "
            "the RMS — four answers no single rated point can give.\n\n"
            "Zero output speed is a hold: the load is there and nothing turns.")
        blurb.setWordWrap(True)
        blurb.setProperty("role", "placeholder")
        layout.addWidget(blurb)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, len(_COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self._table.itemChanged.connect(self._recount)
        layout.addWidget(self._table, 1)

        row = QHBoxLayout()
        add = QPushButton("Add a point")
        add.clicked.connect(lambda: self._append(*_NEW_ROW))
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self._remove_selected)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        layout.addLayout(row)

        self._summary = QLabel()
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        # Clearing the cycle has to be reachable, and it is not the same as
        # cancelling: one says "no cycle", the other says "leave what was
        # there".  A dialog that can only add is a dialog you cannot undo.
        clear = buttons.addButton("Clear the cycle", QDialogButtonBox.ResetRole)
        clear.clicked.connect(self._clear)
        layout.addWidget(buttons)

        self._load(spec.duty_cycle)
        self.resize(620, 420)

    # ------------------------------------------------------------------ rows
    def _load(self, cycle: DutyCycle) -> None:
        for point in cycle.points:
            self._append(point.name, point.output_torque_Nm,
                         point.output_rpm, point.seconds)
        if not cycle.points:
            # Two, because one is not a cycle - and an empty table gives
            # somebody nothing to copy the shape from.
            self._append("move", max(self._rated, 0.01), 10.0, 5.0)
            self._append(*_NEW_ROW)

    def _append(self, name: str, torque: float, rpm: float, seconds: float) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        for column, value in enumerate((name, f"{torque:g}", f"{rpm:g}",
                                        f"{seconds:g}")):
            self._table.setItem(row, column, QTableWidgetItem(value))
        share = QTableWidgetItem("")
        # Computed, so it is not typed into: a share that could be edited would
        # be a fifth number that has to agree with the other four.
        share.setFlags(share.flags() & ~Qt.ItemIsEditable)
        self._table.setItem(row, 4, share)
        self._recount()

    def _remove_selected(self) -> None:
        for index in sorted({i.row() for i in self._table.selectedIndexes()},
                            reverse=True):
            self._table.removeRow(index)
        self._recount()

    # --------------------------------------------------------------- reading
    def _row(self, row: int) -> tuple[str, float, float, float] | None:
        """One row as numbers, or ``None`` if it cannot be read as any."""
        def number(column: int) -> float | None:
            item = self._table.item(row, column)
            try:
                return float((item.text() if item else "").replace(",", "."))
            except ValueError:
                return None

        name = self._table.item(row, 0)
        torque, rpm, seconds = number(1), number(2), number(3)
        if torque is None or rpm is None or seconds is None:
            return None
        if torque <= 0 or rpm < 0 or seconds <= 0:
            return None
        return (name.text().strip() if name else "", torque, rpm, seconds)

    def _points(self) -> list[DutyPoint]:
        rows = (self._row(r) for r in range(self._table.rowCount()))
        return [DutyPoint(name=name[:40], output_torque_Nm=torque,
                          output_rpm=rpm, seconds=seconds)
                for name, torque, rpm, seconds in filter(None, rows)]

    def _recount(self) -> None:
        """Shares and the one warning worth making while the table is open."""
        points = self._points()
        total = sum(p.seconds for p in points)
        readable = 0
        for row in range(self._table.rowCount()):
            values = self._row(row)
            cell = self._table.item(row, 4)
            if cell is None:
                continue
            if values is None or total <= 0:
                cell.setText("—")
                continue
            cell.setText(f"{values[3] / total:.0%}")
            readable += 1

        if len(points) < 2:
            self._summary.setText(
                "A cycle needs at least two points. One point is the rated "
                "duty, which the design already carries.")
            return
        peak = max(p.output_torque_Nm for p in points)
        moving = sum(p.seconds for p in points if not p.is_hold) / total
        note = (f"{len(points)} points over {total:g} s, "
                f"{moving:.0%} of it turning. Peak {peak:g} Nm.")
        if peak > self._rated * 1.001:
            note += (f"  The drive is rated at {self._rated:g} Nm, so the "
                     f"datasheet is describing an easier machine than this "
                     f"cycle - rate it at {peak:g} Nm.")
        if readable < self._table.rowCount():
            note += ("  Rows that are not four readable numbers are ignored.")
        self._summary.setText(note)

    # --------------------------------------------------------------- closing
    def _accept(self) -> None:
        points = self._points()
        if len(points) < 2:
            self._summary.setText(
                "A cycle needs at least two points before it can be applied.")
            return
        self.cycle = DutyCycle(points=tuple(points))
        self.accept()

    def _clear(self) -> None:
        self.cycle = DutyCycle()
        self.accept()
