"""A saved design says which build wrote it, and every file the app writes does.

The release rule (RELEASING.md) lets a minor version move a computed number,
which is honest about what this tool is - but it only works if the file can say
where it came from.  These tests hold that end of it: the stamp goes in, the
stamp comes back out, and the "this may read differently now" question is
answered by the two digits the rule says can move it.
"""
from __future__ import annotations

import json
from pathlib import Path

import ezdxf
import pytest

import cycloidgen
from cycloidgen.core.designfile import (
    design_dict,
    numbers_may_have_moved,
    provenance,
    spec_from_dict,
    written_by,
)
from cycloidgen.core.spec import GearSpec, preset
from cycloidgen.export.dxf import write_dxf, write_part_dxfs
from cycloidgen.report.build import report_dict


def test_a_saved_design_carries_the_build_that_wrote_it():
    data = design_dict(preset(15))
    assert written_by(data) == cycloidgen.__version__
    assert data["generator"] == "cycloidgen"


def test_a_saved_design_still_round_trips_to_the_same_drive():
    spec = preset(21)
    assert spec_from_dict(design_dict(spec)) == spec


def test_the_reader_takes_all_three_shapes_this_app_has_written():
    """A design file, a full report, and a bare spec dump from before either.

    Every one of those is somebody's saved work, and the oldest of them is the
    one most likely to be the design a machine was actually built from.
    """
    spec = preset(15)
    bare = json.loads(spec.model_dump_json())
    assert spec_from_dict(bare) == spec
    assert spec_from_dict({"spec": bare}) == spec
    assert spec_from_dict(design_dict(spec)) == spec


def test_a_file_written_by_a_build_that_did_not_stamp_says_so():
    """Silence is not the same as agreement.

    Nothing before this stamp existed recorded a version, and everything before
    it moved numbers - so an unstamped file is treated as older rather than as
    current.
    """
    assert written_by({"spec": {}}) is None
    assert numbers_may_have_moved(None) is True


def test_patch_is_the_digit_that_cannot_move_a_number():
    """Major and minor move numbers; patch is *defined* as the one that does not.

    That is what makes the version machine-readable rather than advisory: the
    app decides on its own whether to warn, and it decides it the same way the
    release rule decides which digit to bump.  Built from the running version
    rather than written out, so this keeps testing the rule and not the year.
    """
    major, minor, patch = (int(p) for p in cycloidgen.__version__.split(".")[:3])
    assert numbers_may_have_moved(f"{major}.{minor}.{patch}") is False
    assert numbers_may_have_moved(f"{major}.{minor}.{patch + 7}") is False
    assert numbers_may_have_moved(f"{major}.{minor + 1}.0") is True
    assert numbers_may_have_moved(f"{major + 1}.0.0") is True
    assert numbers_may_have_moved(f"{major - 1}.99.99") is True


@pytest.mark.parametrize("written", ["not a version", "6", "", "6.x.0"])
def test_a_version_this_build_cannot_read_counts_as_moved(written):
    """Unreadable is not the same as identical, and the safe reading is older."""
    assert numbers_may_have_moved(written) is True


def test_the_provenance_line_names_both_builds():
    line = provenance("4.2.0")
    assert "4.2.0" in line and cycloidgen.__version__ in line
    # And says what has *not* changed, because a warning that only says
    # "something moved" makes people re-enter a design they did not need to.
    assert "inputs still mean what they meant" in line


def test_an_unknown_build_is_described_rather_than_left_blank():
    line = provenance(None)
    assert "None" not in line
    assert cycloidgen.__version__ in line


def test_the_json_report_names_the_model_that_produced_its_numbers():
    from cycloidgen.analysis import analyse
    data = report_dict(analyse(preset(15)))
    assert data["version"] == cycloidgen.__version__


def test_every_dxf_says_what_cut_it(tmp_path: Path):
    """A DXF is mailed to a shop and comes back as metal weeks later."""
    spec = preset(15)
    files = [write_dxf(spec, tmp_path / "drawing.dxf")]
    files += write_part_dxfs(spec, tmp_path / "parts")
    assert len(files) > 3
    for path in files:
        custom = dict(ezdxf.readfile(path).header.custom_vars.properties)
        assert custom.get("CYCLOIDGEN_VERSION") == cycloidgen.__version__, path
        assert custom.get("GENERATOR") == "cycloidgen", path


def test_a_design_from_the_future_loses_what_this_build_cannot_read():
    """Which is the reason the warning fires in both directions.

    Pydantic drops fields it does not know, so a design saved by a later build
    opens here quietly missing whatever that build added - and quietly is the
    whole problem.
    """
    data = design_dict(preset(15))
    data["version"] = "99.0.0"
    data["spec"]["some_parameter_from_the_future"] = 1.0
    spec = spec_from_dict(data)
    assert isinstance(spec, GearSpec)
    assert not hasattr(spec, "some_parameter_from_the_future")
    assert numbers_may_have_moved(written_by(data)) is True
