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
