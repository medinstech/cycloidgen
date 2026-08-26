"""What turns the input shaft: a mounting face, and a torque against speed.

Two different facts about the same object, and the app has only ever held the
first.  :class:`MotorFrame` is the *face* - a bolt pattern, a register and a
shaft diameter - which is standardised, so knowing the frame size tells you
where the holes go and nothing whatever about what comes out of the shaft.  A
NEMA 17 is sold from 0.09 to 0.65 Nm holding torque, and a NEMA 23 frame carries
brushless motors an order of magnitude apart.  So the curve is stated
separately, and none of it is inferred from the frame.

Why a curve rather than a number
--------------------------------
The rest of the app takes the duty as one output torque at one speed, works the
input torque back through the ratio and the efficiency, and stops - which
quietly assumes the motor delivers whatever the arithmetic asks of it at
whatever speed the arithmetic asks it at.  Neither motor here does.  A stepper's
torque falls with speed because the winding is an inductor and the supply runs
out of voltage to push current into it; a DC motor's falls because its own
back-EMF eats the supply.  Both have a speed past which they make no torque at
all, and it is a property of the *supply voltage* as much as of the motor.

That is the number people are most often wrong about.  Holding torque is quoted
at standstill and is what a stepper is bought on, and a drive designed on it is
designed on a figure the motor does not have at any speed it will run at.

The two models
--------------
**Stepper.**  Torque is proportional to phase current, and the current is what
the supply can force through the winding against its resistance, its inductive
reactance and its own back-EMF::

    V^2 = (K*w_m + I*R)^2 + (w_e*L*I)^2        solved for I, capped at I_rated
    T(n) = T_hold * I / I_rated

with ``w_e = 2*pi*N_r*n/60`` the electrical frequency, ``N_r = steps/4`` the
rotor teeth, and ``K = T_hold / (sqrt(2)*I_rated)`` the back-EMF constant.  That
last identity is the useful one and is worth stating: holding torque is measured
with *both* phases at rated current, so one phase contributes ``T_h/sqrt(2)``,
and the constant relating current to torque in a machine is the same constant
relating speed to back-EMF.  So a stepper's electrical ceiling comes out of its
mechanical rating with nothing else needed::

    n_ceiling = 60*V / (2*pi*K)

Above that the back-EMF alone exceeds the supply and no current flows whichever
way the driver switches.  On 24 V a 0.4 Nm, 1.7 A motor stops at about 1380 rpm;
on 12 V the same motor stops at 690.  Halving the supply halves the top speed,
which is the single most useful thing this model says.

**DC and brushless.**  The straight line between stall and no-load, exact for a
brushed motor on a fixed supply and first-order for a brushless one::

    Kt = 9.5493 / Kv      n_0 = Kv * V      T_stall = Kt * V / R
    T(n) = T_stall * (1 - n/n_0)

The stall end of that line is a fantasy in the sense that matters - it is drawn
at a current the motor cannot survive for more than a few seconds - so the
*continuous* torque is carried separately, at rated current, and it is the one
a drive should be sized on.  A 270 Kv motor on 24 V with 0.1 ohm windings stalls
at 8.5 Nm and can hold 0.7; sizing a gearbox on the first number is how you buy
one that survives the bench and not the robot.

What these ignore
-----------------
The stepper current here is what a driver holding the optimum phase angle could
force.  A step driver without phase advance does less, so published pull-out
curves fall away sooner through the middle of the range than this does - the
ceiling is firm, the shape approaching it is an upper bound.  Mid-band
resonance, which can stall a stepper outright at a few hundred rpm, is not in it
at all.  The brushless line ignores no-load current and iron loss, so it is
optimistic near no-load speed by whatever those cost.  Both take the supply as
stiff and the driver as able to reach the full bus voltage, which a bipolar
chopper does and a unipolar drive does not.  Use the manufacturer's curve where
you have one; this is for the case where you have a motor in a drawer and a
question about it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, Field

__all__ = [
    "MOTOR_FIELDS",
    "MOTOR_FRAMES",
    "NO_MOTOR",
    "MotorCurve",
    "MotorFrame",
    "MotorKind",
    "curve_from",
]

#: The eight fields a curve is made of, under the names the spec gives them.
#:
#: One list rather than five copies of the same eight strings.  They are carried
#: by :class:`~cycloidgen.core.spec.GearSpec`, mirrored by the search's
#: requirements, handed on to every candidate the search builds, passed through
#: the search dialog and read off a design file by the command line - and a
#: ninth number added to the model with any one of those places missed is a
#: motor that silently changes on the way past.  ``tests/test_motor.py`` checks
#: this against the spec itself, so the list cannot fall behind the model.
MOTOR_FIELDS: tuple[str, ...] = (
    "motor_kind",
    "motor_supply_V",
    "motor_resistance_ohm",
    "motor_rated_current_A",
    "motor_holding_torque_Nm",
    "motor_inductance_mH",
    "motor_steps_per_rev",
    "motor_kv_rpm_per_V",
)


class MotorFrame(BaseModel):
    """A motor's mounting face, as the standard defines it.

    NEMA frames put four bolts on a **square**, not on a bolt circle, and the
    difference is not cosmetic: drawing four holes on a circle of the same size
    puts every one of them in the wrong place.  Metric flanges do use a circle,
    so both are here and ``square`` says which.

    ``max_radial_N`` is what the motor's *own* bearings will take at the shaft
    end.  It is a typical figure for the frame size rather than a promise about
    your motor - they vary by a factor of two between makers - and it exists so
    that hanging a drive on a motor face can be checked against something
    instead of hoped about.  Read your datasheet before you believe it.

    Nothing here says what the motor *does*.  That is :class:`MotorCurve`, and
    it is deliberately not derived from the frame: the frame is a face, and
    every frame size is sold across an order of magnitude of torque.
    """

    name: str
    bolt_span: float = Field(gt=0, description="square side, or bolt circle dia")
    square: bool = Field(True, description="four on a square, or N on a circle")
    bolt_count: int = Field(4, ge=1)
    bolt_diameter: float = Field(gt=0, description="clearance hole, not the thread")
    pilot_diameter: float = Field(gt=0, description="the register that centres it")
    pilot_depth: float = Field(gt=0)
    shaft_diameter: float = Field(gt=0)
    max_radial_N: float = Field(gt=0, description="typical, at the shaft end")

    @property
    def bolt_circle_diameter(self) -> float:
        """Where the bolts actually land, whichever way the pattern is stated.

        A square of side ``s`` puts its corners on a circle of ``s*sqrt(2)``, and
        that is the number every clearance check wants.
        """
        return self.bolt_span * (math.sqrt(2.0) if self.square else 1.0)


#: What a motor face is, by frame size.  Standard NEMA geometry; the radial
#: ratings are typical for the frame rather than any one motor.  ``None`` is a
#: plate with no motor interface at all - a drive driven through a coupling from
#: something this table does not describe.
MOTOR_FRAMES: dict[str, MotorFrame] = {
    m.name: m
    for m in [
        MotorFrame(name="None", bolt_span=1.0, bolt_diameter=1.0,
                   pilot_diameter=1.0, pilot_depth=0.1, shaft_diameter=1.0,
                   max_radial_N=1.0),
        MotorFrame(name="NEMA 8", bolt_span=15.4, bolt_diameter=2.2,
                   pilot_diameter=15.0, pilot_depth=1.6, shaft_diameter=4.0,
                   max_radial_N=10.0),
        MotorFrame(name="NEMA 11", bolt_span=23.0, bolt_diameter=2.7,
                   pilot_diameter=22.0, pilot_depth=2.0, shaft_diameter=5.0,
                   max_radial_N=15.0),
        MotorFrame(name="NEMA 14", bolt_span=26.0, bolt_diameter=3.2,
                   pilot_diameter=22.0, pilot_depth=2.0, shaft_diameter=5.0,
                   max_radial_N=20.0),
        MotorFrame(name="NEMA 17", bolt_span=31.0, bolt_diameter=3.4,
                   pilot_diameter=22.0, pilot_depth=2.0, shaft_diameter=5.0,
                   max_radial_N=28.0),
        MotorFrame(name="NEMA 23", bolt_span=47.14, bolt_diameter=5.5,
                   pilot_diameter=38.1, pilot_depth=1.6, shaft_diameter=6.35,
                   max_radial_N=75.0),
        MotorFrame(name="NEMA 34", bolt_span=69.58, bolt_diameter=5.5,
                   pilot_diameter=73.03, pilot_depth=2.0, shaft_diameter=14.0,
                   max_radial_N=220.0),
    ]
}

#: The frame name that means "no motor interface on this plate".
NO_MOTOR = "None"


class MotorKind(str, Enum):
    """Which curve the thing on the input shaft follows.

    ``NONE`` is not "no motor" - something always turns the crank.  It is "no
    curve stated", and it is the default, so a design that has never been told
    what drives it gets exactly the answers it always got.
    """

    NONE = "none"
    STEPPER = "stepper"
    DC = "DC or brushless"


#: Nm/A per rpm/V.  ``Kt = 60/(2*pi*Kv)``, written out because seeing the number
#: is how you catch a Kv entered in rad/s per volt.
_KT_PER_KV = 60.0 / (2.0 * math.pi)


@dataclass(frozen=True)
class MotorCurve:
    """Torque against speed for one motor on one supply.

    Built from :class:`~cycloidgen.core.spec.GearSpec` rather than stored on it,
    so the eight numbers the panel holds stay the source of truth and there is
    no second copy to drift.  Every method takes rpm and returns Nm.
    """

    kind: MotorKind
    #: Bus volts.  Both models scale with it, and it is usually the cheapest
    #: thing in the design to change.
    supply_V: float
    #: Winding resistance: per phase for a stepper, terminal to terminal for a
    #: DC motor.  Whichever one the datasheet prints.
    resistance_ohm: float
    #: The current it will take all day: the driver setting for a stepper, the
    #: continuous rating for a DC motor.
    rated_current_A: float
    #: Stepper: holding torque, both phases at rated current.
    holding_torque_Nm: float = 0.0
    #: Stepper: inductance per phase, mH.
    inductance_mH: float = 0.0
    #: Stepper: full steps per revolution.  200 is 1.8 degrees, 400 is 0.9.
    steps_per_rev: int = 200
    #: DC: no-load speed per volt.
    kv_rpm_per_V: float = 0.0

    # ---------------------------------------------------------------- shared --
    @property
    def modelled(self) -> bool:
        """Whether there is a curve to ask about at all."""
        return self.kind is not MotorKind.NONE

    @property
    def torque_constant_Nm_per_A(self) -> float:
        """Nm per amp, which is also volt-seconds per radian.

        One constant, both directions - that is what makes a stepper's top speed
        computable from its holding torque.  For the stepper it is per phase, so
        the ``sqrt(2)`` that takes the two-phase holding torque down to one
        phase is in it; see the module docstring.
        """
        if self.kind is MotorKind.STEPPER:
            return self.holding_torque_Nm / (math.sqrt(2.0)
                                             * max(self.rated_current_A, 1e-9))
        if self.kind is MotorKind.DC:
            return _KT_PER_KV / max(self.kv_rpm_per_V, 1e-9)
        return 0.0

    @property
    def stall_torque_Nm(self) -> float:
        """Torque at zero speed, at whatever current the supply can push there.

        For a stepper that is the holding torque, unless the supply cannot force
        rated current through the winding even standing still - which is a real
        case on a high-resistance motor and a low bus, and is the one place the
        resistance decides anything on its own.
        """
        if not self.modelled:
            return math.inf
        return self.torque_at(0.0)

    @property
    def ceiling_rpm(self) -> float:
        """The speed past which the motor makes no torque, loaded or not.

        Back-EMF alone reaches the supply voltage here, so no current flows
        whichever way the driver switches.  It is the same quantity for both
        models - ``V/K`` in radians, which is ``Kv*V`` for a DC motor by
        definition - and it is a property of the supply as much as of the motor.
        """
        if not self.modelled:
            return math.inf
        k = self.torque_constant_Nm_per_A
        if k <= 0:
            return math.inf
        return 60.0 * self.supply_V / (2.0 * math.pi * k)

    def torque_at(self, rpm: float) -> float:
        """What the motor can make at this speed, Nm.

        ``inf`` with no curve stated, so a caller that forgets to check
        :attr:`modelled` fails loudly on a plot rather than quietly on a margin.
        """
        if not self.modelled:
            return math.inf
        rpm = abs(rpm)
        if self.kind is MotorKind.STEPPER:
            return self.holding_torque_Nm * self._stepper_current_fraction(rpm)
        n0 = self.kv_rpm_per_V * self.supply_V
        if n0 <= 0 or rpm >= n0:
            return 0.0
        return self._dc_stall_torque() * (1.0 - rpm / n0)

    def continuous_torque_at(self, rpm: float) -> float:
        """What it can make there *and go on making*, Nm.

        The two models differ in kind here and it matters.  A stepper is already
        current limited at its rated current everywhere on the curve, so its
        continuous torque is its curve - there is no second, lower line.  A DC
        motor's curve is drawn at stall current and its continuous line is drawn
        at rated current, and on a brushless motor those are two orders of
        magnitude apart.
        """
        if not self.modelled:
            return math.inf
        if self.kind is MotorKind.STEPPER:
            return self.torque_at(rpm)
        return min(self.torque_at(rpm),
                   self.torque_constant_Nm_per_A * self.rated_current_A)

    def speed_for_torque(self, torque_Nm: float) -> float:
        """The fastest speed at which the motor still makes ``torque_Nm``, rpm.

        What turns "will this work" into "how fast can it go", which is the
        question a drive that fails the torque check actually raises.  Zero if
        it cannot make that torque standing still either.
        """
        if not self.modelled:
            return math.inf
        if torque_Nm <= 0:
            return self.ceiling_rpm
        if self.kind is MotorKind.STEPPER:
            return self._stepper_speed_for(torque_Nm)
        stall = self._dc_stall_torque()
        n0 = self.kv_rpm_per_V * self.supply_V
        if torque_Nm >= stall or n0 <= 0:
            return 0.0
        return n0 * (1.0 - torque_Nm / stall)

    def continuous_speed_for_torque(self, torque_Nm: float) -> float:
        """The same question asked of the continuous line rather than the peak.

        For a stepper the two are one curve and this is
        :meth:`speed_for_torque`.  For a DC motor the continuous rating is a
        horizontal ceiling, so asking for more than it is a flat no at every
        speed rather than a speed limit - which is the honest answer and not the
        one the peak line gives.
        """
        if not self.modelled:
            return math.inf
        if self.kind is MotorKind.STEPPER:
            return self.speed_for_torque(torque_Nm)
        if torque_Nm > self.torque_constant_Nm_per_A * self.rated_current_A:
            return 0.0
        return self.speed_for_torque(torque_Nm)

    # --------------------------------------------------------------- stepper --
    def _electrical_rad_s(self, rpm: float) -> float:
        """Winding frequency, rad/s.  Four full steps to one electrical cycle,
        so a 200-step motor turns 50 electrical cycles per revolution."""
        rotor_teeth = max(self.steps_per_rev, 4) / 4.0
        return 2.0 * math.pi * rotor_teeth * rpm / 60.0

    def _stepper_current_fraction(self, rpm: float) -> float:
        """Phase current as a fraction of rated, 0 to 1.

        Solves ``V^2 = (E + I*R)^2 + (w_e*L*I)^2`` for ``I``, which is a
        quadratic in ``I`` because the back-EMF does not depend on it.  Taking
        the positive root and capping at rated current is the whole model.
        """
        rated = max(self.rated_current_A, 1e-9)
        emf = self.torque_constant_Nm_per_A * 2.0 * math.pi * rpm / 60.0
        if emf >= self.supply_V:
            return 0.0
        reactance = self._electrical_rad_s(rpm) * self.inductance_mH / 1000.0
        a = self.resistance_ohm ** 2 + reactance ** 2
        if a <= 0:
            return 1.0
        b = 2.0 * emf * self.resistance_ohm
        c = emf ** 2 - self.supply_V ** 2
        current = (-b + math.sqrt(max(b * b - 4.0 * a * c, 0.0))) / (2.0 * a)
        return min(current / rated, 1.0)

    def _stepper_speed_for(self, torque_Nm: float) -> float:
        """Invert the stepper curve by bisection.

        The curve falls monotonically and is bounded above by
        :attr:`ceiling_rpm`, so bisection converges to floating point in sixty
        halvings and cannot wander off.  The algebraic inverse exists, but the
        reactance and the back-EMF scale with different constants, so it is a
        page of terms to save microseconds nobody is spending here.
        """
        if torque_Nm > self.holding_torque_Nm:
            return 0.0
        hi = self.ceiling_rpm
        if not math.isfinite(hi):
            return 0.0
        lo = 0.0
        if self.torque_at(lo) < torque_Nm:
            return 0.0
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            if self.torque_at(mid) >= torque_Nm:
                lo = mid
            else:
                hi = mid
        return lo

    # -------------------------------------------------------------------- DC --
    def _dc_stall_torque(self) -> float:
        if self.resistance_ohm <= 0:
            return math.inf
        return (self.torque_constant_Nm_per_A * self.supply_V
                / self.resistance_ohm)


def curve_from(source) -> MotorCurve:
    """Assemble a curve off anything carrying the eight :data:`MOTOR_FIELDS`.

    A spec and a set of search requirements both do, and both wanted the same
    eight-line constructor call written out.  One function instead, so the two
    cannot come to disagree about which field feeds which part of the model -
    which is a mistake that produces a plausible curve rather than an error.
    """
    return MotorCurve(
        kind=source.motor_kind,
        supply_V=source.motor_supply_V,
        resistance_ohm=source.motor_resistance_ohm,
        rated_current_A=source.motor_rated_current_A,
        holding_torque_Nm=source.motor_holding_torque_Nm,
        inductance_mH=source.motor_inductance_mH,
        steps_per_rev=source.motor_steps_per_rev,
        kv_rpm_per_V=source.motor_kv_rpm_per_V,
    )
