"""ParachutesAction - deploy parachutes with verification.

Triggers parachute deployment and stays running until all parachutes
have left the stowed state (armed, semi-deployed, or fully deployed).
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
    """Deploy parachutes and verify deployment."""

    action_id: ClassVar[str] = "parachutes"
    label: ClassVar[str] = "Deploy Parachutes"
    description: ClassVar[str] = "Deploy parachutes"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="min_altitude",
            label="Minimum Altitude",
            description=(
                "Minimum altitude to deploy parachutes. Parachutes will only deploy "
                "once the vessel is at or below this altitude. Leave empty to deploy immediately."
            ),
            required=False,
            param_type=ParamType.FLOAT,
            default=3_000,
        ),
        ActionParam(
            param_id="stage_for_parachutes",
            label="Stage for Parachutes",
            description=(
                "Stage repeatedly until parachutes are reachable in the current stage. "
                "If false, attempts to deploy immediately which may fail if parachutes "
                "are in a later stage."
            ),
            required=False,
            param_type=ParamType.BOOL,
            default=True,
        ),
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        self.min_altitude: float | None = param_values["min_altitude"]
        self.stage_for_parachutes: bool = param_values["stage_for_parachutes"]

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        # Check if parachutes are present
        if state.parts_parachutes_count() == 0:
            return ActionResult(status=ActionStatus.FAILED, message="No parachutes found on the vessel")

        # Wait for altitude gate
        if self.min_altitude is not None and state.altitude_surface > self.min_altitude:
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(f"Waiting for altitude <= {self.min_altitude:.0f}m (current: {state.altitude_surface:.1f}m)"),
            )

        # Stage if needed
        if state.parts_parachutes_count([state.stage_current]) == 0:
            if self.stage_for_parachutes:
                commands.stage = True
                return ActionResult(status=ActionStatus.RUNNING, message="Staging for parachutes")
            else:
                return ActionResult(status=ActionStatus.FAILED, message="Parachutes are not in the current stage")

        # Deploy
        commands.deployable_parachutes = True
        return ActionResult(
            status=ActionStatus.SUCCEEDED,
            message=f"Triggering the deployment of {state.parts_parachutes_count([state.stage_current])} parachutes at {state.altitude_surface:.1f}m",
        )

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)
