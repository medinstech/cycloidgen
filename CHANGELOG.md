# Changelog

Notable changes, newest first. Versions follow the `major.minor.patch` of the
package in `pyproject.toml`; anything that changes a computed number gets called
out, because that is the only kind of change that can quietly invalidate a
design somebody already built.

## 2.2.0

**Added**

- **3D view.** The assembled drive, turning under the same crank as the drawing:
  orbit, pan, zoom, standard viewpoints, an explode slider, per-group visibility
  and a section plane. Built from the same closed-form profile the drawing uses
  rather than tessellated from the solids, so it cannot drift from what gets
  exported, and verified against the volume of that solid part by part.

  Rendered on the GPU through VTK, which the CAD kernel already installs, so it
  costs no new dependency: depth buffer, smooth shading off feature-angle
  normals, a three-point light rig, screen-space ambient occlusion sized off the
  drive, multisampling. Geometry is uploaded once per design and a frame sets
  one transform per part, so a 59:1 drive costs what a 15:1 one does.

  A software renderer - back-face culled, painted back to front with QPainter -
  stays as the fallback for a build without the kernel, a machine with no
  OpenGL, or a remote session that will not forward it. It is also what draws
  the 3D views in the PDF, as vector rather than a screenshot, and what makes
  the projection testable with no display at all.
- **Outputs tab.** Every file an export writes, listed by name with what it is
  for and where it will land, *before* anything is written; sizes filled in
  afterwards, and any of them opens on a double-click. Groups (drawings,
  solids, data) can be selected independently.
- **Export manifest** (`cycloidgen/export/manifest.py`) as the single
  declaration of what a bundle contains. `write_bundle`, the Outputs tab,
  `--list-outputs` and the table in the README all read it, and a test compares
  it against the files that actually appear on disk.
- `--list-outputs` and `--only drawings,data` on the command line.
- **Overlays on the drawing**: contact points sized by the load they carry,
  contact forces to scale, the path a point on the disc rim travels over a full
  output revolution, and ring pin numbers. All off the same kinematics the
  checks and the datasheet use.
- Input and output angle readouts on the drawing, an input-shaft ray inside the
  bore, and an animation speed control.
- The PDF report now carries the 3D assembly beside the drawing on page one, and
  an exploded view above the build order.
- **A Windows installer** (`packaging/cycloidgen.nsi`, NSIS): upgrades in place
  by clearing the previous version first, waits if the application is running,
  registers with Add/Remove Programs, and leaves preferences and the last design
  alone when uninstalled. English and Turkish. `packaging/release.ps1` builds
  the bundle and the installer in the right order and refuses to package a
  bundle that reports a different version.
- **A release workflow** on `v*` tags: checks the tag against the source, runs
  lint and the suite, builds and verifies the bundle, builds the installer, and
  publishes a GitHub release with this file's section as the notes. A second CI
  job compiles the installer script against a stub on every push, which takes
  seconds instead of the half hour the real one needs.
- `--version` on the command line.

**Versioning**

The version now lives in exactly one line, `cycloidgen/__init__.py`. The wheel
reads it (`dynamic = ["version"]`), the executable's file properties are stamped
from it, the installer parses it, and the release workflow refuses a tag that
disagrees with it. `tests/test_version.py` fails if a second copy appears, if
the line stops being statically readable, or if this file has no section for the
current version. See [RELEASING.md](RELEASING.md), which also says what makes a
release major, minor or patch — the question being what the change does to a
design somebody has already built.

**Changed**

- The crank control moved out of the Drawing tab and now drives the drawing and
  the 3D view together; it hides itself on tabs where it would do nothing.
- The drawing is built once and moved rather than rebuilt per frame. A frame
  costs about 10 ms instead of 25, so the animation now keeps its timer instead
  of running at whatever matplotlib could manage.
- Part colours come from one table shared by the 3D view and the STEP assembly.
- The mesh cache is keyed on the fields the geometry depends on rather than on
  the whole design, so changing a material or the rated torque no longer sends a
  fresh copy of the assembly to the graphics card.

**Fixed**

- **The rotation animation no longer jumps when it loops.** It was wrapping the
  crank at 360 degrees, but one input revolution does not put the drive back
  where it started - the disc and the carrier have advanced by 360/lobes. The
  period is `lobes` input turns, one output revolution, and wrapping there is
  seamless because every part really is back at its starting pose. The crank
  slider still reads 0-359, because that is the angle the user set.
- Disc file naming (`disc` versus `disc_1`, `disc_2`, …) comes from one place,
  so the DXF and the STEP exporters cannot disagree about the stack.

**Numbers**: unchanged. Nothing in `core`, `analysis` or `design` moved.

## 2.1.0

- Manual light/dark appearance override, with the desktop theme sampled once at
  start-up so "follow system" can return to light.
- Workspace memory: tab, crank angle and panel split, the split stored as a
  proportion rather than in pixels.
- Severity filter on the checks list, with counts on the toggles.
- Ruff configuration committed and a lint job in CI.
- The Medinstech brand applied to the application chrome; light mode is tinted
  paper rather than white, and both palettes are contrast-tested.

## 2.0.0

- Design search: state ratio, torque, speed, envelope, process and materials and
  get a shortlist of geometries that pass every check.
- Trade studies: sweep one parameter, watch four consequences.
- Stiffness, backlash, thermal, mass and efficiency studies; bill of materials;
  PDF dossier.
- Clearance measured from the manufactured profile rather than assumed. Two of
  the three offset modes had the pin-circle sign backwards and were cutting an
  interference; `both` cancelled itself to almost exactly zero.
- Multi-disc stacks: the discs are different parts, and the per-part files, the
  STLs and the bill of materials keep them apart.
