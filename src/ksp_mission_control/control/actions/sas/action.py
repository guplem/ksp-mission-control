"""SasAction - enable SAS and set its autopilot mode.

One-shot action: enables SAS and sets the requested mode in a single tick.
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
    State,
    VesselCommands,
)


class SasAction(Action):
    """Enable SAS and set its autopilot mode."""

    action_id: ClassVar[str] = "sas"
    label: ClassVar[str] = "Set SAS Mode"
    description: ClassVar[str] = "Enable SAS and set its autopilot mode"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="mode",
            label="SAS Mode",
            description="SAS mode (e.g. stability_assist, prograde, retrograde, radial, anti_radial).",
            required=True,
            param_type=ParamType.STR,
            default="stability_assist",
        ),
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        self._sas_mode: SASMode = SASMode(param_values["mode"])

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        commands.sas = True
        commands.sas_mode = self._sas_mode
        return ActionResult(status=ActionStatus.SUCCEEDED, message=f"SAS mode set to {self._sas_mode.display_name}")

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)
