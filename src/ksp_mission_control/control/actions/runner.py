"""ActionRunner - step-based executor for vessel actions.

The runner manages the currently executing action. It does NOT own a thread;
the control screen's poll loop calls step() each iteration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ksp_mission_control.control.actions.base import (
    Action,
    ActionStatus,
    VesselCommands,
    VesselState,
)


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

    def start_action(
        self,
        action: Action,
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
        action.start(resolved)

    def abort(self) -> VesselCommands:
        """Stop the current action immediately.

        Returns cleanup controls (throttle=0 by default) for the caller to apply.
        If no action is running, returns empty controls.
        """
        controls = VesselCommands()
        if self._action is not None:
            self._action.stop(controls)
            self._action = None
            self._status = None
            self._message = ""
        return controls

    def step(self, vessel_state: VesselState, dt: float) -> VesselCommands:
        """Execute one tick of the current action.

        Creates a fresh VesselCommands, passes it to the action's tick(),
        and returns it. If the action signals completion or failure,
        stop() is called automatically.

        If no action is running, returns empty controls (all None).
        """
        controls = VesselCommands()
        if self._action is None:
            return controls

        result = self._action.tick(vessel_state, controls, dt)
        self._status = result.status
        self._message = result.message

        if result.status in (ActionStatus.SUCCEEDED, ActionStatus.FAILED):
            self._action.stop(controls)
            self._action = None
            self._status = None
            self._message = ""

        return controls

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
