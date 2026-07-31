"""Contact loads and stress.

Model and its limits
--------------------
The disc is treated as rigid and each contact as a linear spring, so the force
at a contact is proportional to its moment arm and only the pins on the pushing
side carry load.  This is the classical Kudryavtsev/Lehmann assumption.  It
ignores manufacturing clearance, which in a real drive concentrates load on
fewer pins.  Treat every number here as preliminary sizing, not certification.

One tidy result falls out of the geometry: the equivalent contact radius is

    R_eq = Rr * (1 + Rr * kappa_locus)

so the contact stress is directly tied to how close the design sits to the
undercut limit ``Rr = 1/max(-kappa)``.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core import profile as prof
from ..core.kinematics import SWEEP_STEPS, output_loads, sweep
from ..core.spec import GearSpec

__all__ = [
    "ContactResult",
    "analyse_contacts",
    "effective_modulus",
    "hertz_line_pressure",
    "torque_capacity",
]


def effective_modulus(E1_GPa: float, nu1: float, E2_GPa: float, nu2: float) -> float:
    """Plane-strain effective modulus E* in MPa."""
    e1, e2 = E1_GPa * 1000.0, E2_GPa * 1000.0
    return 1.0 / ((1.0 - nu1 ** 2) / e1 + (1.0 - nu2 ** 2) / e2)


def hertz_line_pressure(force_N: np.ndarray | float, length_mm: float,
                        R_eq_mm: np.ndarray | float, E_star_MPa: float) -> np.ndarray:
    """Peak Hertzian pressure for line contact, MPa."""
    f_per_mm = np.asarray(force_N, dtype=float) / max(length_mm, 1e-9)
    r = np.maximum(np.asarray(R_eq_mm, dtype=float), 1e-9)
    return np.sqrt(f_per_mm * E_star_MPa / (np.pi * r))


def _R_eq_ring(spec: GearSpec, t: np.ndarray) -> np.ndarray:
    k = prof.locus_curvature(t, spec.pin_circle_radius, spec.eccentricity, spec.lobes)
    return spec.pin_radius * (1.0 + spec.pin_radius * k)


@dataclass
class ContactResult:
    """Worst-case contact numbers over one input revolution."""

    max_pin_force_N: float
    max_pin_pressure_MPa: float
    pin_pressure_allow_MPa: float
    pin_safety_factor: float
    min_R_eq_mm: float
    pins_in_contact: int
    max_output_force_N: float
    max_output_pressure_MPa: float
    output_safety_factor: float
    eccentric_bearing_load_N: float
    radial_load_ripple_pct: float   # variation of the resultant force into the eccentric
    mean_sliding_speed_mm_s: float

    @property
    def ok(self) -> bool:
        return self.pin_safety_factor >= 1.0 and self.output_safety_factor >= 1.0


def analyse_contacts(spec: GearSpec, steps: int = SWEEP_STEPS) -> ContactResult:
    """Sweep a full lobe pitch and report the worst contact conditions."""
    torque_out_Nmm = spec.output_torque_Nm * 1000.0
    # each disc carries its share of the torque
    torque_per_disc = torque_out_Nmm / spec.disc_count
    length = spec.disc_thickness

    e_star_ring = effective_modulus(spec.disc_mat.E_GPa, spec.disc_mat.nu,
                                    spec.pin_mat.E_GPa, spec.pin_mat.nu)
    allow = min(spec.disc_mat.sigma_contact_MPa, spec.pin_mat.sigma_contact_MPa)

    peak_f = peak_p = 0.0
    min_req = float("inf")
    n_contact = 0
    resultants: list[float] = []
    slide_means: list[float] = []
    peak_out_f = 0.0

    omega_in = spec.input_rpm * 2.0 * np.pi / 60.0

    for cs in sweep(spec, steps):
        f = cs.forces(torque_per_disc)
        req = _R_eq_ring(spec, cs.t)
        p = hertz_line_pressure(f, length, req, e_star_ring)

        live = f > 0
        if live.any():
            peak_f = max(peak_f, float(f[live].max()))
            peak_p = max(peak_p, float(p[live].max()))
            min_req = min(min_req, float(req[live].min()))
            n_contact = max(n_contact, int(live.sum()))
            slide_means.append(float((cs.sliding_speed[live] * omega_in).mean()))

        # resultant radial force the disc pushes into the eccentric bearing
        fv = (f[:, None] * cs.normals).sum(axis=0)
        resultants.append(float(np.hypot(*fv)))

        ol = output_loads(spec, cs.phi, torque_per_disc)
        if ol.forces.any():
            peak_out_f = max(peak_out_f, float(ol.forces.max()))

    # output pin in an oversized hole: conformal contact
    r_p = spec.output_pin_diameter / 2.0
    r_hole = r_p + spec.eccentricity
    req_out = r_p * r_hole / max(spec.eccentricity, 1e-6)
    # same pair of materials as the ring contact, so the same effective modulus
    p_out = float(hertz_line_pressure(peak_out_f, length, req_out, e_star_ring))

    ripple = 0.0
    if resultants:
        lo, hi = min(resultants), max(resultants)
        ripple = 100.0 * (hi - lo) / hi if hi > 0 else 0.0

    return ContactResult(
        max_pin_force_N=peak_f,
        max_pin_pressure_MPa=peak_p,
        pin_pressure_allow_MPa=allow,
        pin_safety_factor=allow / peak_p if peak_p > 0 else float("inf"),
        min_R_eq_mm=min_req if np.isfinite(min_req) else 0.0,
        pins_in_contact=n_contact,
        max_output_force_N=peak_out_f,
        max_output_pressure_MPa=p_out,
        output_safety_factor=allow / p_out if p_out > 0 else float("inf"),
        eccentric_bearing_load_N=max(resultants) if resultants else 0.0,
        radial_load_ripple_pct=ripple,
        mean_sliding_speed_mm_s=float(np.mean(slide_means)) if slide_means else 0.0,
    )


def torque_capacity(spec: GearSpec, steps: int = SWEEP_STEPS,
                    contact: ContactResult | None = None) -> float:
    """Output torque (Nm) at which the ring-pin contact reaches its allowable stress.

    Pass ``contact`` when the sweep has already been run at ``spec``'s own duty
    point - the scaling below only needs the peak pressure it reports.
    """
    probe = contact if contact is not None else analyse_contacts(spec, steps)
    if probe.max_pin_pressure_MPa <= 0:
        return float("inf")
    # p_max scales with sqrt(torque), so capacity scales with the square of the ratio
    return spec.output_torque_Nm * (probe.pin_pressure_allow_MPa /
                                    probe.max_pin_pressure_MPa) ** 2
