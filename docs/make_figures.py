"""Regenerate the figures the README embeds.

    python docs/make_figures.py

These come straight out of the same plotting code the application and the PDF
report use, so a figure in the README cannot drift away from what the app
actually draws.  Run it after changing anything in ``cycloidgen.report.plots``.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import numpy as np
from matplotlib.figure import Figure

from cycloidgen.core.spec import GearSpec, Process, preset
from cycloidgen.design.sweep import sweep_parameter
from cycloidgen.export import animation
from cycloidgen.report import plots

DOCS = Path(__file__).resolve().parent


def _hero() -> GearSpec:
    """A machined steel drive - a design the app would actually pass."""
    s = preset(21)
    s.process = Process.CNC
    s.apply_process_defaults()
    s.disc_material = "Steel 4140 (hardened)"
    s.pin_material = "Bearing steel 100Cr6"
    s.housing_material = "Aluminium 7075-T6"
    s.ring_pins_are_rollers = True
    s.output_pins_are_rollers = True
    s.output_torque_Nm = 25.0
    return s


def _save(fig: Figure, name: str) -> None:
    path = DOCS / name
    fig.savefig(path, dpi=110, facecolor=fig.get_facecolor(), bbox_inches="tight")
    print(f"  {path.name}  {path.stat().st_size / 1024:.0f} kB")


def main() -> int:
    plots.set_theme("light")                     # a README is a print surface
    print("writing figures:")

    spec = preset(21)
    # With the overlays on, because they are the point: the dots are where the
    # disc touches each ring pin and the arrows are the load it carries there,
    # both straight off the kinematics the checks use.
    _save(plots.profile_figure(spec, Figure(figsize=(7.3, 7.3), dpi=110),
                               crank_deg=28.0,
                               overlays=plots.Overlays(contacts=True, forces=True,
                                                       trace=True)),
          "drawing.png")

    # `assembly.png` and `exploded.png` are *not* written here, though this
    # module has the code that could: `plots.assembly_figure` is the software
    # painter, the fallback for a machine with no OpenGL, and it renders flat
    # facets with no anti-aliasing.  On its own that is honest work - it is what
    # the PDF report embeds, and it is why a headless export still has a picture
    # of the gearbox in it.  Next to a screenshot of the real viewport in the
    # same README it reads as a different program.  `tools/make_screenshots.py`
    # crops those two out of the running 3D tab instead.

    # The trade study: one parameter moved, four consequences reported. Pin
    # radius is the clearest example - it has a genuine interior optimum rather
    # than a monotone trend, which is the whole reason the tab exists.
    hero = _hero()
    result = sweep_parameter(hero, "pin_radius", np.linspace(1.6, 6.4, 25))
    _save(plots.sweep_figure(result, Figure(figsize=(9.0, 6.2), dpi=110)),
          "tradestudy.png")

    # The drawing, turning.  Smaller than the exported default, because this one
    # is checked into the repository and served on every view of the README.
    #
    # Paced rather than defaulted.  A 21:1 closes exactly at seven turns, and
    # seven turns at the export defaults is over two input revolutions a second:
    # the eccentric becomes a blur and the mesh - the thing the picture exists to
    # show - is not readable at all.  Twenty degrees of crank per frame and a
    # nine-second loop is slow enough to follow one pin through its contact.  It
    # costs about 300 kB over the fast version, which is the right trade for the
    # one figure most visitors will actually watch.
    plan = animation.plan(spec, pixels=360, frames=126, fps=14)
    print(f"  motion.gif  {plan.describe()}")
    path = animation.write_gif(spec, DOCS / "motion.gif", animation=plan,
                               theme="light")
    print(f"  {path.name}  {path.stat().st_size / 1024:.0f} kB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
