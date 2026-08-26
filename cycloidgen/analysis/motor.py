"""Whether the motor can actually drive this gearbox at this duty point.

Everywhere else in the app the duty is an input: a torque out and a speed in,
taken as given, worked back through the ratio and the efficiency to an input
torque nobody then asks about.  That is a complete answer to "is the gearbox
strong enough" and no answer at all to "will this turn", which is the question a
drive is bought to settle.

So this compares the two.  The gearbox says what it needs at the input shaft;
the motor curve says what is there at that speed; the interesting numbers are
the ones in between.

Three of them are worth more than the pass or fail.

**Where the operating point sits on the curve.**  A stepper holds its full
torque to about half its electrical ceiling and then falls off a cliff - three
quarters of the way up it has around half of it left, and nine tenths of the way
up, a third.  So the fraction of stall is the number to read, not the margin:
the margin looks healthy right up until the curve falls out from under it, and
the two are only a few hundred rpm apart.

**The output torque ceiling.**  What this motor and this ratio can deliver at
the output, which is the number the drive is really being asked for.  It is the
continuous torque times the ratio times the efficiency, and it is nearly always
smaller than the gearbox's own capacity - so on most designs the motor, not the
contact stress, is what the drive is worth.

**The output speed ceiling.**  The requirement usually has a speed in it, and a
motor short of torque does not fail everywhere - it fails above a speed.  Saying
"this runs out at 34 rpm at the output" is an answer somebody can design to.
The alternative, a bare failure, sends people back to the ratio when the fix
might be the bus voltage.

Peak against continuous
-----------------------
The margin reported here is on the *continuous* line, which is the same line as
the peak one for a stepper and two orders of magnitude below it for a brushless
motor.  Sizing a drive on a brushless motor's stall torque is the classic way to
build a gearbox that survives a bench test and not a robot, so the honest line
is the default and the peak is carried alongside rather than instead.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.motor import MotorKind
from ..core.spec import GearSpec
from .efficiency import EfficiencyResult

__all__ = ["MotorResult", "analyse_motor"]

#: How much more torque than the duty point asks for a motor should have.
#:
#: Two reasons, and neither is a fudge for the model.  A drive has to accelerate
#: its own reflected inertia and break away from stiction before it does any
#: useful work, and the efficiency this margin is measured through is stated as
#: an upper bound - seals and churning are not in it.  A motor sized at exactly
#: the steady-state figure is a motor that will not start.
COMFORTABLE_MARGIN = 1.5


@dataclass
class MotorResult:
    """What the motor has, against what the gearbox asks for.

    ``modelled`` is false when no curve has been stated, and then every other
    field is a placeholder: nothing here should be shown or checked, in the same
    way :class:`~cycloidgen.analysis.fatigue.FatigueResult` declines to put a
    number on printed parts rather than putting a bad one.
    """

    modelled: bool
    kind: MotorKind
    #: What the motor is turning, rpm.  The input shaft, which is the crank -
    #: the crank is always the input in this machine, whichever member is
    #: grounded.  Deliberately *not* ``spec.crank_rate``: that is crank angle
    #: per input revolution in the ring-fixed frame the kinematics are
    #: parameterised in, an internal quantity, and it is not a shaft speed.
    motor_rpm: float
    #: Input torque the gearbox needs there, Nm.
    required_Nm: float
    #: What the motor makes there on the peak line, Nm.
    available_Nm: float
    #: What it makes there and can go on making, Nm.
    continuous_Nm: float
    #: Torque at standstill, Nm - holding torque for a stepper.
    stall_Nm: float
    #: The speed past which the motor makes no torque at all on this bus, rpm.
    ceiling_rpm: float
    #: The current the supply can force through a stationary winding, A.  Below
    #: the rated current it means the bus cannot reach the motor's own rating,
    #: and the whole curve is scaled down from the datasheet.
    standstill_current_A: float
    #: The fastest input speed that still makes the required torque, rpm.
    top_motor_rpm: float
    #: What the motor and this ratio can deliver at the output, Nm.
    output_torque_ceiling_Nm: float
    #: Carried so :attr:`supply_reaches_rated_current` has something to compare
    #: against without reaching back into the spec.
    rated_current_A: float
    #: The reduction, held rather than reached back for so the torque ceiling
    #: and the speed ceiling cannot be derived through different ratios.
    ratio: float

    @property
    def margin(self) -> float:
        """Times over the requirement, on the continuous line.

        ``inf`` when nothing is asked of the motor, which keeps a design with no
        duty from reading as a failure.
        """
        if self.required_Nm <= 0:
            return math.inf
        return self.continuous_Nm / self.required_Nm

    @property
    def peak_margin(self) -> float:
        """The same against the peak line - what it has for a few seconds."""
        if self.required_Nm <= 0:
            return math.inf
        return self.available_Nm / self.required_Nm

    @property
    def fraction_of_stall(self) -> float:
        """How much of the standstill torque survives to the running speed.

        The number that catches a drive designed on holding torque.  A stepper
        keeps all of it to about half its electrical ceiling, has roughly half
        left at three quarters, and a third at nine tenths - so the whole of the
        fall is in the top half of the speed range, and a design near the top of
        it is a design one supply-voltage sag away from stalling.
        """
        if not math.isfinite(self.stall_Nm) or self.stall_Nm <= 0:
            return 1.0
        return self.available_Nm / self.stall_Nm

    @property
    def fraction_of_ceiling(self) -> float:
        """Where on the speed range the drive runs, 0 to 1."""
        if not math.isfinite(self.ceiling_rpm) or self.ceiling_rpm <= 0:
            return 0.0
        return self.motor_rpm / self.ceiling_rpm

    @property
    def supply_reaches_rated_current(self) -> bool:
        """Whether the bus can push the motor's rated current at standstill.

        A stepper wound for 30 ohms on a 12 V bus cannot, and then its holding
        torque is not the datasheet's - it is whatever ``V/R`` buys.  The one
        thing in either model that the winding resistance decides on its own.
        """
        return self.standstill_current_A >= self.rated_current_A - 1e-9

    @property
    def output_speed_ceiling_rpm(self) -> float:
        """What the top input speed is worth at the output, rpm.

        One honest limit: the torque it is the ceiling *for* was worked out at
        the speed the design is running at now, and the loss inside the gearbox
        moves with speed - faster sliding, a hotter and thinner film.  So this
        is the ceiling under today's losses rather than the ceiling under the
        losses it would have there, and the two are a fixed point apart.  The
        difference is small next to the model's own bounds and stating it is
        cheaper than solving it.
        """
        return self.top_motor_rpm / max(self.ratio, 1e-9)


def analyse_motor(spec: GearSpec, efficiency: EfficiencyResult) -> MotorResult:
    """Put the duty point on the motor's curve.

    ``efficiency`` is where the input torque comes from, rather than
    ``T_out / ratio``: the loss is a real part of what the motor is asked for and
    on a printed drive with fixed pins it is nearly half of it.  Taking the
    input torque from the efficiency solve also means this number and the one on
    the datasheet are the same number.
    """
    curve = spec.motor_curve
    # The input shaft, plainly.  Not ``input_rpm * crank_rate``: the crank rate
    # is crank angle per input revolution in the frame the profile was generated
    # in, which is how every *relative* speed inside the drive is stated, and it
    # is not the speed of anything a motor is bolted to.  The motor turns the
    # input shaft at the input speed whichever member is grounded.
    motor_rpm = spec.input_rpm
    required = efficiency.input_torque_Nm
    if not curve.modelled:
        return MotorResult(
            modelled=False, kind=curve.kind, motor_rpm=motor_rpm,
            required_Nm=required, available_Nm=math.inf,
            continuous_Nm=math.inf, stall_Nm=math.inf,
            ceiling_rpm=math.inf, standstill_current_A=math.inf,
            top_motor_rpm=math.inf, output_torque_ceiling_Nm=math.inf,
            rated_current_A=spec.motor_rated_current_A,
            ratio=float(spec.ratio),
        )

    continuous = curve.continuous_torque_at(motor_rpm)
    return MotorResult(
        modelled=True,
        kind=curve.kind,
        motor_rpm=motor_rpm,
        required_Nm=required,
        available_Nm=curve.torque_at(motor_rpm),
        continuous_Nm=continuous,
        stall_Nm=curve.stall_torque_Nm,
        ceiling_rpm=curve.ceiling_rpm,
        standstill_current_A=spec.motor_supply_V / spec.motor_resistance_ohm,
        top_motor_rpm=curve.continuous_speed_for_torque(required),
        # The ratio and the efficiency, in that order, because that is the order
        # the machine applies them: the gearbox multiplies the torque and then
        # loses some of it.
        output_torque_ceiling_Nm=continuous * spec.ratio * efficiency.efficiency,
        rated_current_A=spec.motor_rated_current_A,
        ratio=float(spec.ratio),
    )
