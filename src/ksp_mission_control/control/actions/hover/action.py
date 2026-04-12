"""HoverAction - PD altitude hold."""

from __future__ import annotations

from typing import Any, ClassVar

from ksp_mission_control.control.actions.base import (
    Action,
    ActionParam,
    ActionResult,
    ActionStatus,
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

    def tick(self, state: VesselState, controls: VesselCommands, dt: float) -> ActionResult:
        error = self._target_altitude - state.altitude_surface
        throttle = 0.5 + _KP * error - _KD * state.vertical_speed
        controls.throttle = max(0.0, min(1.0, throttle))
        controls.sas = True
        return ActionResult(status=ActionStatus.RUNNING)

    def stop(self, controls: VesselCommands) -> None:
        super().stop(controls)
        controls.sas = False
