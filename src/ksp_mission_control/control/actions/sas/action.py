"""SasAction - enable SAS and set its autopilot mode.

Multi-tick action: enables SAS, then sets the requested mode once SAS is
confirmed on, then verifies the mode took effect. Fails with a clear hint
if the mode never sticks (low pilot experience, missing reference, etc.).
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

# Number of ticks to wait for the mode change to be reflected in vessel state
# before declaring failure. At ~0.5s per tick this gives ~2.5s, which is
# enough to absorb the kRPC same-frame race and detect a real refusal.
_MODE_VERIFY_TIMEOUT_TICKS = 5


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
        try:
            self._sas_mode: SASMode = SASMode(param_values["mode"])
        except ValueError:
            valid = ", ".join(m.value for m in SASMode)
            raise ValueError(f"Unknown SAS mode '{param_values['mode']}'. Valid modes: {valid}") from None
        self._verify_ticks_elapsed: int = 0

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        commands.sas = True
        # Hold off on sending the mode until SAS is confirmed on. Setting
        # sas_mode in the same physics frame as enabling SAS can be silently
        # ignored by KSP, leaving the vessel stuck in stability_assist.
        if state.control_sas:
            commands.sas_mode = self._sas_mode

        if state.control_sas and state.control_sas_mode == self._sas_mode:
            return ActionResult(
                status=ActionStatus.SUCCEEDED,
                message=f"SAS mode set to {self._sas_mode.display_name}",
            )

        self._verify_ticks_elapsed += 1
        if self._verify_ticks_elapsed >= _MODE_VERIFY_TIMEOUT_TICKS:
            current = state.control_sas_mode.display_name if state.control_sas_mode is not None else "off"
            return ActionResult(
                status=ActionStatus.FAILED,
                message=(
                    f"Failed: KSP refused SAS mode {self._sas_mode.display_name} "
                    f"(current: {current}). Check pilot experience level or probe core tier."
                ),
            )

        return ActionResult(
            status=ActionStatus.RUNNING,
            message=f"Setting SAS mode to {self._sas_mode.display_name}",
        )

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        pass
