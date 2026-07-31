"""Frozen-build entry point.

PyInstaller runs its entry script as a top-level module, which breaks the
relative imports inside ``cycloidgen/__main__.py``.  Going through this file
keeps ``cycloidgen`` a real package at runtime.
"""
from cycloidgen.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
