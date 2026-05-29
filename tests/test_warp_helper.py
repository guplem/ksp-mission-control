"""Tests for the restore_user_warp helper.

The helper centralizes the "what should stop() write to restore warp?"
policy used by every action with a critical section (ADR 0012). The
contract is: write the user's intended rate to commands.time_warp_rate
if (and only if) KSP's live rate differs from it.
"""

from __future__ import annotations

from ksp_mission_control.control.actions.base import State, VesselCommands
from ksp_mission_control.control.actions.helpers.warp import restore_user_warp


class TestRestoresUpward:
    """Live KSP rate is below the user's target -> write the user's target."""

    def test_writes_user_target_when_ksp_at_one_x(self) -> None:
        # Canonical case: critical section dropped KSP to 1x, user's intent
        # is 100x. The helper must write 100x so KSP returns to user intent.
        state = State(time_warp_rate=1.0, user_target_warp_rate=100.0)
        commands = VesselCommands()
        restore_user_warp(state, commands)
        assert commands.time_warp_rate == 100.0

    def test_writes_user_target_when_ksp_clamped_to_intermediate(self) -> None:
        # KSP clamped to 50x (altitude cap) while user asked for 100x.
        # The helper still writes 100x so the bridge re-tries the request.
        state = State(time_warp_rate=50.0, user_target_warp_rate=100.0)
        commands = VesselCommands()
        restore_user_warp(state, commands)
        assert commands.time_warp_rate == 100.0


class TestRestoresDownward:
    """Live KSP rate is above the user's target -> write the user's target."""

    def test_writes_one_x_when_ksp_higher_than_user_target(self) -> None:
        # User dropped intent to 1x but KSP is still at 100x (e.g. a
        # previous action left it there). The helper writes 1x to bring
        # KSP back to user intent. This case was silently skipped by the
        # old ``> 1.0`` guard.
        state = State(time_warp_rate=100.0, user_target_warp_rate=1.0)
        commands = VesselCommands()
        restore_user_warp(state, commands)
        assert commands.time_warp_rate == 1.0


class TestSkipsOnEquality:
    """Live KSP rate already equals the user's target -> no write."""

    def test_no_write_when_rates_match_at_one_x(self) -> None:
        # Stable case: nothing to do. A no-op stop() must not produce a
        # spurious command so the command stream stays clean.
        state = State(time_warp_rate=1.0, user_target_warp_rate=1.0)
        commands = VesselCommands()
        restore_user_warp(state, commands)
        assert commands.time_warp_rate is None

    def test_no_write_when_rates_match_at_high_warp(self) -> None:
        # User wants 100x, KSP is already at 100x (e.g. execute_node's
        # burn-complete restore already landed). The action's stop()
        # safety-net call must not re-issue the same command.
        state = State(time_warp_rate=100.0, user_target_warp_rate=100.0)
        commands = VesselCommands()
        restore_user_warp(state, commands)
        assert commands.time_warp_rate is None


class TestDoesNotTouchOtherFields:
    """The helper writes time_warp_rate only; other command fields stay None."""

    def test_does_not_modify_other_command_fields(self) -> None:
        # Guard against accidental scope creep: the helper has one job.
        state = State(time_warp_rate=1.0, user_target_warp_rate=100.0)
        commands = VesselCommands()
        restore_user_warp(state, commands)
        assert commands.throttle is None
        assert commands.autopilot is None
        assert commands.user_target_warp_rate is None

    def test_preserves_existing_command_fields(self) -> None:
        # Helper is called inside stop() after the action has set its own
        # cleanup fields (throttle=0, autopilot=False). The helper must
        # not clobber those by resetting unrelated fields.
        state = State(time_warp_rate=1.0, user_target_warp_rate=100.0)
        commands = VesselCommands(throttle=0.0, autopilot=False)
        restore_user_warp(state, commands)
        assert commands.throttle == 0.0
        assert commands.autopilot is False
        assert commands.time_warp_rate == 100.0
