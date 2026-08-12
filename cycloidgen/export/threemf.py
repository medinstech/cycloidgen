"""3MF: the assembled gearbox in one file, coloured, for a printer.

The STL entry in the manifest states the problem this solves in its own
description - *STL carries no assembly structure and no colour, so a multi-disc
stack arrives as separate files, and they are not interchangeable*.  Every one
of those facts is a thing the app knows and the file cannot say.  3MF is the
same triangles with the sentence finished: one container, every part where it
belongs, each with the colour the 3D view paints it and the material the bill of
materials orders it in.

Three decisions are worth naming, because each had a plausible alternative.

**Made parts only, and assembled.**  What is in here is exactly what is in
``stl/`` - the bearings and the tie bolts are bought, and a mesh of a bearing is
a fit check at best and something someone tries to print at worst.  They are
placed as they assemble rather than laid out on a plate: arranging is what a
slicer does in one click, and *which way up* each part should be printed is a
question about walls and layer adhesion that this app has not been given the
means to answer.  What it can say without guessing is where each part goes.

**One object per distinct part, referenced once per instance.**  A stack of two
different discs is two objects; a stack of two identical ones is a single object
built twice, which is the same statement the file names make in ``stl/`` and is
the one thing an STL folder cannot say without being read.  The transform is the
assembly's own, so the 3MF and the STEP cannot come apart.

**Base materials rather than a colour group.**  The materials extension has a
richer colour model, but colour is not the only thing to carry here: a base
material has a *name*, and the name is what the part is made of.  One entry per
part, named for the part and its material, so a slicer's material list reads
``housing - PLA`` rather than four indistinguishable greys - and the file needs
no extension for a reader to understand it.

The triangles come from the same tessellation, at the same tolerances, that
writes the STLs.  Two files of one part that disagree about its geometry would
be worse than either on its own.
"""
from __future__ import annotations

import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import cadquery as cq

from .. import __version__
from ..core.spec import GearSpec
from .manifest import part_names
from .solid import build_assembly

__all__ = ["model_xml", "write_3mf"]

_MODEL_PATH = "3D/3dmodel.model"
_CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_MODEL_REL = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"

#: Coordinates are rounded to a nanometre before duplicate points are merged.
#: OCCT triangulates face by face and each face brings its own copy of the
#: points along its edges, so the raw tessellation is a heap of loose facets -
#: the same thing the 3D view was, and the same fix.  3MF asks for a manifold
#: mesh rather than tolerating a soup of triangles the way STL does, and a
#: printer that has to guess at what is inside a part guesses wrong somewhere.
_WELD_DECIMALS = 6

#: Every part's angular tessellation tolerance, matching :func:`solid.write_stls`.
_ANGULAR_TOLERANCE = 0.1

#: What each made part is made of, as the field on the spec that says so.  It
#: mirrors :mod:`cycloidgen.analysis.mass`, which is where the decision is
#: actually made - the carrier, the end plates and the end cap are all the
#: housing's material because they are all the same casting or billet job.
#:
#: A part with no entry here is refused rather than defaulted: a made part the
#: mass model had not been told about once shipped a gearbox that weighed less
#: on paper than in the hand, and a part exported as an unnamed material is the
#: same mistake with a printer at the end of it.
_PART_MATERIAL: dict[str, str] = {
    "housing": "housing_material",
    "ring_pins": "pin_material",
    "eccentric_shaft": "shaft_material",
    "output_flange": "housing_material",
    "end_cap": "housing_material",
    "input_end_plate": "housing_material",
    "output_end_plate": "housing_material",
}


def _num(value: float) -> str:
    """A coordinate as short as it can be written without losing the weld grid."""
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-", "-0") else text


def _material_of(spec: GearSpec, part: str) -> str:
    """The material name for a made part.  Discs are the only family."""
    if part == "disc" or part.startswith("disc_"):
        return spec.disc_material
    try:
        return getattr(spec, _PART_MATERIAL[part])
    except KeyError:                                     # pragma: no cover - guard
        raise KeyError(f"no material declared for part {part!r}") from None


def _distinct(spec: GearSpec, name: str) -> str:
    """The assembly's name for a part, as the manifest names the file for it.

    The assembly always numbers the discs, because it places two of them; the
    manifest collapses them to one name when they are the same part.  That is
    the whole of the difference between the two vocabularies.
    """
    if name.startswith("disc_") and spec.discs_are_identical:
        return "disc"
    return name


def _weld(shape: cq.Shape, tolerance: float) -> tuple[list[tuple[float, float, float]],
                                                      list[tuple[int, int, int]]]:
    """Tessellate one solid and merge the points its faces duplicate.

    A triangle left with two identical corners after the merge is dropped: it
    encloses nothing, and a zero-area facet is a hole as far as a mesh repair
    pass is concerned.
    """
    vertices, triangles = shape.tessellate(tolerance, _ANGULAR_TOLERANCE)
    index: dict[tuple[float, float, float], int] = {}
    remap: list[int] = []
    for v in vertices:
        key = (round(v.x, _WELD_DECIMALS), round(v.y, _WELD_DECIMALS),
               round(v.z, _WELD_DECIMALS))
        remap.append(index.setdefault(key, len(index)))
    welded = [(remap[a], remap[b], remap[c]) for a, b, c in triangles]
    return list(index), [t for t in welded if len(set(t)) == 3]


def _matrix(loc: cq.Location) -> tuple[float, ...]:
    """A placement as 3MF's twelve numbers.

    3MF multiplies a *row* vector by the matrix, so its rows are OCCT's columns:
    ``x' = m00*x + m10*y + m20*z + m30``.  Transposing it by hand rather than
    reading the twelve off in order is the difference between a rotated disc and
    a mirrored one.
    """
    t = loc.wrapped.Transformation()
    return tuple(t.Value(row, col) for col in (1, 2, 3, 4) for row in (1, 2, 3))


@dataclass(frozen=True)
class _Object:
    """One distinct made part: a mesh, a colour and a material."""

    id: int
    part: str
    material: str
    colour: tuple[float, float, float, float]
    vertices: list[tuple[float, float, float]]
    triangles: list[tuple[int, int, int]]

    @property
    def display_colour(self) -> str:
        r, g, b, a = self.colour
        return "#" + "".join(f"{round(c * 255.0):02X}" for c in (r, g, b, a))


def _collect(spec: GearSpec) -> tuple[list[_Object], list[tuple[int, tuple[float, ...]]]]:
    """Walk the assembly once: distinct parts out of it, instances with it.

    Reading the placements off the assembly rather than working them out again
    is the point - the STEP file, the 3D view and this all put the carrier the
    same distance below the discs because there is one piece of code that knows
    how far that is.
    """
    made = set(part_names(spec))
    tolerance = spec.stl_linear_tolerance
    objects: dict[str, _Object] = {}
    items: list[tuple[int, tuple[float, ...]]] = []

    for child in build_assembly(spec).children:
        part = _distinct(spec, child.name)
        if part not in made:                    # bearings and bolts are bought
            continue
        obj = objects.get(part)
        if obj is None:
            shape = child.obj.val() if isinstance(child.obj, cq.Workplane) else child.obj
            vertices, triangles = _weld(shape, tolerance)
            colour = child.color.toTuple() if child.color is not None else (
                0.7, 0.7, 0.7, 1.0)
            obj = _Object(id=len(objects) + 2, part=part,
                          material=_material_of(spec, part), colour=colour,
                          vertices=vertices, triangles=triangles)
            objects[part] = obj
        items.append((obj.id, _matrix(child.loc)))
    return list(objects.values()), items


def _lift(objects: list[_Object],
          items: list[tuple[int, tuple[float, ...]]]) -> list[tuple[int, tuple[float, ...]]]:
    """Raise the whole assembly onto the build platform.

    3MF puts the platform at ``z = 0`` and the drive is modelled around the disc
    stack, so the carrier and the output plate hang below it.  One translation
    for all of them, and it moves the assembly *onto* the plate rather than off
    the bottom of it: a gearbox floating above the bed is the same wrong answer
    as one buried in it, and only one of the two is obvious on screen.

    Measured from the meshes rather than from a bounding box, because a bounding
    box of a solid is inflated by the kernel's own tolerance and this is a
    number the file states exactly.
    """
    by_id = {obj.id: obj for obj in objects}
    floor = min((m[2] * x + m[5] * y + m[8] * z + m[11]
                 for oid, m in items
                 for x, y, z in by_id[oid].vertices), default=0.0)
    return [(oid, (*m[:11], m[11] - floor)) for oid, m in items]


def model_xml(spec: GearSpec) -> str:
    """The 3MF model part, as text.  The zip around it carries nothing else."""
    objects, items = _collect(spec)
    items = _lift(objects, items)

    out: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<model unit="millimeter" xml:lang="en-US" xmlns="{_CORE_NS}">',
        f' <metadata name="Application">cycloidgen {__version__}</metadata>',
        f' <metadata name="Title">{escape(f"Cycloidal drive {spec.ratio}:1")}</metadata>',
        ' <metadata name="Description">Made parts only, assembled; bearings and '
        'fasteners are bought</metadata>',
        ' <resources>',
        '  <basematerials id="1">',
    ]
    for obj in objects:
        name = quoteattr(f"{obj.part} - {obj.material}")
        out.append(f'   <base name={name} displaycolor="{obj.display_colour}"/>')
    out.append('  </basematerials>')

    for index, obj in enumerate(objects):
        out.append(f'  <object id="{obj.id}" type="model" pid="1" pindex="{index}" '
                   f'name={quoteattr(obj.part)}>')
        out.append('   <mesh>')
        out.append('    <vertices>')
        out.extend(f'     <vertex x="{_num(x)}" y="{_num(y)}" z="{_num(z)}"/>'
                   for x, y, z in obj.vertices)
        out.append('    </vertices>')
        out.append('    <triangles>')
        out.extend(f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>'
                   for a, b, c in obj.triangles)
        out.append('    </triangles>')
        out.append('   </mesh>')
        out.append('  </object>')
    out.append(' </resources>')

    out.append(' <build>')
    for oid, matrix in items:
        out.append(f'  <item objectid="{oid}" '
                   f'transform="{" ".join(_num(v) for v in matrix)}"/>')
    out.append(' </build>')
    out.append('</model>')
    return "\n".join(out) + "\n"


_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" \
ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" \
ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
</Types>
"""

_RELS = f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rel0" Target="/{_MODEL_PATH}" Type="{_MODEL_REL}"/>
</Relationships>
"""

#: A fixed timestamp for every entry, so that exporting the same design twice
#: gives the same bytes.  Nothing about a design changes between two exports of
#: it, and a file that differs anyway cannot be compared against a known-good
#: one.  1980-01-01 is the earliest a zip can record.
_EPOCH = (1980, 1, 1, 0, 0, 0)


def _parts(spec: GearSpec) -> Iterator[tuple[str, str]]:
    yield "[Content_Types].xml", _CONTENT_TYPES
    yield "_rels/.rels", _RELS
    yield _MODEL_PATH, model_xml(spec)


def write_3mf(spec: GearSpec, path: str | Path) -> Path:
    """Write the assembled gearbox as one 3MF container."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in _parts(spec):
            info = zipfile.ZipInfo(name, date_time=_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, text.encode("utf-8"))
    return path
