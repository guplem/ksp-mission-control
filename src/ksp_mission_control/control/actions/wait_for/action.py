"""WaitForAction - Waits for all conditions to be met before activating science experiments.

Conditions can include reaching apoapsis, reaching a minimum altitude, or other vessel states.
Useful for sequencing actions that require specific flight conditions.
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


class WaitForAction(Action):
    """Wait for specific flight conditions."""

    action_id: ClassVar[str] = "wait_for"
    label: ClassVar[str] = "Wait for Conditions"
    description: ClassVar[str] = "Wait until all specified conditions are met"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="apoapsis",
            label="Apoapsis Reached",
            description="Wait until the periapsis is the next apse",
            required=False,
            param_type=ParamType.BOOL,
            default=False,
        ),
        ActionParam(
            param_id="periapsis",
            label="Periapsis Reached",
            description="Wait until the apoapsis is the next apse",
            required=False,
            param_type=ParamType.BOOL,
            default=False,
        ),
        ActionParam(
            param_id="above_altitude",
            label="Above Altitude",
            description=("Wait until the vessel is above this altitude before proceeding."),
            required=False,
            param_type=ParamType.FLOAT,
            default=None,
        ),
        ActionParam(
            param_id="below_altitude",
            label="Below Altitude",
            description=("Wait until the vessel is below this altitude before proceeding."),
            required=False,
            param_type=ParamType.FLOAT,
            default=None,
        ),
        ActionParam(
            param_id="above_available_thrust",
            label="Above Available Thrust",
            description=("Wait until the vessel's available thrust is above this threshold before proceeding."),
            required=False,
            param_type=ParamType.FLOAT,
            default=None,
        ),
        ActionParam(
            param_id="below_available_thrust",
            label="Below Available Thrust",
            description=("Wait until the vessel's available thrust is below this threshold before proceeding."),
            required=False,
            param_type=ParamType.FLOAT,
            default=None,
        ),
        ActionParam(
            param_id="apoapsis_above",
            label="Apoapsis Above",
            description="Wait until the orbit apoapsis is above this altitude (meters) before proceeding.",
            required=False,
            param_type=ParamType.FLOAT,
            default=None,
        ),
        ActionParam(
            param_id="above_dynamic_pressure",
            label="Above Dynamic Pressure",
            description="Wait until dynamic pressure is above this threshold (Pascals) before proceeding.",
            required=False,
            param_type=ParamType.FLOAT,
            default=None,
        ),
        ActionParam(
            param_id="time",
            label="Time",
            description="Wait for a specified amount of time (seconds) before proceeding.",
            required=False,
            param_type=ParamType.FLOAT,
            default=None,
        ),
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        self._apoapsis: bool = bool(param_values.get("apoapsis", False))
        self._periapsis: bool = bool(param_values.get("periapsis", False))
        self._above_altitude: float | None = param_values.get("above_altitude")
        self._below_altitude: float | None = param_values.get("below_altitude")
        self._above_available_thrust: float | None = param_values.get("above_available_thrust")
        self._below_available_thrust: float | None = param_values.get("below_available_thrust")
        self._apoapsis_above: float | None = param_values.get("apoapsis_above")
        self._above_dynamic_pressure: float | None = param_values.get("above_dynamic_pressure")
        self._time: float | None = param_values.get("time")
        self._start_action_time: float = state.universal_time

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:

        if self._apoapsis and not state.orbit_apoapsis_passed:
            return ActionResult(status=ActionStatus.RUNNING, message=f"Waiting for apoapsis ({state.orbit_apoapsis_time_to:.0f}s)")

        if self._periapsis and not state.orbit_periapsis_passed:
            return ActionResult(status=ActionStatus.RUNNING, message=f"Waiting for periapsis ({state.orbit_periapsis_time_to:.0f}s)")

        if self._above_altitude is not None and state.altitude_surface < self._above_altitude:
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(f"Waiting for altitude > {self._above_altitude:.0f}m (current: {state.altitude_surface:.1f}m)"),
            )

        if self._below_altitude is not None and state.altitude_surface > self._below_altitude:
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(f"Waiting for altitude < {self._below_altitude:.0f}m (current: {state.altitude_surface:.1f}m)"),
            )

        if self._above_available_thrust is not None and state.thrust_available < self._above_available_thrust:
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(f"Waiting for available thrust > {self._above_available_thrust:.1f}kN (current: {state.thrust_available:.1f}kN)"),
            )

        if self._below_available_thrust is not None and state.thrust_available > self._below_available_thrust:
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(f"Waiting for available thrust < {self._below_available_thrust:.1f}kN (current: {state.thrust_available:.1f}kN)"),
            )

        if self._apoapsis_above is not None and state.orbit_apoapsis < self._apoapsis_above:
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(f"Waiting for apoapsis > {self._apoapsis_above:.0f}m (current: {state.orbit_apoapsis:.0f}m)"),
            )

        if self._above_dynamic_pressure is not None and state.pressure_dynamic < self._above_dynamic_pressure:
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(f"Waiting for dynamic pressure > {self._above_dynamic_pressure:.1f}Pa (current: {state.pressure_dynamic:.1f}Pa)"),
            )

        if self._time is not None and (state.universal_time - self._start_action_time) < self._time:
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(f"Waiting for time > {self._time:.1f}s (elapsed: {state.universal_time - self._start_action_time:.1f}s)"),
            )

        return ActionResult(status=ActionStatus.SUCCEEDED, message="All conditions met. Wait finished.")

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)
