"""The 3D tab: the assembled drive, turning under the same crank as the drawing.

Painted with ``QPainter`` over the draw list from :mod:`cycloidgen.viz.scene`.
No OpenGL, no Qt 3D, no scene graph.  That is a deliberate trade and worth
stating: a hardware path would render more triangles than this ever needs to,
and would also be the one part of the application that fails on a machine with
no GL driver, over a remote desktop, or in a headless test - which is precisely
where a mechanical tool gets used.  A cycloidal drive is a few thousand polygons;
software is fast enough, and it can be checked without a display.
"""
from __future__ import annotations

import math
import traceback
from contextlib import suppress

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..core.spec import GearSpec
from ..viz.mesh import PART_GROUPS, Mesh, mesh_for_spec
from ..viz.scene import Camera, render
from . import branding
from .logpanel import logger
from .settings import app_settings

__all__ = ["Assembly3DTab", "AssemblyView"]

#: Standard viewpoints, as (azimuth, elevation) in degrees.
STANDARD_VIEWS: dict[str, tuple[float, float]] = {
    "iso": (38.0, 26.0),
    "front": (-90.0, 0.0),
    "top": (-90.0, 88.0),
    "side": (0.0, 0.0),
}

_ORBIT_PER_PIXEL = 0.34
_ZOOM_PER_NOTCH = 0.86


def _polygon(points: np.ndarray) -> QPolygonF:
    return QPolygonF([QPointF(float(x), float(y)) for x, y in points])


class AssemblyView(QWidget):
    """Orbit, pan and zoom around one design at one crank angle."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(320, 260)
        self.setMouseTracking(False)
        self.setToolTip("Drag to orbit, right-drag to pan, wheel to zoom, "
                        "double-click to re-fit.")

        self._spec: GearSpec | None = None
        self._mesh: Mesh | None = None
        self._camera = Camera()
        self._span = 200.0
        self._crank = 0.0
        self._explode = 0.0
        self._hidden: set[str] = set()
        self._edges = False
        self._mode = "light"
        self._drag: tuple[float, float] | None = None
        self._drag_button = Qt.NoButton
        self._failed = ""
        self._label_font = QFont("Consolas")
        self._label_font.setStyleHint(QFont.Monospace)
        self._label_font.setPointSize(9)

    # ------------------------------------------------------------------ state
    def set_spec(self, spec: GearSpec) -> None:
        """Adopt a design, re-framing only when the drive genuinely resized.

        Re-framing a view the user has just orbited and zoomed to, because they
        nudged a clearance by 0.01 mm, is infuriating.  So the camera is left
        alone unless the assembly has changed size enough that the old framing
        would not hold it - a preset change, or a new design from the optimiser.
        """
        try:
            mesh = mesh_for_spec(spec)
        except Exception:
            self._failed = traceback.format_exc()
            logger.error("3D view could not build the assembly\n%s",
                         self._failed.rstrip())
            self._mesh = None
            self.update()
            return

        was = self._span if self._mesh is not None else 0.0
        self._failed = ""
        self._spec, self._mesh = spec, mesh
        if not 0.9 * was <= self._measure() <= 1.1 * was:
            self._refit()
        self.update()

    def set_crank(self, degrees: float) -> None:
        self._crank = float(degrees)
        self.update()

    def set_explode(self, fraction: float) -> None:
        """Pull the assembly apart, re-framing as it grows.

        Exploding is a change of what you are looking at, not of where you are
        looking from, so it takes the framing with it; the alternative is a
        slider that pushes half the gearbox off the edge of the panel.
        """
        self._explode = float(fraction)
        self._refit()
        self.update()

    def _measure(self) -> float:
        """Diagonal of the assembly's bounding box, for framing and zoom limits."""
        if self._mesh is None:
            return self._span
        lo, hi = self._mesh.bounds(self._explode)
        self._span = max(float(np.linalg.norm(hi - lo)), 1e-6)
        return self._span

    def _refit(self) -> None:
        if self._mesh is not None:
            self._camera = Camera.framing(self._mesh, explode=self._explode,
                                          azimuth=self._camera.azimuth,
                                          elevation=self._camera.elevation)

    def set_group_visible(self, group: str, visible: bool) -> None:
        self._hidden.discard(group) if visible else self._hidden.add(group)
        self.update()

    def set_edges(self, on: bool) -> None:
        self._edges = bool(on)
        self.update()

    def set_theme(self, mode: str) -> None:
        self._mode = mode
        self.update()

    def set_standard_view(self, name: str) -> None:
        azimuth, elevation = STANDARD_VIEWS[name]
        self._camera = Camera(target=self._camera.target, azimuth=azimuth,
                              elevation=elevation, distance=self._camera.distance,
                              fov_deg=self._camera.fov_deg)
        self.update()

    def fit(self) -> None:
        self._measure()
        self._refit()
        self.update()

    @property
    def camera(self) -> Camera:
        return self._camera

    def set_camera_angles(self, azimuth: float, elevation: float) -> None:
        """Restore a stored orientation.  Distance stays with the geometry."""
        self._camera = Camera(target=self._camera.target, azimuth=azimuth,
                              elevation=elevation, distance=self._camera.distance,
                              fov_deg=self._camera.fov_deg)
        self.update()

    # --------------------------------------------------------------- painting
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        p = branding.palette(self._mode)
        painter.fillRect(self.rect(), QColor(p.raised))

        if self._mesh is None:
            painter.setPen(QColor(p.ink_dim))
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "No assembly to show."
                             + ("\nSee the log tab." if self._failed else ""))
            return

        width, height = max(self.width(), 1), max(self.height(), 1)
        draw = render(self._mesh, math.radians(self._crank), self._camera,
                      width, height, explode=self._explode, hidden=self._hidden)

        # One pen and one brush per face.  The pen matters: filling a polygon
        # without outlining it leaves an antialiased hairline of background
        # between it and its neighbour, and a solid part ends up looking like a
        # wireframe of its own seams.
        for loops, rgb in zip(draw.loops, draw.colours, strict=True):
            fill = QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]))
            painter.setBrush(fill)
            painter.setPen(fill.darker(150) if self._edges else fill)
            if len(loops) == 1:
                painter.drawPolygon(_polygon(loops[0]))
                continue
            path = QPainterPath()
            path.setFillRule(Qt.OddEvenFill)
            for loop in loops:
                path.addPolygon(_polygon(loop))
                path.closeSubpath()
            painter.drawPath(path)

        self._paint_overlay(painter, p)

    def _paint_overlay(self, painter: QPainter, p) -> None:
        """Readouts and an axis triad, drawn over the model."""
        painter.setFont(self._label_font)
        painter.setPen(QColor(p.ink))
        if self._spec is not None:
            out = self._crank / self._spec.ratio
            painter.drawText(12, 20, f"INPUT {self._crank:6.1f} deg")
            painter.drawText(12, 36, f"OUTPUT{out:7.2f} deg   {self._spec.ratio}:1")

        right, up, _ = self._camera.basis()
        ox, oy, length = 30.0, self.height() - 30.0, 24.0
        for axis, name in zip(np.eye(3), "XYZ", strict=True):
            dx, dy = float(axis @ right) * length, -float(axis @ up) * length
            painter.setPen(QColor(p.ink_dim))
            painter.drawLine(QPointF(ox, oy), QPointF(ox + dx, oy + dy))
            painter.setPen(QColor(p.ink))
            painter.drawText(QPointF(ox + 1.35 * dx - 3, oy + 1.35 * dy + 4), name)

        painter.setPen(QColor(p.ink_dim))
        painter.drawText(self.rect().adjusted(0, 0, -10, -8),
                         Qt.AlignRight | Qt.AlignBottom,
                         "drag orbit  -  right-drag pan  -  wheel zoom")

    # ------------------------------------------------------------ interaction
    def mousePressEvent(self, event) -> None:
        pos = event.position()
        self._drag = (pos.x(), pos.y())
        self._drag_button = event.button()

    def mouseMoveEvent(self, event) -> None:
        if self._drag is None:
            return
        pos = event.position()
        dx, dy = pos.x() - self._drag[0], pos.y() - self._drag[1]
        self._drag = (pos.x(), pos.y())
        if self._drag_button == Qt.LeftButton:
            # Dragging right turns the model right, which means the *camera*
            # goes the other way: increasing azimuth walks the eye anticlockwise
            # and the model appears to slide left.
            self._camera = self._camera.orbited(-dx * _ORBIT_PER_PIXEL,
                                                dy * _ORBIT_PER_PIXEL)
        else:
            self._camera = self._camera.panned(dx, dy, self.height())
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._drag = None
        self._drag_button = Qt.NoButton

    def mouseDoubleClickEvent(self, event) -> None:
        self.fit()

    def wheelEvent(self, event) -> None:
        notches = event.angleDelta().y() / 120.0
        self._camera = self._camera.zoomed(_ZOOM_PER_NOTCH ** notches,
                                           span=self._span)
        self.update()


class Assembly3DTab(QWidget):
    """The viewer plus the controls a gearbox actually needs.

    Hiding the housing and pulling the stack apart are the two things anyone
    does first with a 3D assembly, so they are one click and one drag rather
    than a menu.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.view = AssemblyView()

        view_row = QHBoxLayout()
        view_row.addWidget(QLabel("VIEW"))
        for key, text in (("iso", "ISO"), ("front", "FRONT"),
                          ("top", "TOP"), ("side", "SIDE")):
            button = QPushButton(text)
            button.setMaximumWidth(74)
            button.clicked.connect(lambda _c=False, k=key:
                                   self.view.set_standard_view(k))
            view_row.addWidget(button)
        fit = QPushButton("FIT")
        fit.setMaximumWidth(74)
        fit.clicked.connect(self.view.fit)
        view_row.addWidget(fit)

        view_row.addSpacing(12)
        view_row.addWidget(QLabel("EXPLODE"))
        self._explode = QSlider(Qt.Horizontal)
        self._explode.setRange(0, 100)
        self._explode.setToolTip("Slide the parts apart along the axis, in "
                                 "assembly order.")
        self._explode.valueChanged.connect(
            lambda v: self.view.set_explode(v / 100.0))
        view_row.addWidget(self._explode, 1)

        self._edges = QCheckBox("Edges")
        self._edges.setToolTip("Outline every facet. Useful for reading the "
                               "shape, noisy on a fine profile.")
        self._edges.toggled.connect(self.view.set_edges)
        view_row.addWidget(self._edges)
        layout.addLayout(view_row)

        show_row = QHBoxLayout()
        show_row.addWidget(QLabel("SHOW"))
        self._groups: dict[str, QCheckBox] = {}
        for group, label in PART_GROUPS:
            box = QCheckBox(label)
            box.setChecked(True)
            box.toggled.connect(
                lambda on, g=group: self.view.set_group_visible(g, on))
            show_row.addWidget(box)
            self._groups[group] = box
        show_row.addStretch(1)
        layout.addLayout(show_row)

        layout.addWidget(self.view, 1)

    # ------------------------------------------------------------------ state
    def set_spec(self, spec: GearSpec) -> None:
        self.view.set_spec(spec)

    def set_crank(self, degrees: float) -> None:
        self.view.set_crank(degrees)

    def refresh_theme(self, mode: str) -> None:
        self.view.set_theme(mode)

    def save_state(self) -> None:
        settings = app_settings()
        camera = self.view.camera
        settings.setValue("view3d_azimuth", camera.azimuth)
        settings.setValue("view3d_elevation", camera.elevation)
        settings.setValue("view3d_explode", self._explode.value())
        settings.setValue("view3d_edges", self._edges.isChecked())
        settings.setValue("view3d_hidden",
                          [g for g, box in self._groups.items()
                           if not box.isChecked()])

    def restore_state(self) -> None:
        """Reopen on the viewpoint the last session left.

        Every value is restored on its own and defensively: a stored setting
        from an older build should cost a default, not a tab that will not
        build.
        """
        settings = app_settings()
        try:
            azimuth = float(settings.value("view3d_azimuth", 38.0))
            elevation = float(settings.value("view3d_elevation", 26.0))
        except (TypeError, ValueError):
            azimuth, elevation = STANDARD_VIEWS["iso"]
        self.view.set_camera_angles(azimuth, elevation)

        with suppress(TypeError, ValueError):
            self._explode.setValue(int(settings.value("view3d_explode", 0)))
        self._edges.setChecked(bool(settings.value("view3d_edges", False, type=bool)))

        hidden = settings.value("view3d_hidden") or []
        if isinstance(hidden, str):
            hidden = [hidden]
        for group, box in self._groups.items():
            box.setChecked(group not in hidden)
