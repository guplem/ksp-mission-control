"""ExecuteScienceAction - activate all science experiments on the vessel.

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


class ExecuteScienceAction(Action):
    """Activate science experiments, optionally waiting for apoapsis."""

    action_id: ClassVar[str] = "science"
    label: ClassVar[str] = "Run Science"
    description: ClassVar[str] = "Activate all science experiments on the vessel"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="science_index",
            label="Index",
            description=("Index of the science experiment to run, instead of all."),
            required=False,
            param_type=ParamType.INT,
            default=None,
        ),
        ActionParam(
            param_id="science_count",
            label="Count",
            description=("Number of science experiments to run, instead of all."),
            required=False,
            param_type=ParamType.INT,
            default=None,
        ),
        ActionParam(
            param_id="action",
            label="Action",
            description=("The action to perform on the science experiment."),
            required=False,
            param_type=ParamType.STR,
            default=None,
        ),
        ActionParam(
            param_id="name-tag",
            label="Name Tag",
            description=("Name of the science experiment to run, instead of all."),
            required=False,
            param_type=ParamType.STR,
            default=None,
        ),
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        raw_index = param_values["science_index"]
        self._science_index: int | None = int(raw_index) if raw_index is not None else None
        raw_count = param_values["science_count"]
        self._science_count: int | None = int(raw_count) if raw_count is not None else None
        raw_action: str | None = param_values["action"]
        if raw_action is not None:
            try:
                self._action: ScienceAction | None = ScienceAction(raw_action)
            except ValueError:
                valid = ", ".join(a.value for a in ScienceAction)
                raise ValueError(f"Unknown science action '{raw_action}'. Valid: {valid}") from None
        else:
            self._action = None
        self._name_tag: str | None = param_values["name-tag"]

        if self._science_count is not None and self._science_count > 1 and self._science_index is not None:
            raise ValueError("Cannot specify both science_index and science_count > 1")

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        action = self._action if self._action is not None else ScienceAction.RUN

        # Filter by name tag: find experiments whose part has the matching tag
        if self._name_tag is not None:
            matching = [e for e in state.science_experiments if e.name_tag == self._name_tag]
            if not matching:
                return ActionResult(
                    status=ActionStatus.FAILED,
                    message=f"No science experiment found with name tag '{self._name_tag}'",
                )
            commands.science_commands += tuple(ScienceCommand(e.index, action) for e in matching)
            names = ", ".join(e.title for e in matching)
            return ActionResult(status=ActionStatus.SUCCEEDED, message=f"Running science on tag '{self._name_tag}': {names}")

        if self._science_index is not None and 0 <= self._science_index < len(state.science_experiments):
            commands.science_commands += (ScienceCommand(self._science_index, action),)
            return ActionResult(status=ActionStatus.SUCCEEDED, message=f"Running science experiment index {self._science_index}")

        if self._science_count is not None and self._science_count > 0:
            available_experiments = [e for e in state.science_experiments if e.available and e.available]
            experiments_to_run = available_experiments[: self._science_count]
            commands.science_commands += tuple(ScienceCommand(e.index, action) for e in experiments_to_run)
            return ActionResult(status=ActionStatus.SUCCEEDED, message=f"Running {len(experiments_to_run)} science experiment(s)")

        commands.all_science = action
        available_count = sum(1 for e in state.science_experiments if e.available and not e.has_data)
        return ActionResult(status=ActionStatus.SUCCEEDED, message=f"All ({available_count}) science experiments activated")

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)
