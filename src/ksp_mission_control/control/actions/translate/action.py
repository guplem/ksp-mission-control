"""TranslateAction - horizontal movement while holding altitude.

Moves the vessel a specified number of meters North/South and East/West
using RCS translation, while the main engines maintain altitude.

Phases
------
The action cycles through three phases automatically:

  1. **Orient** - Rotate to face the target. No RCS thrust until aligned.
  2. **Translate** - Push forward with RCS. A velocity controller ramps
     speed up toward max_speed and begins slowing as the target approaches.
  3. **Brake** - If the vessel is overshooting (going too fast for the
     remaining distance), flip to face retrograde (opposite of travel
     direction) and push forward to decelerate.

The action completes when the vessel is within 2 m of the target and
moving slower than 1 m/s.

Altitude hold
-------------
A cascaded velocity controller (same as HoverAction) runs every tick
regardless of horizontal phase. It converts altitude error into a desired
vertical speed, then adjusts throttle to track that speed.

Position tracking
-----------------
Lat/lon coordinates are converted to meters using a flat-Earth
approximation. Velocity is estimated by differentiating position between
ticks (avoids relying on surface_speed which doesn't give direction).
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

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

# Altitude hold (cascaded velocity controller, same gains as HoverAction)
_SPEED_GAIN = 0.5  # m/s desired vertical speed per meter of altitude error
_MAX_APPROACH_SPEED = 50.0  # cap on vertical climb/descent rate (m/s)
_KP_SPEED = 0.2  # throttle adjustment per m/s of vertical speed error

# Heading alignment
_HEADING_ALIGNED_THRESHOLD = 10.0  # degrees: close enough to start thrusting

# Horizontal velocity controller
_HORIZONTAL_GAIN = 0.1  # desired speed = gain * remaining_distance * max_speed
_FORWARD_GAIN = 0.2  # translate_forward per m/s of velocity error

# Arrival / completion
_ARRIVAL_DISTANCE = 2.0  # meters: close enough to declare success
_ARRIVAL_SPEED = 1.0  # m/s: slow enough to declare success

# Braking
_BRAKE_SPEED_THRESHOLD = 0.5  # m/s: minimum speed to reliably determine travel direction


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


def _target_heading(north_component: float, east_component: float) -> float:
    """Heading (0-360) from a north/east vector. 0=N, 90=E, 180=S, 270=W."""
    return math.degrees(math.atan2(east_component, north_component)) % 360.0


def _heading_error(target: float, current: float) -> float:
    """Signed heading error in [-180, 180]. Positive = target is clockwise."""
    return (target - current + 180.0) % 360.0 - 180.0


# ---------------------------------------------------------------------------
# Action
# ---------------------------------------------------------------------------


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
        ActionParam(
            param_id="max_tilt",
            label="Max Tilt",
            description="Maximum tilt from vertical (90=upright). Higher=faster but loses altitude",
            required=False,
            param_type=ParamType.FLOAT,
            default=10.0,
            unit="deg",
        ),
    ]

    # -- Lifecycle ------------------------------------------------------------

    def start(self, state: VesselState, param_values: dict[str, Any]) -> None:
        self._distance_north: float = float(param_values["distance_north"])
        self._distance_east: float = float(param_values["distance_east"])
        self._max_speed: float = float(param_values["max_speed"])
        self._max_tilt: float = float(param_values["max_tilt"])

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
        # Convert current lat/lon to meters traveled from the start point.
        traveled_north, traveled_east = _lat_lon_to_meters(
            state.latitude,
            state.longitude,
            self._start_latitude,
            self._start_longitude,
            self._body_radius,
        )

        # How far we still need to go.
        remaining_north = self._distance_north - traveled_north
        remaining_east = self._distance_east - traveled_east
        remaining_distance = math.sqrt(remaining_north**2 + remaining_east**2)

        # ── 2. How fast are we going? ───────────────────────────────────────
        # Estimate horizontal velocity by differentiating position over time.
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
        # Cascaded controller: altitude error -> desired vertical speed -> throttle.
        # Runs every tick regardless of horizontal phase.
        altitude_error = self._target_altitude - state.altitude_surface
        desired_vspeed = max(
            -_MAX_APPROACH_SPEED,
            min(_MAX_APPROACH_SPEED, _SPEED_GAIN * altitude_error),
        )
        vspeed_error = desired_vspeed - state.vertical_speed
        commands.throttle = max(0.0, min(1.0, 0.5 + _KP_SPEED * vspeed_error))

        # ── 5. Autopilot setup (always active) ─────────────────────────────
        # Engage the kRPC autopilot for heading control. Pitch is clamped
        # near vertical to prevent excessive tilt and altitude loss.
        commands.autopilot = True
        commands.autopilot_pitch = max(90.0 - self._max_tilt, state.pitch)
        commands.rcs = True
        commands.sas = False  # autopilot replaces SAS

        # ── 6. How fast *should* we be going? ──────────────────────────────
        # Desired speed ramps down as we approach the target:
        #   far away  -> max_speed
        #   close     -> gain * distance * max_speed  (approaches 0)
        desired_speed = min(
            self._max_speed,
            _HORIZONTAL_GAIN * remaining_distance * self._max_speed,
        )

        # ── 7. Choose phase: braking / translating / orienting ─────────────
        #
        # Braking condition: we're going meaningfully faster than the desired
        # speed AND fast enough to know our travel direction.
        needs_braking = (
            actual_speed > desired_speed + _BRAKE_SPEED_THRESHOLD
            and actual_speed > _BRAKE_SPEED_THRESHOLD
        )

        if needs_braking:
            phase = self._do_braking(
                state,
                commands,
                velocity_north,
                velocity_east,
                actual_speed,
                desired_speed,
            )
        else:
            phase = self._do_translation(
                state,
                commands,
                remaining_north,
                remaining_east,
                remaining_distance,
                velocity_north,
                velocity_east,
                desired_speed,
            )

        # ── 8. Debug log ───────────────────────────────────────────────────
        log.debug(
            f"translate [{phase}]: "
            f"remaining N={remaining_north:+.1f}m E={remaining_east:+.1f}m "
            f"dist={remaining_distance:.1f}m  "
            f"speed={actual_speed:.1f}/{desired_speed:.1f}m/s  "
            f"fwd={commands.translate_forward:+.2f}  "
            f"alt_err={altitude_error:+.1f}m throttle={commands.throttle:.3f}"
        )

        return ActionResult(status=ActionStatus.RUNNING)

    def stop(self, state: VesselState, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)
        commands.throttle = 0.0
        commands.autopilot = False
        commands.rcs = False
        commands.translate_forward = 0.0

    # -- Phase helpers (called from tick) -------------------------------------

    def _do_braking(
        self,
        state: VesselState,
        commands: VesselCommands,
        velocity_north: float,
        velocity_east: float,
        actual_speed: float,
        desired_speed: float,
    ) -> str:
        """Point retrograde and push forward to decelerate.

        When the vessel is overshooting (moving too fast for the remaining
        distance), we flip 180 degrees from the travel direction and use
        RCS forward thrust to slow down. Only applies thrust once the
        heading is aligned with retrograde.
        """
        # Compute the direction we're currently traveling, then flip 180.
        travel_hdg = _target_heading(velocity_north, velocity_east)
        retrograde_hdg = (travel_hdg + 180.0) % 360.0
        commands.autopilot_heading = retrograde_hdg

        # Only fire RCS once we're facing (roughly) retrograde.
        hdg_err = _heading_error(retrograde_hdg, state.heading)
        if abs(hdg_err) < _HEADING_ALIGNED_THRESHOLD:
            overspeed = actual_speed - desired_speed
            commands.translate_forward = max(0.0, min(1.0, _FORWARD_GAIN * overspeed))
        else:
            commands.translate_forward = 0.0

        return "braking"

    def _do_translation(
        self,
        state: VesselState,
        commands: VesselCommands,
        remaining_north: float,
        remaining_east: float,
        remaining_distance: float,
        velocity_north: float,
        velocity_east: float,
        desired_speed: float,
    ) -> str:
        """Point toward the target and push forward to accelerate.

        The velocity controller compares our actual forward speed (velocity
        projected onto the target direction) against the desired speed for
        the current distance. The difference drives translate_forward.

        If the heading is still rotating toward the target, we wait with
        zero thrust (the "orienting" sub-phase).
        """
        # Point toward the remaining displacement vector.
        target_hdg = _target_heading(remaining_north, remaining_east)
        commands.autopilot_heading = target_hdg

        # Check alignment before firing RCS.
        hdg_err = _heading_error(target_hdg, state.heading)
        aligned = abs(hdg_err) < _HEADING_ALIGNED_THRESHOLD

        if not aligned:
            commands.translate_forward = 0.0
            return "orienting"

        # Project our world-space velocity onto the target direction to get
        # the speed component that actually moves us toward the goal.
        if remaining_distance > 0:
            forward_speed = (
                velocity_north * remaining_north + velocity_east * remaining_east
            ) / remaining_distance
        else:
            forward_speed = 0.0

        # P controller: positive error = we're too slow, push harder.
        velocity_error = desired_speed - forward_speed
        commands.translate_forward = max(-1.0, min(1.0, _FORWARD_GAIN * velocity_error))

        return "translating"
