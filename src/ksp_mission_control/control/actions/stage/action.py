"""StageAction - stage the vessel.

Triggers the next stage.
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


class StageAction(Action):
    """Stage the vessel."""

    action_id: ClassVar[str] = "stage"
    label: ClassVar[str] = "Stage"
    description: ClassVar[str] = "Stage the vessel"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="wait_for_no_thrust",
            label="Wait for No Thrust",
            description="Wait until there is no thrust before staging.",
            required=False,
            param_type=ParamType.BOOL,
            default=False,
        ),
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        self._wait_for_no_thrust: bool = bool(param_values.get("wait_for_no_thrust", False))

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        if state.stage_current <= 0:
            return ActionResult(
                status=ActionStatus.FAILED,
                message="Cannot stage: already at stage 0",
            )

        if self._wait_for_no_thrust and state.thrust_available > 0:
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=f"Waiting for no thrust before staging (current thrust: {state.thrust_available:.1f}kN)",
            )

        commands.stage = True
        return ActionResult(status=ActionStatus.SUCCEEDED, message=f"Vessel staged. Current stage: {state.stage_current + 1}")

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)
