"""Build the two bitmaps the NSIS wizard shows.

    python tools/make_setup_graphics.py

MUI2 draws both from fixed-size controls, so the dimensions are not a choice:
``header.bmp`` is 150x57 and ``wizard.bmp`` is 164x314, both 24-bit BMP with no
alpha channel - NSIS will not composite one, and a PNG with transparency arrives
as a black rectangle.

The sources are the wordmark already committed under ``cycloidgen/ui/assets``,
not the 6000 px masters, and the application icon, which is drawn here at the
exact size each control shows it at - so this needs nothing outside the
repository.  The results are committed too, which is what lets ``makensis`` run
on a machine with no Python.

What the panels show is the *product*: the icon somebody is about to get a
shortcut to, at the two places this wizard has a picture.  The Medinstech
wordmark stays on the welcome band, where it says who publishes it.
"""
from __future__ import annotations

from pathlib import Path

from make_icon import render as render_icon
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "cycloidgen" / "ui" / "assets"
TARGET = ROOT / "packaging" / "setup_graphics"

#: The application's own light surface.  The wizard's background is set to the
#: same value in the .nsi, so the bitmaps have to fade into exactly this or
#: there is a visible seam down the side of the panel.
PAPER = (0xF6, 0xF5, 0xFF)
BRAND_BLUE = (0x0D, 0x00, 0xFF)

HEADER = (150, 57)
WIZARD = (164, 314)


def _flatten(path: Path) -> Image.Image:
    """Load an RGBA asset onto the paper tone.  BMP has nowhere to put alpha."""
    im = Image.open(path).convert("RGBA")
    box = im.getbbox()
    if box:
        im = im.crop(box)
    flat = Image.new("RGB", im.size, PAPER)
    flat.paste(im, mask=im.split()[3])
    return flat


def _fit(im: Image.Image, width: int, height: int) -> Image.Image:
    scale = min(width / im.width, height / im.height)
    return im.resize((max(1, round(im.width * scale)),
                      max(1, round(im.height * scale))), Image.LANCZOS)


def _icon(size: int) -> Image.Image:
    """The application icon at exactly ``size``, on the paper.

    Drawn rather than scaled from the committed 256: the icon is graded by size
    - fewer lobes and no output holes as it gets smaller - and 40 px of a 256 px
    disc is the soup that grading exists to avoid.  BMP has nowhere to put an
    alpha channel, so the tile's rounded corners are composited here.
    """
    icon = render_icon(size)
    flat = Image.new("RGB", icon.size, PAPER)
    flat.paste(icon, mask=icon.split()[3])
    return flat


def _header() -> Image.Image:
    canvas = Image.new("RGB", HEADER, PAPER)
    mark = _icon(40)
    # Right-aligned, because MUI_HEADERIMAGE_RIGHT puts the control on the right
    # and the page title runs along the left.
    canvas.paste(mark, (HEADER[0] - mark.width - 10,
                        (HEADER[1] - mark.height) // 2))
    return canvas


def _wizard() -> Image.Image:
    """A flat blue band with the wordmark, and paper below it.

    Square edges and one heavy block of colour, following the chrome: the
    application has no gradients or rounded corners and its installer should not
    introduce any.
    """
    canvas = Image.new("RGB", WIZARD, PAPER)
    band = Image.new("RGB", (WIZARD[0], 168), BRAND_BLUE)
    canvas.paste(band, (0, 0))

    wordmark = _fit(_flatten(ASSETS / "wordmark-white.png"), WIZARD[0] - 32, 46)
    # The wordmark asset is white-on-transparent; flattening put paper behind
    # it, so it has to be re-composited onto the band instead.
    source = Image.open(ASSETS / "wordmark-white.png").convert("RGBA")
    box = source.getbbox()
    if box:
        source = source.crop(box)
    source = source.resize(wordmark.size, Image.LANCZOS)
    canvas.paste(source, ((WIZARD[0] - source.width) // 2, 62), mask=source)

    mark = _icon(96)
    canvas.paste(mark, ((WIZARD[0] - mark.width) // 2, 200))
    return canvas


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    for name, image in (("header.bmp", _header()), ("wizard.bmp", _wizard())):
        path = TARGET / name
        image.save(path, format="BMP")
        print(f"  {path.relative_to(ROOT)}  {image.width}x{image.height}  "
              f"{path.stat().st_size / 1024:.0f} kB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
