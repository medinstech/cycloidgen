# Changelog

Notable changes, newest first. Versions follow the `major.minor.patch` of the
package in `pyproject.toml`; anything that changes a computed number gets called
out, because that is the only kind of change that can quietly invalidate a
design somebody already built.

## 2.2.0

**Added**

- **3D view.** The assembled drive, turning under the same crank as the drawing:
  orbit, pan, zoom, standard viewpoints, an explode slider and per-group
  visibility. Built from the same closed-form profile the drawing uses rather
  than tessellated from the solids, so it works in a build without the OCCT
  kernel and cannot drift from what gets exported. Rendered in software - no
  OpenGL, no scene graph - which is what makes it work over a remote desktop
  and testable without a display.
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

**Changed**

- The crank control moved out of the Drawing tab and now drives the drawing and
  the 3D view together; it hides itself on tabs where it would do nothing.
- The drawing is built once and moved rather than rebuilt per frame. A frame
  costs about 10 ms instead of 25, so the animation now keeps its timer instead
  of running at whatever matplotlib could manage.
- Part colours come from one table shared by the 3D view and the STEP assembly.
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
