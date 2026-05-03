"""SuborbitalLaunchAction - Perform a suborbital launch to a target altitude.

This action sets the suborbital launch level for the vessel, which controls the throttle of the engines during a suborbital ascent.
The action can be configured with either a specific altitude or just above the atmosphere.
Staging can be handled automatically.
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


class SuborbitalLaunchAction(Action):
    """Perform a suborbital launch to a target altitude."""

    action_id: ClassVar[str] = "suborbital_launch"
    label: ClassVar[str] = "Suborbital Launch"
    description: ClassVar[str] = "Perform a suborbital launch to a target altitude"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="target_altitude",
            label="Target Altitude",
            description="The desired target altitude for the suborbital launch. Above atmosphere if not set.",
            required=False,
            param_type=ParamType.FLOAT,
            default=None,
        ),
        ActionParam(
            param_id="auto_stage",
            label="Auto Stage",
            description="Automatically stage the vessel during the suborbital launch if the current stage runs out of thrust.",
            required=False,
            param_type=ParamType.BOOL,
            default=False,
        ),
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        # Save target altitude
        target_altitude = param_values["target_altitude"]
        self._target_altitude: float = (
            float(target_altitude)
            if target_altitude is not None
            else state.body_atmosphere_depth + 1000.0  # 1km above atmosphere if no target altitude specified
        )
        if self._target_altitude <= 0.0:
            raise ValueError("Invalid target altitude: must be positive.")

        # Save auto-stage setting
        self._auto_stage: bool = bool(param_values["auto_stage"])

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:

        # Handle heading control: point straight up
        commands.autopilot = True
        commands.autopilot_pitch = 90.0  # straight up

        # Check if we have thrust available. If not, either auto-stage or fail.
        if state.thrust_available <= 0:
            if self._auto_stage:
                if state.parts.engines_inactive() > 0:
                    commands.stage = True
                else:
                    return ActionResult(
                        status=ActionStatus.FAILED,
                        message=f"No thrust available. Current apoapsis is {state.orbit_apoapsis:.1f}m, target altitude is {self._target_altitude:.1f}m",
                    )
            else:
                return ActionResult(
                    status=ActionStatus.FAILED,
                    message=f"No thrust available and staging disabled. Current apoapsis is {state.orbit_apoapsis:.1f}m, target altitude is {self._target_altitude:.1f}m",  # noqa: E501
                )

        # Throttle control
        if state.orbit_apoapsis < self._target_altitude:
            commands.throttle = 1.0  # Full throttle until we reach the target altitude
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=f"Ascending: current apoapsis {state.orbit_apoapsis:.1f}m / target {self._target_altitude:.1f}m",
            )
        return ActionResult(status=ActionStatus.SUCCEEDED, message=f"Target apoapsis set: {state.orbit_apoapsis:.1f}m")

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)
