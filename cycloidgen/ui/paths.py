"""Where the packaged assets are, asked without a toolkit.

The brand files live under ``cycloidgen/ui`` because that is what installs
them: ``pyproject.toml`` declares them as package data for this package.  But
the PDF dossier wants the wordmark too, and a dossier is written on machines
that have no Qt - a CI job, a notebook, a `python -m cycloidgen --out` run.
Looking the path up from :mod:`cycloidgen.ui.branding` meant importing
PySide6 to find out where a file is, and the report's fallback then quietly
dropped the letterhead on exactly those machines: same design in, two
different PDFs out, with nothing said.  The path lives here and the painting
stays in `branding`, so the report can have the first without the second.
"""
from __future__ import annotations

from pathlib import Path

__all__ = ["ASSETS", "asset"]

#: The folder itself, for the two callers that want to look before they ask.
ASSETS = Path(__file__).resolve().parent / "assets"


def asset(name: str) -> Path:
    path = ASSETS / name
    if not path.exists():
        # Two generators write into this folder and they are not interchangeable:
        # the brand assets are trimmed from masters that are not in the tree,
        # the icon is drawn from the profile equations.  Naming the wrong one
        # sends whoever hit this looking for logos they were never given.
        tool = "make_icon" if _is_app_icon(name) else "make_assets"
        raise FileNotFoundError(f"missing asset {name!r}; run tools/{tool}.py")
    return path


def _is_app_icon(name: str) -> bool:
    return name.startswith("icon-") or name.endswith(".ico")
