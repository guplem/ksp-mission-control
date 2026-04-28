"""RunScienceAction - activate all science experiments on the vessel.

Triggers every available science experiment that doesn't already have data.
Optionally waits until the vessel reaches apoapsis (vertical speed crosses
zero) before triggering, which is useful for suborbital science flights.
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
    ScienceAction,
    ScienceCommand,
    State,
    VesselCommands,
)


class RunScienceAction(Action):
    """Activate science experiments, optionally waiting for apoapsis."""

    action_id: ClassVar[str] = "run_science"
    label: ClassVar[str] = "Run Science"
    description: ClassVar[str] = "Activate all science experiments on the vessel"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="wait_for_apoapsis",
            label="Wait for Apoapsis",
            description="Wait until the vessel reaches its highest point before running experiments",
            required=False,
            param_type=ParamType.BOOL,
            default=False,
        ),
        ActionParam(
            param_id="science_index",
            label="Science Experiment Index",
            description="Index of the science experiment to run, instead of all. Zero-based index, sorted by experiment name. Overrides 'Wait for Apoapsis' since it will trigger immediately.",
            required=False,
            param_type=ParamType.INT,
            default=None,
        ),
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        self._wait_for_apoapsis: bool = bool(param_values["wait_for_apoapsis"])
        self._science_index: int | None = param_values["science_index"]

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:

        if self._wait_for_apoapsis and not state.orbit_apoapsis_passed:
            return ActionResult(status=ActionStatus.RUNNING, message=f"Waiting for apoapsis ({state.orbit_apoapsis_time_to:.0f}s)")

        if self._science_index is not None and 0 <= self._science_index < len(state.science_experiments):
            commands.science_commands += (ScienceCommand(self._science_index, ScienceAction.RUN),)
            return ActionResult(status=ActionStatus.SUCCEEDED, message=f"Running science experiment index {self._science_index}")

        available_count = sum(1 for e in state.science_experiments if e.available and not e.has_data)
        log.info(f"Running {available_count} science experiment(s)")
        commands.all_science = ScienceAction.RUN
        return ActionResult(status=ActionStatus.SUCCEEDED, message="Science experiments activated")

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)
