"""Application entry point."""
from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtCore import QLocale
    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow

    # Engineering input: a dot decimal separator regardless of the system locale,
    # otherwise "50,000 mm" reads as fifty thousand.
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("cycloidgen")
    app.setOrganizationName("cycloidgen")

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
