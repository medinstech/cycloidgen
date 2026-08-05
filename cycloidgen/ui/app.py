"""Application entry point."""
from __future__ import annotations

import sys


def prepare_opengl() -> None:
    """Settle the GL context before a QApplication exists, because it must be.

    Both of these are read when the application is constructed and ignored
    afterwards, so there is nowhere else they can go.  They matter only to the
    viewport that renders inside Qt's context - see
    :mod:`cycloidgen.ui.view3d_qtgl` - and asking for them costs nothing where
    that is not used.

    * A **shared context**, or a ``QOpenGLWidget`` goes blank the first time it
      is reparented, which is exactly what putting it in a tab does to it.
    * A **3.2 core profile**, because macOS hands out a legacy 2.1 context to
      anyone who does not ask, and VTK's OpenGL2 backend cannot run on that.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QSurfaceFormat
    from PySide6.QtWidgets import QApplication

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    try:
        from .view3d_qtgl import default_surface_format
    except Exception:                       # a build with no VTK to render into
        return
    QSurfaceFormat.setDefaultFormat(default_surface_format())


def main() -> int:
    from PySide6.QtCore import QLocale
    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow

    # Engineering input: a dot decimal separator regardless of the system locale,
    # otherwise "50,000 mm" reads as fifty thousand.
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))

    prepare_opengl()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("cycloidgen")
    app.setOrganizationName("cycloidgen")

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
