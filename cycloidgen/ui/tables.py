"""Table behaviour shared between the panels that carry one.

Both the checks list and the outputs list have a column that is a *sentence*
rather than a field, and both of them used to end every row in an ellipsis.
The fix is the same in both places, so it lives in one.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QTreeWidget

__all__ = ["WRAP_MARGIN_PX", "WrappingColumn"]

#: Padding either side of a wrapped cell, and under it.  One number for both:
#: text that touches the column edge reads as clipped even when it is not.
WRAP_MARGIN_PX = 8


class WrappingColumn(QStyledItemDelegate):
    """Give one column of a tree the height its wrapped text actually needs.

    ``QAbstractItemView.setWordWrap`` is half the job and the half that is easy
    to mistake for all of it: it makes the *painter* wrap, so the text is laid
    out correctly and then clipped to a row one line tall.  The row height comes
    from the delegate's size hint, and the default one measures a single line
    because the option it is handed during layout has no width in it yet.

    So the width is taken from the column rather than from the option.  Nothing
    else here changes: painting is still the base class's, which already wraps.
    """

    def __init__(self, view: QTreeWidget, column: int) -> None:
        super().__init__(view)
        self._view = view
        self._column = column
        # A stretched last section resizes with the window and with the
        # splitter, and a row measured against the old width is a row that
        # clips or a row with a band of empty under it.
        view.header().sectionResized.connect(
            lambda *_: view.scheduleDelayedItemsLayout())

    def sizeHint(self, option, index) -> QSize:
        hint = super().sizeHint(option, index)
        if index.column() != self._column:
            return hint
        width = self._view.columnWidth(self._column) - WRAP_MARGIN_PX
        if width <= 0:
            return hint
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        if not styled.text:
            return hint
        needed = QFontMetrics(styled.font).boundingRect(
            0, 0, width, 0, Qt.TextWordWrap, styled.text).height()
        return QSize(hint.width(), max(hint.height(), needed + WRAP_MARGIN_PX))
