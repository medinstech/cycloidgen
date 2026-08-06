"""The Qt-context VTK backend: who asks for frames, and who answers.

This backend renders inside Qt's own GL context, which means it may only draw
from ``paintGL`` - so every request for a frame, wherever it comes from, has to
turn into a scheduled repaint rather than a draw.  There are two routes in and
they are easy to mistake for one: the application calls ``Render`` on the
widget, and the *interactor* raises ``RenderEvent`` on itself when a drag moves
the camera.  Missing the second is silent - the camera moves, nothing repaints,
and on a platform where a mouse drag runs in its own event loop the viewport
simply freezes until the button comes up.

No GL context is created here.  The widget is built and talked to, never shown,
which is enough to hold the wiring: the whole point is that a request is
*scheduled*, and scheduling happens before any drawing does.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("vtkmodules.vtkRenderingOpenGL2")

from PySide6.QtWidgets import QApplication

from cycloidgen.ui.view3d_qtgl import QtGLRenderWidget


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def widget(app):
    w = QtGLRenderWidget()
    yield w
    w.deleteLater()


def _counting(widget):
    """Replace ``update`` with a counter, since that is the whole observable."""
    seen = []
    widget.update = lambda *a, **k: seen.append(1)      # type: ignore[method-assign]
    return seen


def test_the_application_asking_for_a_frame_schedules_one(widget):
    seen = _counting(widget)
    widget.Render()
    assert len(seen) == 1


def test_the_interactor_asking_for_a_frame_schedules_one(widget):
    """The one that was missing.

    ``vtkGenericRenderWindowInteractor.Render`` does not draw and does not touch
    the render window - it raises ``RenderEvent`` and waits to be answered. With
    nothing listening, every frame an interaction asks for is dropped, which is
    exactly the frames a drag consists of.
    """
    seen = _counting(widget)
    widget._interactor.Render()
    assert len(seen) == 1


def test_the_mouse_reaches_the_interactor(widget, app):
    """The other half of a drag: Qt's events have to arrive as VTK's.

    Only the delivery is checked, not what the camera does with it. Driving a
    real drag needs an *enabled* interactor with a renderer under the pointer,
    and getting there without a GL context means calling the two things -
    ``Initialize`` on the interactor, and the trackball style's own rotate -
    that take the process down when there is no context to draw into. That is
    the trap :meth:`QtGLRenderWidget.Initialize` exists to defer, and a test is
    not a good enough reason to spring it.
    """
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    widget.resize(400, 300)
    # Enabled, because an interactor that is not ignores the mouse outright -
    # but with no renderer behind it, so the style finds nothing under the
    # pointer and stops before it can try to draw.
    widget._interactor.Enable()
    seen = []
    widget._interactor.AddObserver("MouseMoveEvent", lambda *a: seen.append(1))
    for step in range(1, 6):
        app.sendEvent(widget, QMouseEvent(
            QEvent.MouseMove, QPointF(200 + 10 * step, 150),
            QPointF(200 + 10 * step, 150), Qt.LeftButton, Qt.LeftButton,
            Qt.NoModifier))
    assert len(seen) == 5


def test_answering_the_interactor_cannot_loop(widget):
    """``paintGL`` renders the *window*, and the window does not raise the
    interactor's event - so scheduling from a render request is safe."""
    fired = []
    widget._render_window.AddObserver("StartEvent", lambda *a: fired.append(1))
    widget._interactor.Render()
    assert not fired
