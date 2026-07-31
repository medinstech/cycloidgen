"""Sliding duty (PV) and the running temperature that follows from the losses.

Why this matters more than the stress check
-------------------------------------------
A printed cycloidal drive with fixed pins almost never fails by cracking.  It
fails because a polymer sliding dry against steel has a wear rate that climbs
with the product of contact pressure and sliding speed, and above a limiting
*PV* the surface heats faster than it can shed heat, softens, and the drive
grinds itself round.  Contact stress can be comfortable and the drive still be
finished in an afternoon.

PV convention
-------------
Published limiting-PV figures for bearing plastics use the **projected area**
pressure - load divided by ``diameter x length`` - not the Hertzian peak.  This
module follows that convention, because the numbers are only meaningful compared
against limits derived the same way.  The Hertzian pressures live in
:mod:`cycloidgen.analysis.mechanics`; the two are not interchangeable, and the
Hertz peak is several times the projected-area pressure.

Rolling elements sidestep the whole criterion: a needle roller replaces sliding
with rolling, so PV stops being the governing limit and the module says so
rather than reporting a meaningless number.

Temperature
-----------
A single lumped body losing heat from the outside of the housing:

    dT = P_loss / (h * A)

with ``h`` covering natural convection and radiation together.  There is no
conduction into whatever the gearbox is bolted to, no oil, no fan - so this is
the pessimistic, free-standing, still-air case.  Bolt it to a metal frame and
the real rise is lower.  It is a screening number: it answers "will this melt",
not "what temperature will it run at".
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.kinematics import SWEEP_STEPS, output_loads, sweep
from ..core.spec import GearSpec
from .efficiency import EfficiencyResult, analyse_efficiency

__all__ = ["CONVECTION_W_M2K", "ThermalResult", "analyse_thermal"]

#: Combined natural convection and radiation from a small housing in still air,
#: W/m^2K.  Free convection off a palm-sized body runs about 8; grey-body
#: radiation near ambient adds roughly 5.
CONVECTION_W_M2K = 12.0

#: Effective PV multiplier once the contact rolls instead of slides.  Rolling
#: elements do not eliminate micro-slip, but they take the duty far below any
#: sliding limit; this keeps the reported number honest rather than zero.
_ROLLING_PV_FACTOR = 0.05


@dataclass
class ThermalResult:
    """Sliding duty and the temperature it produces."""

    pv_ring_MPa_m_s: float
    pv_ring_limit_MPa_m_s: float
    pv_output_MPa_m_s: float
    pv_output_limit_MPa_m_s: float
    ring_pressure_MPa: float          # projected area, not Hertzian
    ring_sliding_speed_m_s: float
    output_pressure_MPa: float
    output_sliding_speed_m_s: float
    loss_W: float
    cooling_area_mm2: float
    temperature_rise_C: float
    temperature_C: float
    temperature_limit_C: float

    @property
    def ring_pv_margin(self) -> float:
        """Limit over duty.  Below 1 the ring contact is wearing itself out."""
        return (self.pv_ring_limit_MPa_m_s / self.pv_ring_MPa_m_s
                if self.pv_ring_MPa_m_s > 0 else float("inf"))

    @property
    def output_pv_margin(self) -> float:
        return (self.pv_output_limit_MPa_m_s / self.pv_output_MPa_m_s
                if self.pv_output_MPa_m_s > 0 else float("inf"))

    @property
    def temperature_margin_C(self) -> float:
        return self.temperature_limit_C - self.temperature_C


def analyse_thermal(spec: GearSpec, efficiency: EfficiencyResult | None = None,
                    steps: int = SWEEP_STEPS) -> ThermalResult:
    """Worst-case PV at both sliding interfaces, plus the steady temperature."""
    eff = efficiency if efficiency is not None else analyse_efficiency(spec, steps)
    omega_in = spec.input_rpm * 2.0 * np.pi / 60.0
    torque_per_disc = spec.output_torque_Nm * 1000.0 / spec.disc_count
    length = spec.disc_thickness

    # ---- ring pin contact ---------------------------------------------------
    projected = 2.0 * spec.pin_radius * length          # mm^2 per pin
    peak_pv = 0.0
    peak_p = 0.0
    peak_v = 0.0
    for cs in sweep(spec, steps):
        f = cs.forces(torque_per_disc)                  # N
        live = f > 0
        if not live.any():
            continue
        p = f[live] / max(projected, 1e-9)              # MPa
        v = cs.sliding_speed[live] * omega_in / 1000.0  # m/s
        pv = float((p * v).max())
        if pv > peak_pv:
            peak_pv = pv
            j = int(np.argmax(p * v))
            peak_p, peak_v = float(p[j]), float(v[j])

    if spec.ring_pins_are_rollers:
        peak_pv *= _ROLLING_PV_FACTOR

    # ---- output pin contact -------------------------------------------------
    # the disc translates on a circle of radius E relative to the carrier
    v_out = spec.eccentricity * omega_in * (1.0 - 1.0 / spec.ratio) / 1000.0
    projected_out = spec.output_pin_diameter * length
    peak_out_f = 0.0
    for cs in sweep(spec, steps):
        ol = output_loads(spec, cs.phi, torque_per_disc)
        if ol.forces.size:
            peak_out_f = max(peak_out_f, float(ol.forces.max()))
    p_out = peak_out_f / max(projected_out, 1e-9)
    pv_out = p_out * v_out
    if spec.output_pins_are_rollers:
        pv_out *= _ROLLING_PV_FACTOR

    # ---- temperature --------------------------------------------------------
    # the softer of the two rubbing materials sets the limit at each interface
    limit_ring = min(spec.disc_mat.pv_limit_MPa_m_s, spec.pin_mat.pv_limit_MPa_m_s)
    limit_out = limit_ring
    area_m2 = spec.cooling_area_mm2 * 1e-6
    rise = eff.total_loss_W / max(CONVECTION_W_M2K * area_m2, 1e-9)
    temp = spec.ambient_temp_C + rise
    temp_limit = min(spec.disc_mat.max_service_temp_C,
                     spec.housing_mat.max_service_temp_C)

    return ThermalResult(
        pv_ring_MPa_m_s=peak_pv,
        pv_ring_limit_MPa_m_s=limit_ring,
        pv_output_MPa_m_s=pv_out,
        pv_output_limit_MPa_m_s=limit_out,
        ring_pressure_MPa=peak_p,
        ring_sliding_speed_m_s=peak_v,
        output_pressure_MPa=p_out,
        output_sliding_speed_m_s=v_out,
        loss_W=eff.total_loss_W,
        cooling_area_mm2=spec.cooling_area_mm2,
        temperature_rise_C=rise,
        temperature_C=temp,
        temperature_limit_C=temp_limit,
    )
