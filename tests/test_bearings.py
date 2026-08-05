"""The bearing schedule: every rolling interface, counted and placed.

The failures worth guarding here are not arithmetic. They are a schedule that
quietly leaves out a load path - which reads as "that one needs no bearing" -
and a bearing chosen against the wrong diameter, which reads as a part that
fits.
"""
from __future__ import annotations

import pytest

from cycloidgen.analysis import analyse
from cycloidgen.analysis.bearings import CATALOGUE, select_bearings
from cycloidgen.analysis.mechanics import analyse_contacts
from cycloidgen.core.spec import Process, preset


def _spec(rollers: bool = True):
    spec = preset(21)
    spec.process = Process.CNC
    spec.apply_process_defaults()
    spec.disc_material = "Steel 4140 (hardened)"
    spec.pin_material = "Bearing steel 100Cr6"
    spec.ring_pins_are_rollers = rollers
    spec.output_pins_are_rollers = rollers
    return spec


def _schedule(spec):
    contact = analyse_contacts(spec)
    return select_bearings(spec, contact.eccentric_bearing_load_N,
                           contact.max_output_force_N,
                           ring_pin_load_N=contact.max_pin_force_N)


def test_every_load_path_appears():
    """Nothing supported the input shaft and no ring pin roller was ever sized,
    while a switch for them existed and changed the efficiency."""
    roles = {c.role for c in _schedule(_spec())}
    assert roles == {"Eccentric cam bearing", "Output pin roller",
                     "Ring pin roller", "Input shaft support",
                     "Main output bearing"}


def test_the_ring_pin_roller_only_appears_when_it_is_selected():
    roles = {c.role for c in _schedule(_spec(rollers=False))}
    assert "Ring pin roller" not in roles
    assert "Input shaft support" in roles


def test_the_eccentric_bearing_fits_the_cam_and_not_the_shaft():
    """Sized against the shaft it was possible to be handed a bearing whose bore
    was smaller than the cam it had to sit on - a part that cannot be assembled,
    reported as a fit."""
    spec = _spec()
    assert spec.cam_diameter > spec.input_shaft_diameter
    choice = next(c for c in _schedule(spec) if c.role == "Eccentric cam bearing")
    assert choice.bearing is not None
    assert choice.bearing.bore >= spec.cam_diameter
    assert choice.bearing.outer <= spec.center_bore_diameter
    assert choice.bearing.width <= spec.disc_thickness


def test_counts_are_numbers_rather_than_prose():
    """'(one per disc)' in the role string cannot be counted, priced or put on
    a drawing."""
    spec = _spec()
    schedule = {c.role: c for c in _schedule(spec)}
    assert schedule["Eccentric cam bearing"].count == spec.disc_count
    assert schedule["Input shaft support"].count == 2
    assert schedule["Main output bearing"].count == 1
    assert schedule["Ring pin roller"].count == spec.pin_count
    assert (schedule["Output pin roller"].count
            == spec.output_pin_count * spec.disc_count)


def test_every_role_says_what_it_carries_and_where_it_sits():
    for choice in _schedule(_spec()):
        assert choice.carries, choice.role
        if choice.count:
            assert choice.seat, choice.role


def test_a_roller_turns_slower_than_the_input():
    """It only turns as fast as the disc flank drags its surface. Taking the
    input speed would overstate the duty several times over."""
    schedule = {c.role: c for c in _schedule(_spec())}
    ring = schedule["Ring pin roller"]
    assert 0.0 < ring.speed_rpm < _spec().input_rpm


def test_the_catalogue_has_something_narrow_enough_for_a_thin_disc():
    """The eccentric bearing can be no wider than the disc, and every needle in
    the cam bore range used to be 20 mm wide - so nothing fitted an 8 mm disc,
    which read as an impossible design rather than a short list."""
    narrow = [b for b in CATALOGUE
              if b.kind == "needle" and 15 <= b.bore <= 25 and b.width <= 8]
    assert narrow


def test_the_schedule_reaches_the_analysis():
    assert len(analyse(_spec()).bearings) == 5


def test_a_bearing_that_fits_lasts_the_life_it_reports():
    """L10 goes as (C/P)^p, so halving the load has to move the life by 2^p and
    not by anything else."""
    spec = _spec()
    contact = analyse_contacts(spec)
    full = select_bearings(spec, contact.eccentric_bearing_load_N,
                           contact.max_output_force_N,
                           ring_pin_load_N=contact.max_pin_force_N)
    half = select_bearings(spec, contact.eccentric_bearing_load_N / 2.0,
                           contact.max_output_force_N,
                           ring_pin_load_N=contact.max_pin_force_N)
    a = next(c for c in full if c.role == "Eccentric cam bearing")
    b = next(c for c in half if c.role == "Eccentric cam bearing")
    assert a.bearing is not None and b.bearing is a.bearing
    assert b.life_hours == pytest.approx(
        a.life_hours * 2.0 ** a.bearing.life_exponent, rel=1e-9)
