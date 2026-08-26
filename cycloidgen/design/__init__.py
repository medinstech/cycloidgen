"""Going the other way: from requirements to a design.

The rest of the app answers "is this design any good?".  This package answers
"what design should I build?" - you give it a torque, a speed, an envelope and a
manufacturing process, and it searches for the geometry that satisfies every
check with the most margin.

The reduction is either part of the question or part of the answer.  Name it and
the search works inside it; leave it to a stated motor and the search first asks
which reductions that motor can drive this load with, then works across them -
which is the shape the question usually arrives in, because a reduction is a
means and the job is a torque at a speed.
"""
from .optimize import (
                       RATIO_FROM_MOTOR,
                       Candidate,
                       Objective,
                       OptimisationResult,
                       RatioBand,
                       RejectionTally,
                       Requirements,
                       optimise,
                       ratio_band,
                       requirements_from_spec,
)

__all__ = [
                       "RATIO_FROM_MOTOR",
                       "Candidate",
                       "Objective",
                       "OptimisationResult",
                       "RatioBand",
                       "RejectionTally",
                       "Requirements",
                       "optimise",
                       "ratio_band",
                       "requirements_from_spec",
]
