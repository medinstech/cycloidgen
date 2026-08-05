# Contributing

Thanks for looking. This is a small, opinionated tool and the bar for changes is
"does it make the answers better", not "does it add a feature".

## Before you start

The single most valuable contribution needs no code at all: **build one of these
and measure it**. Lost motion, torsional stiffness, efficiency, running
temperature, failure torque. Every number this tool produces is a
first-principles estimate with a stated model, and a table of
predicted-versus-measured is worth more than any feature anyone could add. It is
the difference between a calculator and a calibrated instrument. Open an issue
with what you built and what you measured.

### Settled questions

These are decided, and a pull request that reopens one will get a polite no.
Everything else is open.

- **FEA.** Out of scope. The point of this tool is to get you to a good design
  in seconds so that FEA has something worth meshing.
- **Involute gears.** Well served elsewhere.
- **`ruff format`.** The repository has a hand-aligned style — continuation
  lines under their openers, tables laid out to be read as tables — and the
  formatter would rewrite 46 files to remove it. Lint hunts bug shapes; a
  formatter enforces a preference. The first is worth a CI job, the second is
  worth a discussion first.
- **Shadows, gradients and depth effects.** Structure is *drawn* — a hairline, a
  fill, a border — rather than implied by a light source that is not in the
  room.

## Getting set up

```powershell
py -3.12 -m venv .venv                          # Windows
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check .
```

```bash
python3 -m venv .venv                           # Linux, macOS
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
```

Both have to pass. CI runs them on Linux, Windows and macOS across the oldest
and newest supported Python, then separately exports a bundle and runs a design
search from the command line.

Qt tests run headless (`QT_QPA_PLATFORM=offscreen`, set by the test modules
themselves) and redirect preferences into a temporary file through
`CYCLOIDGEN_SETTINGS`, so running the suite will not rearrange your own
application.

## What a change looks like here

**Numbers are verified, not asserted.** Almost every claim in this repository is
pinned by a test that computes it a second way: the profile's envelope property
is measured against the pin-centre locus, the closed-form undercut limit is
cross-checked against a brute-force scan, the clearance is measured from the
manufactured profile rather than assumed from the input, the 3D mesh is checked
against the volume of the solid that gets exported, and the export manifest is
compared against the files that actually land on disk. If your change asserts a
new number, add the second way of getting it.

**Comments say why, not what.** The code is readable; the reasoning usually is
not. `# offset the pin circle` is noise. `# both levers have to shrink the disc,
and two of the three modes had the sign backwards` is the comment that stops
somebody reintroducing the bug. If you found something surprising, write down
what surprised you.

**Style is hand-aligned and stays that way.** 95 columns, continuation lines
lined up under their openers, tables laid out to be read as tables. `ruff check`
is the lint and it is in CI; `ruff format` is deliberately not, because it would
rewrite 46 files to remove that alignment. Match the file you are editing.

**One reason per change.** A pull request that fixes a bug, renames three things
and adds a feature is three reviews wearing a trench coat.

**Say when a number moves.** The pull request template asks whether your change
alters a computed value, and it is the question that matters most here: someone
may already have cut metal from the old answer. [RELEASING.md](RELEASING.md) has
the version policy, which is built around the same question.

## Where things live

```
cycloidgen/
├── core/       spec (the one source of truth), profile, kinematics, validate,
│               explain (what each check tests, why, and what to change)
├── analysis/   mechanics (Hertz), stiffness (contacts, backlash, transmission
│               error), compliance (the parts around the mesh, as springs),
│               tolerance (where the pins actually are), thermal, mass,
│               efficiency, bearings
├── design/     optimise (requirements -> geometry), sweep (trade studies)
├── viz/        mesh and scene: 3D geometry and rendering maths, no Qt
├── export/     manifest (what a bundle contains), dxf, svg, solid, bom, animation
├── report/     plots (shared by the app and the PDF), build
└── ui/         PySide6 window, 3D viewer, outputs tab, trade study, log panel
```

Two rules about that layout are worth knowing because breaking them is easy:

- **`core` and `viz` do not import Qt.** That is what lets the geometry and the
  renderer be tested without a display, and what keeps the same code drawing
  both the window and the PDF.
- **`export/manifest.py` declares every output file exactly once.** The writer,
  the Outputs tab, `--list-outputs` and the table in the README all read it. Add
  a file to a bundle by adding it there first.

## Brand assets

`cycloidgen/ui/assets/` and the Medinstech name are trademarks and are **not**
covered by the Apache-2.0 licence — see [NOTICE](NOTICE). Do not add, alter or
re-use them. If you are forking, replacing them is a single change confined to
`cycloidgen/ui/branding.py`, which is why that module exists.

## Reporting a bug

Include the design. `File ▸ Save design...` writes a JSON file that reproduces
the state exactly, or paste `report.json` from an export. A ratio and a
screenshot is usually not enough to reproduce a geometry problem; the spec
always is.

If the bug is that a number looks wrong, say what you expected and where the
expectation came from — a measurement, a catalogue figure, a textbook. That is
the difference between a bug report and a disagreement.
