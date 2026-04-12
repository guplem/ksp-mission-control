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
    VesselCommands,
    VesselSituation,
    VesselState,
)

_KP = 0.3  # Proportional gain: speed error to throttle
_KD = 0.15  # Derivative gain: damps throttle oscillation via acceleration


class LandAction(Action):
    """Controlled descent to the surface at a target speed."""

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
        self._prev_vertical_speed: float = state.vertical_speed

    def tick(
        self, state: VesselState, commands: VesselCommands, dt: float, log: ActionLogger
    ) -> ActionResult:
        # Desired descent speed follows sqrt(altitude) curve for smooth deceleration.
        # High up: fall faster (sqrt(400)=20 m/s). Near ground: converge to target_speed.
        # sqrt(4)=2, so at ~4m altitude the curve naturally meets a 2 m/s target.
        altitude_speed = math.sqrt(max(0.0, state.altitude_surface))
        desired_vertical_speed = -max(self._target_speed, altitude_speed)

        speed_error = desired_vertical_speed - state.vertical_speed

        # Estimate acceleration for derivative damping
        safe_dt = max(dt, 0.01)
        acceleration = (state.vertical_speed - self._prev_vertical_speed) / safe_dt
        self._prev_vertical_speed = state.vertical_speed

        # PD controller: P tracks target speed, D damps acceleration to prevent overshoot
        raw_throttle = 0.5 + _KP * speed_error - _KD * acceleration
        commands.throttle = max(0.0, min(1.0, raw_throttle))

        log.debug(
            f"PD: desired_vspd={desired_vertical_speed:+.1f}m/s  "
            f"actual_vspd={state.vertical_speed:+.1f}m/s  "
            f"error={speed_error:+.1f}  accel={acceleration:+.1f}  "
            f"throttle={commands.throttle:.3f}"
        )

        commands.sas = True
        commands.sas_mode = SASMode.RADIAL

        # Deploy landing gear below 50m
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
        commands.sas = False
