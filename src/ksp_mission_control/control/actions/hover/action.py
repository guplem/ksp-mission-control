"""HoverAction - PD altitude hold."""

from __future__ import annotations

from typing import Any, ClassVar

from ksp_mission_control.control.actions.base import (
    Action,
    ActionLogger,
    ActionParam,
    ActionResult,
    ActionStatus,
    SASMode,
    VesselCommands,
    VesselSituation,
    VesselState,
)

_KP = 0.02  # Proportional gain: altitude error to throttle
_KD = 0.1  # Derivative gain: vertical speed damping


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
            default=100.0,
            unit="m",
        ),
        ActionParam(
            param_id="horizontal_control",
            label="Horizontal Travel",
            description="Distance to travel horizontally while maintaining altitude (0 for none)",
            required=False,
            default=0.0,
            unit="m",
        ),
        ActionParam(
            param_id="land_at_end",
            label="Land at End",
            description="Whether to land at the end of the horizontal travel",
            required=False,
            default=False,
        ),
    ]

    def start(self, state: VesselState, param_values: dict[str, Any]) -> None:
        self._target_altitude: float = float(param_values["target_altitude"])
        self._horizontal_control: float = float(param_values["horizontal_control"])
        self._land_at_end: bool = bool(param_values["land_at_end"])
        self._ticks: int = 0
        self._reached_target: bool = False
        self._initial_altitude: float = state.altitude_surface

    def tick(
        self, state: VesselState, commands: VesselCommands, dt: float, log: ActionLogger
    ) -> ActionResult:
        difference = self._target_altitude - state.altitude_surface
        raw_throttle = 0.5 + _KP * difference - _KD * state.vertical_speed
        commands.throttle = max(0.0, min(1.0, raw_throttle))

        # Report internal state for debugging
        log.debug(
            f"PD: difference={difference:+.1f}m  P={_KP * difference:+.4f}  "
            f"D={-_KD * state.vertical_speed:+.4f}  raw={raw_throttle:.4f}  "
            f"clamped={commands.throttle:.3f}"
        )
        commands.sas = True
        commands.sas_mode = SASMode.RADIAL

        if state.altitude_surface > 3.0 and state.gear:
            log.debug(f"Closed landing gear at altitude {state.altitude_surface:.1f}m")
            commands.gear = False
        if state.altitude_surface < 2.0 and not state.gear:
            log.debug(f"Deployed landing gear at altitude {state.altitude_surface:.1f}m")
            commands.gear = True

        if not self._reached_target and abs(difference) < 5.0:
            self._reached_target = True  # Update state
            log.info(f"Reached target altitude: {self._target_altitude:.0f}m")

        # Dynamic threshold for warnings about altitude deviation after reaching target
        deviation_threshold = max(10.0, self._target_altitude * 0.25)
        if self._reached_target and abs(difference) > deviation_threshold:
            log.warn(
                f"Large altitude deviation: {difference:+.0f}m from target "
                f"(threshold {deviation_threshold:.0f}m)"
            )

        if state.altitude_surface < 10.0 and state.vertical_speed < -5.0:
            log.error(
                f"Dangerous descent: alt={state.altitude_surface:.0f}m "
                f"vspd={state.vertical_speed:.1f}m/s"
            )

        if (
            self._reached_target
            and state.altitude_surface <= (self._initial_altitude + 1.0)
            and state.situation == VesselSituation.LANDED
        ):
            log.info("Landed successfully at target altitude")
            return ActionResult(status=ActionStatus.SUCCEEDED)

        return ActionResult(status=ActionStatus.RUNNING)

    def stop(self, state: VesselState, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)
        commands.sas = False
