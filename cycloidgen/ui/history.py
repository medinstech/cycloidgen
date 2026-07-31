"""Undo/redo over designs.

States are stored as the spec's own JSON rather than as diffs or as live
objects: a design is small, the serialisation already exists and round-trips
through validation, and a stack of independent snapshots cannot drift out of
step with the thing it is supposed to describe.

No Qt in here, so it can be tested without starting a window.
"""
from __future__ import annotations

from ..core.spec import GearSpec

__all__ = ["SpecHistory"]


class SpecHistory:
    """Bounded undo/redo stack of design states."""

    def __init__(self, initial: GearSpec, limit: int = 60) -> None:
        self._states: list[str] = [initial.model_dump_json()]
        self._index = 0
        self._limit = max(2, limit)

    def push(self, spec: GearSpec) -> None:
        """Record a new state, discarding anything that was redoable."""
        state = spec.model_dump_json()
        if state == self._states[self._index]:
            return                                   # nothing actually changed
        del self._states[self._index + 1:]
        self._states.append(state)
        if len(self._states) > self._limit:
            del self._states[0]
        self._index = len(self._states) - 1

    @property
    def can_undo(self) -> bool:
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        return self._index < len(self._states) - 1

    def undo(self) -> GearSpec | None:
        if not self.can_undo:
            return None
        self._index -= 1
        return self.current()

    def redo(self) -> GearSpec | None:
        if not self.can_redo:
            return None
        self._index += 1
        return self.current()

    def current(self) -> GearSpec:
        return GearSpec.model_validate_json(self._states[self._index])

    def reset(self, spec: GearSpec) -> None:
        """Start again from ``spec`` - opening a file, not editing one."""
        self._states = [spec.model_dump_json()]
        self._index = 0

    def __len__(self) -> int:
        return len(self._states)
