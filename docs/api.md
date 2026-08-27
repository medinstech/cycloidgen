# The Python API

The analysis has always been importable. This is the part that says so, and
says which of it you can build on.

Everything here works without a display: `import cycloidgen.analysis` pulls in
neither Qt nor matplotlib, so it runs in a notebook, in CI, and on a machine
that has never had a window server. There is a test that holds that — an
accidental import of the UI from the core would otherwise make a headless run
fail on a machine nobody was testing on.

```bash
pip install -e .            # from a checkout
python -m cycloidgen --version
```

---

## The five things it does

### 1. A design

`GearSpec` is the whole design: about fifty parameters, validated on assignment,
with every dimension in **millimetres**. Start from a preset and change what you
mean to change.

```python
from cycloidgen.core.spec import GearSpec, preset

spec = preset(21)                     # a 21:1 drive that passes its checks
spec.output_torque_Nm = 12.0
spec.disc_count = 2
spec.lubricant = "Grease NLGI 2 (EP, moly)"
```

One of those fifty decides more than the rest: **which member the output comes
off**. The crank is always the input, but the ring and the carrier are
interchangeable — ground either one and the other is the output — and that sets
the reduction, the direction, and which end of the drive the motor bolts to.

```python
from cycloidgen.core.spec import OutputMember

spec.output_member = OutputMember.RING     # bolt the carrier down instead
spec.ratio                                 # 22, not 21 - the pin count
spec.output_reverses                       # False: it turns with the input
spec.crank_relative_rate                   # 1.0: the cam bearing runs at input speed
```

Every rate on `GearSpec` is stated **per unit input speed**, which is not the
same as per unit crank angle once the carrier can be the grounded member — the
crank then runs at `(N+1)/N` of the input. `crank_rate` is the conversion, and
`frame_spin` is the single rigid rotation that turns the model's frame into the
one the grounded member sits still in.

Assignment is validated, so a value outside a field's bounds raises there and
then rather than three functions later:

```python
import pydantic

try:
    spec.pin_radius = -1
except pydantic.ValidationError as exc:
    print("refused:", exc.errors()[0]["msg"])
```

Ask a field what it is for rather than guessing. `core/guide.py` carries, for
every parameter, what it physically is, how to choose it, and what choosing it
that way costs — the same text the app puts on a tooltip:

```python
from cycloidgen.core.guide import guide

g = guide("hole_clearance")
print(g.what)        # the physical thing
print(g.choosing)    # how to pick it, in terms of the rest of the design
print(g.trade)       # what picking it that way costs
```

### 2. Analyse it

```python
from cycloidgen.analysis import analyse

a = analyse(spec)

print(a.report.ok)                                  # did every check pass
print(a.torque_capacity_with_clearance_Nm)          # Nm
print(a.efficiency.efficiency)                      # 0..1
print(a.stiffness.lost_motion_arcmin)               # arcmin
print(a.stiffness.stiffness_Nm_per_arcmin)
print(a.transmission_error.peak_to_peak_arcmin)
print(a.thermal.temperature_C)
print(a.mass.total_mass_g)
print(a.fatigue.safety_factor)
```

`DesignAnalysis` groups the results the way the physics does — `contact`,
`efficiency`, `stiffness`, `transmission_error`, `thermal`, `mass`, `fatigue`,
`bearings` — and each is a frozen dataclass you can read fields off. The two
headline numbers that span groups are properties on the analysis itself, because
they are derated by a result from another one:
`torque_capacity_with_clearance_Nm` and `pin_safety_factor_with_clearance`.

### 2a. Will your motor turn it

Everything above is what the drive can *take*. `a.motor` is what it will be
*given*, and on most designs here that is the smaller number. Set a curve on the
spec and the analysis puts the duty point on it:

```python
from cycloidgen.core.spec import MotorKind

spec.motor_kind = MotorKind.STEPPER
spec.motor_holding_torque_Nm = 0.45      # a NEMA 17, off the datasheet
spec.motor_rated_current_A = 1.5
spec.motor_resistance_ohm = 1.5
spec.motor_inductance_mH = 3.0
spec.motor_supply_V = 24.0

m = analyse(spec).motor
print(m.margin)                          # times over, on the continuous line
print(m.ceiling_rpm)                     # no torque at all past here
print(m.fraction_of_stall)               # how much of holding torque is left
print(m.output_torque_ceiling_Nm)        # what motor and ratio buy at the output
print(m.output_speed_ceiling_rpm)        # and how fast, at the required torque
```

`motor_kind` defaults to `MotorKind.NONE`, and then `m.modelled` is false and
nothing about the motor is checked — which is what every design did before there
was a curve. `MotorKind.DC` covers brushed and brushless motors and wants
`motor_kv_rpm_per_V` instead of the holding torque, inductance and step count.

The curve itself is a plain object you can sample without running an analysis at
all, which is what a sizing script wants:

```python
curve = spec.motor_curve
for rpm in (0, 300, 600, 900):
    print(rpm, round(curve.torque_at(rpm), 3))
print(round(curve.speed_for_torque(0.2), 1))   # fastest that still makes 0.2 Nm
```

The models are stated in `cycloidgen.core.motor`, along with what they ignore.
Both are upper bounds: read a margin near 1 as no margin.

### 2b. What it does over time

`spec.output_torque_Nm` and `spec.input_rpm` are the *rated* point — one thing
the drive does. A machine lifts, holds, returns and waits, and the quantities
that describe it do not aggregate the same way, so a cycle is stated separately:

```python
from cycloidgen.core.duty import DutyCycle, DutyPoint

spec.output_torque_Nm = 55.0                 # rate it at the cycle's peak
spec.duty_cycle = DutyCycle(points=(
    DutyPoint(name="lift",   output_torque_Nm=40.0, output_rpm=12.0, seconds=4.0),
    DutyPoint(name="hold",   output_torque_Nm=55.0, output_rpm=0.0,  seconds=6.0),
    DutyPoint(name="return", output_torque_Nm=8.0,  output_rpm=30.0, seconds=2.0),
))

d = analyse(spec).duty
print(d.worst_stress.point.name)         # stress comes from the worst point
print(d.mean_loss_W, d.temperature_C)    # heat from the mean - a housing integrates
print(d.equivalent_torque_Nm)            # ISO 281 cubic mean, for bearing life
print(d.peak_motor_torque_Nm, d.rms_motor_torque_Nm)   # make one, survive the other
print(d.shortest.designation, d.shortest.life_hours)   # hours of cycle
```

Four aggregations, because no single point is conservative for all four. The
durations are in whatever unit suits — only their ratios are read — and
`output_rpm=0` is a **hold**: the load is there, nothing turns, so there is no
loss, no PV and no bearing life consumed.

The bearings are the drive's *own*, chosen at the rated point, with only their
lives recomputed at the cycle's equivalent duty. Re-selecting for the cycle
would answer a different question and could never report a bearing that falls
short, because it would simply have picked a bigger one.

An empty `DutyCycle()` is the default and changes nothing: a design that has not
been given a cycle analyses exactly as it did before there was one.

Findings are data, not printed text:

```python
for f in a.report.findings:
    print(f.severity.name, f.code, f.message, f.value, f.limit)

blocked = [f.code for f in a.report.errors]
```

And every code can explain itself — what it tests, what goes wrong physically,
what to change and in which direction:

```python
from cycloidgen.core.explain import explain

e = explain("PV_LIMIT_CAM")
print(e.title, "|", e.tests)
print(e.why)         # what goes wrong physically when it fails
print(e.fix)         # what to change, and which way
```

### 3. Write the files

```python
from cycloidgen.export import write_bundle

files = write_bundle(spec, "out/", groups={"drawings", "data"})
```

`groups` are the manifest's groups — `drawings`, `solids`, `data`, `animation`.
Omit it for everything. What each group contains is declared in
`cycloidgen/export/manifest.py` and nowhere else, so this cannot disagree with
the Outputs tab or with `--list-outputs`.

`solids` is the group that needs the OCCT kernel, and it is where the meshes
are: `stl/`, one file per part, and `assembly.3mf`, which is the same triangles
placed as they assemble with each part's colour and material on it. Both are
tessellated at `spec.stl_linear_tolerance`.

One file is not in any group and is written whichever groups are asked for:
`NOTICE.txt`, which says what the numbers and the geometry in the folder are
not. The text is `cycloidgen.notice`, and it is the same text the window shows
under its export buttons and in the box it asks with before writing. Asking for
no groups still writes nothing at all - a notice with no parts beside it is not
a bundle.

### 4. Sweep one parameter

Four metrics against one parameter, which is what a chart can carry:

```python
from cycloidgen.design.sweep import SWEEPABLE, suggested_range, sweep_parameter
import numpy as np

lo, hi, n = suggested_range(spec, "output_pin_count")
result = sweep_parameter(spec, "output_pin_count", np.linspace(lo, hi, n))

x, y = result.series("efficiency")          # blocked designs left out
print(len(result.blocked), "designs failed a check")
```

### 5. Study a grid

Many parameters, every combination, every metric — the shape you want when the
question is not "what does this do to efficiency" but "which of these forty
should I build", or when you are fitting the model against measurements.

```python
from cycloidgen.design.batch import (METRICS, Axis, run_batch, write_csv)

axes = [
    Axis("lubricant", ("None (dry)", "Grease NLGI 2 (EP, moly)")),
    Axis("surface_roughness_um", (0.2, 0.8, 3.2, 12.0)),
]
points = run_batch(spec, axes)

for p in points:
    print(p.values, p.ok, p.metrics["efficiency"], p.errors)

write_csv(points, axes, "study.csv")
```

Designs that fail a check are kept in the result with their error codes rather
than dropped: where the feasible region *ends* is most of what a study is for.
A metric that cannot be computed for a design comes back as `nan` rather than
taking the row with it.

The columns are declared once, in `METRICS`, with a unit and a note each:

```python
for m in METRICS:
    print(f"{m.name:28} {m.unit:10} {m.note}")
```

The same thing from the command line, with no Python at all:

```bash
python -m cycloidgen --ratio 21 \
    --vary lubricant="None (dry)" \
    --vary lubricant="Grease NLGI 2 (EP, moly)" \
    --vary surface_roughness_um=0.2:12:8 \
    --csv study.csv
```

`--vary` repeats: twice for the same field is two values of one axis, once each
for two fields is a grid. Numeric fields also take `lo:hi:steps`. Without
`--csv` it prints a summary table instead.

### And going the other way

Requirements in, geometry out:

```python
from cycloidgen.design import Objective, Requirements, optimise

req = Requirements(ratio=29, output_torque_Nm=20.0, input_rpm=1500,
                   max_outer_diameter_mm=120, process="CNC machined",
                   objective=Objective.EFFICIENCY)
result = optimise(req, effort="quick")   # or "normal", or "thorough"

if result.ok:
    best = result.best[0].spec           # result.best is the shortlist, ranked
else:
    print(result.tally.explain())        # why every candidate was rejected
```

The reduction can be an answer rather than a question. Give the search a motor
and what the *output* has to do, and it works out which reductions that motor
can drive the load with, searches a spread of them, and ranks the results
together:

```python
from cycloidgen.design import RATIO_FROM_MOTOR, ratio_band

job = Requirements(
    ratio=RATIO_FROM_MOTOR,              # let the motor decide
    output_torque_Nm=6.0, output_rpm=10.0,
    motor_kind=MotorKind.STEPPER, motor_holding_torque_Nm=0.45,
    motor_rated_current_A=1.5, motor_inductance_mH=3.0, motor_supply_V=24.0,
    max_outer_diameter_mm=130, max_length_mm=60,
)

band = ratio_band(job)                   # closed form, no geometry needed
print(band.span)                         # (37, 97) - the reductions that work
print(band.explain())

found = optimise(job, effort="quick")
print(found.ratios_searched)             # a sample of the band, declared
for c in found.best[:3]:
    print(c.spec.ratio, round(c.analysis.motor.margin, 2))
```

`ratio_band` is worth having on its own: it costs one curve evaluation per
reduction and needs no geometry, so it answers "what reduction do I even want"
before there is anything to analyse. Below the band the motor is short of
torque and gearing down further helps; above it the motor is short of speed and
gearing down further is what caused it. A design the motor cannot turn is
dropped from the search whether or not the search picked the reduction.

---

## Saving and loading

A design file is the spec and the version that wrote it. Use the same reader the
app uses, because it accepts all three shapes this app has ever written — a
design file, a full report, and a bare spec dump from before either had a
wrapper:

```python
import json
from pathlib import Path
from cycloidgen.core.designfile import (design_dict, numbers_may_have_moved,
                                        spec_from_dict, written_by)

Path("design.json").write_text(json.dumps(design_dict(spec), indent=2))

data = json.loads(Path("design.json").read_text())
spec = spec_from_dict(data)
if numbers_may_have_moved(written_by(data)):
    ...     # this build's answers may differ from the ones that were recorded
```

---

## Units, and what a number means

| Quantity | Unit |
|---|---|
| Every length, everywhere inside | mm |
| Force | N |
| Torque | Nm |
| Angle — lost motion, transmission error, windup | arcmin |
| Stiffness | Nm/arcmin |
| Mass | g |
| Temperature | °C |
| Speed | rpm in, m/s at a contact |
| Pressure and stress | MPa |
| Efficiency, safety factors, film ratio | dimensionless |

The inch preference in the desktop app is a *display* preference and does not
reach any of this: the spec is millimetres and so is everything handed over.

Every number here is a first-principles estimate with a stated model and stated
limits, not a measurement. That is the point of the calibration work in the
roadmap, and until it lands, treat the absolute values as engineering estimates
and the *differences* between two designs as the more reliable output.

---

## What is stable

- **`cycloidgen.core.spec`**, **`cycloidgen.analysis`**, **`cycloidgen.export`**,
  **`cycloidgen.design`** and **`cycloidgen.core.designfile`** are the API. Names
  in their `__all__` are what this document describes.
- Anything under **`cycloidgen.ui`** is not: it is the desktop app's internals
  and it changes without notice.
- A leading underscore means the same thing it means everywhere.

Version numbers say what a change did to you, and
[RELEASING.md](../RELEASING.md) is the rule. The short form: **patch** cannot
move a computed number, **minor** may move one because the model improved and
the changelog says by how much, and **major** means something has to be *done* —
a saved design that no longer loads, a parameter that changed meaning, a check
that starts failing designs that used to pass.

That is why every file this app writes carries the version that wrote it,
including the CSV a study produces. The stamp is a `#` comment on the first
line rather than a column repeated down four hundred rows, so read it back
with comments skipped — `pandas.read_csv(path, comment="#")`, or with nothing
installed at all:

```python
import csv

with open("study.csv", encoding="utf-8") as handle:
    stamp = next(handle)                       # "# cycloidgen 6.0.0 - ..."
    rows = list(csv.DictReader(handle))

print(stamp.strip())
print(len(rows), "designs;", sum(r["ok"] == "yes" for r in rows), "built")
```

---

## A worked example: what does surface finish actually buy

The kind of question the grid is for. One design, one lubricant, roughness from
lapped to as-printed:

```python
from cycloidgen.core.spec import preset
from cycloidgen.design.batch import Axis, run_batch

spec = preset(21)
spec.lubricant = "Grease NLGI 2 (EP, moly)"

axis = Axis("surface_roughness_um", (0.02, 0.1, 0.4, 1.6, 6.4, 25.6))
for p in run_batch(spec, [axis]):
    print(f"Rq {p.values['surface_roughness_um']:6.2f} um  "
          f"eff {p.metrics['efficiency']:.3f}  "
          f"lambda {p.metrics['film_lambda_min']:.2f}  "
          f"{p.metrics['temperature_C']:.0f} C")
```

The answer is a cliff rather than a slope, and where it flattens is the point
past which the lubricant's boundary additives are doing all the work and a
better grade buys nothing. That is a manufacturing decision the model can
actually settle.
