"""Tests for ControlSession - poll loop and action orchestration."""

from __future__ import annotations

from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

from ksp_mission_control.control.actions.base import (
    Action,
    ActionLogger,
    ActionParam,
    ActionResult,
    ActionStatus,
    VesselCommands,
    VesselState,
)
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

    def start(self, state: VesselState, param_values: dict[str, Any]) -> None:
        self.started = True

    def tick(
        self, state: VesselState, controls: VesselCommands, dt: float, log: ActionLogger
    ) -> ActionResult:
        self.tick_count += 1
        controls.throttle = 0.5
        return ActionResult(status=ActionStatus.RUNNING)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _make_session(**overrides: object) -> ControlSession:
    """Create a ControlSession with sensible defaults for testing."""
    defaults: dict[str, object] = {
        "on_update": lambda *_unused: None,
        "on_error": lambda _: None,
        "config_manager": MagicMock(),
    }
    defaults.update(overrides)
    return ControlSession(**defaults)  # type: ignore[arg-type]


class TestControlSession:
    """Test ControlSession action orchestration (no kRPC, no threading)."""

    def test_start_action_delegates_to_runner(self) -> None:
        session = _make_session()
        action = StubAction()

        session.start_action(action)

        snapshot = session.snapshot()
        assert snapshot.action_id == "stub"
        assert snapshot.status == ActionStatus.RUNNING

    def test_abort_clears_running_action(self) -> None:
        session = _make_session()
        action = StubAction()
        session.start_action(action)

        session.abort()

        assert session.snapshot().action_id is None

    def test_abort_no_action_is_safe(self) -> None:
        session = _make_session()

        # Should not raise
        session.abort()
        assert session.snapshot().action_id is None

    def test_shutdown_sets_stop_event(self) -> None:
        session = _make_session()

        session.shutdown()

        assert session._stop_event.is_set()  # noqa: SLF001

    def test_shutdown_aborts_running_action(self) -> None:
        session = _make_session()
        session.start_action(StubAction())

        session.shutdown()

        assert session.snapshot().action_id is None

    def test_snapshot_delegates_to_runner(self) -> None:
        session = _make_session()

        # No action running
        snapshot = session.snapshot()
        assert snapshot.action_id is None
        assert snapshot.status is None


class TestControlSessionManualCommand:
    """Test send_manual_command queuing and merge."""

    def test_send_manual_command_queues_pending(self) -> None:
        session = _make_session()
        commands = VesselCommands(throttle=0.5)

        session.send_manual_command(commands)

        assert session._pending_manual_command is commands  # noqa: SLF001

    def test_send_manual_command_overwrites_previous_pending(self) -> None:
        session = _make_session()
        first = VesselCommands(throttle=0.1)
        second = VesselCommands(throttle=0.9)

        session.send_manual_command(first)
        session.send_manual_command(second)

        assert session._pending_manual_command is second  # noqa: SLF001


class TestMergeManualCommand:
    """Test _merge_manual_command helper."""

    def test_merge_overrides_non_none_fields(self) -> None:
        from ksp_mission_control.control.session import _merge_manual_command

        commands = VesselCommands(throttle=0.5, sas=True)
        manual = VesselCommands(throttle=0.9)

        overridden = _merge_manual_command(commands, manual)

        assert commands.throttle == 0.9  # overridden
        assert commands.sas is True  # untouched
        assert "throttle" in overridden
        assert "sas" not in overridden

    def test_merge_leaves_none_fields_alone(self) -> None:
        from ksp_mission_control.control.session import _merge_manual_command

        commands = VesselCommands(throttle=0.5)
        manual = VesselCommands()  # all None

        overridden = _merge_manual_command(commands, manual)

        assert commands.throttle == 0.5
        assert overridden == []

    def test_merge_adds_fields_not_set_by_action(self) -> None:
        from ksp_mission_control.control.session import _merge_manual_command

        commands = VesselCommands(throttle=0.5)
        manual = VesselCommands(gear=True, lights=True)

        overridden = _merge_manual_command(commands, manual)

        assert commands.throttle == 0.5
        assert commands.gear is True
        assert commands.lights is True
        assert set(overridden) == {"gear", "lights"}


class TestControlSessionLive:
    """Test ControlSession live mode with mocked kRPC."""

    def test_poll_loop_calls_on_error_on_connection_failure(self) -> None:
        errors: list[str] = []
        session = _make_session(
            on_error=lambda msg: (errors.append(msg), session.shutdown()),
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

        assert len(errors) >= 1
        assert "refused" in errors[0]
