"""Satisfy cadquery's import of casadi without shipping casadi.

PyInstaller runs this before the application's first line, which is the only
window there is: ``cadquery/__init__.py`` imports ``.assembly``, which imports
``.occ_impl.solver``, which does ``import casadi as ca`` at the top of the
module.  There is no way to ask cadquery for its geometry and not its solver.

casadi is an interior-point optimiser with an LLVM toolchain behind it, and in
the frozen bundle it is about 220 MB - the largest single dependency after VTK,
and larger than the CAD kernel it arrives with.  This application never uses it.
Every part in the assembly is placed by an explicit transform computed from the
kinematics; nothing calls ``.constrain()`` and nothing calls ``.solve()``.

So the package is excluded from the bundle and this stands in its place.  The
substitution is safe because of *where* the module uses it: all thirty-seven
references to ``ca.`` are inside function bodies, and the only names read while
the module is being imported are two annotations - ``ca.Opti`` on a class
attribute and ``ca.MX`` on a handful of signatures.  An annotation needs an
object, not a working optimiser.

Hence the two halves below.  Reading a name yields a placeholder, so the import
completes.  *Calling* one raises, so an assembly constraint fails with a
sentence explaining that the solver was left out rather than with an
``AttributeError`` from somewhere inside cadquery - which is the difference
between a limit that is stated and a bug that is hunted.
"""
import sys
import types


class _SolverLeftOut:
    """A casadi name.  Enough to annotate with, not enough to solve with."""

    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        self._name = name

    def __repr__(self) -> str:                       # pragma: no cover - display
        return f"<casadi.{self._name} (not bundled)>"

    def __call__(self, *args, **kwargs):
        raise RuntimeError(
            f"casadi.{self._name} was called, but casadi is not bundled with "
            "cycloidgen.  The assembly is built by explicit placement and needs "
            "no constraint solver, so the optimiser is left out of the build to "
            "save about 220 MB.  Constraint solving needs cycloidgen installed "
            "from PyPI (pip install cycloidgen), which brings the real cadquery "
            "dependencies with it."
        )


class _Casadi(types.ModuleType):
    def __getattr__(self, name: str):
        # Dunders are asked for by the import machinery and by inspect; answering
        # those with a placeholder makes the module lie about its own shape.
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return _SolverLeftOut(name)


# Only if it is genuinely absent.  A developer running the frozen spec against an
# environment that has casadi should get casadi, not this.
if "casadi" not in sys.modules:
    try:
        import casadi  # noqa: F401
    except ImportError:
        sys.modules["casadi"] = _Casadi("casadi")
