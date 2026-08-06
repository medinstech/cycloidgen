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
