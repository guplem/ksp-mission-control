"""AerobreakAction - Perform an aerobrake maneuver to reduce speed in the atmosphere.

This action assumes the vessel is on a trajectory entering the atmosphere.
It points the vessel retrograde and uses two braking phases:

1. Aero phase: while dynamic pressure is high, throttle up to help atmospheric
   drag bleed speed. Ease off when pressure is low.
2. Engine brake phase: as the vessel approaches the target altitude, compute the
   braking distance needed (accounting for gravity accelerating the vessel during
   descent) and fire engines at the right moment to reach target_speed by
   target_altitude.

The action completes when altitude <= target_altitude and speed <= target_speed.
"""

from __future__ import annotations

from typing import Any, ClassVar

from ksp_mission_control.control.actions.base import (
    Action,
    ActionLogger,
    ActionParam,
    ActionResult,
    ActionStatus,
    AutopilotDirection,
    ParamType,
    ReferenceFrame,
    State,
    VesselCommands,
)

# Retrograde direction in the orbital reference frame: -x = opposite of prograde
_RETROGRADE_DIRECTION = AutopilotDirection(
    vector=(-1.0, 0.0, 0.0),
    reference_frame=ReferenceFrame.VESSEL_ORBITAL,
)

# Safety margin multiplier for braking distance (start burn slightly early)
_BRAKE_MARGIN = 1.1


class AerobreakAction(Action):
    """Perform a controlled aerobrake maneuver to reduce speed in the atmosphere."""

    action_id: ClassVar[str] = "aerobreak"
    label: ClassVar[str] = "Aerobreak"
    description: ClassVar[str] = "Point retrograde and brake to a target speed at a target altitude"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="target_speed",
            label="Target Speed",
            description="The desired surface speed to slow down to.",
            required=False,
            param_type=ParamType.FLOAT,
            default=100.0,
            unit="m/s",
        ),
        ActionParam(
            param_id="target_altitude",
            label="Target Altitude",
            description="The altitude at which the target speed should be reached.",
            required=False,
            param_type=ParamType.FLOAT,
            default=5_000.0,
            unit="m",
        ),
        ActionParam(
            param_id="max_dynamic_pressure",
            label="Max Dynamic Pressure",
            description="The maximum dynamic pressure to allow during the brake.",
            required=False,
            param_type=ParamType.FLOAT,
            default=30_000.0,
            unit="Pa",
        ),
        ActionParam(
            param_id="auto_stage",
            label="Auto Stage",
            description="Automatically stage the vessel if the current stage runs out of thrust.",
            required=False,
            param_type=ParamType.BOOL,
            default=False,
        ),
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        self._target_speed: float = float(param_values["target_speed"])
        if self._target_speed < 0.0:
            raise ValueError("Invalid target speed: must be non-negative.")

        self._target_altitude: float = float(param_values["target_altitude"])
        if self._target_altitude < 0.0:
            raise ValueError("Invalid target altitude: must be non-negative.")

        self._max_dynamic_pressure: float = float(param_values["max_dynamic_pressure"])
        self._auto_stage: bool = bool(param_values["auto_stage"])
        self._engine_brake_started: bool = False

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        # Point retrograde
        commands.autopilot = True
        commands.autopilot_direction = _RETROGRADE_DIRECTION

        # Check completion: at or below target altitude with speed under target
        if state.altitude_surface <= self._target_altitude and state.speed_surface <= self._target_speed:
            return ActionResult(
                status=ActionStatus.SUCCEEDED,
                message=f"Target reached: {state.speed_surface:.1f}m/s at {state.altitude_surface:.0f}m",
            )

        # Check if we have thrust available. If not, either auto-stage or fail.
        if state.thrust_available <= 0:
            if self._auto_stage:
                if state.parts.engines_inactive() > 0:
                    commands.stage = True
                    return ActionResult(
                        status=ActionStatus.RUNNING,
                        message=f"Staging to next stage. {state.parts.engines_inactive()} inactive engines still in the vessel.",  # noqa: E501
                    )
                else:
                    return ActionResult(
                        status=ActionStatus.FAILED,
                        message=f"No thrust available. Speed {state.speed_surface:.1f}m/s, target {self._target_speed:.1f}m/s",  # noqa: E501
                    )
            else:
                return ActionResult(
                    status=ActionStatus.FAILED,
                    message=f"No thrust available and staging disabled. Speed {state.speed_surface:.1f}m/s, target {self._target_speed:.1f}m/s",  # noqa: E501
                )

        # --- Braking distance calculation ---
        # How much altitude remains before the target altitude
        altitude_remaining = state.altitude_surface - self._target_altitude

        # How much speed we still need to lose
        speed_to_lose = state.speed_surface - self._target_speed

        # Max engine deceleration (thrust opposing velocity)
        engine_decel = state.thrust_available / state.mass if state.mass > 0 else 0.0

        # Net deceleration: engines brake, but gravity accelerates the vessel
        # during descent. The effective braking power is reduced by gravity.
        net_decel = engine_decel - state.body_gravity

        # Calculate braking distance: d = (v_current^2 - v_target^2) / (2 * a_net)
        # This is the altitude the vessel will cover while decelerating from
        # current speed to target speed, assuming roughly vertical descent.
        if net_decel > 0 and speed_to_lose > 0:
            braking_distance = (state.speed_surface**2 - self._target_speed**2) / (2.0 * net_decel)
        else:
            # Engines can't overcome gravity, or already at target speed
            braking_distance = float("inf")

        # --- Phase selection ---
        should_engine_brake = altitude_remaining <= braking_distance * _BRAKE_MARGIN and speed_to_lose > 0

        if should_engine_brake:
            # Engine brake phase: full throttle to hit target speed by target altitude
            if not self._engine_brake_started:
                self._engine_brake_started = True
                log.info(
                    f"Engine brake started at {state.altitude_surface:.0f}m "
                    f"(braking distance {braking_distance:.0f}m, altitude remaining {altitude_remaining:.0f}m)"
                )
            commands.throttle = 1.0

            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(
                    f"Engine brake: {state.speed_surface:.1f}m/s -> {self._target_speed:.1f}m/s, "
                    f"alt {state.altitude_surface:.0f}m -> {self._target_altitude:.0f}m"
                ),
            )
        else:
            # Aero phase: use dynamic pressure to decide throttle
            # High pressure = moving too fast through atmosphere, throttle up to help brake.
            # Low pressure = aero drag is manageable, ease off engines.
            self._engine_brake_started = False
            min_throttle = 0.0

            if state.pressure_dynamic > self._max_dynamic_pressure:
                log.debug(
                    f"Dynamic pressure {state.pressure_dynamic:.1f}Pa exceeds {self._max_dynamic_pressure:.0f}Pa, throttling up to brake"  # noqa: E501
                )
                commands.throttle = min(1.0, state.control_throttle + 0.1)
            elif state.control_throttle > min_throttle:
                log.debug(f"Dynamic pressure {state.pressure_dynamic:.1f}Pa below {self._max_dynamic_pressure:.0f}Pa, easing off")
                commands.throttle = max(min_throttle, state.control_throttle - 0.1)

            return ActionResult(
                status=ActionStatus.RUNNING,
                message=(
                    f"Aero brake: {state.speed_surface:.1f}m/s, alt {state.altitude_surface:.0f}m "
                    f"(engine brake in {altitude_remaining - braking_distance * _BRAKE_MARGIN:.0f}m)"
                ),
            )

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        commands.throttle = 0.0
