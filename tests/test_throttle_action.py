"""Tests for the ThrottleAction."""

from __future__ import annotations

import pytest

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionStatus,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.throttle.action import ThrottleAction


class TestThrottleLevel:
    """Tests for the existing throttle_level parameter."""

    def test_sets_throttle_to_specified_level(self) -> None:
        action = ThrottleAction()
        state = State(thrust_available=100.0)
        action.start(state, {"throttle_level": 0.5, "twr": None})
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED
        assert commands.throttle == 0.5

    def test_fails_when_no_thrust_available(self) -> None:
        action = ThrottleAction()
        state = State(thrust_available=0.0)
        action.start(state, {"throttle_level": 1.0, "twr": None})
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.FAILED


class TestTwr:
    """Tests for the twr parameter."""

    def test_computes_throttle_from_target_twr(self) -> None:
        """With max_twr=2.0, requesting twr=1.0 should set throttle to 0.5."""
        action = ThrottleAction()
        state = State(
            mass=1000.0,
            body_gravity=9.81,
            thrust_available=2.0 * 1000.0 * 9.81,  # max_twr = 2.0
        )
        action.start(state, {"throttle_level": None, "twr": 1.0})
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED
        assert commands.throttle is not None
        assert abs(commands.throttle - 0.5) < 0.01

    def test_clamps_throttle_to_max_1(self) -> None:
        """If target twr exceeds max_twr, throttle should clamp to 1.0."""
        action = ThrottleAction()
        state = State(
            mass=1000.0,
            body_gravity=9.81,
            thrust_available=1.0 * 1000.0 * 9.81,  # max_twr = 1.0
        )
        action.start(state, {"throttle_level": None, "twr": 2.0})
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED
        assert commands.throttle == 1.0

    def test_clamps_throttle_to_min_0(self) -> None:
        """Target twr=0 should set throttle to 0.0."""
        action = ThrottleAction()
        state = State(
            mass=1000.0,
            body_gravity=9.81,
            thrust_available=2.0 * 1000.0 * 9.81,
        )
        action.start(state, {"throttle_level": None, "twr": 0.0})
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED
        assert commands.throttle == 0.0

    def test_fails_when_no_thrust_available(self) -> None:
        action = ThrottleAction()
        state = State(thrust_available=0.0, mass=1000.0, body_gravity=9.81)
        action.start(state, {"throttle_level": None, "twr": 1.0})
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.FAILED

    def test_fails_when_zero_weight(self) -> None:
        """If vessel has no weight (e.g. zero mass), can't compute TWR."""
        action = ThrottleAction()
        state = State(thrust_available=100.0, mass=0.0, body_gravity=9.81)
        action.start(state, {"throttle_level": None, "twr": 1.0})
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.FAILED

    def test_raises_when_negative_twr(self) -> None:
        action = ThrottleAction()
        state = State(thrust_available=100.0)
        with pytest.raises(ValueError, match="non-negative"):
            action.start(state, {"throttle_level": None, "twr": -1.0})


class TestMutualExclusion:
    """Tests that twr and throttle_level cannot be used together."""

    def test_raises_when_both_twr_and_throttle_level_set(self) -> None:
        action = ThrottleAction()
        state = State(thrust_available=100.0)
        with pytest.raises(ValueError, match="mutually exclusive"):
            action.start(state, {"throttle_level": 0.5, "twr": 1.0})

    def test_raises_when_neither_twr_nor_throttle_level_set(self) -> None:
        action = ThrottleAction()
        state = State(thrust_available=100.0)
        with pytest.raises(ValueError, match="Either"):
            action.start(state, {"throttle_level": None, "twr": None})
