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
    VesselCommands,
    VesselState,
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

    def start(self, state: VesselState, param_values: dict[str, Any]) -> None:
        self.started = True
        self._param_values = param_values

    def tick(
        self, state: VesselState, controls: VesselCommands, dt: float, log: ActionLogger
    ) -> ActionResult:
        self.tick_count += 1
        controls.throttle = 0.7
        controls.sas = True
        return ActionResult(status=self._return_status)

    def stop(self, state: VesselState, controls: VesselCommands, log: ActionLogger) -> None:
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

    def start(self, state: VesselState, param_values: dict[str, Any]) -> None:
        pass

    def tick(
        self, state: VesselState, controls: VesselCommands, dt: float, log: ActionLogger
    ) -> ActionResult:
        return ActionResult(status=ActionStatus.RUNNING)


class TestActionRunnerNoAction:
    """Tests for the runner with no active action."""

    def test_step_returns_empty_controls(self) -> None:
        runner = ActionRunner()
        result = runner.step(VesselState(), dt=0.5)
        assert result.commands.throttle is None
        assert result.commands.sas is None
        assert result.commands.pitch is None

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
        runner.start_action(action, VesselState())
        assert action.started

    def test_step_calls_tick_and_returns_controls(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        runner.start_action(action, VesselState())
        result = runner.step(VesselState(), dt=0.5)
        assert action.tick_count == 1
        assert result.commands.throttle == 0.7
        assert result.commands.sas is True

    def test_step_increments_tick_count(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        runner.start_action(action, VesselState())
        runner.step(VesselState(), dt=0.5)
        runner.step(VesselState(), dt=0.5)
        runner.step(VesselState(), dt=0.5)
        assert action.tick_count == 3

    def test_snapshot_reflects_running_state(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        runner.start_action(action, VesselState())
        runner.step(VesselState(), dt=0.5)
        snap = runner.snapshot()
        assert snap.action_id == "stub"
        assert snap.action_label == "Stub"
        assert snap.status == ActionStatus.RUNNING

    def test_start_with_explicit_params(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        runner.start_action(action, VesselState(), param_values={"speed": 20.0})
        assert action._param_values == {"speed": 20.0}  # noqa: SLF001

    def test_start_with_no_params_uses_defaults(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        runner.start_action(action, VesselState())
        assert action._param_values == {"speed": 10.0}  # noqa: SLF001


class TestActionRunnerAbort:
    """Tests for aborting a running action."""

    def test_abort_calls_stop(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        runner.start_action(action, VesselState())
        runner.step(VesselState(), dt=0.5)
        result = runner.abort()
        assert action.stopped
        assert result.commands.throttle == 0.0  # from Action.stop() default

    def test_abort_clears_state(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        runner.start_action(action, VesselState())
        runner.step(VesselState(), dt=0.5)
        runner.abort()
        # Subsequent step returns empty controls
        result = runner.step(VesselState(), dt=0.5)
        assert result.commands.throttle is None

    def test_snapshot_after_abort_shows_no_action(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        runner.start_action(action, VesselState())
        runner.abort()
        snap = runner.snapshot()
        assert snap.action_id is None
        assert snap.status is None

    def test_abort_with_no_action_returns_empty_controls(self) -> None:
        runner = ActionRunner()
        result = runner.abort()
        assert result.commands.throttle is None


class TestActionRunnerAutoStop:
    """Tests for automatic stop when action completes."""

    def test_succeeded_action_auto_stops(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        action.set_return_status(ActionStatus.SUCCEEDED)
        runner.start_action(action, VesselState())
        result = runner.step(VesselState(), dt=0.5)
        assert action.stopped
        # Commands from stop() override tick's commands
        assert result.commands.throttle == 0.0

    def test_failed_action_auto_stops(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        action.set_return_status(ActionStatus.FAILED)
        runner.start_action(action, VesselState())
        runner.step(VesselState(), dt=0.5)
        assert action.stopped

    def test_snapshot_after_auto_stop_shows_no_action(self) -> None:
        runner = ActionRunner()
        action = StubAction()
        action.set_return_status(ActionStatus.SUCCEEDED)
        runner.start_action(action, VesselState())
        runner.step(VesselState(), dt=0.5)
        snap = runner.snapshot()
        assert snap.action_id is None
        assert snap.status is None


class TestActionRunnerParamValidation:
    """Tests for parameter validation on start."""

    def test_raises_on_missing_required_param(self) -> None:
        runner = ActionRunner()
        action = RequiredParamAction()
        with pytest.raises(ValueError, match="altitude"):
            runner.start_action(action, VesselState())

    def test_required_param_provided_succeeds(self) -> None:
        runner = ActionRunner()
        action = RequiredParamAction()
        runner.start_action(action, VesselState(), param_values={"altitude": 500.0})
        # Should not raise
        snap = runner.snapshot()
        assert snap.action_id == "required-param"
