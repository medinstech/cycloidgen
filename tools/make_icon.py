"""Draw the application icon: the disc, from the equation the application cuts it with.

    python tools/make_icon.py
    python tools/make_icon.py --preview     # ...and a sheet to look at it on

Until now the icon was the company mark, which says who wrote the program and
nothing about what it does.  This draws the thing itself - an outline straight
out of :func:`cycloidgen.core.profile.disc_profile`, the same call the STEP
export and the drawing use, so the icon cannot drift from the geometry: change
the profile and the icon changes with it.  Nothing is traced by hand, and the
pin radius is taken as a fraction of :func:`critical_radius` so the lobes drawn
here are a disc that could actually be cut rather than a flower.

Unlike the brand assets this needs no masters and no licence - it is arithmetic
and Pillow - so it can be re-run by anyone, and the results are committed for
the same reason theirs are: the build must not depend on running it.

Each size in the .ico is *drawn* at that size rather than resampled down from
one master.  A 256 px disc with nine lobes and six output holes reduced to 16 px
is grey soup; at 16 px this drops the holes and thickens what is left, which is
what the icon is for at that size - a shape you recognise in a task bar.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:                    # runnable without installing
    sys.path.insert(0, str(ROOT))

from cycloidgen.core.profile import critical_radius, disc_profile  # noqa: E402

TARGET = ROOT / "cycloidgen" / "ui" / "assets"

#: Kept in step with `cycloidgen.ui.branding` by `tests/test_branding.py`, not
#: by memory.  Imported from there instead, and this tool would need Qt to draw
#: a PNG.
BRAND_BLUE = "#0d00ff"
BRAND_PAPER = "#f6f5ff"

#: What Windows shows in the title bar and the task bar (16, 32), what the shell
#: uses in its larger views, and 256 for everything high-DPI.
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)

#: Drawn this many times over and resampled down - Pillow has no antialiasing of
#: its own, and a lobe boundary is a curve.  8x at 256 is 2048 px, which is
#: nothing to a one-off tool and is the difference between an edge and a staircase.
SUPERSAMPLE = 8

# ------------------------------------------------------------------ geometry --


@dataclass(frozen=True)
class Grade:
    """How the disc is drawn at one range of sizes.

    A typeface cut for six point is not the eleven point cut scaled down - it
    is drawn with a larger eye and heavier strokes, because ink and eyes do not
    scale.  Neither do pixels.  These are the same disc at every size and not
    the same numbers: as the icon gets smaller the lobes get fewer and deeper
    and the holes come out, because what has to survive is the shape, and a
    faithful nine-lobe disc at 16 px is a circle with a rumour of lobes on it.
    """

    lobes: int
    #: ``k1 = E*(N+1)/R``, the profile's own dimensionless group: it sets how
    #: deep the lobes are and nothing else, and at 1.0 the locus cusps.  Even
    #: the largest value here is deeper than a reducer would really run - they
    #: sit near 0.4-0.6, because deep lobes cost contact ratio.
    k1: float
    #: Pin radius, as a fraction of the largest one the profile tolerates
    #: before it folds on itself.  Rounds the valleys; well under 1 keeps the
    #: flanks straight enough to read as teeth rather than as scallops.
    rr: float
    #: The disc across the tile.  A mark that touches its own edge looks
    #: cropped, so there is always some tile left around it - less of it small,
    #: where every pixel of disc counts.
    span: float
    #: Input bore, as a fraction of the disc's outer radius.
    bore: float
    #: Output roller holes, and where they sit.  Zero below the size at which a
    #: hole is two pixels of grey rather than a hole.
    holes: int = 0
    hole_circle: float = 0.60
    hole_radius: float = 0.12


#: Smallest size each grade is for, largest first; the first one that fits wins.
GRADES: tuple[tuple[int, Grade], ...] = (
    (48, Grade(lobes=8, k1=0.62, rr=0.50, span=0.80, bore=0.26,
               holes=6, hole_radius=0.115)),
    (32, Grade(lobes=8, k1=0.70, rr=0.48, span=0.82, bore=0.27,
               holes=6, hole_radius=0.125)),
    (24, Grade(lobes=7, k1=0.78, rr=0.45, span=0.84, bore=0.30)),
    (20, Grade(lobes=6, k1=0.85, rr=0.40, span=0.86, bore=0.32)),
    (0, Grade(lobes=6, k1=0.92, rr=0.35, span=0.90, bore=0.34)),
)

#: The tile's corner.  Between a Windows tile and a macOS squircle, which is
#: where both look deliberate rather than like a failed impression of the other.
CORNER = 0.235


def grade_for(size: int) -> Grade:
    return next(g for floor, g in GRADES if size >= floor)


def disc_geometry(lobes: int, k1: float, rr_fraction: float) -> tuple[float, float]:
    """The eccentricity and pin radius one grade asks for, at unit R."""
    ecc = k1 / (lobes + 1)
    return ecc, rr_fraction * critical_radius(1.0, ecc, lobes)


def disc_points(lobes: int, k1: float, rr_fraction: float, samples: int = 2048,
                *, upright: bool = True) -> np.ndarray:
    """The profile, in units of its own outer radius, one lobe pointing up.

    Returned as a closed polygon: at these sizes a polygon *is* the curve - 2048
    samples put the chord error below a hundredth of a pixel even at 2048 px.

    ``upright`` is the only liberty taken with it, and it is a rotation: whether
    a crest lands on the vertical axis is up to the lobe count's parity, and an
    icon whose axis of symmetry is a degree and a half off looks like a
    screenshot of a mesh rather than a drawn mark.
    """
    ecc, pin = disc_geometry(lobes, k1, rr_fraction)
    t = np.linspace(0.0, 2.0 * np.pi, samples, endpoint=False)
    pts = disc_profile(t, 1.0, pin, ecc, lobes)
    r = np.hypot(pts[:, 0], pts[:, 1])
    pts = pts / r.max()
    return _upright(pts) if upright else pts


def _upright(pts: np.ndarray) -> np.ndarray:
    """Turn the tallest point to straight up.

    Found rather than assumed: ``t = 0`` is a valley, and which sample carries
    the crest moves with the lobe count.
    """
    r = np.hypot(pts[:, 0], pts[:, 1])
    crest = pts[int(np.argmax(r))]
    turn = np.pi / 2.0 - np.arctan2(crest[1], crest[0])
    rot = np.array([[np.cos(turn), -np.sin(turn)],
                    [np.sin(turn), np.cos(turn)]])
    return pts @ rot.T


# ------------------------------------------------------------------ drawing --


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _gradient(size: int, top: str, bottom: str) -> Image.Image:
    """A vertical wash, light at the top, the way a solid object is lit.

    Flat fill at this scale reads as a swatch; two stops one step apart read as
    a surface, and are still one colour at 16 px.
    """
    a, b = np.array(_rgb(top), float), np.array(_rgb(bottom), float)
    ramp = np.linspace(0.0, 1.0, size)[:, None]
    rows = (a + (b - a) * ramp).round().astype(np.uint8)
    return Image.fromarray(np.repeat(rows[:, None, :], size, axis=1), "RGB")


def _disc_mask(size: int, grade: Grade) -> Image.Image:
    """The disc, punched: white is disc, black is whatever is behind it."""
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)

    span = grade.span * size / 2.0
    centre = size / 2.0
    pts = disc_points(grade.lobes, grade.k1, grade.rr)
    # Screen y grows downward; flipping it keeps the drawn disc the same way up
    # as the profile plotted in the application.
    draw.polygon([(centre + x * span, centre - y * span) for x, y in pts], fill=255)

    def punch(cx: float, cy: float, r: float) -> None:
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=0)

    punch(centre, centre, grade.bore * span)
    for i in range(grade.holes):
        # Offset half a step so a hole sits under a valley rather than thinning
        # the web behind a crest - which is also where a real one goes, and is
        # why it looks right.
        angle = 2.0 * np.pi * (i + 0.5) / grade.holes
        punch(centre + grade.hole_circle * span * np.cos(angle),
              centre - grade.hole_circle * span * np.sin(angle),
              grade.hole_radius * span)
    return mask


def render(size: int, *, tile: bool = True) -> Image.Image:
    """One icon, drawn at ``size`` px rather than resampled down to it."""
    s = size * SUPERSAMPLE
    mask = _disc_mask(s, grade_for(size))

    if tile:
        # Brand blue tile, disc cut out of it in paper: the tile carries the
        # contrast, so the icon is legible on a light task bar and a dark one
        # without a second asset and without an outline to fake it.
        canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        blue = _gradient(s, "#2a1cff", BRAND_BLUE).convert("RGBA")
        paper = Image.new("RGBA", (s, s), (*_rgb(BRAND_PAPER), 255))
        blue.paste(paper, (0, 0), mask)

        corner = Image.new("L", (s, s), 0)
        ImageDraw.Draw(corner).rounded_rectangle([0, 0, s - 1, s - 1],
                                                radius=CORNER * s, fill=255)
        canvas.paste(blue, (0, 0), corner)
    else:
        # No tile: the disc alone, in brand blue, holes to nothing.
        canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        canvas.paste(Image.new("RGBA", (s, s), (*_rgb(BRAND_BLUE), 255)), (0, 0), mask)

    return canvas.resize((size, size), Image.LANCZOS)


# -------------------------------------------------------------------- output --


def _preview(path: Path, *, tile: bool = True) -> None:
    """Every size, on both surfaces it will actually be shown against."""
    sizes = ICON_SIZES
    pad, gap = 24, 20
    row = sum(sizes) + gap * len(sizes)
    sheet = Image.new("RGB", (row + pad * 2, 256 + 256 + pad * 3), (255, 255, 255))
    ImageDraw.Draw(sheet).rectangle([0, 256 + pad * 2, sheet.width, sheet.height],
                                    fill=(24, 24, 27))
    for top in (pad, 256 + pad * 2):               # paper, then a dark task bar
        x = pad
        for size in sizes:
            icon = render(size, tile=tile)
            sheet.paste(icon, (x, top + (256 - size) // 2), icon)
            x += size + gap
    sheet.save(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", type=Path, nargs="?",
                        const=ROOT / "build" / "icon-preview.png",
                        help="also write a contact sheet of every size, light and dark")
    parser.add_argument("--bare", action="store_true",
                        help="draw the disc alone instead of on a brand tile")
    parser.add_argument("--out", type=Path, default=TARGET,
                        help="where the assets go; defaults to the package")
    args = parser.parse_args()
    tile = not args.bare

    args.out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    # The .ico is a container of images, not an image, so each size goes in as
    # itself.  Pillow's `sizes=` argument would resample one of them into the
    # rest, which is the thing this tool exists to avoid.
    frames = [render(size, tile=tile) for size in ICON_SIZES]
    ico = args.out / "cycloidgen.ico"
    frames[-1].save(ico, format="ICO", sizes=[(s, s) for s in ICON_SIZES],
                    append_images=frames[:-1])
    written.append(ico)

    # PNGs for the platforms that cannot read an .ico: 256 is what the Linux
    # desktops' hicolor tree asks for, 1024 is the master the macOS .icns is
    # built from - and it has to exist at 1024, or the Dock shows a 256 blown up.
    for size in (256, 1024):
        path = args.out / f"icon-{size}.png"
        render(size, tile=tile).save(path, optimize=True)
        written.append(path)

    if args.preview:
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        _preview(args.preview, tile=tile)
        written.append(args.preview)

    for path in written:
        print(f"  {path.relative_to(ROOT) if ROOT in path.parents else path}  "
              f"{path.stat().st_size / 1024:.0f} kB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
