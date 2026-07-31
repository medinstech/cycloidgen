"""Derive the application's logo assets from the brand originals.

    python tools/make_assets.py --source "C:/path/to/Logos/Medinstech"

The originals are 6000 px masters that have no business in a source tree.  This
trims them to their own ink, resamples them to the handful of sizes the app and
the report actually ask for, and writes them into the package.

Run it when the brand refreshes, not on every build - the results are committed
so that neither the application nor CI depends on assets living outside the
repository.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

DEFAULT_SOURCE = Path(r"C:\Users\USER\Desktop\Logos\Medinstech")
TARGET = Path(__file__).resolve().parent.parent / "cycloidgen" / "ui" / "assets"

#: Window and executable icon sizes.  16 and 32 are what Windows actually shows
#: in the title bar and the task bar; the rest are for high-DPI and the shell's
#: larger views.
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _trim(path: Path) -> Image.Image:
    """Load and crop to the visible ink, discarding the master's padding."""
    im = Image.open(path).convert("RGBA")
    box = im.getbbox()
    return im.crop(box) if box else im


def _fit(im: Image.Image, width: int) -> Image.Image:
    height = max(1, round(im.height * width / im.width))
    return im.resize((width, height), Image.LANCZOS)


def _square(im: Image.Image, size: int) -> Image.Image:
    """Centre the mark on a transparent square, with a little breathing room."""
    inner = round(size * 0.88)
    scaled = im.copy()
    scaled.thumbnail((inner, inner), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(scaled, ((size - scaled.width) // 2, (size - scaled.height) // 2))
    return canvas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    if not args.source.is_dir():
        raise SystemExit(f"brand assets not found at {args.source}")

    TARGET.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def save(im: Image.Image, name: str) -> None:
        path = TARGET / name
        im.save(path, optimize=True)
        written.append(path)

    for tint in ("blue", "white", "black"):
        mark = _trim(args.source / f"mdns-logo-{tint}@2x.png")
        save(_square(mark, 256), f"mark-{tint}.png")

        word = _trim(args.source / f"Medinstech-logo-text-{tint}@2x.png")
        save(_fit(word, 520), f"wordmark-{tint}.png")

    # Multi-resolution icon for the window and the PyInstaller build
    mark = _trim(args.source / "mdns-logo-blue@2x.png")
    icon = _square(mark, 256)
    icon.save(TARGET / "cycloidgen.ico", sizes=[(s, s) for s in ICON_SIZES])
    written.append(TARGET / "cycloidgen.ico")

    for path in written:
        print(f"  {path.relative_to(TARGET.parent.parent.parent)}  "
              f"{path.stat().st_size / 1024:.0f} kB")
    print(f"{len(written)} assets written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
