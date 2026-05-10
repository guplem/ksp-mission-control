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
from ksp_mission_control.control.actions.sas.action import (
    _MODE_VERIFY_TIMEOUT_TICKS,
    SasAction,
)


class TestSasAction:
    """Tests for setting SAS mode."""

    def test_sends_sas_enable_on_first_tick(self) -> None:
        """First tick: SAS not yet on in state, so only the enable is sent."""
        action = SasAction()
        action.start(State(), {"mode": "prograde"})
        commands = VesselCommands()
        result = action.tick(State(control_sas=False), commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert commands.sas is True
        # Mode is held back until SAS is confirmed on, to avoid the same-frame race.
        assert commands.sas_mode is None

    def test_sends_mode_once_sas_is_on(self) -> None:
        """Once state reports SAS on, the mode is sent."""
        action = SasAction()
        action.start(State(), {"mode": "prograde"})
        commands = VesselCommands()
        result = action.tick(
            State(control_sas=True, control_sas_mode=SASMode.STABILITY_ASSIST),
            commands,
            0.5,
            ActionLogger(),
        )
        assert result.status == ActionStatus.RUNNING
        assert commands.sas is True
        assert commands.sas_mode == SASMode.PROGRADE

    def test_succeeds_when_state_confirms_mode(self) -> None:
        """Success requires both SAS on and the mode reflected in state."""
        action = SasAction()
        action.start(State(), {"mode": "prograde"})
        commands = VesselCommands()
        result = action.tick(
            State(control_sas=True, control_sas_mode=SASMode.PROGRADE),
            commands,
            0.5,
            ActionLogger(),
        )
        assert result.status == ActionStatus.SUCCEEDED
        assert "Prograde" in result.message

    def test_succeeds_after_race_resolves(self) -> None:
        """Tick 1: SAS off (sends enable). Tick 2: SAS on, wrong mode (sends mode). Tick 3: state matches (success)."""
        action = SasAction()
        action.start(State(), {"mode": "prograde"})

        # Tick 1: state shows SAS off → only enable is queued, action keeps running.
        cmd1 = VesselCommands()
        r1 = action.tick(State(control_sas=False), cmd1, 0.5, ActionLogger())
        assert r1.status == ActionStatus.RUNNING
        assert cmd1.sas is True
        assert cmd1.sas_mode is None

        # Tick 2: state now shows SAS on but still in stability_assist → mode is queued.
        cmd2 = VesselCommands()
        r2 = action.tick(
            State(control_sas=True, control_sas_mode=SASMode.STABILITY_ASSIST),
            cmd2,
            0.5,
            ActionLogger(),
        )
        assert r2.status == ActionStatus.RUNNING
        assert cmd2.sas_mode == SASMode.PROGRADE

        # Tick 3: KSP has accepted the mode → success.
        cmd3 = VesselCommands()
        r3 = action.tick(
            State(control_sas=True, control_sas_mode=SASMode.PROGRADE),
            cmd3,
            0.5,
            ActionLogger(),
        )
        assert r3.status == ActionStatus.SUCCEEDED

    def test_fails_when_mode_never_takes_effect(self) -> None:
        """If state never reflects the mode after the verify window, the action fails with a clear hint."""
        action = SasAction()
        action.start(State(), {"mode": "prograde"})
        unchanged_state = State(control_sas=True, control_sas_mode=SASMode.STABILITY_ASSIST)

        for _ in range(_MODE_VERIFY_TIMEOUT_TICKS - 1):
            result = action.tick(unchanged_state, VesselCommands(), 0.5, ActionLogger())
            assert result.status == ActionStatus.RUNNING

        final = action.tick(unchanged_state, VesselCommands(), 0.5, ActionLogger())
        assert final.status == ActionStatus.FAILED
        assert "Prograde" in final.message
        assert "pilot" in final.message.lower() or "probe" in final.message.lower()

    def test_sets_radial_mode(self) -> None:
        action = SasAction()
        action.start(State(), {"mode": "radial"})
        commands = VesselCommands()
        action.tick(State(control_sas=True), commands, 0.5, ActionLogger())
        assert commands.sas_mode == SASMode.RADIAL

    def test_stability_assist_succeeds_on_first_tick_when_sas_on(self) -> None:
        """stability_assist is the default mode reported when SAS is freshly enabled, so it can succeed immediately."""
        action = SasAction()
        action.start(State(), {"mode": "stability_assist"})
        commands = VesselCommands()
        result = action.tick(
            State(control_sas=True, control_sas_mode=SASMode.STABILITY_ASSIST),
            commands,
            0.5,
            ActionLogger(),
        )
        assert result.status == ActionStatus.SUCCEEDED

    def test_raises_on_invalid_mode(self) -> None:
        action = SasAction()
        with pytest.raises(ValueError, match="Unknown SAS mode"):
            action.start(State(), {"mode": "invalid_mode"})

    def test_message_contains_mode_name(self) -> None:
        action = SasAction()
        action.start(State(), {"mode": "retrograde"})
        commands = VesselCommands()
        result = action.tick(
            State(control_sas=True, control_sas_mode=SASMode.RETROGRADE),
            commands,
            0.5,
            ActionLogger(),
        )
        assert "Retrograde" in result.message
