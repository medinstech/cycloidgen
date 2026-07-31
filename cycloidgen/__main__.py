"""``python -m cycloidgen`` - launch the desktop app, or work from the CLI.

    python -m cycloidgen                          # GUI
    python -m cycloidgen --ratio 29 --out ./x     # headless export
    python -m cycloidgen --optimise --ratio 29 --torque 20 --max-od 120 --out ./x
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _search(args) -> tuple[int, object | None]:
    """Run the requirements search and print the shortlist.

    Returns ``(exit_code, spec)``; the spec is the winner, ready to export.
    """
    from .core.spec import MATERIALS, Process
    from .design import Objective, Requirements, optimise

    if args.disc_material not in MATERIALS:
        print(f"unknown material {args.disc_material!r}; choose from "
              + ", ".join(MATERIALS), file=sys.stderr)
        return 2, None

    req = Requirements(
        ratio=args.ratio or 29,
        output_torque_Nm=args.torque,
        input_rpm=args.rpm,
        max_outer_diameter_mm=args.max_od,
        max_length_mm=args.max_length,
        process=Process(args.process),
        disc_material=args.disc_material,
        pin_material=args.pin_material,
        housing_material=args.housing_material,
        ring_pins_are_rollers=args.rollers,
        output_pins_are_rollers=args.rollers,
        min_safety_factor=args.min_safety,
        objective=Objective(args.objective),
        disc_count=args.discs,
    )
    print(f"searching for a {req.ratio}:1 drive, {req.output_torque_Nm:g} Nm out, "
          f"under {req.max_outer_diameter_mm:g} mm across, "
          f"optimising for {req.objective.value}...\n")
    result = optimise(req, effort=args.effort)

    if not result.ok:
        print(f"nothing met those requirements after {result.evaluations} "
              f"candidates.\nwhat stopped them: {result.tally.explain()}",
              file=sys.stderr)
        return 3, None

    header = (f"{'#':>2}  {'OD':>6} {'len':>6} {'capacity':>9} {'margin':>7} "
              f"{'eff':>6} {'mass':>7} {'backlash':>9} {'temp':>6}")
    print(header)
    print("-" * len(header))
    for i, c in enumerate(result.best, 1):
        print(f"{i:>2}  {c.outer_diameter_mm:6.1f} {c.length_mm:6.1f} "
              f"{c.capacity_Nm:8.2f}N {c.margin:6.2f}x {100 * c.efficiency:5.1f}% "
              f"{c.mass_g:6.0f}g {c.lost_motion_arcmin:8.1f}' "
              f"{c.temperature_C:5.0f}C")
    best = result.best[0].spec
    print(f"\ntaking #1: R={best.pin_circle_radius:.2f} Rr={best.pin_radius:.2f} "
          f"E={best.eccentricity:.3f} K1={best.K1:.3f}, "
          f"{best.disc_count} x {best.disc_thickness:.1f} mm disc(s), "
          f"{best.output_pin_count} x {best.output_pin_diameter:.1f} mm output pins")
    return 0, best


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cycloidgen",
                                     description="Cycloidal drive generator")
    parser.add_argument("--ratio", type=int, help="generate a preset and exit")
    parser.add_argument("--design", type=Path, help="load a saved design JSON")
    parser.add_argument("--out", type=Path, help="output folder for a headless run")
    parser.add_argument("--no-solids", action="store_true",
                        help="skip STEP/STL, write drawings and report only")

    search = parser.add_argument_group(
        "design search", "state what the drive has to do and let the app find "
                         "the geometry, instead of giving it one")
    search.add_argument("--optimise", "--optimize", action="store_true",
                        dest="optimise", help="search for a design")
    search.add_argument("--torque", type=float, default=5.0,
                        help="required output torque, Nm (default 5)")
    search.add_argument("--rpm", type=float, default=1000.0,
                        help="input speed (default 1000)")
    search.add_argument("--max-od", type=float, default=120.0,
                        help="outer diameter limit, mm (default 120)")
    search.add_argument("--max-length", type=float, default=60.0,
                        help="axial length limit, mm (default 60)")
    search.add_argument("--process", default="FDM 3D print",
                        help="manufacturing process (default 'FDM 3D print')")
    search.add_argument("--disc-material", default="PLA")
    search.add_argument("--pin-material", default="Steel 1045")
    search.add_argument("--housing-material", default="PLA")
    search.add_argument("--rollers", action="store_true",
                        help="ring and output pins carry rolling elements")
    search.add_argument("--discs", type=int, default=0, choices=(0, 1, 2, 3),
                        help="0 lets the search choose (default)")
    search.add_argument("--min-safety", type=float, default=1.5,
                        help="required margin on contact stress (default 1.5)")
    search.add_argument("--objective", default="balanced",
                        choices=["balanced", "torque capacity", "efficiency",
                                 "small and light", "stiffness and low backlash"])
    search.add_argument("--effort", default="normal",
                        choices=["quick", "normal", "thorough"])
    args = parser.parse_args(argv)

    if args.out or args.ratio or args.design or args.optimise:
        import matplotlib
        matplotlib.use("Agg")
        from .analysis import analyse
        from .core.spec import GearSpec, preset
        from .export import write_bundle

        if args.optimise:
            code, spec = _search(args)
            if code:
                return code
            print()
        elif args.design:
            import json
            data = json.loads(args.design.read_text(encoding="utf-8"))
            spec = GearSpec.model_validate(data.get("spec", data))
        else:
            spec = preset(args.ratio or 15)

        report = analyse(spec).report
        print(report)
        if not args.out and args.optimise:
            return 0                              # searched only, nothing to write
        if not report.ok:
            print("\nblocked: fix the errors above", file=sys.stderr)
            return 2

        out = args.out or Path.cwd() / f"cycloidal_{spec.ratio}to1"
        files = write_bundle(spec, out, include_solids=not args.no_solids)
        print(f"\nwrote {len(files)} files to {out}")
        for f in files:
            print(f"  {f.relative_to(out)}")
        return 0

    from .ui.app import main as gui_main
    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
