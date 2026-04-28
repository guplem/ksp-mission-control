"""ParachutesAction - deploy paraparachutes.

Triggers parachute deployment.
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


class ParachutesAction(Action):
    """Deploy paraparachutes."""

    action_id: ClassVar[str] = "parachutes"
    label: ClassVar[str] = "Deploy Paraparachutes"
    description: ClassVar[str] = "Deploy paraparachutes"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="min_altitude",
            label="Minimum Altitude",
            description="Minimum altitude to deploy paraparachutes. If specified, paraparachutes will only deploy once the vessel is at or below this altitude. If not specified, paraparachutes will deploy immediately.",
            required=False,
            param_type=ParamType.FLOAT,
            default=3_000,
        ),
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        self.min_altitude: float | None = param_values["min_altitude"]
        pass

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        if self.min_altitude and state.altitude_surface > self.min_altitude:
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=f"Waiting to deploy paraparachutes until altitude is at or below {self.min_altitude}m (current altitude: {state.altitude_surface:.1f}m)",
            )

        commands.deployable_parachutes = True
        return ActionResult(status=ActionStatus.SUCCEEDED, message=f"Deploying paraparachutes at altitude {state.altitude_surface:.1f}m")

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)
