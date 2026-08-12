"""Parametric cycloidal drive generator."""

#: The one place the version is written.
#:
#: `pyproject.toml` reads it from here (`dynamic = ["version"]`), the
#: PyInstaller spec stamps it into the executable, and `packaging/cycloidgen.nsi`
#: parses this exact line with `!searchparse`.  Keep it a plain string literal
#: assignment on one line: setuptools reads it statically, without importing the
#: package, and NSIS reads it with a text match.  Anything cleverer - a computed
#: string, a tuple, an import - breaks both.
__version__ = "7.3.2"
