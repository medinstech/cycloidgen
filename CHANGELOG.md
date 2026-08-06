# Changelog

Notable changes, newest first. Versions follow the `major.minor.patch` of the
package in `pyproject.toml`; anything that changes a computed number gets called
out, because that is the only kind of change that can quietly invalidate a
design somebody already built.

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
