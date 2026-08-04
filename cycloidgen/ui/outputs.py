"""The Outputs tab: what an export writes, where, and what each file is for.

The application used to answer "what do I get?" with two buttons and a message
box counting files afterwards.  That is enough to run an export and not enough
to decide whether you want one.  This lists every deliverable *before* anything
is written - straight off :mod:`cycloidgen.export.manifest`, so it lists what
the writer actually produces rather than what a docstring once said it did -
and fills in the sizes afterwards.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.spec import GearSpec
from ..export.manifest import GROUPS, outputs_for
from .settings import app_settings

__all__ = ["OutputsTab"]


def _kb(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.0f} kB"
    return f"{size} B"


class OutputsTab(QWidget):
    """Preview a bundle, choose what goes in it, and export."""

    #: ``(target folder, set of group keys)`` - the window owns the worker.
    export_requested = Signal(object, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._spec: GearSpec | None = None
        self._settings = app_settings()
        self._destination = self._settings.value("export_directory", "") or ""
        self._blocked: list[str] = []
        # Set before any widget exists: building the group toggles restores
        # their stored state, and a stored `False` fires `toggled` on the way
        # past, which lands in `_refresh` before the rest of __init__ has run.
        self._written: dict[str, int] = {}
        self._last_folder: Path | None = None
        self._summary = 0
        self._mono = QFont("Consolas")
        self._mono.setStyleHint(QFont.Monospace)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.addLayout(self._build_destination_row())
        layout.addLayout(self._build_group_row())

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["FILE", "FORMAT", "SIZE", "WHAT IT IS"])
        for column, width in ((0, 250), (1, 76), (2, 82)):
            self.tree.setColumnWidth(column, width)
        self.tree.headerItem().setTextAlignment(2, Qt.AlignRight)
        self.tree.header().setStretchLastSection(True)
        self.tree.itemDoubleClicked.connect(self._open_item)
        layout.addWidget(self.tree, 1)

        row = QHBoxLayout()
        self._export_btn = QPushButton("EXPORT SELECTED")
        self._export_btn.setProperty("primary", "true")
        self._export_btn.clicked.connect(self._export)
        row.addWidget(self._export_btn)
        self._open_btn = QPushButton("OPEN FOLDER")
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._open_folder)
        row.addWidget(self._open_btn)
        self._status = QLabel()
        self._status.setWordWrap(True)
        row.addWidget(self._status, 1)
        layout.addLayout(row)

    # ------------------------------------------------------------------ build
    def _build_destination_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("WRITES TO"))
        self._path_label = QLabel()
        self._path_label.setFont(self._mono)
        self._path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(self._path_label, 1)
        choose = QPushButton("CHOOSE FOLDER...")
        choose.clicked.connect(self._choose_folder)
        row.addWidget(choose)
        return row

    def _build_group_row(self) -> QHBoxLayout:
        """One toggle per group, each carrying the file count it contributes.

        The counts are the point.  "Solids" is thirteen files and most of the
        wait on a big design; "Drawings" is six and near-instant.  Naming the
        cost next to the choice is what makes the choice an informed one.
        """
        row = QHBoxLayout()
        row.addWidget(QLabel("INCLUDE"))
        self._group_boxes: dict[str, QCheckBox] = {}
        for group in GROUPS:
            box = QCheckBox(group.title)
            box.setToolTip(group.note)
            box.setChecked(bool(self._settings.value(f"export_group_{group.key}",
                                                     True, type=bool)))
            box.toggled.connect(lambda on, k=group.key: self._toggle_group(k, on))
            row.addWidget(box)
            self._group_boxes[group.key] = box
        row.addStretch(1)
        return row

    # ------------------------------------------------------------------ state
    def set_spec(self, spec: GearSpec) -> None:
        self._spec = spec
        self._refresh()

    def set_blocked(self, codes: list[str]) -> None:
        """Errors in the checks list stop an export; say which ones."""
        self._blocked = list(codes)
        self._update_export_button()

    def selected_groups(self) -> set[str]:
        return {key for key, box in self._group_boxes.items() if box.isChecked()}

    @property
    def destination(self) -> str:
        """The folder bundles are written into, or ``""`` if none is chosen yet."""
        return self._destination

    def target(self) -> Path | None:
        if not self._destination or self._spec is None:
            return None
        return Path(self._destination) / f"cycloidal_{self._spec.ratio}to1"

    def _toggle_group(self, key: str, on: bool) -> None:
        self._settings.setValue(f"export_group_{key}", on)
        self._refresh()

    def _refresh(self) -> None:
        spec = self._spec
        target = self.target()
        self._path_label.setText(str(target) if target else
                                 "(no folder chosen - press Choose folder)")
        self.tree.clear()
        if spec is None:
            return

        chosen = self.selected_groups()
        total = 0
        for group in GROUPS:
            outputs = outputs_for({group.key})
            included = group.key in chosen
            count = sum(len(o.files(spec)) for o in outputs) if included else 0
            total += count
            parent = QTreeWidgetItem([
                group.title, "", f"{count} files" if included else "not included",
                group.note])
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            parent.setDisabled(not included)
            self.tree.addTopLevelItem(parent)

            for out in outputs:
                names = out.files(spec)
                head = QTreeWidgetItem([
                    out.where, out.fmt,
                    self._size_text(names) if included else "",
                    f"{out.title} - {out.description}"])
                head.setFont(0, self._mono)
                head.setToolTip(3, out.description)
                head.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
                if not out.is_folder:
                    head.setData(0, Qt.UserRole, names[0])
                parent.addChild(head)
                if out.is_folder:
                    for name in names:
                        leaf = QTreeWidgetItem([
                            "    " + name.split("/", 1)[1], "",
                            self._size_text([name]) if included else "", ""])
                        leaf.setFont(0, self._mono)
                        leaf.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
                        leaf.setData(0, Qt.UserRole, name)
                        head.addChild(leaf)
            parent.setExpanded(included)

        self._summary = total
        self._update_export_button()

    def _size_text(self, names: list[str]) -> str:
        sizes = [self._written[n] for n in names if n in self._written]
        return _kb(sum(sizes)) if sizes else ""

    def _update_export_button(self) -> None:
        spec, groups = self._spec, self.selected_groups()
        ready = spec is not None and bool(groups) and not self._blocked
        self._export_btn.setEnabled(ready)
        if self._blocked:
            self._status.setText("Export blocked by " + ", ".join(self._blocked)
                                 + " - fix those checks first.")
        elif not groups:
            self._status.setText("Nothing selected.")
        elif spec is not None and not self._written:
            self._status.setText(f"{self._summary} files. Double-click a row "
                                 f"after an export to open it.")

    # --------------------------------------------------------------- actions
    def _choose_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Export into folder", self._destination or "")
        if directory:
            self.set_destination(directory)

    def set_destination(self, directory: str) -> None:
        self._destination = directory
        self._settings.setValue("export_directory", directory)
        self._written.clear()
        self._refresh()

    def _export(self) -> None:
        if self.target() is None:
            self._choose_folder()
        target = self.target()
        if target is not None:
            self.export_requested.emit(target, self.selected_groups())

    def show_written(self, folder: Path, files: list[Path]) -> None:
        """Fill in the sizes after an export, and let the rows be opened."""
        self._last_folder = folder
        self._written = {}
        total = 0
        for path in files:
            try:
                size = path.stat().st_size
                self._written[path.relative_to(folder).as_posix()] = size
                total += size
            except (OSError, ValueError):
                continue
        self._refresh()
        self._open_btn.setEnabled(True)
        self._status.setText(f"Wrote {len(files)} files ({_kb(total)}) to {folder}.")

    def _open_folder(self) -> None:
        if self._last_folder is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_folder)))

    def _open_item(self, item: QTreeWidgetItem, _column: int) -> None:
        name = item.data(0, Qt.UserRole)
        if name is None or self._last_folder is None:
            return
        path = self._last_folder / name
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
