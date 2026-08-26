"""Matplotlib figures shared by the desktop preview and the PDF report.

Colour comes from the validated reference palette, first three categorical slots.
Both modes are selected rather than flipped: the dark column is the same three
hues re-stepped for the dark surface, and both sets clear the all-pairs CVD and
normal-vision floors.  Every bar also carries a visible value label, which is
what the light-mode aqua contrast warning requires.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure
from matplotlib.patches import Circle, Polygon

from ..core import profile as prof
from ..core.kinematics import contacts, ring_stage_period, sweep, to_world
from ..core.spec import GearSpec, OutputMember
from ..units import unit as _unit_for

__all__ = [
    "Overlays",
    "ProfileView",
    "assembly_figure",
    "force_figure",
    "light_theme",
    "loss_figure",
    "placeholder_figure",
    "print_theme",
    "profile_figure",
    "set_theme",
    "set_units",
    "style_axes",
    "sweep_figure",
    "theme",
    "using_theme",
]

#: The three series are the same in every mode and are **not** re-tuned to the
#: surface.  Their contrast against the paper is only part of the job; the rest
#: is telling them apart, and that rests on their *lightness* being spread out,
#: so a reader who cannot separate the hues still can.  Darkening them all onto
#: a common contrast target closes that spread - it takes the orange and green
#: from 1.14:1 apart to 1.01:1, which is the same grey - and buys nothing a
#: labelled bar does not already provide.
_SERIES_LIGHT = ("#2a78d6", "#eb6834", "#1baf7a")
_SERIES_DARK = ("#3987e5", "#d95926", "#199e70")

_THEMES = {
    # In the window a figure sits inside a panel, so it takes the panel's tone
    # rather than a white one: a white slab inside a tinted window is exactly
    # what following the theme is supposed to prevent.
    "light": {
        "surface": "#f5f5ff", "ink": "#0b0a1c", "ink2": "#4a4763",
        "muted": "#8f8da6", "grid": "#dedcf0",
        "series": _SERIES_LIGHT,
    },
    "dark": {
        "surface": "#232322", "ink": "#ffffff", "ink2": "#c3c2b7",
        "muted": "#7a7973", "grid": "#3a3a36",
        "series": _SERIES_DARK,
    },
    # The report is a print document: white paper, no tint to pay for in ink.
    "print": {
        "surface": "#ffffff", "ink": "#0b0b0b", "ink2": "#52514e",
        "muted": "#9a9994", "grid": "#e6e5e1",
        "series": _SERIES_LIGHT,
    },
}

_mode = "light"

#: What lengths in a figure's own labels are shown in.  Module state for the
#: same reason the theme is: a figure bakes its text in at draw time and every
#: figure in one window has to agree.  The PDF forces millimetres - see
#: :func:`print_theme` - because a document you hand to someone should not carry
#: the units the person who exported it happened to prefer.
_units = "mm"


def set_units(key: str) -> None:
    """Select the unit lengths are labelled in.  Affects figures built after."""
    global _units
    _units = key


def set_theme(mode: str) -> None:
    """Select ``"light"`` or ``"dark"``.  Affects every figure built afterwards."""
    global _mode
    if mode not in _THEMES:
        raise ValueError(f"unknown theme {mode!r}")
    _mode = mode


def theme() -> dict:
    return _THEMES[_mode]


@contextmanager
def using_theme(mode: str):
    """Draw on ``mode``'s surface for the duration, then put it back.

    The theme is module state because a figure bakes its colours in at draw
    time and every figure in one window has to agree.  Anything that wants a
    *different* surface for one job - the PDF, an exported animation - borrows
    it rather than setting it, so a failure part way through cannot leave the
    application painting on the wrong paper.

    It puts back what it found only if that is still what it left.  A borrowed
    theme can outlive a real one: the animation renders on a worker thread, and
    a user who switches appearance while it runs has made a decision that
    restoring the old value would silently undo.
    """
    global _mode
    if mode not in _THEMES:
        raise ValueError(f"unknown theme {mode!r}")
    previous, _mode = _mode, mode
    try:
        yield
    finally:
        if _mode == mode:
            _mode = previous


@contextmanager
def print_theme():
    """Force the print surface, then restore whatever the UI was using.

    Separate from ``light`` on purpose.  The application's light mode is tinted
    paper so that figures match the panels around them; a PDF is a print
    document and gets white, because a tint on every figure is ink someone pays
    for and gains nothing on paper.
    """
    global _units
    previous, _units = _units, "mm"
    try:
        with using_theme("print"):
            yield
    finally:
        if _units == "mm":
            _units = previous


#: Kept for callers written against the old name.
light_theme = print_theme


def style_axes(ax, *, grid: bool = True) -> None:
    """Recessive axes: no box, faint grid, secondary-ink labels."""
    t = theme()
    ax.set_facecolor(t["surface"])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(t["grid"])
    ax.tick_params(colors=t["ink2"], labelsize=8, length=3, width=0.8)
    if grid:
        ax.grid(True, color=t["grid"], linewidth=0.7, zorder=0)
        ax.set_axisbelow(True)
    for axis in (ax.xaxis, ax.yaxis):
        axis.label.set_color(t["ink2"])
        axis.label.set_fontsize(9)


#: Below this share of the worst force in the sweep, a contact is not drawn.
#: Two pins are at the load reversal at any moment and their moment arms pass
#: through zero there, which comes out of the arithmetic as +-1e-13 depending on
#: how the crank angle was reached - so ``force > 0`` makes a dot appear for a
#: force of a ten-thousandth of a micronewton, and makes the count of pins
#: carrying flicker by one as the crank goes past.  It is also what stopped the
#: exported animation from closing: the same pose, reached from crank 0 and from
#: crank 1800, rounded opposite ways.
_CONTACT_FLOOR = 1e-9

#: Point size of the two caption lines under the drawing.  Named because the
#: strip reserved for them is computed from it, and a size changed in one place
#: and not the other is a caption that overlaps the thing it describes again.
_CAPTION_PT = 8.5


def _circle(x, y, r, color, lw, dashed: bool = False, alpha: float = 1.0) -> Circle:
    return Circle((x, y), r, fill=False, edgecolor=color, linewidth=lw,
                  linestyle=(0, (4, 3)) if dashed else "solid", alpha=alpha, zorder=2)


@dataclass(frozen=True)
class Overlays:
    """What the drawing shows beyond the outlines.

    Everything here is off the same kinematics the checks and the datasheet use,
    so the picture and the numbers cannot tell different stories.  They are
    toggles because a 60-pin drive with every overlay on is unreadable, and
    which one you want depends on what you are looking for.
    """

    contacts: bool = True        # where the disc actually touches the ring pins
    forces: bool = True          # and how hard, to scale
    trace: bool = False          # the path a point on the disc rim travels
    labels: bool = False         # ring pin numbers


class ProfileView:
    """The drawing, built once and then *moved*.

    The first version rebuilt every artist for every animation frame - a couple
    of hundred patches, a fresh axes, and a ``tight_layout`` pass - which is
    most of a hundred milliseconds against a 40 ms timer, so the animation ran
    at whatever rate matplotlib could manage rather than the one it was asked
    for.  Nothing about the geometry needs rebuilding when only the crank angle
    moves: the artists are created when the *design* changes and repositioned
    when the *angle* does.
    """

    def __init__(self, fig: Figure | None = None) -> None:
        self.figure = fig or Figure(figsize=(6.2, 6.2), dpi=110)
        self._spec: GearSpec | None = None
        self._reference: GearSpec | None = None
        self._overlays = Overlays()
        self._crank = 0.0
        self._ring_pins: list = []
        self._pin_labels: list = []
        # `tight_layout` solves for the figure size it is run at and writes the
        # answer down as *fractions*.  Embedded in a window the figure is then
        # resized under it, and a fraction that reserved enough room for the
        # title at build time reserves fewer pixels as the panel gets shorter -
        # the drawing panel is a letterbox, 973x271 on a 1560-wide window, where
        # the build-time 0.94 leaves the title 16 px and it needs 22.  So the
        # title was cut in half by the top of the panel, on the one figure the
        # README leads with.
        #
        # Re-solved on resize rather than on every draw: a layout engine would
        # put a `tight_layout` pass back into each animation frame, which is
        # most of what this class exists to have removed.  Resizes are rare and
        # the animation does not cause any.
        self.figure.canvas.mpl_connect("resize_event", self._on_resize)

    def _caption_band(self) -> float:
        """Fraction of the figure height the two caption lines need.

        Computed rather than fixed, because the fraction that reserves the right
        number of pixels is a different fraction on every panel size this figure
        is drawn at - the same reason ``tight_layout`` is re-solved on resize
        below.  Capped, so a letterbox panel gives up a third of itself at worst
        rather than all of it.
        """
        height = max(self.figure.get_size_inches()[1] * self.figure.dpi, 1.0)
        return min((2 * _CAPTION_PT * self.figure.dpi / 72.0 * 1.7 + 6) / height,
                   0.35)

    def _layout(self) -> None:
        """Fit the drawing, leaving the caption band under it untouched."""
        self.figure.tight_layout(rect=(0.0, self._caption_band(), 1.0, 1.0))

    def _place_caption(self) -> None:
        """Put the two caption lines inside the band, wherever it now is."""
        band = self._caption_band()
        self._speed.set_y(0.52 * band)
        self._readout.set_y(0.08 * band)

    def _on_resize(self, _event) -> None:
        if self._spec is not None:
            self._layout()
            self._place_caption()

    # ----------------------------------------------------------------- design
    def set_design(self, spec: GearSpec, *, reference: GearSpec | None = None,
                   overlays: Overlays | None = None) -> None:
        """Adopt a design and rebuild the artists."""
        self._spec = spec
        self._reference = reference
        if overlays is not None:
            self._overlays = overlays
        self._build()
        self.set_crank(self._crank)

    def set_overlays(self, overlays: Overlays) -> None:
        self._overlays = overlays
        if self._spec is not None:
            self._build()
            self.set_crank(self._crank)

    def refresh(self) -> None:
        """Rebuild after a theme change.  Colours are baked in at draw time."""
        if self._spec is not None:
            self._build()
            self.set_crank(self._crank)

    def _build(self) -> None:
        spec, t = self._spec, theme()
        assert spec is not None
        series = t["series"]
        fig = self.figure
        fig.clear()
        fig.patch.set_facecolor(t["surface"])
        ax = fig.add_subplot(111)
        ax.set_facecolor(t["surface"])
        self._ax = ax

        reference = self._reference
        self._ghost = None
        if reference is not None:
            # underneath everything, in the muted ink: it is context, not content
            self._ref_profile = prof.profile_from_spec(reference)
            (self._ghost,) = ax.plot([], [], color=t["muted"], linewidth=1.2,
                                     linestyle=(0, (5, 3)), zorder=1)
            ax.add_artist(_circle(0, 0, reference.housing_outer_radius, t["muted"],
                                  0.8, dashed=True, alpha=0.7))

        # The barrel and the pin circle are concentric, so they read the same
        # whichever way the housing is turning.  The pins do not: on a
        # ring-output drive they are the part that moves, and drawing them
        # nailed down would be drawing the wrong mechanism - the readout would
        # claim an output angle with nothing on screen turning by it.
        ax.add_artist(_circle(0, 0, spec.housing_outer_radius, t["muted"], 0.8))
        ax.add_artist(_circle(0, 0, spec.pin_circle_radius, t["grid"], 0.8, dashed=True))
        self._ring_pins = []
        self._pin_labels = []
        for k in range(spec.pin_count):
            pin = _circle(0, 0, spec.pin_radius, series[1], 1.2)
            ax.add_artist(pin)
            self._ring_pins.append(pin)
            if self._overlays.labels:
                self._pin_labels.append(
                    ax.text(0, 0, str(k), color=t["ink2"], fontsize=6.5,
                            ha="center", va="center", zorder=6))

        self._profile = prof.profile_from_spec(spec)
        self._discs = []
        bore_r = (spec.center_bore_diameter + spec.hole_clearance) / 2.0
        hole_r = spec.output_hole_diameter / 2.0
        for i in range(spec.disc_count):
            alpha = 1.0 if i == 0 else 0.45
            # A closed path, not a polyline with its first point repeated.
            # Both draw the same outline, but a polyline has two *ends* there:
            # they land on the same vertex and each lays down its own
            # antialiased cap, which blends to something an interior join does
            # not.  The seam travels round the rim as the disc turns, so what
            # that costs is a handful of pixels changing every frame at a place
            # nothing is happening.
            line = Polygon(np.zeros((3, 2)), closed=True, fill=False,
                           edgecolor=series[0], linewidth=2.0, alpha=alpha,
                           zorder=3)
            ax.add_patch(line)
            bore = _circle(0, 0, bore_r, series[0], 1.0, alpha=alpha)
            ax.add_artist(bore)
            holes = [_circle(0, 0, hole_r, series[0], 0.9, alpha=alpha)
                     for _ in range(spec.output_pin_count)]
            for hole in holes:
                ax.add_artist(hole)
            self._discs.append((line, bore, holes))

        self._output_pins = [_circle(0, 0, spec.output_pin_diameter / 2,
                                     series[2], 1.2)
                             for _ in range(spec.output_pin_count)]
        for pin in self._output_pins:
            ax.add_artist(pin)

        # Two marks that turn the picture into a mechanism.  The crank arm runs
        # from the axis to the disc centre and is drawn to scale, which on a
        # 130 mm drive with 1.4 mm of eccentricity is almost nothing - honest,
        # and by itself useless.  So the input shaft also carries a ray inside
        # the bore, where there is room for it and nothing else is drawn: that
        # is the mark that visibly turns twenty-one times per output turn.
        self._input_ray_length = bore_r * 0.92
        (self._input_ray,) = ax.plot([], [], color=t["ink2"], linewidth=1.3,
                                     linestyle=(0, (4, 2)), zorder=4)
        (self._crank_arm,) = ax.plot([], [], color=t["ink2"], linewidth=1.2,
                                     zorder=4)
        (self._crank_dot,) = ax.plot([], [], marker="o", markersize=4.5,
                                     color=t["ink2"], zorder=5)

        self._build_overlays(ax, t, series)

        lim = spec.housing_outer_radius * 1.05
        if reference is not None:
            lim = max(lim, reference.housing_outer_radius * 1.05)
        ax.set_xlim(-lim, lim)
        ax.set_ylim(-lim, lim)
        ax.set_aspect("equal")
        ax.axis("off")
        od = _unit_for(_units).text(2 * spec.housing_outer_radius, 1)
        ax.set_title(f"{spec.ratio}:1   {spec.lobes} lobes / {spec.pin_count} pins   "
                     f"OD {od}",
                     color=t["ink"], fontsize=10, pad=8)
        # The design's own speed, which is *not* the speed of the animation: the
        # playback rate is wall-clock and says nothing about the machine.  A
        # drawing that turns visibly at fifteen rpm while the drive it describes
        # runs at a thousand is only confusing while the picture declines to say
        # which of the two it is showing.  "reversed" is the other thing the
        # drawing knew and never said - with the ring fixed the output turns
        # against the input.
        #
        # Both caption lines live in *figure* coordinates, under the drawing,
        # in a strip `tight_layout` is told to keep off.
        #
        # They used to sit in the bottom-left corner of the axes, on the
        # argument that the housing circle leaves that corner empty.  The corner
        # is empty and the argument was still wrong: neither line is short
        # enough to stay in a corner.  `set_aspect("equal")` makes the axes a
        # square in the middle of a wide panel, the circle is inscribed in it,
        # and a full line of monospace starting at the left edge runs straight
        # under the circle and out the other side - across the disc at 1560 px
        # and across the whole gearbox at 1180.  A corner is a place for a word,
        # not for a sentence.
        #
        # Reserving the strip rather than nudging the text is what makes this
        # hold everywhere.  The same figure is drawn on the app's letterbox
        # panel, on the PDF's square, and on the animation's small canvas, and
        # anything positioned relative to the *drawing* has a different amount
        # of room on each.
        held = "ring fixed" if spec.output_member is OutputMember.CARRIER \
            else "carrier fixed"
        self._speed = fig.text(
            0.012, 0.0,
            f"{held} - in {spec.input_rpm:g} rpm, "
            f"out {spec.output_rpm:.1f} rpm"
            f"{' reversed' if spec.output_reverses else ''}",
            ha="left", va="bottom", color=t["ink2"], fontsize=_CAPTION_PT,
            family="monospace")
        self._readout = fig.text(
            0.012, 0.0, "", ha="left", va="bottom", color=t["ink2"],
            fontsize=_CAPTION_PT, family="monospace")
        # Out of the layout: `tight_layout` sizes itself around axes decorations
        # and a figure text is not one, so asking it to find room for these
        # fails on the animation's small canvas - the margins cannot grow that
        # far, the layout is abandoned, and the frame's white border goes with
        # it.  The `rect` in `_layout` is what actually keeps the room.
        self._speed.set_in_layout(False)
        self._readout.set_in_layout(False)
        self._layout()
        self._place_caption()

    def _build_overlays(self, ax, t, series) -> None:
        spec = self._spec
        assert spec is not None
        show = self._overlays

        self._trace_dot = None
        if show.trace:
            # The path of one material point on the disc rim over a full
            # *output* revolution - which takes `lobes` turns of the input, and
            # is the period of the whole mechanism.  Tracing a single input turn
            # instead gives a stub of arc, because that is all the disc advances
            # in one: which is the reduction, drawn.
            turns = spec.lobes
            phis = np.linspace(0.0, 2.0 * np.pi * turns,
                               int(np.clip(48 * turns, 720, 6000)))
            # `to_world` spelled out for the whole sweep at once: the marker
            # starts at (r, 0) in the disc frame, so its world position is the
            # disc rotation applied to that plus the eccentric centre.
            r, E = self._profile.outer_radius, spec.eccentricity
            delta = phis / spec.lobes
            x = r * np.cos(delta) + E * np.cos(phis)
            y = r * np.sin(delta) - E * np.sin(phis)
            # Seen from the ground, which on a ring-output drive is a frame
            # turning under all of this: the locus is a different curve there,
            # and the one drawn has to be the one the eye can follow.
            f = spec.frame_spin * phis
            cf, sf = np.cos(f), np.sin(f)
            ax.plot(x * cf - y * sf, x * sf + y * cf,
                    color=t["ink2"], linewidth=0.7, alpha=0.9, zorder=2)
            (self._trace_dot,) = ax.plot([], [], marker="o", markersize=4,
                                         color=t["ink"], zorder=6)

        self._contact_dots = None
        self._force_lines = None
        self._peak_force = 0.0
        if not (show.contacts or show.forces):
            return

        # Normalised against the worst force over a whole lobe pitch, not
        # against this frame's, so an arrow that grows means the load grew - not
        # that the scale moved under it.  The sweep is the cached one the checks
        # already ran.
        torque = spec.output_torque_Nm * 1000.0 / spec.disc_count
        self._torque_per_disc = torque
        self._peak_force = max(
            (float(state.forces(torque).max()) for state in sweep(spec)),
            default=0.0)
        self._arrow_span = 0.20 * spec.pin_circle_radius

        if show.contacts:
            self._contact_dots = ax.scatter([], [], s=[], color=series[1],
                                            edgecolors="none", zorder=6)
        if show.forces:
            self._force_lines = LineCollection([], colors=t["ink"], linewidths=1.4,
                                               zorder=7)
            ax.add_collection(self._force_lines)

    # ------------------------------------------------------------------ angle
    def set_crank(self, degrees: float) -> None:
        """Move everything to crank angle ``degrees``.  No artist is recreated."""
        self._crank = float(degrees)
        spec = self._spec
        if spec is None:
            return
        phi = np.radians(self._crank)
        E, lobes = spec.eccentricity, spec.lobes

        # The whole picture is built in the frame the ring sits still in, which
        # is the ground frame only when the ring is what is bolted down.  When
        # it is not, one rigid rotation puts every artist below into the frame
        # that *is* the ground - the same trick the 3D mesh uses, and for the
        # same reason: the mechanism is one mechanism, and which part of it
        # stands still is a mounting decision rather than a different drawing.
        frame = spec.frame_spin * phi
        cf, sf = np.cos(frame), np.sin(frame)
        turn = np.array([[cf, sf], [-sf, cf]])           # right-multiplied

        def place(x: float, y: float) -> tuple[float, float]:
            return cf * x - sf * y, sf * x + cf * y

        for k, pin in enumerate(self._ring_pins):
            a = 2.0 * np.pi * k / spec.pin_count + frame
            pin.set_center((spec.pin_circle_radius * np.cos(a),
                            spec.pin_circle_radius * np.sin(a)))
        for k, label in enumerate(self._pin_labels):
            a = 2.0 * np.pi * k / spec.pin_count + frame
            label.set_position((spec.pin_circle_radius * np.cos(a),
                                spec.pin_circle_radius * np.sin(a)))

        if self._ghost is not None:
            ref = self._reference
            d = phi / ref.lobes + ref.frame_spin * phi
            c, s = np.cos(d), np.sin(d)
            centre = place(ref.eccentricity * np.cos(phi),
                           -ref.eccentricity * np.sin(phi))
            pts = self._ref_profile.closed @ np.array([[c, s], [-s, c]]) + list(centre)
            self._ghost.set_data(pts[:, 0], pts[:, 1])

        outline = self._profile.points
        for i, (line, bore, holes) in enumerate(self._discs):
            phase = spec.disc_phases[i]
            hole_phase = spec.disc_hole_phases[i]
            cx, cy = place(E * np.cos(phi + phase), -E * np.sin(phi + phase))
            d = (phi + phase) / lobes + frame
            c, s = np.cos(d), np.sin(d)
            pts = outline @ np.array([[c, s], [-s, c]]) + [cx, cy]
            line.set_xy(pts)
            bore.set_center((cx, cy))
            for k, hole in enumerate(holes):
                # hole_phase cancels the disc's own mesh rotation, so every
                # disc's holes land on the same carrier pins
                a = 2.0 * np.pi * k / spec.output_pin_count + d + hole_phase
                hole.set_center((cx + spec.output_bolt_circle_radius * np.cos(a),
                                 cy + spec.output_bolt_circle_radius * np.sin(a)))

        for k, pin in enumerate(self._output_pins):
            a = 2.0 * np.pi * k / spec.output_pin_count + phi / lobes + frame
            pin.set_center((spec.output_bolt_circle_radius * np.cos(a),
                            spec.output_bolt_circle_radius * np.sin(a)))

        cx, cy = place(E * np.cos(phi), -E * np.sin(phi))
        self._crank_arm.set_data([0.0, cx], [0.0, cy])
        self._crank_dot.set_data([cx], [cy])
        # The shaft turns *against* the crank angle: the disc centre walks
        # clockwise, so the cam carrying it is rotated by -phi.
        ray = -phi + frame
        self._input_ray.set_data([0.0, self._input_ray_length * np.cos(ray)],
                                 [0.0, self._input_ray_length * np.sin(ray)])

        if self._trace_dot is not None:
            point = to_world(np.array([[self._profile.outer_radius, 0.0]]),
                             float(phi), E, lobes) @ turn
            self._trace_dot.set_data(point[:, 0], point[:, 1])

        engaged = self._update_contacts(phi, turn)
        # Both angles modulo a turn, and both as the *shafts* read them: the
        # crank angle is not the input angle once the carrier is the grounded
        # member, because the crank then runs at (N+1)/N of it.  Playback also
        # arrives unwrapped - the mechanism's period is several input turns -
        # and "in 4680.0 deg" is not a reading anybody wants.
        turned_in = abs(spec.shaft_spin) * self._crank
        self._readout.set_text(
            f"in {turned_in % 360.0:6.1f} deg    "
            f"out {(turned_in / spec.ratio) % 360.0:6.2f} deg"
            + (f"    {engaged} of {spec.pin_count} pins carrying"
               if engaged is not None else ""))

    def _update_contacts(self, phi: float, turn: np.ndarray) -> int | None:
        """``turn`` puts the contact geometry into the ground frame - see
        :meth:`set_crank`.  It is passed in rather than recomputed so the dots
        cannot land anywhere but on the profile they were computed against."""
        if self._contact_dots is None and self._force_lines is None:
            return None
        spec = self._spec
        assert spec is not None
        # Clearance is deliberately absent from this contact model - see
        # `kinematics.contacts` - so these points sit on the theoretical
        # profile, a clearance inside the drawn one.  At any readable zoom that
        # is well under a line width.
        state = contacts(spec, float(phi))
        force = state.forces(self._torque_per_disc)
        loaded = force > _CONTACT_FLOOR * self._peak_force
        points = state.points[loaded] @ turn
        normals = state.normals[loaded] @ turn
        magnitude = force[loaded]

        if self._contact_dots is not None:
            self._contact_dots.set_offsets(points if len(points) else np.empty((0, 2)))
            scale = magnitude / self._peak_force if self._peak_force else magnitude
            self._contact_dots.set_sizes(6.0 + 44.0 * scale)
        if self._force_lines is not None:
            # The pin pushes the disc, so the arrow points along -n.
            length = (magnitude / self._peak_force * self._arrow_span
                      if self._peak_force else np.zeros_like(magnitude))
            tips = points - normals * length[:, None]
            self._force_lines.set_segments(
                [[tuple(a), tuple(b)] for a, b in zip(points, tips, strict=True)])
        return int(loaded.sum())


def profile_figure(spec: GearSpec, fig: Figure | None = None,
                   crank_deg: float = 0.0,
                   reference: GearSpec | None = None, *,
                   overlays: Overlays | None = None) -> Figure:
    """One-shot drawing of the disc in the housing at a given crank angle.

    ``reference`` draws a second design underneath in outline only, for
    comparing a change against what it replaced.  The application uses
    :class:`ProfileView` directly so that animating does not rebuild the figure;
    this is the convenience wrapper for the report and the documentation.
    """
    view = ProfileView(fig)
    view.set_design(spec, reference=reference, overlays=overlays or Overlays())
    view.set_crank(crank_deg)
    return view.figure


def assembly_figure(spec: GearSpec, fig: Figure | None = None, *,
                    crank_deg: float = 0.0, explode: float = 0.0,
                    azimuth: float = 38.0, elevation: float = 26.0,
                    hidden=(), pixels: int = 1100) -> Figure:
    """The 3D assembly as a figure, for the report and the documentation.

    The same draw list the desktop viewer paints, handed to matplotlib instead
    of to ``QPainter``.  Two renderers over one scene: the picture in the PDF is
    the picture in the window, and there is no second projection to keep in
    step.  It comes out as vector paths, so it stays sharp at print size.
    """
    from matplotlib.collections import PathCollection
    from matplotlib.path import Path

    from ..viz.mesh import mesh_for_spec
    from ..viz.scene import Camera, render

    t = theme()
    fig = fig or Figure(figsize=(6.2, 4.6), dpi=110)
    fig.clear()
    fig.patch.set_facecolor(t["surface"])
    ax = fig.add_subplot(111)
    ax.set_facecolor(t["surface"])

    w_in, h_in = fig.get_size_inches()
    width, height = pixels, max(round(pixels * h_in / w_in), 1)

    mesh = mesh_for_spec(spec)
    camera = Camera.framing(mesh, explode=explode, azimuth=azimuth,
                            elevation=elevation)
    draw = render(mesh, np.radians(crank_deg), camera, width, height,
                  explode=explode, hidden=hidden)

    paths = []
    for loops in draw.loops:
        verts, codes = [], []
        for loop in loops:
            verts.append(np.vstack([loop, loop[:1]]))
            codes.append(np.concatenate([[Path.MOVETO],
                                         np.full(len(loop) - 1, Path.LINETO),
                                         [Path.CLOSEPOLY]]))
        paths.append(Path(np.vstack(verts), np.concatenate(codes)))

    colours = draw.colours / 255.0
    # Every face is outlined in its own fill colour.  Without it, antialiasing
    # leaves a hairline of background along every shared edge and a solid part
    # arrives looking like a wireframe of its own facets.
    ax.add_collection(PathCollection(paths, facecolors=colours, edgecolors=colours,
                                     linewidths=0.5, antialiaseds=True))
    ax.set_xlim(0, width)
    ax.set_ylim(height, 0)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.tight_layout(pad=0.2)
    return fig


def force_figure(spec: GearSpec, fig: Figure | None = None, steps: int = 721) -> Figure:
    """Peak ring-pin force across one ring-stage period.

    The window is a whole cycle, so the curve closes: the value at the right
    edge is the value at the left, and the ripple quoted is the ripple there
    really is.  It used to span one lobe pitch, which is not a period - the
    trace was cut a tenth of the way through the cycle at an arbitrary phase,
    so it ended somewhere other than it began and read as a broken wave.

    The corners are real and are not sampling.  This is a maximum over the pins,
    which is the upper envelope of ``N+1`` smooth per-pin curves, and an envelope
    has a corner wherever the load hands over from one pin to the next.  The
    trace is identical at 180 samples and at 18000.

    The y axis starts at zero: this is a magnitude, and the variation is often a
    fraction of a percent, which a cropped axis would blow up into a false story.
    """
    t = theme()
    fig = fig or Figure(figsize=(6.2, 3.4), dpi=110)
    fig.clear()
    fig.patch.set_facecolor(t["surface"])
    ax = fig.add_subplot(111)

    torque_per_disc = spec.output_torque_Nm * 1000.0 / spec.disc_count
    period = np.degrees(ring_stage_period(spec.lobes))
    angles = np.linspace(0.0, period, steps)
    peak, engaged = [], []
    for a in angles:
        f = contacts(spec, float(np.radians(a))).forces(torque_per_disc)
        peak.append(float(f.max()))
        engaged.append(int((f > 0).sum()))

    peak_arr = np.asarray(peak)
    ax.plot(angles, peak_arr, color=t["series"][0], linewidth=2.0, zorder=3)
    style_axes(ax)
    ax.set_ylim(0, max(peak_arr.max() * 1.25, 1e-9))
    ax.set_xlim(angles[0], angles[-1])
    ax.set_xlabel(f"crank angle (deg) - one ring-stage period, {period:.1f} deg")
    ax.set_ylabel("peak pin force (N)")

    ripple = 100.0 * (peak_arr.max() - peak_arr.min()) / peak_arr.max() if peak_arr.max() else 0.0
    ax.set_title(f"Ring pin load - {np.mean(engaged):.0f} of {spec.pin_count} pins "
                 f"carrying at {spec.output_torque_Nm:g} Nm out",
                 color=t["ink"], fontsize=10, loc="left", pad=8)
    ax.annotate(f"peak {peak_arr.max():.1f} N   ripple {ripple:.2f}%",
                xy=(angles[int(np.argmax(peak_arr))], peak_arr.max()),
                xytext=(0, 6), textcoords="offset points",
                color=t["ink"], fontsize=9, fontweight="bold", ha="center")
    fig.tight_layout()
    return fig


#: The four things a design trades against each other, and how to draw each.
#: ``higher_is_better`` only decides which way the "good" arrow points in the
#: axis label - no metric is rescaled, because a trade-off you cannot read in
#: real units is not a trade-off you can act on.
_SWEEP_PANELS = (
    ("capacity_Nm", "torque capacity (Nm)", True),
    ("efficiency", "efficiency (%)", True),
    ("lost_motion_arcmin", "lost motion (arcmin)", False),
    ("mass_g", "mass (g)", False),
)


def sweep_figure(result, fig: Figure | None = None) -> Figure:
    """Four metrics against one swept parameter, with the current value marked.

    Blocked designs are shown as a shaded band rather than omitted: where the
    feasible range ends is usually the most useful thing on the chart, and a
    curve that simply stops does not say whether it ran out of geometry or ran
    off the end of the sweep.
    """
    t = theme()
    fig = fig or Figure(figsize=(7.2, 5.0), dpi=110)
    fig.clear()
    fig.patch.set_facecolor(t["surface"])
    axes = fig.subplots(2, 2).ravel()

    blocked = [p.value for p in result.blocked]
    for ax, (name, ylabel, higher_better) in zip(axes, _SWEEP_PANELS, strict=True):
        x, y = result.series(name)
        if name == "efficiency":
            y = 100.0 * y
        ax.set_facecolor(t["surface"])
        if len(x):
            ax.plot(x, y, color=t["series"][0], linewidth=1.8, zorder=3)
            ax.plot([result.current], [np.interp(result.current, x, y)],
                    marker="o", markersize=5, color=t["series"][1], zorder=4)
            _anchor_axis(ax, y)
        for v in blocked:
            ax.axvspan(v - _half_step(result), v + _half_step(result),
                       color=t["muted"], alpha=0.18, linewidth=0, zorder=1)
        ax.axvline(result.current, color=t["series"][1], linewidth=0.9,
                   linestyle=(0, (3, 3)), zorder=2)
        style_axes(ax)
        ax.set_ylabel(f"{ylabel}  {'^' if higher_better else 'v'}")
        ax.set_xlabel(f"{result.label} ({result.unit})" if result.unit else result.label)

    n_blocked = len(blocked)
    tail = f"   -   {n_blocked} blocked design(s) shaded" if n_blocked else ""
    fig.suptitle(f"Sweeping {result.label}{tail}", color=t["ink"], fontsize=10,
                 x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    return fig


def placeholder_figure(message: str, fig: Figure | None = None) -> Figure:
    """A figure that says why it is empty, instead of being a white rectangle.

    An axis-less blank panel under a toolbar reads as a chart that failed to
    draw, and the caption underneath it - which is where the explanation used
    to live - is read after the conclusion has already been reached.  So the
    explanation goes where the chart would be.
    """
    t = theme()
    fig = fig or Figure(figsize=(7.2, 5.0), dpi=110)
    fig.clear()
    fig.patch.set_facecolor(t["surface"])
    ax = fig.add_subplot(111)
    ax.set_facecolor(t["surface"])
    ax.axis("off")
    ax.text(0.5, 0.5, message, transform=ax.transAxes, ha="center", va="center",
            color=t["muted"], fontsize=10, linespacing=1.6, wrap=True)
    fig.tight_layout()
    return fig


def _half_step(result) -> float:
    values = [p.value for p in result.points]
    if len(values) < 2:
        return 0.5
    return abs(values[1] - values[0]) / 2.0


#: Below this relative span, a metric is treated as flat and its axis is
#: anchored at zero.
_FLAT_FRACTION = 0.10


def _anchor_axis(ax, y: np.ndarray) -> None:
    """Start a nearly-flat series at zero instead of magnifying its noise.

    Matplotlib's default is to fill the axis with whatever range it is given, so
    a quantity that moves by a tenth of a percent across the sweep arrives
    looking like a decisive trend.  On a chart whose entire purpose is reading
    off trade-offs, that is not a cosmetic problem - it is the chart telling the
    reader something untrue.  ``force_figure`` already refuses to do it; so does
    this.
    """
    if not len(y) or not np.all(np.isfinite(y)):
        return
    lo, hi = float(np.min(y)), float(np.max(y))
    if lo < 0 or hi <= 0:
        return
    if (hi - lo) / hi < _FLAT_FRACTION:
        ax.set_ylim(0.0, hi * 1.15)


def motor_figure(analysis, fig: Figure | None = None, steps: int = 400) -> Figure:
    """The motor's curve, with this duty point on it.

    The one figure in the app that is about something outside the gearbox, and
    it is here because the gearbox's rating is meaningless without it: a drive
    good for 5 Nm on a motor that runs out at 2 is a 2 Nm drive.

    Three lines and a point.  The peak curve is what the motor makes; the
    continuous curve is what it makes for longer than a few seconds, and it is
    drawn separately only where the two differ - on a stepper they are the same
    line and drawing it twice would suggest a headroom that is not there.  The
    flat line is what this duty point asks for, so where it crosses the curve is
    the top speed, and the app labels that crossing rather than leaving it to be
    read off.
    """
    m = analysis.motor
    if not m.modelled:
        return placeholder_figure(
            "No motor curve stated.\n\nSet one under Motor and this becomes "
            "what the drive can\nactually be driven with, rather than what it "
            "could take.", fig)

    t = theme()
    fig = fig or Figure(figsize=(6.2, 3.0), dpi=110)
    fig.clear()
    fig.patch.set_facecolor(t["surface"])
    ax = fig.add_subplot(111)
    curve = analysis.spec.motor_curve
    # Past the ceiling there is nothing to draw, and a little of the flat top
    # before zero is what makes the shape readable.
    top = curve.ceiling_rpm
    if not np.isfinite(top) or top <= 0:
        top = max(m.motor_rpm * 2.0, 1.0)
    rpm = np.linspace(0.0, top, steps)
    peak = np.array([curve.torque_at(float(n)) for n in rpm])
    cont = np.array([curve.continuous_torque_at(float(n)) for n in rpm])

    ax.plot(rpm, peak, color=t["series"][0], linewidth=2.0, zorder=3,
            label="peak")
    if not np.allclose(peak, cont):
        ax.plot(rpm, cont, color=t["series"][1], linewidth=2.0, zorder=3,
                label="continuous")
    ax.axhline(m.required_Nm, color=t["ink2"], linewidth=1.2, linestyle="--",
               zorder=2, label="asked of it")
    # Primary ink rather than a series colour: the point is not another series,
    # it is where the design sits among them.  Not the brand blue either - the
    # palette is chosen for separation and the brand colour is chosen to be
    # loud, and this figure is read against the other figures.
    ax.plot([m.motor_rpm], [m.required_Nm], marker="o", markersize=6,
            color=t["ink"], zorder=5, linestyle="none",
            label="this duty point")
    if 0.0 < m.top_motor_rpm < top:
        ax.plot([m.top_motor_rpm], [m.required_Nm], marker="|", markersize=14,
                color=t["ink2"], zorder=4, linestyle="none")
        ax.annotate(f"{m.top_motor_rpm:.0f} rpm",
                    (m.top_motor_rpm, m.required_Nm),
                    textcoords="offset points", xytext=(6, 8),
                    color=t["ink2"], fontsize=8)

    style_axes(ax)
    ax.set_xlim(0, top)
    ax.set_ylim(0, max(float(peak.max()), m.required_Nm) * 1.15)
    ax.set_xlabel("input speed (rpm)")
    ax.set_ylabel("torque (Nm)")
    ax.legend(loc="upper right", frameon=False, fontsize=8,
              labelcolor=t["ink2"])
    ax.set_title(f"{m.kind.value}  -  {m.margin:.2f}x at "
                 f"{m.motor_rpm:.0f} rpm, nothing left by "
                 f"{curve.ceiling_rpm:.0f}",
                 color=t["ink"], fontsize=10, loc="left", pad=8)
    fig.tight_layout()
    return fig


def loss_figure(analysis, fig: Figure | None = None) -> Figure:
    """Where the input power goes.  Bars, not a pie, and every bar is labelled."""
    t = theme()
    fig = fig or Figure(figsize=(6.2, 2.8), dpi=110)
    fig.clear()
    fig.patch.set_facecolor(t["surface"])
    ax = fig.add_subplot(111)

    eff = analysis.efficiency
    labels = ["Ring pin contact", "Output pin contact", "Bearings"]
    values = [eff.loss_ring_pins_W, eff.loss_output_pins_W, eff.loss_bearings_W]
    y = np.arange(len(labels))

    ax.barh(y, values, height=0.5, color=t["series"], zorder=3)
    for yi, v in zip(y, values, strict=True):
        ax.text(v, yi, f"  {v:.2f} W", va="center", ha="left",
                color=t["ink"], fontsize=9)

    ax.set_yticks(y, labels, color=t["ink2"])
    ax.invert_yaxis()
    style_axes(ax)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, max(values) * 1.3 if max(values) > 0 else 1)
    ax.set_xlabel("power lost (W)")
    ax.set_title(f"Efficiency {100 * eff.efficiency:.1f}%  -  {eff.total_loss_W:.2f} W lost "
                 f"of {eff.input_power_W:.2f} W in",
                 color=t["ink"], fontsize=10, loc="left", pad=8)
    fig.tight_layout()
    return fig
