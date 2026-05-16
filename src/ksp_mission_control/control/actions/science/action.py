"""ExecuteScienceAction - apply a science action to selected experiments.

All selectors (index, name, title, name-tag, has-data, count) act as AND-composed
filters. ``count`` caps the number of matches. Always enumerates experiments
individually; use ``has-data=false`` to skip experiments that already hold data,
``has-data=true`` to target only those that do (e.g. for transmit or dump).
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
    ScienceExperiment,
    State,
    VesselCommands,
)


class ExecuteScienceAction(Action):
    """Run, reset, dump or transmit science experiments with optional filtering."""

    action_id: ClassVar[str] = "science"
    label: ClassVar[str] = "Run Science"
    description: ClassVar[str] = "Apply a science action to selected experiments"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="action",
            label="Action",
            description="Action to perform on each experiment: run, reset, dump or transmit. Defaults to run.",
            required=False,
            param_type=ParamType.STR,
            default=None,
        ),
        ActionParam(
            param_id="index",
            label="Index",
            description="Filter to the experiment at this position in state.science_experiments.",
            required=False,
            param_type=ParamType.INT,
            default=None,
        ),
        ActionParam(
            param_id="count",
            label="Count",
            description="Cap the number of matching experiments to act on.",
            required=False,
            param_type=ParamType.INT,
            default=None,
        ),
        ActionParam(
            param_id="name",
            label="Experiment Name",
            description="Filter by kRPC internal experiment name (e.g. 'temperatureScan').",
            required=False,
            param_type=ParamType.STR,
            default=None,
        ),
        ActionParam(
            param_id="title",
            label="Experiment Title",
            description="Filter by display title (e.g. '2HOT Thermometer').",
            required=False,
            param_type=ParamType.STR,
            default=None,
        ),
        ActionParam(
            param_id="name-tag",
            label="Name Tag",
            description="Filter by user-assigned part name tag.",
            required=False,
            param_type=ParamType.STR,
            default=None,
        ),
        ActionParam(
            param_id="has-data",
            label="Has Data",
            description="Filter by data status: true for experiments with data, false for those without. Omit to target all.",
            required=False,
            param_type=ParamType.BOOL,
            default=None,
        ),
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        raw_action: str | None = param_values["action"]
        if raw_action is not None:
            try:
                self._action: ScienceAction = ScienceAction(raw_action)
            except ValueError:
                valid = ", ".join(a.value for a in ScienceAction)
                raise ValueError(f"Unknown science action '{raw_action}'. Valid: {valid}") from None
        else:
            self._action = ScienceAction.RUN

        raw_index = param_values["index"]
        self._index: int | None = int(raw_index) if raw_index is not None else None
        raw_count = param_values["count"]
        self._count: int | None = int(raw_count) if raw_count is not None else None
        self._name: str | None = param_values["name"]
        self._title: str | None = param_values["title"]
        self._name_tag: str | None = param_values["name-tag"]
        self._has_data_filter: bool | None = param_values["has-data"]

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        candidates = [e for e in state.science_experiments if e.available and self._matches(e)]
        if not candidates:
            return ActionResult(
                status=ActionStatus.FAILED,
                message=f"Failed: no available science experiments match {self._filter_summary()}",
            )
        if self._count is not None:
            candidates = candidates[: self._count]

        commands.science_commands += tuple(ScienceCommand(e.index, self._action) for e in candidates)
        titles = ", ".join(e.title for e in candidates)
        return ActionResult(
            status=ActionStatus.SUCCEEDED,
            message=f"{self._action.display_name} applied to {len(candidates)} experiment(s): {titles}",
        )

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        pass

    # ---- Helpers ------------------------------------------------------

    def _matches(self, experiment: ScienceExperiment) -> bool:
        if self._index is not None and experiment.index != self._index:
            return False
        if self._name is not None and experiment.name != self._name:
            return False
        if self._title is not None and experiment.title != self._title:
            return False
        if self._name_tag is not None and experiment.name_tag != self._name_tag:
            return False
        return not (self._has_data_filter is not None and experiment.has_data != self._has_data_filter)

    def _filter_summary(self) -> str:
        parts: list[str] = []
        if self._index is not None:
            parts.append(f"index={self._index}")
        if self._name is not None:
            parts.append(f"name={self._name!r}")
        if self._title is not None:
            parts.append(f"title={self._title!r}")
        if self._name_tag is not None:
            parts.append(f"name-tag={self._name_tag!r}")
        if self._has_data_filter is not None:
            parts.append(f"has-data={self._has_data_filter}")
        if not parts:
            return "any filter"
        return ", ".join(parts)
