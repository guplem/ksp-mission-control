"""PlanExecutor - sequential flight plan executor wrapping ActionRunner.

Manages executing a FlightPlan step-by-step. When the current action
succeeds, automatically starts the next step. On failure, logs a warning
and auto-continues to the next step.

``ParallelStep`` entries are processed inline: when reached, the executor
invokes ``spawn_parallel`` (provided by the caller, typically the
``MultiTrackExecutor``), marks the step ``SUCCEEDED`` immediately, and
advances to the next step within the same tick.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ksp_mission_control.control.actions.base import (
    Action,
    ActionStatus,
    LogEntry,
    LogLevel,
    State,
)
from ksp_mission_control.control.actions.flight_plan import (
    FlightPlan,
    FlightPlanStep,
    ParallelStep,
)
from ksp_mission_control.control.actions.registry import get_available_actions
from ksp_mission_control.control.actions.runner import (
    ActionRunner,
    RunnerSnapshot,
    StepResult,
)

PARALLEL_ACTION_ID = "@parallel"
"""Synthetic action_id used for parallel-spawn steps in snapshots and logs."""


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
    step_action_labels: tuple[str, ...] = ()
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
        self._step_actions: list[Action | None] = []
        self._step_index: int = 0
        self._step_statuses: list[StepStatus] = []
        self._emit_plan_started: bool = False
        self._spawn_parallel: Callable[[str, State], None] | None = None
        self._queued_logs: list[LogEntry] = []
        """Logs produced outside of runner ticks (parallel spawns, PLAN_END from
        a plan that ends in parallel steps). Drained on the next step()."""
        self._plan_ended: bool = False
        """True once PLAN_END has been queued or emitted, to prevent duplicates."""

    def start_action(
        self,
        action: Action,
        state: State,
        param_values: dict[str, Any] | None = None,
    ) -> None:
        """Start a single action (clears any active plan)."""
        self._clear_plan()
        self._runner.start_action(action, state, param_values)

    def start_plan(
        self,
        plan: FlightPlan,
        state: State,
        actions: list[Action] | None = None,
        spawn_parallel: Callable[[str, State], None] | None = None,
    ) -> None:
        """Start executing a flight plan from the first step.

        If *actions* is provided, use those instances for each action step
        in order (must match the number of action steps). Otherwise resolve
        from the registry. ``ParallelStep`` entries do not consume an entry
        from *actions*.

        *spawn_parallel* is invoked with the relative plan path each time
        a ``ParallelStep`` is reached. When None, parallel steps are still
        marked SUCCEEDED but no track is spawned.
        """
        if not plan.steps:
            raise ValueError("Flight plan has no steps")

        self._step_actions = self._build_step_actions(plan, actions)

        self._plan = plan
        self._spawn_parallel = spawn_parallel
        self._step_index = 0
        self._step_statuses = [StepStatus.PENDING] * len(plan.steps)
        self._emit_plan_started = True
        self._queued_logs = []
        self._plan_ended = False

        self._begin_from(state, 0)

    def _build_step_actions(
        self,
        plan: FlightPlan,
        actions: list[Action] | None,
    ) -> list[Action | None]:
        """Build the per-step Action list, with None for ParallelStep slots.

        When *actions* is provided, it must contain one Action per
        FlightPlanStep in order; ParallelStep slots are filled with None.
        """
        if actions is None:
            return [self._resolve_action(step.action_id) if isinstance(step, FlightPlanStep) else None for step in plan.steps]

        action_step_count = sum(1 for step in plan.steps if isinstance(step, FlightPlanStep))
        if len(actions) != action_step_count:
            raise ValueError(f"Actions list length ({len(actions)}) must match the number of FlightPlanSteps in the plan ({action_step_count})")

        action_iter = iter(actions)
        return [next(action_iter) if isinstance(step, FlightPlanStep) else None for step in plan.steps]

    def _begin_from(self, state: State, index: int) -> None:
        """Advance through ParallelStep entries starting at *index*.

        Spawns each parallel sub-plan and marks its step SUCCEEDED until
        either an action step is reached (which starts on the runner) or
        the plan ends (which queues PLAN_END).
        """
        assert self._plan is not None
        steps = self._plan.steps

        while index < len(steps):
            step = steps[index]
            if isinstance(step, ParallelStep):
                self._step_index = index
                self._step_statuses[index] = StepStatus.SUCCEEDED
                self._queued_logs.append(
                    LogEntry(
                        level=LogLevel.LOG_INFO,
                        message=f"Spawned parallel track: {step.plan_name}",
                        action_id=PARALLEL_ACTION_ID,
                        plan_step=index + 1,
                    )
                )
                if self._spawn_parallel is not None:
                    self._spawn_parallel(step.plan_path, state)
                index += 1
                continue

            action = self._step_actions[index]
            assert action is not None
            self._step_index = index
            self._step_statuses[index] = StepStatus.RUNNING
            self._runner.start_action(action, state, step.param_values)
            return

        self._step_index = len(steps) - 1
        if not self._plan_ended:
            self._plan_ended = True
            self._queued_logs.append(LogEntry(level=LogLevel.PLAN_END, message=self._plan.name))

    def step(self, vessel_state: State, dt: float) -> StepResult:
        """Tick the runner. If a plan is active, handle step transitions."""
        had_action = self._runner.snapshot().action_id is not None
        result = self._runner.step(vessel_state, dt)

        if self._plan is not None and self._emit_plan_started:
            self._emit_plan_started = False
            result.logs.insert(0, LogEntry(level=LogLevel.PLAN_START, message=self._plan.name))

        if self._plan is not None and self._queued_logs:
            result.logs.extend(self._queued_logs)
            self._queued_logs = []

        if self._plan is None:
            return result

        has_action = self._runner.snapshot().action_id is not None

        # Annotate logs with the action_id and plan_step of the step that
        # produced them. Must run BEFORE the step-transition block below:
        # that block advances self._step_index to the next step, but the
        # runner-produced logs collected this tick (LOG_*, ACTION_FAILED,
        # ACTION_END, ...) belong to the step that just finished.
        if result.logs:
            current_step = self._plan.steps[self._step_index] if 0 <= self._step_index < len(self._plan.steps) else None
            if isinstance(current_step, FlightPlanStep):
                fallback_action_id: str | None = current_step.action_id
            elif isinstance(current_step, ParallelStep):
                fallback_action_id = PARALLEL_ACTION_ID
            else:
                fallback_action_id = None
            plan_step = self._step_index + 1
            result.logs[:] = [
                LogEntry(
                    level=entry.level,
                    message=entry.message,
                    track_name=entry.track_name,
                    action_id=entry.action_id or fallback_action_id,
                    plan_step=entry.plan_step if entry.plan_step is not None else plan_step,
                )
                for entry in result.logs
            ]

        # Detect action completion: was running, now cleared
        if had_action and not has_action:
            if result.finished_status == ActionStatus.SUCCEEDED:
                self._step_statuses[self._step_index] = StepStatus.SUCCEEDED
            else:
                self._step_statuses[self._step_index] = StepStatus.FAILED

            self._begin_from(vessel_state, self._step_index + 1)
            if self._queued_logs:
                result.logs.extend(self._queued_logs)
                self._queued_logs = []

        return result

    def stop(self) -> StepResult:
        """Stop the current action and cancel any remaining plan.

        Skips emitting PLAN_END if every step is already terminal
        (SUCCEEDED or FAILED), since step() already logged it on natural
        completion. This avoids duplicate PLAN_END entries when the user
        clicks Finish after a plan has already finished on its own.
        """
        plan_name = self._plan.name if self._plan is not None else None
        already_done = self._plan_ended or (
            self._plan is not None and all(s in (StepStatus.SUCCEEDED, StepStatus.FAILED) for s in self._step_statuses)
        )
        result = self._runner.stop()
        if plan_name is not None and not already_done:
            result.logs.append(LogEntry(level=LogLevel.PLAN_END, message=plan_name))
        self._clear_plan()
        return result

    def snapshot(self) -> PlanSnapshot:
        """Return a thread-safe snapshot of plan + runner state."""
        runner_snap = self._runner.snapshot()
        if self._plan is not None:
            return PlanSnapshot(
                plan_name=self._plan.name,
                current_step_index=self._step_index,
                total_steps=len(self._plan.steps),
                step_statuses=tuple(self._step_statuses),
                step_action_ids=tuple(self._step_action_id(step) for step in self._plan.steps),
                step_action_labels=tuple(self._step_label(index, step) for index, step in enumerate(self._plan.steps)),
                runner=runner_snap,
            )
        return PlanSnapshot(runner=runner_snap)

    def _step_action_id(self, step: FlightPlanStep | ParallelStep) -> str:
        """Discriminator for step_action_ids in snapshots."""
        if isinstance(step, ParallelStep):
            return PARALLEL_ACTION_ID
        return step.action_id

    def _step_label(self, index: int, step: FlightPlanStep | ParallelStep) -> str:
        """Display label for step_action_labels in snapshots."""
        if isinstance(step, ParallelStep):
            return f"→ {step.plan_name}"
        action = self._step_actions[index]
        return action.label if action is not None else step.action_id

    def _clear_plan(self) -> None:
        """Reset all plan state."""
        self._plan = None
        self._step_actions = []
        self._step_index = 0
        self._step_statuses = []
        self._spawn_parallel = None
        self._queued_logs = []
        self._plan_ended = False

    def _resolve_action(self, action_id: str) -> Action:
        """Get a fresh action instance by ID from the registry."""
        for action in get_available_actions():
            if action.action_id == action_id:
                return action
        raise ValueError(f"Unknown action: {action_id!r}")
