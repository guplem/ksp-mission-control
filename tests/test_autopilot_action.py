"""Tests for the AutopilotAction."""

from __future__ import annotations

import math

from ksp_mission_control.control.actions.autopilot.action import AutopilotAction
from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionStatus,
    State,
    VesselCommands,
)


class TestAutopilotAction:
    """Tests for engaging the autopilot and setting orientation."""

    def test_engages_autopilot_and_sets_pitch(self) -> None:
        action = AutopilotAction()
        state = State()
        action.start(state, {"pitch": "45.0"})
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED
        assert commands.autopilot is True
        assert commands.autopilot_pitch == 45.0

    def test_sets_pitch_and_heading(self) -> None:
        action = AutopilotAction()
        state = State()
        action.start(state, {"pitch": "90.0", "heading": "180.0"})
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED
        assert commands.autopilot_pitch == 90.0
        assert commands.autopilot_heading == 180.0

    def test_sets_pitch_heading_and_roll(self) -> None:
        action = AutopilotAction()
        state = State()
        action.start(state, {"pitch": "45.0", "heading": "90.0", "roll": "0.0"})
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED
        assert commands.autopilot_pitch == 45.0
        assert commands.autopilot_heading == 90.0
        assert commands.autopilot_roll == 0.0

    def test_heading_is_optional(self) -> None:
        action = AutopilotAction()
        state = State()
        action.start(state, {"pitch": "90.0", "heading": None})
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED
        assert commands.autopilot_heading is None

    def test_roll_omitted_sends_nan(self) -> None:
        action = AutopilotAction()
        state = State()
        action.start(state, {"pitch": "90.0"})
        commands = VesselCommands()
        action.tick(state, commands, 0.5, ActionLogger())
        assert commands.autopilot_roll is not None and math.isnan(commands.autopilot_roll)

    def test_message_contains_pitch(self) -> None:
        action = AutopilotAction()
        state = State()
        action.start(state, {"pitch": "45.0"})
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert "pitch=45.0" in result.message

    def test_message_contains_heading_when_set(self) -> None:
        action = AutopilotAction()
        state = State()
        action.start(state, {"pitch": "45.0", "heading": "90.0"})
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert "heading=90.0" in result.message

    def test_message_contains_roll_when_set(self) -> None:
        action = AutopilotAction()
        state = State()
        action.start(state, {"pitch": "0.0", "heading": "0.0", "roll": "30.0"})
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert "roll=30.0" in result.message
