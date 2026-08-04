"""What an export writes, declared in one place.

:func:`~cycloidgen.export.write_bundle` walks this list, the desktop app's
Outputs tab lists it before anything is written, and ``--list-outputs`` prints
it.  Three consumers, one declaration.  A file that lands in the bundle but not
in the list - or worse, a list that promises a file nothing writes - is the kind
of drift nobody notices until someone goes looking for a part drawing that was
never there, and ``tests/test_outputs.py`` compares the two directly.

Nothing here imports a CAD kernel.  Listing what *would* be written has to work
on a machine that cannot write it: that is the whole point of having a
drawings-only build.
"""
from __future__ import annotations

from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass, field

from ..core.spec import GearSpec

__all__ = [
    "GROUPS",
    "MANIFEST",
    "Group",
    "Output",
    "disc_names",
    "group_keys",
    "outputs_for",
    "part_names",
    "planned_files",
    "resolve_groups",
]


@dataclass(frozen=True)
class Group:
    """A set of outputs that are wanted or not wanted together."""

    key: str
    title: str
    note: str


#: Grouped by what it costs to produce and what you would do with it, not by
#: file extension.  Solids are their own group because they are the slow part of
#: an export and the only part that needs the OCCT kernel.
GROUPS: tuple[Group, ...] = (
    Group("drawings", "Drawings",
          "2D geometry: read it, or cut from it. No CAD kernel needed."),
    Group("solids", "Solids",
          "3D geometry, through the OCCT kernel. This is the slow part of an "
          "export, and the only part a drawings-only build cannot do."),
    Group("data", "Data and report",
          "The numbers: bill of materials, machine-readable report, and the "
          "printable dossier."),
    Group("animation", "Animation",
          "The drive turning, as a looping GIF for a document or an issue. "
          "Rendered a frame at a time, so it costs a few seconds."),
)


def disc_names(spec: GearSpec) -> list[str]:
    """File stems for the discs: ``disc``, or ``disc_1``..``disc_n``.

    A stack normally holds *different parts* - each disc's output holes are
    pre-rotated against its lobes - so they get numbered files.  They collapse
    to one name only when the pre-rotation happens to land on a whole hole
    pitch.  Both the DXF and the solid exporters name their files from here, so
    the two cannot disagree about how many discs there are.
    """
    if spec.discs_are_identical:
        return ["disc"]
    return [f"disc_{i + 1}" for i in range(spec.disc_count)]


def part_names(spec: GearSpec) -> list[str]:
    """Every distinct part, in the order :func:`export.solid.parts` builds them."""
    return ["housing", "ring_pins", "eccentric_shaft", "output_flange",
            *disc_names(spec)]


@dataclass(frozen=True)
class Output:
    """One deliverable.  ``where`` ending in ``/`` means a folder of files."""

    key: str
    where: str
    group: str
    fmt: str
    title: str
    description: str
    #: Names inside the folder, for the folder entries.  A plain file needs no
    #: such function, and asking one for it is a bug rather than an empty list.
    contents: Callable[[GearSpec], list[str]] | None = field(default=None, repr=False)

    @property
    def is_folder(self) -> bool:
        return self.where.endswith("/")

    def files(self, spec: GearSpec) -> list[str]:
        """Exactly the paths this output writes for ``spec``, relative to the bundle."""
        if not self.is_folder:
            return [self.where]
        assert self.contents is not None
        return [self.where + name for name in self.contents(spec)]


MANIFEST: tuple[Output, ...] = (
    Output("assembly_dxf", "disc.dxf", "drawings", "DXF",
           "Assembly drawing",
           "Every part of the drive on its own layer: the disc profile as a "
           "closed LWPOLYLINE sampled to the chord tolerance, plus bore, output "
           "holes, ring pins, housing and pitch circle. For reading, not for "
           "cutting."),
    Output("assembly_svg", "disc.svg", "drawings", "SVG",
           "Assembly drawing",
           "The same drawing at 1 unit = 1 mm, for a browser, a document, or a "
           "laser cutter's front end."),
    Output("part_dxf", "dxf/", "drawings", "DXF",
           "Cutting files, one per part",
           "One closed outline and its holes per file, which is what a laser, "
           "waterjet or CAM job wants. Each disc in a stack gets its own file "
           "because their hole patterns differ. The carrier template is drilled "
           "for the press fit, not for the disc's running hole.",
           contents=lambda s: [f"{n}.dxf" for n in disc_names(s)]
           + ["ring_plate.dxf", "output_carrier.dxf"]),
    Output("assembly_step", "assembly.step", "solids", "STEP",
           "Assembled gearbox",
           "Housing, ring pins, phased discs, eccentric shaft and output "
           "carrier as one coloured STEP assembly, at crank angle zero. For "
           "checking fit and for dropping into a larger model."),
    Output("part_step", "step/", "solids", "STEP",
           "Solids, one per part",
           "Each part in its own frame, for handing one part to a machine shop "
           "or to a CAM package that would otherwise make you fish the body out "
           "of an assembly first.",
           contents=lambda s: [f"{n}.step" for n in part_names(s)]),
    Output("stl", "stl/", "solids", "STL",
           "Meshes, one per part",
           "Tessellated to the STL linear tolerance in the design. STL carries "
           "no assembly structure and no colour, so a multi-disc stack arrives "
           "as separate files - and they are not interchangeable.",
           contents=lambda s: [f"{n}.stl" for n in part_names(s)]),
    Output("bom", "bom.csv", "data", "CSV",
           "Bill of materials",
           "Every part with quantity, material, size, mass and make-or-buy, "
           "plus the bearing designations the sizing study picked."),
    Output("json", "report.json", "data", "JSON",
           "Machine-readable report",
           "Every parameter, derived value, load, stiffness, temperature, mass "
           "and finding as plain data. This is the file to script against."),
    Output("pdf", "report.pdf", "data", "PDF",
           "Design dossier",
           "Drawing, 3D view, geometry, checks, contact stress, stiffness and "
           "backlash, PV and temperature, mass, bill of materials, bearings, "
           "and a build order."),
    Output("gif", "motion.gif", "animation", "GIF",
           "The drive turning",
           "A looping animation of the drawing, contacts and contact forces "
           "included, off the same kinematics as the checks. The run is chosen "
           "so that the mechanism is back where it started when the loop "
           "restarts."),
)


def group_keys() -> tuple[str, ...]:
    return tuple(g.key for g in GROUPS)


def resolve_groups(include_solids: bool = True,
                   groups: Collection[str] | None = None) -> set[str]:
    """Turn either way of asking into the set of groups to write.

    ``include_solids`` is the original argument and stays supported because the
    CLI flag, the tests and other people's scripts are written against it.
    """
    if groups is not None:
        unknown = set(groups) - set(group_keys())
        if unknown:
            raise ValueError(f"unknown output group(s): {', '.join(sorted(unknown))}")
        return set(groups)
    chosen = set(group_keys())
    if not include_solids:
        chosen.discard("solids")
    return chosen


def outputs_for(groups: Collection[str]) -> list[Output]:
    return [o for o in MANIFEST if o.group in groups]


def planned_files(spec: GearSpec,
                  groups: Iterable[str] | None = None) -> list[tuple[Output, str]]:
    """Every file an export of ``spec`` would write, in bundle order."""
    chosen = set(groups) if groups is not None else set(group_keys())
    return [(out, name) for out in outputs_for(chosen) for name in out.files(spec)]
