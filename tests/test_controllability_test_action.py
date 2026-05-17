"""Tests for ControllabilityTestAction."""

from __future__ import annotations

import pytest

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    PartInfo,
    Parts,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.controllability_test.action import ControllabilityTestAction
from ksp_mission_control.control.actions.helpers.staging import StagingMode


def _state(*, thrust_available: float = 0.0, engine_states: tuple[str, ...] = ()) -> State:
    """A minimal state with orientation zeros and configurable engine roster."""
    return State(
        orientation_pitch=89.0,
        orientation_heading=90.0,
        orientation_roll=0.0,
        thrust_available=thrust_available,
        thrust_peak=0.0,
        mass=5_000.0,
        stage_current=3,
        parts=Parts(engines=tuple(PartInfo(stage=0, state=s) for s in engine_states)),
    )


def _default_params(**overrides: object) -> dict[str, object]:
    params: dict[str, object] = {
        "roll_offset": 45.0,
        "pitch_offset": 15.0,
        "heading_offset": 30.0,
        "hold_duration": 3.0,
        "tolerance": 5.0,
        "staging_mode": "any_flameout",
    }
    params.update(overrides)
    return params


class TestControllabilityTestMetadata:
    def test_action_id(self) -> None:
        assert ControllabilityTestAction.action_id == "controllability_test"

    def test_has_staging_mode_param(self) -> None:
        assert any(p.param_id == "staging_mode" for p in ControllabilityTestAction.params)


class TestControllabilityTestStart:
    def test_records_staging_mode(self) -> None:
        action = ControllabilityTestAction()
        action.start(_state(), _default_params())
        assert action._staging_mode is StagingMode.ANY_FLAMEOUT

    def test_staging_mode_off_disables(self) -> None:
        action = ControllabilityTestAction()
        action.start(_state(), _default_params(staging_mode="off"))
        assert action._staging_mode is None


class TestControllabilityTestStagingOnLaunchpad:
    """First tick on the pad ignites via auto_stage when mode is on."""

    def test_first_tick_stages_with_default_mode(self) -> None:
        action = ControllabilityTestAction()
        action.start(_state(engine_states=("inactive",)), _default_params())
        commands = VesselCommands()
        action.tick(_state(engine_states=("inactive",)), commands, 0.5, ActionLogger())
        assert commands.stage is True
        # Autopilot must be engaged every tick, not only on the staging tick.
        assert commands.autopilot is True

    def test_first_tick_does_not_stage_when_off(self) -> None:
        action = ControllabilityTestAction()
        action.start(_state(engine_states=("inactive",)), _default_params(staging_mode="off"))
        commands = VesselCommands()
        action.tick(_state(engine_states=("inactive",)), commands, 0.5, ActionLogger())
        assert commands.stage is None
        # Autopilot still engages regardless of staging.
        assert commands.autopilot is True


class TestControllabilityTestStop:
    def test_stop_clears_throttle_and_autopilot(self) -> None:
        action = ControllabilityTestAction()
        action.start(_state(), _default_params(staging_mode="off"))
        commands = VesselCommands()
        action.stop(_state(), commands, ActionLogger())
        assert commands.throttle == 0.0
        assert commands.autopilot is False


class TestControllabilityTestStagingValidation:
    def test_rejects_unknown_staging_mode(self) -> None:
        action = ControllabilityTestAction()
        with pytest.raises(ValueError, match="Unknown staging_mode"):
            action.start(_state(), _default_params(staging_mode="bogus"))
