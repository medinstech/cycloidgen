"""Where the pins actually are, rather than where the drawing says.

Everything else in the app places the pins exactly.  Clearance is modelled to
the micron - measured off the manufactured profile rather than assumed - and
then every pin is put on a perfect bolt circle at a perfect pitch.  Real rings
are not like that, and the difference is not cosmetic: with a uniform clearance
every pin needs the same rotation to come into mesh, so they arrive together,
and it takes only a few hundredths of a millimetre of position error to decide
which ones arrive first and carry the load alone.

So :attr:`~cycloidgen.core.spec.GearSpec.position_tolerance` is a true-position
tolerance zone, stated the way a drawing states it - as the diameter of the zone
the hole centre must fall inside - and applied to the ring pins and the carrier
pins alike, on the argument that one shop and one machine drilled both.

An ensemble, not a worst case
-----------------------------
A single tolerance number does not say where each pin went, and the two usual
ways of turning it into an answer are both bad on their own.  Worst case - one
pin at the edge of its zone and the rest nominal - is a ring nobody will ever
build and derates the drive to nothing.  Nominal is the ring nobody has ever
built either.

This module draws **rings**: each sample is a whole set of pin positions, drawn
uniformly from the tolerance zone, and the load-sharing solve then runs on that
ring the way it runs on a perfect one.  What comes back is a distribution, and a
distribution can be quoted honestly - the median ring is what you should expect
to build, and the ninth-decile ring is what you should be able to live with.

The draw is seeded from a constant, so a design gives the same answer today and
next month.  That matters more than it sounds: an analysis that moves when you
reopen it is one nobody can check against a measurement.

Sign conventions do not matter here, which is worth knowing because getting one
of them right would otherwise be delicate.  Flipping the sign of every error in
a sample gives another sample that is exactly as likely, so the *ensemble* is
invariant under the choice; only the labelling of individual rings changes.
"""
from __future__ import annotations

import numpy as np

from ..core.spec import GearSpec

__all__ = [
    "DEFAULT_SAMPLES",
    "POSITION_SEED",
    "carrier_position_errors",
    "ring_position_errors",
    "tolerance_samples",
]

#: Fixed, so that a design's answer does not move between one run and the next.
POSITION_SEED = 20260805

#: Rings drawn when a tolerance is given.  Enough for a median and a ninth
#: decile to settle - the quantities here are averages over the pins of a ring,
#: so they concentrate quickly - and few enough to stay interactive.
DEFAULT_SAMPLES = 24

#: Fewer for transmission error, which costs a full mesh cycle at ripple
#: resolution per ring rather than the eight crank angles the load study needs.
#: The spread it reports is coarser for it, and is quoted as a worst-of-batch
#: rather than as a percentile it cannot support.
DEFAULT_TE_SAMPLES = 12


def tolerance_samples(spec: GearSpec, requested: int) -> int:
    """How many rings to draw: one, if the ring is stated to be perfect.

    A zero tolerance is not a small tolerance, it is a different question, and
    it has one answer rather than a distribution of them.  Collapsing the
    ensemble here is what keeps a design with no tolerance entered giving the
    number it gave before this module existed.
    """
    return max(1, requested) if spec.position_tolerance > 0.0 else 1


def _draw(seed_offset: int, samples: int, count: int,
          zone_diameter: float) -> np.ndarray:
    """``(samples, count, 2)`` displacements, uniform over the tolerance disc.

    Uniform over the *disc*, which is what a true-position callout means, and
    not uniform in radius - drawing the radius uniformly would crowd the centre
    and quietly report a better ring than the drawing allows.  ``sqrt`` of a
    uniform is the standard fix.
    """
    if samples <= 0 or count <= 0 or zone_diameter <= 0.0:
        return np.zeros((max(samples, 1), max(count, 0), 2))
    rng = np.random.default_rng(POSITION_SEED + seed_offset)
    radius = 0.5 * zone_diameter * np.sqrt(rng.random((samples, count)))
    angle = rng.uniform(0.0, 2.0 * np.pi, (samples, count))
    return np.stack([radius * np.cos(angle), radius * np.sin(angle)], axis=-1)


def ring_position_errors(spec: GearSpec, samples: int) -> np.ndarray:
    """Where each ring pin ended up, per sampled ring.  ``(samples, pins, 2)`` mm."""
    return _draw(0, samples, spec.pin_count, spec.position_tolerance)


def carrier_position_errors(spec: GearSpec, samples: int) -> np.ndarray:
    """The same for the carrier pins.  ``(samples, output_pin_count, 2)`` mm.

    Its own draw rather than a slice of the ring's: the two patterns are
    independent in a real gearbox, and sharing numbers between them would
    correlate a ring pin's error with a carrier pin's for no reason at all.
    """
    return _draw(1, samples, spec.output_pin_count, spec.position_tolerance)
