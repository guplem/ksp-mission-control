"""TranslateAction - multi-axis RCS horizontal movement.

Moves the vessel a specified number of meters North/South and East/West
using RCS translation on two axes (forward and right), while the main
engines maintain altitude.

Strategy
--------
Instead of rotating the vessel to face the target, this action keeps
the vessel's current orientation and decomposes the desired velocity
into vessel-relative axes:

  - **translate_forward**: RCS thrust along the vessel's forward axis
  - **translate_right**: RCS thrust along the vessel's right axis

The world-space desired velocity (north/east) is projected onto the
vessel's heading to compute how much forward and right RCS is needed.
This works regardless of which direction the vessel is facing.

Velocity control
----------------
A P controller ramps speed up toward max_speed when far from the
target, and reduces desired speed as the target approaches, giving
natural deceleration without a separate braking phase.

Altitude hold
-------------
A cascaded velocity controller (same as HoverAction) runs every tick.
It converts altitude error into a desired vertical speed, then adjusts
throttle to track that speed.

Position tracking
-----------------
Lat/lon coordinates are converted to meters using a flat-Earth
approximation. Velocity is estimated by differentiating position between
ticks.
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

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

# Altitude hold (cascaded velocity controller, same gains as HoverAction)
_SPEED_GAIN = 0.5  # m/s desired vertical speed per meter of altitude error
_MAX_APPROACH_SPEED = 50.0  # cap on vertical climb/descent rate (m/s)
_KP_SPEED = 0.2  # throttle adjustment per m/s of vertical speed error

# Horizontal velocity controller
_HORIZONTAL_GAIN = 0.1  # desired speed = gain * remaining_distance * max_speed
_RCS_GAIN = 0.2  # RCS axis output per m/s of velocity error

# Arrival / completion
_ARRIVAL_DISTANCE = 2.0  # meters: close enough to declare success
_ARRIVAL_SPEED = 1.0  # m/s: slow enough to declare success


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _lat_lon_to_meters(
    lat: float,
    lon: float,
    ref_lat: float,
    ref_lon: float,
    body_radius: float,
) -> tuple[float, float]:
    """Convert lat/lon offset from a reference point to (north, east) meters.

    Uses a flat-Earth approximation, accurate for distances under ~10 km.
    """
    north = math.radians(lat - ref_lat) * body_radius
    east = math.radians(lon - ref_lon) * math.cos(math.radians(ref_lat)) * body_radius
    return north, east


def _world_to_vessel(
    north: float,
    east: float,
    heading_deg: float,
) -> tuple[float, float]:
    """Project a world-space (north, east) vector onto vessel-relative (forward, right).

    Uses the vessel's current heading to rotate the vector. This lets us
    drive translate_forward and translate_right without rotating the vessel.

    Returns (forward_component, right_component).
    """
    heading_rad = math.radians(heading_deg)
    forward = north * math.cos(heading_rad) + east * math.sin(heading_rad)
    # kRPC's control.right axis is inverted: positive = left, negative = right.
    right = north * math.sin(heading_rad) - east * math.cos(heading_rad)
    return forward, right


# ---------------------------------------------------------------------------
# Action
# ---------------------------------------------------------------------------


class TranslateAction(Action):
    """Move horizontally while holding altitude using multi-axis RCS."""

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

    # -- Lifecycle ------------------------------------------------------------

    def start(self, state: VesselState, param_values: dict[str, Any]) -> None:
        self._distance_north: float = float(param_values["distance_north"])
        self._distance_east: float = float(param_values["distance_east"])
        self._max_speed: float = float(param_values["max_speed"])

        # Snapshot the starting position so we can measure displacement later.
        self._target_altitude: float = state.altitude_surface
        self._start_latitude: float = state.latitude
        self._start_longitude: float = state.longitude
        self._body_radius: float = state.body_radius

        # Used by the position-derivative velocity estimator.
        self._prev_traveled_north: float = 0.0
        self._prev_traveled_east: float = 0.0

    def tick(
        self, state: VesselState, commands: VesselCommands, dt: float, log: ActionLogger
    ) -> ActionResult:

        # ── 1. Where are we? ────────────────────────────────────────────────
        traveled_north, traveled_east = _lat_lon_to_meters(
            state.latitude,
            state.longitude,
            self._start_latitude,
            self._start_longitude,
            self._body_radius,
        )

        remaining_north = self._distance_north - traveled_north
        remaining_east = self._distance_east - traveled_east
        remaining_distance = math.sqrt(remaining_north**2 + remaining_east**2)

        # ── 2. How fast are we going? ───────────────────────────────────────
        safe_dt = max(dt, 0.01)
        velocity_north = (traveled_north - self._prev_traveled_north) / safe_dt
        velocity_east = (traveled_east - self._prev_traveled_east) / safe_dt
        self._prev_traveled_north = traveled_north
        self._prev_traveled_east = traveled_east
        actual_speed = math.sqrt(velocity_north**2 + velocity_east**2)

        # ── 3. Are we there yet? ────────────────────────────────────────────
        if remaining_distance < _ARRIVAL_DISTANCE and actual_speed < _ARRIVAL_SPEED:
            log.info(f"Target reached: traveled N={traveled_north:.1f}m E={traveled_east:.1f}m")
            return ActionResult(status=ActionStatus.SUCCEEDED)

        # ── 4. Altitude hold ────────────────────────────────────────────────
        altitude_error = self._target_altitude - state.altitude_surface
        desired_vspeed = max(
            -_MAX_APPROACH_SPEED,
            min(_MAX_APPROACH_SPEED, _SPEED_GAIN * altitude_error),
        )
        vspeed_error = desired_vspeed - state.vertical_speed
        commands.throttle = max(0.0, min(1.0, 0.5 + _KP_SPEED * vspeed_error))

        # ── 5. Keep vessel upright with SAS radial ──────────────────────────
        commands.sas = True
        commands.sas_mode = SASMode.RADIAL
        commands.rcs = True

        # ── 6. Desired velocity vector ──────────────────────────────────────
        # Scale desired speed with distance: fast when far, slow when close.
        desired_speed = min(
            self._max_speed,
            _HORIZONTAL_GAIN * remaining_distance * self._max_speed,
        )

        # Desired velocity direction = toward the remaining displacement.
        if remaining_distance > 0:
            desired_velocity_north = desired_speed * (remaining_north / remaining_distance)
            desired_velocity_east = desired_speed * (remaining_east / remaining_distance)
        else:
            desired_velocity_north = 0.0
            desired_velocity_east = 0.0

        # ── 7. Velocity error in world space ────────────────────────────────
        error_north = desired_velocity_north - velocity_north
        error_east = desired_velocity_east - velocity_east

        # ── 8. Project onto vessel axes ─────────────────────────────────────
        # Convert world-space velocity error to vessel-relative (forward, right)
        # using the vessel's current heading. No rotation needed.
        error_forward, error_right = _world_to_vessel(
            error_north,
            error_east,
            state.heading,
        )

        commands.translate_forward = max(-1.0, min(1.0, _RCS_GAIN * error_forward))
        commands.translate_right = max(-1.0, min(1.0, _RCS_GAIN * error_right))

        # ── 9. Debug log ───────────────────────────────────────────────────
        log.debug(
            f"translate: remaining N={remaining_north:+.1f}m E={remaining_east:+.1f}m "
            f"dist={remaining_distance:.1f}m  "
            f"speed={actual_speed:.1f}/{desired_speed:.1f}m/s  "
            f"fwd={commands.translate_forward:+.2f} right={commands.translate_right:+.2f}  "
            f"alt_err={altitude_error:+.1f}m throttle={commands.throttle:.3f}"
        )

        return ActionResult(status=ActionStatus.RUNNING)

    def stop(self, state: VesselState, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)
        commands.throttle = 0.0
        commands.rcs = False
        commands.translate_forward = 0.0
        commands.translate_right = 0.0
