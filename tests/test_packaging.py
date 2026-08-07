"""The installer script, and the encoding it is read with.

The Turkish pages shipped in 2.3.0 as mojibake: the welcome page said "hoÅŸ
geldiniz".  ``makensis`` assumes the system ANSI codepage unless the script
carries a UTF-8 BOM or the charset is named on the command line, so the UTF-8
bytes of ``ş`` were read as two Latin-1 characters.

Nothing about that fails a build.  The installer compiles, the tests pass, CI is
green, and the fault only appears to somebody who runs the setup and reads
Turkish - which is why it survived to a release.  These checks are cheap and
they hold both ends: the file says what it is, and every tool that reads it is
told.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
NSI = ROOT / "packaging" / "cycloidgen.nsi"
RELEASE_PS1 = ROOT / "packaging" / "release.ps1"
WORKFLOWS = ROOT / ".github" / "workflows"

#: What makensis has to be told, in the spelling each caller uses.
CHARSET = "INPUTCHARSET"


def test_the_installer_script_is_utf8_and_says_so():
    """A BOM is what makes a plain ``makensis packaging\\cycloidgen.nsi`` right.

    The README documents that command, so the file has to be self-describing;
    the flag below is the belt to this pair of braces.
    """
    raw = NSI.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "cycloidgen.nsi lost its UTF-8 BOM"
    raw.decode("utf-8")                            # raises if it is not UTF-8


def test_the_script_really_does_carry_characters_that_need_it():
    """If this fails the checks above are guarding nothing, and should go."""
    text = NSI.read_text(encoding="utf-8-sig")
    turkish = [c for c in text if c in "şğıçöüŞĞİÇÖÜ"]
    assert len(turkish) > 50, "no Turkish left in the script"
    assert "hoş geldiniz" in text


def _makensis_invocations() -> list[tuple[str, str]]:
    """Every place the project runs makensis, as (where, the command line)."""
    found = []
    for path in [RELEASE_PS1, *sorted(WORKFLOWS.glob("*.yml")), ROOT / "README.md"]:
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            # An *invocation*, not prose about one and not the lookup that
            # locates the binary: either the executable is named, or the line
            # is the bare command the README tells people to type.
            invokes = ("makensis.exe" in stripped
                       and not re.match(r"^(#|;|\$\w+\s*=|.*Get-Command)", stripped)
                       ) or stripped.startswith("makensis ")
            if invokes:
                found.append((path.name, stripped))
    return found


def test_every_caller_names_the_charset():
    """Including the README: a command in the documentation is a command
    somebody runs."""
    invocations = _makensis_invocations()
    assert invocations, "no makensis invocations found - this test is asserting nothing"
    for where, line in invocations:
        assert CHARSET in line, f"{where}: makensis called without {CHARSET}: {line}"


def test_the_release_script_passes_it_first():
    """Ahead of the optional defines, so a build with none of them still has it."""
    text = RELEASE_PS1.read_text(encoding="utf-8")
    args = re.search(r"\$args = @\((.*?)\)", text, flags=re.S)
    assert args is not None, "release.ps1 no longer builds an argument list"
    assert "'/INPUTCHARSET', 'UTF8'" in args.group(1)


# ------------------------------------------------------------- executables


SPEC = ROOT / "cycloidgen.spec"


def test_the_bundle_carries_a_windowed_app_and_a_console_cli():
    """Two executables over one analysis - `pythonw.exe` / `python.exe`.

    A single console build put a black window behind the application every time
    somebody opened it from the Start menu.  A single windowed build would have
    taken the command line away, and taken it away badly: a frozen windowed
    process has no stdout at all, so `--version` would not print nothing, it
    would raise.
    """
    text = SPEC.read_text(encoding="utf-8")
    assert '_exe("cycloidgen", console=False)' in text, "the app must be windowed"
    assert '_exe("cycloidgen-cli", console=True)' in text, "the CLI needs a console"
    assert re.search(r"COLLECT\(\s*gui,\s*cli,", text), "both must reach COLLECT"


def test_the_shortcuts_point_at_the_windowed_one():
    """The installer's EXE_NAME is what every shortcut and the Run box use."""
    nsi = NSI.read_text(encoding="utf-8-sig")
    assert '!define EXE_NAME    "cycloidgen.exe"' in nsi


def test_the_windowed_build_cannot_be_felled_by_a_print():
    """PyInstaller gives a windowed process ``sys.stdout = None``, and the
    launcher has to replace it before anything imports and prints."""
    launcher = (ROOT / "launcher.py").read_text(encoding="utf-8")
    assert "_ensure_streams()" in launcher
    assert launcher.index("_ensure_streams()\n\nfrom cycloidgen") < \
        launcher.index("from cycloidgen.__main__ import main")


def test_the_version_is_checked_against_the_build_that_can_answer():
    """Asking the windowed one would test nothing and look like it tested."""
    ps1 = RELEASE_PS1.read_text(encoding="utf-8")
    assert "cycloidgen-cli.exe" in ps1
    assert re.search(r"\$reported = \(& \$exe --version\)", ps1)
    workflow = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    assert "cycloidgen-cli.exe --version" in workflow


# ------------------------------------------------------- the README on PyPI


def test_the_readme_carries_no_relative_link_or_image():
    """It is the project page on PyPI as well as the front of the repository.

    `pyproject.toml` names it as the long description, and PyPI serves it from
    its own host: every path relative to the repository root resolves against
    `pypi.org` there and 404s.  The header is mostly pictures, so a README that
    is right on GitHub and relative everywhere lands on PyPI as a column of
    broken-image icons - which is the first thing anyone sees of the project.

    Anchors are left alone deliberately.  PyPI renders the whole document on one
    page, so `#run-it` goes where it says on both.
    """
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    relative = set()
    # Markdown links and images, then the HTML the header is built from.
    for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", readme):
        relative.add(target)
    for target in re.findall(r'(?:src|srcset|href)="([^"]+)"', readme):
        relative.add(target)
    offenders = sorted(t for t in relative
                       if not t.startswith(("http://", "https://", "#", "mailto:")))
    assert not offenders, (
        f"relative in a README that PyPI also serves: {offenders}")
