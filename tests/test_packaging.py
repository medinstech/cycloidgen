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

import pytest

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


def _spec_platform_branch() -> tuple[str, str]:
    """The two arms of the spec's `sys.platform == "win32"` split, as source."""
    text = SPEC.read_text(encoding="utf-8")
    match = re.search(
        r'^if sys\.platform == "win32":\n(.*?)^else:\n(.*?)^\ncoll = COLLECT\(',
        text, re.M | re.S)
    assert match, "the spec no longer splits its executables by platform"
    return match.group(1), match.group(2)


def test_the_windows_bundle_carries_a_windowed_app_and_a_console_cli():
    """Two executables over one analysis - `pythonw.exe` / `python.exe`.

    A single console build put a black window behind the application every time
    somebody opened it from the Start menu.  A single windowed build would have
    taken the command line away, and taken it away badly: a frozen windowed
    process has no stdout at all, so `--version` would not print nothing, it
    would raise.
    """
    windows, _ = _spec_platform_branch()
    assert '_exe("cycloidgen", console=False)' in windows, "the app must be windowed"
    assert '_exe("cycloidgen-cli", console=True)' in windows, "the CLI needs a console"
    assert "COLLECT(\n    *executables," in SPEC.read_text(encoding="utf-8"), \
        "both must reach COLLECT"


def test_every_other_platform_gets_one_executable():
    """`console` is a Windows subsystem flag - a PE header field saying whether
    the loader allocates a console - and there is no equivalent elsewhere.

    So a second binary on Linux would not be a second behaviour, only a second
    copy of the same one under a name implying a difference that does not exist.
    The AppImage's `.desktop` file and its AppRun both name `cycloidgen`, and the
    release workflow checks that `cycloidgen-cli` is *not* there.
    """
    _, other = _spec_platform_branch()
    assert other.count("_exe(") == 1, "one binary off Windows, not two"
    assert '_exe("cycloidgen"' in other
    assert "cycloidgen-cli" not in other


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


# --------------------------------------------------------- the Linux AppImage

APPIMAGE = ROOT / "packaging" / "appimage.sh"
RELEASE_YML = WORKFLOWS / "release.yml"


def test_the_appimage_names_the_same_binary_in_all_three_places():
    """AppRun starts it, the desktop entry points at it, the workflow tests it.

    Three files, one name, and nothing joins them: the desktop entry's `Exec` is
    read by the desktop and by nothing in this repository, so a rename that
    misses it produces an AppImage that runs perfectly from a terminal and does
    nothing at all when double-clicked.
    """
    script = APPIMAGE.read_text(encoding="utf-8")
    assert 'exec "$root/usr/bin/cycloidgen" "$@"' in script
    assert "Exec=cycloidgen %f" in script
    # ...and `Icon=` has to match the icon's basename, or the launcher is blank.
    assert "Icon=cycloidgen" in script
    assert 'cp cycloidgen/ui/assets/icon-256.png "$appdir/cycloidgen.png"' in script
    assert "test -x ./dist/cycloidgen/cycloidgen" in RELEASE_YML.read_text(encoding="utf-8")


def test_the_appimage_script_is_run_through_an_interpreter():
    """Its executable bit is in the index, and this repository is developed on
    Windows, where git's `core.filemode` is off - so an edit that recreates the
    file drops the bit without anybody noticing.  Naming `bash` costs five
    characters and cannot be lost half an hour into a release."""
    workflow = RELEASE_YML.read_text(encoding="utf-8")
    assert "bash packaging/appimage.sh" in workflow


def test_the_appimage_is_built_on_the_oldest_supported_glibc():
    """A PyInstaller bundle carries Python and Qt and links against the host's
    glibc, which is forward compatible only.

    Built on `ubuntu-latest` - 24.04 today - the AppImage needs glibc 2.39, and
    that rules out Debian 12, Ubuntu 22.04 LTS and every enterprise distribution
    currently in service.  The pin is the whole reach of the artefact, and
    `ubuntu-latest` is exactly the sort of thing somebody tidies up.
    """
    import yaml
    jobs = yaml.safe_load(RELEASE_YML.read_text(encoding="utf-8"))["jobs"]
    assert jobs["linux"]["runs-on"] == "ubuntu-22.04"


# ------------------------------------------------------- the macOS disk image

MACOS_SH = ROOT / "packaging" / "macos.sh"

#: Keyed to by macOS for preferences, permissions, window state and the "open
#: with" association - not by path and not by name.  A different one is a
#: different application to every part of the system, and everybody's settings
#: are gone with it.
BUNDLE_ID = "com.medinstech.cycloidgen"


def test_the_bundle_identifier_is_the_one_macos_already_knows():
    """This is a test about *not* changing something.

    There is no error when it changes; the application simply opens with default
    settings on a machine that had it configured, and nothing says why.
    """
    assert f'bundle_identifier="{BUNDLE_ID}"' in SPEC.read_text(encoding="utf-8")


def test_the_app_is_built_windowed_and_the_dmg_carries_it():
    """`console` means a third thing again on macOS: whether Launch Services
    sees a windowed application or a terminal program, and a `.app` has to be
    the first.  It costs nothing - a process started from a shell has stdio
    whatever its bundle says, which is why the workflow can ask the binary
    inside the bundle for its version.
    """
    spec = SPEC.read_text(encoding="utf-8")
    assert 'console=sys.platform != "darwin"' in spec
    assert 'name="cycloidgen.app"' in spec

    workflow = RELEASE_YML.read_text(encoding="utf-8")
    assert "./dist/cycloidgen.app/Contents/MacOS/cycloidgen --version" in workflow


def test_the_signed_bundle_is_copied_with_ditto():
    """A signature is not only bytes inside the Mach-O.

    For everything in the bundle that is not one it lives in an extended
    attribute, and a copy that drops those leaves something that still looks
    complete and no longer verifies - on the user's Mac, not here.  `ditto` is
    what Apple ships for copying a bundle intact; `cp` is not it.
    """
    script = MACOS_SH.read_text(encoding="utf-8")
    assert 'ditto "$APP" "$staging/$(basename "$APP")"' in script
    assert "cp -R" not in script and "cp -a" not in script


def test_the_disk_image_offers_somewhere_to_drag_it_to():
    """Half of what a .dmg is for.  Without the symlink the window opens with a
    bundle in it and no hint that installing means moving it, and the user runs
    the application off the mounted image - which works until they eject it."""
    script = MACOS_SH.read_text(encoding="utf-8")
    assert 'ln -s /Applications "$staging/Applications"' in script
    assert "test -L /Volumes/cycloidgen/Applications" in RELEASE_YML.read_text(
        encoding="utf-8")


def test_nothing_re_signs_the_bundle_over_pyinstaller():
    """PyInstaller signs every Mach-O it collects and then the bundle, ad-hoc,
    because arm64 will not load unsigned code at all.

    Re-signing on top of that with `--deep` is the documented way to break the
    nested signatures - and the failure is not at build time, it is a bundle
    that will not launch on somebody else's Mac.  The script reports what is
    there instead of imposing something.
    """
    script = MACOS_SH.read_text(encoding="utf-8")
    assert "codesign --display" in script
    assert "codesign --verify" in script
    assert "--deep --sign" not in script
    assert "--force" not in script


def test_the_mac_and_linux_bundles_are_built_on_pinned_runners():
    """`-latest` moves under you, and on both of these the runner *is* the
    compatibility floor: glibc on Linux, the SDK on macOS."""
    import yaml
    jobs = yaml.safe_load(RELEASE_YML.read_text(encoding="utf-8"))["jobs"]
    assert jobs["linux"]["runs-on"] == "ubuntu-22.04"
    assert jobs["macos"]["runs-on"] == "macos-15"


def test_the_quarantine_flag_is_cleared_before_the_first_launch_is_suggested():
    """Order, not content - and getting it wrong deletes the installation.

    Both documents used to offer *System Settings ▸ Privacy & Security ▸ Open
    Anyway* first and `xattr` as an alternative.  That reads as "open it, then
    deal with the warning", and on macOS 15 and later the warning's default
    button is *Move to Trash*: a tester on macOS 26 followed it exactly and
    watched 1.3 GB go to the Trash without the application ever running.

    So wherever both remedies appear, the one that avoids the dialog has to come
    first.  Nothing enforces that but this - it is prose in two files, one of
    them a heredoc inside a workflow, and it is precisely the sort of thing a
    tidy-up reflows back into the wrong order.
    """
    for path in (ROOT / "README.md", RELEASE_YML):
        text = path.read_text(encoding="utf-8")
        clear = text.find("xattr -dr com.apple.quarantine")
        settings = text.find("Open Anyway")
        assert clear != -1, f"{path.name} no longer tells anyone how to clear it"
        if settings != -1:
            assert clear < settings, (
                f"{path.name} offers the Settings route before clearing the flag")
        # ...and says what the dialog's default button does, because the whole
        # failure is that the easiest click is the destructive one.
        assert "Move to Trash" in text, f"{path.name} does not warn what it costs"


# ------------------------------------------------- what the bundle leaves out

RTHOOK = ROOT / "packaging" / "rthook_casadi.py"

#: Declared by cadquery, imported by nothing here, and a third of the bundle
#: between them.  Each one is checked below against the import graph rather than
#: trusted, because "we do not use it" is exactly the claim that rots.
DEAD_WEIGHT = ["numba", "llvmlite", "trame", "trame_vuetify", "trame_client",
               "trame_server", "trame_vtk", "pyvista"]


def test_the_spec_excludes_everything_it_declares_dead():
    """The list in the spec is the one thing the build reads.

    Splitting it - a comment naming one set and `excludes` carrying another - is
    how a 116 MB package comes back without anybody deciding it should.
    """
    spec = SPEC.read_text(encoding="utf-8")
    declared = re.search(r"DEAD_WEIGHT = \[(.*?)\]", spec, re.S)
    assert declared, "the spec no longer declares what it drops"
    assert sorted(re.findall(r'"([^"]+)"', declared.group(1))) == sorted(DEAD_WEIGHT)
    assert '"casadi", *DEAD_WEIGHT' in spec, "all of it has to reach excludes"


def test_nothing_in_the_application_imports_what_the_bundle_drops():
    """The check that makes the exclusions safe rather than hopeful.

    Every name below is a hard dependency of cadquery, so it is installed in
    this environment and importing it would succeed - which is why absence has
    to be asserted against the source rather than discovered at run time, where
    the first person to find out is holding a frozen build that will not start.
    """
    offenders = []
    for path in (ROOT / "cycloidgen").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for module in [*DEAD_WEIGHT, "casadi"]:
            if re.search(rf"^\s*(?:from|import)\s+{module}\b", text, re.M):
                offenders.append(f"{path.relative_to(ROOT)} imports {module}")
    assert not offenders, offenders


def test_the_casadi_stand_in_survives_being_read_the_way_cadquery_reads_it():
    """cadquery imports casadi whatever you ask it for, so the stub is on the
    only path into the CAD kernel.

    What runs at import time is two annotations - `ca.Opti` on a class attribute
    and `ca.MX` on some signatures - and an annotation needs an object, not an
    optimiser.  Attribute access therefore has to work and calling has to fail,
    which is the whole design and is checked here in both directions.
    """
    import runpy

    namespace = runpy.run_path(str(RTHOOK))
    stub = namespace["_Casadi"]("casadi")

    assert stub.Opti is not None                     # the annotation that runs
    assert stub.MX is not None
    with pytest.raises(RuntimeError, match="not bundled"):
        stub.Opti()                                  # ...and using it does not

    # Dunders go to the import machinery and to inspect; answering those with a
    # placeholder makes the module lie about its own shape.
    with pytest.raises(AttributeError):
        _ = stub.__wrapped__


def test_the_spec_installs_the_stand_in_before_anything_can_import_cadquery():
    """A runtime hook runs before the application's first line, which is the
    only window there is: by the time `launcher.py` runs, an ordinary import of
    cadquery would already have failed."""
    spec = SPEC.read_text(encoding="utf-8")
    assert 'runtime_hooks=["packaging/rthook_casadi.py"]' in spec
    assert RTHOOK.exists()


#: The old figures, in both decimal separators - the installer's Turkish page
#: writes "1,5 GB".  The README states the old number deliberately, as the
#: history of a wrong guess, so what is forbidden is the *claim* rather than the
#: number: anything not reached through "was".
_CLAIM = re.compile(r"(?<!was )1[.,][25]\s?GB")


def test_nothing_still_claims_the_bundle_is_a_gigabyte_of_occt():
    """It was 1.2 GB and the reason given was OCCT, and both halves were wrong:
    the kernel is 152 MB and the constraint optimiser beside it was larger.

    The number reaches a user through the installer's welcome page, in two
    languages, so a stale one is not an internal note - it is the first sentence
    of the product.
    """
    for path in (ROOT / "README.md", ROOT / "RELEASING.md", NSI, RELEASE_YML,
                 WORKFLOWS / "tests.yml"):
        text = path.read_text(encoding="utf-8-sig")
        stale = _CLAIM.search(text)
        assert not stale, f"{path.name} still states the old size: {stale.group(0)!r}"

    # ...and the installer says it in both languages, because only one of them
    # was ever going to be updated by hand.
    nsi = NSI.read_text(encoding="utf-8-sig")
    assert nsi.count("850 MB") == 2, "both welcome pages quote the footprint"
