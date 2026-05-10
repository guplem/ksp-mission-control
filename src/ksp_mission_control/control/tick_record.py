"""TickRecord - per-tick snapshot of state, logs, and commands for export."""

from __future__ import annotations

from dataclasses import dataclass

from ksp_mission_control.control.actions.base import (
    LogEntry,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.multi_track_executor import MultiTrackSnapshot


@dataclass(frozen=True)
class TickRecord:
    """A single tick's state, logs, and resulting commands, for clipboard export."""

    tick_number: int
    met: float
    state: State
    multi_snap: MultiTrackSnapshot
    logs: list[LogEntry]
    commands: VesselCommands
    applied_fields: frozenset[str]
