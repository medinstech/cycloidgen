"""The drive turning, as a looping GIF.

A still of a cycloidal drive is a picture of a shape.  What it cannot show - and
what no paragraph replaces - is the disc walking round the ring one pin at a
time while the output creeps forward, which is the reduction itself.  That is
the single most useful thing to put in a document or an issue, and the renderer
already produces the frames.

Two things decide whether the file is worth keeping.

**It has to loop.**  A GIF restarts whether or not the mechanism is back where
it started, and a mechanism that is not reads as a fault in the drive rather
than in the file.  What closes when is not obvious and it is not the same for
every part; :func:`loop` works it out exactly, in integers.

**It has to fit.**  Frames are cheap to render and expensive to store, and the
run that closes the loop is ``lobes / gcd(lobes, output_pin_count)`` input turns
- five for a 15:1, fifty-nine for a 59:1.  So there is a frame budget, and
:func:`loop` spends it on the run that comes closest to closing rather than on
the first one that fits.

GIF and not MP4: it plays in a browser, in a chat window, in a GitHub issue and
in a document, with nothing installed.  A video would be a fifth the size and
would need ffmpeg on the machine that writes it, which is a dependency this
project does not otherwise have.
"""
from __future__ import annotations

from collections.abc import Callable, Container, Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..core.spec import GearSpec
from ..report import plots

__all__ = [
    "VIEWS",
    "Animation",
    "Loop",
    "carrier_residual_deg",
    "frames",
    "loop",
    "plan",
    "write_gif",
]

#: What can be animated.  Both are the same simulation seen two ways - the
#: drawing carries the contacts and the forces, the assembly carries the shape.
VIEWS: tuple[str, ...] = ("drawing", "assembly")

#: Frame height as a fraction of its width, per view.  The drawing is a round
#: housing in a square; the assembly is a wide, shallow box seen at an angle.
_ASPECT = {"drawing": 1.0, "assembly": 0.72}

_DEFAULT_PIXELS = 480

#: Frames are sized in pixels and the figure is sized to match, so this only
#: decides how large the labels and line weights come out against the picture.
#: 100 is what the desktop canvases use, and the point of the exported frame is
#: that it looks like the one on screen.
_DPI = 100

#: Frames per input revolution.  The crank is what is being sampled and it is
#: the fastest thing in the picture - the disc turns at a lobe pitch per input
#: turn and the contacts walk one pin per input turn, both an order slower.
#: Eighteen puts a frame every twenty degrees of crank, which reads as turning
#: rather than stepping and is about what the live animation shows at 4x.
_FRAMES_PER_TURN = 18

#: Playback rate.  With the frame count above this runs the input at about 1.4
#: revolutions a second - fast enough to read as turning, slow enough to follow
#: one contact round the ring.
_FPS = 25

#: The budget.  Ten input turns at 480 px comes out around two megabytes, which
#: is about as much as a README or an issue will carry without complaint, and it
#: is also what decides the peak memory - see :func:`write_gif`.
_MAX_FRAMES = 180

#: Palette size, per view.  GIF holds 256 at most and the file is one LZW
#: stream, so every colour that is not needed is a longer code on every pixel
#: that is.  The drawing is eight inks and the antialiased blends between them,
#: and snapping those blends onto sixty-four entries takes a quarter off the
#: file with nothing visible lost.  The assembly is a shaded ramp per part and
#: bands if you try the same thing on it.
_COLOURS = {"drawing": 64, "assembly": 256}


@dataclass(frozen=True)
class Loop:
    """A run of whole input turns, and what is left over when it wraps."""

    turns: int
    #: How far the output carrier is from a position indistinguishable from its
    #: first one.  Zero means the frame after the last is the first, exactly.
    residual_deg: float

    @property
    def exact(self) -> bool:
        return self.residual_deg == 0.0


def carrier_residual_deg(spec: GearSpec, turns: int) -> float:
    """How far the output carrier misses closing after ``turns`` input turns.

    The carrier advances ``360/lobes`` per input turn and repeats itself every
    ``360/output_pin_count``, so after ``turns`` it stands at ``turns * pins /
    lobes`` hole pitches and what fails to close is the distance from there to
    the nearest whole pitch.

    Done in integers on purpose.  ``turns * pins % lobes`` is exactly zero when
    the loop really closes; the same arithmetic in degrees lands on 1e-14 and
    then nothing downstream can tell a closed loop from a nearly-closed one.
    """
    lobes, pins = spec.lobes, spec.output_pin_count
    r = (int(turns) * pins) % lobes
    return min(r, lobes - r) * 360.0 / (lobes * pins)


def loop(spec: GearSpec, *, max_turns: int) -> Loop:
    """The run of at most ``max_turns`` input turns that comes closest to closing.

    What closes when, and why it is not one answer:

    * The **disc**, the **ring contacts** and the **contact forces** close after
      a single input turn.  One turn walks the disc on by exactly one lobe
      pitch, and a profile with ``lobes`` lobes is unchanged by that rotation -
      so the drawing at 360 deg is the drawing at 0 deg, pin for pin.  This is
      why every candidate here is a *whole* number of turns.
    * The **output carrier**, its pins and the disc holes they run in, does not.
      It closes after ``lobes / gcd(lobes, output_pin_count)`` turns and no
      sooner: five for the 15:1 preset, seven for the 21:1, fifty-nine for the
      59:1.
    * The **trace** overlay follows one material point on the rim and closes
      only after a whole output revolution - ``lobes`` turns - so a GIF with the
      trace on and fewer turns than that has a dot that jumps.  The path it
      draws is static and does not.

    When the exact period does not fit the budget the choice is not obvious, and
    the obvious answer is wrong.  Any whole turn count leaves the disc closed,
    so the run to pick is the one whose *carrier* lands closest to a hole pitch
    - which is rarely the longest one that fits.  At 29:1 on six output pins,
    five turns leaves 2.1 deg and ten leaves 4.1; at 59:1, ten leaves 1.0 deg,
    a step small enough that nothing in the picture reads as a jump.
    """
    limit = max(1, int(max_turns))
    turns = min(range(1, limit + 1),
                key=lambda t: (carrier_residual_deg(spec, t), t))
    return Loop(turns, carrier_residual_deg(spec, turns))


@dataclass(frozen=True)
class Animation:
    """Everything about the file, decided before a pixel of it is rendered.

    Separate from the writing for the same reason the export manifest is
    separate from the exporter: what it will cost and whether it will loop are
    worth knowing *before* several seconds of rendering, and both the desktop
    app and the command line want to say so.
    """

    view: str
    turns: int
    frames: int
    fps: int
    #: What the frames are *asked* for.  The renderer can land a pixel short of
    #: it - see :func:`write_gif` - so it is a request, not a guarantee.
    size: tuple[int, int]
    residual_deg: float

    @property
    def seconds(self) -> float:
        return self.frames / self.fps

    @property
    def exact(self) -> bool:
        return self.residual_deg == 0.0

    def crank(self, index: int) -> float:
        """Crank angle of frame ``index``, in degrees.

        The last frame stops one step *short* of the wrap.  Frame zero is the
        wrap, and a loop that ends on a copy of its own first frame holds still
        for one frame every time round.
        """
        return 360.0 * self.turns * index / self.frames

    def describe(self) -> str:
        close = ("loops exactly" if self.exact else
                 f"carrier {self.residual_deg:.1f} deg short at the wrap")
        return (f"{self.turns} input turn(s), {self.frames} frames at "
                f"{self.fps} fps - {self.seconds:.1f} s, "
                f"{self.size[0]}x{self.size[1]} px, {close}")


def plan(spec: GearSpec, *, view: str = "drawing", pixels: int = _DEFAULT_PIXELS,
         fps: int = _FPS, turns: int | None = None,
         frames: int | None = None) -> Animation:
    """Decide the shape of the animation for ``spec``.

    ``turns`` and ``frames`` override the defaults and are not second-guessed:
    a caller who asks for fifty-nine turns gets them, budget or no budget.
    """
    if view not in VIEWS:
        raise ValueError(f"unknown view {view!r}; choose from {', '.join(VIEWS)}")
    if turns is None:
        chosen = loop(spec, max_turns=max(1, _MAX_FRAMES // _FRAMES_PER_TURN))
    else:
        if int(turns) < 1:
            raise ValueError("an animation needs at least one input turn")
        chosen = Loop(int(turns), carrier_residual_deg(spec, int(turns)))

    count = int(frames) if frames is not None else chosen.turns * _FRAMES_PER_TURN
    if count < 2:
        raise ValueError("an animation needs at least two frames")

    width = int(pixels)
    height = max(2 * round(width * _ASPECT[view] / 2), 2)
    return Animation(view=view, turns=chosen.turns, frames=count, fps=int(fps),
                     size=(width, height), residual_deg=chosen.residual_deg)


# ---------------------------------------------------------------------- frames


def _canvas(size: tuple[int, int]):
    """A figure sized in pixels, with an Agg canvas already attached.

    Attached before anything is drawn on it: ``tight_layout`` needs a renderer,
    and a figure that acquires its canvas afterwards has already laid itself
    out against a default one.
    """
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    width, height = size
    fig = Figure(figsize=(width / _DPI, height / _DPI), dpi=_DPI)
    return fig, FigureCanvasAgg(fig)


def _rgb(canvas) -> np.ndarray:
    """Draw and take the pixels.

    Copied out.  ``buffer_rgba`` is a view of the renderer's own buffer, which
    the next frame draws straight over - hand it on without copying and every
    frame of the file ends up being the last one.
    """
    canvas.draw()
    return np.asarray(canvas.buffer_rgba())[..., :3].copy()


def frames(spec: GearSpec, animation: Animation, *,
           overlays: plots.Overlays | None = None,
           explode: float = 0.0, azimuth: float = 38.0, elevation: float = 26.0,
           hidden: Container[str] = (),
           progress: Callable[[int, int], None] | None = None,
           ) -> Iterator[np.ndarray]:
    """Every frame in order, each an ``(h, w, 3)`` uint8 array.

    The drawing is built once and *moved* - :class:`~cycloidgen.report.plots.
    ProfileView` exists for exactly this - so a frame costs a redraw rather than
    a rebuild.  The assembly re-projects the cached mesh, and its camera is
    fitted to hold the whole drive at any crank angle, so the view does not
    breathe from frame to frame.
    """
    fig, canvas = _canvas(animation.size)
    if animation.view == "drawing":
        view = plots.ProfileView(fig)
        view.set_design(spec, overlays=overlays or plots.Overlays())
        for i in range(animation.frames):
            view.set_crank(animation.crank(i))
            yield _rgb(canvas)
            if progress is not None:
                progress(i + 1, animation.frames)
        return

    for i in range(animation.frames):
        plots.assembly_figure(spec, fig, crank_deg=animation.crank(i),
                              explode=explode, azimuth=azimuth,
                              elevation=elevation, hidden=hidden,
                              pixels=animation.size[0])
        yield _rgb(canvas)
        if progress is not None:
            progress(i + 1, animation.frames)


# ----------------------------------------------------------------------- write


def write_gif(spec: GearSpec, path: str | Path, *,
              animation: Animation | None = None,
              overlays: plots.Overlays | None = None,
              theme: str = "print",
              explode: float = 0.0, azimuth: float = 38.0, elevation: float = 26.0,
              hidden: Container[str] = (),
              progress: Callable[[int, int], None] | None = None) -> Path:
    """Write the animation for ``spec`` to ``path``, and return where it landed.

    ``theme`` defaults to the print surface, the same white the PDF is drawn on:
    an exported file outlives the appearance setting that happened to be on when
    it was made, and a document is not a dark-mode window.  The desktop app
    passes its own mode, because there the file is what you were just looking
    at.

    One palette for the whole file, and no dithering.  Both of Pillow's defaults
    are wrong here and in the same direction: left alone it picks a fresh set of
    colours for every frame, which on flat fills reads as the paper quietly
    shifting hue as it plays, and it dithers, which scatters a flat background
    into two-value noise that no LZW stream can compress and that nothing needs
    - this is eight inks, not a photograph.

    The whole run is stacked into one tall image and quantised once.  The
    obvious alternative - take a palette off the first frame and map the rest
    onto it with ``Image.quantize`` - streams instead of holding the frames, and
    is wrong: that path is a five-bit colour-cube lookup, not a nearest-colour
    match, and it puts pure white on a *near*-white entry.  The first frame,
    quantised properly, then keeps a background the other ninety do not, and the
    paper flashes once a loop.  Quantising the run together also chooses the
    palette over every frame rather than over one, so a colour that only appears
    half way through is represented.  It costs holding the frames: about 60 MB
    at the default size, 125 MB for the longest run.
    """
    from PIL import Image

    animation = animation or plan(spec)
    path = Path(path).with_suffix(".gif")
    path.parent.mkdir(parents=True, exist_ok=True)
    stack = width = height = None

    with plots.using_theme(theme):
        for i, frame in enumerate(
                frames(spec, animation, overlays=overlays, explode=explode,
                       azimuth=azimuth, elevation=elevation, hidden=hidden,
                       progress=progress)):
            if stack is None:
                # Sized from the first frame rather than from the plan.
                # matplotlib takes a figure size in inches and turns it back
                # into pixels as `int(inches * dpi)`, and 1.16 is not exactly
                # representable - so a request for 116 px comes back as 116 on
                # one version and 115 on another.  Every frame agrees with
                # every other, which is the part that matters; the plan's size
                # is a request, good to within a pixel.
                height, width = frame.shape[:2]
                stack = np.empty((animation.frames * height, width, 3), np.uint8)
            stack[i * height:(i + 1) * height] = frame

    indexed = Image.fromarray(stack).convert(
        "P", palette=Image.Palette.ADAPTIVE, colors=_COLOURS[animation.view],
        dither=Image.Dither.NONE)
    del stack
    pages = [indexed.crop((0, i * height, width, (i + 1) * height))
             for i in range(animation.frames)]
    del indexed
    pages[0].save(path, save_all=True, append_images=pages[1:], optimize=True,
                  duration=round(1000 / animation.fps), loop=0)
    return path
