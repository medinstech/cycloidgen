# Changelog

Notable changes, newest first. Versions follow the `major.minor.patch` of the
package in `pyproject.toml`; anything that changes a computed number gets called
out, because that is the only kind of change that can quietly invalidate a
design somebody already built.

## 2.4.0

**Added**

- **Transmission error.** The ripple in output angle under a steady load — the
  number that decides whether a drive can *position*, as opposed to lost motion,
  which is only the play before it starts moving. It appears on the datasheet
  and in the comparison table, in `report.json` under `transmission_error`, in
  the PDF beside the backlash table, and as a `TRANSMISSION_ERROR` finding with
  its own explanation.

  The solve it comes out of was already there: `analyse_stiffness` finds the
  loaded rotation at every crank angle, and the peak-to-peak of that curve *is*
  the transmission error. Three things had to be got right on top of that.

  **The two stages have different periods.** The ring mesh repeats every lobe
  pitch. The output stage does not: the eccentricity direction seen from the
  carrier advances at `(N−1)/N` of the crank, so its pattern repeats every
  `2·pi·N/(n·(N−1))` — about two and a half lobe pitches on a typical drive.
  Sweeping a lobe pitch, which is what the existing sweep covers, reports about
  half the ripple that is there (1.27 against 2.07 arcmin on the 29:1 preset).
  Each stage is now swept over its own period and the two are added; the periods
  are incommensurate, so over an output revolution they do line up.

  **A phased disc stack cancels much of it.** Discs half a lobe pitch apart ride
  opposite halves of the same cycle. So the stack is solved as one system — every
  disc at its own crank phase, sharing one carrier rotation — rather than one
  disc scaled by the disc count. That is worth a third of the ripple on two
  discs and five sixths of the ring share on three. It is invisible to the
  stiffness model, and correctly so: phasing does not move the *mean*, which is
  all stiffness is.

  **A ripple has to be resolved, not averaged.** A mean over one period converges
  at any step count; a peak-to-peak only ever comes out too small. The output
  stage gets 48 steps per period and the ring 12, which lands within a quarter of
  a percent of a sweep six times finer — the stiffness sweep's own eight steps
  can be 30% low on the ring share.

  What it says is worth knowing: the output pins, not the ring mesh, are where
  nearly all of it comes from, so **more output pins** is the biggest lever
  (4 pins 5.4 arcmin, 16 pins 0.22 arcmin on the 15:1 preset), then the hole fit,
  then a phased stack. A stiffer disc material is *not* a fix — it leaves the
  clearance to be taken up exactly where it was and pulls fewer pins into mesh
  while it is at it, which makes the ring share worse. `tests/test_stiffness.py`
  pins that, because it is the fix everybody reaches for first.

  Both halves of the error are in the number, the clearance take-up and the
  elastic deflection, because the solve does not separate them and neither does
  the output shaft. What is *not* in it is the manufacturing half — pin position
  error, profile error, runout — which needs a tolerance input the app does not
  have yet.

**Changed**

- **Mesh clearances are measured once and cached.** `mesh_gaps` is a pure
  function of the geometry and the crank angle, and the checks, the stiffness
  study and now the transmission-error study ask for the same angles. It is
  handed out read-only, like the contact sweep, for the same reason: a cached
  array is one everybody else is still holding.

**Numbers**

Nothing that was there moved — checked field by field over six designs across
the offset modes, disc counts, processes and materials, and every one of the 500
values is bit-identical. A saved design reopens on exactly the answers it gave
before, with one number on the datasheet that was not there yesterday.

## 2.3.1

**Fixed**

- **No console window behind the application.** The bundle built one
  executable, with a console, so opening cycloidgen from the Start menu put a
  black window behind it. It now builds two over the same analysis, which is the
  `pythonw.exe` / `python.exe` arrangement and for the same reason:
  `cycloidgen.exe` is windowed and is what every shortcut points at, and
  `cycloidgen-cli.exe` is the console build for headless runs.

  Simply turning the console off would have taken the command line away, and
  taken it away badly: a frozen windowed process has no stdout at all, so
  `--version` would not have printed nothing, it would have raised - and that is
  the command both `release.ps1` and the release workflow verify the build with.
  They ask the console build now. `launcher.py` also gives the windowed one a
  stream to write to, so a stray `print` cannot fell it.
- **The installer's Turkish pages are Turkish again.** They shipped in 2.3.0 as
  mojibake - the welcome page read "hoÅŸ geldiniz". `makensis` assumes the
  system ANSI codepage unless the script carries a UTF-8 BOM or the charset is
  named on the command line, so the UTF-8 bytes of `ş` were read as two Latin-1
  characters. The script now has a BOM, which covers a hand-run, and every
  caller passes `/INPUTCHARSET UTF8`, which covers a BOM that some tool has
  helpfully removed.

  Nothing about this fails a build. The installer compiles, the suite passes and
  CI is green; it only appears to somebody who runs the setup and reads Turkish,
  which is how it reached a release. `tests/test_packaging.py` holds both ends
  now: the file says what it is, and every tool that reads it is told.

  **The published 2.3.0 installer still has it.** A corrected one needs a new
  tag.

**Numbers**

Nothing computed moved. This is the installer's own text; the application, the
analysis and every exported file are untouched, and a saved design reopens on
exactly the answers it gave before.

## 2.3.0

**Added**

- **Export the animation.** The drive turning, as a looping GIF: a fourth output
  group writing `motion.gif` with the bundle, and **File ▸ Export animation**
  (`Ctrl+Shift+E`) for whichever view is on screen - the drawing with the
  overlays you have ticked, or the assembly from the angle, explode and part
  visibility you have set. It renders off the GUI thread with a real progress
  bar and a Cancel that leaves no half-written file. The README's own animation
  is now generated by `docs/make_figures.py`, like every other figure in it.

  The run length is chosen rather than assumed. Different parts of the drive
  close at different times: the disc, the ring contacts and the force arrows
  after a single input turn, because one turn walks the disc on by exactly one
  lobe pitch and the profile is unchanged by that; the output carrier only after
  `N / gcd(N, output_pin_count)` turns. Where the exact period does not fit the
  frame budget, the run picked is the one whose carrier lands *closest* to a
  hole pitch, which is usually not the longest one that fits - at 29:1 five
  turns leaves 2.1 deg and ten leaves 4.1.

  Two of Pillow's defaults are wrong for this and both were caught: a fresh
  palette per frame, which on flat fills reads as the paper shifting hue as it
  plays, and dithering, which scatters a flat background into noise no LZW
  stream can compress. `Image.quantize(palette=...)` is a five-bit colour-cube
  lookup rather than a nearest-colour match and puts pure white on a near-white
  entry, so the whole run is quantised together instead.
- **"Explain this check".** Selecting a finding shows what the check tests, why
  it matters physically, what to change and in which direction, and the margin -
  how many times clear of the limit the design sits, where a ratio means
  anything at all. `cycloidgen/core/explain.py` declares one explanation per
  code; `tests/test_explain.py` parses the source for the calls that raise
  codes and fails if a check has no explanation or an explanation has no check.
  Selecting a finding also no longer loses its selection on every re-analysis,
  which is every nudge of a spin box.
- **Unit preference** (View ▸ Units): millimetres or decimal inches, for
  everything you read - parameter fields, datasheet, checks list, comparison
  table, the explanation panel's reading and the drawing's own title. Everything
  you hand over stays millimetres: DXF, STEP, STL, the JSON report and the PDF.
  A CAD file whose units follow a preference is a CAD file nobody can trust.

  The design never leaves millimetres. Switching reloads the widgets *from the
  spec* rather than converting the numbers in them, so a toggle cannot round a
  value out and back. Guarded, too: narrowing a spin box's range makes Qt clamp
  what is in it and a clamp emits `valueChanged` like any other edit, so the
  first version quietly rewrote a 50 mm pin circle as 500 mm on the way into
  inches.
- **Screenshots of the running application** in the README, and a repeatable
  way of taking them: the window is built, given the hero design and told which
  check to select, then grabbed. The 3D tab needs `PrintWindow` from outside
  because its viewport is a native OpenGL surface.
- `pillow` is now a declared dependency. It arrived behind matplotlib anyway;
  the animation imports it directly.

**Changed**

- The chord-tolerance sample count is rounded up onto a whole number of samples
  per lobe, so the sampled polygon has the disc's own symmetry: turning it by
  one lobe pitch gives back the same vertices instead of ones a fraction of a
  step along. It can only reduce the chord error, and it costs fewer than
  `lobes` extra points out of at least 720.
- `include_solids=False` means everything except the solids rather than the two
  groups that existed when it was written, so a drawings-only run gets the
  animation too - it comes off the same closed-form profile and needs no kernel.
- **Every table of numbers asks for a monospace family per platform** rather
  than for `Consolas`, which is a Windows font. Off Windows, Qt was left to
  substitute by style hint and could land on something that does not line up a
  column - which is the entire reason those tables are monospaced. One list,
  `branding.MONO_FAMILIES`, and one helper the four call sites share.
- **CI runs on macOS as well as Linux and Windows.** There is still no macOS
  package, but "it is pure Python on cross-platform wheels, it should work" is
  not a claim worth making without a run behind it.
- **The chrome is reworked.** Corners eased, structure drawn in one hairline
  weight, and the brand colour spent only where it means "this one" - the
  primary action, the focused field, the selected row and tab, a ticked box,
  the filled part of a slider. It used to be on every group heading, tab, table
  header, status bar and rule; at that point it is not emphasis, it is a
  background colour that happens to be loud. Group headings are labels again
  rather than filled badges, tabs are marked with an underline rather than a
  block, spin buttons lost the divider that made them read as a separate
  control bolted to the field, and numeric fields are set right so the column
  can be scanned. See *Deliberately not doing* in the roadmap, which this
  overturns half of and says why.
- **The plot toolbar carries four tools instead of nine.** *Subplots* and
  *Customize* offer to re-scale and restyle a drawing whose scale is
  millimetres and whose colours are the part colours, which can only make the
  picture disagree with the numbers beside it; *Back* and *Forward* walk a view
  history a single-axes drawing barely has. Reset, pan, zoom and save remain,
  and their icons are tinted from the theme.

**Fixed**

- **The drawing's outline no longer shows its seam.** It was a polyline with its
  first point repeated, so the two ends met on one vertex and each laid down its
  own antialiased cap. Drawn as a closed path the seam is a join like any other.
  Visible because the seam travels round the rim as the disc turns: a handful of
  pixels changed every frame at a place where nothing was happening.
- **A pin at the load reversal is no longer drawn as carrying.** Two pins sit at
  zero moment arm at any crank angle, and whether they come out of the
  arithmetic at +1e-13 or -1e-13 depends on how the angle was reached. `force >
  0` turned that into a contact dot that appeared and disappeared, and a count
  of pins carrying that flickered by one. Drawing only, no reported number
  moves.
- **The checks list can no longer be squeezed out of existence.** The stage is a
  tab widget whose pages ask for several hundred pixels each, so on a window
  that was merely a bit short the layout paid for them out of the only widget
  that would yield - and the findings list went to zero. It takes the answer to
  "is anything wrong with this design" with it, quietly, with no scrollbar to
  notice. It now has a floor, cannot be collapsed, and its split is remembered
  between sessions like the other one.
- **The 3D view is themed before it is first shown.** It paints its own
  background rather than taking one from the stylesheet, and nothing told it the
  mode until the appearance was *changed* - so opening in dark mode gave a white
  viewport in a dark window, which looked like the tab had failed.
- **The release workflow can actually publish.** It built the release notes by
  redirecting Python's stdout into a file, and the changelog is UTF-8 - it
  carries the menu arrow, among other things. stdout on a Windows runner is the
  locale encoding, so the publish step would have gone down with a
  `UnicodeEncodeError` *after* ninety minutes of building the bundle and the
  installer. It writes the file from Python now, with the encoding named.

  `tests/test_workflows.py` holds that end down: it parses every workflow,
  requires the release to trigger only on a tag, and *runs* the notes step under
  a Windows locale encoding. A broken workflow file is otherwise close to
  invisible - GitHub reports a run with no jobs, an instant failure, and the
  file path where the workflow name should be.
- The installer script's CI job creates `releases/` before running `makensis`.
  The folder is gitignored, so it is never in a fresh checkout and NSIS will not
  create the one its `OutFile` lives in; the job had never passed.

**Numbers**

Nothing computed moved. Both fixes above are the drawing only - no datasheet
value, check verdict or report field changes - and the sample-count change can
only reduce the chord error of an exported polyline. A saved design reopens on
exactly the answers it gave before.

## 2.2.0

**Added**

- **3D view.** The assembled drive, turning under the same crank as the drawing:
  orbit, pan, zoom, standard viewpoints, an explode slider, per-group visibility
  and a capped section plane. Built from the same closed-form profile the drawing uses
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

- **The section shows solid material, not a hollow shell.** A clipping plane
  removes the front of a surface and leaves you looking into the inside of a
  casting; the cut is now capped, with the cut faces a shade darker than the
  part, which is how a section drawing has marked them for a century.
- **"Edges" draws the part's edges, not its triangulation.** It was drawing
  every cell edge, and since the end faces are triangulated to get their holes,
  a disc arrived covered in whatever long thin triangles the triangulator had
  produced. Now only the features: rims, hole lips, the join between a cylinder
  and its end.

  Getting those to *land on the edges* took three attempts, and the two that
  failed are worth writing down. A **depth-buffer offset** is fixed in depth
  units while zooming magnifies only the screen, so a value that shows the
  lines from across the drive shows every hidden edge through the part once you
  lean in. **Lifting along the surface normal** moves a line on a vertical wall
  sideways, and the rim of a disc ends up drawn beside the disc - a halo,
  plainly visible at any real zoom. What works is sliding each line vertex
  along its own view ray toward the camera, by a thousandth of its distance: a
  point moved along the ray it is already on projects to exactly the same
  pixel, so the picture does not move and only the depth does, and because the
  shift is a fraction of the distance it scales itself as you zoom.
- The VTK pipeline keeps points in double precision. At 50 mm, 32-bit floats
  resolve about 3 nm, which sounds like plenty until you remember this geometry
  carries clearances of a few tens of micrometres.
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
