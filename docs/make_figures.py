"""Regenerate the figures the README embeds.

    python docs/make_figures.py

These come straight out of the same plotting code the application and the PDF
report use, so a figure in the README cannot drift away from what the app
actually draws.  Run it after changing anything in ``cycloidgen.report.plots``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import numpy as np                                          # noqa: E402
from matplotlib.figure import Figure                        # noqa: E402

from cycloidgen.core.spec import GearSpec, Process, preset  # noqa: E402
from cycloidgen.design.sweep import sweep_parameter         # noqa: E402
from cycloidgen.report import plots                         # noqa: E402

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
    _save(plots.profile_figure(spec, Figure(figsize=(7.3, 7.3), dpi=110)),
          "drawing.png")

    # The trade study: one parameter moved, four consequences reported. Pin
    # radius is the clearest example - it has a genuine interior optimum rather
    # than a monotone trend, which is the whole reason the tab exists.
    hero = _hero()
    result = sweep_parameter(hero, "pin_radius", np.linspace(1.6, 6.4, 25))
    _save(plots.sweep_figure(result, Figure(figsize=(9.0, 6.2), dpi=110)),
          "tradestudy.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
