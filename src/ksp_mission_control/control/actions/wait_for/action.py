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
    VesselSituation,
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
            param_id="above_current_thrust",
            label="Above Current Thrust",
            description=("Wait until the vessel's current thrust is above this threshold before proceeding."),
            required=False,
            param_type=ParamType.FLOAT,
            default=None,
        ),
        ActionParam(
            param_id="below_current_thrust",
            label="Below Current Thrust",
            description=("Wait until the vessel's current thrust is below this threshold before proceeding."),
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
            param_id="below_time_to_impact",
            label="Below Time to Impact",
            description=(
                "Wait until the estimated seconds until surface impact (assuming constant descent rate) "
                "are below this threshold. Only triggers while the vessel is descending."
            ),
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
        ActionParam(
            param_id="biome",
            label="Biome",
            description="Wait until the vessel is in this biome before proceeding.",
            required=False,
            param_type=ParamType.STR,
            default=None,
        ),
        ActionParam(
            param_id="situation",
            label="Situation",
            description="Wait until the vessel is in this situation before proceeding.",
            required=False,
            param_type=ParamType.STR,
            default=None,
        ),
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        self._apoapsis: bool = bool(param_values["apoapsis"])
        self._periapsis: bool = bool(param_values["periapsis"])
        raw_above_altitude = param_values["above_altitude"]
        self._above_altitude: float | None = float(raw_above_altitude) if raw_above_altitude is not None else None
        raw_below_altitude = param_values["below_altitude"]
        self._below_altitude: float | None = float(raw_below_altitude) if raw_below_altitude is not None else None
        raw_above_thrust = param_values["above_available_thrust"]
        self._above_available_thrust: float | None = float(raw_above_thrust) if raw_above_thrust is not None else None
        raw_below_thrust = param_values["below_available_thrust"]
        self._below_available_thrust: float | None = float(raw_below_thrust) if raw_below_thrust is not None else None
        raw_above_current_thrust = param_values["above_current_thrust"]
        self._above_current_thrust: float | None = float(raw_above_current_thrust) if raw_above_current_thrust is not None else None
        raw_below_current_thrust = param_values["below_current_thrust"]
        self._below_current_thrust: float | None = float(raw_below_current_thrust) if raw_below_current_thrust is not None else None
        raw_apoapsis_above = param_values["apoapsis_above"]
        self._apoapsis_above: float | None = float(raw_apoapsis_above) if raw_apoapsis_above is not None else None
        raw_above_dynamic_pressure = param_values["above_dynamic_pressure"]
        self._above_dynamic_pressure: float | None = float(raw_above_dynamic_pressure) if raw_above_dynamic_pressure is not None else None
        raw_below_time_to_impact = param_values["below_time_to_impact"]
        self._below_time_to_impact: float | None = float(raw_below_time_to_impact) if raw_below_time_to_impact is not None else None
        raw_time = param_values["time"]
        self._time: float | None = float(raw_time) if raw_time is not None else None
        self._start_action_time: float = state.universal_time
        self._biome: str | None = param_values["biome"]
        raw_situation = param_values["situation"]
        self._situation: VesselSituation | None = VesselSituation(raw_situation.lower()) if raw_situation is not None else None

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:

        if self._apoapsis and not state.orbit_apoapsis_passed:
            return ActionResult(status=ActionStatus.RUNNING, message=f"Waiting for apoapsis ({state.orbit_apoapsis_time_to:,.0f}s)")

        if self._periapsis and not state.orbit_periapsis_passed:
            return ActionResult(status=ActionStatus.RUNNING, message=f"Waiting for periapsis ({state.orbit_periapsis_time_to:,.0f}s)")

        if self._above_altitude is not None and state.altitude_surface < self._above_altitude:
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(f"Waiting for altitude > {self._above_altitude:,.0f}m (current: {state.altitude_surface:,.1f}m)"),
            )

        if self._below_altitude is not None and state.altitude_surface > self._below_altitude:
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(f"Waiting for altitude < {self._below_altitude:,.0f}m (current: {state.altitude_surface:,.1f}m)"),
            )

        if self._above_available_thrust is not None and state.thrust_available < self._above_available_thrust:
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(f"Waiting for available thrust > {self._above_available_thrust:,.1f}kN (current: {state.thrust_available:,.1f}kN)"),
            )

        if self._below_available_thrust is not None and state.thrust_available > self._below_available_thrust:
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(f"Waiting for available thrust < {self._below_available_thrust:,.1f}kN (current: {state.thrust_available:,.1f}kN)"),
            )

        if self._above_current_thrust is not None and state.thrust < self._above_current_thrust:
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(f"Waiting for current thrust > {self._above_current_thrust:,.1f}kN (current: {state.thrust:,.1f}kN)"),
            )

        if self._below_current_thrust is not None and state.thrust > self._below_current_thrust:
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(f"Waiting for current thrust < {self._below_current_thrust:,.1f}kN (current: {state.thrust:,.1f}kN)"),
            )

        if self._apoapsis_above is not None and state.orbit_apoapsis < self._apoapsis_above:
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(f"Waiting for apoapsis > {self._apoapsis_above:,.0f}m (current: {state.orbit_apoapsis:,.0f}m)"),
            )

        if self._above_dynamic_pressure is not None and state.pressure_dynamic < self._above_dynamic_pressure:
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(f"Waiting for dynamic pressure > {self._above_dynamic_pressure:,.1f}Pa (current: {state.pressure_dynamic:,.1f}Pa)"),
            )

        if self._below_time_to_impact is not None and state.altitude_time_to_impact > self._below_time_to_impact:
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(f"Waiting for time to impact < {self._below_time_to_impact:,.1f}s (current: {state.altitude_time_to_impact:,.1f}s)"),
            )

        if self._time is not None and (state.universal_time - self._start_action_time) < self._time:
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(f"Waiting for time > {self._time:.1f}s (elapsed: {state.universal_time - self._start_action_time:.1f}s)"),
            )

        if self._biome is not None and state.position_biome != self._biome:
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(f"Waiting for biome {self._biome!r} (current: {state.position_biome!r})"),
            )

        if self._situation is not None and state.situation != self._situation:
            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(f"Waiting for situation {self._situation.value!r} (current: {state.situation.value!r})"),
            )

        return ActionResult(status=ActionStatus.SUCCEEDED, message="All conditions met. Wait finished.")

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        pass
