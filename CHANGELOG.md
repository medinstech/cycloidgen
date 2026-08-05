# Changelog

Notable changes, newest first. Versions follow the `major.minor.patch` of the
package in `pyproject.toml`; anything that changes a computed number gets called
out, because that is the only kind of change that can quietly invalidate a
design somebody already built.

## 3.2.0

**Added**

- **Fatigue, not just static strength.** Every other strength check in the app
  asks whether a part survives its peak load once. For two of them that is the
  wrong question: the disc web and the output pins are loaded and unloaded once
  per input revolution — the web because the load sweeps a whole turn around it,
  the pins because the push rotates about them — so both see a fully reversed
  cycle, and a part can sit well inside yield and still crack.

  Marin-corrected infinite life against Goodman, at the running temperature from
  the thermal solve rather than at ambient, and at 99% reliability because the
  published strengths are means. Surface finish is a real term in it and the
  biggest one: a ground disc and a printed one differ by a factor of three on
  the same alloy, which makes a manufacturing choice into a strength decision.

  Polymers get no number. Printed-part fatigue turns on layer orientation and
  void content far more than on tensile strength, and a rule fitted to wrought
  metal applied to PLA would be a confident answer with nothing behind it — so
  the report says the question is not being answered rather than answering it
  badly. Aluminium and bronze are reported on a 5e8-cycle basis and say so; they
  have no endurance limit to quote.

**Fixed**

- **The design search was returning drives whose output pins bend on the first
  turn.** Nothing in the app had ever looked at output pin bending, and the pins
  are cantilevers — `export.solid` extrudes them from one carrier plate and
  nothing catches their free ends. Asked the question for the first time, every
  design the search returned for its own steel requirements came back between
  0.11 and 0.99 on fatigue, and the thin ones were past yield in bending as
  well. It varies pin diameter and count already, so it can find its way out; it
  had simply never been told this was a constraint. It is now, and there is a
  test that the designs it hands back survive being turned.

**Changed**

- **The material table gains an ultimate tensile strength and a fatigue
  strength.** The ultimate is needed for Goodman and for the surface factor. The
  fatigue strength is stated per material rather than derived from it, because
  the usual 0.5×Sut stops holding above about 1400 MPa — 100Cr6 would otherwise
  be credited with 1000 MPa of endurance limit it does not have.

## 3.1.1

**Fixed**

- **The 3D tab no longer takes the application down on macOS.** Opening it hung
  the window on a spinner and then killed the process. It is the same failure
  the offscreen platform has, and it was guarded against there and nowhere else:
  VTK's Python widget builds its GL context directly on the view `winId()`
  returns, with `WA_PaintOnScreen` set — an attribute Qt documents as X11-only,
  on a platform whose views have been layer-backed and mandatorily so since
  10.14. The first render blocks the main thread as the tab opens.

  What made it fatal rather than merely broken is that a process dying is not an
  exception. `build_view` has always caught a failing renderer and fallen back
  to the software painter; there was nothing to catch, so the fallback never got
  its turn. macOS is now refused the hardware path *before* a render window is
  constructed, exactly as the headless platforms are, and gets the software
  painter — which draws the same scene from the same mesh and is what the PDF
  has always used.

  `CYCLOIDGEN_VTK=1` tries VTK anyway, `CYCLOIDGEN_VTK=0` refuses it anywhere.
  The first is how the proper macOS widget will be developed; the second is the
  first thing to ask someone whose 3D tab misbehaves.

  This is a guard, not the fix. Making macOS render on the GPU needs a widget of
  our own over `vtkGenericOpenGLRenderWindow` drawing into the framebuffer Qt
  hands it, because VTK 9.6's `QOpenGLWidget` support is a base class and
  nothing else: no `initializeGL`, no `paintGL`, no `QSurfaceFormat`, and still
  a plain `vtkRenderWindow` given `winId()`.

  None of this was caught by CI, and could not have been: the suite runs
  offscreen, `available()` returns False offscreen, so **the VTK path is not
  exercised on any platform**. The macOS job proves the application imports and
  the software painter works. It says nothing about the hardware viewport, and
  `tests/test_workspace.py` now says so where somebody will read it.

**Numbers**

Nothing computed changed. This is which renderer draws the 3D tab.

## 3.1.0

**Added**

- **Manufacturing tolerance as an input.** A **Pin position** field under
  Manufacturing: the true-position tolerance zone diameter on the pin holes,
  stated the way a drawing states it, and applied to the ring pins and the
  carrier pins alike on the argument that one shop drilled both.

  It matters more than its size suggests. Everything else in the app places the
  pins exactly, and with a uniform clearance that means every pin needs the same
  rotation to come into mesh — so they all arrive together. A few hundredths of
  position error is enough to decide which ones arrive first and carry the load
  by themselves.

  **An ensemble, not a worst case.** A single tolerance number does not say
  where each pin went, and both usual ways of turning it into an answer are bad
  on their own: worst case is a ring nobody will ever build, and nominal is a
  ring nobody has ever built either. So `analysis/tolerance.py` draws *rings* —
  each sample a whole set of pin positions, uniform over the tolerance zone —
  and the load-sharing solve runs on each the way it runs on a perfect one. What
  comes back is a distribution, quoted as the middle ring and the bad one: 24
  rings for the load study, 12 for transmission error, which costs a full mesh
  cycle at ripple resolution per ring. The draw is seeded from a constant, so a
  design gives the same answer today and next month — an analysis that moves
  when you reopen it cannot be checked against a measurement.

  On the 15:1 preset at ⌀0.10 mm true position: stiffness 1.769 → 1.487
  Nm/arcmin with a soft decile of 1.337, load concentration 3.28 → 3.93 with a
  ninth decile of 4.18, and the pins actually carrying drop from 1.75 to 1.31 of
  the eight the ideal model loads.

  It also gives **transmission error the half it was missing**. 3.0.0 said in as
  many words that pin position, profile error and runout were not modelled;
  position is now, and it is most of what a measured trace shows: 1.99 → 5.03
  arcmin peak to peak on that same design, with 6.98 for the worst ring of the
  batch.

  And it produces the sharpest constraint in the app. Past the point where the
  tolerance approaches the clearance, pins are driven *into* the disc and the
  drive binds instead of turning — a 29:1 EDM design with 0.012 mm of clearance
  starts interfering at ⌀0.02. That is reported rather than absorbed, because a
  single-rotation solve reads an interfering pin as one that just touches, which
  makes a jammed ring look like a *better* drive with less backlash and more
  pins engaged. A `PIN_POSITION` warning names the depth and says the figures
  around it are the optimistic version.

  Deliberately **not** applied by *Apply process defaults*, unlike the
  clearances. A clearance is a dimension you choose and the model has always had
  one; a position tolerance is a claim about what your machine actually holds,
  and defaulting it to a guess would quietly derate every design in the app on
  the strength of that guess. The `PIN_POSITION` check names the guide value for
  the selected process instead, and it stays a suggestion until you enter it.

**Changed**

- **The design search sees the tolerance too**, over a short batch of six rings
  rather than the full twenty-four — it is choosing between designs rather than
  reporting one, and a search blind to the tolerance would happily pick a design
  that only works on paper.

**Numbers**

Nothing moved. Verified field by field against a v3.0.0 checkout over six
designs spanning the offset modes, disc counts, processes and materials: every
value is bit-identical, transmission error included. The new figures appear only
once a tolerance is entered, and a design with none is solved over exactly one
ring — which is the perfect one it was always solved over.

Cost follows the same rule: unchanged with no tolerance entered, and about
0.5 s of analysis with one, nearly all of it the transmission-error batch.

## 3.0.0

**This release changes computed numbers.** Torsional stiffness falls on every
design — see **Numbers** — because the model stopped calling half the gearbox
rigid. Reopen anything you sized on 2.x before you cut it.

**Added**

- **Housing, shaft and carrier compliance** — `analysis/compliance.py`. The
  stiffness model solved two contact stages and declared everything they were
  mounted in to be rigid, which made every answer an upper bound and was the
  largest known error in the model. Six springs now sit in series with the
  contacts, each a closed form off geometry the app already has:

  | Part | Modelled as |
  |---|---|
  | Carrier plate | an annulus in in-plane torsion, bolt circle to rim |
  | Carrier pins | cantilevers off the plate, in bending **and** in shear |
  | Disc body | an annulus in in-plane torsion, holes out to the rim |
  | Ring pin seats | a conforming line contact, pin bedding into its pocket |
  | Housing | a barrel in torsion, picking the load up along the stack |
  | Input shaft | a bar in torsion, divided by the *square* of the ratio |

  Each is reported on its own line — in the datasheet, in `report.json` under
  `stiffness.structure`, and as a table in the PDF — because "everything else"
  as one number is a number to distrust, and because the softest part is usually
  a surprise. On a small printed drive it is the ring pin seats, where a steel
  pin beds into a polymer housing; as soon as the stack gets taller or the mesh
  gets better it is the carrier pins, which do not care what the mesh is made of.
  A `STRUCTURAL_COMPLIANCE` finding names the softest part and warns when the
  parts around the mesh are softer than the mesh itself. On the presets that is
  the three-disc stack and the ground steel drive — the two whose mesh is good
  enough for the carrier to become the problem.

  Two things are stated in the module rather than buried, because the geometry
  does not settle them. **The carrier plate is rim-driven** — its centre bore is
  clearance for the input shaft passing through, not a hub — and a drive that
  takes its output from a hub on the axis instead is an order of magnitude softer
  there, because the formula goes as `1/r²`. **The load reaches the carrier pins
  at the middle of the stack**, one spring instead of the coupled set a rigorous
  treatment would need, and exact for a single disc.

  The ring pins are deliberately not in the table. They sit half-buried in
  pockets cut to their own radius and supported along their whole length, so they
  bed rather than bend — that is a contact, and it is modelled with the contacts.

  What the numbers say is worth acting on. Fatter carrier pins are the single
  biggest lever on any drive whose mesh is decent, because a cantilever goes as
  the fourth power of diameter; a second carrier plate supporting the far ends of
  those pins would be worth roughly an order of magnitude on that line, which is
  why production reducers have one. It is also why a **taller stack now costs
  something**: three discs share the load between three meshes, but they stand
  the same carrier pins off a plate half again as far, and the 3-disc 21:1 design
  loses 65% where the 2-disc ones lose 45%. And it is why the headline falls
  furthest on the *best* drives — a ground steel mesh stiffens by two orders of
  magnitude and a cantilevered pin does not stiffen at all.

**Fixed**

- **The contact model paired each body's radius with the other body's modulus.**
  Johnson's line-contact approach carries one logarithmic term per body, each
  with that body's own radius *and* its own elastic constants. The call passed
  the pin's radius with the disc's modulus and vice versa. It cancels when both
  parts are the same material, which is why a steel drive barely notices, and it
  is worth 12–20% on a printed one, where a steel pin meets a polymer flank whose
  radius is several times larger. The argument names now say which is which.

**Numbers**

Torsional stiffness falls on every design. Two separate causes, and they are
worth separating because one is a fix and the other is new physics:

| Design | 2.4.0 | contacts alone | with the structure |
|---|---|---|---|
| 15:1 preset, PLA, FDM, 5 Nm | 3.218 | 2.792 (−13%) | **1.769 (−45%)** |
| 29:1 preset, PLA, FDM, 5 Nm | 6.107 | 5.400 (−12%) | **3.350 (−45%)** |
| 21:1, three discs, 5 Nm | 6.177 | 5.478 (−11%) | **2.163 (−65%)** |
| 29:1, hardened steel, EDM, 50 Nm | 239.4 | 239.3 (−0.0%) | **23.40 (−90%)** |

Wind-up at the rated torque rises to match: 2.95 → 4.43 arcmin on the 15:1
preset, 0.37 → 2.30 on the steel one. Total backlash follows it, by about 1% —
the play dominates that sum and the play has not changed.

The contact fix also moves the load sharing, because softer contacts turn
further and pull more pins into mesh. Load concentration falls 6–12% on printed
designs, so the torque capacity *after* derating rises by the same: 0.681 → 0.728
Nm on the 15:1 preset, 0.902 → 1.021 on the 29:1. Ring safety factor rises 3–6%
with it. A steel drive is unaffected to four figures.

Lost motion, transmission error, contact stress, efficiency, thermal, mass,
bearings and every exported geometry are untouched.

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
