"""Application entry point."""
from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtCore import QLocale, Qt
    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow

    # Engineering input: a dot decimal separator regardless of the system locale,
    # otherwise "50,000 mm" reads as fifty thousand.
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))

    # Has to be set before the QApplication exists, which is why it is here and
    # not with the rest of the 3D setup.  The VTK view is a QOpenGLWidget on
    # macOS - see `view3d_vtk._imports` - and a QOpenGLWidget that does not
    # share its context with the application's gets a blank viewport the first
    # time it is reparented, which is exactly what a tab widget does to it.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("cycloidgen")
    app.setOrganizationName("cycloidgen")

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
