"""HoverAction - simple proportional altitude hold."""

from __future__ import annotations

from typing import Any, ClassVar

from ksp_mission_control.control.actions.base import (
    Action,
    ActionParam,
    ActionResult,
    ActionStatus,
    VesselControls,
    VesselState,
)

"""Proportional gain for the throttle controller"""
_KP = 0.01


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

    def tick(self, state: VesselState, controls: VesselControls, dt: float) -> ActionResult:
        error = self._target_altitude - state.altitude_surface
        throttle = 0.5 + error * _KP
        controls.throttle = max(0.0, min(1.0, throttle))
        controls.sas = True
        return ActionResult(status=ActionStatus.RUNNING)

    def stop(self, controls: VesselControls) -> None:
        super().stop(controls)
        controls.sas = False
