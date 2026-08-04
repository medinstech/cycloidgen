"""The export manifest, and whether it tells the truth.

The manifest exists so that three consumers - the writer, the desktop app's
Outputs tab and ``--list-outputs`` - cannot disagree about what a bundle
contains.  That is only worth anything if the promise is checked against the
files that actually land on disk, which is what most of this module does.
"""
from __future__ import annotations

import re
from pathlib import Path

import matplotlib
import pytest

matplotlib.use("Agg")

from cycloidgen.core.spec import preset
from cycloidgen.export import manifest, write_bundle

README = Path(__file__).resolve().parent.parent / "README.md"


def _relative(files, root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in files)


def _on_disk(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


@pytest.fixture(scope="module")
def spec():
    s = preset(15)
    s.disc_count = 2
    return s


# ----------------------------------------------------------------- the promise


def test_the_bundle_is_exactly_what_the_manifest_promised(spec, tmp_path_factory):
    """The one test the manifest exists for.

    Not "the files it listed are present" - *exactly* those files and no
    others.  An extra file nobody declared is how a bundle grows something the
    Outputs tab never mentions.
    """
    root = tmp_path_factory.mktemp("bundle")
    written = write_bundle(spec, root)
    planned = sorted(name for _, name in manifest.planned_files(spec))
    assert _relative(written, root) == planned
    assert _on_disk(root) == planned


def test_drawings_and_data_alone_leave_the_kernel_out(spec, tmp_path):
    """The path that has to work on a machine with no OCCT."""
    written = write_bundle(spec, tmp_path, include_solids=False)
    planned = sorted(name for _, name in
                     manifest.planned_files(spec, {"drawings", "data"}))
    assert _relative(written, tmp_path) == planned
    assert not any("step" in name or "stl" in name for name in planned)


def test_a_single_group_writes_only_that_group(spec, tmp_path):
    written = write_bundle(spec, tmp_path, groups={"drawings"})
    assert _relative(written, tmp_path) == sorted(
        name for _, name in manifest.planned_files(spec, {"drawings"}))
    assert not (tmp_path / "report.pdf").exists()


def test_every_manifest_entry_has_a_writer(spec, tmp_path):
    """A declared output with no writer would fail only when someone selects it."""
    from cycloidgen.export import _write
    for out in manifest.MANIFEST:
        if out.group != "drawings":                # the cheap ones are enough
            continue
        assert _write(out, spec, tmp_path, None)


def test_an_undeclared_output_is_refused(spec, tmp_path):
    from cycloidgen.export import _write
    ghost = manifest.Output("nope", "nope.txt", "data", "TXT", "", "")
    with pytest.raises(KeyError):
        _write(ghost, spec, tmp_path, None)


# ------------------------------------------------------------------- structure


def test_folder_entries_declare_their_contents_and_files_do_not():
    for out in manifest.MANIFEST:
        assert (out.contents is not None) == out.is_folder, out.key
        assert out.group in manifest.group_keys(), out.key
        assert out.title and out.description and out.fmt


def test_the_disc_names_are_the_ones_the_exporters_use(spec, tmp_path):
    """One naming rule, so the DXF and the STEP cannot disagree about the stack."""
    from cycloidgen.export import dxf, solid
    names = manifest.disc_names(spec)
    assert names == ["disc_1", "disc_2"]
    assert set(names) <= {p.stem for p in dxf.write_part_dxfs(spec, tmp_path / "d")}
    assert set(names) <= set(solid.parts(spec))


def test_identical_discs_collapse_to_one_name_everywhere():
    s = preset(10)
    s.disc_count = 2
    s.output_pin_count = 2 * s.lobes               # the rare identical case
    assert s.discs_are_identical
    assert manifest.disc_names(s) == ["disc"]
    assert "disc" in manifest.part_names(s)
    for _, name in manifest.planned_files(s, {"solids"}):
        assert "disc_1" not in name


def test_resolve_groups_understands_both_ways_of_asking():
    assert manifest.resolve_groups(True) == set(manifest.group_keys())
    assert manifest.resolve_groups(False) == {"drawings", "data"}
    assert manifest.resolve_groups(False, ["solids"]) == {"solids"}
    with pytest.raises(ValueError, match="unknown output group"):
        manifest.resolve_groups(True, ["drawings", "pictures"])


# ---------------------------------------------------------------------- README


def test_the_readme_lists_exactly_what_an_export_writes():
    """Documentation drift, caught by the same mechanism as code drift.

    The table in the README is the first thing anyone reads to decide whether
    this tool produces what they need.  It has one job and no way of knowing
    when it stops doing it.
    """
    text = README.read_text(encoding="utf-8")
    section = text.split("## What it produces", 1)[1].split("\n## ", 1)[0]
    listed = re.findall(r"^\|\s*`([^`]+)`", section, flags=re.MULTILINE)
    assert listed == [out.where for out in manifest.MANIFEST]
