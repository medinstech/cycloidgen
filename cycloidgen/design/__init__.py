"""Going the other way: from requirements to a design.

The rest of the app answers "is this design any good?".  This package answers
"what design should I build?" - you give it a ratio, a torque, an envelope and a
manufacturing process, and it searches for the geometry that satisfies every
check with the most margin.
"""
from .optimize import (
                       Candidate,
                       Objective,
                       OptimisationResult,
                       RejectionTally,
                       Requirements,
                       optimise,
                       requirements_from_spec,
)

__all__ = [
                       "Candidate",
                       "Objective",
                       "OptimisationResult",
                       "RejectionTally",
                       "Requirements",
                       "optimise",
                       "requirements_from_spec",
]
