"""File output: DXF, SVG, STEP, STL, 3MF, and the JSON/PDF report.

Every deliverable is declared in :mod:`cycloidgen.export.manifest`; this module
knows how to write them.  Keeping the *declaration* separate from the *writing*
is what lets the application list a bundle before producing it, and on a machine
that has no CAD kernel to produce it with.
"""
from __future__ import annotations

from collections.abc import Collection
from pathlib import Path

from ..core.spec import GearSpec
from . import bom, dxf, manifest, solid, svg, threemf
from .manifest import GROUPS, MANIFEST, Output, planned_files, resolve_groups

__all__ = [
    "GROUPS",
    "MANIFEST",
    "Output",
    "bom",
    "dxf",
    "manifest",
    "planned_files",
    "resolve_groups",
    "solid",
    "svg",
    "threemf",
    "write_bundle",
]


def _write(out: Output, spec: GearSpec, directory: Path, analysis) -> list[Path]:
    """Produce one manifest entry.

    ``report.build`` is imported here rather than at the top because it imports
    ``export.bom``; at module level the two would close a cycle.  ``animation``
    is deferred for a different reason: it pulls matplotlib in, and listing a
    bundle has to stay cheap enough to do before deciding to write one.
    """
    target = directory / out.where.rstrip("/")
    if out.key == "notice":
        from .. import notice
        target.write_text(
            notice.file_text(f"Cycloidal drive, {spec.ratio}:1, "
                             f"{2 * spec.housing_outer_radius:.0f} mm outside "
                             f"diameter."),
            encoding="utf-8")
        return [target]
    if out.key == "assembly_dxf":
        return [dxf.write_dxf(spec, target)]
    if out.key == "assembly_svg":
        return [svg.write_svg(spec, target)]
    if out.key == "part_dxf":
        return dxf.write_part_dxfs(spec, target)
    if out.key == "assembly_step":
        return [solid.write_step(spec, target)]
    if out.key == "part_step":
        return solid.write_part_steps(spec, target)
    if out.key == "stl":
        return solid.write_stls(spec, target)
    if out.key == "threemf":
        return [threemf.write_3mf(spec, target)]
    if out.key == "bom":
        return [bom.write_bom_csv(analysis, target)]
    if out.key == "gif":
        from . import animation
        return [animation.write_gif(spec, target)]

    from ..report import build
    if out.key == "json":
        return [build.write_json(analysis, target)]
    if out.key == "pdf":
        return [build.write_pdf(analysis, target)]
    raise KeyError(f"no writer for output {out.key!r}")


def write_bundle(spec: GearSpec, directory: str | Path,
                 include_solids: bool = True, *,
                 groups: Collection[str] | None = None) -> list[Path]:
    """Write the selected outputs for ``spec`` into ``directory``.

    ``groups`` names entries of :data:`cycloidgen.export.manifest.GROUPS`;
    ``include_solids=False`` is the older way of saying
    ``groups={"drawings", "data"}`` and still works, because the CLI flag and a
    good deal of other people's scripting is written against it.

    The order is the manifest's, so the fast files land first: on a big design
    the STEP and STL writing is most of the wait, and having the drawings and
    the report already on disk while it finishes is worth something.
    """
    from ..analysis import analyse

    chosen = resolve_groups(include_solids, groups)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    analysis = analyse(spec) if "data" in chosen else None
    written: list[Path] = []
    for out in MANIFEST:
        if out.group in chosen or (out.always and chosen):
            written.extend(_write(out, spec, directory, analysis))
    return written
