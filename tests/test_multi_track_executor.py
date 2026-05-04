"""Tests for the MultiTrackExecutor parallel plan execution system."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest

from ksp_mission_control.control.actions.base import (
    Action,
    ActionLogger,
    ActionParam,
    ActionResult,
    ActionStatus,
    LogLevel,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.flight_plan import FlightPlan, FlightPlanStep
from ksp_mission_control.control.actions.multi_track_executor import (
    MultiTrackExecutor,
    MultiTrackSnapshot,
    TrackSnapshot,
    _merge_commands,
)
from ksp_mission_control.control.actions.plan_executor import PlanSnapshot, StepStatus


class StubAction(Action):
    """Controllable stub action for testing."""

    action_id: ClassVar[str] = "stub"
    label: ClassVar[str] = "Stub"
    description: ClassVar[str] = "A stub action for testing"
    params: ClassVar[list[ActionParam]] = []

    def __init__(self, throttle: float | None = None) -> None:
        self._return_status = ActionStatus.RUNNING
        self._throttle = throttle

    def set_return_status(self, status: ActionStatus) -> None:
        self._return_status = status

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        pass

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        if self._throttle is not None:
            commands.throttle = self._throttle
        return ActionResult(status=self._return_status)

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)


class ScienceStubAction(Action):
    """Stub action that only sets science commands."""

    action_id: ClassVar[str] = "science_stub"
    label: ClassVar[str] = "Science Stub"
    description: ClassVar[str] = "A stub action that sets science fields"
    params: ClassVar[list[ActionParam]] = []

    def __init__(self) -> None:
        self._return_status = ActionStatus.RUNNING

    def set_return_status(self, status: ActionStatus) -> None:
        self._return_status = status

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        pass

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        from ksp_mission_control.control.actions.base import ScienceAction

        commands.all_science = ScienceAction.RUN
        return ActionResult(status=self._return_status)

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)


def _make_plan(
    name: str = "test-plan",
    num_steps: int = 2,
    throttle: float | None = 0.5,
) -> tuple[FlightPlan, list[StubAction]]:
    """Create a plan and matching stub action instances."""
    actions = [StubAction(throttle=throttle) for _ in range(num_steps)]
    steps = tuple(FlightPlanStep(action_id="stub", param_values={}) for _ in range(num_steps))
    plan = FlightPlan(name=name, steps=steps)
    return plan, actions


def _make_science_plan(
    name: str = "science-plan",
    num_steps: int = 1,
) -> tuple[FlightPlan, list[ScienceStubAction]]:
    """Create a science plan with stub actions."""
    actions = [ScienceStubAction() for _ in range(num_steps)]
    steps = tuple(FlightPlanStep(action_id="science_stub", param_values={}) for _ in range(num_steps))
    plan = FlightPlan(name=name, steps=steps)
    return plan, actions


class TestMultiTrackSnapshot:
    """Tests for snapshot dataclasses."""

    def test_empty_snapshot_has_no_tracks(self) -> None:
        snap = MultiTrackSnapshot()
        assert snap.tracks == ()
        assert snap.is_multi_track is False

    def test_primary_returns_empty_plan_snapshot_when_no_tracks(self) -> None:
        snap = MultiTrackSnapshot()
        assert snap.primary.plan_name is None

    def test_primary_returns_first_track(self) -> None:
        plan_snap = PlanSnapshot(plan_name="test")
        track = TrackSnapshot(track_name="main", plan_snapshot=plan_snap)
        snap = MultiTrackSnapshot(tracks=(track,))
        assert snap.primary.plan_name == "test"
        assert snap.is_multi_track is False

    def test_is_multi_track_with_two_tracks(self) -> None:
        tracks = (
            TrackSnapshot(track_name="a", plan_snapshot=PlanSnapshot()),
            TrackSnapshot(track_name="b", plan_snapshot=PlanSnapshot()),
        )
        snap = MultiTrackSnapshot(tracks=tracks)
        assert snap.is_multi_track is True


class TestMergeCommands:
    """Tests for the _merge_commands function."""

    def test_merge_non_none_fields(self) -> None:
        target = VesselCommands()
        source = VesselCommands(throttle=0.7)
        field_owners: dict[str, tuple[str, object]] = {}
        warnings: list = []
        _merge_commands(target, source, "merged", "track-a", field_owners, warnings)
        assert target.throttle == 0.7
        assert len(warnings) == 0

    def test_merge_skips_none_fields(self) -> None:
        target = VesselCommands(throttle=0.5)
        source = VesselCommands()
        field_owners: dict[str, tuple[str, object]] = {}
        warnings: list = []
        _merge_commands(target, source, "merged", "track-a", field_owners, warnings)
        assert target.throttle == 0.5

    def test_conflict_warning_on_same_field(self) -> None:
        target = VesselCommands()
        source_a = VesselCommands(throttle=0.7)
        source_b = VesselCommands(throttle=0.8)
        field_owners: dict[str, tuple[str, object]] = {}
        warnings: list = []

        _merge_commands(target, source_a, "merged", "track-a", field_owners, warnings)
        _merge_commands(target, source_b, "merged", "track-b", field_owners, warnings)

        assert target.throttle == 0.8
        assert len(warnings) == 1
        assert warnings[0].level == LogLevel.PYTHON_WARNING
        assert "throttle" in warnings[0].message
        assert "track-a" in warnings[0].message
        assert "track-b" in warnings[0].message

    def test_science_commands_concatenate(self) -> None:
        from ksp_mission_control.control.actions.base import ScienceAction, ScienceCommand

        target = VesselCommands()
        cmd_a = ScienceCommand(experiment_index=0, action=ScienceAction.RUN)
        cmd_b = ScienceCommand(experiment_index=1, action=ScienceAction.RUN)
        source_a = VesselCommands(science_commands=(cmd_a,))
        source_b = VesselCommands(science_commands=(cmd_b,))

        field_owners: dict[str, tuple[str, object]] = {}
        warnings: list = []
        _merge_commands(target, source_a, "merged", "track-a", field_owners, warnings)
        _merge_commands(target, source_b, "merged", "track-b", field_owners, warnings)

        assert len(target.science_commands) == 2
        assert target.science_commands[0].experiment_index == 0
        assert target.science_commands[1].experiment_index == 1
        assert len(warnings) == 0

    def test_no_conflict_when_same_track_sets_field_twice(self) -> None:
        target = VesselCommands()
        source = VesselCommands(throttle=0.5)
        field_owners: dict[str, tuple[str, object]] = {}
        warnings: list = []
        _merge_commands(target, source, "merged", "track-a", field_owners, warnings)
        _merge_commands(target, source, "merged", "track-a", field_owners, warnings)
        assert len(warnings) == 0


class TestMultiTrackExecutorSingleAction:
    """Tests that single-action mode works as a drop-in for PlanExecutor."""

    def test_start_and_step_single_action(self) -> None:
        executor = MultiTrackExecutor()
        action = StubAction(throttle=0.5)
        state = State()
        executor.start_action(action, state)
        result = executor.step(state, dt=0.5)
        assert result.commands.throttle == 0.5
        snap = executor.snapshot()
        assert snap.primary.runner.action_id == "stub"

    def test_abort_single_action(self) -> None:
        executor = MultiTrackExecutor()
        action = StubAction()
        state = State()
        executor.start_action(action, state)
        executor.abort()
        snap = executor.snapshot()
        assert snap.tracks == ()

    def test_single_action_has_one_track(self) -> None:
        executor = MultiTrackExecutor()
        action = StubAction()
        executor.start_action(action, State())
        assert executor.track_count == 1


class TestMultiTrackExecutorSinglePlan:
    """Tests for single-plan mode (drop-in replacement for PlanExecutor)."""

    def test_plan_snapshot_shows_progress(self) -> None:
        executor = MultiTrackExecutor()
        plan, actions = _make_plan(num_steps=2)
        state = State()
        executor.start_plan(plan, state, actions=actions)

        snap = executor.snapshot()
        assert snap.primary.plan_name == "test-plan"
        assert snap.primary.current_step_index == 0
        assert snap.primary.total_steps == 2
        assert snap.primary.step_statuses == (StepStatus.RUNNING, StepStatus.PENDING)

    def test_step_advances_on_success(self) -> None:
        executor = MultiTrackExecutor()
        plan, actions = _make_plan(num_steps=2)
        state = State()
        executor.start_plan(plan, state, actions=actions)

        executor.step(state, dt=0.5)
        actions[0].set_return_status(ActionStatus.SUCCEEDED)
        executor.step(state, dt=0.5)

        snap = executor.snapshot()
        assert snap.primary.current_step_index == 1
        assert snap.primary.step_statuses[0] == StepStatus.SUCCEEDED
        assert snap.primary.step_statuses[1] == StepStatus.RUNNING

    def test_auto_continues_on_failure(self) -> None:
        executor = MultiTrackExecutor()
        plan, actions = _make_plan(num_steps=2)
        state = State()
        executor.start_plan(plan, state, actions=actions)

        actions[0].set_return_status(ActionStatus.FAILED)
        executor.step(state, dt=0.5)

        snap = executor.snapshot()
        assert snap.primary.step_statuses[0] == StepStatus.FAILED
        assert snap.primary.step_statuses[1] == StepStatus.RUNNING
        assert snap.primary.current_step_index == 1

    def test_abort_plan(self) -> None:
        executor = MultiTrackExecutor()
        plan, actions = _make_plan(num_steps=2)
        state = State()
        executor.start_plan(plan, state, actions=actions)
        executor.abort()
        snap = executor.snapshot()
        assert snap.tracks == ()

    def test_start_plan_clears_previous(self) -> None:
        executor = MultiTrackExecutor()
        plan1, actions1 = _make_plan(name="plan-1", num_steps=1)
        plan2, actions2 = _make_plan(name="plan-2", num_steps=1)
        state = State()

        executor.start_plan(plan1, state, actions=actions1)
        executor.start_plan(plan2, state, actions=actions2)

        snap = executor.snapshot()
        assert snap.primary.plan_name == "plan-2"
        assert executor.track_count == 1

    def test_is_not_multi_track_for_single_plan(self) -> None:
        executor = MultiTrackExecutor()
        plan, actions = _make_plan(num_steps=1)
        executor.start_plan(plan, State(), actions=actions)
        assert executor.snapshot().is_multi_track is False


class TestMultiTrackExecutorParallel:
    """Tests for multi-track parallel execution."""

    def test_two_tracks_merge_disjoint_commands(self) -> None:
        executor = MultiTrackExecutor()
        flight_plan, flight_actions = _make_plan(name="flight", num_steps=1, throttle=0.8)
        science_plan, science_actions = _make_science_plan(name="science", num_steps=1)

        state = State()
        executor.start_plan(flight_plan, state, actions=flight_actions)

        # Manually add a second track (simulating @parallel loading)
        from ksp_mission_control.control.actions.plan_executor import PlanExecutor

        science_executor = PlanExecutor()
        science_executor.start_plan(science_plan, state, actions=science_actions)
        executor._tracks.append(("science", science_executor))

        result = executor.step(state, dt=0.5)
        assert result.commands.throttle == 0.8
        from ksp_mission_control.control.actions.base import ScienceAction

        assert result.commands.all_science == ScienceAction.RUN
        assert executor.snapshot().is_multi_track is True

    def test_conflict_warning_when_tracks_set_same_field(self) -> None:
        executor = MultiTrackExecutor()
        plan_a, actions_a = _make_plan(name="plan-a", num_steps=1, throttle=0.7)
        plan_b, actions_b = _make_plan(name="plan-b", num_steps=1, throttle=0.9)

        state = State()
        executor.start_plan(plan_a, state, actions=actions_a)

        from ksp_mission_control.control.actions.plan_executor import PlanExecutor

        executor_b = PlanExecutor()
        executor_b.start_plan(plan_b, state, actions=actions_b)
        executor._tracks.append(("plan-b", executor_b))

        result = executor.step(state, dt=0.5)
        assert result.commands.throttle == 0.9

        warn_logs = [log for log in result.logs if log.level == LogLevel.PYTHON_WARNING]
        assert len(warn_logs) == 1
        assert "throttle" in warn_logs[0].message
        assert "plan-a" in warn_logs[0].message
        assert "plan-b" in warn_logs[0].message

    def test_track_level_failure_isolation(self) -> None:
        """Failure in one track should not affect others."""
        executor = MultiTrackExecutor()
        plan_a, actions_a = _make_plan(name="flight", num_steps=2, throttle=0.5)
        plan_b, actions_b = _make_plan(name="science", num_steps=2, throttle=None)

        state = State()
        executor.start_plan(plan_a, state, actions=actions_a)

        from ksp_mission_control.control.actions.plan_executor import PlanExecutor

        executor_b = PlanExecutor()
        executor_b.start_plan(plan_b, state, actions=actions_b)
        executor._tracks.append(("science", executor_b))

        # Fail science track - it auto-continues (no pause)
        actions_b[0].set_return_status(ActionStatus.FAILED)
        executor.step(state, dt=0.5)

        # Flight track should still be running
        snap = executor.snapshot()
        flight_snap = snap.tracks[0].plan_snapshot
        assert flight_snap.runner.action_id == "stub"

    def test_abort_track_removes_only_that_track(self) -> None:
        executor = MultiTrackExecutor()
        plan_a, actions_a = _make_plan(name="flight", num_steps=1, throttle=0.5)
        plan_b, actions_b = _make_plan(name="science", num_steps=1, throttle=None)

        state = State()
        executor.start_plan(plan_a, state, actions=actions_a)

        from ksp_mission_control.control.actions.plan_executor import PlanExecutor

        executor_b = PlanExecutor()
        executor_b.start_plan(plan_b, state, actions=actions_b)
        executor._tracks.append(("science", executor_b))

        executor.abort_track("science")
        assert executor.track_count == 1
        assert executor.snapshot().tracks[0].track_name == "flight"

    def test_abort_track_raises_for_unknown(self) -> None:
        executor = MultiTrackExecutor()
        with pytest.raises(ValueError, match="Unknown track"):
            executor.abort_track("nonexistent")


class TestMultiTrackRecursiveLoading:
    """Tests for recursive @parallel sub-plan loading from .plan files."""

    def test_loads_parallel_sub_plan(self, tmp_path: Path) -> None:
        # Create sub-plan
        sub_plan = tmp_path / "sub.plan"
        sub_plan.write_text("hover\n")

        # Create main plan referencing sub-plan
        main_plan = tmp_path / "main.plan"
        main_plan.write_text("@parallel sub.plan\nhover\n")

        from ksp_mission_control.control.actions.flight_plan import parse_flight_plan

        plan = parse_flight_plan(main_plan)

        executor = MultiTrackExecutor()
        executor.start_plan(plan, State(), plans_dir=tmp_path)

        assert executor.track_count == 2
        snap = executor.snapshot()
        assert snap.tracks[0].track_name == "main"
        assert snap.tracks[1].track_name == "sub"
        assert snap.is_multi_track is True

    def test_loads_nested_parallel_plans(self, tmp_path: Path) -> None:
        # Create deeply nested plan
        deep = tmp_path / "deep.plan"
        deep.write_text("hover\n")

        # Create mid-level plan with @parallel to deep
        mid = tmp_path / "mid.plan"
        mid.write_text("@parallel deep.plan\nhover\n")

        # Create root plan with @parallel to mid
        root = tmp_path / "root.plan"
        root.write_text("@parallel mid.plan\nhover\n")

        from ksp_mission_control.control.actions.flight_plan import parse_flight_plan

        plan = parse_flight_plan(root)

        executor = MultiTrackExecutor()
        executor.start_plan(plan, State(), plans_dir=tmp_path)

        # root + mid + deep = 3 tracks
        assert executor.track_count == 3
        snap = executor.snapshot()
        track_names = [t.track_name for t in snap.tracks]
        assert track_names == ["root", "mid", "deep"]

    def test_parallel_plans_in_subdirectory(self, tmp_path: Path) -> None:
        # Create subdirectory with plan
        science_dir = tmp_path / "science"
        science_dir.mkdir()
        sub_plan = science_dir / "collect.plan"
        sub_plan.write_text("hover\n")

        # Main plan references sub-plan via relative path
        main_plan = tmp_path / "main.plan"
        main_plan.write_text("@parallel science/collect.plan\nhover\n")

        from ksp_mission_control.control.actions.flight_plan import parse_flight_plan

        plan = parse_flight_plan(main_plan)

        executor = MultiTrackExecutor()
        executor.start_plan(plan, State(), plans_dir=tmp_path)

        assert executor.track_count == 2
        snap = executor.snapshot()
        assert snap.tracks[1].track_name == "collect"

    def test_meta_plan_with_only_parallel_no_steps(self, tmp_path: Path) -> None:
        """A plan with only @parallel directives and no steps should work."""
        sub_a = tmp_path / "a.plan"
        sub_a.write_text("hover\n")
        sub_b = tmp_path / "b.plan"
        sub_b.write_text("hover\n")

        main = tmp_path / "meta.plan"
        main.write_text("@parallel a.plan\n@parallel b.plan\n")

        from ksp_mission_control.control.actions.flight_plan import parse_flight_plan

        plan = parse_flight_plan(main)

        executor = MultiTrackExecutor()
        executor.start_plan(plan, State(), plans_dir=tmp_path)

        # Root has no steps, so only the two sub-plans become tracks
        assert executor.track_count == 2
        snap = executor.snapshot()
        assert snap.tracks[0].track_name == "a"
        assert snap.tracks[1].track_name == "b"
        assert snap.is_multi_track is True

    def test_all_tracks_tick_together(self, tmp_path: Path) -> None:
        sub_plan = tmp_path / "sub.plan"
        sub_plan.write_text("hover\n")

        main_plan = tmp_path / "main.plan"
        main_plan.write_text("@parallel sub.plan\nhover\n")

        from ksp_mission_control.control.actions.flight_plan import parse_flight_plan

        plan = parse_flight_plan(main_plan)

        executor = MultiTrackExecutor()
        executor.start_plan(plan, State(), plans_dir=tmp_path)

        result = executor.step(State(), dt=0.5)
        # Both tracks should produce logs (at least "Started" messages)
        assert len(result.logs) > 0
        # Both tracks have running actions
        snap = executor.snapshot()
        assert snap.tracks[0].plan_snapshot.runner.action_id is not None
        assert snap.tracks[1].plan_snapshot.runner.action_id is not None
