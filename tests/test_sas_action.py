"""Tests for the SasAction."""

from __future__ import annotations

import pytest

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionStatus,
    SASMode,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.sas.action import SasAction


class TestSasAction:
    """Tests for setting SAS mode."""

    def test_enables_sas_and_sets_mode(self) -> None:
        action = SasAction()
        state = State()
        action.start(state, {"mode": "prograde"})
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED
        assert commands.sas is True
        assert commands.sas_mode == SASMode.PROGRADE

    def test_sets_radial_out_mode(self) -> None:
        action = SasAction()
        state = State()
        action.start(state, {"mode": "radial"})
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED
        assert commands.sas_mode == SASMode.RADIAL

    def test_sets_stability_assist_mode(self) -> None:
        action = SasAction()
        state = State()
        action.start(state, {"mode": "stability_assist"})
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert commands.sas_mode == SASMode.STABILITY_ASSIST

    def test_raises_on_invalid_mode(self) -> None:
        action = SasAction()
        state = State()
        with pytest.raises(ValueError, match="Unknown SAS mode"):
            action.start(state, {"mode": "invalid_mode"})

    def test_message_contains_mode_name(self) -> None:
        action = SasAction()
        state = State()
        action.start(state, {"mode": "retrograde"})
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert "Retrograde" in result.message
