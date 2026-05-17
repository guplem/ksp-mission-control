"""Tests for the AutopilotConfigAction."""

from __future__ import annotations

import pytest

from ksp_mission_control.control.actions.autopilot_config.action import (
    AutopilotConfigAction,
)
from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionStatus,
    AutopilotConfig,
    State,
    VesselCommands,
)


def _all_none() -> dict[str, None | bool]:
    """Param dict with every optional field omitted (runner fills None/default)."""
    return {
        "time_to_peak": None,
        "overshoot": None,
        "stopping_time": None,
        "deceleration_time": None,
        "attenuation_angle": None,
        "restore_defaults": False,
    }


class TestAutopilotConfigAction:
    """Tests for tuning the autopilot PID configuration."""

    def test_no_params_resets_to_krpc_defaults(self) -> None:
        action = AutopilotConfigAction()
        state = State()
        action.start(state, _all_none())
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED
        assert commands.autopilot_config == AutopilotConfig()

    def test_scalar_time_to_peak_is_replicated_to_all_axes(self) -> None:
        action = AutopilotConfigAction()
        state = State()
        params = _all_none() | {"time_to_peak": 6.0}
        action.start(state, params)
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED
        assert commands.autopilot_config is not None
        assert commands.autopilot_config.time_to_peak == (6.0, 6.0, 6.0)
        # Unspecified fields keep kRPC defaults.
        assert commands.autopilot_config.overshoot == (0.01, 0.01, 0.01)
        assert commands.autopilot_config.stopping_time == (0.5, 0.5, 0.5)

    def test_all_scalar_fields_replicated(self) -> None:
        action = AutopilotConfigAction()
        state = State()
        action.start(
            state,
            {
                "time_to_peak": 6.0,
                "overshoot": 0.02,
                "stopping_time": 1.0,
                "deceleration_time": 8.0,
                "attenuation_angle": 5.0,
            },
        )
        commands = VesselCommands()
        action.tick(state, commands, 0.5, ActionLogger())
        cfg = commands.autopilot_config
        assert cfg is not None
        assert cfg.time_to_peak == (6.0, 6.0, 6.0)
        assert cfg.overshoot == (0.02, 0.02, 0.02)
        assert cfg.stopping_time == (1.0, 1.0, 1.0)
        assert cfg.deceleration_time == (8.0, 8.0, 8.0)
        assert cfg.attenuation_angle == (5.0, 5.0, 5.0)

    def test_message_lists_set_fields_only(self) -> None:
        action = AutopilotConfigAction()
        state = State()
        params = _all_none() | {"time_to_peak": 6.0, "stopping_time": 1.0}
        action.start(state, params)
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert "time_to_peak=6.0" in result.message
        assert "stopping_time=1.0" in result.message
        assert "overshoot" not in result.message
        assert "deceleration_time" not in result.message

    def test_message_when_reset_to_defaults(self) -> None:
        action = AutopilotConfigAction()
        state = State()
        action.start(state, _all_none())
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert "default" in result.message.lower()

    def test_zero_is_rejected(self) -> None:
        action = AutopilotConfigAction()
        state = State()
        params = _all_none() | {"time_to_peak": 0.0}
        with pytest.raises(ValueError, match="time_to_peak"):
            action.start(state, params)

    def test_negative_is_rejected(self) -> None:
        action = AutopilotConfigAction()
        state = State()
        params = _all_none() | {"stopping_time": -1.0}
        with pytest.raises(ValueError, match="stopping_time"):
            action.start(state, params)

    def test_stop_does_not_mutate_commands(self) -> None:
        action = AutopilotConfigAction()
        state = State()
        params = _all_none() | {"time_to_peak": 6.0}
        action.start(state, params)
        commands = VesselCommands()
        action.stop(state, commands, ActionLogger())
        assert commands.autopilot_config is None

    def test_restore_defaults_writes_default_config(self) -> None:
        action = AutopilotConfigAction()
        state = State()
        action.start(state, _all_none() | {"restore_defaults": True})
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED
        assert commands.autopilot_config == AutopilotConfig()
        assert result.message == "Restored autopilot tuning to kRPC defaults"

    def test_restore_defaults_rejects_other_tuning_params(self) -> None:
        action = AutopilotConfigAction()
        state = State()
        params = _all_none() | {"restore_defaults": True, "time_to_peak": 6.0}
        with pytest.raises(ValueError, match="restore_defaults"):
            action.start(state, params)
