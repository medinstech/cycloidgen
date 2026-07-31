"""SVG output, 1 user unit = 1 mm, y flipped so the drawing reads the right way up."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..core import profile as prof
from ..core.spec import GearSpec

__all__ = ["write_svg", "svg_document"]

_STROKE = 'fill="none" stroke-width="0.35"'


def _path_d(points: np.ndarray) -> str:
    head = f"M {points[0, 0]:.4f} {points[0, 1]:.4f}"
    body = " ".join(f"L {x:.4f} {y:.4f}" for x, y in points[1:])
    return f"{head} {body} Z"


def svg_document(spec: GearSpec) -> str:
    """Build the SVG as a string."""
    p = prof.profile_from_spec(spec)
    margin = 5.0
    extent = spec.housing_outer_radius + margin
    size = 2 * extent

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}mm" height="{size}mm" '
        f'viewBox="{-extent:.3f} {-extent:.3f} {size:.3f} {size:.3f}">',
        '<g transform="scale(1,-1)">',
        f'<circle cx="0" cy="0" r="{spec.housing_outer_radius:.4f}" '
        f'stroke="#999" {_STROKE}/>',
        f'<circle cx="0" cy="0" r="{spec.pin_circle_radius:.4f}" stroke="#bbb" '
        f'stroke-dasharray="2,2" {_STROKE}/>',
        f'<path d="{_path_d(p.points)}" stroke="#0a7" stroke-width="0.5" fill="none"/>',
        f'<circle cx="0" cy="0" r="{(spec.center_bore_diameter + spec.hole_clearance) / 2:.4f}" '
        f'stroke="#c33" {_STROKE}/>',
    ]

    # one hole pattern per distinct disc - they sit at different angles
    hole_r = spec.output_hole_diameter / 2.0
    phases = ([spec.disc_hole_phases[0]] if spec.discs_are_identical
              else spec.disc_hole_phases)
    for i, hole_phase in enumerate(phases):
        stroke = "#36c" if i == 0 else "#8ab"
        for k in range(spec.output_pin_count):
            a = 2.0 * np.pi * k / spec.output_pin_count + hole_phase
            cx = spec.output_bolt_circle_radius * np.cos(a)
            cy = spec.output_bolt_circle_radius * np.sin(a)
            parts.append(f'<circle cx="{cx:.4f}" cy="{cy:.4f}" r="{hole_r:.4f}" '
                         f'stroke="{stroke}" {_STROKE}/>')

    for k in range(spec.pin_count):
        a = 2.0 * np.pi * k / spec.pin_count
        cx = spec.pin_circle_radius * np.cos(a)
        cy = spec.pin_circle_radius * np.sin(a)
        parts.append(f'<circle cx="{cx:.4f}" cy="{cy:.4f}" r="{spec.pin_radius:.4f}" '
                     f'stroke="#e80" {_STROKE}/>')

    parts.append("</g>")
    parts.append(
        f'<text x="{-extent + 2:.2f}" y="{extent - 2:.2f}" font-size="3" fill="#666">'
        f'i={spec.ratio}:1  N={spec.lobes}/{spec.pin_count}  R={spec.pin_circle_radius} '
        f'Rr={spec.pin_radius} E={spec.eccentricity}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


def write_svg(spec: GearSpec, path: str | Path) -> Path:
    path = Path(path)
    path.write_text(svg_document(spec), encoding="utf-8")
    return path
