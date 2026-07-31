"""Geometric and manufacturability checks.

Errors block file export, warnings do not.  Each finding carries the numbers it
was based on so the report can show the margin, not just a verdict.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from . import profile as prof
from .spec import PROCESS_CLEARANCE, GearSpec, Process

__all__ = ["Finding", "Report", "Severity", "validate"]


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Finding:
    severity: Severity
    code: str
    message: str
    value: float | None = None
    limit: float | None = None

    def __str__(self) -> str:
        tail = ""
        if self.value is not None and self.limit is not None:
            tail = f"  [{self.value:.4g} vs limit {self.limit:.4g}]"
        return f"{self.severity.value.upper():7} {self.code}: {self.message}{tail}"


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def add(self, severity: Severity, code: str, message: str,
            value: float | None = None, limit: float | None = None) -> None:
        self.findings.append(Finding(severity, code, message, value, limit))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def __str__(self) -> str:
        return "\n".join(str(f) for f in self.findings) or "no findings"


def _candidate_pairs(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Segment index pairs whose bounding boxes overlap.

    Uniform-grid broad phase.  Two boxes that overlap share at least one point,
    and therefore at least one grid cell, so bucketing every segment into the
    cells its box covers finds every candidate without the all-pairs cost.  The
    cell is as wide as the longest segment, which keeps each box inside a 2x2
    block of cells.
    """
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    cell = float((hi - lo).max())
    if not cell > 0.0:
        return np.empty(0, np.int64), np.empty(0, np.int64)

    origin = lo.min(axis=0)
    c0 = np.floor((lo - origin) / cell).astype(np.int64)
    c1 = np.floor((hi - origin) / cell).astype(np.int64)
    stride = int(c1[:, 1].max()) + 2

    buckets: dict[int, list[int]] = {}
    for i, ((x0, y0), (x1, y1)) in enumerate(zip(c0, c1, strict=True)):
        for cx in range(x0, x1 + 1):
            base = cx * stride
            for cy in range(y0, y1 + 1):
                buckets.setdefault(base + cy, []).append(i)

    left: list[np.ndarray] = []
    right: list[np.ndarray] = []
    for members in buckets.values():
        if len(members) < 2:
            continue
        arr = np.asarray(members, dtype=np.int64)
        ii, jj = np.triu_indices(len(arr), k=1)
        left.append(arr[ii])
        right.append(arr[jj])
    if not left:
        return np.empty(0, np.int64), np.empty(0, np.int64)
    return np.concatenate(left), np.concatenate(right)


def _self_intersects(points: np.ndarray) -> bool:
    """True when the closed polyline crosses itself.

    Exhaustive over every pair that could possibly meet - the earlier version
    sampled every other segment as the query, which could step over a crossing.
    """
    n = len(points)
    if n < 6:
        return False
    a = points
    b = np.roll(points, -1, axis=0)
    i, j = _candidate_pairs(a, b)
    if not len(i):
        return False

    # Neighbours share an endpoint and are near collinear at this sampling
    # density, so they trip the exact test on rounding alone.
    d = np.abs(i - j)
    keep = (d > 2) & (d < n - 2)
    i, j = i[keep], j[keep]
    if not len(i):
        return False

    seg = b - a
    p, r = a[i], seg[i]
    q, s = a[j], seg[j]
    den = r[:, 0] * s[:, 1] - r[:, 1] * s[:, 0]
    ok = np.abs(den) > 1e-12
    qp = q - p
    safe = np.where(ok, den, 1.0)
    t = (qp[:, 0] * s[:, 1] - qp[:, 1] * s[:, 0]) / safe
    u = (qp[:, 0] * r[:, 1] - qp[:, 1] * r[:, 0]) / safe
    hit = ok & (t > 1e-9) & (t < 1 - 1e-9) & (u > 1e-9) & (u < 1 - 1e-9)
    return bool(hit.any())


def validate(spec: GearSpec) -> Report:
    """Run every check against ``spec``."""
    rep = Report()
    R, E, N = spec.pin_circle_radius, spec.eccentricity, spec.lobes
    Rr_eff, R_eff = spec.effective_Rr, spec.effective_R

    # ---------------------------------------------------------------- profile --
    if spec.K1 >= 1.0:
        rep.add(Severity.ERROR, "K1_TOO_HIGH",
                "Shortening coefficient K1 = E*pins/R must stay below 1 or the "
                "pin-centre locus develops cusps.", spec.K1, 1.0)
    elif spec.K1 > 0.75:
        rep.add(Severity.WARNING, "K1_HIGH",
                "K1 above 0.75 gives very pointed lobes and high contact stress.",
                spec.K1, 0.75)

    rho_c = prof.critical_radius(R_eff, E, N)
    if Rr_eff >= rho_c:
        rep.add(Severity.ERROR, "UNDERCUT",
                "Pin radius exceeds the locus curvature limit; the profile folds "
                "on itself. Reduce pin radius or eccentricity.", Rr_eff, rho_c)
    elif Rr_eff > 0.85 * rho_c:
        rep.add(Severity.WARNING, "UNDERCUT_MARGIN",
                "Pin radius is within 15% of the undercut limit.", Rr_eff, rho_c)

    # The equivalent contact radius is R_eq = Rr*(1 - Rr/rho_c), a parabola that
    # peaks at half the critical radius - the lowest-stress pin size for this R,
    # E and lobe count.
    best_pin = rho_c / 2.0
    if abs(spec.pin_radius - best_pin) > 0.35 * best_pin:
        rep.add(Severity.INFO, "PIN_RADIUS_SUGGESTION",
                f"Contact stress is lowest near a {best_pin:.2f} mm pin radius "
                f"for this pin circle, eccentricity and lobe count.",
                spec.pin_radius, best_pin)

    p = prof.profile_from_spec(spec, n=4000)
    if _self_intersects(p.points):
        rep.add(Severity.ERROR, "PROFILE_SELF_INTERSECT",
                "The generated outline crosses itself and cannot be manufactured.")

    # The clearance is *measured* off the manufactured profile rather than
    # assumed, which is the only way to catch an offset mode that shrinks the
    # gap instead of opening it.
    from .kinematics import mesh_gaps
    gaps = np.concatenate([mesh_gaps(spec, phi) for phi in (0.0, 0.7, 1.9)])
    worst_gap = float(gaps.min())
    if worst_gap < -1e-3:
        rep.add(Severity.ERROR, "PROFILE_INTERFERENCE",
                "The manufactured profile overlaps the ring pins at the nominal "
                "mesh position; the drive cannot be assembled, let alone turn.",
                worst_gap, 0.0)
    elif spec.profile_clearance > 0 and worst_gap < 0.25 * spec.profile_clearance:
        rep.add(Severity.WARNING, "CLEARANCE_NOT_DELIVERED",
                "The smallest real gap between disc and pins is far below the "
                "requested profile clearance.", worst_gap, spec.profile_clearance)

    # ---------------------------------------------------------------- ring pins --
    pitch = 2.0 * R * np.sin(np.pi / spec.pin_count)
    if pitch <= 2.0 * spec.pin_radius:
        rep.add(Severity.ERROR, "PIN_OVERLAP",
                "Adjacent ring pins intersect each other.", pitch, 2.0 * spec.pin_radius)
    elif pitch < 2.2 * spec.pin_radius:
        rep.add(Severity.WARNING, "PIN_SPACING",
                "Very little material between adjacent ring pins.",
                pitch, 2.2 * spec.pin_radius)

    # ------------------------------------------------------------ output holes --
    hole_r = spec.output_hole_diameter / 2.0
    bore_r = spec.center_bore_diameter / 2.0 + spec.hole_clearance / 2.0
    web_inner = spec.output_bolt_circle_radius - hole_r - bore_r
    if web_inner <= 0:
        rep.add(Severity.ERROR, "HOLE_HITS_BORE",
                "Output pin holes break into the central bearing bore.",
                web_inner, 0.0)
    elif web_inner < 2.0:
        rep.add(Severity.WARNING, "THIN_INNER_WEB",
                "Less than 2 mm of material between the output holes and the bore.",
                web_inner, 2.0)

    web_outer = p.root_radius - (spec.output_bolt_circle_radius + hole_r)
    if web_outer <= 0:
        rep.add(Severity.ERROR, "HOLE_BREAKS_RIM",
                "Output pin holes break through the cycloidal rim.", web_outer, 0.0)
    elif web_outer < 2.0:
        rep.add(Severity.WARNING, "THIN_OUTER_WEB",
                "Less than 2 mm of rim left outside the output holes.", web_outer, 2.0)

    gap = 2.0 * spec.output_bolt_circle_radius * np.sin(np.pi / spec.output_pin_count) - 2 * hole_r
    if gap <= 0:
        rep.add(Severity.ERROR, "OUTPUT_HOLES_OVERLAP",
                "Adjacent output pin holes overlap.", gap, 0.0)
    elif gap < 1.5:
        rep.add(Severity.WARNING, "OUTPUT_HOLE_SPACING",
                "Adjacent output holes leave a thin web.", gap, 1.5)

    if spec.center_bore_diameter <= spec.input_shaft_diameter + 2 * E:
        rep.add(Severity.WARNING, "ECCENTRIC_TIGHT",
                "Central bore leaves no room for an eccentric bearing over the shaft.",
                spec.center_bore_diameter, spec.input_shaft_diameter + 2 * E)

    # --------------------------------------------------------------- machining --
    kappa = np.abs(p.curvature())
    rho_tool = 1.0 / max(kappa.max(), 1e-12)
    if spec.process in (Process.CNC, Process.EDM):
        rep.add(Severity.INFO, "TOOL_RADIUS",
                f"Smallest concave radius on the profile is {rho_tool:.3f} mm; the "
                f"cutter must be smaller than {2 * rho_tool:.3f} mm diameter.",
                rho_tool)

    guide_prof, guide_hole = PROCESS_CLEARANCE[spec.process]
    if spec.profile_clearance < guide_prof * 0.5:
        rep.add(Severity.WARNING, "CLEARANCE_DEFICIT",
                f"Profile clearance is well below the {spec.process.value} guide "
                f"of {guide_prof} mm; the drive will likely bind.",
                spec.profile_clearance, guide_prof)
    if spec.hole_clearance < guide_hole * 0.5:
        rep.add(Severity.WARNING, "HOLE_CLEARANCE_DEFICIT",
                f"Hole clearance is below the {spec.process.value} guide of "
                f"{guide_hole} mm.", spec.hole_clearance, guide_hole)

    # ------------------------------------------------------------- disc stack --
    if spec.disc_count > 1 and not spec.discs_are_identical:
        rep.add(Severity.INFO, "DISCS_DIFFER",
                f"The {spec.disc_count} discs are different parts: each hole "
                f"pattern is turned back against its lobes so all discs share the "
                f"output carrier's rotation. They would only be interchangeable "
                f"with {2 * N} output pins.",
                float(spec.output_pin_count), float(2 * N))

    # ---------------------------------------------------------------- dynamics --
    if spec.disc_count == 1 and spec.input_rpm > 500:
        rep.add(Severity.WARNING, "SINGLE_DISC_UNBALANCE",
                "A single disc leaves an unbalanced rotating mass; use two discs "
                "at 180 deg above 500 rpm.", spec.input_rpm, 500.0)

    # --------------------------------------------------------- pressure angle --
    # Evaluated at the most heavily loaded contact.  Contacts whose normal passes
    # near the disc centre have a ~90 deg angle but carry no torque, so taking a
    # plain maximum over all pins would always report 90.
    from .kinematics import sweep
    worst = 0.0
    for cs in sweep(spec):
        f = cs.forces(1.0)
        if not (f > 0).any():
            continue
        j = int(np.argmax(f))
        centre = np.array([E * np.cos(cs.phi), -E * np.sin(cs.phi)])
        r = float(np.hypot(*(cs.points[j] - centre)))
        cosa = np.clip(abs(cs.moment_arms[j]) / max(r, 1e-9), 0.0, 1.0)
        worst = max(worst, float(np.degrees(np.arccos(cosa))))
    if worst > 55.0:
        rep.add(Severity.WARNING, "PRESSURE_ANGLE",
                "Peak pressure angle is steep; radial load on the pins will be high.",
                worst, 55.0)
    else:
        rep.add(Severity.INFO, "PRESSURE_ANGLE", "Peak pressure angle.", worst, 55.0)

    return rep
