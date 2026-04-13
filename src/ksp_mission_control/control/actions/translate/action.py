"""TranslateAction - orient-then-translate horizontal movement.

Strategy:
  1. Orient: engage the kRPC autopilot targeting pitch=90 (upright) and
     heading toward the destination. Wait until heading aligns.
  2. Translate: use translate_forward (RCS) to move toward the target.
     A velocity P controller ramps up to max_speed and brakes on approach.

Altitude is held throughout using the same cascaded velocity controller as
HoverAction. Position is tracked via lat/lon coordinates.
"""

from __future__ import annotations

import math
from typing import Any, ClassVar

from ksp_mission_control.control.actions.base import (
    Action,
    ActionLogger,
    ActionParam,
    ActionResult,
    ActionStatus,
    ParamType,
    VesselCommands,
    VesselState,
)

# --- Altitude hold (same gains as HoverAction) ---
_SPEED_GAIN = 0.5  # m/s desired vertical speed per meter of altitude error
_MAX_APPROACH_SPEED = 50.0  # cap on vertical climb/descent rate (m/s)
_KP_SPEED = 0.2  # throttle adjustment per m/s of vertical speed error

# --- Heading control ---
_HEADING_ALIGNED_THRESHOLD = 10.0  # degrees: heading close enough to start translating

# --- Horizontal translation ---
_HORIZONTAL_GAIN = 0.1  # desired speed per meter of remaining distance (scales with max_speed)
_FORWARD_GAIN = 0.2  # translate_forward per m/s of forward velocity error
_ARRIVAL_DISTANCE = 2.0  # meters: consider target reached below this
_ARRIVAL_SPEED = 1.0  # m/s: must be slower than this to complete


def _lat_lon_to_meters(
    lat: float,
    lon: float,
    ref_lat: float,
    ref_lon: float,
    body_radius: float,
) -> tuple[float, float]:
    """Convert lat/lon displacement from a reference point to meters (north, east).

    Uses a flat-Earth approximation valid for small distances (< ~10 km).
    """
    north = math.radians(lat - ref_lat) * body_radius
    east = math.radians(lon - ref_lon) * math.cos(math.radians(ref_lat)) * body_radius
    return north, east


def _target_heading(remaining_north: float, remaining_east: float) -> float:
    """Compute the heading (0-360) from the vessel toward the target.

    0 = north, 90 = east, 180 = south, 270 = west.
    """
    rad = math.atan2(remaining_east, remaining_north)
    deg = math.degrees(rad)
    return deg % 360.0


def _heading_error(target: float, current: float) -> float:
    """Signed heading error in degrees, normalized to [-180, 180].

    Positive = target is clockwise from current (yaw right).
    """
    error = target - current
    error = (error + 180.0) % 360.0 - 180.0
    return error


class TranslateAction(Action):
    """Move horizontally while holding altitude using orient-then-translate."""

    action_id: ClassVar[str] = "translate"
    label: ClassVar[str] = "Translate"
    description: ClassVar[str] = "Move N/S/E/W while holding altitude"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="distance_north",
            label="Distance North",
            description="Meters to move north (negative = south)",
            required=False,
            param_type=ParamType.FLOAT,
            default=0.0,
            unit="m",
        ),
        ActionParam(
            param_id="distance_east",
            label="Distance East",
            description="Meters to move east (negative = west)",
            required=False,
            param_type=ParamType.FLOAT,
            default=0.0,
            unit="m",
        ),
        ActionParam(
            param_id="max_speed",
            label="Max Speed",
            description="Maximum horizontal speed during translation",
            required=False,
            param_type=ParamType.FLOAT,
            default=10.0,
            unit="m/s",
        ),
    ]

    def start(self, state: VesselState, param_values: dict[str, Any]) -> None:
        self._distance_north: float = float(param_values["distance_north"])
        self._distance_east: float = float(param_values["distance_east"])
        self._max_speed: float = float(param_values["max_speed"])
        self._target_altitude: float = state.altitude_surface
        self._start_latitude: float = state.latitude
        self._start_longitude: float = state.longitude
        self._body_radius: float = state.body_radius
        # Previous position for velocity estimation (position derivative)
        self._prev_traveled_north: float = 0.0
        self._prev_traveled_east: float = 0.0

    def tick(
        self, state: VesselState, commands: VesselCommands, dt: float, log: ActionLogger
    ) -> ActionResult:
        # --- Position from coordinates ---
        traveled_north, traveled_east = _lat_lon_to_meters(
            state.latitude,
            state.longitude,
            self._start_latitude,
            self._start_longitude,
            self._body_radius,
        )

        # --- Remaining distance ---
        remaining_north = self._distance_north - traveled_north
        remaining_east = self._distance_east - traveled_east
        remaining_distance = math.sqrt(remaining_north**2 + remaining_east**2)

        # --- Actual velocity from position derivative ---
        safe_dt = max(dt, 0.01)
        actual_north_velocity = (traveled_north - self._prev_traveled_north) / safe_dt
        actual_east_velocity = (traveled_east - self._prev_traveled_east) / safe_dt
        self._prev_traveled_north = traveled_north
        self._prev_traveled_east = traveled_east
        actual_speed = math.sqrt(actual_north_velocity**2 + actual_east_velocity**2)

        # --- Completion check ---
        if remaining_distance < _ARRIVAL_DISTANCE and actual_speed < _ARRIVAL_SPEED:
            log.info(f"Target reached: traveled N={traveled_north:.1f}m E={traveled_east:.1f}m")
            return ActionResult(status=ActionStatus.SUCCEEDED)

        # --- Altitude hold (cascaded velocity controller, same as HoverAction) ---
        altitude_error = self._target_altitude - state.altitude_surface
        desired_vspeed = max(
            -_MAX_APPROACH_SPEED, min(_MAX_APPROACH_SPEED, _SPEED_GAIN * altitude_error)
        )
        speed_error = desired_vspeed - state.vertical_speed
        raw_throttle = 0.5 + _KP_SPEED * speed_error
        commands.throttle = max(0.0, min(1.0, raw_throttle))

        # --- Autopilot: hold current pitch, rotate heading toward target ---
        # Use the vessel's current pitch so the autopilot only controls heading
        # and doesn't fight the throttle-based altitude hold.
        commands.autopilot = True
        commands.autopilot_pitch = state.pitch
        commands.rcs = True
        # Disable SAS (autopilot handles orientation)
        commands.sas = False

        # --- Heading control ---
        target_hdg = _target_heading(remaining_north, remaining_east)
        commands.autopilot_heading = target_hdg
        hdg_error = _heading_error(target_hdg, state.heading)
        aligned = abs(hdg_error) < _HEADING_ALIGNED_THRESHOLD

        # --- Forward translation: only when heading is aligned ---
        if aligned:
            desired_forward_speed = min(
                self._max_speed,
                _HORIZONTAL_GAIN * remaining_distance * self._max_speed,
            )
            if remaining_distance > 0:
                actual_forward_speed = (
                    actual_north_velocity * remaining_north + actual_east_velocity * remaining_east
                ) / remaining_distance
            else:
                actual_forward_speed = 0.0
            forward_error = desired_forward_speed - actual_forward_speed
            commands.translate_forward = max(-1.0, min(1.0, _FORWARD_GAIN * forward_error))
        else:
            commands.translate_forward = 0.0

        phase = "translating" if aligned else "orienting"
        log.debug(
            f"translate [{phase}]: remaining N={remaining_north:+.1f}m E={remaining_east:+.1f}m "
            f"dist={remaining_distance:.1f}m  hdg_err={hdg_error:+.1f}deg  "
            f"fwd={commands.translate_forward:+.2f}  speed={actual_speed:.1f}m/s  "
            f"alt_err={altitude_error:+.1f}m throttle={commands.throttle:.3f}"
        )

        return ActionResult(status=ActionStatus.RUNNING)

    def stop(self, state: VesselState, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)
        commands.throttle = 0.0
        commands.autopilot = False
        commands.rcs = False
        commands.translate_forward = 0.0
