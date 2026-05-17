"""Tests for HoldAttitudeAction."""

from __future__ import annotations

import pytest

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionStatus,
    PartInfo,
    Parts,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.helpers.staging import StagingMode
from ksp_mission_control.control.actions.hold_attitude.action import HoldAttitudeAction


def _state(*, thrust_available: float = 0.0, engine_states: tuple[str, ...] = ()) -> State:
    """A minimal state with orientation zeros and configurable engine roster."""
    return State(
        orientation_pitch=80.0,
        orientation_heading=90.0,
        orientation_roll=0.0,
        thrust_available=thrust_available,
        stage_current=3,
        parts=Parts(engines=tuple(PartInfo(stage=0, state=s) for s in engine_states)),
    )


class TestHoldAttitudeMetadata:
    def test_action_id(self) -> None:
        assert HoldAttitudeAction.action_id == "hold_attitude"

    def test_has_staging_mode_param(self) -> None:
        assert any(p.param_id == "staging_mode" for p in HoldAttitudeAction.params)


class TestHoldAttitudeStart:
    def test_captures_initial_orientation(self) -> None:
        action = HoldAttitudeAction()
        action.start(_state(), {"hold_ticks": 10, "staging_mode": "any_flameout"})
        assert action._target_pitch == 80.0
        assert action._target_heading == 90.0
        assert action._target_roll == 0.0
        assert action._staging_mode is StagingMode.ANY_FLAMEOUT

    def test_staging_mode_off_disables(self) -> None:
        action = HoldAttitudeAction()
        action.start(_state(), {"hold_ticks": 10, "staging_mode": "off"})
        assert action._staging_mode is None


class TestHoldAttitudeStagingOnLaunchpad:
    """First tick on the pad with thrust=0 and an inactive engine ignites via auto_stage."""

    def test_first_tick_stages_with_default_mode(self) -> None:
        action = HoldAttitudeAction()
        action.start(_state(engine_states=("inactive",)), {"hold_ticks": 10, "staging_mode": "any_flameout"})
        commands = VesselCommands()
        action.tick(_state(engine_states=("inactive",)), commands, 0.5, ActionLogger())
        assert commands.stage is True

    def test_first_tick_does_not_stage_when_off(self) -> None:
        action = HoldAttitudeAction()
        action.start(_state(engine_states=("inactive",)), {"hold_ticks": 10, "staging_mode": "off"})
        commands = VesselCommands()
        action.tick(_state(engine_states=("inactive",)), commands, 0.5, ActionLogger())
        assert commands.stage is None


class TestHoldAttitudeStagingMidFlight:
    """auto_stage runs every tick, so flameouts mid-hold also stage."""

    def test_mid_hold_flameout_stages(self) -> None:
        action = HoldAttitudeAction()
        action.start(_state(thrust_available=80_000.0), {"hold_ticks": 10, "staging_mode": "any_flameout"})
        # First tick: engines active, no staging.
        commands = VesselCommands()
        action.tick(_state(thrust_available=80_000.0, engine_states=("active",)), commands, 0.5, ActionLogger())
        assert commands.stage is None

        # Later tick: one engine flames out, inner stack still thrusting.
        commands = VesselCommands()
        action.tick(
            _state(thrust_available=40_000.0, engine_states=("active", "flameout")),
            commands,
            0.5,
            ActionLogger(),
        )
        assert commands.stage is True


class TestHoldAttitudeCompletion:
    def test_succeeds_after_hold_ticks(self) -> None:
        action = HoldAttitudeAction()
        action.start(_state(), {"hold_ticks": 2, "staging_mode": "off"})
        action.tick(_state(), VesselCommands(), 0.5, ActionLogger())
        result = action.tick(_state(), VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED


class TestHoldAttitudeStop:
    def test_stop_clears_throttle_and_autopilot(self) -> None:
        action = HoldAttitudeAction()
        action.start(_state(), {"hold_ticks": 10, "staging_mode": "off"})
        commands = VesselCommands()
        action.stop(_state(), commands, ActionLogger())
        assert commands.throttle == 0.0
        assert commands.autopilot is False


class TestHoldAttitudeStagingValidation:
    def test_rejects_unknown_staging_mode(self) -> None:
        action = HoldAttitudeAction()
        with pytest.raises(ValueError, match="Unknown staging_mode"):
            action.start(_state(), {"hold_ticks": 10, "staging_mode": "bogus"})
