"""ActionRunner - step-based executor for vessel actions.

The runner manages the currently executing action. It does NOT own a thread;
the control screen's poll loop calls step() each iteration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ksp_mission_control.control.actions.base import (
    Action,
    ActionLogger,
    ActionStatus,
    LogEntry,
    LogLevel,
    VesselCommands,
    VesselState,
)


@dataclass(frozen=True)
class StepResult:
    """Output of a single runner step: commands to apply and typed log entries."""

    commands: VesselCommands
    logs: list[LogEntry]


@dataclass(frozen=True)
class RunnerSnapshot:
    """Immutable snapshot of runner state for thread-safe UI reads."""

    action_id: str | None = None
    action_label: str | None = None
    status: ActionStatus | None = None
    message: str = ""


class ActionRunner:
    """Manages execution of a single action at a time.

    Call start_action() to begin, step() each tick, abort() to cancel.
    """

    def __init__(self) -> None:
        self._action: Action | None = None
        self._status: ActionStatus | None = None
        self._message: str = ""
        self._pending_logs: list[LogEntry] = []
        self._last_state: VesselState = VesselState()

    def start_action(
        self,
        action: Action,
        state: VesselState,
        param_values: dict[str, Any] | None = None,
    ) -> None:
        """Begin executing an action.

        If param_values is None, builds values from each ActionParam's default.
        Raises ValueError if any required param is missing.
        """
        resolved = self._resolve_params(action, param_values)
        self._action = action
        self._status = ActionStatus.RUNNING
        self._message = ""
        self._last_state = state
        action.start(state, resolved)
        self._pending_logs.append(LogEntry(level=LogLevel.INFO, message=f"Started: {action.label}"))

    def abort(self) -> StepResult:
        """Stop the current action immediately.

        Returns cleanup commands and any log messages from stop().
        If no action is running, returns empty result.
        """
        commands = VesselCommands()
        log = ActionLogger()
        if self._action is not None:
            log.info(f"Aborted: {self._action.label}")
            self._action.stop(self._last_state, commands, log)
            self._action = None
            self._status = None
            self._message = ""
        self._pending_logs.extend(log.entries)
        return StepResult(commands=commands, logs=[])

    def step(self, vessel_state: VesselState, dt: float) -> StepResult:
        """Execute one tick of the current action.

        Creates a fresh VesselCommands and ActionLogger, passes them to
        the action's tick(), and returns commands plus typed log entries.

        If no action is running, returns empty result (all None, no logs).
        """
        commands = VesselCommands()
        log = ActionLogger()
        log.entries.extend(self._pending_logs)
        self._pending_logs.clear()
        self._last_state = vessel_state
        if self._action is None:
            return StepResult(commands=commands, logs=log.entries)

        result = self._action.tick(vessel_state, commands, dt, log)
        self._status = result.status
        self._message = result.message

        if result.status in (ActionStatus.SUCCEEDED, ActionStatus.FAILED):
            label = self._action.label
            log.info(f"Finished: {label} ({result.status.value})")
            self._action.stop(vessel_state, commands, log)
            self._action = None
            self._status = None
            self._message = ""

        return StepResult(commands=commands, logs=log.entries)

    def snapshot(self) -> RunnerSnapshot:
        """Return an immutable snapshot of the current runner state."""
        if self._action is None:
            return RunnerSnapshot()
        return RunnerSnapshot(
            action_id=self._action.action_id,
            action_label=self._action.label,
            status=self._status,
            message=self._message,
        )

    def _resolve_params(
        self,
        action: Action,
        param_values: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Build the final param_values dict, filling defaults and validating required params."""
        resolved: dict[str, Any] = {}
        for param in action.params:
            if param_values is not None and param.param_id in param_values:
                resolved[param.param_id] = param_values[param.param_id]
            elif not param.required and param.default is not None:
                resolved[param.param_id] = param.default
            elif param.required:
                msg = (
                    f"Required parameter '{param.param_id}' "
                    f"not provided for action '{action.action_id}'"
                )
                raise ValueError(msg)
        return resolved
