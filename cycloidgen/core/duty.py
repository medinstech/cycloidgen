"""What the drive is actually asked to do, over time.

Everywhere else in this application the duty is one point: a torque out at a
speed in.  That is the right way to *size* a gearbox and the wrong way to
describe a machine.  A robot joint lifts, holds, returns and waits; a winch
pulls hard and slowly and then spools back fast and empty.  A single point can
be the worst of those or the average of them, and the two answers are different
by a factor that matters - so the app has been asking which one you meant
without saying that it was asking.

Why one point cannot stand in for the cycle
-------------------------------------------
Because the quantities do not aggregate the same way, and no single point is
conservative for all of them at once.

* **Stress and fatigue** want the *worst* point.  The contact pressure at the
  hardest moment is what breaks the disc, and averaging it away is how a drive
  passes on paper and cracks on a bench.
* **Temperature** wants the *mean loss*.  A drive that spends a tenth of its
  time at four times the load does not run at four times the loss; the housing
  integrates, and sizing the cooling to the peak is sizing it to a transient.
* **Bearing life** wants neither.  Life goes as the cube of load, so a varying
  load is carried by the *cubic mean* - ISO 281's equivalent load - which sits
  well above the arithmetic mean and well below the peak.
* **The motor** wants both ends: it has to make the peak torque at the peak
  point's speed, and it has to survive the RMS current all day.

Four aggregations, one cycle.  Getting any of them by picking a representative
point is a coincidence rather than a method.

What a point is
---------------
A torque at the output, a speed at the output, and how long it lasts.  The
duration is in whatever unit suits - only the ratios are read - so a cycle can
be typed the way it is measured rather than converted into shares that have to
add up to one.

Zero output speed is a *point*, not an error.  Holding a load still is most of
what some drives do: the motor must make the torque, nothing slides so there is
no PV and no wear, and no bearing turns so no life is consumed.  Arithmetic
that divides by speed has to know that, which is why the rates below are
properties rather than expressions scattered through the analysis.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

__all__ = ["DutyCycle", "DutyPoint"]


class DutyPoint(BaseModel):
    """One thing the drive does, and for how long."""

    model_config = {"validate_assignment": True}

    #: What the point is called on a datasheet.  Free text, because the useful
    #: names are the machine's - "lift", "hold", "return" - and no list this
    #: module could offer would contain them.
    name: str = Field("", max_length=40)
    output_torque_Nm: float = Field(gt=0)
    #: Zero is allowed and means a hold: the load is there and nothing turns.
    output_rpm: float = Field(ge=0)
    #: How long this point lasts.  Any consistent unit; only the ratios matter.
    seconds: float = Field(gt=0)

    @property
    def is_hold(self) -> bool:
        """Whether the output is stationary under load."""
        return self.output_rpm <= 0.0


class DutyCycle(BaseModel):
    """A sequence of points, and the aggregates that need all of them.

    Empty is the default and means "no cycle stated", which is what every design
    has meant until now: the rated point on the spec is the whole duty and every
    number is the number it always was.
    """

    model_config = {"validate_assignment": True}

    points: tuple[DutyPoint, ...] = ()

    @model_validator(mode="after")
    def _a_cycle_is_more_than_one_point(self) -> DutyCycle:
        """One point is not a cycle - it is the rated point with extra steps.

        Refused rather than accepted quietly, because a one-point cycle would
        give the same answers as no cycle while making the panel look like the
        feature was in use.
        """
        if len(self.points) == 1:
            raise ValueError(
                "a duty cycle needs at least two points; one point is the "
                "rated duty, which the design already carries")
        return self

    @property
    def stated(self) -> bool:
        return bool(self.points)

    @property
    def total_seconds(self) -> float:
        return sum(p.seconds for p in self.points)

    def shares(self) -> tuple[float, ...]:
        """Each point's fraction of the cycle, summing to one."""
        total = self.total_seconds
        if total <= 0:
            return tuple(0.0 for _ in self.points)
        return tuple(p.seconds / total for p in self.points)

    @property
    def moving_share(self) -> float:
        """The fraction of the cycle in which anything turns.

        Bearing life is consumed per revolution, so a cycle that holds for half
        of itself wears its bearings at half the rate - and the hours the life
        is quoted in are hours of *the cycle*, not hours of rotation.  Keeping
        the two apart is the difference between a life figure somebody can plan
        a service interval on and one that is optimistic by however much the
        machine spends standing still.
        """
        total = self.total_seconds
        if total <= 0:
            return 0.0
        return sum(p.seconds for p in self.points if not p.is_hold) / total

    @property
    def peak(self) -> DutyPoint | None:
        """The point with the most torque - what the geometry has to survive."""
        return max(self.points, key=lambda p: p.output_torque_Nm, default=None)

    @property
    def fastest(self) -> DutyPoint | None:
        """The point with the most speed - what the sliding contacts have to."""
        return max(self.points, key=lambda p: p.output_rpm, default=None)

    def mean_of(self, values: tuple[float, ...]) -> float:
        """Time-weighted mean of one value per point.  For anything that the
        housing integrates - loss, and so temperature."""
        return sum(v * s for v, s in zip(values, self.shares(), strict=True))

    def rms_of(self, values: tuple[float, ...]) -> float:
        """Time-weighted root mean square.  For anything that heats at the
        square of itself, which is a motor winding."""
        return sum(v * v * s for v, s in zip(values, self.shares(),
                                             strict=True)) ** 0.5

    def cubic_mean_of(self, values: tuple[float, ...], *,
                      exponent: float = 3.0,
                      turning: tuple[bool, ...] | None = None) -> float:
        """ISO 281's equivalent load for a varying one.

        ``P_m = (sum(P_i^p * u_i) / sum(u_i))^(1/p)`` over the points that
        actually *turn*, because a bearing standing still under load consumes no
        life - it consumes something else, which is a static rating and a
        different check.  Weighted by revolutions rather than by seconds for the
        same reason: a bearing wears per revolution, so a point at half the
        speed contributes half as much of it.
        """
        if turning is None:
            turning = tuple(not p.is_hold for p in self.points)
        weights = [p.seconds * p.output_rpm if turn else 0.0
                   for p, turn in zip(self.points, turning, strict=True)]
        total = sum(weights)
        if total <= 0:
            return 0.0
        carried = sum(abs(v) ** exponent * w
                      for v, w in zip(values, weights, strict=True))
        return (carried / total) ** (1.0 / exponent)
