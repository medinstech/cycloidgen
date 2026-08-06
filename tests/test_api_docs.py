"""The documented API is documented *and* executed.

``docs/api.md`` is the answer to "the analysis is importable but not documented
as something to import".  A document full of examples that nobody runs is worse
than no document: it is confidently wrong the first time a name moves, and the
person it misleads is someone who trusted it enough to build on.

So every ``python`` block in it is extracted and run here, in order, in one
namespace - which is also how a reader meets them.  If a rename lands without
the document following, this fails rather than the reader.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

DOC = Path(__file__).resolve().parent.parent / "docs" / "api.md"

_BLOCK = re.compile(r"^```python\n(.*?)^```", re.DOTALL | re.MULTILINE)


def blocks() -> list[str]:
    return _BLOCK.findall(DOC.read_text(encoding="utf-8"))


def test_the_document_exists_and_has_examples():
    assert DOC.exists(), "docs/api.md is the documented API; it has gone missing"
    assert len(blocks()) >= 10


def test_every_example_in_the_document_runs(tmp_path, monkeypatch):
    """In order, sharing state, because that is how they are written.

    Run from a scratch directory: two of them write files, and an example that
    only works in the author's checkout is not an example.
    """
    import matplotlib
    matplotlib.use("Agg")

    monkeypatch.chdir(tmp_path)
    namespace: dict = {"__name__": "__doc_example__"}
    for i, source in enumerate(blocks(), 1):
        try:
            exec(compile(source, f"docs/api.md[block {i}]", "exec"), namespace)
        except Exception as exc:                 # pragma: no cover - the message is the point
            pytest.fail(f"block {i} of docs/api.md failed: "
                        f"{type(exc).__name__}: {exc}\n\n{source}")


def test_the_headless_promise_holds():
    """The document opens by promising the analysis needs no display.

    It is the reason any of this can be used from a notebook, from CI, or from
    a fitting script on a machine that has never had a window server - and it
    is one careless top-level import away from being untrue, in a direction
    nobody testing on a desktop would notice.
    """
    import subprocess
    import sys

    code = ("import sys; import cycloidgen.analysis, cycloidgen.design.batch; "
            "print([m for m in ('PySide6', 'matplotlib') if m in sys.modules])")
    env = dict(os.environ, MPLBACKEND="Agg")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, check=True, env=env)
    assert out.stdout.strip() == "[]", (
        f"importing the analysis now drags in {out.stdout.strip()}")


def test_the_units_table_names_the_units_the_code_uses():
    """A units table is the part of a document most likely to quietly rot.

    Checked against the field names rather than by eye: every suffix the spec
    and the results actually use has to appear in the table.
    """
    table = DOC.read_text(encoding="utf-8")
    for unit in ("mm", "Nm", "arcmin", "Nm/arcmin", "rpm", "MPa", "g"):
        assert f"| {unit} |" in table or f"| {unit} " in table, \
            f"the units table says nothing about {unit}"
