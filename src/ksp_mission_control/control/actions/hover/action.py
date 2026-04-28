"""HoverAction - cascaded velocity altitude hold.

Uses a two-loop controller to reach and hold a target altitude:
  1. Outer loop: converts altitude error into a desired vertical speed
     (linear gain, capped at _MAX_APPROACH_SPEED).
  2. Inner loop: adjusts throttle to match the desired vertical speed
     (P controller around a 0.5 hover baseline).

This gives aggressive climb/descent when far from the target and smooth
deceleration on approach. Same pattern as LandAction.
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
    SASMode,
    SpeedMode,
    State,
    VesselCommands,
    VesselSituation,
)

# Cascaded velocity controller gains
# Outer loop: altitude error -> desired vertical speed
_SPEED_GAIN = 0.5  # m/s desired speed per meter of altitude error
_MAX_APPROACH_SPEED = 50.0  # cap on climb/descent rate during approach (m/s)
# Inner loop: speed error -> throttle
_KP_SPEED = 0.2  # throttle adjustment per m/s of speed error


class HoverAction(Action):
    """Hold altitude at a target"""

    action_id: ClassVar[str] = "hover"
    label: ClassVar[str] = "Hover"
    description: ClassVar[str] = "Hold altitude at target"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="target_altitude",
            label="Target Altitude",
            description="Altitude to maintain above surface",
            required=False,
            param_type=ParamType.FLOAT,
            default=100.0,
            unit="m",
        ),
        ActionParam(
            param_id="hover_duration",
            label="Hover Duration",
            description="Time to maintain hover after reaching target altitude (0 for indefinite)",
            required=False,
            param_type=ParamType.FLOAT,
            default=0.0,
            unit="s",
        ),
        ActionParam(
            param_id="horizontal_control",
            label="Horizontal Travel",
            description="Distance to travel horizontally while maintaining altitude (0 for none)",
            required=False,
            param_type=ParamType.FLOAT,
            default=0.0,
            unit="m",
        ),
        ActionParam(
            param_id="land_at_end",
            label="Land at End",
            description="This is old and will be removed in favour of flight plans",
            required=False,
            param_type=ParamType.BOOL,
            default=False,
        ),
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        self._target_altitude: float = float(param_values["target_altitude"])
        self._hover_duration: float = float(param_values["hover_duration"])
        self._horizontal_control: float = float(param_values["horizontal_control"])
        self._land_at_end: bool = bool(param_values["land_at_end"])
        self._ticks: int = 0
        self._first_tick: bool = True
        self._reached_target: bool = False
        self._hover_elapsed: float = 0.0
        self._initial_altitude: float = state.altitude_surface

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        # --- Throttle control (cascaded velocity controller) ---
        # Outer loop: how fast should we be climbing/descending right now?
        # At 100m below target -> desired_vspeed = 50 m/s (capped)
        # At  10m below target -> desired_vspeed =  5 m/s
        # At   2m below target -> desired_vspeed =  1 m/s
        # At target            -> desired_vspeed =  0 m/s
        difference = self._target_altitude - state.altitude_surface
        desired_vspeed = max(-_MAX_APPROACH_SPEED, min(_MAX_APPROACH_SPEED, _SPEED_GAIN * difference))

        # Inner loop: adjust throttle to match desired speed.
        # 0.5 is the approximate hover throttle; positive speed_error means
        # we need to climb faster, so we add throttle (and vice versa).
        speed_error = desired_vspeed - state.speed_vertical
        raw_throttle = 0.5 + _KP_SPEED * speed_error
        commands.throttle = max(0.0, min(1.0, raw_throttle))

        log.debug(
            f"hover: diff={difference:+.1f}m  desired_vspd={desired_vspeed:+.1f}m/s  "
            f"actual_vspd={state.speed_vertical:+.1f}m/s  "
            f"speed_err={speed_error:+.1f}  throttle={commands.throttle:.3f}"
        )
        # --- First tick: switch navball to surface mode ---
        if self._first_tick:
            self._first_tick = False
            commands.ui_speed_mode = SpeedMode.SURFACE
            log.info("Navball speed mode set to Surface")

        # --- Orientation: point straight up and use RCS for stability ---
        commands.sas = True
        commands.sas_mode = SASMode.RADIAL
        commands.rcs = True

        # --- Landing gear: retract above 3m
        if state.altitude_surface > 3.0 and state.control_gear:
            log.debug(f"Closed landing gear at altitude {state.altitude_surface:.1f}m")
            commands.gear = False

        # --- Target reached detection (within 5m) ---
        if not self._reached_target and abs(difference) < 5.0:
            self._reached_target = True
            if self._hover_duration > 0:
                log.info(f"Reached target altitude: {self._target_altitude:.0f}m, hovering for {self._hover_duration:.0f}s")
            else:
                log.info(f"Reached target altitude: {self._target_altitude:.0f}m")

        # --- Hover duration countdown (only after reaching target) ---
        if self._reached_target and self._hover_duration > 0:
            self._hover_elapsed += dt
            remaining = self._hover_duration - self._hover_elapsed
            if remaining <= 0:
                log.info(f"Hover duration complete ({self._hover_duration:.0f}s), stopping")
                return ActionResult(status=ActionStatus.SUCCEEDED)

        # --- Safety warnings ---
        # Warn if drifting too far from target (25% of target alt, min 10m)
        deviation_threshold = max(10.0, self._target_altitude * 0.25)
        if self._reached_target and abs(difference) > deviation_threshold:
            log.warn(f"Large altitude deviation: {difference:+.0f}m from target (threshold {deviation_threshold:.0f}m)")

        # Emergency: falling fast near the ground
        if state.altitude_surface < 100.0 and state.speed_vertical < -5.0:
            log.error(f"Dangerous descent: alt={state.altitude_surface:.0f}m vspd={state.speed_vertical:.1f}m/s")

        # --- Landed detection: back at starting altitude and on the ground ---
        if self._reached_target and state.altitude_surface <= (self._initial_altitude + 1.0) and state.situation == VesselSituation.LANDED:
            log.info("Landed successfully at target altitude")
            return ActionResult(status=ActionStatus.SUCCEEDED)

        return ActionResult(status=ActionStatus.RUNNING)

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)
