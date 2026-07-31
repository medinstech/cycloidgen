"""Matplotlib figures shared by the desktop preview and the PDF report.

Colour comes from the validated reference palette, first three categorical slots.
Both modes are selected rather than flipped: the dark column is the same three
hues re-stepped for the dark surface, and both sets clear the all-pairs CVD and
normal-vision floors.  Every bar also carries a visible value label, which is
what the light-mode aqua contrast warning requires.
"""
from __future__ import annotations

from contextlib import contextmanager

import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Circle

from ..core import profile as prof
from ..core.kinematics import contacts
from ..core.spec import GearSpec

__all__ = ["set_theme", "theme", "light_theme", "profile_figure", "force_figure",
           "loss_figure", "sweep_figure", "style_axes"]

_THEMES = {
    "light": {
        "surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e",
        "muted": "#9a9994", "grid": "#e6e5e1",
        "series": ("#2a78d6", "#eb6834", "#1baf7a"),
    },
    "dark": {
        "surface": "#1a1a19", "ink": "#ffffff", "ink2": "#c3c2b7",
        "muted": "#6f6e68", "grid": "#33332f",
        "series": ("#3987e5", "#d95926", "#199e70"),
    },
}

_mode = "light"


def set_theme(mode: str) -> None:
    """Select ``"light"`` or ``"dark"``.  Affects every figure built afterwards."""
    global _mode
    if mode not in _THEMES:
        raise ValueError(f"unknown theme {mode!r}")
    _mode = mode


def theme() -> dict:
    return _THEMES[_mode]


@contextmanager
def light_theme():
    """Force light for print output, then restore whatever the UI was using."""
    global _mode
    previous, _mode = _mode, "light"
    try:
        yield
    finally:
        _mode = previous


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


def _circle(x, y, r, color, lw, dashed: bool = False, alpha: float = 1.0) -> Circle:
    return Circle((x, y), r, fill=False, edgecolor=color, linewidth=lw,
                  linestyle=(0, (4, 3)) if dashed else "solid", alpha=alpha, zorder=2)


def profile_figure(spec: GearSpec, fig: Figure | None = None,
                   crank_deg: float = 0.0,
                   reference: GearSpec | None = None) -> Figure:
    """Technical drawing of the disc in the housing at a given crank angle.

    ``reference`` draws a second design underneath in outline only, for
    comparing a change against what it replaced.
    """
    t = theme()
    fig = fig or Figure(figsize=(6.2, 6.2), dpi=110)
    fig.clear()
    fig.patch.set_facecolor(t["surface"])
    ax = fig.add_subplot(111)
    ax.set_facecolor(t["surface"])

    phi = np.radians(crank_deg)
    p = prof.profile_from_spec(spec)
    series = t["series"]

    if reference is not None:
        # underneath everything, in the muted ink: it is context, not content
        ref = prof.profile_from_spec(reference)
        d = phi / reference.lobes
        c, s = np.cos(d), np.sin(d)
        pts = (ref.closed @ np.array([[c, s], [-s, c]])
               + np.array([reference.eccentricity * np.cos(phi),
                           -reference.eccentricity * np.sin(phi)]))
        ax.plot(pts[:, 0], pts[:, 1], color=t["muted"], linewidth=1.2,
                linestyle=(0, (5, 3)), zorder=1)
        ax.add_artist(_circle(0, 0, reference.housing_outer_radius, t["muted"],
                              0.8, dashed=True, alpha=0.7))

    ax.add_artist(_circle(0, 0, spec.housing_outer_radius, t["muted"], 0.8))
    ax.add_artist(_circle(0, 0, spec.pin_circle_radius, t["grid"], 0.8, dashed=True))

    for k in range(spec.pin_count):
        a = 2.0 * np.pi * k / spec.pin_count
        ax.add_artist(_circle(spec.pin_circle_radius * np.cos(a),
                              spec.pin_circle_radius * np.sin(a),
                              spec.pin_radius, series[1], 1.2))

    for i, (phase, hole_phase) in enumerate(zip(spec.disc_phases,
                                                spec.disc_hole_phases)):
        cx = spec.eccentricity * np.cos(phi + phase)
        cy = -spec.eccentricity * np.sin(phi + phase)
        d = (phi + phase) / spec.lobes
        c, s = np.cos(d), np.sin(d)
        pts = p.closed @ np.array([[c, s], [-s, c]]) + np.array([cx, cy])
        alpha = 1.0 if i == 0 else 0.45
        ax.plot(pts[:, 0], pts[:, 1], color=series[0], linewidth=2.0,
                alpha=alpha, zorder=3)
        ax.add_artist(_circle(cx, cy,
                              (spec.center_bore_diameter + spec.hole_clearance) / 2,
                              series[0], 1.0, alpha=alpha))
        hole_r = spec.output_hole_diameter / 2.0
        for k in range(spec.output_pin_count):
            # hole_phase cancels the disc's own mesh rotation, so every disc's
            # holes land on the same carrier pins
            a = 2.0 * np.pi * k / spec.output_pin_count + d + hole_phase
            ax.add_artist(_circle(cx + spec.output_bolt_circle_radius * np.cos(a),
                                  cy + spec.output_bolt_circle_radius * np.sin(a),
                                  hole_r, series[0], 0.9, alpha=alpha))

    for k in range(spec.output_pin_count):
        a = 2.0 * np.pi * k / spec.output_pin_count + phi / spec.lobes
        ax.add_artist(_circle(spec.output_bolt_circle_radius * np.cos(a),
                              spec.output_bolt_circle_radius * np.sin(a),
                              spec.output_pin_diameter / 2, series[2], 1.2))

    lim = spec.housing_outer_radius * 1.05
    if reference is not None:
        lim = max(lim, reference.housing_outer_radius * 1.05)
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(f"{spec.ratio}:1   {spec.lobes} lobes / {spec.pin_count} pins   "
                 f"OD {2 * spec.housing_outer_radius:.1f} mm",
                 color=t["ink"], fontsize=10, pad=8)
    fig.tight_layout()
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
    for ax, (name, ylabel, higher_better) in zip(axes, _SWEEP_PANELS):
        x, y = result.series(name)
        if name == "efficiency":
            y = 100.0 * y
        ax.set_facecolor(t["surface"])
        if len(x):
            ax.plot(x, y, color=t["series"][0], linewidth=1.8, zorder=3)
            ax.plot([result.current], [np.interp(result.current, x, y)],
                    marker="o", markersize=5, color=t["series"][1], zorder=4)
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


def _half_step(result) -> float:
    values = [p.value for p in result.points]
    if len(values) < 2:
        return 0.5
    return abs(values[1] - values[0]) / 2.0


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
    for yi, v in zip(y, values):
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
