"""Tests for TimeWarpAction."""

from __future__ import annotations

import pytest

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionStatus,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.time_warp.action import TimeWarpAction


class TestTimeWarpMetadata:
    def test_action_id(self) -> None:
        assert TimeWarpAction.action_id == "time_warp"

    def test_target_multiplier_is_optional(self) -> None:
        # ``target_multiplier`` is optional: leaving it empty triggers the
        # re-send mode (resend ``state.user_target_warp_rate`` without
        # changing the user's intent).
        param = next(p for p in TimeWarpAction.params if p.param_id == "target_multiplier")
        assert param.required is False


class TestTimeWarpStartValidation:
    def test_rejects_multiplier_below_one(self) -> None:
        action = TimeWarpAction()
        with pytest.raises(ValueError, match="target_multiplier must be >= 1"):
            action.start(State(), {"target_multiplier": 0.5})

    def test_accepts_multiplier_at_one(self) -> None:
        action = TimeWarpAction()
        action.start(State(), {"target_multiplier": 1.0})
        assert action._target_multiplier == 1.0

    def test_accepts_large_multiplier(self) -> None:
        action = TimeWarpAction()
        action.start(State(), {"target_multiplier": 100_000.0})
        assert action._target_multiplier == 100_000.0

    def test_no_arg_stores_none(self) -> None:
        # Omitting the parameter altogether selects the re-send mode.
        action = TimeWarpAction()
        action.start(State(), {})
        assert action._target_multiplier is None

    def test_explicit_none_stores_none(self) -> None:
        # The plan parser passes ``None`` for an unset optional value;
        # this must also select the re-send mode (no float() crash).
        action = TimeWarpAction()
        action.start(State(), {"target_multiplier": None})
        assert action._target_multiplier is None


class TestTimeWarpTick:
    def test_sets_command_and_succeeds_immediately(self) -> None:
        action = TimeWarpAction()
        action.start(State(time_warp_rate=1.0, time_warp_rate_max=100_000.0), {"target_multiplier": 1000.0})

        commands = VesselCommands()
        result = action.tick(State(time_warp_rate=1.0, time_warp_rate_max=100_000.0), commands, 0.5, ActionLogger())

        assert result.status == ActionStatus.SUCCEEDED
        assert commands.time_warp_rate == 1000.0

    def test_also_updates_user_target_warp_rate(self) -> None:
        # The action sets both the KSP-side rate and the session-level user
        # target so burn-driven actions can read the user's intent later.
        action = TimeWarpAction()
        action.start(State(time_warp_rate=1.0, time_warp_rate_max=100_000.0), {"target_multiplier": 100.0})

        commands = VesselCommands()
        action.tick(State(time_warp_rate=1.0, time_warp_rate_max=100_000.0), commands, 0.5, ActionLogger())

        assert commands.user_target_warp_rate == 100.0

    def test_warns_when_request_exceeds_cap(self) -> None:
        action = TimeWarpAction()
        state = State(time_warp_rate=1.0, time_warp_rate_max=100.0)
        action.start(state, {"target_multiplier": 1000.0})

        commands = VesselCommands()
        log = ActionLogger()
        result = action.tick(state, commands, 0.5, log)

        assert result.status == ActionStatus.SUCCEEDED
        assert commands.time_warp_rate == 1000.0
        # Log carries a WARN entry about the cap so the user knows the bridge clamped.
        assert any("exceeds KSP" in entry.message for entry in log.entries)

    def test_target_one_drops_back_to_real_time(self) -> None:
        action = TimeWarpAction()
        action.start(State(time_warp_rate=100.0), {"target_multiplier": 1.0})

        commands = VesselCommands()
        action.tick(State(time_warp_rate=100.0), commands, 0.5, ActionLogger())
        assert commands.time_warp_rate == 1.0
        assert commands.user_target_warp_rate == 1.0


class TestTimeWarpResendMode:
    """Empty ``target_multiplier`` re-sends ``state.user_target_warp_rate``."""

    def test_no_arg_resends_current_user_target(self) -> None:
        # User clicked 100x earlier; KSP clamped it to 50x. A bare
        # ``time_warp`` step should re-issue 100x so the bridge tries again.
        action = TimeWarpAction()
        action.start(State(), {})

        state = State(time_warp_rate=50.0, time_warp_rate_max=100_000.0, user_target_warp_rate=100.0)
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())

        assert result.status == ActionStatus.SUCCEEDED
        assert commands.time_warp_rate == 100.0

    def test_no_arg_does_not_overwrite_user_target(self) -> None:
        # Re-send must not touch the session intent. Writing
        # ``user_target_warp_rate`` would let the action silently change
        # what other actions later read as the user's intent.
        action = TimeWarpAction()
        action.start(State(), {})

        state = State(time_warp_rate=50.0, user_target_warp_rate=100.0)
        commands = VesselCommands()
        action.tick(state, commands, 0.5, ActionLogger())

        assert commands.user_target_warp_rate is None

    def test_no_arg_with_one_x_user_target_still_sends_one_x(self) -> None:
        # When the user's intent is already 1x, the re-send is effectively
        # a no-op for KSP, but the action still emits the command so it is
        # observable in logs and tick records.
        action = TimeWarpAction()
        action.start(State(), {})

        state = State(time_warp_rate=1.0, user_target_warp_rate=1.0)
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())

        assert result.status == ActionStatus.SUCCEEDED
        assert commands.time_warp_rate == 1.0
        assert commands.user_target_warp_rate is None


class TestTimeWarpStopIsNoOp:
    def test_stop_does_not_touch_commands(self) -> None:
        action = TimeWarpAction()
        action.start(State(), {"target_multiplier": 100.0})
        commands = VesselCommands()
        action.stop(State(), commands, ActionLogger())
        assert commands.time_warp_rate is None
        assert commands.throttle is None
