"""What a saved design is on disk, and what it says about where it came from.

A design file is the spec *and* the version that wrote it, and the second half
is not decoration.  Every number this app reports is a model of a machine, the
model gets better, and the same design reopened in a later build can come back
with a different mass or a different verdict on a check it used to pass.  The
release notes can say that something moved; only the file can say whether it
moved under *this* design, because only the file knows which build produced the
numbers somebody wrote down.

The shape is the report's shape - the spec under a ``spec`` key - and that is
deliberate rather than tidy.  ``--design`` and File > Open have both always
accepted a full report in place of a design, so a build that predates any of
this opens these files without needing to know why they changed.
"""
from __future__ import annotations

import json

from .. import __version__
from .spec import GearSpec

__all__ = [
    "design_dict",
    "numbers_may_have_moved",
    "provenance",
    "spec_from_dict",
    "written_by",
]


def design_dict(spec: GearSpec) -> dict:
    """A saved design: what it is, and what wrote it."""
    return {
        "generator": "cycloidgen",
        "version": __version__,
        "spec": json.loads(spec.model_dump_json()),
    }


def spec_from_dict(data: dict) -> GearSpec:
    """The design in ``data``.

    Takes a design file, a full report, or a bare spec dump from before either
    had a wrapper round it - one reader for all three, because the app has
    written all three and every one of them is somebody's saved work.
    """
    return GearSpec.model_validate(data.get("spec", data))


def written_by(data: dict) -> str | None:
    """The version that wrote ``data``, or ``None`` where the file does not say."""
    version = data.get("version") if isinstance(data, dict) else None
    return version if isinstance(version, str) and version else None


def numbers_may_have_moved(written: str | None) -> bool:
    """Whether a design written by ``written`` can read differently here.

    Major and minor are the two digits the release rule allows to move a
    computed number; patch is *defined* as the one that cannot, so a patch
    apart is silence rather than a warning nobody needs.  A file that does not
    say which build wrote it predates the stamp, and everything before the
    stamp is further away than one release - so unknown counts as moved.
    """
    if written is None:
        return True
    try:
        theirs = tuple(int(part) for part in written.split(".")[:2])
        ours = tuple(int(part) for part in __version__.split(".")[:2])
    except ValueError:
        return True                 # unreadable is not the same as identical
    return theirs != ours


def provenance(written: str | None) -> str:
    """One line for a person: which build made this, and what that means for it.

    Kept here rather than at each of the two places that show it, so the modal
    on an opened file and the status line on a restored session cannot end up
    telling the same user two different stories about the same situation.
    """
    made = f"version {written}" if written else "a build too old to record which"
    return (f"This design was saved by {made}; this is {__version__}. "
            "Anything that was reported for it - mass, efficiency, stiffness, "
            "the verdict on a check - may have moved since. The geometry has "
            "not: the inputs still mean what they meant. The changelog says "
            "what changed and by how much.")
