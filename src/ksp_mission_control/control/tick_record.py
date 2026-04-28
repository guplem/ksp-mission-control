"""TickRecord - per-tick snapshot of state, logs, and commands for export."""

from __future__ import annotations

from dataclasses import dataclass

from ksp_mission_control.control.actions.base import (
    ActionStatus,
    LogEntry,
    State,
    VesselCommands,
)


@dataclass(frozen=True)
class TickRecord:
    """A single tick's state, logs, and resulting commands, for clipboard export."""

    tick_number: int
    met: float
    state: State
    action_label: str | None
    action_status: ActionStatus | None
    logs: list[LogEntry]
    commands: VesselCommands
    applied_fields: frozenset[str]
