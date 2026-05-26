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

    def test_target_multiplier_is_required(self) -> None:
        param = next(p for p in TimeWarpAction.params if p.param_id == "target_multiplier")
        assert param.required is True


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


class TestTimeWarpTick:
    def test_sets_command_and_succeeds_immediately(self) -> None:
        action = TimeWarpAction()
        action.start(State(time_warp_rate=1.0, time_warp_rate_max=100_000.0), {"target_multiplier": 1000.0})

        commands = VesselCommands()
        result = action.tick(State(time_warp_rate=1.0, time_warp_rate_max=100_000.0), commands, 0.5, ActionLogger())

        assert result.status == ActionStatus.SUCCEEDED
        assert commands.time_warp_rate == 1000.0

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


class TestTimeWarpStopIsNoOp:
    def test_stop_does_not_touch_commands(self) -> None:
        action = TimeWarpAction()
        action.start(State(), {"target_multiplier": 100.0})
        commands = VesselCommands()
        action.stop(State(), commands, ActionLogger())
        assert commands.time_warp_rate is None
        assert commands.throttle is None
