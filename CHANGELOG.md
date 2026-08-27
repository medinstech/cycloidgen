# Changelog

Notable changes, newest first. Versions follow the `major.minor.patch` of the
package in `pyproject.toml`; anything that changes a computed number gets called
out, because that is the only kind of change that can quietly invalidate a
design somebody already built.

## 7.7.0

**Numbers** — none move. A design with no duty cycle analyses exactly as it did:
the field defaults to empty, nothing about a cycle feeds back into the geometry
or the rated point, and `tests/test_duty.py` holds that by comparing whole report
sections between a design with a cycle and the same design without one. What is
new is a set of numbers a single rated point could not produce.

**Added**

- **A duty cycle, because a machine is not one point.** The app has always taken
  the duty as a torque out at a speed in, which is the right way to *size* a
  gearbox and the wrong way to describe a machine. A robot joint lifts, holds,
  returns and waits; a winch pulls hard and slowly and spools back fast and
  empty. A single point can be the worst of those or the average of them, and
  the app has been asking which one you meant without saying that it was asking.

  **Design ▸ Duty cycle** (`Ctrl+D`) takes a table of them: what it does, the
  torque, the speed at the output, and how long it lasts. The durations are in
  whatever unit suits — only the ratios are read — so a cycle can be typed the
  way it was measured rather than converted into shares that have to add up to
  one.

  The point of it is that the quantities **do not aggregate the same way**, and
  no single point is conservative for all of them at once:

  - **Stress** takes the worst point. Averaging the hardest moment away is how a
    drive passes on paper and cracks on a bench.
  - **Temperature** takes the mean loss. A housing integrates, and sizing the
    cooling to the peak is sizing it to a transient.
  - **Bearing life** takes neither. Life goes as the cube of load, so a varying
    load is carried at ISO 281's equivalent load — the cubic mean, which sits
    well above the arithmetic mean and well below the peak.
  - **The motor** takes both ends: it has to make the peak and survive the RMS.

  Four aggregations from one cycle. Getting any of them by picking a
  representative point is a coincidence rather than a method.

- **Holding still is a point, not an error.** Zero output speed is most of what
  some drives do: the torque is there so the contact loads are, nothing slides
  so there is no PV and no friction loss, nothing turns so no bearing life is
  consumed. It falls out of the arithmetic rather than being special-cased —
  the cubic mean weighs *revolutions*, so a point at half the speed contributes
  half the wear and a point at no speed contributes none, and the equivalent
  speed is averaged over the whole cycle including the standstill. That last
  one is what makes the life a number of hours of **cycle** rather than hours of
  rotation, which is the unit a service interval is actually written in.

- **`DUTY_RATING_MISMATCH`, and it is the check that makes the rest safe to
  read.** Everything on the datasheet — capacity, safety factor, wind-up,
  transmission error, fatigue — is computed at the rated torque. State a cycle
  that goes above it and every one of those numbers is describing an easier
  machine than the one you have just described. The drive is not wrong; the page
  in front of you is. Beside it, `DUTY_MOTOR_SHORT` names the hardest *moment* —
  which is not always the heaviest point, because torque falls with speed and a
  light point at speed can be tighter than a heavy one standing still — and
  `DUTY_BEARING_LIFE` reports the drive's own bearings over the cycle.

  That last one is the one that had to be built twice. The first version
  re-selected bearings for the cycle, which answers "what would I fit for this
  duty" and can therefore never report a bearing that falls short: it would
  simply have picked a bigger one. The question worth asking is whether the
  parts the drive *has* survive what it will actually do, so the rated
  schedule's parts are kept and only their lives are recomputed — at one scalar
  equivalent torque and one equivalent speed, which is exact here because every
  load in this machine is linear in output torque and every speed is linear in
  input speed. Doing it that way also means nothing has to match a role by its
  *name* to know what a number means, which is how the bearing quantities went
  wrong once before.

- **Where it shows up.** A section on the datasheet and in the PDF, a `duty`
  block in the JSON with every point and every aggregate, and a shape that
  matches the motor block: the key is always there so a consumer can tell "no
  cycle stated" from "an older version that could not be asked", with nulls
  rather than zeros so nothing reads a missing answer as a good one.

**Changed**

- **`analysis.bearings.life_hours` is public.** It is a fact about a part rather
  than a step in selecting one, and the duty cycle asks it of parts that have
  already been chosen.

## 7.6.0

**Numbers** — none move. Every existing design analyses exactly as it did:
`motor_kind` defaults to `none`, nothing about the motor feeds back into the
geometry, and `tests/test_motor.py` holds that promise by comparing whole report
sections between a design with a motor stated and the same design without one.
What is new is a set of numbers that were not there before.

**Added**

- **The motor is a curve now, not a mounting face.** The app has always known
  which NEMA frame a drive bolts to and nothing whatever about what comes out of
  the shaft — so the duty point was taken on trust: an output torque at a speed,
  worked back through the ratio and the efficiency to an input torque nobody
  then asked about. That is a complete answer to *is the gearbox strong enough*
  and no answer at all to *will this turn*, which is the question a drive is
  bought to settle. Set a torque curve under **Motor** in the panel and the
  analysis puts the duty point on it: what the motor has there, what is being
  asked of it, and the margin between.

  Two models, both closed form, both stated with their limits in
  [`core/motor.py`](https://github.com/medinstech/cycloidgen/blob/main/cycloidgen/core/motor.py).
  A **stepper**'s torque follows its phase current, and the current is what the
  supply can force through the winding against its resistance, its inductive
  reactance and its own back-EMF — `V^2 = (K*w_m + I*R)^2 + (w_e*L*I)^2`, solved
  for `I` and capped at the rated current. A **DC or brushless** motor gets the
  straight line between `Kt*V/R` at stall and `Kv*V` at no load, with the
  continuous rating carried as a separate, much lower line.

  Eight numbers off a datasheet, and three of them are shared between the two
  kinds because the sharing is physical rather than a squeeze: both motors run
  off the same bus, both datasheets print a winding resistance, and both have a
  current they will hold all day. What is *not* shared is what that current
  means — a stepper is current limited everywhere, so its curve is already its
  continuous curve, and a brushless motor's is drawn at stall current with a
  continuous line two orders of magnitude below it. Sizing a gearbox on the
  first is the classic way to build one that survives the bench and not the
  robot, so the margin reported here is on the continuous line and the peak is
  carried alongside rather than instead.

  The identity that makes this cheap is worth stating: torque per amp and volts
  per radian per second are the *same constant*, so a stepper's electrical
  ceiling falls out of its mechanical rating with nothing else needed —
  `n_ceiling = 60*V/(2*pi*K)`, where `K = T_hold/(sqrt(2)*I_rated)` because
  holding torque is measured with both phases energised. On 24 V a 0.4 Nm,
  1.7 A motor makes no torque at all past about 1380 rpm; on 12 V the same motor
  stops at 690. Halving the supply halves the top speed, and the supply is
  usually the cheapest thing in the design to change.

  It also says something people do not expect: on a fixed bus and a fixed
  current, **more holding torque buys less top speed**. More torque per amp is
  more volts per rad/s, so the bigger motor meets the supply sooner. Buying
  torque without buying current or volts moves the ceiling *down*.

- **Three checks and a reading.** `MOTOR_OPERATING_POINT` says where on the
  curve this duty point sits — how much of the standstill torque is left here
  and how close to the ceiling it is, which is the number that catches a drive
  designed on holding torque. `MOTOR_TORQUE_SHORT` is the test — thin
  margin, a duty that is a burst rather than a rating, or a motor that will not
  turn the drive at all. A warning in every case, including the last: an error
  in this app means the *files* are wrong, and these files are right. What is
  wrong is which motor goes on the end, which is fixed by buying a different one
  as readily as by redrawing anything — the same argument `MOTOR_SHAFT_MISMATCH`
  has always been a warning on. Blocking the export would also have made the app
  refuse to hand over a gearbox somebody is having machined so they can go and
  find a motor for it. `MOTOR_SUPPLY_VOLTAGE` catches the
  one thing the winding resistance decides on its own: a bus that cannot push
  the rated current through a stationary winding, which scales the whole curve
  down from the datasheet's, standing still included.

- **A MOTOR tab**, the curve with the duty point on it and the crossing where
  the motor runs out labelled, plus seven rows on the datasheet and a section in
  the PDF. Two of those rows are the ones to design against: the **output torque
  this motor buys** through this reduction at this efficiency, and the **output
  speed** past which it cannot make the required torque. On most designs here
  the first is smaller than the gearbox's own capacity — so the motor, not the
  contact stress, is what the drive is worth, and that comparison is now on one
  page.

- **The reduction can come from the motor.** In the search dialog, *work it out
  from the motor*: state what the **output** has to do and the reduction stops
  being part of the question. `design.ratio_band` asks the curve which whole
  reductions can drive that load — closed form, one curve evaluation each, no
  geometry needed — and the search then works across a spread of them and ranks
  the results together. A reduction is a means; the job is a torque at a speed.

  The band's two ends fail for different reasons and it says which. Below it the
  motor is short of torque and gearing down further helps. Above it the motor is
  short of *speed*, and gearing down further is what caused it — so the answer
  there is bus voltage or a different motor, and a design that fails both ends
  at once is a motor that cannot do the job at any reduction. Told apart by
  asking whether the *next* reduction up improves the margin, rather than by
  whether the speed ceiling has been reached: past the peak the motor is often
  still making torque, just less than the speed has taken away, and calling that
  a torque shortage sends somebody to gear down when gearing down is what did
  it.

  What the search leaves out, it says: a feasible band is usually dozens wide
  and each one costs a full search, so five are sampled and the rest are
  reported in the rejection tally. A bounded search that looks exhaustive is how
  somebody concludes a reduction does not work when it was never tried.

  On the command line it is `--ratio-from-motor --out-rpm 10`, and the curve
  comes off the design passed with `--design` rather than off eight more flags —
  the app already has a place to put those eight numbers, and a second way to
  state them would be a second thing to keep in step.

- **`motor_margin`** joins the batch metrics, so a study can sweep bus voltage
  or reduction against what the motor can hold. `nan` where no curve was stated
  — the same rule the fatigue margin follows on a printed part, because a study
  that sweeps a motor across a design that has none should come back empty
  rather than come back passing.

**Changed**

- **`GearSpec.motor` is now `GearSpec.motor_face`.** It returns the mounting
  face, and an analysis result now carries the motor's own answer under `motor`;
  leaving both called the same thing would have put two different objects behind
  one word on the two most-read classes in the app. `MotorFrame` and
  `MOTOR_FRAMES` moved to the new `core/motor.py` beside the curve and are
  re-exported from `core.spec`, so every existing import still resolves.

- **The panel has a Motor group.** The frame and *motor turns the cam* used to
  be filed under Mounting with the tie bolts, because a bolt pattern is what
  they did to the geometry. That put the two halves of "which motor" in
  different boxes the moment there was a second half. Fields the chosen kind
  does not use are greyed rather than hidden — the search box already owns
  visibility in that panel, and a field that vanishes takes the reason it does
  not apply with it.

**Fixed**

- **A headless run wrote its files and then died on the way out, on Windows.**
  `import cadquery` pulls casadi in whether anything uses it or not — the
  PyInstaller build already stubs it out of the frozen bundle for exactly that
  reason — and with casadi 3.8.0 the two native libraries corrupt the heap while
  they unload. The process does its work, prints its results, and exits
  `0xC0000374`. Nothing here calls casadi, so nothing here could avoid it;
  `casadi<3.8` is pinned on Windows until the unload order is fixed upstream.

  It matters more than a red tick on a dashboard: every scripted run reported
  failure having succeeded, which is the worst way for a tool to be wrong.

  Measured rather than suspected, and it took the measurement to get there. The
  suite ended `1048 passed, 1 skipped` and the step then said "exit code 1" with
  nothing else in the log, which reads as a test failure that has hidden itself.
  Four experiments said what it was not: the same failure on `v7.5.0`, code that
  had been green a fortnight earlier; the same failure with PySide6 pinned back
  to the version that was green; the same failure on every one of sixteen test
  modules run in its own process, and none on the other twenty-three. What the
  sixteen had in common was the CAD kernel. Then two lines were enough:
  `python -c "import cadquery"` crashes, `python -c "import casadi"` does not,
  and `import cadquery` on casadi 3.7.2 is clean.

- **The test step now reports the exit code it was given.** The default shell on
  Windows is pwsh, which GitHub runs with `$ErrorActionPreference = 'stop'`, and
  since PowerShell 7.4 that turns any native command failure into a terminating
  error and a flat `1`. The real code was `-1073741819`. A step that cannot tell
  you which of those it saw is a step that cannot be debugged, and this one was
  hiding the only fact that mattered.

- **The Qt test modules destroy their windows.** `test_workspace.py` built
  sixty-six top-level windows and took down none of them, `test_view3d` nine,
  `test_notice` one — each holding a 3D view, matplotlib canvases and a worker
  thread, all left for the interpreter to take apart at exit in whatever order
  Python's collector reached them. Two other test modules here have always used
  `deleteLater`; these are the ones that never did. They are hidden and deleted
  after each test now — hidden rather than closed, because `closeEvent` writes
  the workspace to the preferences and a teardown that silently saved state
  would hand the next test a window restored from one it never asked about.

  It was not the crash above, and it was worth doing anyway: the suite went from
  32:49 to 15:35 on the Windows runner, and from 17:53 to 8:42 locally. Sixty-six
  live windows were not only a bad way to end a process, they were a tax on every
  test that ran after them.

- **The drawing's two caption lines used to run across the gearbox.** They sat
  in the bottom-left corner of the *axes*, on the argument that the housing
  circle leaves that corner empty. It does, and neither line is short enough to
  stay in a corner: `set_aspect("equal")` makes the axes a square in the middle
  of a wide panel, the circle is inscribed in it, and a full line of monospace
  starting at the left edge runs straight under the circle and out the other
  side — across the disc on a 1560 px window and across the whole gearbox on a
  1180 px one. A corner is a place for a word, not for a sentence.

  Both lines are figure text now, in a strip `tight_layout` is told to keep off,
  and the strip is computed from the point size and the panel height rather than
  written down as a fraction — the same reason the layout is already re-solved
  on resize. Reserving the room rather than nudging the text is what makes it
  hold on all three canvases this one figure is drawn on: the app's letterbox
  panel, the PDF's square and the animation's small frame. Tested at four
  shapes, and what is asserted is that the *drawing* stops above the strip
  rather than where the text happens to be.

- **The 3D tab opened with the gearbox a third of the height of its own
  viewport.** VTK's `ResetCamera` fits a *sphere* around the bounding box, and
  a cycloidal drive is a flat cylinder — so the diagonal it is sized by is most
  of a diameter longer than anything on screen, and the camera ended up that
  much too far back. The software renderer had never had this problem: it
  projects the vertices themselves onto the screen axes and asks how far back it
  has to be to hold *those*, which is a millisecond once per design. The GPU
  view uses the same call now, with the same field of view, so a design looks
  the same size whether or not the machine has a usable GPU — and the view opens
  on a gearbox instead of on a small object in an empty room.

- **The empty COMPARE tab is a panel that explains itself.** The invitation to
  pin a reference was one sentence in the top-left corner with four hundred
  pixels of nothing under it, because one label was being asked to be both that
  invitation and the header over the filled table. They are two messages with
  two jobs; they are two labels now, and the empty one sits in the middle of the
  panel it is about to fill — which is what the trade study next door has always
  done, and it matters more here, because pinning a reference is the one feature
  of this window that nothing else in it mentions.

- **The remembered tab is stored by name now, not by position.** A tab added in
  the middle renumbers every one after it, so a stored `4` reopened the session
  on somebody else's tab — which is exactly what putting MOTOR between
  EFFICIENCY and DATASHEET would have done to everybody who had the app open on
  the datasheet. The name survives being reordered and says what it means in a
  preferences file somebody may one day have to read. Preferences written by an
  earlier version still hold an integer and it is still read, so an upgrade does
  not lose the tab it was left on. The log tab's unread badge is stripped before
  the name is stored, because a session saved under `LOG !!` would never be
  found again by a window whose log is quiet.

- **The motor curve was being sampled at the wrong speed** — caught by its own
  test before it shipped, and worth recording because the mistake is a
  reasonable one. `GearSpec.crank_rate` is crank angle per input revolution *in
  the ring-fixed frame the kinematics are parameterised in*, which is how every
  relative speed inside the drive is stated and is not a shaft speed at all. It
  is not 1 on a ring-output drive, so multiplying by it read the curve 4.5% off
  on a 21:1 and further out the lower the ratio. The motor turns the input shaft
  at the input speed, whichever member is grounded.

## 7.5.0

**Numbers** — none.

**Changed**

- **The application icon is the disc it cuts, not the company logo.** Every
  window, task bar button, Start menu entry, installer page, Dock tile and
  desktop launcher showed the Medinstech mark — which says who wrote the
  program and nothing whatever about what it does. Somebody scanning a task bar
  full of windows is looking for *this* application, and a vendor logo is the
  one thing on it that is also on everything else the vendor ships.

  It is a cycloidal disc now, and not a drawing of one: `tools/make_icon.py`
  renders the outline through
  [`disc_profile()`](https://github.com/medinstech/cycloidgen/blob/main/cycloidgen/core/profile.py),
  the same call the STEP export cuts the part with, with the pin radius taken
  as a fraction of `critical_radius()` so the lobes are a disc that could
  actually be manufactured rather than a flower. The icon cannot drift from the
  geometry: change the profile and it changes with it. `tests/test_icon.py`
  measures the committed images back against the equation — every point of the
  outline sits at exactly the pin radius from the pin-centre locus — and against
  what the tool draws today, so a hand-edited PNG fails.

  **Each size is drawn at that size.** A 256 px disc with eight lobes and six
  output holes *resampled* to 16 px is grey soup, so it is graded like an
  optical size instead: fewer lobes, deeper, and the holes come out, until at
  16 px it is six lobes and a bore. The `.ico` carries seven separately drawn
  images and Windows picks between them; the macOS `.icns` is built the same way
  at package time and now fills every slot up to 1024, where before it stopped
  at 256 and left Finder's largest view to blur one.

  The disc is cut out of a brand-blue tile, which is what lets one asset be
  legible on a light task bar and a dark one — the bare mark was the brand
  colour against whatever the desktop happened to be, and on a dark task bar
  that is 2.8:1.

  **The installer's two panels show it too**, drawn at the exact 40 px and 96 px
  those controls display rather than scaled down from the 256. The Medinstech
  wordmark stays on the welcome band, where it says who publishes this; the
  picture beside it is now the icon the shortcut will get, which is what
  somebody halfway through a setup wizard is being told about.

  **It is not a trademark.** `cycloidgen.ico` and `icon-*.png` carry no name or
  mark of Medinstech, they are Apache-2.0 with the rest of the source, and a
  fork may keep them — see [NOTICE](https://github.com/medinstech/cycloidgen/blob/main/NOTICE). The brand assets beside
  them are unchanged and still are not. The two generators are kept apart on
  purpose: `tools/make_assets.py` needs masters that are not in this repository
  and no longer writes the icon, so a brand refresh cannot quietly put the logo
  back.

## 7.4.0

**Numbers** — none.

**Added**

- **The app says what its output is not, where the output is made.** It said it
  before, in Help ▸ About, which is a dialog nobody opens - the least-read place
  in the application for the one paragraph in it that carries a consequence. It
  is in three more places now, and they are the three that matter:

  - **A strip under the export buttons**, in the window, always. Not
    dismissible: a disclaimer with a close button is a disclaimer that is shown
    once. Quiet on purpose - a hairline, the warning ink, one line - because it
    has to still be legible on the hundredth session and a banner that shouts is
    read as decoration by the second.
  - **A box before an export is written**, every time, with no "do not show
    again". Before rather than after, because after is a notification and this
    is a decision: the files are the thing that leaves the app, gets emailed to
    a shop and outlives the session that made them.
  - **`NOTICE.txt`, in the folder with the parts** — and in the PDF dossier, on
    the first page, above the verdict. That last position is deliberate: the
    verdict says **READY TO EXPORT** in capitals, which is a statement about the
    checks and reads, on its own, like a statement about the design.

  The notice is written into *every* bundle whichever groups were selected,
  because somebody exporting drawings only is exactly the person taking a DXF
  straight to a laser cutter. It is the first entry in the export manifest and
  the first row in the README's table of outputs, and it is not a group anyone
  can untick. Asking for no groups still writes nothing at all.

  All five copies read `cycloidgen.notice`. The risk with a disclaimer in five
  places is not that one disappears - somebody would notice - but that one
  *softens*, and the weakest copy is the one that will be quoted back. A test
  holds them to the same string.

  What it says is also wider than what About used to say. It named the numbers;
  it names the geometry too. Profiles, fits and clearances come out of the same
  idealised model as the analysis, no tolerance stack has been proven, and a
  STEP file that looks finished is the easiest thing here to mistake for a
  drawing that has been checked.

## 7.3.2

**Numbers** — none.

**Fixed**

- **The housing bore was drawn with two of every junction point**, and on VTK
  9.3 that was still a hole in the housing for every ring pin. 7.3.1 replaced
  the triangulation that could not be trusted across builds, and every face it
  cuts is checked - but the *mesh* was handing it a loop with edges of no length
  in it: the bore arc and the pocket arc meet at the intersection, and each
  computed that point for itself, agreeing to fourteen decimal places and not to
  the fifteenth. Forty-four of them on a 21:1.

  Geometrically they cost nothing, which is why they went unnoticed for so long.
  What they cost is edges. A segment with no length has no direction, so the
  wall standing on it is a quad with no area, and whether any of that survives
  being merged back into a closed surface is up to the mesh library: VTK 9.6
  keeps the two points apart, VTK 9.3 does not, and the one that does not leaves
  the wall and the cap disagreeing about where the boundary is. Two points that
  are the same point are one point now.

## 7.3.1

**Numbers** — none. Nothing computed moves in this release: it is the 3D view's
geometry and the interpreters the package will install on.

**Fixed**

- **Parts in the 3D view were not watertight on macOS or on VTK 9.3**, so a
  section cut through them read as a hollow shell rather than as solid
  material — the exact fault 7.2.0 said it had fixed, on the two platforms it
  had not been run on.

  The cause is worth stating plainly, because it is a lesson rather than a
  slip. Faces with holes in them were filled by `vtkContourTriangulator`, which
  gives up part way on some inputs and reports nothing about it. 7.2.0 added a
  check for that and a list of angles to turn the face by and try again — a
  list searched, on one machine, for the smallest set that cleared every face
  this app can draw. But *which* inputs defeat that filter is a property of the
  build, not of the geometry: the same list left the housing full of holes on
  VTK 9.3 (which is what Python 3.10 gets) and the end cap full of holes on
  macOS arm64 at the very version it was developed on. Neither reproduces here.

  So the face is cut here now, in `viz/tessellate.py`, by the textbook method
  for a polygon with holes: a sweep adds the diagonals that leave nothing but
  monotone pieces, the pieces are traced out of the loops and those diagonals
  together, and each is triangulated by the stack walk. Every step is
  comparisons and cross products in a fixed order, so two machines get the same
  triangles — and the suite checks all of it directly: the whole area, no
  directed edge twice, and a boundary exactly as long as the loops.

  It is also **faster**, and by more than the algorithm: the triangles come back
  as indices into the mesh's own vertices, so a cap shares its corners with the
  walls that meet it and there is nothing to append and merge afterwards, and
  the cutting is remembered per mesh rather than repeated for each of the two
  surfaces every part needs. A full rebuild of the 21:1 view went from 0.18 s to
  0.11 s, and rebuilding a mesh already seen from 0.18 s to 0.02 s.

  Two things came out of writing it. **Nothing in the suite had asked that a
  face's triangles all be wound the same way** — and the area cannot see it, so
  a face covered twice over and once backwards passes on the sum. And the
  housing's bore is drawn as a bore arc and a pocket arc per pin, meeting at a
  point each of them computes for itself: the same point to fourteen decimal
  places, which is an edge of no length to a sweep and cannot simply be dropped,
  because the wall below the cap keeps that edge and a boundary only one of them
  keeps is a hole.

**Changed**

- **Python 3.13 and 3.14.** `requires-python` said `<3.13` on a tree whose whole
  suite passes on 3.14, so `pip install` refused an interpreter the code was
  fine on. The bound is `<3.15` now. An upper bound is still stated rather than
  dropped — this depends on OCCT, VTK and Qt through binary wheels, and an
  interpreter no wheel exists for is a failed install however permissive the
  metadata is — and it moved to where there is a run behind it: 3.13 and 3.14 on
  Linux, and 3.14 on Windows as well, because those wheels are built per
  interpreter *and* per platform. 3.12 stays the version every bundle is frozen
  on.

## 7.3.0

**Numbers**

- **The disc turns against the crank, and the app had them subtracting.** Every
  speed measured between the disc and the crank was computed as
  `input_rpm * (1 - 1/i)`. It is `1 + 1/i`: the disc rotates the *opposite* way
  from the crank — that is what a fixed-ring cycloidal drive is — so the two
  rates add rather than cancel.

  Three places carried it. The **eccentric cam bearing**, which separates those
  two bodies and so turns at their difference; the **output pin** rubbing speed,
  which is the disc walking round the carrier at that same rate; and the
  **output stage's sweep period**, derived from how fast the eccentricity
  direction runs round as seen from the carrier.

  What gave it away was the pin-in-hole constraint. Relative to the carrier the
  disc translates on a circle of radius `E`, so at every crank angle each output
  pin has to sit *exactly* `E` from its hole centre — and it does, only with the
  carrier turning at `+phi/N`. Put that rate in and the eccentricity direction
  seen from the carrier advances at `(N+1)/N`, not `(N-1)/N`. The two stage
  periods then agree for the first time: the output period comes out as the ring
  period divided by the output pin count, which is what a pattern of `n` repeats
  in one turn of the ring pattern has to be. They were derived independently and
  only the correct rate makes them meet.

  Measured over the presets:

  | Quantity | 10:1 | 21:1 | 59:1 |
  |---|---|---|---|
  | Cam bearing speed, output PV, output sliding speed | **+22.2%** | +10.0% | +3.5% |
  | Cam bearing L10 life | −11% | −9.1% | −3.3% |
  | Input shaft support speed | +10.0% | +4.8% | +1.7% |
  | Running temperature | +4.2% | +1.7% | +0.3% |
  | Input torque for the rated output | +1.7% | +1.0% | +0.4% |
  | Efficiency | −1.2 pt | −0.7 pt | −0.3 pt |
  | Torsional stiffness | +2.6% | +4.5% | +5.6% |

  It is worst where it matters most — a low ratio is where that bearing is
  fastest — and everything on the ring side is unchanged, which is the expected
  result rather than a reassuring one: nothing about the ring contact was ever
  measured against the crank.

- **The two input shaft supports do not turn at the same speed**, and both were
  quoted at the input speed. One sits in an end plate and one in the carrier's
  boss, and those two bodies move differently. The schedule still carries one
  row — the seats are the same size, so one part number does for both — but it
  is sized on the faster of the two and prints both.

- **The output pin rollers were sized against the input speed**, which is
  neither the speed of anything at that contact nor the frequency of anything.
  They are now counted on the rate the hole walks round the pin, which is the
  cycle they are actually loaded on.

**Which member is the output**

- **Either of the two slow members can now be the output.** A cycloidal drive is
  a three-shaft machine: the crank is the input, and the ring and the carrier are
  interchangeable. Ground the ring and the carrier turns at `N:1`, reversed —
  which is what the app has always built. Ground the carrier and the *housing*
  turns, at `N+1:1`, in the same direction as the input. Same parts, one more
  tooth of reduction, and it is what most printed micro drives are.

  `output_member` selects it, and everything downstream follows rather than
  being told twice:

  - The reduction and the direction come off the two members' rotation rates, so
    `ratio` cannot disagree with the picture drawn from the same numbers.
  - Every rate in the app is now stated per unit *input* speed rather than per
    unit crank angle, because those part company here: with the carrier
    grounded the crank runs at `(N+1)/N` of the input. Relative speeds inside
    the drive are unchanged by the choice, which they must be — grounding a
    member adds one rigid rotation to all of it at once.
  - The motor moves to whichever member stands still. On a ring-output drive
    the carrier grows a base at the end of its boss, carrying the motor's
    pattern and register; the input end plate loses them and gains an output
    bolt circle for the driven machine instead, on the tie bolts' own circle
    and half a pitch round from them.
  - The 3D view, the 2D mechanism view and the exported animation turn the part
    that actually turns. One rigid frame rotation applied to the whole assembly,
    not a second set of motion laws to keep in step with the first.
  - The design search knows the difference between a reduction and a lobe count:
    a 30:1 off the ring is a twenty-nine lobe disc.

- **A ring-output drive is a frame, not a plate.** The grounded member cannot be
  a carrier hanging on six cantilevered pins with a barrel swinging off one
  bearing, and the reference builds are not: the pins land in an **end cap** at
  their far end and become the frame's own fasteners, so the carrier, the pins
  and the cap are one rigid cage that the housing turns inside. That is a new
  made part, `end_cap`, with its own STEP, STL and line on the bill of
  materials, and it changes two numbers that matter.

  **The output pins are beams.** A pin built into one plate carries `F*L`; the
  same pin caught at both ends carries `F*a*b/L`. On the 21:1 preset with two
  discs that is 45.3 MPa of fully reversed bending against 19.9 MPa. Their
  *stiffness* moves the other way and the app says so - the span is now the
  whole pin rather than half a stack, so the structure comes out slightly softer
  (7.26 to 6.57 Nm/arcmin) even though the case is stiffer.

  **The housing is carried at both ends.** One bearing locates a barrel and does
  not hold one against a moment, which is exactly what a wheel or a pulley on a
  turning barrel applies. There is a main output bearing on each of the frame's
  two bosses now, and both shaft supports move inside those bosses - the one
  that used to sit in the input end plate had to, because that plate turns.

  It costs length: the barrel has to cover the cap, so the 21:1 preset goes from
  40 mm to 63 mm and from 781 g to 1033 g.

- **The output pin's bending arm starts at the carrier's face**, which is a
  carrier drop below the first disc, and it was being measured from the disc.
  Small - one millimetre on a moment arm - but it is a moment arm, and it pushed
  a 16 mm disc stack on the 15:1 preset from just inside the output pin's
  fatigue limit to just outside it. `FATIGUE_LIFE` says so now. Carrier-output
  drives are affected, which is all of the ones that existed before this
  release.

- **The carrier's base was drawn one millimetre off the boss it stands on.**
  Introduced with the base itself, earlier in this release, and never shipped:
  the part is modelled in its own frame and an assembled height was used in it
  without the carrier drop, so the exported solid was in two pieces. The volume
  was right, which is why nothing caught it - a printer would have made both.

- **`OUTPUT_BOLT_CLASH`**, a new check. The output face's bolts share a circle
  with the tie bolts, because that is the one radius on that plate with barrel
  wall behind it to thread into. Equal counts interleave exactly; seven against
  six leaves 0.12 mm of metal; twelve against six lands one hole on another.
  Fifty-six checks.

**Ring pins the housing is printed with**

- **The ring pins can be formed with the housing** instead of fitted into it as
  separate dowels — `ring_pins_integral`, and the case every printed drive is.
  A pocket and the pin that fills it are one shape read from either side, so
  almost the whole of the difference is which arc of the same circle the bore
  follows, the outward half or the inward one, and `cut` against `union` in the
  exporter.

  The pins stop being a part when they are integral: no body in the 3D view, no
  STL, no line on the bill of materials — twelve lines to eleven, six bought
  parts to five — and no visibility row for something you can neither see
  separately nor take out. Their mass moves into the barrel and into the
  *housing's* material, which is the point of the option: on the 21:1 preset the
  drive goes from 781 g to 623 g, because 188 g of steel dowels become 30 g of
  the printed material that was going to be hollowed out to seat them.

- **They also stop being able to roll, and that is not free.** An integral pin
  cannot turn in a pocket it is part of, so the drive that pays for this is the
  one that had rolling ring pins. Same 21:1, rollers on:

  | Quantity | Rolling dowels | Formed with the housing |
  |---|---|---|
  | Efficiency | 83.7% | **70.4%** |
  | Ring pin loss | 1.00 W | **6.63 W** |
  | Running temperature | 29.5 °C | **40.5 °C** |
  | Ring pin sliding duty | rolls | **2.2x the PV limit** |

  `PV_LIMIT_RING` fires there rather than the trade being made quietly: PLA on
  steel at 0.22 MPa and 0.30 m/s is a disc that wears round long before it
  breaks. The ring pin roller leaves the bearing schedule with it, five rows to
  four, which is the other half of the same fact — there is no longer a part
  free to turn for a needle to sit under.

- **`ring_pins_roll` is what every consumer asks now**, and it is derived rather
  than enforced. The obvious way is a validator that clears
  `ring_pins_are_rollers` when the pins are integral, and it does not work:
  `model_copy` runs none, so a spec that arrived that way kept rolling pins on
  an integral ring and its efficiency came back unchanged — which is how this
  was caught. Deriving it also keeps the roller preference for when the pins
  stop being integral, which is why the box is greyed rather than cleared. The
  field is in `mesh_fingerprint` for the same class of reason: it changes the
  mesh, and a key that did not carry it would have served the old one.

**Added**

- **3MF export** — `assembly.3mf`, in the solids group. The STL entry in the
  manifest has always carried its own complaint: *STL has no assembly structure
  and no colour, so a multi-disc stack arrives as separate files*. Every one of
  those is a thing the app knows and the file cannot say. This is the same
  triangles with the sentence finished — one container, every part where it
  assembles, in the colour the 3D view paints it and named for the material the
  bill of materials orders it in. Identical discs are one object placed twice
  and different discs are two objects, which is the fact an STL folder can only
  state in its file names. Made parts only: a mesh of a bearing is a fit check
  at best and something someone tries to print at worst.

  Two things 3MF asks for that STL does not. **The shells have to be closed.**
  OCCT triangulates face by face and each face brings its own copy of the points
  along its edges, so the raw tessellation is the same heap of loose facets the
  3D view turned out to be, and the points are merged on a nanometre grid before
  anything is written — which halves the vertex count as a side effect. **And
  they have to be wound outwards**, which is checked as a signed volume against
  the solid: every part lands within 0.1% of the body it stands for, short
  wherever the surface is convex and — on the discs alone — a whisker long,
  because a chord across a concave flank falls *outside* the surface it is
  approximating.

  The tessellation is the STLs' own, at the same tolerance, so two files of one
  part cannot disagree about its geometry, and the placements are the STEP
  assembly's. The whole drive is lifted onto the build platform by one
  translation, because 3MF puts the plate at `z = 0` and this gearbox is
  modelled around its disc stack, with the carrier hanging below it. Exporting
  the same design twice gives the same bytes.

  The one check the suite cannot make is whether a slicer opens it, so that was
  made by hand: Bambu Studio's command line reads the file back as eight named
  objects, and each one's volume matches the solid it was tessellated from.

**Fixed**

- **Integral ring pins were promised as two files that nothing wrote.**
  `step/ring_pins.step` and `stl/ring_pins.stl` stayed in the manifest after the
  pins became part of the housing. The exporter had it right — there is no pin
  to make — so the Outputs tab listed two files, `--list-outputs` printed them,
  and a double-click opened nothing. The check that compares the declaration
  against what lands on disk is the one this project relies on for exactly this,
  and it had only ever been pointed at a drive with dowels.

- **The last two parts that were not watertight.** 7.2.0 closed twelve of the
  fourteen and named the two it had not, which were separate faults.

  `output_flange` had a wall buried in it. The carrier plate and the boss below
  it are separate prisms that meet at the plate's underside, and each kept the
  face it meets on, so four surfaces shared the bore ring. Only the annulus
  outside the boss is a face of the part; the rest is interior to the union and
  is no longer emitted. `prism` takes `cap_bottom`/`cap_top` for it, and there
  is a `ring` for the annulus that is left — both of which any other stacked
  pair will want.

  `disc_1` had a four-edge hole in its top face. `vtkContourTriangulator`
  stopped part way and said nothing, and any output with triangles in it was
  accepted, so the face came back 0.93% short. The area is checked against the
  loops it was given now, and a short face is retried with the plane turned,
  through angles that are not multiples of one another. The retry keeps the
  connectivity and throws the rotated coordinates away: rotating and unrotating
  would move every point by a rounding error, and these points have to merge
  *exactly* with the wall vertices that share them, which is what closes the
  surface in the first place.

  Every part of every preset is watertight, so the section plane caps all of
  them rather than twelve of fourteen, and three tests hold it — no holes and no
  non-manifold edges, every face triangulated to its whole area, and the
  assumption the retry stands on, that the triangulator hands back the points it
  was given in order. `test_every_part_is_a_closed_surface` passed throughout
  and was not wrong: it weighs the mesh's own facet loops, and those cancel
  whether or not anything managed to fill them.

- **A face with two bolt circles in it could come back triangulated wrong**, and
  the check that was meant to catch it could not see the failure. Faces are
  filled by `vtkContourTriangulator` and verified against the area they should
  have — but a plate carrying fourteen loops came back with its area exact to
  rounding and a triangle missing, because the triangulator had also emitted a
  different one twice and the two errors cancelled in a sum of absolute areas.
  The acceptance test now asks the topology directly: every edge either on a
  loop or shared by exactly two triangles. Four more retry angles came out of a
  search over every distinct multi-hole face the app can draw.

- **The motor's register left a wall inside the input end plate.** Where a
  spigot is wider than the bore under it the plate is built as two prisms, and
  both were capped on the face where they meet — so the plate had a full annular
  wall buried in it, every bolt hole crossing that wall was non-manifold, and
  the section plane could not cap the one part a motor bolts to. Only the step
  between the two bores is exposed, and only that is emitted now. It affected
  any frame piloting wider than the shaft support seat, which is a NEMA 23 or 34
  on a default drive.

- **The carrier's base is weighed.** A made part the mass model has not been
  told about is a gearbox that weighs less on paper than in your hand.

## 7.2.0

**Numbers**

- **Every sweep in the app was running over a window that is not a period, and
  the numbers taken over it have moved.** A lobe pitch, `360/N`, is the period
  of the disc's *shape*. It is not the period of anything a sweep samples: a
  sweep samples the pins, and there are `N+1` of those against `N` lobes, which
  is the entire mechanism. Pin `k` meets the profile at `t_k = phi/N -
  2*pi*k/(N+1)`, so the crank has to turn `360*N/(N+1)` before each contact
  lands where its neighbour was — 330 degrees on the default drive, not 32.7.

  What gave it away is that the curve did not close. Peak pin force reads
  49.859 N at `phi = 0` and 49.271 N one lobe pitch later, so the *Ring pin
  load* plot was a tenth of a cycle cut at an arbitrary phase, ending somewhere
  other than it began. Tiled, it steps at the seam. That is what it looked
  like, and it is what it was.

  The ring stage now sweeps `360*N/(N+1)` and the output stage sweeps its own
  `360*N/(n*(N-1))`, which is a different number and always was — the two have a
  common multiple that runs to thirty input revolutions on some tooth counts,
  which is exactly why neither can be swept on the other's window. Each stage
  gets its own loop. This is not an approximation: a maximum per stage is a
  maximum per stage, and the mean of a sum is the sum of the means.

  Measured against 7.1.1, over the presets and several tooth counts:

  | Quantity | Worst change |
  |---|---|
  | Ring peaks — pin force, contact pressure, torque capacity | under 0.01% |
  | Efficiency, running temperature | 0.6% |
  | Mean sliding speed | 0.7% |
  | Output pin force, output PV, disc web shear | **5.5%** |
  | Torsional stiffness | **12.6%** |
  | Load concentration | **8.6%** |
  | Transmission error | **7.4%** |

  The ring-side peaks barely move, and that is the expected result rather than a
  reassuring one: a maximum over the pins does not care which phase of the cycle
  you start at, only whether you covered it. What moves is everything averaged
  or ripple-measured, and the output stage, which was being swept over about
  *half* its period.

- **A check that should have been firing was silent.** On the 29:1 preset the
  output pin contact pressure exceeds the allowable, and `HERTZ_STRESS_OUTPUT`
  now says so. It did not before, because the peak output pin force was sampled
  over a lobe pitch — half the output stage's period — and came out 5.3% low,
  which was the wrong side of the limit. Anyone who took that preset as passing
  should re-run it.

- **`ring_period_deg` in the transmission-error result was the lobe pitch**, on
  a result type whose other field, `output_period_deg`, has been correct since
  it was written. It now reports the ring period: 330 degrees rather than 32.7
  on the default drive.

- **Sweeps are 144 steps rather than 72.** Sampling an exact period uniformly is
  unbiased at almost any count, so this is not what fixed the window — it is
  only about resolving the peak. Against a 20000-step reference, 72 steps miss
  peak pin force by 0.11% at 30 lobes and 144 by 0.004%.

- **The transmission error's ring sweep needed four times the steps**, and this
  one *is* about resolution. Twelve samples were enough across a lobe pitch and
  are less than one per pitch across the ring period, which read 11% low on the
  ring share; forty-eight is where it stops moving. What is left is bounded by
  the shared sweep rather than by that number, and is stated in the source: the
  ring share sits about 2% under a sweep four times finer, 0.7% on the total.
  Closing it means quadrupling the sweep every other study reads, and a
  transmission error 2% conservative on one of its two halves is not what limits
  this model.

**Fixed**

- **No part in the 3D view was watertight, so the section could not cap them.**
  A cut came out with some parts reading as solid material and others as empty
  shells — half the assembly sectioned, half of it hollow.

  The faces are emitted one at a time and each brings its own copy of every
  corner, so no face shared an edge with its neighbour: geometrically solid,
  topologically a heap of loose facets, every edge in it a boundary edge.
  `vtkClipClosedSurface` caps a *closed* surface and could not cap any of the
  fourteen.

  The comment on the filter that was supposed to prevent this said it merged
  the duplicate points. `vtkPolyDataNormals` does not merge points — with
  `SplittingOn` it *creates* them, which is what gives a cylinder's end cap a
  hard edge against its wall and is the right thing for shading. So the points
  are merged first and split afterwards, and the two surfaces have different
  jobs: the section and the edges take the closed one, the shading takes the
  split one. Twelve of the fourteen parts are now watertight.

  The same duplication had been doubling the edge overlay, which found every
  edge twice — once from each of the two faces that should have been sharing
  it. 12,614 line segments where 6,253 do.

  Two parts are still not clean, for reasons of their own, and are not fixed
  here: `output_flange` has 28 non-manifold edges where the plate and the boss
  both keep the face they meet on, and `disc_1` has a four-edge hole in its top
  face where `vtkContourTriangulator` gives up on one arrangement of output
  holes and the code checks only that it produced *some* triangles. `disc_2`,
  the same part on a different hole phase, is clean.

- **The screenshot tool drove the operator's real preferences.** It forced the
  light theme, cleared the section plane and unhid the 3D groups, then put them
  back at the end — and anything that raised in between skipped the putting
  back, which is how a window starts opening in the wrong theme with no sign of
  why. It runs against a throwaway settings file now, which is what
  `settings.ENV_VAR` exists for and is a better answer besides: these images are
  meant to show a fresh install, and now they are taken on one.

- **The output stage was swept over a lobe pitch in four more places** —
  `analyse_contacts`, `analyse_efficiency`, the thermal solve, and the disc-web
  and output-pin fatigue checks. `output_stage_period` had been in the codebase
  since the transmission-error work, with a docstring warning that sweeping a
  lobe pitch "reports about half the ripple that is really there", and nothing
  outside that one function called it. Both period functions live in
  `core.kinematics` now, next to the sweeps that need them.

- **Nothing in the suite asserted that a period was a period**, which is why
  this survived four releases and 788 tests. There are now tests that advance
  each stage by its own period and require the load pattern to return — one pin
  along for the ring stage, one the other way for the output stage, because the
  pattern steps onto its neighbour rather than staying put. And a test that
  holds the mistake down directly: a lobe pitch must *not* close either stage,
  compared as multisets so that renumbering the pins cannot rescue it.

**Changed**

- **The drawing says what speed it is showing, and the playback control says
  what "1x" means.** These were one confusion. The animation runs at 3 degrees
  of input per 33 ms frame, which is one input revolution every four seconds —
  15.2 rpm — while the tooltip claimed "input revolutions per second of wall
  clock", four times faster than the thing it described. The control is
  labelled PLAYBACK now and carries a live readout of the rate it actually
  turns at, so the multiplier is answerable without a tooltip; the rate is
  derived from the two timing constants rather than written down beside them.
  The drawing carries the *design's* speed, which is the other half of the
  question: a picture turning visibly at fifteen rpm, describing a drive rated
  at a thousand, needs to say which of the two it is.

- **The drawing and the datasheet name the arrangement.** Ring fixed, output
  taken from the disc's pin holes through the carrier — the planetary
  configuration, as against grounding the carrier and driving the ring, which
  is the star configuration and gives `Np` rather than `N`. The reduction line
  and the output-speed line both now say the output turns *against* the input,
  which the geometry has always done and nothing ever mentioned:
  `output_rpm` has no sign to carry it. The README says which member is
  grounded, why that fixes the ratio and the direction, and that the disc rolls
  on the inside of the pin circle.

- **The explanation panel answers two questions and sat beside one of them.**
  It explains the selected check *and* the parameter you clicked, and it lived
  in the bottom-right corner — so clicking a parameter in the left-hand panel
  put the reply as far from the question as the layout allowed. It is under the
  parameters now, and the checks list has the full width it had been competing
  for. That also retires the machinery that used to hide the panel on a narrow
  window and hold a floor under the detail column: nothing competes for that
  width any more.

- **The 3D tab's controls are grouped by what they do.** Explode was alone at
  the top beside the view buttons while section was squeezed onto the end of the
  visibility checkboxes at 150 px, on a row that had already run out of width
  and wrapped. They are the same kind of control — drag to open the assembly up
  — and they share the top row now, at the same size. The second row is
  visibility and nothing else. No extra height.

- **The wrapping toolbar lined its widgets up by their boxes, not their
  contents.** Everything was placed at the top of its row, so the bearings menu
  — a few pixels taller than the checkboxes beside it — painted its own glyph
  low and read as dropped punctuation. Rows are measured before they are filled
  now, and each widget is centred in its own.

- **The at-a-glance strip read as one run of words.** Eight captions, each wider
  than the number beneath it, right-aligned in pairs: every value hung off the
  end of its own caption with a gap to its left, which put it nearer the column
  next door. Each pair is centred now and the columns are separated by a
  hairline.

- **The status bar and the LOG tab look like one feature.** They are not
  duplicates — the bar is the last line and forgets it after five seconds, the
  tab is the record — but nothing said so, and two places showing similar text
  read as one of them being redundant. The bar carries a permanent link to the
  log, badge and all.

- **The drawing's title was cut in half by the top of its own panel.**
  `tight_layout` solves for the size it runs at and writes the answer down as
  fractions, and the figure is then resized under it by the window. The drawing
  panel is a letterbox — 973x271 on a 1560-wide window — where the fraction
  solved at build time leaves the title 16 px and it needs 22. It is re-solved
  when the canvas resizes now, rather than on every draw: a layout engine would
  put a `tight_layout` pass back into each animation frame, which is most of
  what `ProfileView` exists to have removed, and resizes are rare.

- **The About box leads with what the output is not.** The disclaimer was the
  last paragraph of the informative text, in the dim ink, under three links —
  the least-read position in the dialog for the one paragraph with a
  consequence in it. It is boxed, in the primary text, above the links. It also
  only ever disclaimed the *numbers*; the geometry needed saying too, because a
  STEP file that opens looking finished is the easiest thing here to mistake
  for a drawing somebody checked.

## 7.1.1

**Numbers**

- **Nothing computed moved.** Every quantity this reports is what 7.1.0
  reported, to the digit — the export from the trimmed bundle was compared file
  by file against one built with every dependency present, and all 29 came out
  the same size. This release is packaging, documentation and one dialog.

**Fixed**

- **"Design for requirements" could not be made to fit a short screen**, which
  put the buttons that end it out of reach. Four group boxes and the Search
  button came to 832 px of minimum height; a dialog inherits the minimum of what
  is inside it, so the window could not be sized below 885 px with its frame on
  — `resize(1080, 660)` asked for 660 and silently got 854. On anything shorter
  than that, the *Use this design* and *Cancel* box at the bottom of the results
  column sat off the bottom of the screen, and dragging the edge did nothing,
  because the window was already as small as it was allowed to be. A 1366x768
  laptop is short enough. So is a 1080p panel at 150% scaling, where the
  *logical* height is 720.

  The requirements form now scrolls, which is what breaks the inheritance: the
  dialog's minimum height goes from 854 px to 156 px and it is bounded by the
  results column, which stretches, rather than by the tallest thing in it.

  Search stays outside the scrolled part, pinned under it. Putting it in with
  the fields would have fixed the reaching problem by handing it to the button
  the dialog exists to have pressed — on a short screen it would have been below
  the fold, which is where the button box was to begin with.

  The failure was not that it looked cramped. Both buttons that close the dialog
  were unreachable, so the feature could be opened and not used.

- **The macOS instructions deleted the application.** They offered *System
  Settings ▸ Privacy & Security ▸ Open Anyway* first and `xattr -dr
  com.apple.quarantine` as an alternative, which reads as "open it, then deal
  with the warning". On macOS 15 and later that warning's default button is
  *Move to Trash*. A tester on macOS 26 followed the README exactly and watched
  the 1.3 GB install go to the Trash without the application ever running —
  Gatekeeper blocked the launch, then `syspolicyd` moved the bundle. *Open
  Anyway* is not in that dialog at all; it appears in System Settings only
  after a launch has already been blocked, and right-click ▸ *Open* stopped
  bypassing Gatekeeper in macOS 15.

  So the order is reversed everywhere it appears — the README, the generated
  release notes and RELEASING.md — and the clearing step now comes *before* the
  first launch, where it produces no dialog at all. A test holds the order,
  because it is prose in two files, one of them a heredoc inside a workflow,
  and reflowing it back the wrong way is a plausible tidy-up.

  Being unsigned was known and stated. What was not stated is that the easiest
  click destroys the install, which is the difference between a warning and a
  trap.

- **`--version` from the `.app` does not print while the bundle is
  quarantined.** The README explained why a windowed macOS build still answers
  on the command line and offered the command as proof. True for the bundle the
  release workflow builds, which never carries the flag, and false for the one
  a user downloads: Gatekeeper blocks the `exec` as well as the double-click,
  so the command hangs for about ten seconds and prints nothing. It answers
  normally once the quarantine flag is cleared, and the claim now says so.

  Both of these came from a tester on real hardware. Neither could have been
  caught here: the release workflow runs the binary out of the mounted image
  and it passes, because a file the workflow built itself was never quarantined
  in the first place.

**Changed**

- **The bundle is 790 MB, down from 1.2 GB.** 444 MB of it, 36%, was three
  packages that CadQuery declares as dependencies and this application never
  imports: `casadi`, an interior-point optimiser, at about 220 MB; `numba` with
  LLVM behind it at 142 MB; and `trame`, a browser viewer, at 20 MB. CadQuery
  declares what CadQuery can do, not what one caller uses.

  The note this replaces said the bundle was "essentially all OCCT" and
  suggested a build without the CAD kernel for anybody who cared. Both halves
  were wrong. OCCT is 152 MB — 12% — and the optimiser that arrives beside it is
  larger than it is, so the prescribed remedy would have given up STEP and STL
  export, which is half the point of the tool, to save a third of what came off
  by shipping the same features with less beside them. The size was a plausible
  guess nobody had weighed; measuring it took one pass and reversed the answer.

  Nothing is dropped on the strength of not finding an `import`. Each package is
  made unimportable and the whole suite is run against that — 778 tests — and the
  export is compared file by file against one from an environment with every
  dependency present: 29 files, identical sizes, kernel path included.

  `casadi` needed more than an exclusion, because it is imported whether it is
  used or not: `cadquery/__init__.py` reaches `occ_impl.solver`, which imports it
  at the top. So `packaging/rthook_casadi.py` stands in for it, and what makes
  the substitution safe is *where* the module uses it — all thirty-seven
  references are inside function bodies, and the only names that run at import
  are two annotations. Reading a name off the stand-in works, which is all an
  annotation needs; calling one raises with a sentence saying the solver was left
  out. This application constrains no assemblies — every part is placed by an
  explicit transform off the kinematics — so the limit is real but unreachable
  from the application, and `pip install cycloidgen` brings the genuine article.

  Not done, and measured rather than left vague: about 123 MB of VTK is never
  loaded either. It is left in because it cannot be checked the way the rest
  was. Excluding a VTK module is a missing DLL in a frozen build, not a failed
  import in a virtual environment, so the test suite would go green on a bundle
  that had lost the 3D view.

## 7.1.0

**Added**

- **A macOS disk image.** Drag it to Applications, which is what a Mac user
  expects installing to be. Apple silicon only: every x86-64 macOS runner GitHub
  offers is now a paid larger runner and the free Intel image was retired, so an
  Intel Mac gets the wheel — the same application by a different route.

  It is signed ad-hoc, which is the minimum Apple silicon will execute at all,
  and not notarized — so Gatekeeper stops the first launch and the user has to
  allow it by hand. That is worse than SmartScreen, it is said plainly in the
  release notes and the README rather than discovered, and it is a certificate
  away rather than a rewrite: [RELEASING.md](https://github.com/medinstech/cycloidgen/blob/main/RELEASING.md)
  has the three commands the job would gain.

  The workflow mounts the finished image and runs the binary out of the mounted
  volume, which is the last state the thing is in before a user sees it.

- **A Linux AppImage.** One file, `chmod +x`, double-click — the Linux answer to
  the Windows installer, arrived at from the opposite direction: NSIS unpacks
  the bundle into Program Files and registers it, an AppImage installs nothing
  and *is* the bundle. Built on Ubuntu 22.04 rather than the latest runner,
  because a PyInstaller bundle links against the host's glibc and glibc is
  forward compatible only: built on 24.04 it would need 2.39 and rule out Debian
  12, Ubuntu 22.04 LTS and every enterprise distribution in service.

  It carries one executable where the Windows bundle carries two. `console` is a
  Windows subsystem flag and Linux has no equivalent, so a second binary there
  would have been a second copy of the same one under a name implying a
  difference that does not exist.

  The release workflow unpacks the AppImage and runs it — `--version` and a real
  export — before anything is published. A bundle that builds and cannot start
  is the whole failure mode here, and it is invisible until somebody downloads
  it.

- **`pip install cycloidgen`.** The installer is Windows-only and always will be
  — NSIS is a Windows tool — but the application never was: it is tested on
  Linux and macOS on every push, and `cadquery-ocp` ships wheels for every
  platform and architecture it runs on. So the honest answer for a Linux or Mac
  user was "clone it and install from source", which is an answer for a
  developer and not for anybody else. Now a release publishes a wheel to PyPI as
  well, and `cycloidgen` opens the window on all three. It is also the only
  route on an Intel Mac, and the only way to `import cycloidgen`. Publishing
  goes through PyPI's Trusted Publishing, so there is no API token in the
  repository to leak or rotate.

  `README.md` is the project page there as well as the front of the repository,
  and PyPI serves it from its own host — so every path in it is absolute now,
  and a test keeps it that way. Relative ones would have landed on PyPI as a
  column of broken-image icons.

**Fixed**

- **Three more parts were quoted off the disc stack.** 7.0.0 found the tie bolt
  doing this and fixed it alone. It was never one bug: when the barrel was
  lengthened in 5.0.0 to reach the end plates, *four* things that measure
  themselves against it were never told, and reading the code for the other
  three is what this release is.

  - **The ring pins were seven millimetres short of the pockets they sit in.**
    A pocket is broached down the bore in one pass, so it runs the barrel's
    whole length — and a pin cut to the disc stack had seven millimetres of
    empty groove beneath it and nothing at the bottom but the end plate.
    Nothing held it up. It slides down, and what it slides out of is the mesh:
    a third of its engagement gone and an open pocket left at the top for a
    lobe to drop into. They run the barrel now and the two plates trap them.
  - **The output pins stopped one carrier drop short of the last disc.** They
    leave the carrier face a drop below the first disc, so a stack-high pin
    arrives a drop short of the top of the stack: on a two-disc drive, the last
    disc driven over seven of its eight millimetres — while the hole bearing
    stress this app reports is computed over all eight.
  - **The bill of materials described a barrel seven millimetres shorter than
    the one the exporter writes.** Exactly the tie bolt's mistake, one line up
    the same page.

- **A pin under a roller was ordered and weighed at the wrong diameter.** The
  roller's OD *is* the working pin — the profile was cut to it — so the pin
  beneath is the sleeve's bore. Everything that draws a pin already asked; the
  bill of materials and the mass model did not. A 15:1 with rollers on was
  telling you to buy 14 mm dowels for the 8 mm bore of the sleeves it lists
  three lines further down.

- **The end plates weighed nothing on the bill of materials.** Their mass was
  real and computed, and it was being added to the barrel's line — so the
  barrel read heavy, and a third of the gearbox went out as a blank cell next
  to the word "make". Barrel and plates are separate numbers now, on the
  datasheet as well.

- **The screenshot tool photographed whatever the operator had left on.** The
  section plane and the crank angle are both restored from settings, and
  neither was being reset: one run came out as half a gearbox. It also cropped
  the bare-gearbox figures six pixels too tall, because `GetWindowRect`
  includes Windows' invisible resize border and dividing that by Qt's frame
  width produced a "scale" of 1.009 on a display at 100%.

**Numbers**

- **Assembled mass is up 7 to 9%** — the pins are longer, and now they are as
  long as the holes they live in. On the presets: 615.5 g → 661.1 g at 15:1,
  724.9 g → 781.1 g at 21:1, 853.5 g → 926.8 g at 33:1. Every gram of it was
  always in the exported STEP file; it was the sum that was light.
- **On a design with rollers fitted the mass falls instead**, because the
  dowels shrink to the sleeve bores they actually are.
- **The bill of materials states different lengths and diameters.** Ring pin 17
  → 24 mm and output pin 17 → 18 mm on every preset, the barrel 17 → 24 mm, and
  a rollered pin at its shank rather than its nominal size. If you ordered
  dowels from a 7.0.0 bill of materials, they are short.
- **`housing_mass_g` in the JSON report is now the barrel alone**, with the
  plates beside it as `plates_mass_g`. It used to be both.

Unchanged: every dimension in the geometry, contact stress, torque capacity,
efficiency, lost motion, transmission error, fatigue, lubrication and bearing
selection. Inertia is unchanged too — the pins do not turn with anything.

## 7.0.0

**Added**

- **A documented Python API, and a grid to put designs through.** The analysis
  was always importable and never documented as something to import.
  [`docs/api.md`](docs/api.md) is what it looks like from the outside — the
  spec, the analysis, the exporters, the sweep, the search — and every example
  in it is executed by the test suite, in order, in one namespace. A document
  nobody runs is worse than none: it is confidently wrong the first time a name
  moves, and the person it misleads is the one who trusted it enough to build
  on. Two names in it were already wrong when it was written.

  Alongside it, `--vary` puts a design through every combination of whatever
  you name and returns a table: twice for one field is two values of one axis,
  once each for two fields is a grid, and numeric fields also take
  `lo:hi:steps`. Fifteen metrics per design, declared once so the CSV, the
  terminal table and the documentation cannot describe different tables — the
  first five of them the five the calibration plan measures on real hardware.
  Designs that fail a check stay in with their error codes, because where the
  feasible region *ends* is most of what a study is for.

  Together these are the half of **calibration against real hardware** that was
  never waiting on a lathe: fitting the model's free constants is a script over
  a grid, and until both existed it was blocked on something other than
  hardware.

- **Every file the app writes says which build wrote it** — a saved design, the
  JSON report, the PDF and every DXF. None of the numbers here are
  measurements; they are a model's answers, and the model improves between
  releases. So a design saved by an earlier build says so when you open it,
  and says what may have moved and what has not, instead of quietly reporting a
  different mass than the one you wrote down. Which digits are allowed to move
  a number is now stated in [RELEASING.md](RELEASING.md) and enforced in code:
  patch is *defined* as the one that cannot.

**Fixed**

- **The tie bolts had nothing to pass through.** The bill of materials ordered
  six of them, both end plates were drilled for them and the DXF drew the
  circle — and the barrel they clamp had no holes in it. The app billed you for
  six bolts, drilled two plates, and exported a gearbox they could not pass
  through. The holes are cut now, in the STEP solid and in the viewer, the
  bolts themselves are drawn, and the check that was missing is there:
  **`HOUSING_BOLT_CLASH`**, which asks whether the bolt fits in the wall it
  runs up the middle of.

- **The bolt length was seven millimetres short.** The bill of materials quoted
  it off the disc stack, and when the barrel was lengthened in 5.0.0 to reach
  the plates it bolts to, that number did not follow. It is one derived
  property now, read by the bill of materials and by both renderers, and a test
  measures the span in the geometry and compares it against what is printed.

- **The mass model did not know about the holes.** It already subtracted the
  ring-pin pockets; the tie-bolt holes went in later and it was still weighing
  a barrel that did not have them. It is checked against the volume the three
  housing solids actually enclose now, rather than against arithmetic that
  happens to agree.

- **Dark mode drew white edges.** Turning edges on in the 3D view painted a
  bright halo round every ring pin, and the model read as a wireframe lit from
  inside rather than as shaded solids. What was wrong underneath is that the
  two renderers disagreed: the software painter has always drawn an edge as the
  part's own colour darkened, which needs no theme at all, and the hardware
  path was drawing the window's ink. One shared constant now.

**Changed**

- **The at-a-glance strip says what its numbers are.** It was eight bare
  values — `15:1 120 mm OD 40 mm LONG 620 g 0.73 Nm 71% 98' 52 C` — which is a
  summary only the person who wrote it can read. Each carries its own name and
  a tooltip, and two of the eight are coloured against a limit the analysis
  itself computes: whether the drive carries the torque it is rated for, and
  whether it stays under the temperature its materials allow. Colouring the
  rest would have meant inventing thresholds.

- **A finding can be read without being clicked.** The detail column was cut
  off on every row, so the checks list was a set of codes you opened one at a
  time. It wraps. On a window too narrow for both, the explanation panel yields
  to the list rather than the list's detail being squeezed to nothing. The
  Outputs tab had the same defect and got the same treatment.

- **Empty panels say what they are waiting for.** The trade study opened on a
  blank white rectangle under a chart toolbar, which reads as a chart that
  failed to draw; the comparison tab showed an empty table with its headings
  on, above two buttons that acted on a reference that did not exist. Also the
  steps box held 21 and displayed `2`.

- **The project is reachable from inside the application** — the repository,
  the issue tracker, the release notes and the company site, in the Help menu
  and the About box, with the wordmark as a link.

**Numbers**

- **Assembled mass is down about 0.8%**, because the barrel and both plates
  lost the tie-bolt holes they always had on the drawing. On the presets:
  620.3 g → 615.5 g at 15:1, 729.6 g → 724.9 g at 21:1, 858.3 g → 853.5 g at
  33:1.
- **The tie bolt in the bill of materials is 40 mm rather than 33** on every
  preset. If you ordered bolts from a 6.x bill of materials, they are short.
- **`HOUSING_BOLT_CLASH` is an error**, so a design whose bolt does not fit its
  housing wall now blocks an export that used to run. No preset trips it; a
  wall thinner than the bolt through it does, and that is the case where the
  exported barrel was wrong before.

Unchanged: contact stress, torque capacity, efficiency, lost motion,
transmission error, fatigue, lubrication, bearing selection, and every
dimension of the disc, ring and carrier. A saved design reopens as the drive it
was, and now says which build it was saved by.

## 6.0.0

**Added**

- **Lubrication is calculated now, not declared.** One number — a friction
  coefficient you typed in — was carrying efficiency, PV and running
  temperature between them, and it knew nothing about how fast the surfaces
  were moving, how hard they were pressed together, what was between them, or
  how hot it had got.

  There is a Dowson-Hamrock film at each of the three sliding contacts now,
  measured against the roughness it has to clear, and the coefficient the
  resulting regime earns — boundary and full-film blended by how much load the
  asperities still carry. Lubricants are a table like the materials and the
  bearing catalogue, and surface roughness defaults from the process, because
  unlike a position tolerance every process has one whether it is stated or
  not. **Dry is the default and its numbers are untouched**, which is the same
  rule the position tolerance follows: a design that says nothing about
  lubrication gets the answer it always got.

  Two things fell out of it that are worth more than the coefficient. The first
  is *why* fixed pins wear: a fixed pin does not move, so the entrainment
  velocity is half the sliding velocity — the contact is dragged rather than
  rolled — and at cycloidal mesh loads the film lands at tens of nanometres
  against hundreds of nanometres of roughness. That holds for ground steel and
  is not close for anything printed. It is the quantitative form of a choice
  the app used to offer as two different constants.

  The second is that the surface is the lever and the grade is not. Sweeping
  roughness on a machined steel drive gives a cliff rather than a slope: 86% at
  a lapped 0.02 µm, flat at 79% from about 3 µm up, because past there the
  coefficient has saturated at the lubricant's boundary value. So where the
  film is out of reach — which is most builds here — the lubricant worth buying
  is the one with the additives, and moly against dry is a factor of two on
  every sliding loss in the drive.

  Temperature made it a fixed point rather than a formula: friction heats the
  oil, the hot oil stops holding the surfaces apart, and that is more friction.
  Damped substitution, converging because the feedback is bounded by the
  boundary coefficient, and the test that matters re-runs the losses at the
  answer and checks the answer comes back. Two limits are stated rather than
  buried — the line-contact formula is being applied to two conforming contacts
  it was not derived for, so their film is capped at the radial clearance, a
  real bound that says the shaft is floating in the middle of its hole rather
  than that the formula was right; and the full-film traction coefficient stays
  a constant, which it earns, because oil in a loaded contact shears at a
  limiting stress and measured traction barely moves with speed or load.

  New finding: `LUBRICATION_REGIME`, reported on every design.

- **The parameters explain themselves, instead of only complaining.** Forty-eight
  fields, and the only prose attached to any of them appeared after something
  had already gone wrong. A panel that speaks up only when it is unhappy
  teaches you the machine by punishing you.

  `core/guide.py` declares, for every parameter, what it physically is, how to
  choose it in terms of the rest of the design, and what choosing it that way
  costs — three parts kept apart for the same reason the check explanations
  keep theirs apart. Almost none of these are preferences; they are trades, and
  the trade is the half that is hard to find out.

  It shows up in two places for two different moments. Hovering gives what it
  is and how to pick it, where the eye already is. Clicking into it fills the
  explanation panel with the trade as well, and with which checks the field
  moves and how each of them currently stands — that last part cannot be
  declared, because it belongs to the design on screen, so a parameter about to
  break something says so before it is moved rather than after. The
  field-to-check list is `CODE_FIELDS` read backwards, derived rather than
  restated so it cannot drift from the direction that is maintained.

- **Dimensioned drawings for the two end plates.** 5.0.0 made them parts and
  gave them a solid, which is the one thing you cannot drill from — and they
  are the two parts here whose whole job is a hole pattern. Both are in the
  cutting folder now, tie bolts and motor pattern on layers of their own so a
  shop drilling one can switch the other off, every hole with a centre mark
  rather than only a circle, and the numbers a driller asks for on the title
  line, including the motor pattern stated as the *square* it is.

  What decides the features is read from the same spec properties the solid
  extrudes rather than restated: the register is drawn only where the bore has
  not already swallowed it, and nothing motor-shaped reaches the output plate.
  The first turned out not to be hypothetical — on the default 10 mm shaft a
  NEMA 17's 22 mm spigot lands on the 22 mm hub bore exactly, so that plate has
  no register left to cut.

**Changed**

- **macOS gets the hardware 3D path by default.** `view3d_qtgl.py` had never
  been run on the platform it was written for — every measurement behind it was
  a Windows one — and it has now been opened on a Mac and draws. `available()`
  no longer refuses darwin outright; `CYCLOIDGEN_VTK_QTGL` forces either way
  and `CYCLOIDGEN_VTK=0` still drops any machine back to the software painter.

**Fixed**

- **The housing did not reach the plates it bolts to.** There was a slot cut
  round the gearbox: the ring housing ran the height of the disc stack and
  stopped, but the output carrier hangs below the discs — a drop, then its own
  thickness — and the output end plate bolts on underneath that. Between the
  barrel and the plate it is fastened to there was nothing at all, seven
  millimetres of daylight with the carrier standing in it. The barrel was sized
  to the disc stack when the disc stack was all there was to enclose, and 5.0.0
  gave it two plates to reach without lengthening it.

  `envelope_length` was already counting the carrier's share, so the app has
  been reporting 40 mm for a design whose geometry only filled 33 — which is
  what two separate sums of the same stack-up do to each other. It is stated as
  the barrel plus its two plates now, so the length and the parts cannot
  disagree again, and the three places that each held their own copy of the
  barrel's extent — the mesh, the STEP solid and the mass model — read it off
  the spec instead.

- **The guts showed through a closed gearbox.** The software viewport painted
  the ring pins, the discs and the shaft over the top of the end plate that
  encloses them. The note in `scene.py` argued that no two parts share space,
  so nothing could be occluded out of order — but not sharing space is not the
  same as not being *inside* something, and a centroid is one number for a face
  that spans the whole depth of the scene.

  Measured against a real per-pixel z-buffer rather than by eye, which turned
  up that the premise was half right: within one part the centroid order is
  exact, and a single part on its own disagrees with the z-buffer on 0.00% of
  pixels. Every bit of the error was *between* parts. So the sort is two-level
  now — faces within a part by centroid, parts against each other by their
  nearest point, because back-face culling leaves a surface lying entirely in
  front of whatever that part encloses. Assembled, that takes the
  wrong-surface rate from about 9% of pixels to under 2%, and the sealed-part
  leak from 7915 pixels to 29, at 2.11 ms a frame against 2.08 before. Exploded
  it is a wash — parts pulled apart are not nested and there is no correct part
  order to find — and the docstring says so rather than implying it was fixed.

- **Orbiting the 3D view did nothing while the animation ran**, on macOS, with
  the accumulated rotation appearing the moment the animation stopped.
  `vtkGenericRenderWindowInteractor.Render` does not draw: it raises
  `RenderEvent` and waits for the toolkit that owns the context to schedule a
  frame, which is the entire reason it is the interactor for an embedded case.
  Nothing was listening, so every frame an interaction asked for was dropped.
  Windows hid it because something else always repaints; macOS runs a mouse
  drag in the window server's own event-tracking loop where ordinary timers do
  not fire, so with the animation running there is genuinely nothing else.

- **The 3D visibility row squeezed its own labels.** A `QHBoxLayout` short of
  width takes it from its children anyway, and a squeezed `QCheckBox` elides
  its own text — Housing became Housin and Carrier became Carrie on any window
  narrower than the one it was built on, which reads as a rendering fault
  rather than as a layout out of room. It wraps instead.

**Numbers**

- **Efficiency and running temperature now follow the lubricant.** On the 21:1
  preset: dry 71.3% and 39.6 °C, unchanged from 5.0.0; lithium grease 73.0%,
  ISO VG 220 gear oil 78.6%, moly EP grease 82.9% and 30.1 °C. Nothing moves
  for a design that does not name a lubricant, and `friction_coefficient` keeps
  its old meaning in that case — with one in, it becomes the boundary value the
  film is compared against rather than the answer.
- **Assembled mass is up about 4%**, the housing being longer by the carrier
  drop plus the flange thickness: 17 mm of barrel becoming 24, about 28 g, and
  on the 21:1 preset 702 g → 730 g.
- **The bundle gains two drawings**, `dxf/input_end_plate.dxf` and
  `dxf/output_end_plate.dxf`.

Unchanged: envelope length and cooling area, both of which were already
measured off the full length; contact stress, torque capacity, lost motion,
transmission error, fatigue, bearing selection, and every dimension of the
disc, ring and carrier. A saved design reopens as the drive it was, dry.

## 5.0.0

**Added**

- **The two seats the model did not have.** The bearing schedule had five load
  paths and the geometry had somewhere to put three. The main output bearing was
  sized and then not drawn — there was no hub for its bore and no plate for its
  outside — and the shaft supports were rings on a bare shaft with nothing
  around them at all.

  Two end plates close the housing, one on each face, and the output carrier
  grew the boss the drive actually turns on: the output bearing rides its
  outside, a shaft support sits in its bore, the other sits in the input plate.
  All three seats are dimensions of the design rather than consequences of a
  selection — the geometry is the input and the bearing fits into it, the same
  way round as the cam — so nothing is circular and a bearing that stands off
  its journal is reported rather than accommodated.

  The plates are their own visibility group, and the 3D tab opens with them off:
  with them on the assembled view is a closed cylinder with a shaft out of one
  end, which is exactly what the gearbox looks like and exactly no use as the
  first thing a design tool shows you.

- **A face to bolt a motor to, and one to grip at the other end.** The app
  mentioned the motor in four places and had no motor interface: no bolt
  pattern, no register, no motor shaft. Turning the shaft supports off is
  documented, in those words, as *"the drive hangs on the motor face"* — and
  there was no face.

  Motor frames are a table now, like the materials and the bearing catalogue,
  and the input end plate is cut to whichever you pick: the register first,
  because four clearance holes on their own leave a motor free to sit anywhere
  inside them, then the bolts. **NEMA patterns are a square, not a bolt
  circle** — four holes on a circle of the same span land where the motor has
  nothing, which draws perfectly and does not fit — so the pattern kind is data
  rather than something to remember. `None` is the default: presuming a motor
  would put a finding on every design out of the box, because no frame here
  matches a 10 mm shaft.

  Three checks come with it. `MOTOR_SHAFT_MISMATCH` — a NEMA 17 turns 5 mm and
  every preset is drawn around 10 mm; with the motor driving the cam directly
  those are the same shaft, so the pairing is wrong and the app used to take it
  without comment. A warning rather than an error, because every exported file
  is still right; what is wrong is which motor you bought.
  `MOTOR_FACE_CLASH` — a pattern falling into the bore or off the rim, which
  *is* an error, because then the plate is wrong; a small drive being narrower
  across than its motor is as reachable as the obvious way round.
  `MOTOR_RADIAL_LOAD` — with no shaft bearings, the crank reaction measured
  against the frame's own radial rating instead of "check its rating".

  The output end of this topology is a boss on the axis rather than a bolt
  face — what goes on there is a coupling or a clamp hub — so what it needed was
  somewhere to grip, and it was coming out flush with the end plate. It stands
  proud now. The tie bolts that hold the plates on are drawn as well.

**Fixed**

- **The input shaft was too short to reach through its own bearing.** Twelve
  millimetres of overhang each end predates the carrier boss existing, so the
  outboard shaft support fell off the end of the shaft it is meant to sit on —
  by a hair on the default and by more on any deeper carrier. The overhang is
  derived from what it has to reach through now, which also retires the last
  hand-copied instance of that constant.

**Numbers**

Every one of these moves because the gearbox gained parts it always needed and
was never counting.

- **Mass is up by about a third.** On the 21:1 preset, 447 g → 702 g: the two
  end plates and the carrier boss are 36% of the assembled drive and were
  simply not being weighed.
- **The envelope is 23.0 mm → 40.0 mm** on the same design. The plates are part
  of the gearbox — they close it and carry three of its bearings — and leaving
  them out understated the length of every drive this app has ever sized.
- **Running temperature falls**, because cooling area follows the envelope:
  357 cm² → 427 cm² on the preset. The drive is not cooler than it was; the
  earlier figure was pessimistic about a surface that exists.
- **Input shaft torsional stiffness is down about 23%**, a longer shaft being a
  less stiff one. It is the stiffest link in the chain by two orders of
  magnitude, so the drive's own stiffness barely moves.
- **Shaft support and main output bearings may change.** Their seats are real
  now instead of guesses at the pin circle, and tighter for it, so a
  hard-worked design can be told that nothing fits a 22 mm boss bore eight deep
  — which is true, and says which two dimensions to open.

Unchanged: contact stress, torque capacity, efficiency, lost motion,
transmission error, fatigue, and the disc, ring and carrier geometry. A saved
design reopens as the drive it was, with a motor face of `None`.

## 4.0.0

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

- **The bearings are in the 3D view, the STEP assembly and the BOM.** The
  schedule said where each one goes in words, and words leave the question open:
  "on the input shaft either side of the disc stack" is a description, not a
  place. They are now geometry — a ring on the cam inside each disc bore, sleeves
  over the ring and output pins, the two shaft supports where the end plates
  belong — drawn from the same selection the schedule reports, so the picture and
  the parts list cannot come apart.

  Two rules decide what appears. The diameters are the picked part's, not the
  seat's, so what you see is the bearing you will hold. And a bearing is drawn
  only where both of its working diameters are known — which is why a ring pin
  sleeve is left out when no drawn cup is small enough: the schedule's answer
  there is a sleeve on a smaller pin, and *how much* smaller is not something
  this app has decided. A guessed wall would be inventing the part.

  The main output bearing is the one absence, and it is deliberate: it seats
  between the output flange and the housing, and the model has neither a flange
  hub nor a housing end plate for it to sit in. Its note says so.

  They switch off one at a time as well, from the **…** beside the group in the
  3D tab. A group toggle is enough for the housing, where there is one of it;
  the bearings sit in four different places, and looking at the cam bearing down
  its bore means putting the others away rather than putting all of them away.

- **Bearings you can leave out of the design, not just out of the picture.**
  Three of the five load paths can be built without a bearing of their own, and
  plenty of drives are: a printed one usually runs its disc bore straight on the
  cam, and a drive bolted to a motor face lets that motor's bearings hold the
  shaft. **Bearings fitted** in the parameter panel, `--no-cam-bearing`,
  `--no-shaft-bearings` and `--no-output-bearing` on the command line.

  Switching one off takes the part out of the schedule, the BOM, the STEP and
  the 3D view — and changes the physics with it, which is the difference between
  a design decision and a display option. A drive with no cam bearing has a
  plain journal at the fastest contact in the machine, so the cam grows to fill
  the bore instead of standing 8 mm off it to leave a bearing wall, and the
  sliding coefficient replaces the rolling one: the 21:1 steel preset goes from
  71% efficient to 40%. Drag on a bearing the drive does not carry is not
  counted at all, because it belongs to the machine on the other end.

  The load path stays on the schedule either way. A row that vanishes reads as a
  path that does not exist, which is the thing this schedule was rewritten to
  stop doing; each one now says what is carrying it instead, with the number —
  a motor's own bearings do not make the crank reaction go away.

  New check `PV_LIMIT_CAM`, because a plain cam is the textbook wear failure of
  this whole machine and nothing had ever asked about that contact: the largest
  single force in the drive, rubbing at nearly the input speed, usually against
  the disc material. A PLA disc on a steel cam at the 15:1 preset comes out 18×
  over its wear limit — a drive that passes every stress check in the app and
  wears its own bore oval in an afternoon. `BEARINGS_OMITTED` states, as a note,
  which paths have been handed to something the app cannot see.

- **Bearing sizes you can set, instead of only the smallest one that fits.**
  Each of the five seats takes a designation instead of `auto`, which is what
  you want whenever something outside the geometry is deciding: a bearing
  already in the drawer, one your supplier stocks, or simply a bigger one than
  the smallest that will do.

  A named part is checked against its seat and **never quietly swapped** for one
  that fits — "this is the bearing I have" is exactly the case where a
  substitution is useless — so `BEARING_DOES_NOT_FIT` names the dimension that
  is wrong: the bore against what it sits on, the outside against what it sits
  in, the width against the room. A part that does not go in stays on the
  schedule and is not drawn, because drawing it would mean shrinking it to the
  seat, and a picture of a part at a size it is not is worse than no picture.

  The same check caught something that was always reachable on automatic: the
  study takes any bore at or above the shaft or cam, so a hand-set cam diameter
  between two catalogue sizes could come back with a bearing that does not touch
  it, and said nothing. It now says what to turn the journal to.

**Fixed**

- **Bearing selection and the short-life warning disagreed by a factor of five.**
  The study took anything lasting 1000 hours; the report warned below 5000. So
  the app could pick a bearing and complain about it in the same breath. There
  is one number now, `bearing_min_life_hours`, it is the design's rather than the
  code's, and it defaults to the 5000 the warning already used — which is the
  stricter of the two, so a design at the margin may now be handed a larger
  bearing than it was before.

- **The design search was returning drives whose output pins bend on the first
  turn.** Nothing in the app had ever looked at output pin bending, and the pins
  are cantilevers — `export.solid` extrudes them from one carrier plate and
  nothing catches their free ends. Asked the question for the first time, every
  design the search returned for its own steel requirements came back between
  0.11 and 0.99 on fatigue, and the thin ones were past yield in bending as
  well. It varies pin diameter and count already, so it can find its way out; it
  had simply never been told this was a constraint. It is now, and there is a
  test that the designs it hands back survive being turned.

- **The BOM was under-ordering bearings.** The quantity was read out of the role
  *string* — `disc_count if "per disc" in role else 1` — which worked only while
  the roles happened to be worded that way. Once they were not, the list said one
  eccentric bearing for a two-disc stack and one input shaft support for a shaft
  that takes two. It now uses the count the schedule carries.

- **An output pin roller could never be selected, whatever the design.** The seat
  asked for a bore of a full pin diameter *and* an outside diameter of the hole
  less twice the eccentricity — which is the same diameter again. Nothing can
  match a ring with no wall, so the answer was always "no roller fits" and the
  switch that turns them on changed the efficiency and the PV duty without ever
  producing a part. The roller's outside *is* the working pin, as it already was
  for the ring pins, and the pin shrinks to its bore.

- **A roller was counted once per pin however long the pin was.** A sleeve is the
  surface the disc runs on, so it has to cover it; an 8 mm needle on a 25 mm
  stack leaves the pin loose in its pocket for the other 17 mm. The schedule now
  says how many it takes end to end, and the drawing lays them that way.

**Changed**

- **The material table gains an ultimate tensile strength and a fatigue
  strength.** The ultimate is needed for Goodman and for the surface factor. The
  fatigue strength is stated per material rather than derived from it, because
  the usual 0.5×Sut stops holding above about 1400 MPa — 100Cr6 would otherwise
  be credited with 1000 MPa of endurance limit it does not have.

**Numbers**

Numbers moved, and one of them is on a list people order from.

- **Bearing quantities in `bom.csv` were wrong and are now right.** A two-disc
  stack was listed as needing one eccentric cam bearing and one input shaft
  support; it needs two of each. Anyone who ordered off a 3.1.x bill of
  materials is short. Roller quantities move too, and further: a sleeve is now
  counted as many times as it takes to cover the surface it is the surface of.
- **A bearing has to reach 5000 hours to be selected, not 1000.** On every
  preset nothing changes — those seats run 10⁵ to 10⁷ hours — but a heavily
  loaded design near the old line will be handed a larger bearing than it was.
- **Output pin rollers can be selected at all.** The seat asked for a ring with
  no wall, so `output_pins_are_rollers` never produced a part. Designs with that
  switch on and pins large enough now gain rollers in the schedule, the BOM and
  the geometry, and their pins shrink to the roller bore — in the STEP, the 3D
  view and the carrier drilling template alike.
- **The design search returns different drives**, because it now knows output
  pins bend.

Unchanged for any design that keeps the new switches at their defaults: contact
stress, torque capacity, efficiency, stiffness, backlash, transmission error,
temperature and mass. The new bearing switches default to fitted and the new
seat fields to `auto`, so a saved design reopens as the drive it was.

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
