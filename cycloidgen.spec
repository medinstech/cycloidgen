# PyInstaller build spec.  Build with:  pyinstaller cycloidgen.spec
#
# OCCT (via cadquery/OCP) is the awkward dependency: it ships large binary
# extensions and data files that PyInstaller's analysis does not find on its own.
# collect_all pulls them in wholesale, which is heavy but reliable.
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []
# casadi backs cadquery's assembly solver and ships loose DLLs beside its .pyd,
# which PyInstaller's dependency walker does not follow on its own.
# PIL comes in behind matplotlib, but the animation export reaches the GIF
# writer by name at run time; collect_all is what guarantees the image plugins
# travel with it rather than only the ones matplotlib happens to touch.
for package in ("cadquery", "OCP", "casadi", "vtkmodules", "ezdxf", "matplotlib",
                "reportlab", "pydantic", "PIL"):
    try:
        d, b, h = collect_all(package)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:                      # optional at build time
        print(f"[spec] skipping {package}: {exc}")

# PyInstaller relocates _casadi.pyd to the bundle root but leaves the DLLs it
# links against inside casadi/, so the import fails with "DLL load failed".
# Put a copy of those DLLs beside the .pyd.
from importlib.util import find_spec
from pathlib import Path

for package in ("casadi", "OCP"):
    found = find_spec(package)
    if found and found.origin:
        for dll in Path(found.origin).parent.glob("*.dll"):
            binaries.append((str(dll), "."))

hiddenimports += collect_submodules("cycloidgen")
hiddenimports += ["matplotlib.backends.backend_qtagg", "PySide6.QtSvg"]
# The 3D view reaches these three only at run time: VTK's Qt widget, and the
# two modules whose import is what *registers* the OpenGL backend and the
# interactor styles.  Without them the frozen build silently falls back to the
# software renderer.
hiddenimports += ["vtkmodules.qt.QVTKRenderWindowInteractor",
                  "vtkmodules.vtkRenderingOpenGL2",
                  "vtkmodules.vtkInteractionStyle"]

# Brand assets: collect_submodules only finds importable modules, so the logos
# have to be listed as data or the frozen app starts with no icon and an empty
# header.
_assets = Path("cycloidgen/ui/assets")
if _assets.is_dir():
    datas += [(str(p), "cycloidgen/ui/assets") for p in _assets.iterdir()
              if p.suffix in {".png", ".ico"}]

# Stamp the version into the executable, read from the one place it is written
# (see RELEASING.md).  Windows shows this in the file's Properties and the
# installer's Add/Remove entry is generated from the same string, so a stale
# copy here would be a build that lies about itself.
import re
import sys

_source = Path("cycloidgen/__init__.py").read_text(encoding="utf-8")
_version = re.search(r'^__version__ = "([^"]+)"$', _source, re.MULTILINE).group(1)
# VS_FIXEDFILEINFO wants exactly four integers; the fourth is a build number we
# do not use, and a pre-release suffix has nowhere to go in it.
_parts = tuple(int(n) for n in re.findall(r"\d+", _version)[:3]) + (0,)

_version_file = None
if sys.platform == "win32":
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    _info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=_parts, prodvers=_parts, mask=0x3F, flags=0x0,
                          OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", "Medinstech"),
                StringStruct("FileDescription",
                             "cycloidgen - parametric cycloidal drive generator"),
                StringStruct("FileVersion", _version),
                StringStruct("InternalName", "cycloidgen"),
                StringStruct("LegalCopyright",
                             "Copyright 2026 Medinstech. Apache-2.0."),
                StringStruct("OriginalFilename", "cycloidgen.exe"),
                StringStruct("ProductName", "cycloidgen"),
                StringStruct("ProductVersion", _version),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )
    # Written out rather than passed as an object: older PyInstaller releases
    # only accept a path here, and this costs one file in the build directory.
    Path("build").mkdir(exist_ok=True)
    _version_file = "build/version_info.txt"
    Path(_version_file).write_text(str(_info), encoding="utf-8")

a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "PyQt5", "PyQt6", "IPython", "jupyter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

_icon = Path("cycloidgen/ui/assets/cycloidgen.ico")


def _exe(name: str, *, console: bool):
    """One executable over the shared analysis."""
    return EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name=name,
        icon=str(_icon) if _icon.exists() else None,
        version=_version_file,
        console=console,
        disable_windowed_traceback=False,
    )


# Two executables over one analysis, which is the `pythonw.exe` / `python.exe`
# arrangement and for the same reason.  A single console build put a black
# window behind the application every time somebody opened it from the Start
# menu; a single windowed build would have taken the command line away, and
# taken it away *badly* - a frozen windowed process has no stdout at all, so
# `--version` would not print nothing, it would raise.
#
# So the one the shortcuts point at is windowed, and the command line gets its
# own console build beside it.  `launcher.py` keeps the windowed one from
# falling over if it is handed arguments anyway.
gui = _exe("cycloidgen", console=False)
cli = _exe("cycloidgen-cli", console=True)

coll = COLLECT(
    gui, cli, a.binaries, a.datas,
    strip=False,
    upx=False,            # UPX corrupts some OCCT DLLs
    name="cycloidgen",
)
