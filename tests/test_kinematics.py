"""Meshing, ratio and load sharing.

The interference sweep is the second half of the profile proof: the envelope test
says the shape is right, this one says the shape and the motion law agree.
"""
from __future__ import annotations

import numpy as np
import pytest

from cycloidgen.core import profile as prof
from cycloidgen.core.kinematics import (
    contacts,
    disc_pose,
    output_loads,
    output_stage_period,
    output_sweep_angles,
    ring_stage_period,
    sweep_angles,
    to_world,
)
from cycloidgen.core.spec import GearSpec, preset

CASES = [(50.0, 4.0, 1.5, 11), (45.0, 4.5, 2.0, 10), (60.0, 3.5, 1.1, 29)]


def _worst_interference(R, Rr, E, N, ratio=None, steps=32, n_prof=3000):
    """Deepest a ring pin cuts into the disc over one input revolution, in mm."""
    k = ratio or N
    pins_n = N + 1
    pins = R * np.column_stack([np.cos(2 * np.pi * np.arange(pins_n) / pins_n),
                                np.sin(2 * np.pi * np.arange(pins_n) / pins_n)])
    q = prof.disc_profile(np.linspace(0, 2 * np.pi, n_prof, endpoint=False), R, Rr, E, N)
    worst = -np.inf
    for phi in np.linspace(0, 2 * np.pi, steps, endpoint=False):
        d = phi / k
        c, s = np.cos(d), np.sin(d)
        w = np.column_stack([q[:, 0] * c - q[:, 1] * s + E * np.cos(phi),
                             q[:, 0] * s + q[:, 1] * c - E * np.sin(phi)])
        dist = np.linalg.norm(w[:, None, :] - pins[None, :, :], axis=2)
        worst = max(worst, float((Rr - dist.min(axis=1)).max()))
    return worst


@pytest.mark.parametrize("R,Rr,E,N", CASES)
def test_disc_rolls_without_interference(R, Rr, E, N):
    """A full input revolution with the verified pose law must not bind."""
    assert _worst_interference(R, Rr, E, N) < 2e-3


@pytest.mark.parametrize("R,Rr,E,N", CASES)
def test_wrong_ratio_jams(R, Rr, E, N):
    """One tooth either way must produce gross interference - proves i == lobes."""
    for wrong in (N - 1, N + 1):
        assert _worst_interference(R, Rr, E, N, ratio=wrong) > 0.1


@pytest.mark.parametrize("R,Rr,E,N", CASES)
def test_output_hole_is_pin_plus_twice_eccentricity(R, Rr, E, N):
    """In the carrier frame the disc translates on a circle of radius exactly E."""
    p0 = np.array([[0.4 * R, 0.0]])
    radii = []
    for phi in np.linspace(0, 2 * np.pi, 720):
        w = to_world(p0, float(phi), E, N)[0]
        _, delta = disc_pose(float(phi), E, N)
        c, s = np.cos(-delta), np.sin(-delta)
        carrier = np.array([w[0] * c - w[1] * s, w[0] * s + w[1] * c])
        radii.append(np.hypot(*(carrier - p0[0])))
    assert np.allclose(radii, E, atol=1e-9)


def test_contact_parameters_land_on_the_pins():
    """Each contact point must be exactly Rr away from its own pin centre."""
    s = preset(15)
    R, Rr, N = s.pin_circle_radius, s.pin_radius, s.lobes
    for phi in np.linspace(0, 2 * np.pi, 17):
        cs = contacts(s, float(phi))
        pins = R * np.column_stack([np.cos(2 * np.pi * np.arange(N + 1) / (N + 1)),
                                    np.sin(2 * np.pi * np.arange(N + 1) / (N + 1))])
        assert np.allclose(np.linalg.norm(cs.points - pins, axis=1), Rr, atol=1e-9)


def test_contact_normal_points_at_the_pin():
    s = preset(15)
    cs = contacts(s, 0.7)
    pins = s.pin_circle_radius * np.column_stack([
        np.cos(2 * np.pi * np.arange(s.pin_count) / s.pin_count),
        np.sin(2 * np.pi * np.arange(s.pin_count) / s.pin_count)])
    direction = pins - cs.points
    direction /= np.linalg.norm(direction, axis=1)[:, None]
    assert np.allclose(direction, cs.normals, atol=1e-9)


def test_load_sharing_balances_torque():
    s = preset(15)
    torque = 4200.0
    for phi in np.linspace(0, 2 * np.pi / s.lobes, 12):
        cs = contacts(s, float(phi))
        f = cs.forces(torque)
        assert (f >= 0).all()
        assert float((f * np.abs(cs.moment_arms)).sum()) == pytest.approx(torque, rel=1e-9)
        assert 0 < (f > 0).sum() <= s.pin_count


def test_about_half_the_pins_carry_load():
    """All pins touch in the zero-clearance ideal, but only half can push."""
    s = preset(15)
    counts = [int((contacts(s, float(p)).forces(1000.0) > 0).sum())
              for p in np.linspace(0, 2 * np.pi / s.lobes, 24)]
    assert 0.3 * s.pin_count <= np.mean(counts) <= 0.7 * s.pin_count


def test_output_load_sharing():
    s = preset(15)
    torque = 3000.0
    for phi in np.linspace(0, 2 * np.pi, 12):
        ol = output_loads(s, float(phi), torque)
        assert float((ol.forces * np.abs(ol.moment_arms)).sum()) == pytest.approx(
            torque, rel=1e-9)
        assert 0 < ol.engaged <= s.output_pin_count


def test_disc_turns_one_lobe_pitch_backwards_per_input_revolution():
    s = GearSpec(lobes=11)
    _, d0 = disc_pose(0.0, s.eccentricity, s.lobes)
    _, d1 = disc_pose(2 * np.pi, s.eccentricity, s.lobes)
    assert float(d1 - d0) == pytest.approx(2 * np.pi / s.lobes)


# ------------------------------------------------------------------ periods --
#
# The bug these lock out: every sweep in the app ran over one lobe pitch and a
# docstring called that "the period of the mesh".  It is not.  A lobe pitch is
# the period of the disc's *shape*; a sweep samples the *pins*, and there are
# N+1 of those against N lobes.  The pin force at phi=0 and at phi=one lobe
# pitch differed by 0.59 N on the default drive, so the plotted curve did not
# close and every statistic was taken over an arbitrary phase of a cycle it
# never covered.
#
# No test caught it because no test asserted a period was a period.

PERIOD_CASES = [(7, 6), (9, 6), (10, 6), (11, 6), (15, 8), (20, 6), (30, 12)]


@pytest.mark.parametrize("lobes,out_pins", PERIOD_CASES)
def test_ring_stage_period_repeats_the_contact_state(lobes, out_pins):
    """Advance by the ring period and every contact lands where its neighbour was.

    The load *pattern* returns, indexed one pin along - not the load on a given
    pin.  That is the periodicity a sweep needs: a maximum and a mean over the
    pins are both invariant under relabelling them, so a window of this length
    samples the whole cycle whatever the labels do.
    """
    s = GearSpec(lobes=lobes, output_pin_count=out_pins)
    period = ring_stage_period(lobes)
    for phi in (0.0, 0.37, 1.9, 4.2):
        a = contacts(s, phi).forces(5000.0)
        b = contacts(s, phi + period).forces(5000.0)
        assert np.allclose(np.roll(a, 1), b, atol=1e-9), \
            f"ring stage not periodic at {phi}"


@pytest.mark.parametrize("lobes,out_pins", PERIOD_CASES)
def test_output_stage_period_repeats_the_pin_loads(lobes, out_pins):
    """As above, and the pattern steps the *other* way round the carrier."""
    s = GearSpec(lobes=lobes, output_pin_count=out_pins)
    period = output_stage_period(lobes, out_pins)
    for phi in (0.0, 0.37, 1.9, 4.2):
        a = output_loads(s, phi, 5000.0).forces
        b = output_loads(s, phi + period, 5000.0).forces
        assert np.allclose(np.roll(a, -1), b, atol=1e-9), \
            f"output stage not periodic at {phi}"


@pytest.mark.parametrize("lobes,out_pins", PERIOD_CASES)
def test_a_lobe_pitch_is_not_either_stage_period(lobes, out_pins):
    """The mistake itself, held down.

    Without this the periods above could quietly be replaced by ``2*pi/lobes``
    again and only the plots would show it.  Compared as multisets, because
    relabelling is allowed and this still has to fail: a lobe pitch does not
    return the set of loads, so no amount of renumbering the pins rescues it.
    """
    s = GearSpec(lobes=lobes, output_pin_count=out_pins)
    pitch = 2.0 * np.pi / lobes
    assert not np.allclose(np.sort(contacts(s, 0.0).forces(5000.0)),
                           np.sort(contacts(s, pitch).forces(5000.0)), atol=1e-6)
    assert not np.allclose(np.sort(output_loads(s, 0.0, 5000.0).forces),
                           np.sort(output_loads(s, pitch, 5000.0).forces), atol=1e-6)


@pytest.mark.parametrize("lobes,out_pins", PERIOD_CASES)
def test_sweeps_span_exactly_one_period(lobes, out_pins):
    """Both sweeps must tile their cycle: last sample plus one step is the first."""
    for angles, period in (
        (sweep_angles(lobes, 16), ring_stage_period(lobes)),
        (output_sweep_angles(lobes, out_pins, 16), output_stage_period(lobes, out_pins)),
    ):
        step = angles[1] - angles[0]
        assert angles[0] == 0.0
        assert float(angles[-1] + step) == pytest.approx(period)


def test_ring_period_is_shorter_than_the_revolution_that_also_closes():
    """It is N/(N+1) of a turn.

    A full input revolution closes the ring stage too - and closes it exactly,
    pin for pin, with no relabelling, because the disc's own N-fold symmetry has
    come round.  Sweeping that would not be wrong, only ``N+1`` times the work.
    """
    s = GearSpec(lobes=11)
    assert ring_stage_period(11) == pytest.approx(2 * np.pi * 11 / 12)
    assert ring_stage_period(11) < 2 * np.pi
    assert np.allclose(contacts(s, 0.0).forces(5000.0),
                       contacts(s, 2 * np.pi).forces(5000.0), atol=1e-9)
