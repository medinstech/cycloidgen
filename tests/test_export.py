"""Export round-trips.  Every format is re-opened and checked, not just sized."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import ezdxf
import matplotlib
import numpy as np
import pytest

matplotlib.use("Agg")

from cycloidgen.analysis import analyse                       # noqa: E402
from cycloidgen.core import profile as prof                   # noqa: E402
from cycloidgen.core.spec import preset                       # noqa: E402
from cycloidgen.export import dxf, solid, svg                  # noqa: E402
from cycloidgen.report import build                            # noqa: E402


@pytest.fixture(scope="module")
def spec():
    s = preset(15)
    s.disc_count = 2
    return s


def test_dxf_reopens_with_a_closed_profile(spec, tmp_path):
    path = dxf.write_dxf(spec, tmp_path / "d.dxf")
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    polys = msp.query('LWPOLYLINE[layer=="DISC_PROFILE"]')
    assert len(polys) == 1
    poly = polys[0]
    assert poly.closed
    pts = np.array([(p[0], p[1]) for p in poly.get_points()])
    r = np.hypot(*pts.T)
    assert r.min() == pytest.approx(
        spec.effective_R - spec.effective_Rr - spec.eccentricity, abs=1e-3)
    assert len(msp.query('CIRCLE[layer=="RING_PINS"]')) == spec.pin_count
    # a multi-disc stack gets one hole layer per disc: they are different parts
    holes = msp.query('CIRCLE[layer ? "OUTPUT_HOLES.*"]')
    assert len(holes) == spec.output_pin_count * spec.disc_count


def test_svg_is_wellformed_and_scaled(spec, tmp_path):
    path = svg.write_svg(spec, tmp_path / "d.svg")
    root = ET.parse(path).getroot()
    assert root.tag.endswith("svg")
    assert root.get("width").endswith("mm")
    assert len(root.findall(".//{http://www.w3.org/2000/svg}path")) == 1


def test_step_assembly_reimports_with_every_part(spec, tmp_path):
    import cadquery as cq
    path = solid.write_step(spec, tmp_path / "a.step")
    assert path.stat().st_size > 10_000
    imported = cq.importers.importStep(str(path))
    solids = imported.val().Solids()
    # housing + pins + 2 discs + shaft + flange, pins/cams counted individually
    assert len(solids) >= 4 + spec.pin_count


def test_stls_are_binary_and_watertight_enough(spec, tmp_path):
    paths = solid.write_stls(spec, tmp_path / "stl")
    assert {p.stem for p in paths} == {"disc_1", "disc_2", "housing", "ring_pins",
                                       "eccentric_shaft", "output_flange"}
    for p in paths:
        raw = p.read_bytes()
        assert len(raw) > 84
        count = int.from_bytes(raw[80:84], "little")
        assert count > 0
        assert len(raw) == 84 + count * 50, f"{p.name} triangle count mismatch"


def test_disc_solid_volume_matches_the_planar_area(spec):
    """Guards against the outline being built from the wrong point set."""
    p = prof.profile_from_spec(spec)
    x, y = p.points[:, 0], p.points[:, 1]
    area = 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))
    bore = np.pi * ((spec.center_bore_diameter + spec.hole_clearance) / 2) ** 2
    holes = spec.output_pin_count * np.pi * (spec.output_hole_diameter / 2) ** 2
    expected = (area - bore - holes) * spec.disc_thickness
    assert solid.disc_solid(spec).val().Volume() == pytest.approx(expected, rel=2e-3)


def test_json_report_round_trips(spec, tmp_path):
    a = analyse(spec)
    data = json.loads(build.write_json(a, tmp_path / "r.json").read_text())
    assert data["derived"]["ratio"] == spec.ratio
    assert data["derived"]["pin_count"] == spec.pin_count
    assert data["contact"]["max_pin_force_N"] > 0
    assert 0 < data["efficiency"]["efficiency"] < 1
    assert len(data["bearings"]) == 3
    assert data["spec"]["lobes"] == spec.lobes


def test_pdf_is_produced(spec, tmp_path):
    a = analyse(spec)
    path = build.write_pdf(a, tmp_path / "r.pdf")
    raw = path.read_bytes()
    assert raw.startswith(b"%PDF-")
    assert raw.rstrip().endswith(b"%%EOF")
    assert len(raw) > 50_000


def test_export_bundle_writes_everything(spec, tmp_path):
    from cycloidgen.export import write_bundle
    files = write_bundle(spec, tmp_path / "bundle")
    names = {f.name for f in files}
    assert {"disc.dxf", "disc.svg", "assembly.step", "report.json",
            "report.pdf", "bom.csv"} <= names
    assert all(f.exists() and f.stat().st_size > 0 for f in files)


# ----------------------------------------------------------- per-part output


def test_part_dxfs_hold_one_part_each(spec, tmp_path):
    """``disc.dxf`` is a drawing of the whole drive; these are cutting files, so
    a disc file must contain the disc and nothing else."""
    paths = dxf.write_part_dxfs(spec, tmp_path / "dxf")
    assert {p.stem for p in paths} == {"disc_1", "disc_2", "ring_plate",
                                       "output_carrier"}
    for name in ("disc_1", "disc_2"):
        msp = ezdxf.readfile(tmp_path / "dxf" / f"{name}.dxf").modelspace()
        assert len(msp.query('LWPOLYLINE[layer=="DISC_PROFILE"]')) == 1
        assert len(msp.query('CIRCLE[layer=="OUTPUT_HOLES"]')) == spec.output_pin_count
        assert len(msp.query('CIRCLE[layer=="DISC_BORE"]')) == 1
        assert len(msp.query('CIRCLE[layer=="RING_PINS"]')) == 0   # not this part


def test_the_two_disc_files_differ_by_the_hole_phase(spec, tmp_path):
    """The whole multi-disc trap in one test: same outline, rotated holes."""
    dxf.write_part_dxfs(spec, tmp_path / "dxf")

    def holes(name):
        msp = ezdxf.readfile(tmp_path / "dxf" / f"{name}.dxf").modelspace()
        return sorted(np.arctan2(c.dxf.center.y, c.dxf.center.x)
                      for c in msp.query('CIRCLE[layer=="OUTPUT_HOLES"]'))

    a, b = holes("disc_1"), holes("disc_2")
    expected = spec.disc_hole_phases[1] - spec.disc_hole_phases[0]
    assert not np.allclose(a, b)
    assert (b[0] - a[0]) == pytest.approx(expected, abs=1e-6)


def test_the_carrier_template_drills_the_press_fit_not_the_running_hole(spec, tmp_path):
    """Drilling the disc's running hole into the carrier gives you a gearbox
    with no output coupling at all."""
    dxf.write_part_dxfs(spec, tmp_path / "dxf")
    msp = ezdxf.readfile(tmp_path / "dxf" / "output_carrier.dxf").modelspace()
    circles = msp.query('CIRCLE[layer=="OUTPUT_HOLES"]')
    assert len(circles) == spec.output_pin_count
    for c in circles:
        assert c.dxf.radius == pytest.approx(spec.output_pin_diameter / 2)
        assert c.dxf.radius < spec.output_hole_diameter / 2


def test_part_steps_are_written_one_per_distinct_part(spec, tmp_path):
    import cadquery as cq
    paths = solid.write_part_steps(spec, tmp_path / "step")
    assert {p.stem for p in paths} == {"disc_1", "disc_2", "housing", "ring_pins",
                                       "eccentric_shaft", "output_flange"}
    disc = cq.importers.importStep(str(tmp_path / "step" / "disc_1.step"))
    assert disc.val().Volume() == pytest.approx(
        solid.disc_solid(spec, spec.disc_hole_phases[0]).val().Volume(), rel=1e-6)


def test_identical_discs_collapse_to_one_file(tmp_path):
    """When the hole pre-rotation happens to be a whole hole pitch there is only
    one part, and shipping two files would imply otherwise."""
    # needs output_pin_count == 2*lobes, which the 24-pin cap only allows for
    # short ratios - which is exactly why this case is rare in practice
    s = preset(10)
    s.disc_count = 2
    s.output_pin_count = 2 * s.lobes
    assert s.discs_are_identical
    names = {p.stem for p in dxf.write_part_dxfs(s, tmp_path / "dxf")}
    assert "disc" in names and "disc_1" not in names


# --------------------------------------------------------------------- BOM


def test_bom_lists_every_part_with_quantities(spec):
    from cycloidgen.export.bom import bom_items
    items = bom_items(analyse(spec))
    by_part = {i.part: i for i in items}
    assert by_part["Ring pin (dowel)"].quantity == spec.pin_count
    assert by_part["Output pin (dowel)"].quantity == spec.output_pin_count
    assert by_part["Ring housing"].quantity == 1
    assert {i.source for i in items} <= {"make", "buy"}


def test_bom_calls_out_that_the_discs_are_different_parts(spec):
    from cycloidgen.export.bom import bom_items
    discs = [i for i in bom_items(analyse(spec)) if i.part.startswith("Cycloidal disc")]
    assert len(discs) == spec.disc_count
    assert all("NOT interchangeable" in i.note for i in discs)


def test_bom_mass_agrees_with_the_analysis(spec):
    from cycloidgen.export.bom import bom_items
    a = analyse(spec)
    made = sum(i.mass_total_g for i in bom_items(a) if i.source == "make")
    pins = sum(i.mass_total_g for i in bom_items(a) if i.part.endswith("(dowel)"))
    assert made + pins == pytest.approx(a.mass.total_mass_g, rel=1e-6)


def test_bom_csv_round_trips(spec, tmp_path):
    import csv
    from cycloidgen.export.bom import write_bom_csv
    path = write_bom_csv(analyse(spec), tmp_path / "bom.csv")
    rows = list(csv.reader(path.open(encoding="utf-8")))
    assert rows[0][0] == "Part"
    assert any(r and r[0] == "Assembled mass (g)" for r in rows)
    assert len([r for r in rows if r and r[0].startswith("Cycloidal disc")]) == 2


def test_json_report_carries_the_new_studies(spec, tmp_path):
    a = analyse(spec)
    data = json.loads(build.write_json(a, tmp_path / "r.json").read_text())
    assert data["stiffness"]["lost_motion_arcmin"] > 0
    assert data["thermal"]["temperature_C"] > 0
    assert data["mass"]["total_mass_g"] > 0
    assert data["contact"]["torque_capacity_with_clearance_Nm"] <= \
        data["contact"]["torque_capacity_Nm"]
    assert len(data["bom"]) >= 6
