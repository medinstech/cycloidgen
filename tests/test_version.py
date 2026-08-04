"""One version, in one place, documented before it ships.

A version that disagrees with itself across the wheel, the executable and the
installer is not a cosmetic problem: it is what makes a bug report impossible to
place.  These tests are cheap and they are the reason there is no second copy to
drift.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

import cycloidgen

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "cycloidgen" / "__init__.py"
NSI = ROOT / "packaging" / "cycloidgen.nsi"

#: MAJOR.MINOR.PATCH, optionally a pre-release.  Deliberately narrower than
#: PEP 440 allows: the NSIS `VIProductVersion` field wants four integers and
#: gets them by appending `.0`, which only works while the first three parts are
#: plain numbers.
_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?$")


def test_the_version_is_a_version():
    assert _VERSION.match(cycloidgen.__version__), cycloidgen.__version__


def test_the_declared_version_is_the_only_one():
    """`pyproject.toml` must not carry a second copy that can fall behind.

    Read as text rather than parsed: ``tomllib`` arrived in 3.11 and this
    project still supports 3.10, and what needs checking is precisely a *line*
    that must not exist.
    """
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert not re.search(r'^version\s*=\s*"', text, flags=re.MULTILINE), \
        "pyproject.toml has a hard-coded version; it should stay dynamic"
    assert 'dynamic = ["version"]' in text
    assert re.search(r'version\s*=\s*\{\s*attr\s*=\s*"cycloidgen\.__version__"\s*\}',
                     text)


def test_the_build_backend_can_read_it_without_importing_the_package():
    """setuptools reads `attr:` statically when the assignment is simple.

    If it ever has to *import* `cycloidgen` to find the version, building a
    wheel starts requiring the runtime dependencies to be installed first - and
    that failure appears only on a clean machine.
    """
    source = INIT.read_text(encoding="utf-8")
    assert re.search(r'^__version__ = "[^"]+"$', source, flags=re.MULTILINE)


def test_the_installer_reads_the_same_line():
    """`!searchparse` is a text match, so the format is a contract."""
    if not NSI.exists():                       # packaging is optional to check out
        pytest.skip("no NSIS script in this checkout")
    script = NSI.read_text(encoding="utf-8", errors="replace")
    prefix = re.search(r"!searchparse\s+/file\s+\S+\s+`([^`]*)`", script)
    assert prefix is not None, "the NSIS script no longer parses a version"
    assert INIT.read_text(encoding="utf-8").count(prefix.group(1)) == 1


def test_the_changelog_documents_this_version():
    """A release with no entry is a release nobody can read the diff of."""
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## (\S+)", changelog, flags=re.MULTILINE)
    assert cycloidgen.__version__ in headings, (
        f"CHANGELOG.md has no '## {cycloidgen.__version__}' section")
    assert headings[0] == cycloidgen.__version__, \
        "the newest changelog section should be the current version"


def test_the_application_reports_it():
    out = subprocess.run([sys.executable, "-m", "cycloidgen", "--version"],
                         capture_output=True, text=True, check=True)
    assert cycloidgen.__version__ in out.stdout
