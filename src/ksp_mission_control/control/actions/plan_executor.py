"""PlanExecutor - sequential flight plan executor wrapping ActionRunner.

Manages executing a FlightPlan step-by-step. When the current action
succeeds, automatically starts the next step. On failure, pauses the
plan for the UI to show a confirmation dialog.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ksp_mission_control.control.actions.base import Action, VesselState
from ksp_mission_control.control.actions.flight_plan import FlightPlan
from ksp_mission_control.control.actions.registry import get_available_actions
from ksp_mission_control.control.actions.runner import (
    ActionRunner,
    RunnerSnapshot,
    StepResult,
)


class StepStatus(Enum):
    """Status of a single step in a flight plan."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class PlanSnapshot:
    """Thread-safe snapshot of plan execution state for the UI."""

    plan_name: str | None = None
    current_step_index: int = 0
    total_steps: int = 0
    step_statuses: tuple[StepStatus, ...] = ()
    step_action_ids: tuple[str, ...] = ()
    runner: RunnerSnapshot = field(default_factory=RunnerSnapshot)


class PlanExecutor:
    """Wraps ActionRunner to execute flight plans sequentially.

    Supports both single-action execution (no plan) and multi-step
    flight plans. The existing ActionRunner handles per-action lifecycle;
    PlanExecutor manages the step-to-step transitions.
    """

    def __init__(self) -> None:
        self._runner: ActionRunner = ActionRunner()
        self._plan: FlightPlan | None = None
        self._step_actions: list[Action] = []
        self._step_index: int = 0
        self._step_statuses: list[StepStatus] = []
        self._paused_on_failure: bool = False

    def start_action(
        self,
        action: Action,
        state: VesselState,
        param_values: dict[str, Any] | None = None,
    ) -> None:
        """Start a single action (clears any active plan)."""
        self._clear_plan()
        self._runner.start_action(action, state, param_values)

    def start_plan(
        self,
        plan: FlightPlan,
        state: VesselState,
        actions: list[Action] | None = None,
    ) -> None:
        """Start executing a flight plan from the first step.

        If *actions* is provided, use those instances for each step
        (must match plan.steps length). Otherwise resolve from the registry.
        """
        if not plan.steps:
            raise ValueError("Flight plan has no steps")

        if actions is not None:
            if len(actions) != len(plan.steps):
                raise ValueError("Actions list length must match plan steps")
            self._step_actions = list(actions)
        else:
            self._step_actions = [self._resolve_action(step.action_id) for step in plan.steps]

        self._plan = plan
        self._step_index = 0
        self._step_statuses = [StepStatus.PENDING] * len(plan.steps)
        self._paused_on_failure = False

        self._step_statuses[0] = StepStatus.RUNNING
        self._runner.start_action(self._step_actions[0], state, plan.steps[0].param_values)

    def step(self, vessel_state: VesselState, dt: float) -> StepResult:
        """Tick the runner. If a plan is active, handle step transitions."""
        had_action = self._runner.snapshot().action_id is not None
        result = self._runner.step(vessel_state, dt)

        if self._plan is None or self._paused_on_failure:
            return result

        has_action = self._runner.snapshot().action_id is not None

        # Detect action completion: was running, now cleared
        if had_action and not has_action:
            succeeded = self._detect_succeeded(result)

            if succeeded:
                self._step_statuses[self._step_index] = StepStatus.SUCCEEDED

                # Advance to next step if available
                if self._step_index + 1 < len(self._plan.steps):
                    self._step_index += 1
                    self._step_statuses[self._step_index] = StepStatus.RUNNING
                    self._runner.start_action(
                        self._step_actions[self._step_index],
                        vessel_state,
                        self._plan.steps[self._step_index].param_values,
                    )
                    # Flush "Started: ..." log so it appears in this tick's result,
                    # not delayed until the next step() call.
                    result.logs.extend(self._runner.flush_pending_logs())
                else:
                    # Plan complete - keep snapshot visible until next action/plan
                    pass
            else:
                # Action failed - pause for user decision
                self._step_statuses[self._step_index] = StepStatus.FAILED
                self._paused_on_failure = True

        return result

    def abort(self) -> StepResult:
        """Abort the current action and cancel any remaining plan."""
        result = self._runner.abort()
        self._clear_plan()
        return result

    def continue_plan(self, vessel_state: VesselState) -> None:
        """Resume a paused plan by skipping the failed step and starting the next.

        Called by the UI when the user chooses to continue after a failure.
        Raises ValueError if no plan is paused or no more steps remain.
        """
        if self._plan is None or not self._paused_on_failure:
            raise ValueError("No paused plan to continue")

        self._paused_on_failure = False

        if self._step_index + 1 >= len(self._plan.steps):
            self._clear_plan()
            raise ValueError("No more steps in the plan")

        self._step_index += 1
        self._step_statuses[self._step_index] = StepStatus.RUNNING
        self._runner.start_action(
            self._step_actions[self._step_index],
            vessel_state,
            self._plan.steps[self._step_index].param_values,
        )
        # Flush so the "Started" log appears on the next step() result immediately
        self._runner.flush_pending_logs()

    def abort_plan(self) -> StepResult:
        """Abort a paused plan (user chose not to continue after failure)."""
        result = self._runner.abort()
        self._clear_plan()
        return result

    @property
    def paused_on_failure(self) -> bool:
        """Whether the plan is paused waiting for user decision after a failure."""
        return self._paused_on_failure

    def snapshot(self) -> PlanSnapshot:
        """Return a thread-safe snapshot of plan + runner state."""
        runner_snap = self._runner.snapshot()
        if self._plan is not None:
            return PlanSnapshot(
                plan_name=self._plan.name,
                current_step_index=self._step_index,
                total_steps=len(self._plan.steps),
                step_statuses=tuple(self._step_statuses),
                step_action_ids=tuple(s.action_id for s in self._plan.steps),
                runner=runner_snap,
            )
        return PlanSnapshot(runner=runner_snap)

    def _clear_plan(self) -> None:
        """Reset all plan state."""
        self._plan = None
        self._step_actions = []
        self._step_index = 0
        self._step_statuses = []
        self._paused_on_failure = False

    def _detect_succeeded(self, result: StepResult) -> bool:
        """Check step result logs to determine if the action succeeded."""
        for entry in result.logs:
            if "Finished:" in entry.message and "succeeded" in entry.message:
                return True
        return False

    def _resolve_action(self, action_id: str) -> Action:
        """Get a fresh action instance by ID from the registry."""
        for action in get_available_actions():
            if action.action_id == action_id:
                return action
        raise ValueError(f"Unknown action: {action_id!r}")
