"""ThrottleAction - set the throttle level for the vessel.

Triggers the specified throttle level.
"""

from __future__ import annotations

from typing import Any, ClassVar

from ksp_mission_control.control.actions.base import (
    Action,
    ActionLogger,
    ActionParam,
    ActionResult,
    ActionStatus,
    ParamType,
    State,
    VesselCommands,
)


class ThrottleAction(Action):
    """Set the throttle level for the vessel."""

    action_id: ClassVar[str] = "throttle"
    label: ClassVar[str] = "Set Throttle"
    description: ClassVar[str] = "Set the throttle level for the vessel"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="throttle_level",
            label="Throttle Level",
            description="The desired throttle level (0.0 to 1.0)",
            required=True,
            param_type=ParamType.FLOAT,
            default=1.0,
        )
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        self._throttle_level: float = float(param_values["throttle_level"])

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        if state.thrust_available <= 0:
            return ActionResult(status=ActionStatus.FAILED, message="Cannot set throttle: no thrust available")

        commands.throttle = self._throttle_level
        return ActionResult(status=ActionStatus.SUCCEEDED, message=f"Throttle level set to {self._throttle_level}")

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)
