"""StageAction - activate one or more stages.

Default behavior: activate the next stage once and succeed. With ``until=N``,
keep activating successive stages until ``state.stage_current`` reaches N.
Stage N itself is NOT activated; it remains as the active stage.
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
    description: ClassVar[str] = "Activate one or more stages"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="until",
            label="Stop at stage",
            description=(
                "Keep activating successive stages until stage_current reaches this number. "
                "This stage itself is NOT activated. Omit to stage exactly once."
            ),
            required=False,
            param_type=ParamType.INT,
            default=None,
        ),
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        raw_until = param_values["until"]
        if raw_until is None:
            self._until: int | None = None
        else:
            until = int(raw_until)
            if until < 0:
                raise ValueError(f"Parameter 'until' must be >= 0, got {until}")
            self._until = until

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        if self._until is None:
            if state.stage_current <= 0:
                return ActionResult(
                    status=ActionStatus.FAILED,
                    message="Failed: already at stage 0",
                )
            commands.stage = True
            return ActionResult(
                status=ActionStatus.SUCCEEDED,
                message=f"Activated stage {state.stage_current}",
            )

        if state.stage_current <= self._until:
            return ActionResult(
                status=ActionStatus.SUCCEEDED,
                message=f"Reached stage {state.stage_current} (target {self._until})",
            )

        commands.stage = True
        return ActionResult(
            status=ActionStatus.RUNNING,
            message=f"Staging from {state.stage_current} toward {self._until}",
        )

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        pass
