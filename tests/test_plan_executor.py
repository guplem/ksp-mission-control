"""Tests for the PlanExecutor flight plan execution system."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from ksp_mission_control.control.actions.base import (
    Action,
    ActionLogger,
    ActionParam,
    ActionResult,
    ActionStatus,
    VesselCommands,
    VesselState,
)
from ksp_mission_control.control.actions.flight_plan import FlightPlan, FlightPlanStep
from ksp_mission_control.control.actions.plan_executor import (
    PlanExecutor,
    PlanSnapshot,
    StepStatus,
)


class StubAction(Action):
    """Controllable stub action for testing the executor."""

    action_id: ClassVar[str] = "stub"
    label: ClassVar[str] = "Stub"
    description: ClassVar[str] = "A stub action for testing"
    params: ClassVar[list[ActionParam]] = [
        ActionParam("speed", "Speed", "Target speed", required=False, default=10.0, unit="m/s"),
    ]

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self._return_status = ActionStatus.RUNNING

    def set_return_status(self, status: ActionStatus) -> None:
        self._return_status = status

    def start(self, state: VesselState, param_values: dict[str, Any]) -> None:
        self.started = True

    def tick(
        self, state: VesselState, commands: VesselCommands, dt: float, log: ActionLogger
    ) -> ActionResult:
        commands.throttle = 0.5
        return ActionResult(status=self._return_status)

    def stop(self, state: VesselState, commands: VesselCommands, log: ActionLogger) -> None:
        self.stopped = True
        super().stop(state, commands, log)


def _make_plan(num_steps: int = 2) -> tuple[FlightPlan, list[StubAction]]:
    """Create a plan and matching stub action instances."""
    actions = [StubAction() for _ in range(num_steps)]
    steps = tuple(FlightPlanStep(action_id="stub", param_values={}) for _ in range(num_steps))
    plan = FlightPlan(name="test-plan", steps=steps)
    return plan, actions


class TestPlanExecutorSingleAction:
    """Tests that single-action mode works unchanged."""

    def test_start_and_step_single_action(self) -> None:
        executor = PlanExecutor()
        action = StubAction()
        state = VesselState()
        executor.start_action(action, state)
        result = executor.step(state, dt=0.5)
        assert result.commands.throttle == 0.5
        snap = executor.snapshot()
        assert snap.plan_name is None
        assert snap.runner.action_id == "stub"

    def test_single_action_clears_plan(self) -> None:
        executor = PlanExecutor()
        plan, actions = _make_plan(1)
        state = VesselState()
        executor.start_plan(plan, state, actions=actions)

        # Override with single action
        single = StubAction()
        executor.start_action(single, state)
        snap = executor.snapshot()
        assert snap.plan_name is None

    def test_abort_single_action(self) -> None:
        executor = PlanExecutor()
        action = StubAction()
        state = VesselState()
        executor.start_action(action, state)
        executor.abort()
        snap = executor.snapshot()
        assert snap.runner.action_id is None


class TestPlanExecutorPlan:
    """Tests for flight plan sequential execution."""

    def test_plan_snapshot_shows_progress(self) -> None:
        executor = PlanExecutor()
        plan, actions = _make_plan(2)
        state = VesselState()
        executor.start_plan(plan, state, actions=actions)

        snap = executor.snapshot()
        assert snap.plan_name == "test-plan"
        assert snap.current_step_index == 0
        assert snap.total_steps == 2
        assert snap.step_statuses == (StepStatus.RUNNING, StepStatus.PENDING)
        assert snap.runner.action_id == "stub"

    def test_step_advances_on_success(self) -> None:
        executor = PlanExecutor()
        plan, actions = _make_plan(2)
        state = VesselState()
        executor.start_plan(plan, state, actions=actions)

        # Step while running
        executor.step(state, dt=0.5)
        snap = executor.snapshot()
        assert snap.current_step_index == 0

        # Action succeeds
        actions[0].set_return_status(ActionStatus.SUCCEEDED)
        executor.step(state, dt=0.5)

        snap = executor.snapshot()
        assert snap.current_step_index == 1
        assert snap.step_statuses[0] == StepStatus.SUCCEEDED
        assert snap.step_statuses[1] == StepStatus.RUNNING

    def test_plan_completes_after_last_step(self) -> None:
        executor = PlanExecutor()
        plan, actions = _make_plan(1)
        state = VesselState()
        executor.start_plan(plan, state, actions=actions)

        actions[0].set_return_status(ActionStatus.SUCCEEDED)
        executor.step(state, dt=0.5)

        # Plan stays visible with all steps succeeded
        snap = executor.snapshot()
        assert snap.plan_name == "test-plan"
        assert snap.step_statuses == (StepStatus.SUCCEEDED,)

    def test_two_step_plan_completes_fully(self) -> None:
        executor = PlanExecutor()
        plan, actions = _make_plan(2)
        state = VesselState()
        executor.start_plan(plan, state, actions=actions)

        # Complete step 1
        actions[0].set_return_status(ActionStatus.SUCCEEDED)
        executor.step(state, dt=0.5)

        # Complete step 2
        actions[1].set_return_status(ActionStatus.SUCCEEDED)
        executor.step(state, dt=0.5)

        snap = executor.snapshot()
        assert snap.plan_name == "test-plan"
        assert snap.step_statuses == (StepStatus.SUCCEEDED, StepStatus.SUCCEEDED)

    def test_completed_plan_clears_on_new_action(self) -> None:
        executor = PlanExecutor()
        plan, actions = _make_plan(1)
        state = VesselState()
        executor.start_plan(plan, state, actions=actions)

        actions[0].set_return_status(ActionStatus.SUCCEEDED)
        executor.step(state, dt=0.5)

        # Starting a new action clears the completed plan
        executor.start_action(StubAction(), state)
        snap = executor.snapshot()
        assert snap.plan_name is None

    def test_plan_pauses_on_failure(self) -> None:
        executor = PlanExecutor()
        plan, actions = _make_plan(2)
        state = VesselState()
        executor.start_plan(plan, state, actions=actions)

        actions[0].set_return_status(ActionStatus.FAILED)
        executor.step(state, dt=0.5)

        assert executor.paused_on_failure is True
        snap = executor.snapshot()
        assert snap.step_statuses[0] == StepStatus.FAILED
        assert snap.step_statuses[1] == StepStatus.PENDING

    def test_continue_after_failure(self) -> None:
        executor = PlanExecutor()
        plan, actions = _make_plan(2)
        state = VesselState()
        executor.start_plan(plan, state, actions=actions)

        actions[0].set_return_status(ActionStatus.FAILED)
        executor.step(state, dt=0.5)
        assert executor.paused_on_failure is True

        executor.continue_plan(state)
        assert executor.paused_on_failure is False
        snap = executor.snapshot()
        assert snap.current_step_index == 1
        assert snap.step_statuses[1] == StepStatus.RUNNING

    def test_abort_plan_after_failure(self) -> None:
        executor = PlanExecutor()
        plan, actions = _make_plan(2)
        state = VesselState()
        executor.start_plan(plan, state, actions=actions)

        actions[0].set_return_status(ActionStatus.FAILED)
        executor.step(state, dt=0.5)

        executor.abort_plan()
        assert executor.paused_on_failure is False
        snap = executor.snapshot()
        assert snap.plan_name is None

    def test_abort_cancels_remaining_steps(self) -> None:
        executor = PlanExecutor()
        plan, actions = _make_plan(2)
        state = VesselState()
        executor.start_plan(plan, state, actions=actions)

        executor.step(state, dt=0.5)
        executor.abort()

        snap = executor.snapshot()
        assert snap.plan_name is None
        assert snap.total_steps == 0

    def test_paused_plan_does_not_advance(self) -> None:
        executor = PlanExecutor()
        plan, actions = _make_plan(2)
        state = VesselState()
        executor.start_plan(plan, state, actions=actions)

        actions[0].set_return_status(ActionStatus.FAILED)
        executor.step(state, dt=0.5)

        for _ in range(5):
            executor.step(state, dt=0.5)

        snap = executor.snapshot()
        assert snap.current_step_index == 0
        assert executor.paused_on_failure is True

    def test_continue_raises_when_no_paused_plan(self) -> None:
        executor = PlanExecutor()
        with pytest.raises(ValueError, match="No paused plan"):
            executor.continue_plan(VesselState())

    def test_continue_raises_when_no_more_steps(self) -> None:
        executor = PlanExecutor()
        plan, actions = _make_plan(1)
        state = VesselState()
        executor.start_plan(plan, state, actions=actions)

        actions[0].set_return_status(ActionStatus.FAILED)
        executor.step(state, dt=0.5)

        with pytest.raises(ValueError, match="No more steps"):
            executor.continue_plan(state)

    def test_empty_plan_raises(self) -> None:
        executor = PlanExecutor()
        plan = FlightPlan(name="empty", steps=())
        with pytest.raises(ValueError, match="has no steps"):
            executor.start_plan(plan, VesselState())

    def test_actions_list_length_mismatch_raises(self) -> None:
        executor = PlanExecutor()
        plan, _ = _make_plan(2)
        with pytest.raises(ValueError, match="must match"):
            executor.start_plan(plan, VesselState(), actions=[StubAction()])


class TestPlanSnapshot:
    """Tests for PlanSnapshot dataclass."""

    def test_default_snapshot_has_no_plan(self) -> None:
        snap = PlanSnapshot()
        assert snap.plan_name is None
        assert snap.total_steps == 0
        assert snap.step_statuses == ()

    def test_snapshot_is_frozen(self) -> None:
        snap = PlanSnapshot()
        with pytest.raises(AttributeError):
            snap.plan_name = "test"  # type: ignore[misc]
