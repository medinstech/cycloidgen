"""Frozen-build entry point.

PyInstaller runs its entry script as a top-level module, which breaks the
relative imports inside ``cycloidgen/__main__.py``.  Going through this file
keeps ``cycloidgen`` a real package at runtime.
"""
import io
import sys


def _ensure_streams() -> None:
    """Give the windowed build somewhere to write.

    A frozen windowed process has no console, and PyInstaller sets
    ``sys.stdout`` and ``sys.stderr`` to ``None`` rather than to something
    inert.  Anything that prints then raises ``AttributeError`` on
    ``None.write`` - which includes ``argparse``, so ``cycloidgen.exe
    --version`` would not print nothing, it would fall over.  The command line
    has its own console build (``cycloidgen-cli.exe``); this is only so that the
    windowed one cannot be taken down by a stray ``print``.
    """
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, io.StringIO())


_ensure_streams()

from cycloidgen.__main__ import main  # noqa: E402  - streams first, then imports

if __name__ == "__main__":
    raise SystemExit(main())
