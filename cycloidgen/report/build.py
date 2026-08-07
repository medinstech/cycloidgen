"""JSON and PDF reports for a finished design."""
from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path

from matplotlib.figure import Figure
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    CondPageBreak,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .. import __version__
from ..analysis import DesignAnalysis
from ..core.validate import Severity
from . import plots

__all__ = ["report_dict", "write_json", "write_pdf"]

_INK = colors.HexColor("#0b0b0b")
_INK2 = colors.HexColor("#52514e")
_GRID = colors.HexColor("#e6e5e1")
_SEV = {
    Severity.ERROR: colors.HexColor("#e34948"),
    Severity.WARNING: colors.HexColor("#eda100"),
    Severity.INFO: colors.HexColor("#52514e"),
}


def _bom_items(a: DesignAnalysis):
    """Imported lazily: ``export`` imports ``report``, so the other way round
    at module level would close the loop."""
    from ..export.bom import bom_items
    return bom_items(a)


def report_dict(a: DesignAnalysis) -> dict:
    """Everything about the design as plain JSON-safe data."""
    s = a.spec
    return {
        "generator": "cycloidgen",
        # Which build produced these numbers.  A report outlives the session
        # that made it, and every quantity below is a model's answer rather
        # than a measurement - so the model has to be named alongside them.
        "version": __version__,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "spec": json.loads(s.model_dump_json()),
        "derived": {
            "ratio": s.ratio,
            "pin_count": s.pin_count,
            "K1": s.K1,
            "output_hole_diameter_mm": s.output_hole_diameter,
            "disc_outer_radius_mm": s.disc_outer_radius,
            "housing_outer_radius_mm": s.housing_outer_radius,
            "stack_height_mm": s.stack_height,
            "output_rpm": s.output_rpm,
            "effective_R_mm": s.effective_R,
            "effective_Rr_mm": s.effective_Rr,
            "cam_diameter_mm": s.cam_diameter,
        },
        "contact": {
            "max_pin_force_N": a.contact.max_pin_force_N,
            "max_pin_pressure_MPa": a.contact.max_pin_pressure_MPa,
            "allowable_MPa": a.contact.pin_pressure_allow_MPa,
            "pin_safety_factor": a.contact.pin_safety_factor,
            "min_equivalent_radius_mm": a.contact.min_R_eq_mm,
            "pins_in_contact": a.contact.pins_in_contact,
            "max_output_pin_force_N": a.contact.max_output_force_N,
            "max_output_pressure_MPa": a.contact.max_output_pressure_MPa,
            "output_safety_factor": a.contact.output_safety_factor,
            "eccentric_bearing_load_N": a.contact.eccentric_bearing_load_N,
            "radial_load_ripple_pct": a.contact.radial_load_ripple_pct,
            "torque_capacity_Nm": a.torque_capacity_Nm,
            "torque_capacity_with_clearance_Nm": a.torque_capacity_with_clearance_Nm,
            "pin_safety_factor_with_clearance": a.pin_safety_factor_with_clearance,
        },
        "stiffness": {
            "torsional_stiffness_Nm_per_arcmin": a.stiffness.stiffness_Nm_per_arcmin,
            "contact_only_Nm_per_arcmin": a.stiffness.contact_only_Nm_per_arcmin,
            "structure_Nm_per_arcmin": a.stiffness.structure_Nm_per_arcmin,
            "structure": {
                "ring_seat_Nm_per_arcmin":
                    a.stiffness.structure.ring_seat_Nm_per_arcmin,
                "housing_Nm_per_arcmin": a.stiffness.structure.housing_Nm_per_arcmin,
                "disc_body_Nm_per_arcmin":
                    a.stiffness.structure.disc_body_Nm_per_arcmin,
                "output_pin_Nm_per_arcmin":
                    a.stiffness.structure.output_pin_Nm_per_arcmin,
                "carrier_plate_Nm_per_arcmin":
                    a.stiffness.structure.carrier_plate_Nm_per_arcmin,
                "input_shaft_Nm_per_arcmin":
                    a.stiffness.structure.input_shaft_Nm_per_arcmin,
            },
            "ring_stage_Nm_per_arcmin": a.stiffness.ring_stage_Nm_per_arcmin,
            "output_stage_Nm_per_arcmin": a.stiffness.output_stage_Nm_per_arcmin,
            "windup_arcmin": a.stiffness.windup_arcmin,
            "lost_motion_arcmin": a.stiffness.lost_motion_arcmin,
            "lost_motion_ring_arcmin": a.stiffness.lost_motion_ring_arcmin,
            "lost_motion_output_arcmin": a.stiffness.lost_motion_output_arcmin,
            "backlash_total_arcmin": a.stiffness.backlash_total_arcmin,
            "pins_engaged": a.stiffness.pins_engaged,
            "pins_engaged_ideal": a.stiffness.pins_engaged_ideal,
            "load_concentration": a.stiffness.load_concentration,
        },
        "position_tolerance": {
            "tolerance_mm": a.spec.position_tolerance,
            "rings_sampled": a.stiffness.rings_sampled,
            "stiffness_p10_Nm_per_arcmin": a.stiffness.stiffness_p10_Nm_per_arcmin,
            "load_concentration_p90": a.stiffness.load_concentration_p90,
            "lost_motion_p90_arcmin": a.stiffness.lost_motion_p90_arcmin,
            "transmission_error_worst_arcmin":
                a.transmission_error.worst_ring_arcmin,
            "interference_mm": a.stiffness.position_interference_mm,
        },
        "transmission_error": {
            "peak_to_peak_arcmin": a.transmission_error.peak_to_peak_arcmin,
            "rms_arcmin": a.transmission_error.rms_arcmin,
            "ring_arcmin": a.transmission_error.ring_arcmin,
            "output_arcmin": a.transmission_error.output_arcmin,
            "ring_period_deg": a.transmission_error.ring_period_deg,
            "output_period_deg": a.transmission_error.output_period_deg,
        },
        "thermal": {
            "pv_ring_MPa_m_s": a.thermal.pv_ring_MPa_m_s,
            "pv_ring_limit_MPa_m_s": a.thermal.pv_ring_limit_MPa_m_s,
            "pv_output_MPa_m_s": a.thermal.pv_output_MPa_m_s,
            "pv_output_limit_MPa_m_s": a.thermal.pv_output_limit_MPa_m_s,
            "ring_sliding_speed_m_s": a.thermal.ring_sliding_speed_m_s,
            "loss_W": a.thermal.loss_W,
            "cooling_area_mm2": a.thermal.cooling_area_mm2,
            "temperature_rise_C": a.thermal.temperature_rise_C,
            "temperature_C": a.thermal.temperature_C,
            "temperature_limit_C": a.thermal.temperature_limit_C,
        },
        "lubrication": {
            "lubricant": a.lubrication.lubricant,
            "temperature_C": a.lubrication.temperature_C,
            "viscosity_cSt": a.lubrication.viscosity_cSt,
            "roughness_um": a.spec.roughness_um,
            "contacts": [
                # ``null`` rather than infinity for a contact that does not
                # slide: there is no lambda there, and JSON's infinity is a
                # non-standard extension half the parsers downstream reject.
                {"name": c.name, "slides": c.slides, "regime": c.regime,
                 "film_um": c.film_um, "composite_roughness_um": c.roughness_um,
                 "lambda_ratio": c.lambda_ratio if c.slides else None, "mu": c.mu,
                 "entrainment_m_s": c.entrainment_m_s,
                 "sliding_speed_m_s": c.sliding_speed_m_s}
                for c in a.lubrication.contacts
            ],
        },
        "mass": {
            "disc_mass_g": a.mass.disc_mass_g,
            "disc_volume_cm3": a.mass.disc_volume_cm3,
            "total_mass_g": a.mass.total_mass_g,
            "housing_mass_g": a.mass.housing_mass_g,
            "plates_mass_g": a.mass.plates_mass_g,
            "pins_mass_g": a.mass.pins_mass_g,
            "shaft_mass_g": a.mass.shaft_mass_g,
            "flange_mass_g": a.mass.flange_mass_g,
            "disc_inertia_kg_mm2": a.mass.disc_inertia_kg_mm2,
            "reflected_inertia_kg_mm2": a.mass.reflected_inertia_kg_mm2,
            "unbalance_force_N": a.mass.unbalance_force_N,
            "unbalance_couple_Nmm": a.mass.unbalance_couple_Nmm,
            "web_shear_MPa": a.mass.web_shear_MPa,
            "web_shear_allow_MPa": a.mass.web_shear_allow_MPa,
            "min_web_mm": a.mass.min_web_mm,
            "power_density_Nm_per_kg": a.power_density_Nm_per_kg,
        },
        "bom": [
            {"part": i.part, "quantity": i.quantity, "material": i.material,
             "size": i.size, "mass_each_g": i.mass_each_g,
             "mass_total_g": i.mass_total_g, "source": i.source, "note": i.note}
            for i in _bom_items(a)
        ],
        "efficiency": {
            "efficiency": a.efficiency.efficiency,
            "input_torque_Nm": a.efficiency.input_torque_Nm,
            "input_power_W": a.efficiency.input_power_W,
            "output_power_W": a.efficiency.output_power_W,
            "loss_ring_pins_W": a.efficiency.loss_ring_pins_W,
            "loss_output_pins_W": a.efficiency.loss_output_pins_W,
            "loss_bearings_W": a.efficiency.loss_bearings_W,
        },
        "bearings": [
            {
                "role": b.role,
                "count": b.count,
                "carries": b.carries,
                "seat": b.seat,
                "designation": b.bearing.designation if b.bearing else None,
                "bore_mm": b.bearing.bore if b.bearing else None,
                "outer_mm": b.bearing.outer if b.bearing else None,
                "width_mm": b.bearing.width if b.bearing else None,
                "load_N": b.load_N,
                "speed_rpm": b.speed_rpm,
                "L10_hours": None if b.life_hours == float("inf") else b.life_hours,
                "note": b.note,
            }
            for b in a.bearings
        ],
        "findings": [
            {"severity": f.severity.value, "code": f.code, "message": f.message,
             "value": f.value, "limit": f.limit}
            for f in a.report.findings
        ],
    }


def write_json(a: DesignAnalysis, path: str | Path) -> Path:
    path = Path(path)
    path.write_text(json.dumps(report_dict(a), indent=2), encoding="utf-8")
    return path


def _letterhead():
    """The wordmark above the title, sized off its own aspect ratio.

    Falls back to nothing if the asset is missing: a report that refuses to
    generate because a logo moved would be a poor trade.
    """
    from reportlab.platypus import Spacer

    try:
        from ..ui.branding import asset
        path = asset("wordmark-blue.png")
    except Exception:
        return Spacer(1, 0)

    from PIL import Image as PILImage
    with PILImage.open(path) as im:
        aspect = im.height / im.width
    width = 32 * mm
    logo = Image(str(path), width=width, height=width * aspect)
    logo.hAlign = "LEFT"
    return logo


def _fig_png(fig, width_mm: float) -> Image:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, facecolor=fig.get_facecolor())
    buf.seek(0)
    w_in, h_in = fig.get_size_inches()
    w = width_mm * mm
    return Image(buf, width=w, height=w * h_in / w_in)


def _table(rows: list[list[str]], widths: list[float], header: bool = True) -> Table:
    t = Table(rows, colWidths=widths, hAlign="LEFT")
    style = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, -1), _INK2),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, _GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style += [("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                  ("TEXTCOLOR", (0, 0), (-1, 0), _INK),
                  ("LINEBELOW", (0, 0), (-1, 0), 0.8, _INK2)]
    t.setStyle(TableStyle(style))
    return t


def write_pdf(a: DesignAnalysis, path: str | Path) -> Path:
    """Full design dossier: drawing, parameters, checks, loads, bearings.

    Always rendered on the light surface - it is a print document, whatever
    theme the application happens to be running in.
    """
    with plots.light_theme():
        return _write_pdf(a, path)


def _write_pdf(a: DesignAnalysis, path: str | Path) -> Path:
    path = Path(path)
    s = a.spec
    doc = SimpleDocTemplate(str(path), pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"Cycloidal drive {s.ratio}:1")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=16, textColor=_INK,
                        spaceAfter=2, alignment=TA_LEFT)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=11, textColor=_INK,
                        spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("body", parent=ss["BodyText"], fontSize=8.5,
                          textColor=_INK2, leading=11)

    story: list = [
        _letterhead(),
        Paragraph(f"Cycloidal drive {s.ratio}:1", h1),
        Paragraph(
            f"{s.lobes} lobes / {s.pin_count} ring pins &middot; "
            f"{2 * s.housing_outer_radius:.1f} mm outside diameter &middot; "
            f"{s.disc_count} disc(s) &middot; {s.process.value} &middot; "
            f"generated {datetime.now():%Y-%m-%d %H:%M} "
            f"by cycloidgen {__version__}", body),
        Spacer(1, 6),
        # The drawing and the assembly side by side.  They answer different
        # questions - what the geometry is, and what the thing looks like - and
        # a reader who has never seen a cycloidal drive needs the second one
        # before the first one means anything.
        Table([[_fig_png(plots.profile_figure(s, Figure(figsize=(5.4, 5.4), dpi=110)),
                         83),
                _fig_png(plots.assembly_figure(s, Figure(figsize=(5.4, 5.4), dpi=110)),
                         83)]],
              colWidths=[86 * mm, 86 * mm], hAlign="LEFT"),
    ]

    # --- verdict -------------------------------------------------------------
    verdict = ("READY TO EXPORT" if a.report.ok else "BLOCKED - fix the errors below")
    story += [
        Paragraph("Verdict", h2),
        Paragraph(f"<b>{verdict}</b> &mdash; {len(a.report.errors)} error(s), "
                  f"{len(a.report.warnings)} warning(s). Predicted efficiency "
                  f"{100 * a.efficiency.efficiency:.1f}%, torque capacity "
                  f"{a.torque_capacity_with_clearance_Nm:.2f} Nm at the output "
                  f"(clearance-derated from {a.torque_capacity_Nm:.2f} Nm), "
                  f"{a.stiffness.lost_motion_arcmin:.0f} arcmin of backlash, "
                  f"{a.mass.total_mass_g:.0f} g assembled, running at "
                  f"{a.thermal.temperature_C:.0f} C in still air.", body),
    ]

    # --- parameters ----------------------------------------------------------
    story += [Paragraph("Geometry", h2)]
    geo = [
        ["Parameter", "Value", "Parameter", "Value"],
        ["Pin circle radius R", f"{s.pin_circle_radius:g} mm",
         "Ratio", f"{s.ratio}:1"],
        ["Pin radius Rr", f"{s.pin_radius:g} mm",
         "Lobes / pins", f"{s.lobes} / {s.pin_count}"],
        ["Eccentricity E", f"{s.eccentricity:g} mm", "K1", f"{s.K1:.4f}"],
        ["Disc thickness", f"{s.disc_thickness:g} mm",
         "Disc count / gap", f"{s.disc_count} / {s.disc_gap:g} mm"],
        ["Central bore", f"{s.center_bore_diameter:g} mm",
         "Eccentric cam OD", f"{s.cam_diameter:g} mm"],
        ["Output pins", f"{s.output_pin_count} x {s.output_pin_diameter:g} mm",
         "Output hole dia", f"{s.output_hole_diameter:.3f} mm"],
        ["Output bolt circle", f"{s.output_bolt_circle_radius:g} mm",
         "Disc OD", f"{2 * s.disc_outer_radius:.2f} mm"],
        ["Profile clearance", f"{s.profile_clearance:g} mm ({s.offset_mode.value})",
         "Hole clearance", f"{s.hole_clearance:g} mm"],
        ["Cut with R / Rr", f"{s.effective_R:g} / {s.effective_Rr:g} mm",
         "Stack height", f"{s.stack_height:g} mm"],
        ["Disc material", s.disc_material, "Pin material", s.pin_material],
        ["Input speed", f"{s.input_rpm:g} rpm", "Output speed",
         f"{s.output_rpm:.1f} rpm"],
    ]
    story += [_table(geo, [42 * mm, 36 * mm, 42 * mm, 36 * mm])]

    # --- findings ------------------------------------------------------------
    story += [Paragraph("Checks", h2)]
    if a.report.findings:
        rows = [["Severity", "Code", "Detail", "Value", "Limit"]]
        for f in a.report.findings:
            rows.append([f.severity.value.upper(), f.code,
                         Paragraph(f.message, body),
                         f"{f.value:.4g}" if f.value is not None else "",
                         f"{f.limit:.4g}" if f.limit is not None else ""])
        t = _table(rows, [17 * mm, 33 * mm, 76 * mm, 17 * mm, 17 * mm])
        for i, f in enumerate(a.report.findings, start=1):
            t.setStyle(TableStyle([("TEXTCOLOR", (0, i), (0, i), _SEV[f.severity]),
                                   ("FONTNAME", (0, i), (0, i), "Helvetica-Bold")]))
        story += [t]
    else:
        story += [Paragraph("No findings.", body)]

    # --- loads ---------------------------------------------------------------
    c = a.contact
    story += [
        CondPageBreak(120 * mm),
        Paragraph("Loads and contact stress", h2),
        Paragraph(
            "Rigid-disc, linear-contact load sharing: force at a contact is taken "
            "proportional to its moment arm and only the pushing half carries load. "
            "Clearance is not modelled, so a real drive concentrates load on fewer "
            "pins. Use these as sizing estimates, not as a certification.", body),
        Spacer(1, 4),
        _table([
            ["Quantity", "Value", "Quantity", "Value"],
            ["Peak ring pin force", f"{c.max_pin_force_N:.1f} N",
             "Pins carrying load", f"{c.pins_in_contact} of {s.pin_count}"],
            ["Peak contact pressure", f"{c.max_pin_pressure_MPa:.1f} MPa",
             "Allowable", f"{c.pin_pressure_allow_MPa:.0f} MPa"],
            ["Safety factor (ring)", f"{c.pin_safety_factor:.2f}",
             "Min equivalent radius", f"{c.min_R_eq_mm:.3f} mm"],
            ["Peak output pin force", f"{c.max_output_force_N:.1f} N",
             "Output pin pressure", f"{c.max_output_pressure_MPa:.1f} MPa"],
            ["Safety factor (output)", f"{c.output_safety_factor:.2f}",
             "Eccentric bearing load", f"{c.eccentric_bearing_load_N:.1f} N"],
            ["Radial load ripple", f"{c.radial_load_ripple_pct:.1f} %",
             "Torque capacity", f"{a.torque_capacity_Nm:.2f} Nm"],
        ], [42 * mm, 36 * mm, 42 * mm, 36 * mm]),
        Spacer(1, 6),
        _fig_png(plots.force_figure(s), 155),
    ]

    # --- efficiency ----------------------------------------------------------
    e = a.efficiency
    story += [
        CondPageBreak(90 * mm),
        Paragraph("Efficiency", h2),
        _fig_png(plots.loss_figure(a), 155),
        Spacer(1, 4),
        _table([
            ["Quantity", "Value", "Quantity", "Value"],
            ["Efficiency", f"{100 * e.efficiency:.1f} %",
             "Input torque", f"{e.input_torque_Nm:.3f} Nm"],
            ["Input power", f"{e.input_power_W:.2f} W",
             "Output power", f"{e.output_power_W:.2f} W"],
            ["Ring pins", "rolling" if s.ring_pins_are_rollers else "fixed (sliding)",
             "Output pins", "rolling" if s.output_pins_are_rollers else "fixed (sliding)"],
        ], [42 * mm, 36 * mm, 42 * mm, 36 * mm]),
    ]

    # --- stiffness and backlash ----------------------------------------------
    st, te = a.stiffness, a.transmission_error
    story += [
        CondPageBreak(80 * mm),
        Paragraph("Stiffness, backlash and what clearance does", h2),
        Paragraph(
            "Hold the input still and twist the output: the ring contacts, the "
            "output pins and every part they are mounted in act as springs in "
            "series. Unlike the load table above, this model does see clearance - "
            "the gap at each pin is measured off the manufactured profile - "
            "which is where the lost motion and the load concentration come from.",
            body),
        Spacer(1, 4),
        _table([
            ["Quantity", "Value", "Quantity", "Value"],
            ["Torsional stiffness", f"{st.stiffness_Nm_per_arcmin:.3f} Nm/arcmin",
             "Wind-up at rated torque", f"{st.windup_arcmin:.2f} arcmin"],
            ["Mesh contacts", f"{st.contact_only_Nm_per_arcmin:.3f} Nm/arcmin",
             "Structure around them",
             f"{st.structure_Nm_per_arcmin:.3f} Nm/arcmin"],
            ["Ring stage", f"{st.ring_stage_Nm_per_arcmin:.3f} Nm/arcmin",
             "Output stage", f"{st.output_stage_Nm_per_arcmin:.3f} Nm/arcmin"],
            ["Lost motion (profile)", f"{st.lost_motion_ring_arcmin:.1f} arcmin",
             "Lost motion (holes)", f"{st.lost_motion_output_arcmin:.1f} arcmin"],
            ["Total backlash", f"{st.backlash_total_arcmin:.1f} arcmin",
             "Pins actually carrying",
             f"{st.pins_engaged:.1f} of {st.pins_engaged_ideal:.0f}"],
            ["Load concentration", f"{st.load_concentration:.2f} x",
             "Capacity after derating",
             f"{a.torque_capacity_with_clearance_Nm:.2f} Nm"],
        ], [42 * mm, 36 * mm, 42 * mm, 36 * mm]),
        Spacer(1, 6),
        Paragraph(
            "Lost motion is the play before the output moves. <b>Transmission "
            "error</b> is what the output does once it is moving: turning the "
            "drive hands load from one contact to the next, and both the gap to "
            "be taken up and the deflection under load change at the handover, "
            "so the output leads and lags the exact ratio by the band below. "
            "Each stage is swept over its own period - they are different, and "
            "the output stage's is the longer of the two. Pin position error, "
            "profile error and runout are not modelled, so this is the drive's "
            "own share of the error and not the whole of it.",
            body),
        Spacer(1, 4),
        _table([
            ["Quantity", "Value", "Quantity", "Value"],
            ["Transmission error", f"{te.peak_to_peak_arcmin:.3f} arcmin p-p",
             "rms", f"{te.rms_arcmin:.3f} arcmin"],
            ["From the output pins", f"{te.output_arcmin:.3f} arcmin "
             f"/ {te.output_period_deg:.0f} deg",
             "From the ring mesh", f"{te.ring_arcmin:.3f} arcmin "
             f"/ {te.ring_period_deg:.0f} deg"],
        ], [42 * mm, 36 * mm, 42 * mm, 36 * mm]),
        Spacer(1, 6),
        Paragraph(
            "What the mesh is mounted in, part by part. These used to be taken "
            "as rigid; they are not, and on a printed drive they are the softer "
            "half. The carrier pins stand off the plate as cantilevers, which is "
            "what the modelled carrier is - a second plate supporting their far "
            "ends would be worth roughly an order of magnitude on that line.",
            body),
        Spacer(1, 4),
        _table([["Part", "Nm/arcmin", "Part", "Nm/arcmin"]]
               + [[a_name, f"{a_k:.2f}", b_name, f"{b_k:.2f}"]
                  for (a_name, a_k), (b_name, b_k)
                  in zip(st.structure.items[0::2], st.structure.items[1::2],
                         strict=True)],
               [42 * mm, 36 * mm, 42 * mm, 36 * mm]),
    ]

    # --- what the pin position tolerance costs -------------------------------
    if st.tolerance_was_sampled:
        story += [
            Spacer(1, 6),
            Paragraph(
                f"Everything above places the pins exactly. At the "
                f"{s.position_tolerance:.3f} mm true position entered, they are "
                f"not: the load sharing was solved over {st.rings_sampled} rings "
                f"drawn from that tolerance zone, and the spread below is what "
                f"came back. The middle ring is what to expect to build; the "
                f"tail is what to be able to live with.",
                body),
            Spacer(1, 4),
            _table([
                ["Quantity", "Middle ring", "Quantity", "Bad ring"],
                ["Stiffness", f"{st.stiffness_Nm_per_arcmin:.3f} Nm/arcmin",
                 "Soft decile", f"{st.stiffness_p10_Nm_per_arcmin:.3f} Nm/arcmin"],
                ["Load concentration", f"{st.load_concentration:.2f} x",
                 "Ninth decile", f"{st.load_concentration_p90:.2f} x"],
                ["Lost motion", f"{st.lost_motion_arcmin:.1f} arcmin",
                 "Ninth decile", f"{st.lost_motion_p90_arcmin:.1f} arcmin"],
                ["Transmission error", f"{te.peak_to_peak_arcmin:.3f} arcmin",
                 "Worst of batch", f"{te.worst_ring_arcmin:.3f} arcmin"],
            ], [42 * mm, 36 * mm, 42 * mm, 36 * mm]),
        ]
        if st.position_interference_mm > 0:
            story += [
                Spacer(1, 4),
                Paragraph(
                    f"<b>Read those as optimistic.</b> Some of those rings put a "
                    f"pin {1000 * st.position_interference_mm:.0f} um into the "
                    f"disc - the tolerance has eaten the clearance - and a "
                    f"single-rotation model reads an interfering pin as one that "
                    f"just touches. A drive built that way binds.",
                    body),
            ]

    # --- sliding duty and heat -----------------------------------------------
    th = a.thermal
    story += [
        CondPageBreak(70 * mm),
        Paragraph("Sliding duty and temperature", h2),
        Paragraph(
            "PV is the wear limit, and it is usually what finishes a printed "
            "drive - not stress. It is quoted on the projected-area convention "
            "the published limits use, which is not the Hertzian peak above. "
            "The temperature is a lumped still-air estimate with no conduction "
            "into the mount, so it is the pessimistic case.", body),
        Spacer(1, 4),
        _table([
            ["Quantity", "Value", "Quantity", "Value"],
            ["Ring pin PV", f"{th.pv_ring_MPa_m_s:.3f} MPa m/s",
             "Limit", f"{th.pv_ring_limit_MPa_m_s:.3f} ({th.ring_pv_margin:.2f}x)"],
            ["Ring sliding speed", f"{th.ring_sliding_speed_m_s:.3f} m/s",
             "Ring pressure", f"{th.ring_pressure_MPa:.2f} MPa"],
            ["Output pin PV", f"{th.pv_output_MPa_m_s:.3f} MPa m/s",
             "Limit", f"{th.pv_output_limit_MPa_m_s:.3f} ({th.output_pv_margin:.2f}x)"],
            ["Power lost", f"{th.loss_W:.2f} W",
             "Cooling area", f"{th.cooling_area_mm2 / 100:.0f} cm2"],
            ["Temperature rise", f"{th.temperature_rise_C:.0f} C",
             "Steady temperature",
             f"{th.temperature_C:.0f} C of {th.temperature_limit_C:.0f} C"],
        ], [42 * mm, 36 * mm, 42 * mm, 36 * mm]),
    ]

    # --- what is between the surfaces ----------------------------------------
    lb = a.lubrication
    rows = [["Contact", "Regime", "Film", "Roughness", "Lambda", "mu"]]
    for c in lb.contacts:
        if not c.slides:
            rows.append([c.name, "rolling", "-", "-", "-", "-"])
            continue
        rows.append([c.name, c.regime,
                     f"{1000 * c.film_um:.0f} nm" if c.film_um else "none",
                     f"{1000 * c.roughness_um:.0f} nm",
                     f"{c.lambda_ratio:.2f}", f"{c.mu:.3f}"])
    story += [
        CondPageBreak(60 * mm),
        Paragraph("Lubrication regime", h2),
        Paragraph(
            f"{lb.lubricant} at the running temperature of "
            f"{lb.temperature_C:.0f} C"
            + (f", where it is {lb.viscosity_cSt:.0f} cSt. " if lb.viscosity_cSt
               else ". ")
            + "Lambda is the minimum film thickness over the composite "
              "roughness of the two surfaces, and it is the number that decides "
              "whether they touch: above 3 they are separated, below 1 the peaks "
              "carry the load and the friction coefficient belongs to the "
              "additives rather than to the oil. Film thickness is "
              "Dowson-Hamrock for a line contact, entrained at half the sliding "
              "speed because a fixed pin does not move - which is most of why a "
              "rolling pin is worth having.", body),
        Spacer(1, 4),
        _table(rows, [46 * mm, 22 * mm, 22 * mm, 24 * mm, 20 * mm, 22 * mm]),
    ]

    # --- mass, inertia, structure --------------------------------------------
    ms = a.mass
    story += [
        CondPageBreak(70 * mm),
        Paragraph("Mass, inertia and disc structure", h2),
        _table([
            ["Quantity", "Value", "Quantity", "Value"],
            ["Assembled mass", f"{ms.total_mass_g:.0f} g",
             "Power density", f"{a.power_density_Nm_per_kg:.2f} Nm/kg"],
            ["Disc", f"{ms.disc_mass_g:.1f} g x{s.disc_count}",
             "Barrel / end plates",
             f"{ms.housing_mass_g:.0f} / {ms.plates_mass_g:.0f} g"],
            ["Pins", f"{ms.pins_mass_g:.0f} g",
             "Shaft / flange",
             f"{ms.shaft_mass_g:.0f} / {ms.flange_mass_g:.0f} g"],
            ["Disc inertia", f"{ms.disc_inertia_kg_mm2:.3f} kg mm2",
             "Reflected at input", f"{ms.reflected_inertia_kg_mm2:.4f} kg mm2"],
            ["Residual unbalance", f"{ms.unbalance_force_N:.1f} N",
             "Unbalance couple", f"{ms.unbalance_couple_Nmm:.1f} Nmm"],
            ["Thinnest disc web", f"{ms.min_web_mm:.2f} mm",
             "Web shear",
             f"{ms.web_shear_MPa:.2f} / {ms.web_shear_allow_MPa:.0f} MPa "
             f"({ms.web_safety_factor:.1f}x)"],
        ], [42 * mm, 36 * mm, 42 * mm, 36 * mm]),
    ]

    # --- bill of materials ----------------------------------------------------
    story += [CondPageBreak(70 * mm), Paragraph("Bill of materials", h2)]
    rows = [["Part", "Qty", "Material", "Size", "Mass", "Note"]]
    for item in _bom_items(a):
        rows.append([
            Paragraph(item.part, body), str(item.quantity),
            Paragraph(item.material, body), Paragraph(item.size, body),
            f"{item.mass_total_g:.1f} g" if item.mass_each_g else "-",
            Paragraph(item.note, body)])
    story += [_table(rows, [30 * mm, 9 * mm, 26 * mm, 42 * mm, 16 * mm, 37 * mm]),
              Spacer(1, 4),
              Paragraph(f"Assembled mass {ms.total_mass_g:.0f} g. Also written as "
                        f"<b>bom.csv</b> next to this report.", body)]

    # --- bearings ------------------------------------------------------------
    story += [CondPageBreak(70 * mm), Paragraph("Bearings", h2)]
    rows = [["Role and seat", "Qty", "Suggested", "Size", "Load", "Speed", "L10"]]
    for b in a.bearings:
        size = (f"{b.bearing.bore:g}x{b.bearing.outer:g}x{b.bearing.width:g}"
                if b.bearing else "-")
        life = ("-" if b.life_hours == float("inf")
                else f"{b.life_hours:,.0f} h" if b.life_hours else "n/a")
        # The seat under the role, not a column of its own: where a bearing goes
        # is a sentence, and a table that only names the part leaves the builder
        # to guess it - which is the question this whole page exists to answer.
        rows.append([Paragraph(f"<b>{b.role}</b><br/>{b.seat or b.note}", body),
                     f"{b.count}" if b.count else "-",
                     b.bearing.designation if b.bearing else "-",
                     size, f"{b.load_N:.0f} N", f"{b.speed_rpm:.0f} rpm", life])
    story += [_table(rows, [48 * mm, 10 * mm, 20 * mm, 24 * mm, 18 * mm, 20 * mm, 20 * mm]),
              Spacer(1, 4),
              Paragraph("Catalogue ratings are nominal metric-series values for "
                        "first-pass selection; confirm against the manufacturer's "
                        "data before ordering.", body)]

    # --- assembly notes ------------------------------------------------------
    notes = [
        f"Output pin holes are {s.output_hole_diameter:.3f} mm: the pin diameter "
        f"plus twice the eccentricity plus {s.hole_clearance:g} mm clearance. "
        f"The disc rotates {360 / s.lobes:.3f} deg backwards per input revolution."
    ]
    if s.disc_count == 1:
        notes.append("A single disc leaves an unbalanced rotating mass; two discs "
                     "at 180 deg cancel it.")
    else:
        phases = ", ".join(f"{360 * i / s.disc_count:.0f}"
                           for i in range(s.disc_count))
        notes.append(
            f"Mount the {s.disc_count} discs at {phases} deg crank phase. Each disc "
            f"is rotated {360 / s.disc_count / s.lobes:.3f} deg further on its own "
            f"axis than the one before it, to stay meshed with the ring.")
        if s.discs_are_identical:
            notes.append(
                f"With {s.output_pin_count} output pins that rotation is a whole "
                f"hole pitch, so all {s.disc_count} discs are the same part.")
        else:
            offsets = ", ".join(f"{-360 * ph / (2 * 3.141592653589793):.3f}"
                                for ph in s.disc_hole_phases)
            notes.append(
                f"<b>The discs are different parts.</b> Every disc must share the "
                f"output carrier's rotation, so each one's hole pattern is turned "
                f"back against its lobes by {offsets} deg respectively. Exported as "
                f"separate files disc_1 .. disc_{s.disc_count} - do not substitute "
                f"one for another. They would only be interchangeable with "
                f"{2 * s.lobes} output pins.")

    story += [CondPageBreak(45 * mm), Paragraph("Assembly notes", h2)]
    story += [Paragraph(n, body) for n in notes]

    steps = [
        f"Press the {s.pin_count} ring pins into the housing pockets on the "
        f"{2 * s.pin_circle_radius:g} mm circle. They are "
        f"{s.ring_pin_length:g} mm long - the barrel's whole length, so the two "
        f"end plates trap them and nothing can walk out of mesh."
        + ("" if not s.ring_pins_are_rollers else
           " These are meant to turn, so the pins must be a running fit in the "
           "pockets or carry rollers - a press fit here throws away the "
           "efficiency you selected them for."),
        f"Press the {s.output_pin_count} output pins into the carrier on the "
        f"{2 * s.output_bolt_circle_radius:g} mm circle. Use "
        f"<b>output_carrier.dxf</b> as the drilling template - those holes are "
        f"the {s.output_pin_diameter:g} mm press fit, not the "
        f"{s.output_hole_diameter:.3f} mm running holes in the disc.",
        f"Fit the eccentric bearings onto the {s.cam_diameter:g} mm cams, then "
        f"drop each disc over its own cam.",
    ]
    if s.disc_count > 1:
        steps.append(
            "Check the phasing before closing it up: at any crank angle the "
            "output pins must sit inside their holes on <i>every</i> disc "
            "simultaneously. If one disc binds while another is free, its hole "
            "pattern is at the wrong angle - see the note above.")
    steps.append(
        "Turn the input by hand through a full revolution before powering it. "
        "It should feel uniform. A tight spot once per disc revolution means "
        "the profile is interfering; a tight spot once per input revolution "
        "means the eccentric is.")
    if a.stiffness.lost_motion_arcmin > 30:
        steps.append(
            f"Expect about {a.stiffness.lost_motion_arcmin:.0f} arcmin "
            f"({a.stiffness.lost_motion_arcmin / 60:.2f} deg) of free play at "
            f"the output. That is the clearance you asked for, not a fault.")

    story += [CondPageBreak(120 * mm), Paragraph("Build order", h2),
              _fig_png(plots.assembly_figure(
                  s, Figure(figsize=(6.4, 4.4), dpi=110),
                  explode=0.85, azimuth=32.0, elevation=20.0), 115),
              Paragraph("Exploded along the axis in assembly order: carrier at "
                        "the bottom, then the housing and its ring pins, the "
                        "disc stack, and the eccentric shaft through the "
                        "middle.", body), Spacer(1, 4)]
    story += [Paragraph(f"{i}. {text}", body) for i, text in enumerate(steps, 1)]

    doc.build(story)
    return path
