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
    State,
    VesselCommands,
)


class StageAction(Action):
    """Stage the vessel."""

    action_id: ClassVar[str] = "stage"
    label: ClassVar[str] = "Stage"
    description: ClassVar[str] = "Stage the vessel"
    params: ClassVar[list[ActionParam]] = []

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        pass

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        if state.stage_current >= state.stage_max - 1:
            return ActionResult(status=ActionStatus.FAILED, message="Cannot stage: already at final stage")
        commands.stage = True
        return ActionResult(status=ActionStatus.SUCCEEDED, message=f"Vessel staged. Current stage: {state.stage_current + 1}")

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)
