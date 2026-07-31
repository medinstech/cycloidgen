"""Meshing, ratio and load sharing.

The interference sweep is the second half of the profile proof: the envelope test
says the shape is right, this one says the shape and the motion law agree.
"""
from __future__ import annotations

import numpy as np
import pytest

from cycloidgen.core import profile as prof
from cycloidgen.core.kinematics import contacts, disc_pose, output_loads, to_world
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
