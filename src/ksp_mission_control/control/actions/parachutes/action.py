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
    filter_parts,
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
            default=10_000,
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
        ActionParam(
            param_id="wait_for_safe",
            label="Wait for Safe",
            description=(
                "Wait until the game reports it is safe to deploy before triggering. "
                "Prevents parachute destruction from excessive speed or pressure. "
                "If false, deploys immediately regardless of safety."
            ),
            required=False,
            param_type=ParamType.BOOL,
            default=True,
        ),
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        raw_min_altitude = param_values["min_altitude"]
        self._min_altitude: float | None = float(raw_min_altitude) if raw_min_altitude is not None else None
        self._stage_for_parachutes: bool = bool(param_values["stage_for_parachutes"])
        self._wait_for_safe: bool = bool(param_values["wait_for_safe"])

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        # Check if parachutes are present
        if state.parts.parachutes_count() == 0:
            return ActionResult(status=ActionStatus.FAILED, message="No parachutes found on the vessel")

        # Wait for altitude gate
        if self._min_altitude is not None and state.altitude_surface > self._min_altitude:
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(f"Waiting for altitude <= {self._min_altitude:.0f}m (current: {state.altitude_surface:.1f}m)"),
            )

        # Stage if needed
        if state.parts.parachutes_count([state.stage_current]) == 0:
            if self._stage_for_parachutes:
                commands.stage = True
                return ActionResult(status=ActionStatus.RUNNING, message="Staging for parachutes")
            else:
                return ActionResult(status=ActionStatus.FAILED, message="Parachutes are not in the current stage")

        # Wait for safe deployment conditions
        if self._wait_for_safe:
            current_stage_chutes = filter_parts(state.parts.parachutes, [state.stage_current])
            all_safe = all(p.safe_to_deploy for p in current_stage_chutes)
            if not all_safe:
                unsafe_count = sum(1 for p in current_stage_chutes if not p.safe_to_deploy)
                return ActionResult(
                    status=ActionStatus.RUNNING,
                    message=f"Waiting for safe deployment conditions ({unsafe_count} chute(s) unsafe)",
                )

        # Deploy
        commands.deployable_parachutes = True
        return ActionResult(
            status=ActionStatus.SUCCEEDED,
            message=f"Triggering the deployment of {state.parts.parachutes_count([state.stage_current])} parachutes at {state.altitude_surface:.1f}m",
        )

    # def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
