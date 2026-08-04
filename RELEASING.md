# Releasing

## Where the version lives

In exactly one place:

```python
# cycloidgen/__init__.py
__version__ = "2.3.0"
```

Everything else reads it from there and nothing copies it:

| Consumer | How it reads it |
|---|---|
| The wheel and `pip show` | `pyproject.toml` — `dynamic = ["version"]`, `attr = "cycloidgen.__version__"` |
| `Help ▸ About` and `--version` | imports it |
| The executable's file properties | `cycloidgen.spec` parses the line and writes a Windows version resource |
| The installer, its filename and its Add/Remove entry | `packaging/cycloidgen.nsi`, `!searchparse` on the same line |
| The release workflow | compares the git tag against it and refuses to publish a mismatch |

That is why the line has to stay a plain string literal on one line:
setuptools reads it *statically*, without importing the package, and NSIS reads
it as text. `tests/test_version.py` holds both ends of that contract, and also
fails if `CHANGELOG.md` has no section for the current version.

## What the numbers mean

`MAJOR.MINOR.PATCH`, and the question that decides which one moves is **what
does this do to a design someone has already built?**

- **PATCH** — a fix that changes no computed number, or a change to the UI, the
  documentation or the packaging. Reopening a saved design gives the same
  answers.
- **MINOR** — new capability, new outputs, new checks. A saved design still
  loads and still means what it meant. A number may *appear* that was not there
  before, but the ones that were there do not move.
- **MAJOR** — a computed number changes, a check changes verdict on designs that
  used to pass, a file disappears from the bundle, or a saved design no longer
  loads. This is a tool people cut metal from: a quietly different torque
  capacity is a breaking change even though no API moved.

A change to `core/`, `analysis/` or `design/` should make you stop and ask which
of those three it is. If a number moved, say so in the changelog and say by how
much — the pull request template asks the same question for the same reason.

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
   publishes a GitHub release with the changelog section as its notes.

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
