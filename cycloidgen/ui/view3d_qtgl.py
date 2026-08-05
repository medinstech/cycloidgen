"""A VTK viewport that renders inside Qt's OpenGL context rather than beside it.

VTK ships a Qt widget, and on Windows and Linux it works.  On macOS it takes the
application down: it builds a GL context directly on the view ``winId()``
returns, with ``WA_PaintOnScreen`` set - an attribute Qt documents as X11-only,
on a platform whose views have been layer-backed and mandatorily so since 10.14.
The first render blocks the main thread as the tab opens.

Setting VTK's ``QVTKRWIBase`` to ``QOpenGLWidget`` looks like the answer and is
not.  In VTK 9.6 that changes the base class and nothing else: the widget has no
``initializeGL``, no ``paintGL``, it never touches ``QSurfaceFormat``, and it
still constructs a plain ``vtkRenderWindow`` and hands it ``winId()``.  The
context is still built beside Qt's.

So this is the widget VTK's C++ side has as ``QVTKOpenGLNativeWidget`` and its
Python side does not.  Three things make it work:

* **``vtkGenericOpenGLRenderWindow``** owns no context.  It adopts the one Qt
  has already made current - ``InitializeFromCurrentContext`` - so there is no
  second context and no native handle to get wrong.
* **Blit to current.**  A ``QOpenGLWidget`` does not draw to the screen; it draws
  to a framebuffer Qt binds before ``paintGL`` and composites afterwards.  VTK
  renders into its own framebuffer and blits into whatever is bound, which is
  exactly that one.  Qt swaps, so VTK must not.
* **Rendering only ever happens inside ``paintGL``.**  ``Render`` schedules a
  repaint instead of drawing, because a draw outside ``paintGL`` is a draw on
  whatever context happens to be current - which is the original bug in a
  different costume.

Interaction is forwarded by hand.  ``vtkGenericRenderWindowInteractor`` is the
interactor for exactly this case: it has no event loop of its own and expects to
be told what happened.

Where this got to, so the next attempt starts here
--------------------------------------------------
**Unfinished.**  Off by default everywhere, including macOS, and selected only
by ``CYCLOIDGEN_VTK_QTGL=1``.

**Nothing was being rendered at all, anywhere**, and the one call that fixes
that is ``SetIsCurrent``.  ``vtkGenericOpenGLRenderWindow`` cannot discover
whether the context is current - it exists to be driven by a toolkit that owns
one, and it expects to be told.  Unanswered, ``IsCurrent()`` is false and the
render short-circuits *silently*: no error, no warning, and not even the
background cleared.  Measured off VTK's own buffer with ``GetPixelData`` rather
than off the screen, which is what separates "drew and the frame was lost" from
"never drew": without the call it is 100% black, and with it the background
lands at 88% and a cone fills the rest.  ``SetMapped`` and ``SetSupportsOpenGL``
change nothing; only this one matters.

**The previous note here was wrong, and that is why the search went where it
did.**  It recorded that a cone in this widget draws top-level, in a layout and
in a tab, and that only :class:`~cycloidgen.ui.view3d_vtk.VtkAssemblyView` came
out empty.  Re-measured with a rig checked by two controls - a painted widget
with no GL in it, and a plain ``QOpenGLWidget`` clearing to a known colour, both
of which photograph correctly - the standalone case is black too.  It had never
drawn anywhere.  So subtracting from ``MainWindow`` was always going to find
nothing, in either direction, and everything "ruled out" by that subtraction was
ruled out against a fault that was not there: multisampling, FXAA, SSAO, the
marker's second renderer, the ``StartEvent`` observer, layered rendering, the
surface format, nesting in a layout, nesting in a tab, the stylesheet.  None of
those are cleared any more.  They were never suspects.

**What is left: the transfer, and it is unsolved in both cases.**  The commit
that found ``SetIsCurrent`` claimed a bare widget draws on screen with it.  That
was measured while the ``WindowMakeCurrentEvent`` observer below was still in
the file, and the same commit removed it.  Measured again afterwards, with one
camera across all four combinations:

===================  ==========================  =====================
observer             bare widget                 assembly view
===================  ==========================  =====================
on                   draws, 269 colours, 4% black  black, 98%
off (what is here)   black, 93%                  black, 98%
===================  ==========================  =====================

So the observer was never a repair for the assembly view - it only ever moved
the bare widget's frame into the framebuffer Qt composites, by rebinding it
mid-render as a side effect, and mid-render is also what destroys the assembly
view's frame.  One mechanism, helpful at one moment and fatal at another.

What is established is upstream of that: with ``SetIsCurrent`` VTK draws, which
is measured off its own buffer with ``GetPixelData`` - in the real assembly view
a hand-driven ``Render`` fills it with the gearbox, mean ``(222, 223, 241)``.
The picture exists.  Nothing carries it to Qt.

Tried and does not do it: ``makeCurrent`` after ``Render`` rather than during;
binding the widget's framebuffer with ``glBindFramebuffer`` before an explicit
``BlitDisplayFramebuffer``; and that explicit blit at all, which turns the one
case that did reach the screen black.  ``SSAO``, the second layer and
multisampling change nothing either way, measured on screen.

So the question is narrow now: what binds the framebuffer VTK blits into, and
when.  ``vtkGenericOpenGLRenderWindow`` has no ``SetDefaultFrameBufferId`` in
the 9.6 Python wheel, which is the call VTK's own C++ widget uses for exactly
this, and that absence is the shape of the remaining problem.

Four traps, all of them paid for, and all of them the same lesson - **check the
measurement before believing the result**:

* ``QOpenGLWidget.grabFramebuffer`` is not a measurement here.  It reports a
  uniform image for a viewport demonstrably drawing on screen.
* Neither is ``PrintWindow`` on a *child* widget's own ``winId()``.  It reported
  blank for the same widget that a top-level capture showed rendering, which
  cost a whole false conclusion about nesting.  Photograph the top-level window
  and crop, as ``tools/make_screenshots.py`` does.
* ``mapper.SetInputConnection(vtkConeSource().GetOutputPort())`` segfaults.  The
  temporary source is collected the moment the call returns, the port does not
  keep it alive, and the crash looks exactly like a broken GL integration.  It
  cost an afternoon and a wrong bug report that was very nearly filed upstream.
* Answering ``WindowMakeCurrentEvent`` with ``makeCurrent()`` looks like the
  other half of the ``SetIsCurrent`` repair and undoes it.  VTK raises that
  event mid-render and ``QOpenGLWidget.makeCurrent()`` rebinds the widget's
  framebuffer, abandoning the frame in progress.  Removing the view's own
  ``StartEvent`` observer left the viewport black; removing this one drew the
  gearbox.  A repair can arrive carrying its own bug, and only taking the two
  apart one at a time says which is which.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from vtkmodules.vtkRenderingOpenGL2 import vtkGenericOpenGLRenderWindow
from vtkmodules.vtkRenderingUI import vtkGenericRenderWindowInteractor

__all__ = ["QtGLRenderWidget", "default_surface_format"]


def default_surface_format() -> QSurfaceFormat:
    """The format VTK's OpenGL2 backend needs, which macOS will not give by default.

    Ask for nothing and macOS hands out a legacy 2.1 context, because the core
    profile has to be requested explicitly there; VTK's backend wants 3.2 core.
    A depth buffer is not optional for a solid model, and the stencil buffer is
    what the section plane's capping uses.

    Must be installed before the ``QApplication`` exists to be the default for
    widgets created later, which is why it is a function here and called from
    :mod:`cycloidgen.ui.app`.
    """
    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setVersion(3, 2)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    fmt.setSamples(8)                       # the multisampling the view asks for
    fmt.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
    return fmt


class QtGLRenderWidget(QOpenGLWidget):
    """Drop-in for ``QVTKRenderWindowInteractor``, on Qt's own context.

    The surface the assembly view uses is small on purpose - ``GetRenderWindow``,
    ``Initialize``, ``Render`` and ``Finalize`` - so the two backends are
    interchangeable and everything above this line is written once.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        self._render_window = vtkGenericOpenGLRenderWindow()
        # Qt owns the context and the swap; VTK borrows the first and must not
        # do the second, or the frame is presented twice and tears.
        self._render_window.SetOwnContext(0)
        self._render_window.SwapBuffersOff()
        self._render_window.SetFrameBlitModeToBlitToCurrent()

        self._interactor = vtkGenericRenderWindowInteractor()
        self._interactor.SetRenderWindow(self._render_window)
        self._initialised = False
        self._interactor_wanted = False

    # ------------------------------------------------ the interchangeable bit
    def GetRenderWindow(self):
        return self._render_window

    def Initialize(self) -> None:
        """Remember that the interactor is wanted; start it once there is a context.

        ``vtkRenderWindowInteractor.Initialize`` renders as part of starting up,
        and callers reasonably do this straight after construction - VTK's own
        widget is built that way.  Here that is a render before the widget has
        ever been shown, so before ``initializeGL`` has adopted a context, and
        VTK announces it as ``Failed to initialize OpenGL functions`` on its way
        down.  Deferring is the whole fix: there is nothing useful to initialise
        until Qt has a context to hand over.
        """
        self._interactor_wanted = True
        if self._initialised:
            self._start_interactor()

    def _start_interactor(self) -> None:
        self._interactor.Initialize()
        self._interactor.Enable()

    def Render(self) -> None:
        """Schedule a frame.  Drawing happens in ``paintGL`` and nowhere else."""
        self.update()

    def Finalize(self) -> None:
        """Release VTK's GL objects while the context is still alive.

        Letting them go afterwards leaves the driver holding buffers whose
        context has been destroyed, which is a crash on exit rather than a leak.
        """
        if self._initialised:
            self.makeCurrent()
            self._render_window.SetIsCurrent(True)
            self._render_window.SetReadyForRendering(False)
            self._render_window.Finalize()
            self.doneCurrent()
            # The context is no longer ours, and a render window that thinks it
            # still is would skip making one current and draw on a stranger's.
            self._render_window.SetIsCurrent(False)
            self._initialised = False

    # ------------------------------------------------------- Qt's GL callbacks
    def initializeGL(self) -> None:
        super().initializeGL()
        self._render_window.SetReadyForRendering(True)
        self._render_window.InitializeFromCurrentContext()
        # VTK cannot find out whether the context is current; the toolkit that
        # owns it has to say so, and until it does nothing is drawn at all.
        #
        # Answering `WindowMakeCurrentEvent` with `makeCurrent()` looks like the
        # matching half of this and is not: VTK raises it mid-render, and
        # `QOpenGLWidget.makeCurrent()` rebinds the widget's framebuffer, which
        # abandons the frame in progress.  Measured, and it is the difference
        # between a drawn gearbox and a black viewport.  Qt has already made the
        # context current at every point we hand VTK to it, so there is nothing
        # for that observer to do except damage.
        self._render_window.SetIsCurrent(True)
        self._initialised = True
        if self._interactor_wanted:
            self._start_interactor()

    def resizeGL(self, width: int, height: int) -> None:
        super().resizeGL(width, height)
        # Qt reports logical pixels and OpenGL wants physical ones; on a retina
        # display those differ by two and the picture lands in a quarter of the
        # viewport if this is missed.
        ratio = self.devicePixelRatioF()
        size = max(int(width * ratio), 1), max(int(height * ratio), 1)
        self._render_window.SetSize(*size)
        self._interactor.SetSize(*size)

    def paintGL(self) -> None:
        super().paintGL()
        if self._initialised:
            # Qt has made the context current to call this, so the answer is
            # yes - and saying so is what makes the frame happen at all.
            self._render_window.SetIsCurrent(True)
            self._render_window.Render()

    # ------------------------------------------------------------- the mouse
    def _tell_vtk_where(self, event) -> None:
        ratio = self.devicePixelRatioF()
        position = event.position()
        modifiers = event.modifiers()
        # VTK counts from the bottom, Qt from the top.  Four arguments and no
        # more: the keyboard ones are defaulted, and naming them here means
        # passing a char and a null through the wrapper for no gain.
        self._interactor.SetEventInformation(
            int(position.x() * ratio),
            int((self.height() - position.y()) * ratio),
            1 if modifiers & Qt.KeyboardModifier.ControlModifier else 0,
            1 if modifiers & Qt.KeyboardModifier.ShiftModifier else 0)

    def mousePressEvent(self, event) -> None:
        self._tell_vtk_where(event)
        button = event.button()
        if button == Qt.MouseButton.LeftButton:
            self._interactor.LeftButtonPressEvent()
        elif button == Qt.MouseButton.RightButton:
            self._interactor.RightButtonPressEvent()
        elif button == Qt.MouseButton.MiddleButton:
            self._interactor.MiddleButtonPressEvent()

    def mouseReleaseEvent(self, event) -> None:
        self._tell_vtk_where(event)
        button = event.button()
        if button == Qt.MouseButton.LeftButton:
            self._interactor.LeftButtonReleaseEvent()
        elif button == Qt.MouseButton.RightButton:
            self._interactor.RightButtonReleaseEvent()
        elif button == Qt.MouseButton.MiddleButton:
            self._interactor.MiddleButtonReleaseEvent()

    def mouseMoveEvent(self, event) -> None:
        self._tell_vtk_where(event)
        self._interactor.MouseMoveEvent()

    def wheelEvent(self, event) -> None:
        ratio = self.devicePixelRatioF()
        position = event.position()
        self._interactor.SetEventInformation(
            int(position.x() * ratio),
            int((self.height() - position.y()) * ratio))
        if event.angleDelta().y() >= 0:
            self._interactor.MouseWheelForwardEvent()
        else:
            self._interactor.MouseWheelBackwardEvent()
