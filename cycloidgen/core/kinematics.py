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
    "sweep",
    "sweep_angles",
    "to_disc_frame",
    "to_world",
]

#: Steps per lobe pitch for every sweep in the app.  One shared value means the
#: checks, the contact study and the efficiency study all reuse a single cached
#: sweep instead of each running their own.
SWEEP_STEPS = 72


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


def sweep_angles(lobes: int, steps: int = SWEEP_STEPS) -> np.ndarray:
    """Crank angles covering exactly one lobe pitch, the period of the mesh."""
    return np.linspace(0.0, 2.0 * np.pi / lobes, steps, endpoint=False)


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
    """One cached lobe-pitch sweep, shared by the checks and both studies.

    Rebuilding this three times was most of the cost of a design update, and the
    three copies were sampled differently for no reason.
    """
    return _sweep(spec.pin_circle_radius, spec.pin_radius, spec.eccentricity,
                  spec.lobes, steps)


def mesh_gaps(spec: GearSpec, phi: float, n: int = 2000) -> np.ndarray:
    """Normal clearance at every ring pin at crank angle ``phi``, mm.

    Measured rather than assumed: the distance from each pin centre to the
    *manufactured* profile, less the pin radius.  Whatever the selected offset
    mode actually does to the profile shows up here, including getting the sign
    wrong and cutting an interference instead of a clearance.

    A negative value means the disc and that pin occupy the same space.
    """
    p = prof.profile_from_spec(spec, n=n)
    alpha = 2.0 * np.pi * np.arange(spec.pin_count) / spec.pin_count
    pins_world = spec.pin_circle_radius * np.column_stack([np.cos(alpha), np.sin(alpha)])
    pins_disc = to_disc_frame(pins_world, float(phi), spec.eccentricity, spec.lobes)
    return prof.distance_to_polyline(pins_disc, p.points) - spec.pin_radius


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
