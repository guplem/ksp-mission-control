"""MultiTrackExecutor - orchestrates parallel flight plan tracks.

Wraps multiple PlanExecutor instances (one per track) and merges their
VesselCommands each tick. Supports recursive @parallel sub-plan loading.

When only one track is active, behaves identically to a bare PlanExecutor.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Any

from ksp_mission_control.control.actions.base import (
    Action,
    ActionStatus,
    LogEntry,
    LogLevel,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.flight_plan import FlightPlan, parse_flight_plan
from ksp_mission_control.control.actions.plan_executor import PlanExecutor, PlanSnapshot
from ksp_mission_control.control.actions.runner import StepResult

_MAX_PARALLEL_DEPTH = 10
"""Maximum recursion depth for nested @parallel directives."""


@dataclass(frozen=True)
class TrackSnapshot:
    """Immutable snapshot of a single track's state."""

    track_name: str
    plan_snapshot: PlanSnapshot


@dataclass(frozen=True)
class MultiTrackSnapshot:
    """Immutable snapshot of all tracks for the UI."""

    tracks: tuple[TrackSnapshot, ...] = ()

    @property
    def primary(self) -> PlanSnapshot:
        """Return the first track's PlanSnapshot, or an empty one."""
        if self.tracks:
            return self.tracks[0].plan_snapshot
        return PlanSnapshot()

    @property
    def is_multi_track(self) -> bool:
        """Whether there are multiple active tracks."""
        return len(self.tracks) > 1


def _merge_commands(
    target: VesselCommands,
    source: VesselCommands,
    target_track: str,
    source_track: str,
    field_owners: dict[str, tuple[str, object]],
    warnings: list[LogEntry],
) -> None:
    """Merge non-None fields from source into target.

    Tracks which track last set each field in field_owners.
    Logs a warning when two tracks set the same field in the same tick.
    science_commands is additive (concatenated, no conflict).
    """
    for field in dataclass_fields(source):
        value = getattr(source, field.name)

        if field.name == "science_commands":
            if value:
                target.science_commands = target.science_commands + value
            continue

        if value is None:
            continue

        if field.name in field_owners:
            prev_track, prev_value = field_owners[field.name]
            if prev_track != source_track:
                warnings.append(
                    LogEntry(
                        level=LogLevel.PYTHON_WARNING,
                        message=(
                            f"Command conflict on '{field.name}': "
                            f"set by '{prev_track}' ({prev_value}) "
                            f"and '{source_track}' ({value}). Using last value."
                        ),
                    )
                )

        setattr(target, field.name, value)
        field_owners[field.name] = (source_track, value)


class MultiTrackExecutor:
    """Orchestrates parallel flight plan tracks.

    Wraps multiple PlanExecutor instances. Each tick, all tracks are stepped
    sequentially and their VesselCommands merged into one definitive buffer.
    """

    def __init__(self) -> None:
        self._tracks: list[tuple[str, PlanExecutor]] = []
        self._root_plan_name: str | None = None

    def start_action(
        self,
        action: Action,
        state: State,
        param_values: dict[str, Any] | None = None,
    ) -> None:
        """Start a single action (clears all tracks)."""
        self._tracks.clear()
        executor = PlanExecutor()
        executor.start_action(action, state, param_values)
        self._tracks.append(("main", executor))

    def start_plan(
        self,
        plan: FlightPlan,
        state: State,
        plans_dir: Path | None = None,
        actions: list[Action] | None = None,
    ) -> None:
        """Start a flight plan, recursively loading @parallel sub-plans.

        If actions is provided (for testing), only the root plan uses them
        and no parallel sub-plans are loaded.
        """
        self._tracks.clear()
        self._root_plan_name = plan.name

        if plan.steps:
            root_executor = PlanExecutor()
            root_executor.start_plan(plan, state, actions=actions)
            self._tracks.append((plan.name, root_executor))

        if actions is None and plans_dir is not None:
            self._load_parallel_plans(plan, state, plans_dir, depth=0)

    def _load_parallel_plans(
        self,
        plan: FlightPlan,
        state: State,
        plans_dir: Path,
        depth: int,
    ) -> None:
        """Recursively load @parallel sub-plans and flatten into tracks."""
        if depth >= _MAX_PARALLEL_DEPTH:
            return
        for parallel_path in plan.parallel_plans:
            sub_plan = parse_flight_plan(plans_dir / parallel_path)
            executor = PlanExecutor()
            executor.start_plan(sub_plan, state)
            self._tracks.append((sub_plan.name, executor))
            self._load_parallel_plans(sub_plan, state, plans_dir, depth + 1)

    def step(self, vessel_state: State, dt: float) -> StepResult:
        """Tick all tracks, merge commands, aggregate logs."""
        merged_commands = VesselCommands()
        all_logs: list[LogEntry] = []
        field_owners: dict[str, tuple[str, object]] = {}
        warnings: list[LogEntry] = []
        finished_status: ActionStatus | None = None
        is_multi = len(self._tracks) > 1

        completed_tracks: list[str] = []

        for track_name, executor in self._tracks:
            result = executor.step(vessel_state, dt)
            _merge_commands(
                merged_commands,
                result.commands,
                target_track="merged",
                source_track=track_name,
                field_owners=field_owners,
                warnings=warnings,
            )
            if is_multi and result.logs:
                for log_entry in result.logs:
                    all_logs.append(
                        LogEntry(
                            level=log_entry.level,
                            message=log_entry.message,
                            track_name=track_name,
                            action_id=log_entry.action_id,
                            plan_step=log_entry.plan_step,
                        )
                    )
            else:
                all_logs.extend(result.logs)

            # Check if this track's plan is fully completed
            snap = executor.snapshot()
            if snap.plan_name is not None and snap.runner.action_id is None:
                all_succeeded = all(s.value == "succeeded" for s in snap.step_statuses)
                if all_succeeded:
                    completed_tracks.append(track_name)

        # Primary track (first) determines the overall finished_status
        if self._tracks:
            primary_name, primary_executor = self._tracks[0]
            primary_result = primary_executor.snapshot()
            if primary_result.runner.action_id is None and primary_result.plan_name is not None:
                all_succeeded = all(s.value == "succeeded" for s in primary_result.step_statuses)
                if all_succeeded:
                    finished_status = ActionStatus.SUCCEEDED

        all_logs.extend(warnings)
        return StepResult(
            commands=merged_commands,
            logs=all_logs,
            finished_status=finished_status,
        )

    def abort(self) -> StepResult:
        """Abort all tracks."""
        merged_commands = VesselCommands()
        all_logs: list[LogEntry] = []
        for _track_name, executor in self._tracks:
            result = executor.abort()
            for field in dataclass_fields(result.commands):
                value = getattr(result.commands, field.name)
                if field.name == "science_commands":
                    if value:
                        merged_commands.science_commands = merged_commands.science_commands + value
                elif value is not None:
                    setattr(merged_commands, field.name, value)
            all_logs.extend(result.logs)
        self._tracks.clear()
        return StepResult(commands=merged_commands, logs=all_logs)

    def abort_track(self, track_name: str) -> StepResult:
        """Abort a single track by name."""
        for index, (name, executor) in enumerate(self._tracks):
            if name == track_name:
                result = executor.abort()
                self._tracks.pop(index)
                return result
        raise ValueError(f"Unknown track: {track_name!r}")

    def continue_track(self, track_name: str, vessel_state: State) -> None:
        """Continue a paused track (skip failed step)."""
        for name, executor in self._tracks:
            if name == track_name:
                executor.continue_plan(vessel_state)
                return
        raise ValueError(f"Unknown track: {track_name!r}")

    def abort_plan(self) -> StepResult:
        """Abort all tracks (called when user chooses abort after failure)."""
        return self.abort()

    def continue_plan(self, vessel_state: State) -> None:
        """Continue the first paused track."""
        for _name, executor in self._tracks:
            if executor.paused_on_failure:
                executor.continue_plan(vessel_state)
                return
        raise ValueError("No paused plan to continue")

    @property
    def paused_on_failure(self) -> bool:
        """Whether any track is paused waiting for user decision."""
        return any(executor.paused_on_failure for _name, executor in self._tracks)

    def paused_tracks(self) -> list[str]:
        """Return names of all tracks that are paused on failure."""
        return [name for name, executor in self._tracks if executor.paused_on_failure]

    def snapshot(self) -> MultiTrackSnapshot:
        """Return an immutable snapshot of all tracks."""
        tracks = tuple(TrackSnapshot(track_name=name, plan_snapshot=executor.snapshot()) for name, executor in self._tracks)
        return MultiTrackSnapshot(tracks=tracks)

    @property
    def track_count(self) -> int:
        """Number of active tracks."""
        return len(self._tracks)
