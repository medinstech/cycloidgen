"""Derive the application's logo assets from the brand originals.

    python tools/make_assets.py --source "path/to/Logos/Medinstech"
    MEDINSTECH_LOGOS=path/to/logos python tools/make_assets.py

The originals are 6000 px masters that have no business in a source tree.  This
trims them to their own ink, resamples them to the handful of sizes the app and
the report actually ask for, and writes them into the package.

Run it when the brand refreshes, not on every build - the results are committed
so that neither the application nor CI depends on assets living outside the
repository.  The masters are trademarks and are not distributed with it (see
NOTICE), so there is no default path to give: say where they are.

The application *icon* is not one of these.  It is a cycloidal disc drawn from
the profile equations, it needs no masters, and it lives in
``tools/make_icon.py``.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from PIL import Image

#: Where the masters live, if you would rather not pass it every time.
SOURCE_ENV = "MEDINSTECH_LOGOS"
TARGET = Path(__file__).resolve().parent.parent / "cycloidgen" / "ui" / "assets"


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


def _tick(size: int = 32) -> Image.Image:
    """A white check mark for the brand-filled checkbox indicator.

    Styling ``QCheckBox::indicator`` replaces the native one *including* its
    tick, which leaves a filled square that does not obviously mean "on".
    """
    from PIL import ImageDraw

    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    w = max(2, round(size * 0.12))
    d.line([(size * 0.22, size * 0.52), (size * 0.42, size * 0.72),
            (size * 0.78, size * 0.28)],
           fill=(255, 255, 255, 255), width=w, joint="curve")
    return im


def _chevron(size: int, colour: tuple[int, int, int], up: bool = False) -> Image.Image:
    """A chevron for combo boxes and spin buttons.

    Styling ``QComboBox::drop-down`` or a spin box's buttons drops the platform
    arrow with them, so a styled combo looks exactly like a text field until you
    click it, and a spin box loses its up/down affordance entirely.
    """
    from PIL import ImageDraw

    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    w = max(2, round(size * 0.10))
    near, far = (0.60, 0.40) if up else (0.40, 0.60)
    d.line([(size * 0.26, size * near), (size * 0.5, size * far),
            (size * 0.74, size * near)],
           fill=(*colour, 235), width=w, joint="curve")
    return im


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path,
                        default=Path(os.environ[SOURCE_ENV])
                        if os.environ.get(SOURCE_ENV) else None,
                        help=f"folder holding the brand masters; defaults to "
                             f"${SOURCE_ENV}")
    args = parser.parse_args()
    if args.source is None:
        raise SystemExit(f"say where the brand masters are: --source PATH, "
                         f"or set ${SOURCE_ENV}")
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

    # Control glyphs the stylesheet needs, because styling a control replaces
    # the platform's own drawing of it.
    save(_tick(32), "tick.png")
    for tint, rgb in (("light", (0x52, 0x51, 0x4e)), ("dark", (0xc3, 0xc2, 0xb7))):
        save(_chevron(28, rgb), f"chevron-down-{tint}.png")
        save(_chevron(28, rgb, up=True), f"chevron-up-{tint}.png")

    # The application icon is *not* written here.  It used to be - the mark, at
    # icon sizes - and an icon that is the company logo says who wrote the
    # program and nothing about what it does.  It is a cycloidal disc now, drawn
    # from the profile equations by `tools/make_icon.py`, which needs none of
    # these masters and is not run from here so that a brand refresh cannot
    # quietly put the logo back.

    for path in written:
        print(f"  {path.relative_to(TARGET.parent.parent.parent)}  "
              f"{path.stat().st_size / 1024:.0f} kB")
    print(f"{len(written)} assets written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
