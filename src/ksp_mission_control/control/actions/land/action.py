"""LandAction - controlled descent to surface."""

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
    VesselCommands,
    VesselSituation,
    VesselState,
)

# Proportional gain: speed error to throttle
_KP = 0.2


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

    def tick(
        self, state: VesselState, commands: VesselCommands, dt: float, log: ActionLogger
    ) -> ActionResult:
        # Target vertical speed: descend at target_speed (negative = downward)
        # Scale descent rate with altitude: slower near ground
        desired_vertical_speed = -self._target_speed
        if state.altitude_surface > 100.0:
            # Above 100m, descend faster (up to 5x target speed)
            altitude_factor = min(5.0, state.altitude_surface / 100.0)
            desired_vertical_speed = -self._target_speed * altitude_factor

        speed_error = desired_vertical_speed - state.vertical_speed
        # Positive error = descending too fast, need more throttle
        raw_throttle = 0.5 + _KP * speed_error
        commands.throttle = max(0.0, min(1.0, raw_throttle))

        log.debug(
            f"PD: desired_vspd={desired_vertical_speed:+.1f}m/s  "
            f"actual_vspd={state.vertical_speed:+.1f}m/s  "
            f"error={speed_error:+.1f}  throttle={commands.throttle:.3f}"
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
