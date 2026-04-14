"""LaunchAction - ascent to target apoapsis with gravity turn.

Launches the vessel from the pad (or ground) and performs a gravity turn
to reach a target apoapsis altitude. Cuts engines once the apoapsis is
reached, leaving circularization to a separate action.

Phases
------
1. **Vertical ascent**: Full throttle straight up until turn_start_altitude.
2. **Gravity turn**: Gradually pitch from 90 deg toward the horizon between
   turn_start_altitude and turn_end_altitude, following the target
   inclination heading.
3. **Coast to apoapsis**: Once pitch is near horizontal, hold prograde and
   throttle to maintain apoapsis target without overshooting.
4. **Complete**: Cut engines when apoapsis reaches target_altitude.

Parameter defaults
------------------
All parameters are nullable. When None, they are inferred from the current
body's properties at start():

- target_altitude: body_atmosphere_depth * 1.1 (or 50km if no atmosphere)
- target_inclination: 0 (equatorial, eastward launch)
- turn_start_altitude: ~1000m (just enough to clear the pad and build speed)
- turn_end_altitude: 0.7 * target_altitude
"""

from __future__ import annotations

from math import asin, cos, degrees, radians, sin
from typing import Any, ClassVar

from ksp_mission_control.control.actions.base import (
    Action,
    ActionLogger,
    ActionParam,
    ActionResult,
    ActionStatus,
    ParamType,
    SpeedMode,
    VesselCommands,
    VesselState,
)

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

_APOAPSIS_TOLERANCE_MULTIPLIER = 0.002  # fraction of target altitude to consider "close enough" to apoapsis
_GRAVITY_TURN_CLEARANCE = 50  # meters: altitude to start gravity turn to avoid ground collision
_DEFAULT_ALTITUDE_ATMOSPHERE_MULTIPLIER = 1.1  # multiplier: default target = atmosphere_depth * this
_DEFAULT_ALTITUDE_AIRLESS_BODY = 50_000.0  # meters: default target when body has no atmosphere
_DEFAULT_TURN_END_FRACTION = 0.7  # fraction of target altitude where pitch reaches horizontal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _inclination_to_heading(inclination_deg: float, latitude_deg: float = 0.0) -> float:
    """Convert an orbital inclination (degrees) to a launch compass heading.

    Uses the spherical geometry relation:
        sin(heading) = cos(inclination) / cos(latitude)

    0 deg inclination = due east (heading 90).
    90 deg inclination = due north (heading 0).
    Negative inclination = launch southeast (heading > 90).

    If the desired inclination is less than the launch latitude (geometrically
    impossible), clamps to the nearest reachable heading (due east/west).

    Returns heading in [0, 360).
    """
    cos_inc = cos(radians(abs(inclination_deg)))
    cos_lat = cos(radians(latitude_deg))

    # Clamp for impossible inclinations (inc < latitude).
    sin_heading = min(1.0, cos_inc / cos_lat) if cos_lat > 0 else 1.0

    heading = degrees(asin(sin_heading))

    # Negative inclination means launch southeast instead of northeast.
    if inclination_deg < 0:
        heading = 180.0 - heading

    return heading % 360.0


# ---------------------------------------------------------------------------
# Action
# ---------------------------------------------------------------------------


class LaunchAction(Action):
    """Ascend from the pad to a target apoapsis via gravity turn."""

    action_id: ClassVar[str] = "launch"
    label: ClassVar[str] = "Launch"
    description: ClassVar[str] = "Ascend to target apoapsis with gravity turn"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="target_altitude",
            label="Target Altitude",
            description=(
                f"Target apoapsis altitude (default: {_DEFAULT_ALTITUDE_ATMOSPHERE_MULTIPLIER:.0%} of atmosphere, or {_DEFAULT_ALTITUDE_AIRLESS_BODY:.0f}m)"
            ),
            required=False,
            param_type=ParamType.FLOAT,
            default=None,
            unit="m",
        ),
        ActionParam(
            param_id="target_inclination",
            label="Target Inclination",
            description="Orbital inclination in degrees (default: 0 = current inclination)",
            required=False,
            param_type=ParamType.FLOAT,
            default=None,
            unit="deg",
        ),
        ActionParam(
            param_id="turn_start_altitude",
            label="Turn Start Altitude",
            description=f"Altitude to begin gravity turn (default: {_GRAVITY_TURN_CLEARANCE}m above initial altitude)",
            required=False,
            param_type=ParamType.FLOAT,
            default=None,
            unit="m",
        ),
        ActionParam(
            param_id="turn_end_altitude",
            label="Turn End Altitude",
            description=f"Altitude where pitch reaches horizontal (default: {_DEFAULT_TURN_END_FRACTION:.0%} of target)",
            required=False,
            param_type=ParamType.FLOAT,
            default=None,
            unit="m",
        ),
    ]

    def _pitch_for_altitude(
        self,
        altitude: float,
        turn_start: float,
        turn_end: float,
    ) -> float:
        """Compute the target pitch angle for the current altitude.

        Returns 90 (straight up) below turn_start, 0 (horizontal) above
        turn_end, and a smooth interpolation in between.

        Parameters
        ----------
        altitude : current altitude above sea level
        turn_start : altitude where the gravity turn begins
        turn_end : altitude where pitch reaches ~0 (horizontal)

        Returns a pitch angle in degrees [0, 90].
        """
        actual_turn_start = max(self._initial_altitude + _GRAVITY_TURN_CLEARANCE, turn_start)  # ensure we start after clearing the pad
        progress = (altitude - actual_turn_start) / (turn_end - actual_turn_start)  # percent of turn completed
        progress = max(0, min(1, progress))  # clamp to [0, 1]
        target_pitch = sin(progress) * 90  # smoothly interpolate from 90 to 0
        return target_pitch

    # -- Lifecycle ------------------------------------------------------------

    def start(self, state: VesselState, param_values: dict[str, Any]) -> None:
        # Snapshot initial altitude so _pitch_for_altitude can reference it.
        self._initial_altitude: float = state.altitude_sea

        # Resolve target_altitude: use provided value, or infer from body.
        raw_altitude = param_values.get("target_altitude")
        if raw_altitude is not None:
            self._target_altitude: float = float(raw_altitude)
        elif state.body_has_atmosphere:
            self._target_altitude = state.body_atmosphere_depth * _DEFAULT_ALTITUDE_ATMOSPHERE_MULTIPLIER
        else:
            self._target_altitude = _DEFAULT_ALTITUDE_AIRLESS_BODY

        # Compute tolerance for considering apoapsis "close enough" to target.
        self.tolerance_altitude = self._target_altitude * _APOAPSIS_TOLERANCE_MULTIPLIER

        # Resolve target_inclination: use provided value, or default to 0.
        raw_inclination = param_values.get("target_inclination")
        if raw_inclination is not None:
            self._target_inclination: float = float(raw_inclination)
        else:
            self._target_inclination = state.inclination

        # Resolve turn_start_altitude: use provided value, or default to
        # 50m above the initial altitude (just enough to clear the pad).
        raw_turn_start = param_values.get("turn_start_altitude")
        if raw_turn_start is not None:
            self._turn_start_altitude: float = float(raw_turn_start)
        else:
            self._turn_start_altitude = self._initial_altitude

        # Resolve turn_end_altitude: use provided value, or default to 70% of target.
        raw_turn_end = param_values.get("turn_end_altitude")
        if raw_turn_end is not None:
            self._turn_end_altitude: float = float(raw_turn_end)
        else:
            self._turn_end_altitude = self._target_altitude * _DEFAULT_TURN_END_FRACTION

        # Compute the launch heading from the target inclination.
        self._launch_heading: float = _inclination_to_heading(self._target_inclination, state.latitude)

    def tick(self, state: VesselState, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:

        # Check if finished
        if state.apoapsis >= self._target_altitude - self.tolerance_altitude:
            return ActionResult(status=ActionStatus.SUCCEEDED, message="Target apoapsis reached")

        # General Configuration
        commands.speed_mode = SpeedMode.ORBIT  # show orbital speed on navball
        commands.autopilot = True

        # Rotation
        if state.altitude_surface > _GRAVITY_TURN_CLEARANCE:
            commands.autopilot_roll = 0  # For the time being, just go east
            # commands.autopilot_roll = self._launch_heading  # keep the vessel pointed in the right compass direction for the desired inclination

            if state.autopilot_roll_error and ((state.autopilot_roll_error < 5) or (state.autopilot_roll_error > -5)):
                commands.autopilot_pitch = self._pitch_for_altitude(state.altitude_sea, self._turn_start_altitude, self._turn_end_altitude)

        # Throttle control
        commands.throttle = 1.0  # full throttle until we reach apoapsis

        if state.available_thrust <= 1:
            commands.stage = True
            log.info(f"Staging stage {state.current_stage} due to insufficient thrust({state.available_thrust}N)")

        if state.engines_flamed_out > 0:
            commands.stage = True
            log.info(f"Staging. {state.engines_flamed_out} engine(s) have flamed out ")

        log.debug(f"Dynamic pressure: {(state.dynamic_pressure / 1000):.1f}kPa ")

        return ActionResult(status=ActionStatus.RUNNING)

    def stop(self, state: VesselState, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)
        # Cut engines and disengage autopilot on stop/abort.
        commands.autopilot = False
        commands.sas = False
        commands.throttle = 0.0
