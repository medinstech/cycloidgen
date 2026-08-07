# Releasing

## Where the version lives

In exactly one place:

```python
# cycloidgen/__init__.py
__version__ = "2.3.1"
```

Everything else reads it from there and nothing copies it:

| Consumer | How it reads it |
|---|---|
| The wheel and `pip show` | `pyproject.toml` — `dynamic = ["version"]`, `attr = "cycloidgen.__version__"` |
| `Help ▸ About` and `--version` | imports it |
| The executable's file properties | `cycloidgen.spec` parses the line and writes a Windows version resource |
| The installer, its filename and its Add/Remove entry | `packaging/cycloidgen.nsi`, `!searchparse` on the same line |
| The release workflow | compares the git tag against it and refuses to publish a mismatch |
| A saved design, the JSON report, the PDF and every DXF | stamped in as the file is written — `core/designfile.py` and the writers |

That is why the line has to stay a plain string literal on one line:
setuptools reads it *statically*, without importing the package, and NSIS reads
it as text. `tests/test_version.py` holds both ends of that contract, and also
fails if `CHANGELOG.md` has no section for the current version.

## What the numbers mean

`MAJOR.MINOR.PATCH`, and the question that decides which one moves is **what
does this ask of someone who already has a design?**

- **PATCH** — nothing computed moves. A fix, the UI, the documentation, the
  packaging. Reopening a saved design gives the same answers to the digit.
- **MINOR** — new capability, new outputs, new checks, **or a better model**. A
  saved design still loads and every input still means what it meant, but the
  answers may be different, because the answers are a model of a machine and
  the model improves. When they move, the changelog's **Numbers** section says
  which quantity, on which design, and by how much. That section is not
  optional.
- **MAJOR** — the contract breaks, and reading the changelog is not enough to
  put it right. A saved design no longer loads, an input changes meaning or
  disappears, a file leaves the bundle, or a check starts failing designs that
  used to pass. Something has to be *done* — to the design, or to whatever
  consumes its files.

This used to say that any moved number was major, and for four releases in
three days it was — which is the tell rather than the vindication. This tool is
*made of* numbers that get better; a rule that makes every improvement a
breaking change spends the major digit on the ordinary case and has nothing
left to say when the extraordinary one arrives.

The warning that rule was protecting is still owed. It is paid in the two
places that can be precise about it instead of the one that cannot:

- the **Numbers** section says what moved and by how much, on a named design;
- **every file the app writes carries the version that wrote it**, so a design
  opened in a later build is told to its face that the model has changed under
  it, and a report or a DXF found in six months says which model produced it.

A change to `core/`, `analysis/` or `design/` should still make you stop and ask
which of the three it is. If a number moved, say so and say by how much — the
pull request template asks the same question for the same reason.

## The steps

1. **Land everything** you want in the release, on `main`, green.

2. **Bump the version** in `cycloidgen/__init__.py`.

3. **Write the changelog section.** `## 2.3.0` at the top of `CHANGELOG.md`,
   with **Added / Changed / Fixed** as needed and a **Numbers** line saying
   either what moved or that nothing did. The release notes on GitHub are
   generated from this section, so it is the text people will actually read.

4. **Check.** `python -m ruff check . && python -m pytest -q`. The version tests
   will fail if the changelog is missing its section or if a second copy of the
   version has appeared somewhere.

5. **Commit and tag.**

   ```bash
   git commit -am "Release 2.3.0"
   git tag -a v2.3.0 -m "cycloidgen 2.3.0"
   git push origin main --follow-tags
   ```

6. **The tag does the rest.** `.github/workflows/release.yml` checks the tag
   against the source, runs lint and the suite, builds the bundle, asks the
   built executable what version it thinks it is, builds the installer, and
   publishes a GitHub release with the changelog section as its notes. Beside
   it, a Linux job builds the AppImage and a macOS job builds the disk image,
   and both run what they built; behind all three, one job attaches those two to
   the release and another pushes the wheel to PyPI.

## Where a release goes

Four artefacts, and they are not alternatives — they are for different people.

| | who it is for | platforms |
|---|---|---|
| **Installer** (`.exe`) on the GitHub release | somebody who wants to run the app and does not have Python | Windows |
| **Disk image** (`.dmg`) on the GitHub release | the same person, on a Mac | macOS 11+, Apple silicon |
| **AppImage** on the GitHub release | the same person, on Linux | x86-64, glibc 2.35 and up |
| **Wheel** on PyPI | anybody with Python 3.10–3.12 — the only route on an Intel Mac, and the only way to `import cycloidgen` | Windows, Linux, macOS, x86-64 and arm64 |

There is no cross-platform installer format, which is why the first three are
separate programs. NSIS writes an installer that unpacks the bundle into Program
Files and registers it; an AppImage installs nothing and *is* the bundle, in a
squashfs image behind a runtime that mounts it; a `.dmg` is a disk image that
opens to the application beside a shortcut to `/Applications`.

Apple silicon only, because every x86-64 macOS runner GitHub offers is now a
paid *larger runner* — `macos-15-intel`, `macos-15-large` — and the free Intel
image was retired. An Intel Mac gets the wheel, which is the same application.

### The AppImage, and the two pins in it

`packaging/appimage.sh` builds it, and the workflow runs the result before
anything is published — extracted, `--version`, and a real export. A bundle that
builds and cannot start is the whole failure mode here, and it is invisible
until somebody downloads it.

Two things in that job are load-bearing and look like tidying:

- **`runs-on: ubuntu-22.04`, not `ubuntu-latest`.** A PyInstaller bundle carries
  Python and Qt but links against the host's glibc, and glibc is forward
  compatible only. Built on 24.04 the AppImage needs 2.39, which rules out
  Debian 12, Ubuntu 22.04 LTS and every enterprise distribution in service.
- **`appimagetool` is pinned to a release**, not `continuous`. The tool that
  builds a release artefact is part of the release, and "whatever was on the
  server that morning" is not something a build can be reproduced from.

A user whose machine has no FUSE 2 cannot mount the image; `libfuse2` or
`--appimage-extract-and-run` are the two ways round it, and the README says so.

### The disk image, and the thing it cannot fix

`packaging/macos.sh` wraps `dist/cycloidgen.app` — which the spec builds, so a
plain `pyinstaller cycloidgen.spec` on a Mac already produces the application —
in a `.dmg` with a symlink to `/Applications` beside it. The workflow mounts the
result and runs the binary out of the mounted volume before anything is
published, which is the last state the thing is in before a user sees it.

Two things not to change:

- **`bundle_identifier="com.medinstech.cycloidgen"`.** macOS keys preferences,
  permissions, window state and the *open with* association to the identifier —
  not the path, not the name. A new one is a new application to every part of
  the system, and there is no error: it simply opens with default settings on a
  machine that had it configured, and nothing says why.
- **Nothing re-signs over PyInstaller.** It signs every Mach-O it collects and
  then the bundle, ad-hoc, because arm64 will not load unsigned code at all.
  `codesign --deep --force` on top of that is the documented way to break the
  nested signatures, and the failure is not at build time — it is a bundle that
  will not launch on somebody else's Mac. The script reports the signature
  rather than imposing one.

**Ad-hoc is not signed.** Gatekeeper stops the first launch and the user has to
allow it by hand, which is worse than SmartScreen and is stated plainly in the
release notes and the README. Fixing it needs the Apple Developer Program
($99/yr) and then three steps in the macOS job, in this order:

```bash
codesign --sign "Developer ID Application: ..." --options runtime \
         --timestamp --force dist/cycloidgen.app
xcrun notarytool submit releases/*.dmg --apple-id ... --team-id ... --wait
xcrun stapler staple releases/*.dmg
```

The certificate and the app-specific password would be repository secrets; the
signing identity has to be imported into a temporary keychain in the job. That
is a configuration change to a job that already exists, not a rewrite, which is
why the unsigned image ships in the meantime rather than nothing.

### PyPI, and the one thing that is set up by hand

Publishing uses **Trusted Publishing**: PyPI verifies an OpenID Connect token
minted by the workflow itself against a publisher it has on file, so there is no
API token in this repository to leak, rotate or forget. It is configured once,
at `pypi.org/manage/project/cycloidgen/settings/publishing` — or, before the
first release, as a *pending* publisher under **Your projects → Publishing**:

| field | value |
|---|---|
| PyPI project name | `cycloidgen` |
| Owner | `medinstech` |
| Repository name | `cycloidgen` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

The environment name has to match the `environment:` on the `pypi` job. Leave it
blank on PyPI's side and any workflow in the repository can publish; naming it
is what keeps that to this one.

A version on PyPI **cannot be replaced**, only yanked. That is why the job waits
on the Windows one rather than running beside it: that job is the gate — lint,
the whole suite, the tag against the source, the changelog section — and half an
hour is a cheap price for not publishing something permanent that failed it.

`twine check` runs before the upload because `README.md` is the project page
there. PyPI serves it from its own host, so every path relative to the
repository root would 404; the check that keeps them absolute is
`test_the_readme_carries_no_relative_link_or_image`.

## Building the installer locally

```powershell
.\packaging\release.ps1                 # tests, bundle, installer
.\packaging\release.ps1 -FastPack -SkipTests   # quick internal build
```

Needs NSIS 3.x on `PATH` (`winget install NSIS.NSIS`). The script always
rebuilds `dist\`, because packaging a stale bundle produces an installer for the
*previous* version wearing the new version's number, and nothing downstream
notices.

The wizard bitmaps are committed. Regenerate them from the brand assets with
`python tools/make_setup_graphics.py` if the brand changes — `makensis` itself
needs no Python.

## Signing

The installer is unsigned today, which means a SmartScreen warning on first run.
When there is a certificate:

```powershell
.\packaging\release.ps1 -SignCmd 'signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 /a'
```

That signs the installer **and** the uninstaller stub. Both matter: an unsigned
uninstaller shows "Unknown Publisher" at the UAC prompt even when the installer
is signed.

## Not doing

- **Adding the CLI to `PATH` from the installer.** NSIS truncates `PATH` at 1024
  characters unless it is built with a larger string length, and silently
  corrupting a user's `PATH` is a far worse outcome than making them type a full
  path. Use the pip install for command-line work.
- **A per-user install.** The bundle is 1.2 GB; putting that in a roaming
  profile is not a kindness.
- **Auto-update.** An engineering tool changing its own answers overnight, on a
  machine where somebody is mid-project, is not a feature.
