"""The 3MF container, opened and checked rather than sized.

There is no 3MF reader in this environment to lean on, which is just as well:
the interesting questions are about the file's own content - is each shell
closed, does it enclose the solid it stands for, is each part where the assembly
put it - and a library that repaired a mesh on the way in would answer them all
with a shrug.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile

import pytest

from cycloidgen.core.spec import OutputMember, preset
from cycloidgen.export import manifest, solid, threemf

NS = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}


# ------------------------------------------------------------------- helpers --


def _model(path) -> ET.Element:
    with zipfile.ZipFile(path) as zf:
        return ET.fromstring(zf.read("3D/3dmodel.model"))


def _objects(model: ET.Element) -> list[ET.Element]:
    return model.findall("m:resources/m:object", NS)


def _mesh(obj: ET.Element):
    verts = [(float(v.get("x")), float(v.get("y")), float(v.get("z")))
             for v in obj.findall("m:mesh/m:vertices/m:vertex", NS)]
    tris = [(int(t.get("v1")), int(t.get("v2")), int(t.get("v3")))
            for t in obj.findall("m:mesh/m:triangles/m:triangle", NS)]
    return verts, tris


def _volume(verts, tris) -> float:
    """Signed volume by the divergence theorem: positive means outward normals."""
    total = 0.0
    for a, b, c in tris:
        (px, py, pz), (qx, qy, qz), (rx, ry, rz) = verts[a], verts[b], verts[c]
        total += (px * (qy * rz - qz * ry)
                  - py * (qx * rz - qz * rx)
                  + pz * (qx * ry - qy * rx)) / 6.0
    return total


def _apply(m: list[float], point) -> tuple[float, float, float]:
    """3MF multiplies a row vector by the matrix, so its rows are the columns."""
    x, y, z = point
    return (m[0] * x + m[3] * y + m[6] * z + m[9],
            m[1] * x + m[4] * y + m[7] * z + m[10],
            m[2] * x + m[5] * y + m[8] * z + m[11])


def _items(model: ET.Element) -> list[tuple[int, list[float]]]:
    return [(int(i.get("objectid")),
             [float(v) for v in i.get("transform").split()])
            for i in model.findall("m:build/m:item", NS)]


@pytest.fixture(scope="module")
def spec():
    s = preset(15)
    s.disc_count = 2
    return s


@pytest.fixture(scope="module")
def path(spec, tmp_path_factory):
    return threemf.write_3mf(spec, tmp_path_factory.mktemp("3mf") / "assembly.3mf")


@pytest.fixture(scope="module")
def model(path):
    return _model(path)


# ----------------------------------------------------------------- container --


def test_the_container_holds_what_a_reader_opens_it_by(path):
    """A 3MF is an OPC package: the model is found through the relationship."""
    with zipfile.ZipFile(path) as zf:
        assert zf.namelist()[0] == "[Content_Types].xml"
        assert set(zf.namelist()) == {"[Content_Types].xml", "_rels/.rels",
                                      "3D/3dmodel.model"}
        types = zf.read("[Content_Types].xml").decode()
        rels = ET.fromstring(zf.read("_rels/.rels"))
    assert "3dmanufacturing-3dmodel+xml" in types
    (rel,) = list(rels)
    assert rel.get("Target") == "/3D/3dmodel.model"
    assert rel.get("Type").endswith("/3dmodel")


def test_the_model_says_millimetres_and_which_build_wrote_it(model):
    from cycloidgen import __version__
    assert model.get("unit") == "millimeter"
    stamps = {m.get("name"): m.text for m in model.findall("m:metadata", NS)}
    assert stamps["Application"] == f"cycloidgen {__version__}"
    assert "15:1" in stamps["Title"]


def test_two_exports_of_one_design_are_the_same_bytes(spec, path, tmp_path):
    """Nothing about a design changes between two exports of it.

    A file that differs anyway - a timestamp, a set iteration order - cannot be
    compared against a known-good one, which is most of what a mesh export is
    checked with.
    """
    again = threemf.write_3mf(spec, tmp_path / "again.3mf")
    assert again.read_bytes() == path.read_bytes()


# ---------------------------------------------------------------- the meshes --


def test_every_object_is_a_closed_manifold_shell(model):
    """What 3MF asks for and STL does not.

    Each directed edge exactly once, and its opposite present: that is closed
    (no holes), manifold (no edge shared by three faces) and consistently wound,
    in one pass.
    """
    for obj in _objects(model):
        verts, tris = _mesh(obj)
        assert tris, obj.get("name")
        edges = set()
        for a, b, c in tris:
            for edge in ((a, b), (b, c), (c, a)):
                assert edge not in edges, f"{obj.get('name')}: {edge} twice"
                edges.add(edge)
        unpaired = [e for e in edges if (e[1], e[0]) not in edges]
        assert not unpaired, f"{obj.get('name')}: {len(unpaired)} boundary edges"
        assert len(verts) == len({v for tri in tris for v in tri})


def test_each_object_encloses_the_volume_its_solid_does(spec, model):
    """The mesh is the solid, tessellated - not a second model of the part.

    The volume is signed, so this also fixes the winding: a shell wound inwards
    encloses a negative volume, and a printer given one fills the room instead
    of the part.

    Which side of the exact figure it lands on is the curvature's to decide,
    and the discs are the only part where it is not the convex one. Everything
    else is bores and circles cut out of a prism, where a chord falls inside the
    surface and takes material with it; a cycloidal flank is concave between the
    lobes, so there the chord falls outside and adds a little.
    """
    solids = solid.parts(spec)
    for obj in _objects(model):
        verts, tris = _mesh(obj)
        name = obj.get("name")
        mesh_volume = _volume(verts, tris)
        exact = solids[name].val().Volume()
        assert mesh_volume > 0.0, name
        assert mesh_volume == pytest.approx(exact, rel=0.01), name
        if not name.startswith("disc"):
            assert mesh_volume < exact, name


# ------------------------------------------------------------- what is in it --


def test_the_bought_parts_are_not_in_it(spec, model):
    """Made parts only, and exactly the ones the STL folder holds.

    An STL of a bearing is a fit check at best and a part someone tries to print
    at worst; fit is checked in the STEP assembly and bearings are ordered from
    the bill of materials.
    """
    names = [obj.get("name") for obj in _objects(model)]
    assert sorted(names) == sorted(manifest.part_names(spec))
    assert not any("bearing" in n or "bolt" in n for n in names)


def test_different_discs_are_two_objects_and_identical_ones_are_one(spec, model,
                                                                    tmp_path):
    """The thing a folder of STLs can only say in its file names.

    A stack is normally two *different* parts and the file has to carry that;
    when the pre-rotation lands on a whole hole pitch they really are the same
    part, and then one object placed twice is the honest statement.
    """
    ids = [oid for oid, _ in _items(model)]
    assert len(ids) == len(set(ids))              # every part built once here
    assert len([n for n in (o.get("name") for o in _objects(model))
                if n.startswith("disc")]) == 2

    same = preset(10)
    same.disc_count = 2
    same.output_pin_count = 2 * same.lobes        # the rare identical case
    assert same.discs_are_identical
    model2 = _model(threemf.write_3mf(same, tmp_path / "same.3mf"))
    discs = [o for o in _objects(model2) if o.get("name") == "disc"]
    assert len(discs) == 1
    disc_id = int(discs[0].get("id"))
    assert [oid for oid, _ in _items(model2)].count(disc_id) == 2


def test_integral_ring_pins_are_not_a_part_here_either(tmp_path):
    s = preset(21)
    s.ring_pins_integral = True
    model = _model(threemf.write_3mf(s, tmp_path / "integral.3mf"))
    names = [obj.get("name") for obj in _objects(model)]
    assert "ring_pins" not in names
    assert sorted(names) == sorted(manifest.part_names(s))


# -------------------------------------------------------- colour and material --


def test_every_object_carries_its_material_and_the_viewer_s_colour(spec, model):
    """One palette, and the material the bill of materials orders."""
    from cycloidgen.viz.mesh import PART_COLOURS
    bases = model.findall("m:resources/m:basematerials/m:base", NS)
    assert len(bases) == len(_objects(model))
    for obj in _objects(model):
        base = bases[int(obj.get("pindex"))]
        assert obj.get("pid") == "1"
        name, material = base.get("name").rsplit(" - ", 1)
        assert name == obj.get("name")
        assert material in {spec.disc_material, spec.pin_material,
                            spec.housing_material, spec.shaft_material}
        assert base.get("displaycolor").endswith("FF")     # opaque, 8 hex digits
        assert len(base.get("displaycolor")) == 9

    housing = next(b for b in bases if b.get("name").startswith("housing "))
    r, g, b = PART_COLOURS["housing"]
    assert housing.get("displaycolor") == f"#{r:02X}{g:02X}{b:02X}FF"


def test_the_discs_are_the_disc_material_and_the_shaft_is_not(spec, model):
    bases = {b.get("name").split(" - ")[0]: b.get("name").split(" - ")[1]
             for b in model.findall("m:resources/m:basematerials/m:base", NS)}
    assert bases["disc_1"] == spec.disc_material
    assert bases["eccentric_shaft"] == spec.shaft_material
    assert bases["ring_pins"] == spec.pin_material
    assert bases["output_flange"] == spec.housing_material


def test_every_made_part_declares_a_material(spec):
    """The drift guard, for both drives.

    A ring-output drive has an end cap that a carrier-output one does not, and a
    part the material table has not been told about would export as somebody
    else's plastic.  This is the same failure the mass model had once, where a
    part it did not know about made the gearbox lighter on paper than in the
    hand.
    """
    for member in OutputMember:
        s = preset(21)
        s.output_member = member
        for part in manifest.part_names(s):
            assert threemf._material_of(s, part)


# ------------------------------------------------------------------ placement --


def test_the_assembly_arrives_assembled_and_on_the_build_platform(spec, model):
    """Placed as it goes together, with nothing under the plate.

    3MF puts the platform at ``z = 0``; the drive is modelled around its disc
    stack, so the carrier and the output plate hang below that and the whole
    thing is lifted by one translation rather than each part being dropped
    somewhere of its own.
    """
    by_id = {int(o.get("id")): _mesh(o) for o in _objects(model)}
    zs = [_apply(m, p)[2] for oid, m in _items(model) for p in by_id[oid][0]]
    assert min(zs) == pytest.approx(0.0, abs=1e-6)
    assert max(zs) > spec.stack_height            # still one assembled gearbox

    # and the parts are still stacked, not spread out on a plate
    spans = []
    for oid, m in _items(model):
        xy = [_apply(m, p)[:2] for p in by_id[oid][0]]
        spans.append(max(max(abs(x), abs(y)) for x, y in xy))
    assert max(spans) < 2.0 * spec.housing_outer_radius


def test_a_disc_is_placed_where_the_step_assembly_places_it(spec, model):
    """The transform is the assembly's own, phase rotation included.

    Two of these numbers could be transposed without anyone noticing on a round
    part: the second disc is meshed at its own angle, so it is the one that
    catches a matrix written out in the wrong order.
    """
    import cadquery as cq

    child = next(c for c in solid.build_assembly(spec).children
                 if c.name == "disc_2")
    placed = cq.Workplane(child.obj.val().moved(child.loc)).val().BoundingBox()

    ids = {o.get("name"): int(o.get("id")) for o in _objects(model)}
    meshes = {int(o.get("id")): _mesh(o) for o in _objects(model)}
    matrix = next(m for oid, m in _items(model) if oid == ids["disc_2"])
    points = [_apply(matrix, p) for p in meshes[ids["disc_2"]][0]]

    assert min(p[0] for p in points) == pytest.approx(placed.xmin, abs=0.05)
    assert max(p[0] for p in points) == pytest.approx(placed.xmax, abs=0.05)
    assert min(p[1] for p in points) == pytest.approx(placed.ymin, abs=0.05)
    assert max(p[1] for p in points) == pytest.approx(placed.ymax, abs=0.05)
    # z is the one axis the platform lift moves, and it moves all of them alike
    assert (max(p[2] for p in points) - min(p[2] for p in points)) == pytest.approx(
        placed.zmax - placed.zmin, abs=0.05)


def test_a_ring_output_drive_brings_its_end_cap(tmp_path):
    s = preset(21)
    s.output_member = OutputMember.RING
    model = _model(threemf.write_3mf(s, tmp_path / "ring.3mf"))
    names = [obj.get("name") for obj in _objects(model)]
    assert "end_cap" in names
    assert sorted(names) == sorted(manifest.part_names(s))
