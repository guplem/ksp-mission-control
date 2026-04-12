"""LandAction - controlled descent to surface."""

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
    SpeedMode,
    VesselCommands,
    VesselSituation,
    VesselState,
)

# --- PD controller tuning constants ---
# The throttle output is: 0.5 (hover baseline) + KP * speed_error - KD * acceleration
# KP converts m/s speed error into throttle adjustment (0-1 range).
# KD damps rapid velocity changes to prevent throttle oscillation and mid-descent stalls.
_KP = 0.3
_KD = 0.15


class LandAction(Action):
    """Controlled descent to the surface using a PD controller.

    Descent profile:
        The target descent speed follows a sqrt(altitude) curve, which gives
        natural deceleration: fast at high altitude, smoothly slowing near the
        ground. At ~4m altitude, sqrt(4)=2 m/s, matching the default target.

    Throttle control:
        A PD (proportional-derivative) controller adjusts throttle around a 0.5
        baseline. The P term corrects for speed error (too fast/slow vs target).
        The D term uses estimated vertical acceleration to dampen oscillations
        that would otherwise cause throttle overshoot and stalling.

    Automatic actions:
        - Lights turned on at the start of descent
        - SAS held in radial mode to keep vessel upright
        - Landing gear deployed at 50m altitude
        - Brakes engaged on touchdown
        - Completes when vessel situation becomes LANDED
    """

    action_id: ClassVar[str] = "land"
    label: ClassVar[str] = "Land"
    description: ClassVar[str] = "Controlled descent to surface"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="target_speed",
            label="Target Speed",
            description="Desired touchdown speed (positive = downward)",
            required=False,
            param_type=ParamType.FLOAT,
            default=2.0,
            unit="m/s",
        ),
    ]

    def start(self, state: VesselState, param_values: dict[str, Any]) -> None:
        self._target_speed: float = float(param_values["target_speed"])
        self._gear_deployed: bool = False
        self._first_tick: bool = True
        # Store initial vertical speed for acceleration estimation on first tick
        self._prev_vertical_speed: float = state.vertical_speed

    def tick(
        self, state: VesselState, commands: VesselCommands, dt: float, log: ActionLogger
    ) -> ActionResult:
        # --- Descent speed target ---
        # sqrt(altitude) gives a smooth curve: e.g. 400m -> 20 m/s, 100m -> 10 m/s,
        # 4m -> 2 m/s. Clamped to never go below target_speed (the touchdown speed).
        altitude_speed = math.sqrt(max(0.0, state.altitude_surface))
        desired_vertical_speed = -max(self._target_speed, altitude_speed)

        # Positive error = descending too fast, need more throttle
        speed_error = desired_vertical_speed - state.vertical_speed

        # --- Derivative term: estimate vertical acceleration ---
        # Used by the D term to detect and dampen rapid throttle swings.
        # safe_dt avoids division by zero on the first tick or very small timesteps.
        safe_dt = max(dt, 0.01)
        acceleration = (state.vertical_speed - self._prev_vertical_speed) / safe_dt
        self._prev_vertical_speed = state.vertical_speed

        # --- PD throttle calculation ---
        # 0.5 baseline ~= hover thrust. P corrects speed error, D dampens oscillation.
        raw_throttle = 0.5 + _KP * speed_error - _KD * acceleration
        commands.throttle = max(0.0, min(1.0, raw_throttle))

        log.debug(
            f"PD: desired_vspd={desired_vertical_speed:+.1f}m/s  "
            f"actual_vspd={state.vertical_speed:+.1f}m/s  "
            f"error={speed_error:+.1f}  accel={acceleration:+.1f}  "
            f"throttle={commands.throttle:.3f}"
        )

        # First tick: lights on and switch navball to surface mode
        if self._first_tick:
            self._first_tick = False
            commands.lights = True
            commands.speed_mode = SpeedMode.SURFACE
            log.info("Lights on for descent, navball set to Surface")

        # Hold radial SAS to keep vessel pointing away from surface
        commands.sas = True
        commands.sas_mode = SASMode.RADIAL

        # Auto-deploy landing gear when close to the ground
        if state.altitude_surface < 50.0 and not self._gear_deployed:
            self._gear_deployed = True
            commands.gear = True
            log.info(f"Deployed landing gear at altitude {state.altitude_surface:.1f}m")

        if state.situation == VesselSituation.LANDED:
            log.info("Landed successfully")
            return ActionResult(status=ActionStatus.SUCCEEDED)

        return ActionResult(status=ActionStatus.RUNNING)

    def stop(self, state: VesselState, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)
        commands.throttle = 0.0
        commands.sas = False
        commands.brakes = True
