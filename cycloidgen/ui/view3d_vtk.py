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
import traceback

import numpy as np
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from ..core.spec import GearSpec
from ..viz.mesh import Mesh, mesh_for_spec
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


def available() -> bool:
    """Whether a VTK view can be built on this display.

    Two questions, and both have to be answered before anything is
    constructed: are the modules importable, and is there a real window system
    underneath.  Whether the *driver* can then give us a GL context is the one
    thing left that has to be discovered by trying, and that failure is an
    ordinary exception, caught where the view is built.
    """
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance()
    platform = (app.platformName() if app is not None
                else os.environ.get("QT_QPA_PLATFORM", ""))
    if platform.lower() in _HEADLESS_PLATFORMS:
        return False
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


class VtkAssemblyView(QWidget):
    """Same interface as the software view, so the tab can hold either."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(320, 260)

        v = _imports()
        self._vtk = v

        self._spec: GearSpec | None = None
        self._mesh: Mesh | None = None
        self._actors: dict[str, object] = {}
        self._crank = 0.0
        self._explode = 0.0
        self._hidden: set[str] = set()
        self._edges = False
        self._section = 0.0
        self._mode = "light"

        self._widget = v["QVTKRenderWindowInteractor"](self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._widget)

        self._renderer = v["vtkRenderer"]()
        window = self._widget.GetRenderWindow()
        window.AddRenderer(self._renderer)
        # Multisampling is the cheap, universally supported anti-aliasing;
        # FXAA is the fallback for drivers that quietly give zero samples.
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
        from ..viz.vtkbridge import part_polydata

        v, mesh = self._vtk, self._mesh
        assert mesh is not None
        for actor in self._actors.values():
            self._renderer.RemoveActor(actor)
        self._actors.clear()

        for part in mesh.parts:
            mapper = v["vtkPolyDataMapper"]()
            mapper.SetInputData(part_polydata(mesh, part))
            mapper.ScalarVisibilityOff()

            actor = v["vtkActor"]()
            actor.SetMapper(mapper)
            prop = actor.GetProperty()
            prop.SetColor(*[c / 255.0 for c in part.colour])
            prop.SetInterpolationToPhong()
            prop.SetAmbient(0.16)
            prop.SetDiffuse(0.82)
            # A little specular so the metals read as metal.  Not much: this is
            # a drawing tool, and a mirror finish hides the geometry it is
            # supposed to be showing.
            prop.SetSpecular(0.30)
            prop.SetSpecularPower(28)
            actor.SetUserTransform(v["vtkTransform"]())
            self._renderer.AddActor(actor)
            self._actors[part.name] = actor

        self._apply_visibility()
        self._apply_edges()
        self._apply_section()

    def set_crank(self, degrees: float) -> None:
        """Re-pose every part.  No geometry moves; the transforms do."""
        self._crank = float(degrees)
        mesh = self._mesh
        if mesh is None:
            return
        from ..viz.vtkbridge import pose_matrix

        phi = np.radians(self._crank)
        for part in mesh.parts:
            actor = self._actors.get(part.name)
            if actor is None:
                continue
            angle, dx, dy, dz = pose_matrix(mesh, part, phi, self._explode)
            transform = actor.GetUserTransform()
            transform.Identity()
            # VTK applies these in reverse, so this rotates about the axis and
            # then carries the part out to the eccentric - not the other way
            # round, which would swing it round the housing.
            transform.Translate(dx, dy, dz)
            transform.RotateZ(angle)
        self._render()

    def set_explode(self, fraction: float) -> None:
        self._explode = float(fraction)
        self.set_crank(self._crank)
        self.fit()

    def set_group_visible(self, group: str, visible: bool) -> None:
        self._hidden.discard(group) if visible else self._hidden.add(group)
        self._apply_visibility()
        self._render()

    def _apply_visibility(self) -> None:
        if self._mesh is None:
            return
        for part in self._mesh.parts:
            actor = self._actors.get(part.name)
            if actor is not None:
                actor.SetVisibility(part.group not in self._hidden)

    def set_edges(self, on: bool) -> None:
        self._edges = bool(on)
        self._apply_edges()
        self._render()

    def _apply_edges(self) -> None:
        line = branding.palette(self._mode).ink
        rgb = [int(line[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
        for actor in self._actors.values():
            prop = actor.GetProperty()
            prop.SetEdgeVisibility(self._edges)
            prop.SetEdgeColor(*rgb)
            prop.SetLineWidth(1.0)

    def set_section(self, fraction: float) -> None:
        """Cut the assembly on a plane through the axis.

        A clipping plane on the mapper rather than a boolean on the geometry:
        the GPU does it per fragment, so the slider is live at any frame rate,
        and the design being cut is untouched.  The cut faces are open, which
        is what a clipping plane gives you - capping them means re-cutting the
        surface on the CPU every time the slider moves.
        """
        self._section = float(fraction)
        self._apply_section()
        self._render()

    def _apply_section(self) -> None:
        v = self._vtk
        for actor in self._actors.values():
            actor.GetMapper().RemoveAllClippingPlanes()
        if self._section <= 0.0 or self._mesh is None:
            return
        from vtkmodules.vtkCommonDataModel import vtkPlane

        lo, hi = self._mesh.bounds(self._explode)
        span = float(hi[1] - lo[1])
        plane = vtkPlane()
        plane.SetOrigin(0.0, lo[1] + span * (1.0 - self._section), 0.0)
        plane.SetNormal(0.0, -1.0, 0.0)
        for actor in self._actors.values():
            actor.GetMapper().AddClippingPlane(plane)
        self._clip = (plane, v)

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

    def _render(self) -> None:
        if self.isVisible():
            self._widget.GetRenderWindow().Render()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._widget.GetRenderWindow().Render()

    def closeEvent(self, event) -> None:
        # The interactor holds the window; letting it go with the widget still
        # attached leaves a GL context behind on shutdown.
        self._widget.GetRenderWindow().Finalize()
        super().closeEvent(event)
