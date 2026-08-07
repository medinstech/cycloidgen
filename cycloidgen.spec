# PyInstaller build spec.  Build with:  pyinstaller cycloidgen.spec
#
# OCCT (via cadquery/OCP) is the awkward dependency: it ships large binary
# extensions and data files that PyInstaller's analysis does not find on its own.
# collect_all pulls them in wholesale, which is heavy but reliable.
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []
# PIL comes in behind matplotlib, but the animation export reaches the GIF
# writer by name at run time; collect_all is what guarantees the image plugins
# travel with it rather than only the ones matplotlib happens to touch.
for package in ("cadquery", "OCP", "vtkmodules", "ezdxf", "matplotlib",
                "reportlab", "pydantic", "PIL"):
    try:
        d, b, h = collect_all(package)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:                      # optional at build time
        print(f"[spec] skipping {package}: {exc}")

# PyInstaller relocates the extension modules to the bundle root but leaves the
# DLLs they link against inside the package directory, so the import fails with
# "DLL load failed".  Put a copy of those DLLs beside the .pyd.
from importlib.util import find_spec
from pathlib import Path

found = find_spec("OCP")
if found and found.origin:
    for dll in Path(found.origin).parent.glob("*.dll"):
        binaries.append((str(dll), "."))

#: Pulled in by cadquery as hard dependencies and never imported by this
#: application - measured, not assumed: with all of them blocked at import time
#: the whole export path still writes an identical STEP file.
#:
#: They are not small.  Together they are about a third of the bundle, and the
#: reason is that cadquery declares what *cadquery* can do rather than what any
#: one caller uses: numba (with LLVM behind it) accelerates a tessellation path
#: this application does not take, and trame is the Jupyter and browser viewer
#: for a program that ships its own window.
#:
#: casadi is the fourth and is handled differently, because unlike these it is
#: imported whether or not it is used - see `packaging/rthook_casadi.py`.
DEAD_WEIGHT = ["numba", "llvmlite", "trame", "trame_vuetify", "trame_client",
               "trame_server", "trame_vtk", "pyvista"]

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
    excludes=["tkinter", "PyQt5", "PyQt6", "IPython", "jupyter", "pytest",
              "casadi", *DEAD_WEIGHT],
    # Runs before the application's first line, which is the only place the
    # casadi substitution can be made: cadquery imports it on the way in.
    runtime_hooks=["packaging/rthook_casadi.py"],
    noarchive=False,
)
pyz = PYZ(a.pure)

# Windows takes an .ico and nothing else; on Linux the parameter is ignored, so
# the icon travels beside the binary in the AppImage instead - see
# `packaging/appimage.sh`, which reads it out of the same assets folder.
_icon = Path("cycloidgen/ui/assets/cycloidgen.ico")


def _exe(name: str, *, console: bool):
    """One executable over the shared analysis."""
    return EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name=name,
        icon=str(_icon) if (_icon.exists() and sys.platform == "win32") else None,
        version=_version_file,
        console=console,
        disable_windowed_traceback=False,
    )


# On Windows, two executables over one analysis: the `pythonw.exe` /
# `python.exe` arrangement, and for the same reason.  A single console build put
# a black window behind the application every time somebody opened it from the
# Start menu; a single windowed build would have taken the command line away,
# and taken it away *badly* - a frozen windowed process has no stdout at all, so
# `--version` would not print nothing, it would raise.
#
# So the one the shortcuts point at is windowed, and the command line gets its
# own console build beside it.  `launcher.py` keeps the windowed one from
# falling over if it is handed arguments anyway.
#
# Elsewhere, one.  `console` is a Windows subsystem flag - a PE header field
# saying whether the loader allocates a console - and there is no equivalent on
# Linux, where every process has whatever streams it was handed.  A second
# binary there would not be a second behaviour, only a second copy of the same
# one, and a name (`cycloidgen-cli`) implying a difference that does not exist.
#
# The flag does mean something on macOS, but something else again: it decides
# whether Launch Services sees a windowed application or a terminal program, and
# a `.app` has to be the first.  It costs nothing there - unlike Windows, a
# process started from a shell has stdio whatever its bundle says, so
# `cycloidgen.app/Contents/MacOS/cycloidgen --version` still prints.
if sys.platform == "win32":
    executables = [_exe("cycloidgen", console=False),
                   _exe("cycloidgen-cli", console=True)]
else:
    executables = [_exe("cycloidgen", console=sys.platform != "darwin")]

coll = COLLECT(
    *executables, a.binaries, a.datas,
    strip=False,
    upx=False,            # UPX corrupts some OCCT DLLs
    name="cycloidgen",
)

# ---------------------------------------------------------------- macOS .app
#
# A folder with a name and a plist in it, which is what a Mac calls an
# application: Finder shows one icon, Launch Services reads the identifier, and
# `packaging/macos.sh` puts it in a disk image.  Built here rather than in that
# script so that a plain `pyinstaller cycloidgen.spec` produces the same thing
# on a Mac that it does everywhere else - the whole application, ready to run.
if sys.platform == "darwin":
    import subprocess

    # The icon has to be an .icns, and .icns is a container of sizes rather than
    # an image.  `iconutil` builds one from a folder of exact squares; the mark
    # is committed at 256, so what goes in is every size at or below it and
    # nothing above.  Upscaling would fill the two largest slots with a blurred
    # 256 and Finder would show exactly that.  256 is what the Dock asks for on
    # a Retina display, which is where an application icon is actually looked
    # at - the missing 512 and 1024 are Finder's largest icon view alone.
    _icns = None
    _mark = Path("cycloidgen/ui/assets/mark-blue.png")
    if _mark.exists():
        from PIL import Image

        _master = Image.open(_mark).convert("RGBA")
        # Emptied rather than topped up: `iconutil` refuses an iconset with a
        # name in it that it does not recognise, so one file left behind by a
        # build against a different master fails every build after it.
        import shutil

        _iconset = Path("build/cycloidgen.iconset")
        shutil.rmtree(_iconset, ignore_errors=True)
        _iconset.mkdir(parents=True)
        #: (point size, scale) -> pixels, keeping only what the master can fill.
        for _points, _scale in ((16, 1), (16, 2), (32, 1), (32, 2),
                                (128, 1), (128, 2), (256, 1)):
            _pixels = _points * _scale
            if _pixels > _master.width:
                continue
            _suffix = "" if _scale == 1 else "@2x"
            _master.resize((_pixels, _pixels), Image.LANCZOS).save(
                _iconset / f"icon_{_points}x{_points}{_suffix}.png")
        _icns = "build/cycloidgen.icns"
        subprocess.run(["iconutil", "-c", "icns", str(_iconset), "-o", _icns],
                       check=True)

    app = BUNDLE(
        coll,
        name="cycloidgen.app",
        icon=_icns,
        # Never change this.  macOS keys preferences, window state, permissions
        # and the "open with" association to the identifier, not the path or the
        # name, so a new one is a new application to every part of the system and
        # everybody's settings are gone.
        bundle_identifier="com.medinstech.cycloidgen",
        version=_version,
        info_plist={
            "CFBundleName": "cycloidgen",
            "CFBundleDisplayName": "cycloidgen",
            "CFBundleShortVersionString": _version,
            "CFBundleVersion": _version,
            "NSHumanReadableCopyright": "Copyright 2026 Medinstech. Apache-2.0.",
            # Without it the window is drawn at 1x and scaled up, which on a
            # Retina display looks like a screenshot of the application rather
            # than the application.
            "NSHighResolutionCapable": True,
            # The app has a dark theme of its own and follows the system; this
            # is what stops AppKit forcing every window light.
            "NSRequiresAquaSystemAppearance": False,
            # Not a guess: every wheel this is built from is tagged
            # `macosx_11_0_arm64`, so 11 is what the dependencies themselves
            # claim.  It is the floor they state, not one measured here.
            "LSMinimumSystemVersion": "11.0",
        },
    )
