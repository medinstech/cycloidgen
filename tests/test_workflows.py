"""The CI definitions, checked like anything else.

A broken workflow file does not fail loudly.  GitHub reports a run with *no
jobs*, an instant failure and the file path where the workflow name should be -
and it does that for every push, so the noise looks like infrastructure trouble
rather than a mistake in a file somebody edited.  Worse, the release workflow
only runs on a tag: a fault in it is discovered by tagging, waiting ninety
minutes for a 1.2 GB bundle to compress, and watching the last step fall over.

Both of those happened while cutting 2.3.0.  These are the checks that would
have caught them in a second.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOWS = sorted((pathlib.Path(__file__).resolve().parent.parent
                    / ".github" / "workflows").glob("*.yml"))
ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_there_are_workflows_to_check():
    assert WORKFLOWS, "no workflow files found - this file is asserting nothing"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_the_workflow_parses_and_declares_jobs(path):
    """The zero-job failure, caught before it is pushed."""
    definition = _load(path)
    assert definition, path.name
    assert definition.get("jobs"), f"{path.name} declares no jobs"
    for name, job in definition["jobs"].items():
        assert job.get("steps"), f"{path.name}: job {name} has no steps"
        assert job.get("runs-on"), f"{path.name}: job {name} names no runner"


def test_the_release_only_runs_on_a_tag():
    """Not on every branch push.  `on` parses as the boolean True in YAML 1.1,
    which is why it is read by either spelling."""
    definition = _load(ROOT / ".github" / "workflows" / "release.yml")
    triggers = definition.get("on", definition.get(True))
    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["push"] == {"tags": ["v*"]}
    assert "branches" not in triggers["push"]


def _release_notes_script() -> str:
    definition = _load(ROOT / ".github" / "workflows" / "release.yml")
    steps = definition["jobs"]["windows"]["steps"]
    step = next(s for s in steps if s.get("name") == "Publish the release")
    return step["run"].split("python - <<'PY'", 1)[1].split("\nPY", 1)[0]


def test_the_release_notes_are_built_on_an_unhelpful_stdout():
    """The bug this test exists for.

    The notes used to be produced by redirecting Python's stdout into a file.
    The changelog is UTF-8 and carries the menu arrow among other things, and
    stdout on a Windows runner is the locale encoding - so the publish step
    would have died with a UnicodeEncodeError *after* the whole installer had
    been built.  Run here under that encoding, so it cannot come back.
    """
    script = _release_notes_script()
    with tempfile.TemporaryDirectory() as tmp:
        runner = pathlib.Path(tmp) / "notes_step.py"
        runner.write_text(script, encoding="utf-8")
        # The runner's environment, with only the encoding forced: replacing
        # it wholesale is how a test starts failing on the platform it was not
        # written on.
        env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
        result = subprocess.run(
            [sys.executable, str(runner)], cwd=ROOT, capture_output=True,
            text=True, env=env)
    written = ROOT / "notes.md"
    try:
        assert result.returncode == 0, result.stderr[-400:]
        notes = written.read_text(encoding="utf-8")
        assert len(notes) > 200
        # Some section, not a particular one: a fix-only release has no
        # **Added**, and asserting on the shape of this release's contents
        # would make the test fail on the next one for no reason.
        assert any(h in notes for h in ("**Added**", "**Changed**", "**Fixed**"))
        # and the split stopped at the next version rather than running on
        assert "\n## " not in notes
    finally:
        written.unlink(missing_ok=True)
