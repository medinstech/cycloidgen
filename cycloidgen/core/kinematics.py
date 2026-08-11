"""Motion of the disc, contact points, and load sharing.

Every relation here was verified by a meshing sweep: with the pose law below the
disc rolls through a full input revolution with 0.08 um residual interference,
while a ratio one tooth away jams by 450-730 um.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from . import profile as prof
from .spec import GearSpec

__all__ = [
    "SWEEP_STEPS",
    "ContactState",
    "OutputLoads",
    "contacts",
    "contacts_at",
    "disc_pose",
    "mesh_gaps",
    "output_loads",
    "output_stage_period",
    "output_sweep_angles",
    "ring_stage_period",
    "sweep",
    "sweep_angles",
    "to_disc_frame",
    "to_world",
]

#: Steps per period for every sweep in the app.  One shared value means the
#: checks, the contact study and the efficiency study all reuse a single cached
#: sweep instead of each running their own.
#:
#: 72 is enough because each sweep now covers an exact period: uniform samples
#: over a whole cycle are unbiased however few there are, so the count only has
#: to resolve the peak.  Measured against a 20000-step reference, 72 steps miss
#: the peak pin force by 0.11% at 30 lobes and 144 by 0.004%; the mean is
#: already exact to four figures at 72.  The old window was not a period, and no
#: step count fixes that.
SWEEP_STEPS = 144


def disc_pose(phi: float | np.ndarray, E: float, lobes: int):
    """Disc centre and disc rotation for crank angle ``phi``.

    Verified law: centre = E*(cos phi, -sin phi), rotation = +phi / lobes.
    """
    centre = np.stack([E * np.cos(phi), -E * np.sin(phi)], axis=-1)
    return centre, np.asarray(phi) / lobes


def to_world(points: np.ndarray, phi: float, E: float, lobes: int) -> np.ndarray:
    """Map disc-frame points into the housing frame at crank angle ``phi``."""
    centre, delta = disc_pose(phi, E, lobes)
    c, s = np.cos(delta), np.sin(delta)
    rot = np.array([[c, -s], [s, c]])
    return points @ rot.T + centre


def to_disc_frame(points: np.ndarray, phi: float, E: float, lobes: int) -> np.ndarray:
    """Inverse of :func:`to_world`.

    ``to_world`` post-multiplies by ``rot.T``, so undoing it post-multiplies by
    ``rot`` - getting that backwards silently mirrors the mesh, which looks
    plausible and measures wrong.
    """
    centre, delta = disc_pose(phi, E, lobes)
    c, s = np.cos(delta), np.sin(delta)
    return (points - centre) @ np.array([[c, -s], [s, c]])


@dataclass(frozen=True)
class ContactState:
    """Everything about the ring-pin contacts at one crank angle."""

    phi: float
    t: np.ndarray            # profile parameter at each pin's contact
    points: np.ndarray       # contact points, housing frame (pins, 2)
    normals: np.ndarray      # unit normals pointing disc -> pin, housing frame
    moment_arms: np.ndarray  # signed, about the disc centre (mm)
    curvature: np.ndarray    # signed profile curvature at contact (1/mm)
    sliding_speed: np.ndarray  # |mm/s| per unit input rad/s

    @property
    def loaded_mask(self) -> np.ndarray:
        """Pins that can push against the driving torque (the other half cannot pull)."""
        return self.moment_arms < 0

    def forces(self, torque_Nmm: float) -> np.ndarray:
        """Share ``torque_Nmm`` over the loaded pins, force proportional to lever arm.

        Standard rigid-disc/linear-contact assumption: deflection at a contact is
        proportional to its moment arm, so F_i ~ h_i and sum(F_i * h_i) = T.
        """
        h = self.moment_arms
        m = self.loaded_mask
        denom = float((h[m] ** 2).sum())
        f = np.zeros_like(h)
        if denom > 0:
            f[m] = torque_Nmm * np.abs(h[m]) / denom
        return f


def contacts(spec: GearSpec, phi: float) -> ContactState:
    """Contact geometry at crank angle ``phi``, using the *theoretical* profile.

    Clearance is deliberately excluded: with clearance the real contact set is
    smaller and load-dependent, which this closed-form model cannot resolve.
    """
    return contacts_at(spec.pin_circle_radius, spec.pin_radius, spec.eccentricity,
                       spec.lobes, float(phi))


def contacts_at(R: float, Rr: float, E: float, n_lobes: int, phi: float) -> ContactState:
    """:func:`contacts` on plain numbers, so results can be cached and shared."""
    pins = n_lobes + 1

    alpha = 2.0 * np.pi * np.arange(pins) / pins
    t = phi / n_lobes - alpha

    q = prof.disc_profile(t, R, Rr, E, n_lobes)
    nrm = prof.profile_normal(t, R, E, n_lobes)
    h = q[:, 0] * nrm[:, 1] - q[:, 1] * nrm[:, 0]
    kappa = prof.profile_curvature(t, R, Rr, E, n_lobes)

    _, delta = disc_pose(phi, E, n_lobes)
    c, s = np.cos(delta), np.sin(delta)
    rot = np.array([[c, -s], [s, c]])
    q_w = to_world(q, phi, E, n_lobes)
    n_w = nrm @ rot.T
    r_c = q_w - np.array([E * np.cos(phi), -E * np.sin(phi)])

    # velocity of the disc material point at the contact, per unit input rad/s
    dC = np.array([-E * np.sin(phi), -E * np.cos(phi)])
    v = dC + np.column_stack([-r_c[:, 1], r_c[:, 0]]) / n_lobes
    tang = np.column_stack([-n_w[:, 1], n_w[:, 0]])
    slide = np.abs((v * tang).sum(axis=1))

    return ContactState(phi=phi, t=t, points=q_w, normals=n_w, moment_arms=h,
                        curvature=kappa, sliding_speed=slide)


def ring_stage_period(lobes: int) -> float:
    """Crank angle over which the ring-pin engagement pattern repeats, rad.

    Not the lobe pitch.  The lobe pitch is the period of the *disc's shape*, and
    that is not what a sweep samples: a sweep samples the pins, and there are
    ``N+1`` of them against ``N`` lobes, which is the whole point of the drive.
    Pin ``k`` touches the profile at ``t_k = phi/N - 2*pi*k/(N+1)``, so the crank
    has to turn ``2*pi*N/(N+1)`` before every contact lands where its neighbour
    was.  That is just under one input revolution, ten lobe pitches, not one.

    Sampling a lobe pitch instead does not merely lose resolution - it samples a
    window that is not a cycle, so the curve does not close and the statistics
    are taken over an arbitrary phase.  See :func:`output_stage_period`, where
    the same mistake was caught for the other stage first.
    """
    return 2.0 * np.pi * lobes / (lobes + 1)


def output_stage_period(lobes: int, output_pins: int) -> float:
    """Crank angle over which the output-pin engagement pattern repeats, rad.

    The disc's eccentricity direction, *seen from the carrier*, advances at
    ``(N-1)/N`` of the crank; the pin pattern repeats every ``2*pi/n`` of that.
    So the output stage's period is ``2*pi*N / (n*(N-1))`` - two and a half lobe
    pitches on a typical drive, and sampling only one lobe pitch of it reports
    about half the ripple that is really there.

    This is a different period from :func:`ring_stage_period`, and deliberately
    so.  Their common multiple runs to thirty input revolutions on some tooth
    counts, which is why each stage is swept over its own: a mean of a sum is
    the sum of the means, and a maximum per stage is a maximum per stage.
    """
    return 2.0 * np.pi * lobes / (output_pins * (lobes - 1))


def sweep_angles(lobes: int, steps: int = SWEEP_STEPS) -> np.ndarray:
    """Crank angles covering exactly one ring-stage period."""
    return np.linspace(0.0, ring_stage_period(lobes), steps, endpoint=False)


def output_sweep_angles(lobes: int, output_pins: int,
                        steps: int = SWEEP_STEPS) -> np.ndarray:
    """Crank angles covering exactly one output-stage period."""
    return np.linspace(0.0, output_stage_period(lobes, output_pins), steps,
                       endpoint=False)


@lru_cache(maxsize=8)
def _sweep(R: float, Rr: float, E: float, lobes: int, steps: int) -> tuple[ContactState, ...]:
    states = tuple(contacts_at(R, Rr, E, lobes, float(phi))
                   for phi in sweep_angles(lobes, steps))
    for cs in states:                      # shared objects: hand them out read-only
        for arr in (cs.t, cs.points, cs.normals, cs.moment_arms,
                    cs.curvature, cs.sliding_speed):
            arr.flags.writeable = False
    return states


def sweep(spec: GearSpec, steps: int = SWEEP_STEPS) -> tuple[ContactState, ...]:
    """One cached ring-stage sweep, shared by the checks and both studies.

    Rebuilding this three times was most of the cost of a design update, and the
    three copies were sampled differently for no reason.

    This covers the ring stage only.  Anything that loads the *output* pins has
    to sweep :func:`output_sweep_angles` as well - the two stages do not share a
    period, and reading output loads off these states samples them at whatever
    phases the ring happened to need.
    """
    return _sweep(spec.pin_circle_radius, spec.pin_radius, spec.eccentricity,
                  spec.lobes, steps)


@lru_cache(maxsize=1024)
def _mesh_gaps(R_eff: float, Rr_eff: float, R: float, Rr: float, E: float,
               lobes: int, phi: float, n: int) -> np.ndarray:
    """:func:`mesh_gaps` on plain numbers, so results can be cached and shared.

    Worth caching: this is the one part of a design update that samples the
    profile and measures against it, the checks and the stiffness and
    transmission-error studies all ask for the same crank angles, and it is a
    pure function of the numbers below.  Handed out read-only, like the sweep.
    """
    p = prof.sampled_profile(R_eff, Rr_eff, E, lobes, n)
    pins = lobes + 1
    alpha = 2.0 * np.pi * np.arange(pins) / pins
    pins_world = R * np.column_stack([np.cos(alpha), np.sin(alpha)])
    pins_disc = to_disc_frame(pins_world, phi, E, lobes)
    gaps = prof.distance_to_polyline(pins_disc, p.points) - Rr
    gaps.flags.writeable = False
    return gaps


def mesh_gaps(spec: GearSpec, phi: float, n: int = 2000) -> np.ndarray:
    """Normal clearance at every ring pin at crank angle ``phi``, mm.

    Measured rather than assumed: the distance from each pin centre to the
    *manufactured* profile, less the pin radius.  Whatever the selected offset
    mode actually does to the profile shows up here, including getting the sign
    wrong and cutting an interference instead of a clearance.

    A negative value means the disc and that pin occupy the same space.
    """
    return _mesh_gaps(spec.effective_R, spec.effective_Rr, spec.pin_circle_radius,
                      spec.pin_radius, spec.eccentricity, spec.lobes,
                      float(phi), int(n))


@dataclass(frozen=True)
class OutputLoads:
    """Force sharing on the output pins at one crank angle."""

    phi: float
    positions: np.ndarray    # pin centres in the carrier frame (n, 2)
    moment_arms: np.ndarray
    forces: np.ndarray       # N, magnitude
    sliding_speed: float     # mm per unit input rad/s

    @property
    def engaged(self) -> int:
        return int((self.forces > 0).sum())


def output_loads(spec: GearSpec, phi: float, torque_Nmm: float) -> OutputLoads:
    """Distribute output torque over the pins that can push.

    Relative to the output carrier the disc performs a pure circular translation
    of radius E, so every pin's contact normal is parallel to the eccentricity
    direction and only the half with a favourable lever arm carries load.
    """
    n = spec.output_pin_count
    gamma = 2.0 * np.pi * np.arange(n) / n
    pos = spec.output_bolt_circle_radius * np.column_stack([np.cos(gamma), np.sin(gamma)])

    # eccentricity direction seen from the carrier (carrier spins with the disc)
    eps = phi - phi / spec.lobes
    normal = np.array([np.cos(eps), -np.sin(eps)])
    h = pos[:, 0] * normal[1] - pos[:, 1] * normal[0]

    m = h < 0
    denom = float((h[m] ** 2).sum())
    f = np.zeros(n)
    if denom > 0:
        f[m] = torque_Nmm * np.abs(h[m]) / denom

    return OutputLoads(phi=phi, positions=pos, moment_arms=h, forces=f,
                       sliding_speed=spec.eccentricity)
