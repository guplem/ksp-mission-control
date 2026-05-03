"""AutopilotAction - engage the kRPC autopilot and set target orientation.

One-shot action: engages the autopilot and sets pitch/heading/roll in a single tick.
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


class AutopilotAction(Action):
    """Engage the kRPC autopilot and set target pitch, heading, and roll."""

    action_id: ClassVar[str] = "autopilot"
    label: ClassVar[str] = "Set Autopilot"
    description: ClassVar[str] = "Engage the kRPC autopilot and set target orientation"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="pitch",
            label="Target Pitch",
            description="Target pitch in degrees. 0 = horizontal, 90 = straight up, -90 = straight down.",
            required=True,
            param_type=ParamType.FLOAT,
            default=90.0,
            unit="deg",
        ),
        ActionParam(
            param_id="heading",
            label="Target Heading",
            description="Target heading in degrees. 0 = north, 90 = east, 180 = south, 270 = west.",
            required=False,
            param_type=ParamType.FLOAT,
            default=90.0,
            unit="deg",
        ),
        ActionParam(
            param_id="roll",
            label="Target Roll",
            description="Target roll in degrees. Leave empty to disable roll targeting.",
            required=False,
            param_type=ParamType.FLOAT,
            unit="deg",
        ),
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        self._pitch: float = float(param_values["pitch"])

        raw_heading = param_values.get("heading")
        self._heading: float | None = float(raw_heading) if raw_heading is not None else None

        raw_roll = param_values.get("roll")
        self._roll: float | None = float(raw_roll) if raw_roll is not None else None

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        commands.autopilot = True
        commands.autopilot_pitch = self._pitch

        if self._heading is not None:
            commands.autopilot_heading = self._heading

        if self._roll is not None:
            commands.autopilot_roll = self._roll
        else:
            commands.autopilot_roll = float("nan")

        parts = [f"pitch={self._pitch}"]
        if self._heading is not None:
            parts.append(f"heading={self._heading}")
        if self._roll is not None:
            parts.append(f"roll={self._roll}")

        return ActionResult(
            status=ActionStatus.SUCCEEDED,
            message=f"Autopilot engaged: {', '.join(parts)}",
        )

    # def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
    #     super().stop(state, commands, log)
