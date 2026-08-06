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
from ..core.kinematics import contacts, sweep, to_world
from ..core.spec import GearSpec
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

        ax.add_artist(_circle(0, 0, spec.housing_outer_radius, t["muted"], 0.8))
        ax.add_artist(_circle(0, 0, spec.pin_circle_radius, t["grid"], 0.8, dashed=True))
        for k in range(spec.pin_count):
            a = 2.0 * np.pi * k / spec.pin_count
            x = spec.pin_circle_radius * np.cos(a)
            y = spec.pin_circle_radius * np.sin(a)
            ax.add_artist(_circle(x, y, spec.pin_radius, series[1], 1.2))
            if self._overlays.labels:
                ax.text(x, y, str(k), color=t["ink2"], fontsize=6.5,
                        ha="center", va="center", zorder=6)

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
        # Inside the axes, in the corner the housing circle leaves empty.  Below
        # it, `tight_layout` does not reserve room for a text in axes
        # coordinates and the line is cropped by the figure edge.
        self._readout = ax.text(0.005, 0.005, "", transform=ax.transAxes,
                                ha="left", va="bottom", color=t["ink2"],
                                fontsize=8.5, family="monospace")
        fig.tight_layout()

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
            ax.plot(r * np.cos(delta) + E * np.cos(phis),
                    r * np.sin(delta) - E * np.sin(phis),
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

        if self._ghost is not None:
            ref = self._reference
            d = phi / ref.lobes
            c, s = np.cos(d), np.sin(d)
            pts = (self._ref_profile.closed @ np.array([[c, s], [-s, c]])
                   + [ref.eccentricity * np.cos(phi), -ref.eccentricity * np.sin(phi)])
            self._ghost.set_data(pts[:, 0], pts[:, 1])

        outline = self._profile.points
        for i, (line, bore, holes) in enumerate(self._discs):
            phase = spec.disc_phases[i]
            hole_phase = spec.disc_hole_phases[i]
            cx = E * np.cos(phi + phase)
            cy = -E * np.sin(phi + phase)
            d = (phi + phase) / lobes
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
            a = 2.0 * np.pi * k / spec.output_pin_count + phi / lobes
            pin.set_center((spec.output_bolt_circle_radius * np.cos(a),
                            spec.output_bolt_circle_radius * np.sin(a)))

        cx, cy = E * np.cos(phi), -E * np.sin(phi)
        self._crank_arm.set_data([0.0, cx], [0.0, cy])
        self._crank_dot.set_data([cx], [cy])
        # The shaft turns *against* the crank angle: the disc centre walks
        # clockwise, so the cam carrying it is rotated by -phi.
        self._input_ray.set_data([0.0, self._input_ray_length * np.cos(-phi)],
                                 [0.0, self._input_ray_length * np.sin(-phi)])

        if self._trace_dot is not None:
            point = to_world(np.array([[self._profile.outer_radius, 0.0]]),
                             float(phi), E, lobes)
            self._trace_dot.set_data(point[:, 0], point[:, 1])

        engaged = self._update_contacts(phi)
        # Both angles modulo a turn.  The crank arrives unwrapped during
        # playback - the mechanism's period is `lobes` input revolutions, not
        # one - and "in 4680.0 deg" is not a reading anybody wants.
        self._readout.set_text(
            f"in {self._crank % 360.0:6.1f} deg    "
            f"out {(self._crank / spec.ratio) % 360.0:6.2f} deg"
            + (f"    {engaged} of {spec.pin_count} pins carrying"
               if engaged is not None else ""))

    def _update_contacts(self, phi: float) -> int | None:
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
        points = state.points[loaded]
        magnitude = force[loaded]

        if self._contact_dots is not None:
            self._contact_dots.set_offsets(points if len(points) else np.empty((0, 2)))
            scale = magnitude / self._peak_force if self._peak_force else magnitude
            self._contact_dots.set_sizes(6.0 + 44.0 * scale)
        if self._force_lines is not None:
            # The pin pushes the disc, so the arrow points along -n.
            length = (magnitude / self._peak_force * self._arrow_span
                      if self._peak_force else np.zeros_like(magnitude))
            tips = points - state.normals[loaded] * length[:, None]
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


def force_figure(spec: GearSpec, fig: Figure | None = None, steps: int = 180) -> Figure:
    """Peak ring-pin force across one lobe pitch.

    The y axis starts at zero: this is a magnitude, and the variation is often a
    fraction of a percent, which a cropped axis would blow up into a false story.
    """
    t = theme()
    fig = fig or Figure(figsize=(6.2, 3.4), dpi=110)
    fig.clear()
    fig.patch.set_facecolor(t["surface"])
    ax = fig.add_subplot(111)

    torque_per_disc = spec.output_torque_Nm * 1000.0 / spec.disc_count
    angles = np.linspace(0.0, 360.0 / spec.lobes, steps)
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
    ax.set_xlabel("crank angle (deg)")
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
