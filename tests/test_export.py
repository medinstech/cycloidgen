"""Export round-trips.  Every format is re-opened and checked, not just sized."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import ezdxf
import matplotlib
import numpy as np
import pytest

matplotlib.use("Agg")

from cycloidgen.analysis import analyse
from cycloidgen.core import profile as prof
from cycloidgen.core.spec import preset
from cycloidgen.export import dxf, solid, svg
from cycloidgen.report import build


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
                                       "eccentric_shaft", "output_flange",
                                       "input_end_plate", "output_end_plate"}
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
    assert len(data["bearings"]) == 4 + int(spec.ring_pins_are_rollers)
    assert data["spec"]["lobes"] == spec.lobes


def test_pdf_is_produced(spec, tmp_path):
    a = analyse(spec)
    path = build.write_pdf(a, tmp_path / "r.pdf")
    raw = path.read_bytes()
    assert raw.startswith(b"%PDF-")
    assert raw.rstrip().endswith(b"%%EOF")
    assert len(raw) > 50_000


def test_the_letterhead_survives_a_machine_with_no_qt():
    """The dossier is written headless more often than not - CI, a notebook, a
    ``python -m cycloidgen --out`` run - and it used to lose its wordmark there
    and say nothing about it, because the asset *path* was looked up through a
    module that imports PySide6 in order to paint with.  One design in, two
    different PDFs out, decided by whether Qt happened to be installed.  The
    difference only shows where PySide6 cannot be imported at all, so that is
    what the subprocess arranges.
    """
    import subprocess
    import sys

    code = """
import sys
class Block:
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] == 'PySide6':
            raise ImportError('no Qt on this machine')
sys.meta_path.insert(0, Block())
from cycloidgen.report.build import _letterhead
print(type(_letterhead()).__name__, 'PySide6' in sys.modules)
"""
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, check=True)
    assert out.stdout.split() == ["Image", "False"], (
        f"headless letterhead came back as {out.stdout.strip()!r}; a Spacer "
        "means the wordmark was dropped for want of a toolkit")


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
                                       "output_carrier",
                                       "input_end_plate", "output_end_plate"}
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


def _plate(spec, tmp_path, name):
    dxf.write_part_dxfs(spec, tmp_path / "dxf")
    return ezdxf.readfile(tmp_path / "dxf" / f"{name}.dxf").modelspace()


def test_each_end_plate_is_bored_for_what_actually_sits_in_it(spec, tmp_path):
    """The plates are the same disc of metal with different holes: a shaft
    support one end, the bearing the whole drive turns on at the other.  Boring
    them alike would give the output bearing nowhere to go."""
    for name, bore in (("input_end_plate", spec.hub_bore),
                       ("output_end_plate", spec.output_bearing_seat_diameter)):
        msp = _plate(spec, tmp_path, name)
        outer = msp.query('CIRCLE[layer=="HOUSING"]')
        assert len(outer) == 1
        assert outer[0].dxf.radius == pytest.approx(spec.housing_outer_radius)
        bores = msp.query('CIRCLE[layer=="DISC_BORE"]')
        assert len(bores) == 1
        assert bores[0].dxf.radius == pytest.approx(bore / 2.0)


def test_the_tie_bolts_land_where_the_solid_puts_them(spec, tmp_path):
    """Two plates and a barrel drilled off three different circles do not bolt
    together, so the DXF has to read the same property the solid extrudes."""
    for name in ("input_end_plate", "output_end_plate"):
        msp = _plate(spec, tmp_path, name)
        bolts = msp.query('CIRCLE[layer=="BOLTS"]')
        assert len(bolts) == spec.housing_bolt_count
        for b in bolts:
            assert b.dxf.radius == pytest.approx(spec.housing_bolt_diameter / 2.0)
            assert np.hypot(b.dxf.center.x, b.dxf.center.y) == pytest.approx(
                spec.housing_bolt_radius)


def test_the_motor_pattern_is_a_square_and_only_on_the_input_plate(tmp_path):
    """A NEMA face is four bolts on a *square*.  Drilling them on a bolt circle
    of the same number is the mistake the frame table exists to stop, and it
    fits badly enough to look like it nearly worked."""
    s = preset(15)
    s.motor_frame = "NEMA 17"
    frame = s.motor_face

    msp = _plate(s, tmp_path, "input_end_plate")
    motor = msp.query('CIRCLE[layer=="MOTOR"]')
    holes = [c for c in motor
             if c.dxf.radius == pytest.approx(frame.bolt_diameter / 2.0)]
    assert len(holes) == 4
    corners = sorted((round(h.dxf.center.x, 6), round(h.dxf.center.y, 6))
                     for h in holes)
    h = frame.bolt_span / 2.0
    assert corners == sorted([(x * h, y * h) for x in (-1, 1) for y in (-1, 1)])
    # the corners sit on span*sqrt(2), which is not where a polar array of the
    # same span would have put them
    for c in corners:
        assert np.hypot(*c) == pytest.approx(frame.bolt_circle_diameter / 2.0)
        assert np.hypot(*c) != pytest.approx(frame.bolt_span / 2.0)

    # nothing bolts to the output end - that face is a boss for a coupling
    assert len(_plate(s, tmp_path, "output_end_plate").query('*[layer=="MOTOR"]')) == 0


def test_the_register_is_drawn_only_where_there_is_one_left_to_cut(tmp_path):
    """The register is what actually centres a motor - four clearance holes on
    their own leave it free to sit anywhere inside them.  But it is a recess in
    a face, so a bore wider than the spigot has already taken it away, and
    drawing the circle anyway would put a line on the plate with no metal under
    it.  On the default 10 mm shaft a NEMA 17 is exactly that case: its 22 mm
    spigot lands on the 22 mm hub bore to the millimetre."""
    def register(frame_name):
        s = preset(15)
        s.motor_frame = frame_name
        msp = _plate(s, tmp_path / frame_name.replace(" ", ""),
                     "input_end_plate")
        return s, [c for c in msp.query('CIRCLE[layer=="MOTOR"]')
                   if c.dxf.radius == pytest.approx(s.motor_face.pilot_diameter / 2.0)]

    s, swallowed = register("NEMA 17")
    assert s.motor_face.pilot_diameter == s.hub_bore        # the exact-equality case
    assert swallowed == []

    s, cut = register("NEMA 23")
    assert s.motor_face.pilot_diameter > s.hub_bore
    assert len(cut) == 1


def test_a_plate_with_no_motor_on_it_gets_no_motor_pattern(spec, tmp_path):
    """The default is a plain plate driven through a coupling, and drilling the
    'None' frame's placeholder 1 mm holes into it would be worse than useless."""
    assert not spec.has_motor_face
    assert len(_plate(spec, tmp_path, "input_end_plate").query('*[layer=="MOTOR"]')) == 0


def test_part_steps_are_written_one_per_distinct_part(spec, tmp_path):
    import cadquery as cq
    paths = solid.write_part_steps(spec, tmp_path / "step")
    assert {p.stem for p in paths} == {"disc_1", "disc_2", "housing", "ring_pins",
                                       "eccentric_shaft", "output_flange",
                                       "input_end_plate", "output_end_plate"}
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


def test_bom_counts_every_bearing_the_schedule_asks_for(spec):
    """The quantity used to be read out of the role *string*.

    ``s.disc_count if "per disc" in choice.role else 1`` worked only while the
    roles happened to be worded that way, and when they stopped being, the BOM
    quietly said one eccentric bearing for a two-disc stack and one input shaft
    support for a shaft that needs two.  Ordering off it would leave you short.
    """
    from cycloidgen.export.bom import bom_items
    a = analyse(spec)
    lines = {i.part: i for i in bom_items(a)}
    for choice in a.bearings:
        if choice.bearing is None or not choice.count:
            continue
        assert lines[choice.role].quantity == choice.count, choice.role
        assert choice.seat in lines[choice.role].note


def test_the_step_assembly_holds_the_bearings_as_well_as_the_made_parts(spec, tmp_path):
    """A bearing is bought, so it gets no STL of its own - but the assembly is
    where fit is checked, and a fit check with no bearings in it is not one."""
    import cadquery as cq

    from cycloidgen.analysis.bearings import placements_for_spec
    from cycloidgen.export import solid

    placements = placements_for_spec(spec)
    assert placements
    assert not {p.name for p in placements} & set(solid.parts(spec))
    rings = sum(p.count for p in placements)
    bare = len(cq.importers.importStep(
        str(solid.write_step(spec, tmp_path / "a.step"))).val().Solids())
    assert bare >= 4 + spec.pin_count + rings
