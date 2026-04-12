"""TranslateAction - hovering translation to move N/S/E/W while holding altitude.

Uses the same cascaded velocity controller as HoverAction for altitude hold.
Horizontal movement is driven by RCS translation, decomposed from world-space
(north/east) into vessel-relative (forward/right) based on current heading.
Position is tracked via latitude/longitude coordinates converted to meters
using the body's equatorial radius.
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
    SASMode,
    VesselCommands,
    VesselState,
)

# --- Altitude hold (same gains as HoverAction) ---
_SPEED_GAIN = 0.5  # m/s desired vertical speed per meter of altitude error
_MAX_APPROACH_SPEED = 50.0  # cap on vertical climb/descent rate (m/s)
_KP_SPEED = 0.2  # throttle adjustment per m/s of vertical speed error

# --- Horizontal translation ---
_HORIZONTAL_GAIN = 0.1  # RCS input per meter of remaining distance
_ARRIVAL_DISTANCE = 2.0  # meters: consider target reached below this
_ARRIVAL_SPEED = 1.0  # m/s: must be slower than this to complete
_BRAKING_GAIN = 0.2  # RCS braking input per m/s of excess surface speed


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


class TranslateAction(Action):
    """Move horizontally while holding altitude using RCS translation."""

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
        # Capture starting coordinates for displacement calculation
        self._start_latitude: float = state.latitude
        self._start_longitude: float = state.longitude
        self._body_radius: float = state.body_radius

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

        # --- Completion check ---
        if remaining_distance < _ARRIVAL_DISTANCE and state.surface_speed < _ARRIVAL_SPEED:
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

        # --- Orientation: point up, RCS for translation ---
        commands.sas = True
        commands.sas_mode = SASMode.RADIAL
        commands.rcs = True

        # --- Horizontal RCS control ---
        # Desired velocity: proportional to remaining distance, capped at max_speed
        if remaining_distance > 0:
            scale = min(self._max_speed, _HORIZONTAL_GAIN * remaining_distance * self._max_speed)
            desired_north_speed = (remaining_north / remaining_distance) * scale
            desired_east_speed = (remaining_east / remaining_distance) * scale
        else:
            desired_north_speed = 0.0
            desired_east_speed = 0.0

        # Estimate current velocity components from heading + surface speed
        heading_rad = math.radians(state.heading)
        north_speed = state.surface_speed * math.cos(heading_rad)
        east_speed = state.surface_speed * math.sin(heading_rad)

        # Braking: compare desired vs actual velocity
        north_speed_error = desired_north_speed - north_speed
        east_speed_error = desired_east_speed - east_speed

        # Convert world-space velocity error to vessel-relative axes
        # Forward = cos(heading) * north + sin(heading) * east
        # Right   = -sin(heading) * north + cos(heading) * east
        raw_forward = _BRAKING_GAIN * (
            math.cos(heading_rad) * north_speed_error + math.sin(heading_rad) * east_speed_error
        )
        raw_right = _BRAKING_GAIN * (
            -math.sin(heading_rad) * north_speed_error + math.cos(heading_rad) * east_speed_error
        )

        commands.translate_forward = max(-1.0, min(1.0, raw_forward))
        commands.translate_right = max(-1.0, min(1.0, raw_right))

        log.debug(
            f"translate: remaining N={remaining_north:+.1f}m E={remaining_east:+.1f}m "
            f"dist={remaining_distance:.1f}m  "
            f"fwd={commands.translate_forward:+.2f} right={commands.translate_right:+.2f}  "
            f"alt_err={altitude_error:+.1f}m throttle={commands.throttle:.3f}"
        )

        return ActionResult(status=ActionStatus.RUNNING)

    def stop(self, state: VesselState, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)
