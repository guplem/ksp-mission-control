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
    ]

    def start(self, param_values: dict[str, Any]) -> None:
        self._target_altitude: float = float(param_values["target_altitude"])
        self._ticks: int = 0
        self._reached_target: bool = False

    def tick(
        self, state: VesselState, commands: VesselCommands, dt: float, log: ActionLogger
    ) -> ActionResult:
        self._ticks += 1
        difference = self._target_altitude - state.altitude_surface
        raw_throttle = 0.5 + _KP * difference - _KD * state.vertical_speed
        commands.throttle = max(0.0, min(1.0, raw_throttle))
        commands.sas = True
        commands.sas_mode = SASMode.RADIAL

        log.debug(
            f"PD: error={difference:+.1f}m  P={_KP * difference:+.4f}  D={-_KD * state.vertical_speed:+.4f}"
            f"  raw={raw_throttle:.4f}  clamped={commands.throttle:.3f}"
        )

        if not self._reached_target and abs(difference) < 5.0:
            self._reached_target = True
            log.info(f"Reached target altitude: {self._target_altitude:.0f}m")

        deviation_threshold = max(10.0, self._target_altitude * 0.25)
        if self._reached_target and abs(difference) > deviation_threshold:
            log.warn(
                f"Large altitude deviation: {difference:+.0f}m from target (threshold {deviation_threshold:.0f}m)"
            )

        if state.altitude_surface < 10.0 and state.vertical_speed < -5.0:
            log.error(
                f"Dangerous descent: alt={state.altitude_surface:.0f}m vspd={state.vertical_speed:.1f}m/s"
            )

        return ActionResult(status=ActionStatus.RUNNING)

    def stop(self, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(commands, log)
        commands.sas = False
        log.info(f"Hover stopped after {self._ticks} ticks")
