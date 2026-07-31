"""Where the application keeps its preferences.

One function, so there is exactly one answer to "which QSettings?".

The override exists because Qt's own redirection does not reliably apply to the
``QSettings(organisation, application)`` constructor - ``setDefaultFormat`` is
quietly ignored on Windows, and the result is a test suite that reads and
rewrites the developer's real preferences while appearing to be isolated.  An
explicit environment variable is both more honest and more useful: it is what
makes a portable install possible.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings

__all__ = ["ENV_VAR", "app_settings"]

#: Point this at a file and every preference is stored there instead of in the
#: platform default location.
ENV_VAR = "CYCLOIDGEN_SETTINGS"

ORGANISATION = "cycloidgen"
APPLICATION = "cycloidgen"


def app_settings() -> QSettings:
    """The application's settings store."""
    override = os.environ.get(ENV_VAR)
    if override:
        return QSettings(override, QSettings.Format.IniFormat)
    return QSettings(ORGANISATION, APPLICATION)
