"""The exported animation, and whether it actually loops.

A GIF restarts whether or not the mechanism is back where it started, so the
one claim worth testing is the one the eye would otherwise have to judge: that
the frame after the last frame *is* the first frame.  That is checked against
rendered pixels rather than against the arithmetic that chose the run length,
because the arithmetic is the thing most likely to be wrong.
"""
from __future__ import annotations

import math

import matplotlib
import numpy as np
import pytest

matplotlib.use("Agg")

from PIL import Image

from cycloidgen.core.spec import GearSpec, preset
from cycloidgen.export import animation, manifest
from cycloidgen.report import plots


@pytest.fixture(scope="module")
def spec():
    s = preset(15)
    s.disc_count = 2
    return s


def _frame(spec: GearSpec, size: tuple[int, int], crank: float) -> np.ndarray:
    """One frame at an arbitrary angle, through exactly the export's path."""
    fig, canvas = animation._canvas(size)
    with plots.using_theme("print"):
        view = plots.ProfileView(fig)
        view.set_design(spec, overlays=plots.Overlays())
        view.set_crank(crank)
        return animation._rgb(canvas)


# ------------------------------------------------------------------- the loop


def test_the_carrier_residual_is_exactly_zero_only_on_the_real_period():
    """The period is ``lobes / gcd(lobes, output_pin_count)`` and nothing shorter."""
    for lobes, pins in ((15, 6), (21, 6), (29, 6), (12, 6), (11, 5), (24, 8)):
        s = GearSpec(lobes=lobes, output_pin_count=pins)
        period = lobes // math.gcd(lobes, pins)
        closes = [t for t in range(1, 2 * period + 1)
                  if animation.carrier_residual_deg(s, t) == 0.0]
        assert closes == [period, 2 * period]


def test_a_generous_budget_buys_the_exact_period():
    s = preset(21)                                    # period 7 turns on 6 pins
    chosen = animation.loop(s, max_turns=20)
    assert chosen.turns == 7
    assert chosen.exact


def test_a_tight_budget_takes_the_closest_run_and_not_the_longest():
    """The obvious answer - as many turns as fit - is the wrong one.

    A 29:1 on six output pins closes only after 29 turns.  Under a ten-turn
    budget, five turns leaves the carrier 2.1 deg out and ten leaves it 4.1,
    so the shorter run is also the better loop.
    """
    s = preset(29)
    chosen = animation.loop(s, max_turns=10)
    assert chosen.turns == 5
    assert not chosen.exact
    assert chosen.residual_deg < animation.carrier_residual_deg(s, 10)
    assert chosen.residual_deg == pytest.approx(2.069, abs=1e-3)


def test_every_preset_gets_a_loop_inside_the_frame_budget():
    for ratio in (10, 15, 21, 29, 39, 59):
        plan = animation.plan(preset(ratio))
        assert 2 <= plan.frames <= animation._MAX_FRAMES
        assert plan.residual_deg <= 360.0 / preset(ratio).lobes
        assert plan.seconds > 1.0


def test_the_frames_stop_one_step_short_of_the_wrap():
    """Frame zero is the wrap.  Ending on a copy of it stutters once a loop."""
    plan = animation.plan(preset(15))
    assert plan.crank(0) == 0.0
    assert plan.crank(plan.frames) == 360.0 * plan.turns
    assert plan.crank(plan.frames - 1) < 360.0 * plan.turns


def test_the_drawing_really_is_back_where_it_started(spec):
    """Pixels, not arithmetic.

    ``preset(15)`` closes exactly at five turns, so the frame one step past the
    last one has to be indistinguishable from the first - every disc, every
    output pin, every contact and every force arrow.

    Everything except the readout, which is a count of how far the run has gone
    rather than a part of the mechanism, and restarts with the loop.  So the
    test is the sharper one: what differs is *only* the readout, and it lives in
    the bottom tenth of the frame.
    """
    plan = animation.plan(spec, pixels=240)
    assert plan.exact
    first = _frame(spec, plan.size, 0.0)
    wrapped = _frame(spec, plan.size, 360.0 * plan.turns)

    height = first.shape[0]
    mechanism = int(0.85 * height)                    # everything above the readout
    moved = np.flatnonzero((first != wrapped).any(axis=(1, 2)))
    assert moved.size, "the readout should have advanced"
    assert moved.min() >= mechanism
    assert np.array_equal(first[:mechanism], wrapped[:mechanism])


def test_one_input_turn_closes_the_disc_but_not_the_carrier(spec):
    """The claim the run length rests on, from both sides."""
    size = (240, 240)
    assert animation.carrier_residual_deg(spec, 1) > 0.0
    assert not np.array_equal(_frame(spec, size, 0.0),
                              _frame(spec, size, 360.0))


# ----------------------------------------------------------------- the file


@pytest.fixture(scope="module")
def written(spec, tmp_path_factory):
    path = tmp_path_factory.mktemp("gif") / "motion.gif"
    plan = animation.plan(spec, pixels=180, frames=8)
    return animation.write_gif(spec, path, animation=plan), plan


def test_the_gif_has_the_frames_the_plan_promised(written):
    path, plan = written
    with Image.open(path) as im:
        assert im.n_frames == plan.frames
        # Size to within a pixel: matplotlib turns the figure size back into
        # pixels as int(inches * dpi) and which side of the rounding it lands
        # on depends on the version.  What has to be exact is that every frame
        # agrees, and the format enforces that.
        assert abs(im.size[0] - plan.size[0]) <= 1
        assert abs(im.size[1] - plan.size[1]) <= 1
        assert im.info["loop"] == 0                   # 0 is "for ever"
        assert im.info["duration"] == round(1000 / plan.fps)


def test_a_renderer_that_lands_a_pixel_short_still_writes(spec, tmp_path,
                                                          monkeypatch):
    """The frame buffer is the authority on its own size, not the plan.

    Sizing the stack from the plan crashed on exactly one of the three CI
    configurations - the one whose matplotlib truncated 1.16 x 100 to 115 -
    which is the worst way for this to be wrong: it works everywhere it is
    developed. So the shortfall is simulated rather than waited for.
    """
    real = animation._canvas
    monkeypatch.setattr(animation, "_canvas",
                        lambda size: real((size[0], size[1] - 1)))

    plan = animation.plan(spec, pixels=140, frames=4)
    path = animation.write_gif(spec, tmp_path / "short.gif", animation=plan)
    with Image.open(path) as im:
        assert im.size == (140, 139)
        assert im.n_frames == 4


def _played(path) -> list[np.ndarray]:
    """Every frame as it is actually seen, composited in playback order."""
    with Image.open(path) as im:
        frames = []
        for i in range(im.n_frames):
            im.seek(i)
            frames.append(np.asarray(im.convert("RGB")))
    return frames


def test_the_frames_are_not_all_the_same_picture(written):
    """A writer that renders one frame and repeats it would pass everything else."""
    frames = _played(written[0])
    assert not any(np.array_equal(frames[0], f) for f in frames[1:])


def test_the_background_does_not_shift_as_it_plays(written):
    """What one palette for the whole file buys.

    Left to itself Pillow picks a fresh set of 256 colours per frame, and on
    flat fills that reads as the paper quietly changing hue under the drawing.
    """
    corners = {tuple(f[0, 0]) for f in _played(written[0])}
    assert corners == {(255, 255, 255)}               # the print surface


def test_the_assembly_view_renders_too(spec, tmp_path):
    plan = animation.plan(spec, view="assembly", pixels=160, frames=4)
    assert plan.size[1] < plan.size[0]                # wide, not square
    path = animation.write_gif(spec, tmp_path / "assembly", animation=plan,
                               hidden={"housing"})
    assert path.suffix == ".gif"
    with Image.open(path) as im:
        assert im.n_frames == 4


def test_an_unknown_view_is_refused(spec):
    with pytest.raises(ValueError, match="unknown view"):
        animation.plan(spec, view="isometric")


def test_progress_is_reported_once_per_frame(spec, tmp_path):
    seen: list[tuple[int, int]] = []
    plan = animation.plan(spec, pixels=120, frames=5)
    animation.write_gif(spec, tmp_path / "m.gif", animation=plan,
                        progress=lambda done, total: seen.append((done, total)))
    assert seen == [(i, 5) for i in range(1, 6)]


def test_a_cancelled_render_stops_asking_for_frames(spec, tmp_path):
    """What the desktop app's Cancel button does: raise out of the generator."""
    def stop(done: int, _total: int) -> None:
        if done == 2:
            raise InterruptedError

    plan = animation.plan(spec, pixels=120, frames=20)
    with pytest.raises(InterruptedError):
        animation.write_gif(spec, tmp_path / "m.gif", animation=plan,
                            progress=stop)


# --------------------------------------------------------------- the manifest


def test_the_animation_is_a_declared_output_with_a_writer(spec, tmp_path):
    from cycloidgen.export import _write

    out = next(o for o in manifest.MANIFEST if o.key == "gif")
    assert out.group in manifest.group_keys()
    assert out.files(spec) == ["motion.gif"]
    assert [p.name for p in _write(out, spec, tmp_path, None)] == ["motion.gif"]


def test_the_theme_is_borrowed_and_given_back():
    plots.set_theme("dark")
    try:
        with plots.using_theme("print"):
            assert plots.theme() is plots._THEMES["print"]
        assert plots.theme() is plots._THEMES["dark"]
        with pytest.raises(ValueError, match="unknown theme"), \
                plots.using_theme("sepia"):
            pass
        assert plots.theme() is plots._THEMES["dark"]
    finally:
        plots.set_theme("light")


def test_a_theme_changed_underneath_is_left_alone():
    """A worker restoring what it found would undo a decision made since."""
    plots.set_theme("light")
    try:
        with plots.using_theme("print"):
            plots.set_theme("dark")                   # the user, mid-render
        assert plots.theme() is plots._THEMES["dark"]
    finally:
        plots.set_theme("light")
