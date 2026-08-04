"""What lengths are *shown* in.  Everything inside this program is millimetres.

The line this draws is between reading and handing over.  A number on screen is
read by a person, and a shop that works in inches should not have to convert one
in their head to know whether a web is thick enough.  A file is read by a
machine: a DXF, a STEP, an STL and the JSON report stay in millimetres whatever
this is set to, because a CAD file whose units follow a preference is a CAD file
nobody can trust.  The PDF is in the second category - it is a document you send
someone - and stays millimetres too.

Decimal inches, not fractional.  Fractions are how a drawing is dimensioned and
they are miserable to type into a spin box, which is what most of these numbers
are for.

Kept at the package root rather than under ``ui`` because both the window and
the shared plotting code need it, and ``report`` must not import ``ui``.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["MM_PER_INCH", "UNITS", "Unit", "unit"]

MM_PER_INCH = 25.4


@dataclass(frozen=True)
class Unit:
    """One way of showing a length."""

    key: str
    #: What goes after the number, with its leading space.
    suffix: str
    #: Multiply a value in millimetres by this to get the displayed number.
    per_mm: float
    #: Added to a field's millimetre decimals.  An inch is 25.4 mm - about 1.4
    #: decades - so two more places keeps every digit the mm form carried, which
    #: matters most for the clearances, where the whole quantity is 0.22 mm.
    extra_decimals: int

    def show(self, mm: float) -> float:
        """Millimetres in, displayed number out."""
        return mm * self.per_mm

    def store(self, shown: float) -> float:
        """Displayed number in, millimetres out."""
        return shown / self.per_mm

    def decimals(self, mm_decimals: int) -> int:
        return mm_decimals + self.extra_decimals

    def text(self, mm: float, mm_decimals: int = 2) -> str:
        """A formatted length, unit included."""
        return f"{self.show(mm):.{self.decimals(mm_decimals)}f}{self.suffix}"


UNITS: dict[str, Unit] = {
    "mm": Unit("mm", " mm", 1.0, 0),
    "in": Unit("in", " in", 1.0 / MM_PER_INCH, 2),
}


def unit(key: str) -> Unit:
    """The unit for ``key``, falling back to millimetres for anything unknown.

    Forgiving on purpose: this comes out of a settings file that an older or
    newer build may have written, and an unreadable preference should cost the
    default rather than a window that will not open.
    """
    return UNITS.get(key, UNITS["mm"])
