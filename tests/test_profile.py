"""Profile maths.

The first two tests are the reason this file exists.  A sign error in the psi
form of the profile equation produced a curve that looked perfectly plausible on
screen but interfered with the ring pins by 1.07 mm.  Only the envelope property
catches it, so it is checked here on every run.
"""
from __future__ import annotations

import numpy as np
import pytest

from cycloidgen.core import profile as prof
from cycloidgen.core.spec import GearSpec, preset

CASES = [
    (50.0, 4.0, 1.5, 11),
    (45.0, 4.5, 2.0, 10),
    (60.0, 3.5, 1.1, 29),
    (70.0, 3.0, 0.7, 59),
    (30.0, 2.5, 1.2, 7),
]


@pytest.mark.parametrize("R,Rr,E,N", CASES)
def test_envelope_property(R, Rr, E, N):
    """Every profile point must sit exactly Rr from the pin-centre locus.

    This is the definition of the conjugate profile: it is what guarantees the
    disc rolls on the pins instead of digging into them.
    """
    locus = prof.pin_locus(np.linspace(0, 2 * np.pi, 200_000, endpoint=False), R, E, N)
    q = prof.disc_profile(np.linspace(0, 2 * np.pi, 1200, endpoint=False), R, Rr, E, N)
    d = np.array([np.hypot(locus[:, 0] - x, locus[:, 1] - y).min() for x, y in q])
    assert np.abs(d - Rr).max() < 5e-3, f"envelope deviation {np.abs(d - Rr).max():.4f} mm"


@pytest.mark.parametrize("R,Rr,E,N", CASES)
def test_psi_sign_trap(R, Rr, E, N):
    """The positive-sign psi form is wrong; make sure nobody 'fixes' it back.

    psi(t) = -atan2(sin(N t), R/(E*Np) - cos(N t))  is correct.  The variant
    without the leading minus circulates widely and fails by millimetres.
    """
    p = N + 1
    t = np.linspace(0, 2 * np.pi, 4000, endpoint=False)
    psi_wrong = +np.arctan2(np.sin(N * t), (R / (E * p)) - np.cos(N * t))
    wrong = np.column_stack([
        R * np.cos(t) - E * np.cos(p * t) - Rr * np.cos(t + psi_wrong),
        -R * np.sin(t) + E * np.sin(p * t) + Rr * np.sin(t + psi_wrong)])
    right = prof.disc_profile(t, R, Rr, E, N)
    assert np.abs(right - wrong).max() > 0.1, "the two psi signs must not agree"

    psi_right = -np.arctan2(np.sin(N * t), (R / (E * p)) - np.cos(N * t))
    from_psi = np.column_stack([
        R * np.cos(t) - E * np.cos(p * t) - Rr * np.cos(t + psi_right),
        -R * np.sin(t) + E * np.sin(p * t) + Rr * np.sin(t + psi_right)])
    assert np.abs(right - from_psi).max() < 1e-9


@pytest.mark.parametrize("R,Rr,E,N", CASES)
def test_matches_finite_difference_offset(R, Rr, E, N):
    """The closed form must equal a brute-force normal offset of the locus."""
    t = np.linspace(0, 2 * np.pi, 4000, endpoint=False)
    h = 1e-7
    base = prof.pin_locus(t, R, E, N)
    d1 = (prof.pin_locus(t + h, R, E, N) - prof.pin_locus(t - h, R, E, N)) / (2 * h)
    n = np.column_stack([d1[:, 1], -d1[:, 0]])
    n /= np.linalg.norm(n, axis=1)[:, None]
    n *= -np.sign((n * base).sum(axis=1))[:, None]        # inward
    assert np.abs(prof.disc_profile(t, R, Rr, E, N) - (base + Rr * n)).max() < 1e-6


@pytest.mark.parametrize("R,Rr,E,N", CASES)
def test_extents_and_lobe_count(R, Rr, E, N):
    t = np.linspace(0, 2 * np.pi, 20000, endpoint=False)
    q = prof.disc_profile(t, R, Rr, E, N)
    r = np.hypot(*q.T)
    assert r.min() == pytest.approx(R - Rr - E, abs=1e-6)
    assert r.max() == pytest.approx(R - Rr + E, abs=1e-6)
    spectrum = np.abs(np.fft.rfft(r - r.mean()))
    assert int(np.argmax(spectrum)) == N


@pytest.mark.parametrize("R,Rr,E,N", CASES)
def test_normal_is_unit_and_outward(R, Rr, E, N):
    t = np.linspace(0, 2 * np.pi, 3000, endpoint=False)
    n = prof.profile_normal(t, R, E, N)
    assert np.abs(np.linalg.norm(n, axis=1) - 1.0).max() < 1e-12
    q = prof.disc_profile(t, R, Rr, E, N)
    assert ((q * n).sum(axis=1) > 0).all(), "normal must point away from the disc centre"


def _self_intersects(points):
    a, b = points, np.roll(points, -1, axis=0)
    seg, n = b - a, len(points)
    for i in range(0, n, 2):
        p, r = a[i], seg[i]
        den = r[0] * seg[:, 1] - r[1] * seg[:, 0]
        ok = np.abs(den) > 1e-12
        qp, safe = a - p, np.where(ok, den, 1.0)
        tt = np.where(ok, (qp[:, 0] * seg[:, 1] - qp[:, 1] * seg[:, 0]) / safe, -1.0)
        uu = np.where(ok, (qp[:, 0] * r[1] - qp[:, 1] * r[0]) / safe, -1.0)
        hit = ok & (tt > 1e-9) & (tt < 1 - 1e-9) & (uu > 1e-9) & (uu < 1 - 1e-9)
        idx = np.where(hit)[0]
        if len(idx[(np.abs(idx - i) > 2) & (np.abs(idx - i) < n - 2)]):
            return True
    return False


@pytest.mark.parametrize("E", [0.6, 1.0, 1.5, 2.0, 3.0])
def test_critical_radius_predicts_self_intersection(E):
    """critical_radius must agree with a brute-force bisection on the real curve."""
    R, N = 50.0, 11
    lo, hi = 0.01, 60.0
    for _ in range(34):
        mid = 0.5 * (lo + hi)
        pts = prof.disc_profile(np.linspace(0, 2 * np.pi, 6000, endpoint=False),
                                R, mid, E, N)
        if _self_intersects(pts):
            hi = mid
        else:
            lo = mid
    empirical = 0.5 * (lo + hi)
    assert prof.critical_radius(R, E, N) == pytest.approx(empirical, rel=2e-3)


def test_profile_curvature_matches_finite_difference():
    R, Rr, E, N = 50.0, 4.0, 1.5, 11
    t = np.linspace(0.05, 2 * np.pi - 0.05, 500)
    h = 1e-5
    q0 = prof.disc_profile(t, R, Rr, E, N)
    qm = prof.disc_profile(t - h, R, Rr, E, N)
    qp = prof.disc_profile(t + h, R, Rr, E, N)
    d1, d2 = (qp - qm) / (2 * h), (qp - 2 * q0 + qm) / h ** 2
    k_fd = (d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / np.power(
        d1[:, 0] ** 2 + d1[:, 1] ** 2, 1.5)
    assert np.abs(k_fd - prof.profile_curvature(t, R, Rr, E, N)).max() < 1e-5


def test_chord_tolerance_is_actually_met():
    spec = preset(15)
    spec.dxf_chord_tolerance = 0.002
    p = prof.profile_from_spec(spec)
    dense = prof.disc_profile(np.linspace(0, 2 * np.pi, 400_000, endpoint=False),
                              spec.effective_R, spec.effective_Rr,
                              spec.eccentricity, spec.lobes)
    mid = 0.5 * (p.points + np.roll(p.points, -1, axis=0))
    err = np.array([np.hypot(dense[:, 0] - x, dense[:, 1] - y).min() for x, y in mid[::7]])
    assert err.max() < spec.dxf_chord_tolerance * 1.5


@pytest.mark.parametrize("R,Rr,E,N", CASES)
def test_the_sampled_polygon_has_the_disc_s_own_symmetry(R, Rr, E, N):
    """Turning the sampled disc by one lobe pitch gives back the same vertices.

    True of the curve - ``q(t + 2*pi/N) = rot(-2*pi/N) . q(t)`` - and true of the
    sampling only if the sample count divides by the lobe count, which is why
    the chord-tolerance count is rounded up onto one.  Without it each lobe is
    sampled from a slightly different place, and a disc that turns by exactly
    one pitch comes back a fraction of a step out: which is what stops an
    exported animation from closing on itself.
    """
    n = prof.sample_count_for_chord_tolerance(R, Rr, E, N, 0.005)
    assert n % N == 0

    pts = prof.sampled_profile(R, Rr, E, N, n).points
    a = 2.0 * np.pi / N
    c, s = np.cos(a), np.sin(a)
    turned = pts @ np.array([[c, -s], [s, c]])        # rotate by -a
    assert np.abs(turned - np.roll(pts, -n // N, axis=0)).max() < 1e-9


def test_spec_derived_values():
    s = GearSpec(lobes=11, pin_circle_radius=50, pin_radius=4, eccentricity=1.5,
                 output_pin_diameter=6, hole_clearance=0.0)
    assert s.pin_count == 12 and s.ratio == 11
    assert pytest.approx(1.5 * 12 / 50) == s.K1
    assert s.output_hole_diameter == pytest.approx(6 + 2 * 1.5)
