"""Recapture the application screenshots the README embeds.

    python tools/make_screenshots.py

Unlike `docs/make_figures.py`, which renders through matplotlib and runs
anywhere, this one needs a **real desktop session**.  It opens the actual
window, drives it, and photographs it.  Two reasons it cannot be done headless:

* The offscreen Qt platform has no fonts.  Every label comes out as tofu - the
  little rectangles a font renderer draws when it has no glyph - so an offscreen
  screenshot is a picture of the layout and none of the words.
* The 3D tab's viewport is a native OpenGL surface.  It is not part of Qt's
  backing store, so `QWidget.grab` composites the widget tree around it and
  leaves a black hole where the gearbox was.

So the window is grabbed through `PrintWindow` with `PW_RENDERFULLCONTENT`,
which asks Windows for the window's own rendering including native children,
and does not care what is stacked on top of it.  Anything else - screen
grabs, `QScreen.grabWindow` - photographs whatever pixels happen to be there,
including this terminal if it is in the way.

The window will appear on your screen for a few seconds.  That is the point.
"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# Before PySide6 is imported anywhere: the app's own modules pick the platform
# up at import time, and the whole point here is *not* to be offscreen.
os.environ.pop("QT_QPA_PLATFORM", None)

from PIL import Image  # noqa: E402
from PySide6.QtCore import QEventLoop, QPoint, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from cycloidgen.core.spec import GearSpec, Process, preset  # noqa: E402
from cycloidgen.ui.app import prepare_opengl  # noqa: E402
from cycloidgen.ui.main_window import MainWindow  # noqa: E402

#: Matches the committed screenshots, so the README's images stay one size.
WINDOW = (1560, 940)


def hero() -> GearSpec:
    """A machined steel drive - a design worth photographing, not the default.

    The same one `docs/make_figures.py` uses for the trade study, so the README
    is showing one gearbox rather than four.
    """
    spec = preset(21)
    spec.process = Process.CNC
    spec.apply_process_defaults()
    spec.disc_material = "Steel 4140 (hardened)"
    spec.pin_material = "Bearing steel 100Cr6"
    spec.housing_material = "Aluminium 7075-T6"
    spec.ring_pins_are_rollers = True
    spec.output_pins_are_rollers = True
    spec.output_torque_Nm = 25.0
    return spec


def settle(app: QApplication, ms: int = 400) -> None:
    """Run the event loop for a while, so paints and workers actually happen."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    app.processEvents()


def wait_for_analysis(app: QApplication, window: MainWindow,
                      timeout_ms: int = 30_000) -> None:
    """Block until the off-thread analysis has landed, or give up loudly.

    The window runs its analysis in a worker and accepts the result only if its
    generation is still current, so photographing it too early gets a datasheet
    full of the *previous* design.
    """
    waited = 0
    while window.analysis is None and waited < timeout_ms:
        settle(app, 100)
        waited += 100
    if window.analysis is None:
        raise SystemExit("the analysis never finished; nothing worth capturing")


def select_finding(window: MainWindow, code: str) -> bool:
    """Select a check by code, so the explanation panel has something in it."""
    tree = window.findings
    for i in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(i)
        if code in (item.text(c) for c in range(tree.columnCount())):
            tree.setCurrentItem(item)
            return True
    return False


def verify_hue(image: Image.Image) -> None:
    """Refuse to write a screenshot whose channels are the wrong way round.

    A red/blue swap is the one defect in this pipeline that cannot be caught by
    looking: BGRA arrives from GDI, and the picture that comes out of getting
    the conversion wrong is a perfectly composed window in a plausible-looking
    palette.  It shipped once.

    Every surface in the light theme is a *blue*-tinted white - the window is
    ``#eeedff`` and a panel is ``#f5f5ff`` - because they are white mixed with
    the brand blue.  Which of them covers the most pixels depends on the tab, so
    the test is not which one it is; it is that the background is still tinted
    the way the brand tints it.  Reverse the channels and the same pixels come
    out warm, which is the one thing that cannot happen by accident.
    """
    red, _green, blue = max(image.getcolors(maxcolors=1 << 24),
                            key=lambda kv: kv[0])[1]
    if blue < red:
        raise SystemExit(
            f"the red and blue channels look swapped: the background came out "
            f"({red}, {_green}, {blue}), which is warm, and every surface in "
            f"the light theme is a blue-tinted white")


def capture(window: MainWindow, path: Path, widget=None) -> None:
    """Photograph the window through PrintWindow, including native children.

    ``widget`` crops the result to one child - which is how the bare gearbox
    figures are taken.  They have to come from here rather than from
    ``docs/make_figures.py``: that renders through the *software* painter, and
    next to a screenshot of the real viewport it reads as a different program.
    """
    hwnd = int(window.winId())
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32

    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top

    window_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    gdi32.SelectObject(memory_dc, bitmap)

    # 2 is PW_RENDERFULLCONTENT, which is what pulls the OpenGL viewport in.
    if not user32.PrintWindow(hwnd, memory_dc, 2):
        raise SystemExit("PrintWindow refused; is the window minimised?")

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    header = BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    header.biWidth, header.biHeight = width, -height      # negative: top-down
    header.biPlanes, header.biBitCount = 1, 32
    buffer = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer, ctypes.byref(header), 0)

    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory_dc)
    user32.ReleaseDC(hwnd, window_dc)

    # GDI hands back BGRA, and the `raw` decoder's "BGRA" mode is what reorders
    # it - doing that *and* swapping the channels by hand afterwards puts them
    # straight back, which is a mistake that survives review because the result
    # is a perfectly plausible picture in the wrong hue.  The alpha channel is
    # meaningless for a screenshot, so it goes.
    image = Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1)
    image = image.convert("RGB")
    verify_hue(image)

    if widget is not None:
        # PrintWindow photographs the frame as well, so the widget's position
        # inside the client area has to be shifted by however much of that frame
        # sits above and to the left of it.
        scale = width / max(window.frameGeometry().width(), 1)
        inset = window.geometry().topLeft() - window.frameGeometry().topLeft()
        origin = widget.mapTo(window, QPoint(0, 0))
        left, top = origin.x() + inset.x(), origin.y() + inset.y()
        image = image.crop((round(left * scale), round(top * scale),
                            round((left + widget.width()) * scale),
                            round((top + widget.height()) * scale)))

    image.save(path)
    print(f"  {path.name}  {image.width}x{image.height}  "
          f"{path.stat().st_size / 1024:.0f} kB")


def main() -> int:
    if sys.platform != "win32":
        raise SystemExit("PrintWindow is a Win32 call; run this one on Windows")

    # The same GL preparation the real entry point does, or a run with
    # CYCLOIDGEN_VTK_QTGL=1 would be measuring a different program.
    prepare_opengl()
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.resize(*WINDOW)
    window.show()
    window.raise_()
    window.activateWindow()

    # The committed screenshots are light-theme ones, and the window opens on
    # whatever the operator's desktop is set to.  Without this the images depend
    # on who ran the tool - and `verify_hue` below, which is written against the
    # light palette, rejects a dark capture as a channel swap.  Put the stored
    # preference back afterwards: this is a screenshot run, not a settings change.
    appearance = window.appearance
    window._set_appearance("light")

    # ...and the same for the 3D tab's part visibility, which is restored from
    # whatever the operator last left it on.  These images are of a fresh
    # install, so they show what a fresh install shows.
    from cycloidgen.ui.view3d import _HIDDEN_BY_DEFAULT
    for group, box in window._view3d._groups.items():
        box.setChecked(group not in _HIDDEN_BY_DEFAULT)
    settle(app, 600)

    window._replace_spec(hero(), record=False)
    wait_for_analysis(app, window)
    settle(app, 600)

    print("writing screenshots:")

    # The drawing tab, with a check selected so the explanation panel is doing
    # the thing the README says it does.
    window.tabs.setCurrentIndex(window._drawing_tab)

    # Overlays on: they are what makes the README's claim true. Without them the
    # hero image is an outline, and the caption underneath it promises a
    # simulation - contact points sized by the load they carry, forces to scale,
    # and the path a rim point travels over a full output revolution.
    for key in ("contacts", "forces", "trace"):
        window._overlay_boxes[key].setChecked(True)

    for code in ("TRANSMISSION_ERROR", "STRUCTURAL_COMPLIANCE", "PRESSURE_ANGLE"):
        if select_finding(window, code):
            break
    settle(app, 900)
    capture(window, DOCS / "app-drawing.png")

    # The 3D tab needs longer: the first paint builds the mesh and hands it to
    # the card, and photographing during that gets an empty viewport.
    window.tabs.setCurrentIndex(window._solid_tab)
    settle(app, 1500)
    # The panel restores whatever camera it was left on, which on this machine
    # may be straight down the axis - a picture of a circle. Ask for the
    # isometric it opens on from clean, and refit, so the screenshot shows the
    # stack, the shaft and the depth rather than a disc.
    window._view3d.view.set_standard_view("iso")
    window._view3d.view.fit()
    settle(app, 1500)
    capture(window, DOCS / "app-3d.png")

    # The gearbox on its own, assembled and pulled apart, cropped out of the
    # same viewport.  The README puts these next to the window shots, so they
    # have to be the same renderer or the reader is looking at two programs.
    #
    # The window is reshaped first.  In the normal layout the viewport is a wide
    # letterbox, and `fit` fits to its *shortest* side - so a gearbox cropped
    # out of it is a small object adrift in a field of background. A squarer
    # window gives a squarer viewport and the part fills it.
    viewport = window._view3d.view
    window.resize(1080, 1020)
    settle(app, 900)
    window._view3d.view.fit()
    settle(app, 900)
    capture(window, DOCS / "assembly.png", widget=viewport)

    window._view3d.view.set_explode(0.85)
    window._view3d.view.fit()
    settle(app, 1200)
    capture(window, DOCS / "exploded.png", widget=viewport)

    window._set_appearance(appearance)
    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
