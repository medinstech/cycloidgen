"""The matplotlib navigation bar, cut down and brought into the chrome.

Two things are wrong with the stock toolbar here, and they are different kinds
of wrong.

It carries **tools that do not apply**.  *Subplots* opens a dialog of margin
sliders for a figure that lays itself out; *Customize* offers to re-scale the
axes and restyle the series of a drawing whose scale is millimetres and whose
colours are the part colours.  Both of them can only make the picture disagree
with the numbers beside it.  *Back* and *Forward* walk a view history that a
single-axes drawing barely has.  What is left - reset, pan, zoom, save - is what
anyone actually reaches for.

And it **decides its own ink**.  matplotlib picks light or dark artwork by
reading the toolbar's ``QPalette``, and under an application-wide stylesheet
that palette is not ours: every role on it resolves to black, so the toolbar
concluded "dark" and drew white icons on the light theme's paper, where they are
invisible.  Rather than fight the palette, the icons are tinted here, from the
same mode everything else is painted from.  It is matplotlib's own artwork - a
second set of hand-drawn icons would drift from the toolbar's behaviour - just
in the right colour.
"""
from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import matplotlib
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

from . import branding

__all__ = ["PlotToolbar"]

#: The tools that make sense on a drawing whose scale is fixed and whose colours
#: mean something.  Order is the stock order, minus the rest.
_KEEP = ("Home", "Pan", "Zoom", "Save")

#: Above this device pixel ratio the 24 px artwork is soft, and matplotlib ships
#: a 48 px copy of every icon beside it.
_LARGE_ABOVE = 1.5


class PlotToolbar(NavigationToolbar2QT):
    """Reset, pan, zoom and save - themed to match the window."""

    #: Read by matplotlib's own ``_init_toolbar``, so it has to stay a plain
    #: class attribute with the stock shape: (text, tooltip, image, callback).
    toolitems: ClassVar[list] = [item for item in NavigationToolbar2QT.toolitems
                                 if item[0] in _KEEP]

    def __init__(self, canvas, parent=None, *, mode: str = "light") -> None:
        super().__init__(canvas, parent)
        # The artwork behind each action, so the icons can be made again when
        # the appearance changes.  Taken from `toolitems` rather than from the
        # actions, because only `toolitems` knows the file name.
        self._icon_files = {text: f"{image}.png"
                            for text, _tip, image, _callback in self.toolitems}
        if self.coordinates:
            self.locLabel.setObjectName("PlotCoords")
            self.locLabel.setFont(branding.mono_font(8))
        self.apply_theme(mode)

    # ------------------------------------------------------------------ theme
    def apply_theme(self, mode: str) -> None:
        """Repaint for ``mode``.  Safe to call on a live toolbar."""
        ink = branding.palette(mode).ink
        for action in self.actions():
            name = self._icon_files.get(action.text())
            if name is not None:
                action.setIcon(self._tinted(name, ink))

    def _tinted(self, name: str, colour: str) -> QIcon:
        """matplotlib's artwork in ``colour``.

        Composited rather than masked.  The obvious way - build a mask of the
        black pixels, fill, reapply - is what matplotlib itself does and it
        throws away the antialiasing, because a half-covered edge pixel is grey
        and grey is not black.  ``SourceIn`` keeps the artwork's alpha and
        replaces only its colour, so the edges survive.
        """
        images = Path(matplotlib.get_data_path()) / "images"
        ratio = self.devicePixelRatioF() or 1.0
        large = images / name.replace(".png", "_large.png")
        path = large if ratio > _LARGE_ABOVE and large.exists() else images / name

        artwork = QPixmap(str(path))
        if artwork.isNull():                          # pragma: no cover
            return QIcon()
        tinted = QPixmap(artwork.size())
        tinted.fill(Qt.transparent)
        painter = QPainter(tinted)
        painter.drawPixmap(0, 0, artwork)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(tinted.rect(), QColor(colour))
        painter.end()
        tinted.setDevicePixelRatio(ratio)
        return QIcon(tinted)
