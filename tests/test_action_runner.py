"""Tests for the ActionRunner step-based executor."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from ksp_mission_control.control.actions.base import (
    Action,
    ActionLogger,
    ActionParam,
    ActionResult,
    ActionStatus,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.runner import ActionRunner


class StubAction(Action):
    """Minimal action for testing the runner."""

    action_id: ClassVar[str] = "stub"
    label: ClassVar[str] = "Stub"
    description: ClassVar[str] = "A stub action for testing"
    params: ClassVar[list[ActionParam]] = [
        ActionParam("speed", "Speed", "Target speed", required=False, default=10.0, unit="m/s"),
    ]

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.tick_count = 0
        self._return_status = ActionStatus.RUNNING

    def set_return_status(self, status: ActionStatus) -> None:
        self._return_status = status

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        self.started = True
        self._param_values = param_values

    def tick(self, state: State, controls: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        self.tick_count += 1
        controls.throttle = 0.7
        controls.sas = True
        return ActionResult(status=self._return_status)

    def stop(self, state: State, controls: VesselCommands, log: ActionLogger) -> None:
        self.stopped = True
        super().stop(state, controls, log)


class RequiredParamAction(Action):
    """Action with a required parameter for testing validation."""

    action_id: ClassVar[str] = "required-param"
    label: ClassVar[str] = "Required Param"
    description: ClassVar[str] = "Has a required param"
    params: ClassVar[list[ActionParam]] = [
        ActionParam("altitude", "Altitude", "Target altitude", required=True, unit="m"),
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        pass

    def tick(self, state: State, controls: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        return ActionResult(status=ActionStatus.RUNNING)

    def stop(self, state: State, controls: VesselCommands, log: ActionLogger) -> None:
        pass


class WarpHoldingStubAction(StubAction):
    """Stub whose tick() forces 1x warp, to verify the action overrides the
    runner's start-of-action warp reassert (a burn or orientation wait must win)."""

    def tick(self, state: State, controls: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        result = super().tick(state, controls, dt, log)
        controls.time_warp_rate = 1.0
        return result


class TestActionRunnerNoAction:
    """Tests for the runner with no active action."""

    def test_step_returns_empty_controls(self) -> None:
        runner = ActionRunner()
        result = runner.step(State(), dt=0.5)
        assert result.commands.throttle is None
        assert result.commands.sas is None
        assert result.commands.autopilot_pitch is None

    def test_snapshot_shows_no_action(self) -> None:
        runner = ActionRunner()
        snap = runner.snapshot()
        assert snap.action_id is None
        assert snap.action_label is None
        assert snap.status is None
        assert snap.message == ""


class TestActionRunnerStartAndStep:
    """Tests for starting an action and stepping."""

    def test_start_action_with_defaults(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        runner.start_action(action, State())
        assert action.started

    def test_step_calls_tick_and_returns_controls(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        runner.start_action(action, State())
        result = runner.step(State(), dt=0.5)
        assert action.tick_count == 1
        assert result.commands.throttle == 0.7
        assert result.commands.sas is True

    def test_step_increments_tick_count(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        runner.start_action(action, State())
        runner.step(State(), dt=0.5)
        runner.step(State(), dt=0.5)
        runner.step(State(), dt=0.5)
        assert action.tick_count == 3

    def test_snapshot_reflects_running_state(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        runner.start_action(action, State())
        runner.step(State(), dt=0.5)
        snap = runner.snapshot()
        assert snap.action_id == "stub"
        assert snap.action_label == "Stub"
        assert snap.status == ActionStatus.RUNNING

    def test_start_with_explicit_params(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        runner.start_action(action, State(), param_values={"speed": 20.0})
        assert action._param_values == {"speed": 20.0}  # noqa: SLF001

    def test_start_with_no_params_uses_defaults(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        runner.start_action(action, State())
        assert action._param_values == {"speed": 10.0}  # noqa: SLF001


class TestActionRunnerStop:
    """Tests for stopping a running action."""

    def test_stop_calls_action_stop(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        runner.start_action(action, State())
        runner.step(State(), dt=0.5)
        result = runner.stop()
        assert action.stopped
        # Base Action.stop() only logs; no command resets
        assert result.commands.throttle is None

    def test_stop_clears_state(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        runner.start_action(action, State())
        runner.step(State(), dt=0.5)
        runner.stop()
        # Subsequent step returns empty controls
        result = runner.step(State(), dt=0.5)
        assert result.commands.throttle is None

    def test_snapshot_after_stop_shows_no_action(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        runner.start_action(action, State())
        runner.stop()
        snap = runner.snapshot()
        assert snap.action_id is None
        assert snap.status is None

    def test_stop_with_no_action_returns_empty_controls(self) -> None:
        runner = ActionRunner()
        result = runner.stop()
        assert result.commands.throttle is None


class TestActionRunnerAutoStop:
    """Tests for automatic stop when action completes."""

    def test_succeeded_action_auto_stops(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        action.set_return_status(ActionStatus.SUCCEEDED)
        runner.start_action(action, State())
        result = runner.step(State(), dt=0.5)
        assert action.stopped
        # tick() set throttle=0.7; stop() doesn't reset it
        assert result.commands.throttle == 0.7

    def test_failed_action_auto_stops(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        action.set_return_status(ActionStatus.FAILED)
        runner.start_action(action, State())
        runner.step(State(), dt=0.5)
        assert action.stopped

    def test_snapshot_after_auto_stop_shows_no_action(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        action.set_return_status(ActionStatus.SUCCEEDED)
        runner.start_action(action, State())
        runner.step(State(), dt=0.5)
        snap = runner.snapshot()
        assert snap.action_id is None
        assert snap.status is None


class TestActionRunnerWarpRestore:
    """The runner restores ``state.user_target_warp_rate`` after every
    ``action.stop()`` (ADR 0012). Per-action stop bodies no longer do it."""

    def test_external_stop_restores_user_target_warp_rate(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        # last_state captured during step() is what runner.stop() reads for
        # the restore, so seed user_target_warp_rate there.
        runner.start_action(action, State(time_warp_rate=1.0, user_target_warp_rate=100.0))
        runner.step(State(time_warp_rate=1.0, user_target_warp_rate=100.0), dt=0.5)
        result = runner.stop()
        assert result.commands.time_warp_rate == 100.0

    def test_succeeded_auto_stop_restores_warp(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        action.set_return_status(ActionStatus.SUCCEEDED)
        runner.start_action(action, State(time_warp_rate=1.0, user_target_warp_rate=50.0))
        result = runner.step(State(time_warp_rate=1.0, user_target_warp_rate=50.0), dt=0.5)
        assert action.stopped
        assert result.commands.time_warp_rate == 50.0

    def test_failed_auto_stop_restores_warp(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        action.set_return_status(ActionStatus.FAILED)
        runner.start_action(action, State(time_warp_rate=1.0, user_target_warp_rate=10.0))
        result = runner.step(State(time_warp_rate=1.0, user_target_warp_rate=10.0), dt=0.5)
        assert result.commands.time_warp_rate == 10.0

    def test_no_warp_write_when_rates_already_match(self) -> None:
        # Both KSP and user target at the same rate: the helper inside the
        # runner skips the write, so no redundant command goes out.
        runner = ActionRunner()
        action = StubAction()
        runner.start_action(action, State(time_warp_rate=1.0, user_target_warp_rate=1.0))
        result = runner.stop()
        assert result.commands.time_warp_rate is None


class TestActionRunnerParamValidation:
    """Tests for parameter validation on start."""

    def test_raises_on_missing_required_param(self) -> None:
        runner = ActionRunner()
        action = RequiredParamAction()
        with pytest.raises(ValueError, match="altitude"):
            runner.start_action(action, State())

    def test_required_param_provided_succeeds(self) -> None:
        runner = ActionRunner()
        action = RequiredParamAction()
        runner.start_action(action, State(), param_values={"altitude": 500.0})
        # Should not raise
        snap = runner.snapshot()
        assert snap.action_id == "required-param"


class TestActionRunnerWarpReassertOnStart:
    """The runner reasserts ``user_target_warp_rate`` on each action's first
    tick (ADR 0012), so warp left clamped by KSP's post-burn lockout on the
    previous action's stop() recovers as soon as the next action begins."""

    def test_first_tick_reasserts_user_target_warp(self) -> None:
        runner = ActionRunner()
        action = StubAction()  # tick() does not touch warp
        runner.start_action(action, State(time_warp_rate=1.0, user_target_warp_rate=100.0))
        result = runner.step(State(time_warp_rate=1.0, user_target_warp_rate=100.0), dt=0.5)
        assert result.commands.time_warp_rate == 100.0

    def test_reassert_skipped_when_rates_already_match(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        runner.start_action(action, State(time_warp_rate=1.0, user_target_warp_rate=1.0))
        result = runner.step(State(time_warp_rate=1.0, user_target_warp_rate=1.0), dt=0.5)
        assert result.commands.time_warp_rate is None

    def test_reassert_only_on_first_tick(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        runner.start_action(action, State(time_warp_rate=1.0, user_target_warp_rate=100.0))
        runner.step(State(time_warp_rate=1.0, user_target_warp_rate=100.0), dt=0.5)
        # Second tick is not the first, so the runner does not reassert; StubAction
        # never touches warp, so nothing is commanded.
        result = runner.step(State(time_warp_rate=1.0, user_target_warp_rate=100.0), dt=0.5)
        assert result.commands.time_warp_rate is None

    def test_action_tick_overrides_reassert(self) -> None:
        runner = ActionRunner()
        action = WarpHoldingStubAction()
        runner.start_action(action, State(time_warp_rate=50.0, user_target_warp_rate=100.0))
        result = runner.step(State(time_warp_rate=50.0, user_target_warp_rate=100.0), dt=0.5)
        # Runner reasserts 100x first, then tick() forces 1x; the action wins.
        assert result.commands.time_warp_rate == 1.0
