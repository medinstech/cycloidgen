# PyInstaller build spec.  Build with:  pyinstaller cycloidgen.spec
#
# OCCT (via cadquery/OCP) is the awkward dependency: it ships large binary
# extensions and data files that PyInstaller's analysis does not find on its own.
# collect_all pulls them in wholesale, which is heavy but reliable.
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []
# casadi backs cadquery's assembly solver and ships loose DLLs beside its .pyd,
# which PyInstaller's dependency walker does not follow on its own.
for package in ("cadquery", "OCP", "casadi", "vtkmodules", "ezdxf", "matplotlib",
                "reportlab", "pydantic"):
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

# Brand assets: collect_submodules only finds importable modules, so the logos
# have to be listed as data or the frozen app starts with no icon and an empty
# header.
_assets = Path("cycloidgen/ui/assets")
if _assets.is_dir():
    datas += [(str(p), "cycloidgen/ui/assets") for p in _assets.iterdir()
              if p.suffix in {".png", ".ico"}]

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

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="cycloidgen",
    icon=str(_icon) if _icon.exists() else None,
    console=True,   # keep the CLI usable and errors visible
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False,
    upx=False,            # UPX corrupts some OCCT DLLs
    name="cycloidgen",
)
