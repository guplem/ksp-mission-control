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
            param_id="science_index",
            label="Science Experiment Index",
            description=("Index of the science experiment to run, instead of all."),
            required=False,
            param_type=ParamType.INT,
            default=None,
        ),
        ActionParam(
            param_id="science_count",
            label="Science Experiment Count",
            description=("Number of science experiments to run, instead of all."),
            required=False,
            param_type=ParamType.INT,
            default=None,
        ),
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        self._science_index: int | None = param_values["science_index"]
        self._science_count: int | None = param_values["science_count"]

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:

        if self._science_count is not None and self._science_count > 1 and self._science_index is not None:
            return ActionResult(
                status=ActionStatus.FAILED,
                message="Cannot specify both science_index and science_count parameters if science_count > 1",
            )

        if self._science_index is not None and 0 <= self._science_index < len(state.science_experiments):
            commands.science_commands += (ScienceCommand(self._science_index, ScienceAction.RUN),)
            return ActionResult(status=ActionStatus.SUCCEEDED, message=f"Running science experiment index {self._science_index}")

        if self._science_count is not None and self._science_count > 0:
            available_experiments = [e for e in state.science_experiments if e.available and e.available]
            experiments_to_run = available_experiments[: self._science_count]
            commands.science_commands += tuple(ScienceCommand(e.index, ScienceAction.RUN) for e in experiments_to_run)
            return ActionResult(status=ActionStatus.SUCCEEDED, message=f"Running {len(experiments_to_run)} science experiment(s)")

        commands.all_science = ScienceAction.RUN
        available_count = sum(1 for e in state.science_experiments if e.available and not e.has_data)
        return ActionResult(status=ActionStatus.SUCCEEDED, message=f"All ({available_count}) science experiments activated")

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)
