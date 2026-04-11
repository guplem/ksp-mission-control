"""Tests for ControlSession - poll loop and action orchestration."""

from __future__ import annotations

from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

from ksp_mission_control.control.actions.base import (
    Action,
    ActionParam,
    ActionResult,
    ActionStatus,
    VesselControls,
    VesselState,
)
from ksp_mission_control.control.actions.runner import RunnerSnapshot
from ksp_mission_control.control.session import ControlSession

# ---------------------------------------------------------------------------
# Stub action for testing
# ---------------------------------------------------------------------------


class StubAction(Action):
    """Minimal action that tracks lifecycle calls."""

    action_id: ClassVar[str] = "stub"
    label: ClassVar[str] = "Stub"
    description: ClassVar[str] = "A stub action for tests"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="speed",
            label="Speed",
            description="Target speed",
            required=False,
            default=10.0,
            unit="m/s",
        ),
    ]

    def __init__(self) -> None:
        self.started = False
        self.tick_count = 0

    def start(self, param_values: dict[str, Any]) -> None:
        self.started = True

    def tick(self, state: VesselState, controls: VesselControls, dt: float) -> ActionResult:
        self.tick_count += 1
        controls.throttle = 0.5
        return ActionResult(status=ActionStatus.RUNNING)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestControlSessionDemo:
    """Test ControlSession in demo mode (no kRPC, no threading)."""

    def test_demo_tick_calls_on_update(self) -> None:
        updates: list[tuple[VesselState, RunnerSnapshot]] = []
        session = ControlSession(
            demo=True,
            on_update=lambda s, r: updates.append((s, r)),
            on_error=lambda _: None,
        )

        session.demo_tick()

        assert len(updates) == 1
        state, snapshot = updates[0]
        assert isinstance(state, VesselState)
        assert isinstance(snapshot, RunnerSnapshot)

    def test_demo_tick_increments_met(self) -> None:
        states: list[VesselState] = []
        session = ControlSession(
            demo=True,
            on_update=lambda s, _: states.append(s),
            on_error=lambda _: None,
        )

        session.demo_tick()
        session.demo_tick()
        session.demo_tick()

        assert states[0].met < states[1].met < states[2].met

    def test_start_action_delegates_to_runner(self) -> None:
        session = ControlSession(
            demo=True,
            on_update=lambda *_: None,
            on_error=lambda _: None,
        )
        action = StubAction()

        session.start_action(action)
        session.demo_tick()

        snapshot = session.snapshot()
        assert snapshot.action_id == "stub"
        assert snapshot.status == ActionStatus.RUNNING
        assert action.tick_count == 1

    def test_abort_clears_running_action(self) -> None:
        session = ControlSession(
            demo=True,
            on_update=lambda *_: None,
            on_error=lambda _: None,
        )
        action = StubAction()
        session.start_action(action)

        session.abort()

        assert session.snapshot().action_id is None

    def test_abort_no_action_is_safe(self) -> None:
        session = ControlSession(
            demo=True,
            on_update=lambda *_: None,
            on_error=lambda _: None,
        )

        # Should not raise
        session.abort()
        assert session.snapshot().action_id is None

    def test_shutdown_sets_stop_event(self) -> None:
        session = ControlSession(
            demo=True,
            on_update=lambda *_: None,
            on_error=lambda _: None,
        )

        session.shutdown()

        assert session._stop_event.is_set()  # noqa: SLF001

    def test_shutdown_aborts_running_action(self) -> None:
        session = ControlSession(
            demo=True,
            on_update=lambda *_: None,
            on_error=lambda _: None,
        )
        session.start_action(StubAction())

        session.shutdown()

        assert session.snapshot().action_id is None

    def test_snapshot_delegates_to_runner(self) -> None:
        session = ControlSession(
            demo=True,
            on_update=lambda *_: None,
            on_error=lambda _: None,
        )

        # No action running
        snapshot = session.snapshot()
        assert snapshot.action_id is None
        assert snapshot.status is None


class TestControlSessionLive:
    """Test ControlSession live mode with mocked kRPC."""

    def test_poll_loop_calls_on_error_on_connection_failure(self) -> None:
        errors: list[str] = []
        session = ControlSession(
            demo=False,
            on_update=lambda *_: None,
            on_error=lambda msg: errors.append(msg),
            config_manager=MagicMock(),
        )

        # Mock krpc.connect to raise
        mock_krpc = MagicMock()
        mock_krpc.connect.side_effect = ConnectionRefusedError("refused")

        with (
            patch.dict("sys.modules", {"krpc": mock_krpc}),
            patch(
                "ksp_mission_control.control.session.resolve_krpc_connection",
                return_value=MagicMock(),
            ),
        ):
            session.run_poll_loop()

        assert len(errors) == 1
        assert "refused" in errors[0]
