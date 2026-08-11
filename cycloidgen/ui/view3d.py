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
from PySide6.QtCore import QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.spec import GearSpec
from ..viz.mesh import EDGE_SHADE, PART_GROUPS, Mesh, mesh_for_spec
from ..viz.scene import Camera, render
from . import branding
from .logpanel import logger
from .settings import app_settings

__all__ = ["Assembly3DTab", "AssemblyView", "FlowLayout"]


class FlowLayout(QLayout):
    """A row that wraps instead of squeezing.

    ``QHBoxLayout`` given less width than its children asked for takes it from
    them anyway, and a ``QCheckBox`` that has been squeezed elides its own text:
    *Housing* becomes *Housin*, *Carrier* becomes *Carrie*. On a wide window the
    row fits and nothing shows; on a narrower one - a laptop, a Mac's default
    window, a user who has dragged the splitter - every label in the visibility
    row loses its last letters at once, which reads as a rendering fault rather
    than as a layout that ran out of room.

    Wrapping is the honest answer for a row of independent toggles: they have no
    order that matters and no alignment to keep, so a second line costs nothing
    but height, and height is what this tab has spare.
    """

    def __init__(self, parent=None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list = []
        self.setSpacing(spacing)

    # ------------------------------------------------------- QLayout plumbing
    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._lay_out(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect) -> None:
        super().setGeometry(rect)
        self._lay_out(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(),
                            margins.top() + margins.bottom())

    def _lay_out(self, rect, *, apply: bool) -> int:
        """Place the items left to right, wrapping; return the height used.

        Two passes, because the items are centred in their row and a row's
        height is not known until it has ended.  Placing everything at the
        row's top - which is what one pass can do - lines the widgets up by
        their boxes rather than by what is drawn in them, and a control a few
        pixels taller than the checkboxes beside it then paints its own
        contents low: the bearings menu hung below the row like dropped
        punctuation, which is exactly what it was mistaken for.
        """
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(),
                             -margins.right(), -margins.bottom())
        space = self.spacing()

        rows: list[tuple[int, list]] = []
        x, line, line_height = area.x(), [], 0
        for item in self._items:
            hint = item.sizeHint()
            if line and x + hint.width() > area.right():
                rows.append((line_height, line))
                x, line, line_height = area.x(), [], 0
            line.append((item, x, hint))
            x += hint.width() + space
            line_height = max(line_height, hint.height())
        if line:
            rows.append((line_height, line))
        if not rows:
            return margins.top() + margins.bottom()

        y = area.y()
        for height, items in rows:
            if apply:
                for item, item_x, hint in items:
                    top = y + (height - hint.height()) // 2
                    item.setGeometry(QRect(QPoint(item_x, top), hint))
            y += height + space
        return y - space - rect.y() + margins.bottom()


#: Standard viewpoints, as (azimuth, elevation) in degrees.
STANDARD_VIEWS: dict[str, tuple[float, float]] = {
    "iso": (38.0, 26.0),
    "front": (-90.0, 0.0),
    "top": (-90.0, 88.0),
    "side": (0.0, 0.0),
}

_ORBIT_PER_PIXEL = 0.34
_ZOOM_PER_NOTCH = 0.86

#: Groups this tab opens with switched off, on a machine that has never run it.
#:
#: Only the end plates.  With them on, the assembled view is a closed cylinder
#: with a shaft out of one end - which is exactly what the gearbox looks like and
#: exactly no use as the first thing a design tool shows you.  They are one click
#: away and the checkbox is visibly unticked, so nothing is being hidden from
#: anyone; the default just starts where the work is.
#: The tab opens on an open gearbox: with the plates on, the assembled view is
#: a closed cylinder with a shaft out of one end, which is what the gearbox
#: looks like and exactly no use as the first thing a design tool shows you.
#: The bolts go with them - six fasteners floating where the plates they hold
#: on are not is a stranger picture than either.
_HIDDEN_BY_DEFAULT: frozenset[str] = frozenset({"end_plates", "fasteners"})


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
        self._label_font = branding.mono_font(9)

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
        """Show or hide a part group, or one named part."""
        self._hidden.discard(group) if visible else self._hidden.add(group)
        self.update()

    def hideable_parts(self, group: str) -> list[tuple[str, str]]:
        """(name, label) of the parts in ``group``, for a per-part menu."""
        if self._mesh is None:
            return []
        return [(p.name, p.label) for p in self._mesh.parts if p.group == group]

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
            # The same rule the hardware path uses - `EDGE_SHADE` is shared
            # so the two renderers cannot drift about what an edge looks
            # like, which is how one of them ended up drawing them in the
            # theme's ink and the other in the part's.
            painter.setPen(QColor(*[int(c * EDGE_SHADE) for c in rgb])
                           if self._edges else fill)
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
            # Modulo a turn: playback runs the crank unwrapped over the
            # mechanism's period, which is `lobes` input revolutions.
            crank = self._crank % 360.0
            out = (self._crank / self._spec.ratio) % 360.0
            painter.drawText(12, 20, f"INPUT {crank:6.1f} deg")
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


def build_view(parent: QWidget | None = None) -> QWidget:
    """The best 3D view this machine can give us.

    VTK when it is there and its render window can actually be created, which
    is the normal case because CadQuery installs it.  The software painter
    otherwise: a build with the CAD kernel stripped out, a machine with no
    OpenGL, a remote session that does not forward it.  Falling back is worth
    more than failing - a flat-shaded gearbox is still a gearbox, and the
    alternative is a tab that shows an error.
    """
    try:
        from . import view3d_vtk
        if view3d_vtk.available():
            view = view3d_vtk.VtkAssemblyView(parent)
            logger.info("3D: hardware renderer (VTK)")
            return view
        logger.info("3D: VTK unavailable, using the software renderer")
    except Exception:
        logger.warning("3D: VTK failed to start, using the software renderer\n%s",
                       traceback.format_exc().rstrip())
    return AssemblyView(parent)


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

        self.view = build_view()

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

        # The two sliders travel together.  They are one kind of control - drag
        # to open the assembly up - and they were split across the two rows,
        # explode alone at the top and section squeezed onto the end of the
        # checkboxes at 150 px, where the row had already run out of width and
        # wrapped.  Same row, same stretch, so they read as the pair they are.
        view_row.addSpacing(12)
        view_row.addWidget(QLabel("EXPLODE"))
        self._explode = QSlider(Qt.Horizontal)
        self._explode.setRange(0, 100)
        self._explode.setToolTip("Slide the parts apart along the axis, in "
                                 "assembly order.")
        self._explode.valueChanged.connect(
            lambda v: self.view.set_explode(v / 100.0))
        view_row.addWidget(self._explode, 1)

        self._section = QSlider(Qt.Horizontal)
        self._section.setRange(0, 100)
        self._section.setToolTip("Cut the assembly on a plane through the axis, "
                                 "to see the mesh instead of the outside of it.")
        # Only the hardware view can cut: a clipping plane is a per-fragment
        # test, and the software painter works on whole faces.
        if hasattr(self.view, "set_section"):
            view_row.addSpacing(12)
            view_row.addWidget(QLabel("SECTION"))
            self._section.valueChanged.connect(
                lambda v: self.view.set_section(v / 100.0))
            view_row.addWidget(self._section, 1)

        view_row.addSpacing(12)
        self._edges = QCheckBox("Edges")
        self._edges.setToolTip("Outline every facet. Useful for reading the "
                               "shape, noisy on a fine profile.")
        self._edges.toggled.connect(self.view.set_edges)
        view_row.addWidget(self._edges)
        layout.addLayout(view_row)

        # Visibility, and nothing else.  What this row is for is now answerable
        # from the row itself.
        show_row = FlowLayout()
        show_row.addWidget(QLabel("SHOW"))
        # The bearings are the one group where all-or-nothing is not enough.  The
        # cam bearing is down a bore and the shaft supports are out in the open,
        # so seeing one of them usually means putting the others away - and which
        # ones a design even has changes with the design, which is why this is a
        # menu rebuilt per spec rather than a row of boxes built once.
        self._hidden_parts: set[str] = set()
        self._bearing_menu = QToolButton()
        self._bearing_menu.setText("...")
        self._bearing_menu.setPopupMode(QToolButton.InstantPopup)
        # Wide enough to read as a button.  At its natural size an ellipsis and
        # a menu arrow next to a row of checkboxes look like stray punctuation.
        self._bearing_menu.setMinimumWidth(30)
        self._bearing_menu.setToolTip("Show or hide bearings one at a time.")
        self._bearing_menu.setMenu(QMenu(self._bearing_menu))
        self._bearing_menu.setEnabled(False)

        self._groups: dict[str, QCheckBox] = {}
        for group, label in PART_GROUPS:
            box = QCheckBox(label)
            box.setChecked(group not in _HIDDEN_BY_DEFAULT)
            box.toggled.connect(
                lambda on, g=group: self.view.set_group_visible(g, on))
            self.view.set_group_visible(group, box.isChecked())
            show_row.addWidget(box)
            self._groups[group] = box
            if group == "bearings":
                show_row.addWidget(self._bearing_menu)

        layout.addLayout(show_row)

        layout.addWidget(self.view, 1)

    # ------------------------------------------------------------------ state
    def set_spec(self, spec: GearSpec) -> None:
        self.view.set_spec(spec)
        self._rebuild_bearing_menu()

    def _rebuild_bearing_menu(self) -> None:
        """One entry per bearing this design actually has.

        A bearing already hidden stays hidden across a design change: the names
        are stable, so switching preset and back does not quietly put a part you
        put away back on the screen.  A name that no longer exists costs nothing
        - the renderer is being told to hide something that is not there.
        """
        menu = self._bearing_menu.menu()
        menu.clear()
        parts = self.view.hideable_parts("bearings")
        self._bearing_menu.setEnabled(bool(parts))
        for name, label in parts:
            action = menu.addAction(label)
            action.setCheckable(True)
            # Checked before it is connected: setting it after would fire
            # `toggled` and hide whatever the last design had hidden.
            action.setChecked(name not in self._hidden_parts)
            action.toggled.connect(
                lambda on, n=name: self._set_part_visible(n, on))
            self.view.set_group_visible(name, name not in self._hidden_parts)

    def _set_part_visible(self, name: str, visible: bool) -> None:
        self._hidden_parts.discard(name) if visible else self._hidden_parts.add(name)
        self.view.set_group_visible(name, visible)

    def set_crank(self, degrees: float) -> None:
        self.view.set_crank(degrees)

    def refresh_theme(self, mode: str) -> None:
        self.view.set_theme(mode)

    def render_options(self) -> dict:
        """What an exported animation needs to look like this tab does.

        Orientation, explode and which groups are hidden - not the section
        plane or the edge outlines, which are the hardware renderer's own and
        have no equivalent in the polygon list a frame is built from.
        """
        camera = self.view.camera
        return {"azimuth": camera.azimuth, "elevation": camera.elevation,
                "explode": self._explode.value() / 100.0,
                "hidden": frozenset(self._hidden())}

    def _hidden(self) -> list[str]:
        """Everything currently switched off, groups and single parts alike.

        One list, because the renderer takes one set: a name that is both a group
        and a part is a group of exactly one part named after it, so it says the
        same thing read either way.
        """
        return [g for g, box in self._groups.items()
                if not box.isChecked()] + sorted(self._hidden_parts)

    def save_state(self) -> None:
        settings = app_settings()
        camera = self.view.camera
        settings.setValue("view3d_azimuth", camera.azimuth)
        settings.setValue("view3d_elevation", camera.elevation)
        settings.setValue("view3d_explode", self._explode.value())
        settings.setValue("view3d_edges", self._edges.isChecked())
        settings.setValue("view3d_section", self._section.value())
        settings.setValue("view3d_hidden", self._hidden())

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
        with suppress(TypeError, ValueError):
            self._section.setValue(int(settings.value("view3d_section", 0)))
        self._edges.setChecked(bool(settings.value("view3d_edges", False, type=bool)))

        # `contains` rather than a falsy check: a stored *empty* list means the
        # last session had everything on, and treating that as "no preference"
        # would put the end plates back every time you took them off.
        if settings.contains("view3d_hidden"):
            hidden = settings.value("view3d_hidden") or []
        else:
            hidden = list(_HIDDEN_BY_DEFAULT)
        if isinstance(hidden, str):
            hidden = [hidden]
        for group, box in self._groups.items():
            box.setChecked(group not in hidden)
        # Whatever is left is a part name.  Kept without checking it against the
        # current design: the tab is restored before a spec ever arrives, so
        # there is nothing yet to check it against.
        self._hidden_parts = {h for h in hidden if h not in self._groups}
        self._rebuild_bearing_menu()
