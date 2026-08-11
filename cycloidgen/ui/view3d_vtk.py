"""The 3D view on VTK: a real renderer, on hardware.

The software painter in :mod:`cycloidgen.ui.view3d` is honest and portable and
it is not enough to look at a gearbox with.  A painter's-algorithm renderer has
no depth buffer, so it sorts whole faces and gets the arbitration wrong wherever
two of them interleave; it flat-shades, so every cylinder is visibly a prism;
and it has no ambient occlusion, so nothing sits in anything.

This does the same job on the GPU, through the VTK that CadQuery already
installs.  It keeps the software one as a fallback rather than replacing it: a
machine with no OpenGL still gets a picture, and the PDF still gets a vector
drawing rather than a screenshot.

Geometry is uploaded once per design.  Turning the crank sets one 4x4 per part,
which is why this runs at the display's refresh rate instead of the timer's.
"""
from __future__ import annotations

import os
import sys
import traceback

import numpy as np
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget
from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy

from ..core.spec import GearSpec
from ..viz.mesh import EDGE_SHADE, Mesh, mesh_for_spec
from ..viz.scene import Camera
from . import branding
from .logpanel import logger
from .view3d import STANDARD_VIEWS

__all__ = ["VtkAssemblyView", "available"]


#: Qt platforms with no native window to give VTK.  This has to be checked
#: rather than discovered: ``QVTKRenderWindowInteractor`` asks the widget for a
#: window handle and hands it straight to OpenGL, so on the offscreen platform
#: it does not raise, it takes the process down with an access violation - and
#: an access violation is not something a `try` can catch.  The test suite runs
#: offscreen, which is how this was found.
_HEADLESS_PLATFORMS = frozenset({"offscreen", "minimal", "minimalegl", "vnc"})

#: Force the decision either way: ``1`` to try VTK where it is refused, ``0`` to
#: refuse it where it would be tried.  Both directions are worth having - the
#: first is how the macOS path gets developed, the second is the first thing to
#: ask someone whose 3D tab misbehaves.
_OVERRIDE = "CYCLOIDGEN_VTK"

#: Force the *backend* either way, independently of whether VTK runs at all.
#: ``1`` renders into Qt's own GL context, which is the only thing that can work
#: on macOS and the only way to exercise that path from a machine where the
#: older one already does.
_QT_GL_OVERRIDE = "CYCLOIDGEN_VTK_QTGL"


def available() -> bool:
    """Whether a VTK view can be built on this display.

    Everything here has to be decided *before* a render window is constructed,
    because the failures this is guarding against are not exceptions.  VTK asks
    the widget for a native handle and hands it straight to OpenGL; when that is
    the wrong kind of handle the process goes down, and a process going down is
    not something the ``try`` in :func:`~cycloidgen.ui.view3d.build_view` can
    catch.  So the fallback never gets its turn, and what the user sees is not a
    flat-shaded gearbox but a dead application.

    Three answers, in order:

    * **No native window at all** - the offscreen and minimal platforms. This is
      how the crash was found, because the test suite runs there.
    * **macOS**, on the *classic* backend. VTK's Python widget builds its GL
      context directly on the view ``winId()`` returns, with ``WA_PaintOnScreen``
      set - an attribute Qt documents as X11-only. macOS views have been
      layer-backed, and mandatorily so, since 10.14. What happens is not a blank
      viewport: the first render blocks the main thread the moment the tab is
      opened, and the application dies with it.

      So macOS gets :mod:`cycloidgen.ui.view3d_qtgl` instead - a viewport that
      renders *inside* Qt's context rather than building one beside it, so there
      is no native handle to get wrong. That is chosen for it in
      :func:`qt_context_wanted` rather than refused here.
    * **Whether the modules are importable**, which is an ordinary question.

    Whether the *driver* can then give a GL context is the one thing left to
    discover by trying, and that failure is an ordinary exception. Setting
    ``CYCLOIDGEN_VTK=0`` puts any machine back on the software painter, which is
    still the first thing to ask someone whose 3D tab misbehaves.
    """
    from PySide6.QtGui import QGuiApplication

    override = os.environ.get(_OVERRIDE, "").strip()
    if override in {"0", "1"}:
        return override == "1" and _importable()

    app = QGuiApplication.instance()
    platform = (app.platformName() if app is not None
                else os.environ.get("QT_QPA_PLATFORM", ""))
    if platform.lower() in _HEADLESS_PLATFORMS:
        return False
    return _importable()


def _importable() -> bool:
    try:
        _imports()
    except Exception:
        return False
    return True


def _imports():
    """Import VTK's Qt widget against *our* binding.

    ``vtkmodules.qt`` sniffs for whichever Qt binding it can find and remembers
    the first one.  On a machine that also has PyQt5 installed that is the
    wrong answer, and the failure is a crash inside the widget rather than an
    import error, so the choice is made here instead.
    """
    import vtkmodules.qt
    vtkmodules.qt.PyQtImpl = "PySide6"

    # These two are imported for their side effect: importing them is what
    # registers the OpenGL backend and the interactor styles with VTK's object
    # factory.  Without them the render window has no implementation and the
    # failure is a null pointer rather than an ImportError.
    import vtkmodules.vtkInteractionStyle
    import vtkmodules.vtkRenderingOpenGL2
    from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
    from vtkmodules.vtkCommonTransforms import vtkTransform
    from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
    from vtkmodules.vtkInteractionWidgets import vtkOrientationMarkerWidget
    from vtkmodules.vtkRenderingAnnotation import vtkAxesActor
    from vtkmodules.vtkRenderingCore import (
        vtkActor,
        vtkLightKit,
        vtkPolyDataMapper,
        vtkRenderer,
    )
    assert vtkmodules.vtkInteractionStyle and vtkmodules.vtkRenderingOpenGL2
    return {
        "QVTKRenderWindowInteractor": QVTKRenderWindowInteractor,
        "vtkActor": vtkActor,
        "vtkAxesActor": vtkAxesActor,
        "vtkInteractorStyleTrackballCamera": vtkInteractorStyleTrackballCamera,
        "vtkLightKit": vtkLightKit,
        "vtkOrientationMarkerWidget": vtkOrientationMarkerWidget,
        "vtkPolyDataMapper": vtkPolyDataMapper,
        "vtkRenderer": vtkRenderer,
        "vtkTransform": vtkTransform,
    }


def qt_context_wanted() -> bool:
    """Whether to render inside Qt's GL context instead of beside it.

    **On for macOS, off elsewhere.**  It has now been opened on a Mac and it
    draws, which is the run this backend was waiting for and could not be given
    from a Windows machine.  Everywhere else the classic widget already works
    and is the one with the miles on it, so there is no reason to move.

    ``CYCLOIDGEN_VTK_QTGL`` forces it either way - ``1`` to exercise this path
    from a machine where the older one works, ``0`` to fall back on a Mac if it
    turns out to have a fault the software painter does not.  See
    :mod:`cycloidgen.ui.view3d_qtgl`.
    """
    override = os.environ.get(_QT_GL_OVERRIDE, "").strip()
    if override in {"0", "1"}:
        return override == "1"
    return sys.platform == "darwin"


def _render_widget(v: dict, parent):
    """The viewport, on whichever of the two backends this machine wants."""
    if qt_context_wanted():
        from .view3d_qtgl import QtGLRenderWidget
        logger.info("3D: rendering into Qt's own GL context")
        return QtGLRenderWidget(parent)
    return v["QVTKRenderWindowInteractor"](parent)


class VtkAssemblyView(QWidget):
    """Same interface as the software view, so the tab can hold either."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(320, 260)

        v = _imports()
        self._vtk = v

        from vtkmodules.vtkCommonDataModel import vtkPlane

        self._spec: GearSpec | None = None
        self._mesh: Mesh | None = None
        self._actors: dict[str, dict] = {}
        self._world_plane = vtkPlane()
        self._crank = 0.0
        self._explode = 0.0
        self._hidden: set[str] = set()
        self._edges = False
        self._section = 0.0
        self._mode = "light"

        self._widget = _render_widget(v, self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._widget)

        self._renderer = v["vtkRenderer"]()
        window = self._widget.GetRenderWindow()
        window.AddRenderer(self._renderer)
        # Multisampling is the cheap, universally supported anti-aliasing;
        # FXAA is the fallback for drivers that quietly give zero samples.
        #
        # Not on the Qt-context backend: there VTK renders into its own
        # framebuffer and blits into the one Qt bound, and a multisampled source
        # cannot be blitted into a single-sampled destination - the frame is
        # dropped and the viewport comes out empty rather than aliased.  Qt is
        # already asked for a multisampled surface in `app.prepare_opengl`, so
        # the samples are not lost, they are just the ones Qt owns.
        if not qt_context_wanted():
            window.SetMultiSamples(8)
            self._renderer.UseFXAAOn()

        # A three-point kit rather than the single head-on light VTK starts
        # with: a flat frontal light on a machined part removes exactly the
        # shading that tells you it is round.
        kit = v["vtkLightKit"]()
        kit.SetKeyLightIntensity(0.9)
        kit.SetKeyToFillRatio(2.6)
        kit.SetKeyToHeadRatio(3.2)
        kit.SetKeyToBackRatio(3.0)
        kit.SetKeyLightWarmth(0.58)
        kit.SetFillLightWarmth(0.42)
        kit.AddLightsToRenderer(self._renderer)

        self._interactor = window.GetInteractor()
        self._interactor.SetInteractorStyle(v["vtkInteractorStyleTrackballCamera"]())

        axes = v["vtkAxesActor"]()
        axes.SetXAxisLabelText("X")
        axes.SetYAxisLabelText("Y")
        axes.SetZAxisLabelText("Z")
        self._marker = v["vtkOrientationMarkerWidget"]()
        self._marker.SetOrientationMarker(axes)
        self._marker.SetInteractor(self._interactor)
        self._marker.SetViewport(0.0, 0.0, 0.18, 0.24)
        self._marker.EnabledOn()
        self._marker.InteractiveOff()

        # The edge shift depends on where the camera is, so it cannot be baked
        # in when the geometry is built: orbiting and zooming both change it.
        # Recomputing it immediately before each frame is the only place that
        # catches every way the view can move, including the interactor's own
        # drag handling, which never comes back through our code.
        window.AddObserver("StartEvent", self._before_render)

        self._clip = None
        self._apply_background()
        # VTK starts looking straight down the Z axis, which on a gearbox is the
        # one view that shows no depth at all.  The stored viewpoint replaces
        # this a moment later; this is what the first frame looks like if there
        # is none.
        self._place_camera(*STANDARD_VIEWS["iso"])
        self._widget.Initialize()

    # ------------------------------------------------------------------ state
    def set_spec(self, spec: GearSpec) -> None:
        try:
            mesh = mesh_for_spec(spec)
        except Exception:
            logger.error("3D view could not build the assembly\n%s",
                         traceback.format_exc().rstrip())
            return
        first = self._mesh is None
        # `mesh_for_spec` is keyed on the geometry, so an unchanged mesh here is
        # the same object and there is nothing to send to the card: a change of
        # material or rated torque should not cost an upload.
        changed = mesh is not self._mesh
        self._spec, self._mesh = spec, mesh
        if changed:
            self._build_actors()
            self.set_crank(self._crank)
        if first:
            self.fit()
        self._render()

    def _build_actors(self) -> None:
        from vtkmodules.vtkCommonDataModel import vtkPlane, vtkPlaneCollection
        from vtkmodules.vtkFiltersGeneral import vtkClipClosedSurface

        from ..viz.vtkbridge import closed_polydata, feature_edges, part_polydata

        v, mesh = self._vtk, self._mesh
        assert mesh is not None
        for record in self._actors.values():
            self._renderer.RemoveActor(record["actor"])
            self._renderer.RemoveActor(record["edges"])
        self._actors.clear()

        for part in mesh.parts:
            colour = [c / 255.0 for c in part.colour]
            polydata = part_polydata(mesh, part)
            # The clipper and the edge finder both want topology, not shading:
            # the shaded surface has its points split along every crease, which
            # leaves it open, and an open surface cannot be capped.
            solid = closed_polydata(mesh, part)

            # The section is a real cut, not a hole in a shell.  A clipping
            # plane on the mapper is per-fragment and free, and it is also
            # wrong for this: it removes the front of the surface and leaves
            # you looking into a hollow casting.  `vtkClipClosedSurface` caps
            # the opening, so the cut reads as solid material - which for a
            # tool whose job is showing where metal is, is the whole point.
            # It costs CPU, so it only sits in the pipeline while the section
            # slider is off zero.
            plane = vtkPlane()
            planes = vtkPlaneCollection()
            planes.AddItem(plane)
            clipper = vtkClipClosedSurface()
            clipper.SetInputData(solid)
            clipper.SetClippingPlanes(planes)
            clipper.GenerateFacesOn()
            clipper.GenerateOutlineOff()
            clipper.SetScalarModeToColors()
            clipper.SetBaseColor(*colour)
            # Cut faces a shade darker than the part.  Section drawings have
            # marked the cut surface differently for a century, and here it is
            # what separates "you are seeing inside" from "this part is dark".
            clipper.SetClipColor(*[c * 0.62 for c in colour])

            mapper = v["vtkPolyDataMapper"]()
            mapper.SetInputData(polydata)
            mapper.ScalarVisibilityOff()

            actor = v["vtkActor"]()
            actor.SetMapper(mapper)
            prop = actor.GetProperty()
            prop.SetColor(*colour)
            prop.SetInterpolationToPhong()
            prop.SetAmbient(0.16)
            prop.SetDiffuse(0.82)
            # A little specular so the metals read as metal.  Not much: this is
            # a drawing tool, and a mirror finish hides the geometry it is
            # supposed to be showing.
            prop.SetSpecular(0.30)
            prop.SetSpecularPower(28)
            transform = v["vtkTransform"]()
            actor.SetUserTransform(transform)
            self._renderer.AddActor(actor)

            edge_polydata = feature_edges(solid)
            edge_mapper = v["vtkPolyDataMapper"]()
            edge_mapper.SetInputData(edge_polydata)
            edge_mapper.ScalarVisibilityOff()
            edge_actor = v["vtkActor"]()
            edge_actor.SetMapper(edge_mapper)
            edge_actor.SetUserTransform(transform)      # rides with the part
            edge_actor.GetProperty().SetLighting(False)
            edge_actor.GetProperty().SetLineWidth(1.0)
            edge_actor.VisibilityOff()
            self._renderer.AddActor(edge_actor)

            self._actors[part.name] = {
                "part": part, "actor": actor, "mapper": mapper,
                "polydata": polydata, "clipper": clipper, "plane": plane,
                "edges": edge_actor, "edge_mapper": edge_mapper,
                "edge_polydata": edge_polydata,
                # The pristine line vertices.  Every frame writes a shifted
                # copy back; keeping the original means the shift is applied
                # to the geometry and never to a previous shift.
                "edge_points": vtk_to_numpy(
                    edge_polydata.GetPoints().GetData()).copy(),
                "pose": (0.0, 0.0, 0.0, 0.0),
            }

        self._apply_visibility()
        self._apply_edges()
        self._apply_section()

    def set_crank(self, degrees: float) -> None:
        """Re-pose every part.  No geometry moves; the transforms do."""
        self._crank = float(degrees)
        mesh = self._mesh
        if mesh is None:
            return
        from ..viz.vtkbridge import local_plane, pose_matrix

        phi = np.radians(self._crank)
        cut = self._section_plane()
        for part in mesh.parts:
            record = self._actors.get(part.name)
            if record is None:
                continue
            pose = pose_matrix(mesh, part, phi, self._explode)
            record["pose"] = pose
            angle, dx, dy, dz = pose
            transform = record["actor"].GetUserTransform()
            transform.Identity()
            # VTK applies these in reverse, so this rotates about the axis and
            # then carries the part out to the eccentric - not the other way
            # round, which would swing it round the housing.
            transform.Translate(dx, dy, dz)
            transform.RotateZ(angle)

            if cut is not None:
                # The cut is stated in the world and the geometry is stored
                # unposed, so the plane travels backwards through the pose.
                origin, normal = local_plane(pose, *cut)
                record["plane"].SetOrigin(*origin)
                record["plane"].SetNormal(*normal)
        self._render()

    def set_explode(self, fraction: float) -> None:
        self._explode = float(fraction)
        self.set_crank(self._crank)
        self.fit()

    def set_group_visible(self, group: str, visible: bool) -> None:
        """Show or hide a part group, or one named part."""
        self._hidden.discard(group) if visible else self._hidden.add(group)
        self._apply_visibility()
        self._render()

    def hideable_parts(self, group: str) -> list[tuple[str, str]]:
        """(name, label) of the parts in ``group``, for a per-part menu."""
        if self._mesh is None:
            return []
        return [(p.name, p.label) for p in self._mesh.parts if p.group == group]

    def _apply_visibility(self) -> None:
        for record in self._actors.values():
            part = record["part"]
            shown = part.group not in self._hidden and part.name not in self._hidden
            record["actor"].SetVisibility(shown)
            record["edges"].SetVisibility(shown and self._edges)

    def set_edges(self, on: bool) -> None:
        self._edges = bool(on)
        self._apply_edges()
        self._apply_visibility()
        self._render()

    def _apply_edges(self) -> None:
        """Draw the part's *features*, not its triangulation.

        Every cell edge is what `SetEdgeVisibility` gives you, and on this mesh
        that means the long thin triangles the cap triangulator produced, drawn
        across the face of every disc.  These are separate actors carrying only
        the edges above the feature angle - rims, hole lips, the join between a
        cylinder and its end - which is the set a drawing would have.

        Each part's edges are its own colour, darkened.  They used to be the
        theme's ink, which on the dark theme is pure white: every ring pin came
        out ringed in a bright halo, and the model read as a wireframe lit from
        inside rather than as shaded solids.  An edge belongs to the part
        rather than to the window - and this is the rule the software painter
        was already using, so the two renderers agree about it now.
        """
        for record in self._actors.values():
            colour = record["part"].colour
            record["edges"].GetProperty().SetColor(
                *[c / 255.0 * EDGE_SHADE for c in colour])

    def set_section(self, fraction: float) -> None:
        """Cut the assembly on a plane through the axis, and cap the cut."""
        self._section = float(fraction)
        self._apply_section()
        self.set_crank(self._crank)      # the plane moves with the parts
        self._render()

    def _section_plane(self):
        """``(origin, normal)`` in world coordinates, or ``None`` when off.

        The plane is fixed in the model, not in the view.  It was made to
        follow the camera for a while - which does keep the cut facing you from
        every angle - and that is the wrong trade: a cut that moves while you
        orbit gives you nothing steady to read the geometry against, and the
        part you were looking into slides away as you turn towards it.  A
        section plane belongs to the drawing.

        The cost is the one every CAD package has: from behind, you see the
        uncut side, and edge-on you see half a model.  Orbiting is the answer
        to both, and orbiting is not the thing that was ever hard here.
        """
        if self._section <= 0.0 or self._mesh is None:
            return None
        lo, hi = self._mesh.bounds(self._explode)
        span = float(hi[1] - lo[1])
        return (0.0, lo[1] + span * (1.0 - self._section), 0.0), (0.0, -1.0, 0.0)

    def _apply_section(self) -> None:
        """Swap the capping filter in and out of each part's pipeline.

        It is only in circuit while the slider is off zero.  Capping is CPU
        work that has to be redone whenever the plane moves against the part -
        which, for anything that turns, is every frame - and paying for it when
        nothing is being cut would be paying for nothing.

        The edge actors keep a plain mapper clipping plane instead: lines have
        nothing to cap, and cutting them on the GPU is free.
        """
        cut = self._section_plane()
        cutting = cut is not None
        if cutting:
            self._world_plane.SetOrigin(*cut[0])
            self._world_plane.SetNormal(*cut[1])
        for record in self._actors.values():
            mapper = record["mapper"]
            if cutting:
                mapper.SetInputConnection(record["clipper"].GetOutputPort())
                mapper.ScalarVisibilityOn()
            else:
                mapper.RemoveAllInputConnections(0)
                mapper.SetInputData(record["polydata"])
                mapper.ScalarVisibilityOff()

            # A mapper clipping plane is stated in *world* coordinates - VTK
            # carries it through the actor's matrix itself - which is the
            # opposite of what the capping filter needs, since that one works
            # on the stored geometry.  Two planes, and mixing them up puts the
            # cut somewhere else on every part that turns.
            edge_mapper = record["edge_mapper"]
            edge_mapper.RemoveAllClippingPlanes()
            if cutting:
                edge_mapper.AddClippingPlane(self._world_plane)

    def set_theme(self, mode: str) -> None:
        self._mode = mode
        self._apply_background()
        self._apply_edges()
        self._render()

    def _apply_background(self) -> None:
        p = branding.palette(self._mode)
        top = [int(p.raised[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
        bottom = [int(p.surface[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
        # The one gradient in the application, and it earns its place: a flat
        # background gives a rounded grey housing nothing to separate itself
        # from, and the silhouette disappears.
        self._renderer.GradientBackgroundOn()
        self._renderer.SetBackground(*bottom)
        self._renderer.SetBackground2(*top)

    # ----------------------------------------------------------------- camera
    def set_standard_view(self, name: str) -> None:
        azimuth, elevation = STANDARD_VIEWS[name]
        self._place_camera(azimuth, elevation)
        self.fit()

    def _place_camera(self, azimuth: float, elevation: float) -> None:
        camera = self._renderer.GetActiveCamera()
        focal = np.array(camera.GetFocalPoint())
        distance = camera.GetDistance()
        az, el = np.radians(azimuth), np.radians(elevation)
        offset = np.array([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az),
                           np.sin(el)])
        camera.SetPosition(*(focal + distance * offset))
        camera.SetViewUp(0.0, 0.0, 1.0)
        self._renderer.ResetCameraClippingRange()

    def fit(self) -> None:
        if self._mesh is None:
            self._render()
            return
        lo, hi = self._mesh.bounds(self._explode)
        self._renderer.ResetCamera(lo[0], hi[0], lo[1], hi[1], lo[2], hi[2])

        # Screen-space ambient occlusion, with its radius set from the drive
        # rather than left at the default.  It is what makes a pin look like it
        # is *in* its pocket instead of drawn on top of it, and the effect is
        # entirely a function of that radius: too small and it does nothing,
        # too large and the whole assembly goes muddy.
        span = float(np.linalg.norm(hi - lo))
        self._renderer.SetUseSSAO(True)
        self._renderer.SetSSAORadius(0.035 * span)
        self._renderer.SetSSAOBias(0.002 * span)
        self._renderer.SetSSAOKernelSize(32)
        self._renderer.SSAOBlurOn()
        self._render()

    @property
    def camera(self) -> Camera:
        """The current viewpoint as the software view's camera, for storing."""
        vtk_camera = self._renderer.GetActiveCamera()
        focal = np.array(vtk_camera.GetFocalPoint())
        offset = np.array(vtk_camera.GetPosition()) - focal
        distance = float(np.linalg.norm(offset)) or 1.0
        return Camera(target=tuple(focal),
                      azimuth=float(np.degrees(np.arctan2(offset[1], offset[0]))),
                      elevation=float(np.degrees(np.arcsin(
                          np.clip(offset[2] / distance, -1.0, 1.0)))),
                      distance=distance)

    def set_camera_angles(self, azimuth: float, elevation: float) -> None:
        self._place_camera(azimuth, elevation)
        self._render()

    def _before_render(self, *_args) -> None:
        """Put the drawn edges back on their own view rays.

        Only when they are being drawn, and only a few thousand points, so it
        is well under a millisecond - and it is what makes the lines land on
        the edges from every direction and at every zoom rather than beside
        them.
        """
        if not self._edges or not self._actors:
            return
        from ..viz.vtkbridge import local_point, toward_eye

        eye = np.array(self._renderer.GetActiveCamera().GetPosition())
        for record in self._actors.values():
            if not record["edges"].GetVisibility():
                continue
            local_eye = local_point(record["pose"], eye)
            shifted = toward_eye(record["edge_points"], local_eye)
            points = record["edge_polydata"].GetPoints()
            points.SetData(numpy_to_vtk(np.ascontiguousarray(shifted), deep=1))
            points.Modified()

    def _render(self) -> None:
        # Through the widget rather than straight at the render window.  On the
        # Qt-context backend a frame has to be drawn inside `paintGL`, where Qt
        # has made the context current, and `Render` there schedules one.  VTK's
        # own widget spells it the same way, so this reads identically on both.
        if self.isVisible():
            self._widget.Render()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._widget.Render()

    def closeEvent(self, event) -> None:
        # The interactor holds the window; letting it go with the widget still
        # attached leaves a GL context behind on shutdown.  Both backends spell
        # the cleanup `Finalize`.
        self._widget.Finalize()
        super().closeEvent(event)
