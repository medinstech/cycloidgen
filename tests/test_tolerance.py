"""Pin position tolerance: the ring that gets built, not the one that is drawn.

The load model has always placed the pins exactly.  These tests hold the two
ends of relaxing that: with no tolerance entered the answer must not move at
all, and with one entered it must move the way a real ring does.
"""
from __future__ import annotations

import numpy as np
import pytest

from cycloidgen.analysis.stiffness import (
    analyse_stiffness,
    analyse_transmission_error,
)
from cycloidgen.analysis.tolerance import (
    carrier_position_errors,
    ring_position_errors,
    tolerance_samples,
)
from cycloidgen.core.spec import PROCESS_POSITION_TOLERANCE, Process, preset

# ------------------------------------------------------------------- the draw


def test_a_perfect_ring_is_one_ring_and_not_a_distribution():
    """A zero tolerance is a different question, not a small one, and it has to
    collapse the ensemble - otherwise every design in the app pays for a study
    of a spread that is identically zero."""
    spec = preset(15)
    assert spec.position_tolerance == 0.0
    assert tolerance_samples(spec, 24) == 1
    spec.position_tolerance = 0.05
    assert tolerance_samples(spec, 24) == 24


def test_every_pin_lands_inside_its_tolerance_zone():
    spec = preset(15)
    spec.position_tolerance = 0.08
    for errors in (ring_position_errors(spec, 32),
                   carrier_position_errors(spec, 32)):
        radius = np.hypot(errors[..., 0], errors[..., 1])
        assert radius.max() <= 0.08 / 2 + 1e-12
        assert radius.min() >= 0.0


def test_the_zone_is_filled_evenly_rather_than_crowded_at_the_middle():
    """Drawing the radius uniformly would put half the pins inside half the
    radius, which is a quarter of the area - a quietly better ring than the
    drawing allows.  Half the area should hold half the pins."""
    spec = preset(15)
    spec.position_tolerance = 0.10
    errors = ring_position_errors(spec, 400)
    radius = np.hypot(errors[..., 0], errors[..., 1])
    half_area = (0.10 / 2) / np.sqrt(2.0)
    assert (radius < half_area).mean() == pytest.approx(0.5, abs=0.05)


def test_the_same_design_draws_the_same_ring_every_time():
    """An analysis that moves when you reopen it cannot be checked against a
    measurement."""
    spec = preset(15)
    spec.position_tolerance = 0.05
    assert np.array_equal(ring_position_errors(spec, 8),
                          ring_position_errors(spec, 8))
    assert analyse_stiffness(spec).stiffness_Nm_per_arcmin == (
        analyse_stiffness(spec).stiffness_Nm_per_arcmin)


def test_the_ring_and_the_carrier_are_drawn_independently():
    spec = preset(15)
    spec.position_tolerance = 0.05
    spec.output_pin_count = spec.pin_count      # same shape, so they could match
    assert not np.allclose(ring_position_errors(spec, 4),
                           carrier_position_errors(spec, 4))


# ------------------------------------------------------- what it does to a drive


def test_a_drawing_with_no_tolerance_gets_the_answer_it_always_got():
    """The whole release rests on this: entering nothing changes nothing."""
    spec = preset(15)
    result = analyse_stiffness(spec)
    assert result.rings_sampled == 1
    assert not result.tolerance_was_sampled
    assert result.stiffness_p10_Nm_per_arcmin == result.stiffness_Nm_per_arcmin
    assert result.load_concentration_p90 == result.load_concentration
    assert result.lost_motion_p90_arcmin == result.lost_motion_arcmin
    assert result.position_interference_mm == 0.0


def test_position_error_concentrates_load_and_softens_the_drive():
    """The point of the whole model: with a uniform clearance every pin arrives
    together, and a few hundredths of position error decides which arrive
    first and carry it alone."""
    perfect, sloppy = preset(15), preset(15)
    sloppy.position_tolerance = 0.10
    a, b = analyse_stiffness(perfect), analyse_stiffness(sloppy)
    assert b.load_concentration > a.load_concentration
    assert b.pins_engaged < a.pins_engaged
    assert b.stiffness_Nm_per_arcmin < a.stiffness_Nm_per_arcmin


def test_a_looser_tolerance_costs_more_of_everything():
    """What grows with the tolerance is the *level*, not the spread.

    The spread does not grow without bound and must not be asserted to: past a
    point every ring in the batch has one pin carrying, so they all agree again
    and the band closes at a bad number rather than a good one.
    """
    concentration, stiffness = [], []
    for tolerance in (0.0, 0.02, 0.05, 0.10):
        spec = preset(15)
        spec.position_tolerance = tolerance
        r = analyse_stiffness(spec)
        concentration.append(r.load_concentration)
        stiffness.append(r.stiffness_Nm_per_arcmin)
    assert concentration == sorted(concentration)
    assert stiffness == sorted(stiffness, reverse=True)


def test_the_bad_ring_is_worse_than_the_middle_one_in_every_direction():
    spec = preset(15)
    spec.position_tolerance = 0.08
    r = analyse_stiffness(spec)
    assert r.rings_sampled > 1
    assert r.stiffness_p10_Nm_per_arcmin < r.stiffness_Nm_per_arcmin
    assert r.load_concentration_p90 > r.load_concentration
    assert r.lost_motion_p90_arcmin >= r.lost_motion_arcmin


def test_a_tolerance_that_eats_the_clearance_is_reported_not_absorbed():
    """A pin driven past the profile makes the drive bind. Clamping its gap at
    zero is the only thing a single-rotation solve can do, and it reads as a
    *better* drive - fewer gaps to close - so the bite has to be reported or
    the model quietly rewards the mistake."""
    spec = preset(29)
    spec.process = Process.EDM
    spec.apply_process_defaults()               # 0.012 mm of profile clearance
    spec.position_tolerance = 0.20              # far past it
    assert analyse_stiffness(spec).position_interference_mm > 0.0

    fits = preset(29)                           # 0.22 mm, room for the error
    fits.position_tolerance = 0.05
    assert analyse_stiffness(fits).position_interference_mm == 0.0


def test_position_error_is_the_half_transmission_error_was_missing():
    perfect, sloppy = preset(15), preset(15)
    sloppy.position_tolerance = 0.10
    a, b = analyse_transmission_error(perfect), analyse_transmission_error(sloppy)
    assert b.peak_to_peak_arcmin > 2.0 * a.peak_to_peak_arcmin
    assert b.worst_ring_arcmin > b.peak_to_peak_arcmin
    assert a.worst_ring_arcmin == a.peak_to_peak_arcmin      # one ring, no spread


def test_the_process_guides_cover_every_process():
    for process in Process:
        assert PROCESS_POSITION_TOLERANCE[process] > 0.0
    assert (PROCESS_POSITION_TOLERANCE[Process.FDM]
            > PROCESS_POSITION_TOLERANCE[Process.CNC]
            > PROCESS_POSITION_TOLERANCE[Process.EDM])


def test_the_process_defaults_button_does_not_enter_a_tolerance_for_you():
    """The clearances are dimensions you choose; a position tolerance is a claim
    about your machine. Defaulting it would derate every design in the app on
    the strength of a guess, so it stays a suggestion."""
    spec = preset(15)
    spec.process = Process.CNC
    spec.apply_process_defaults()
    assert spec.position_tolerance == 0.0
    assert spec.profile_clearance == 0.03       # the clearances did move
