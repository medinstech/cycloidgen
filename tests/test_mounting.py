"""How the gearbox bolts to the world, at both ends.

The app talked about the motor in four places and had no motor interface at
all: no bolt pattern, no register, no shaft.  ``shaft_bearings_fitted = False``
said in so many words that the drive "hangs on the motor face", and there was
no face.  Nothing on this gearbox could be attached to anything.
"""
from __future__ import annotations

import numpy as np
import pytest

from cycloidgen.analysis import analyse
from cycloidgen.core.spec import MOTOR_FRAMES, NO_MOTOR, preset


def _spec(frame: str = "NEMA 17", shaft: float | None = None):
    spec = preset(21)
    spec.motor_frame = frame
    if shaft is not None:
        spec.input_shaft_diameter = shaft
    return spec


def _codes(spec):
    return {f.code for f in analyse(spec).report.findings}


# ------------------------------------------------------------------ the frames


def test_a_nema_pattern_is_a_square_and_not_a_bolt_circle():
    """Four holes on a circle of the same size land where the motor has nothing.

    It is the kind of wrong that draws perfectly and does not fit, so the
    distinction is in the data rather than in whoever writes the geometry.
    """
    frame = MOTOR_FRAMES["NEMA 17"]
    assert frame.square
    assert frame.bolt_circle_diameter == pytest.approx(31.0 * np.sqrt(2.0))
    assert frame.bolt_circle_diameter > frame.bolt_span


def test_every_frame_puts_its_bolts_outside_its_own_register():
    """A hole inside the spigot is a hole in the motor, not in the plate."""
    for name, frame in MOTOR_FRAMES.items():
        if name == NO_MOTOR:
            continue
        reach = frame.bolt_circle_diameter / 2.0 - frame.bolt_diameter / 2.0
        assert reach > frame.pilot_diameter / 2.0, name


def test_no_motor_is_the_default_because_none_of_them_fits_the_presets():
    """Presuming a motor that cannot drive the preset it ships with would put a
    finding on every design out of the box."""
    assert preset(21).motor_frame == NO_MOTOR
    assert not [c for c in _codes(preset(21)) if c.startswith("MOTOR")]


# ------------------------------------------------------------------- the plate


def test_the_motor_face_is_cut_into_the_input_plate_only():
    """The output end plate carries the bearing the drive turns on; a motor
    pattern in it would be four holes into the machine's own mounting face."""
    from cycloidgen.export import solid

    plain = solid.parts(preset(21))
    with_motor = solid.parts(_spec())
    assert (with_motor["input_end_plate"].val().Volume()
            < plain["input_end_plate"].val().Volume())
    assert (with_motor["output_end_plate"].val().Volume()
            == pytest.approx(plain["output_end_plate"].val().Volume()))


def test_the_bolt_holes_are_drawn_where_the_motor_has_bolts():
    """The picture and the part have to agree about a pattern you drill."""
    from cycloidgen.viz.mesh import build_mesh

    spec = _spec()
    mesh = build_mesh(spec)
    plate = next(p for p in mesh.parts if p.name == "input_end_plate")
    xy = mesh.vertices[plate.vertices][:, :2]

    half = spec.motor.bolt_span / 2.0
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            near = np.hypot(xy[:, 0] - sx * half, xy[:, 1] - sy * half)
            assert near.min() == pytest.approx(spec.motor.bolt_diameter / 2.0,
                                               rel=0.05), (sx, sy)


def test_the_tie_bolts_miss_the_pins_they_are_holding_the_plate_over():
    spec = preset(21)
    assert spec.housing_bolt_count > 0
    inner = spec.pin_circle_radius + spec.pin_radius
    assert inner < spec.housing_bolt_radius - spec.housing_bolt_diameter / 2.0
    assert (spec.housing_bolt_radius + spec.housing_bolt_diameter / 2.0
            < spec.housing_outer_radius)


# ------------------------------------------------------------------- the checks


def test_a_motor_whose_shaft_is_not_the_drive_s_shaft_is_caught():
    """A NEMA 17 turns 5 mm.  A drive drawn around a 10 mm shaft has a cam bored
    10 mm and nothing to put it on."""
    assert "MOTOR_SHAFT_MISMATCH" in _codes(_spec())
    assert "MOTOR_SHAFT_MISMATCH" not in _codes(_spec(shaft=5.0))

    # ...and a coupling is a real answer, so saying so clears it.
    spec = _spec()
    spec.motor_drives_the_shaft = False
    assert "MOTOR_SHAFT_MISMATCH" not in _codes(spec)


def test_the_mismatch_does_not_block_the_export():
    """Every file is still right - the cam is bored to the shaft the design
    states.  What is wrong is which motor you bought."""
    findings = {f.code: f for f in analyse(_spec()).report.findings}
    assert findings["MOTOR_SHAFT_MISMATCH"].severity.value == "warning"


def test_a_pattern_that_runs_off_the_plate_is_an_error():
    """A small drive can be narrower across than the motor bolted to it, and
    then the holes are in fresh air - which does make the exported plate wrong."""
    spec = preset(10)
    spec.motor_frame = "NEMA 34"
    spec.motor_drives_the_shaft = False
    spec.pin_circle_radius = 20.0
    spec.housing_wall = 2.0
    assert "MOTOR_FACE_CLASH" in _codes(spec)
    assert not analyse(spec).report.ok


def test_hanging_the_drive_on_the_motor_is_measured_against_the_motor():
    """'Check its rating' was the best this could say before there was a frame
    to check against."""
    spec = _spec(shaft=5.0)
    spec.shaft_bearings_fitted = False
    spec.output_torque_Nm = 15.0
    assert "MOTOR_RADIAL_LOAD" in _codes(spec)

    spec.shaft_bearings_fitted = True
    assert "MOTOR_RADIAL_LOAD" not in _codes(spec)


def test_the_bolts_reach_the_bill_of_materials():
    from cycloidgen.export.bom import bom_items

    parts = {i.part: i for i in bom_items(analyse(_spec()))}
    assert parts["Tie bolt"].quantity == preset(21).housing_bolt_count
    assert parts["Motor bolt"].quantity == 4
    assert "NEMA 17" in parts["Motor bolt"].note

    assert "Motor bolt" not in {i.part for i in bom_items(analyse(preset(21)))}


# -------------------------------------------------------------- the output end


def test_the_output_boss_stands_out_far_enough_to_grip():
    """It came out flush with the end plate, which is nothing for a coupling to
    hold - the output of this topology is a shaft, not a bolt face."""
    spec = preset(21)
    assert spec.output_boss_protrusion > 0

    from cycloidgen.viz.mesh import build_mesh
    mesh = build_mesh(spec)
    carrier = next(p for p in mesh.parts if p.name == "output_flange")
    plate = next(p for p in mesh.parts if p.name == "output_end_plate")
    assert (mesh.vertices[carrier.vertices][:, 2].min()
            < mesh.vertices[plate.vertices][:, 2].min() - 1e-9)
