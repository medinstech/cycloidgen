"""File output: DXF, SVG, STEP, STL, and the JSON/PDF report."""
from __future__ import annotations

from pathlib import Path

from ..core.spec import GearSpec
from . import bom, dxf, solid, svg

__all__ = ["dxf", "svg", "solid", "bom", "write_bundle"]


def write_bundle(spec: GearSpec, directory: str | Path,
                 include_solids: bool = True) -> list[Path]:
    """Write every deliverable for ``spec`` into ``directory``.

    Solids are optional so the app still produces drawings, a bill of materials
    and a report on a machine where the OCCT kernel is unavailable.
    """
    from ..analysis import analyse
    from ..report import build

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    written = [dxf.write_dxf(spec, directory / "disc.dxf"),
               svg.write_svg(spec, directory / "disc.svg")]
    written.extend(dxf.write_part_dxfs(spec, directory / "dxf"))

    if include_solids:
        written.append(solid.write_step(spec, directory / "assembly.step"))
        written.extend(solid.write_part_steps(spec, directory / "step"))
        written.extend(solid.write_stls(spec, directory / "stl"))

    analysis = analyse(spec)
    written.append(bom.write_bom_csv(analysis, directory / "bom.csv"))
    written.append(build.write_json(analysis, directory / "report.json"))
    written.append(build.write_pdf(analysis, directory / "report.pdf"))
    return written
