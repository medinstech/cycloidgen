"""``python -m cycloidgen`` - launch the desktop app, or work from the CLI.

    python -m cycloidgen                          # GUI
    python -m cycloidgen --ratio 29 --out ./x     # headless export
    python -m cycloidgen --ratio 29 --list-outputs # what an export would write
    python -m cycloidgen --optimise --ratio 29 --torque 20 --max-od 120 --out ./x
    python -m cycloidgen --ratio 21 --vary disc_count=1 --vary disc_count=2 \
        --vary output_pin_count=8:16:5 --csv study.csv       # parameter study
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import notice


def _spec_from_args(args):
    """The design a headless run works on: a saved file if given, else a preset."""
    import json

    from .core.designfile import numbers_may_have_moved, provenance, spec_from_dict, written_by
    from .core.spec import preset
    if args.design:
        data = json.loads(args.design.read_text(encoding="utf-8"))
        spec = spec_from_dict(data)
        # No dialog to put it in out here, and a headless run is the one most
        # likely to end up in a script whose output nobody reads twice.
        written = written_by(data)
        if numbers_may_have_moved(written):
            print(provenance(written), file=sys.stderr)
    else:
        # ``--ratio`` is a reduction wherever this CLI uses it, including in the
        # search - and off the ring a reduction of N+1 is a disc of N lobes,
        # which is what ``preset`` is indexed by.  Asking for 20:1 and being
        # handed 21:1 because of how the preset table happens to be keyed would
        # be the flag quietly not doing what it says.
        wanted = args.ratio or 15
        spec = preset(max(wanted - 1, 3) if args.output_from == "ring" else wanted)
    # Applied over a loaded design too, and deliberately: this is the one
    # decision somebody is most likely to want to try both ways on a design
    # they already have, and the answer is a different gearbox rather than a
    # different view of the same one.
    if args.output_from:
        spec.output_member = _member(args.output_from)
    return _apply_omissions(spec, args)


def _member(name: str):
    """``--output-from`` as the enum.  Short words on the command line, because
    the enum's own values have spaces in them and are meant for a combo box."""
    from .core.spec import OutputMember
    return OutputMember.CARRIER if name == "carrier" else OutputMember.RING


def _apply_omissions(spec, args):
    """Take out the bearings the caller says this drive does not have.

    Only ever subtractive - the flags are ``--no-...`` - so applying them over a
    saved design can remove a bearing it had and never put one back that it did
    not, which is the only reading of a command line that is not a surprise.
    """
    if args.no_cam_bearing:
        spec.cam_bearing_fitted = False
    if args.no_shaft_bearings:
        spec.shaft_bearings_fitted = False
    if args.no_output_bearing:
        spec.output_bearing_fitted = False
    return spec


def _list_outputs(spec, groups: set[str]) -> int:
    """Print the bundle without producing it.

    Straight off the manifest, which is also what ``write_bundle`` walks, so
    this is a promise the exporter keeps rather than a table someone wrote once.
    """
    from .export.manifest import GROUPS, always_written, outputs_for

    print(f"An export of this {spec.ratio}:1 design writes:\n")
    total = 0
    for out in always_written():
        print("[x] Always  -  written whichever groups are selected")
        print(f"      {out.fmt:<5} {out.where:<16} {out.title}\n")
        total += len(out.files(spec)) if groups else 0
    for group in GROUPS:
        mark = "x" if group.key in groups else " "
        print(f"[{mark}] {group.title}  -  {group.note}")
        for out in outputs_for({group.key}):
            names = out.files(spec)
            print(f"      {out.fmt:<5} {out.where:<16} {out.title}")
            if out.is_folder:
                for name in names:
                    print(f"            {name}")
            total += len(names) if group.key in groups else 0
        print()
    print(f"{total} file(s) with the current selection.")
    return 0


def _batch(args, spec) -> int:
    """Run the parameter study and print it, or write it, and stop there.

    A study is numbers rather than parts: four hundred designs are four hundred
    answers and one folder of STEP files nobody asked for, so this deliberately
    does not export.  ``--out`` with ``--vary`` is refused rather than ignored,
    because ignoring it would look like it had worked.
    """
    import sys as _sys

    from .design.batch import METRICS, as_text, merge_axes, parse_axis, run_batch, write_csv

    if args.out:
        print("--out writes one design; --vary evaluates many. Use --csv for a "
              "study, or drop --vary to export this design.", file=_sys.stderr)
        return 2

    try:
        axes = merge_axes([parse_axis(*_split_vary(text)) for text in args.vary])
    except ValueError as exc:
        print(exc, file=_sys.stderr)
        return 2

    total = 1
    for axis in axes:
        total *= len(axis)
    plan = " x ".join(f"{len(a)} {a.field}" for a in axes)
    print(f"{total} design(s): {plan}", file=_sys.stderr)

    def tick(done: int, of: int) -> None:
        if of > 20 and (done % max(1, of // 20) == 0 or done == of):
            print(f"\r  {done}/{of}", end="", file=_sys.stderr, flush=True)

    points = run_batch(spec, axes, progress=tick)
    if total > 20:
        print(file=_sys.stderr)

    if args.csv:
        path = write_csv(points, axes, args.csv)
        built = sum(1 for p in points if p.ok)
        print(f"wrote {len(points)} row(s) to {path}  ({built} built, "
              f"{len(points) - built} blocked)")
        return 0

    # No file asked for, so this goes on the terminal - and the whole table is
    # too wide for one.  The five shown are the five the calibration plan
    # measures on real hardware, which is why they are the first five in
    # METRICS rather than a second list kept here.
    shown = METRICS[:5]
    header = [a.field for a in axes] + ["ok"] + [m.name for m in shown]
    rows = [[as_text(p.values[a.field]) for a in axes]
            + ["yes" if p.ok else "no"]
            + [f"{p.metrics.get(m.name, float('nan')):.4g}" for m in shown]
            for p in points]

    # Sized to what is in them.  A lubricant name is 24 characters and a fixed
    # width either truncates it into two rows that read as the same design or
    # pushes every column out to fit the longest thing in the app.
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) if rows
              else len(header[i]) for i in range(len(header))]
    line = "  ".join(h.rjust(w) for h, w in zip(header, widths, strict=True))
    print(line)
    print("-" * len(line))
    for row in rows:
        print("  ".join(cell.rjust(w) for cell, w in zip(row, widths, strict=True)))
    print(f"\n{len(METRICS)} metrics per design; --csv writes all of them.")
    return 0


def _split_vary(text: str) -> tuple[str, str]:
    """``field=value`` into its two halves, splitting on the *first* ``=``.

    Values can contain one - a bearing designation or a lubricant name is
    somebody else's naming scheme, not ours to constrain.
    """
    name, sep, value = text.partition("=")
    if not sep:
        raise ValueError(f"--vary wants field=value, not {text!r}")
    return name.strip(), value


def _search(args) -> tuple[int, object | None]:
    """Run the requirements search and print the shortlist.

    Returns ``(exit_code, spec)``; the spec is the winner, ready to export.
    """
    from .core.motor import MOTOR_FIELDS
    from .core.spec import MATERIALS, Process
    from .design import (
        RATIO_FROM_MOTOR,
        Objective,
        Requirements,
        optimise,
        ratio_band,
    )

    # Every name a flag hands to `Requirements` is checked here, and all four
    # of them rather than just the disc: unchecked, they arrive as a pydantic
    # error or an enum ValueError raised several frames inside the search, so
    # what the caller gets for one mistyped word is a traceback about a design
    # they never asked for.  Both lists are read off the definitions rather
    # than spelled out again, so a material added to `MATERIALS` is not one
    # this refuses, and the message is the whole list rather than a pointer to
    # where it might be written down.
    for flag, name in (("--disc-material", args.disc_material),
                       ("--pin-material", args.pin_material),
                       ("--housing-material", args.housing_material)):
        if name not in MATERIALS:
            print(f"unknown material {name!r} for {flag}; choose from "
                  + ", ".join(MATERIALS), file=sys.stderr)
            return 2, None

    if args.process not in {p.value for p in Process}:
        print(f"unknown process {args.process!r}; choose from "
              + ", ".join(p.value for p in Process), file=sys.stderr)
        return 2, None

    # The motor comes off a design file rather than off eight more flags.  A
    # curve is eight numbers from a datasheet and the app already has a place to
    # put them; a second way to state them here would be a second thing to keep
    # in step, and the first thing anybody would do with it is get one wrong.
    motor: dict = {}
    if args.design:
        motor = {f: getattr(_spec_from_args(args), f) for f in MOTOR_FIELDS}
    if args.ratio_from_motor and not motor:
        print("--ratio-from-motor needs a design to take the motor from: pass "
              "--design with a torque curve on it", file=sys.stderr)
        return 2, None

    req = Requirements(
        **motor,
        output_rpm=args.out_rpm,
        ratio=RATIO_FROM_MOTOR if args.ratio_from_motor else (args.ratio or 29),
        output_member=_member(args.output_from or "carrier"),
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
        cam_bearing_fitted=not args.no_cam_bearing,
        shaft_bearings_fitted=not args.no_shaft_bearings,
        output_bearing_fitted=not args.no_output_bearing,
        min_safety_factor=args.min_safety,
        objective=Objective(args.objective),
        disc_count=args.discs,
    )
    if req.ratio_is_free:
        print(f"the motor: {ratio_band(req).explain()}")
        print(f"searching for a drive off the {req.output_member.value}, "
              f"{req.output_torque_Nm:g} Nm at {req.output_rpm:g} rpm out, "
              f"under {req.max_outer_diameter_mm:g} mm across, "
              f"optimising for {req.objective.value}...\n")
    else:
        print(f"searching for a {req.ratio}:1 drive off the "
              f"{req.output_member.value} ({req.lobes} lobes), "
              f"{req.output_torque_Nm:g} Nm out, "
              f"under {req.max_outer_diameter_mm:g} mm across, "
              f"optimising for {req.objective.value}...\n")
    result = optimise(req, effort=args.effort)

    if not result.ok:
        if result.band is not None and not result.band.ok:
            # No geometry was ever at fault, so the usual advice - loosen the
            # envelope, drop the torque - would send somebody to the wrong knob.
            print(f"the motor cannot do this job: {result.band.explain()}",
                  file=sys.stderr)
            return 3, None
        print(f"nothing met those requirements after {result.evaluations} "
              f"candidates.\nwhat stopped them: {result.tally.explain()}",
              file=sys.stderr)
        return 3, None
    if len(result.ratios_searched) > 1:
        print("reductions searched: "
              + ", ".join(f"{r}:1" for r in result.ratios_searched) + "\n")

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
    from . import __version__

    parser = argparse.ArgumentParser(prog="cycloidgen",
                                     description="Cycloidal drive generator")
    parser.add_argument("--version", action="version",
                        version=f"cycloidgen {__version__}")
    parser.add_argument("--ratio", type=int, help="generate a preset and exit")
    parser.add_argument("--output-from", choices=("carrier", "ring"),
                        help="which member turns the load: 'carrier' bolts the "
                             "housing down and reduces by the lobe count, "
                             "reversed; 'ring' bolts the carrier down and "
                             "reduces by the pin count - one more - in the same "
                             "direction. Applies to a preset, a loaded design "
                             "and a search alike")
    parser.add_argument("--design", type=Path, help="load a saved design JSON")
    parser.add_argument("--out", type=Path, help="output folder for a headless run")
    parser.add_argument("--no-solids", action="store_true",
                        help="skip the solids (STEP, STL, 3MF), write drawings "
                             "and report only")
    parser.add_argument("--only", metavar="GROUPS",
                        help="write only these output groups, comma separated: "
                             "drawings, solids, data")
    parser.add_argument("--list-outputs", action="store_true",
                        help="print every file an export would write, and exit")

    study = parser.add_argument_group(
        "parameter study", "evaluate a grid of designs and get a table out "
                           "instead of a folder of parts")
    study.add_argument("--vary", action="append", default=[], metavar="FIELD=VALUE",
                       help="a parameter and a value to put the design through. "
                            "Repeat it for more values of the same field, or for "
                            "another field - every combination is evaluated. "
                            "Numeric fields also take a lo:hi:steps range")
    study.add_argument("--csv", type=Path, metavar="PATH",
                       help="write the full table here instead of a summary to "
                            "the terminal")

    built = parser.add_argument_group(
        "bearings fitted", "three of the five load paths can be built without a "
                           "bearing of their own; these leave them out of the "
                           "design, not just out of the picture")
    built.add_argument("--no-cam-bearing", action="store_true",
                       help="the disc bore runs straight on the cam")
    built.add_argument("--no-shaft-bearings", action="store_true",
                       help="the drive hangs on the driving motor's bearings")
    built.add_argument("--no-output-bearing", action="store_true",
                       help="the driven machine locates the output flange")

    search = parser.add_argument_group(
        "design search", "state what the drive has to do and let the app find "
                         "the geometry, instead of giving it one")
    search.add_argument("--optimise", "--optimize", action="store_true",
                        dest="optimise", help="search for a design")
    search.add_argument("--torque", type=float, default=5.0,
                        help="required output torque, Nm (default 5)")
    search.add_argument("--rpm", type=float, default=1000.0,
                        help="input speed (default 1000)")
    search.add_argument("--out-rpm", type=float, default=30.0,
                        help="required *output* speed, used with "
                             "--ratio-from-motor (default 30)")
    search.add_argument("--ratio-from-motor", action="store_true",
                        help="work the reduction out from the motor on the "
                             "design given with --design, instead of taking "
                             "it from --ratio")
    search.add_argument("--max-od", type=float, default=120.0,
                        help="outer diameter limit, mm (default 120)")
    search.add_argument("--max-length", type=float, default=60.0,
                        help="axial length limit, mm (default 60)")
    search.add_argument("--process", default="FDM 3D print",
                        help="manufacturing process (default 'FDM 3D print')")
    search.add_argument("--disc-material", default="PLA",
                        help="disc material (default PLA); passing an unknown "
                             "name prints the choices, as it does for the pins "
                             "and the housing")
    search.add_argument("--pin-material", default="Steel 1045",
                        help="ring and output pin material (default 'Steel 1045')")
    search.add_argument("--housing-material", default="PLA",
                        help="housing material (default PLA)")
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

    headless = (args.out or args.ratio or args.design or args.optimise
                or args.list_outputs or args.vary)
    if headless:
        import matplotlib
        matplotlib.use("Agg")
        from .analysis import analyse
        from .export import write_bundle
        from .export.manifest import resolve_groups

        try:
            groups = resolve_groups(
                not args.no_solids,
                [g.strip() for g in args.only.split(",")] if args.only else None)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2

        if args.optimise:
            code, spec = _search(args)
            if code:
                return code
            print()
        else:
            spec = _spec_from_args(args)

        if args.list_outputs:
            return _list_outputs(spec, groups)

        if args.vary:
            # After the search rather than instead of it: varying around a
            # design the app found is a more useful study than varying around
            # a preset, and it costs nothing to allow.
            return _batch(args, spec)

        report = analyse(spec).report
        print(report)
        if not args.out and args.optimise:
            return 0                              # searched only, nothing to write
        if not report.ok:
            print("\nblocked: fix the errors above", file=sys.stderr)
            return 2

        out = args.out or Path.cwd() / f"cycloidal_{spec.ratio}to1"
        files = write_bundle(spec, out, groups=groups)
        print(f"\nwrote {len(files)} files to {out}")
        for f in files:
            print(f"  {f.relative_to(out)}")
        # The same sentence the window puts in front of an export, on the route
        # that has no window.  It is in `NOTICE.txt` beside the parts as well,
        # which is the copy that survives being emailed to a shop.
        print(f"\n{notice.HEADLINE}: {notice.SHORT}")
        return 0

    from .ui.app import main as gui_main
    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
