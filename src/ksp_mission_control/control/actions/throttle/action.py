"""ThrottleAction - set the throttle level for the vessel.

Supports two modes (mutually exclusive):
- throttle_level: set an explicit throttle value (0.0 to 1.0)
- twr: compute the throttle needed to achieve a target thrust-to-weight ratio
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
    State,
    VesselCommands,
)


class ThrottleAction(Action):
    """Set the throttle level for the vessel."""

    action_id: ClassVar[str] = "throttle"
    label: ClassVar[str] = "Set Throttle"
    description: ClassVar[str] = "Set the throttle level for the vessel"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="throttle_level",
            label="Throttle Level",
            description="The desired throttle level (0.0 to 1.0). Mutually exclusive with twr.",
            required=False,
            param_type=ParamType.FLOAT,
            default=None,
        ),
        ActionParam(
            param_id="twr",
            label="Target TWR",
            description="Target thrust-to-weight ratio. Computes throttle automatically. Mutually exclusive with throttle_level.",
            required=False,
            param_type=ParamType.FLOAT,
            default=None,
        ),
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        raw_throttle = param_values["throttle_level"]
        raw_twr = param_values["twr"]
        self._throttle_level: float | None = float(raw_throttle) if raw_throttle is not None else None
        self._twr: float | None = float(raw_twr) if raw_twr is not None else None

        if self._throttle_level is not None and self._twr is not None:
            raise ValueError("throttle_level and twr are mutually exclusive; set only one")
        if self._throttle_level is None and self._twr is None:
            raise ValueError("Either throttle_level or twr must be set")
        if self._twr is not None and self._twr < 0:
            raise ValueError("Invalid TWR: must be non-negative")

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        if state.thrust_available <= 0:
            return ActionResult(status=ActionStatus.FAILED, message="Cannot set throttle: no thrust available")

        if self._throttle_level is not None:
            commands.throttle = self._throttle_level
            return ActionResult(status=ActionStatus.SUCCEEDED, message=f"Throttle level set to {self._throttle_level}")

        # TWR mode: throttle = (target_twr * weight) / thrust_available
        # start() guarantees exactly one of _throttle_level/_twr is set.
        assert self._twr is not None
        if state.weight <= 0.0:
            return ActionResult(status=ActionStatus.FAILED, message="Cannot compute TWR: vessel has no weight")

        throttle = max(0.0, min(1.0, (self._twr * state.weight) / state.thrust_available))
        commands.throttle = throttle
        return ActionResult(status=ActionStatus.SUCCEEDED, message=f"Throttle set to {throttle:.3f} for TWR {self._twr}")

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        pass
