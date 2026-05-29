"""Tests for the warp helpers.

The helpers centralize warp policy across actions (ADR 0012):

- ``restore_user_warp``: called by the ActionRunner after every
  ``action.stop()`` to bring KSP back to ``state.user_target_warp_rate``.
  Writes only when the rates differ.
- ``drop_warp_for_critical_section``: called at the top of ``tick()`` by
  actions whose feedback loop requires 1x. Returns an ActionResult the
  caller surfaces immediately, or ``None`` if warp is already at or below
  1x and the caller can proceed.
"""

from __future__ import annotations

from ksp_mission_control.control.actions.base import (
    ActionStatus,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.helpers.warp import (
    drop_warp_for_critical_section,
    restore_user_warp,
)


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


class TestDropWarpForCriticalSection:
    """Top-of-tick guard that drops warp before a 1x-only critical section."""

    def test_drops_warp_and_returns_running_when_above_one(self) -> None:
        state = State(time_warp_rate=100.0)
        commands = VesselCommands()
        result = drop_warp_for_critical_section(state, commands, "hovering")
        assert result is not None
        assert result.status == ActionStatus.RUNNING
        # Helper wrote the 1x command for the caller.
        assert commands.time_warp_rate == 1.0
        # Message contains the original rate and the dropping_for label so
        # the user understands what is about to run at 1x.
        assert "100" in result.message
        assert "hovering" in result.message

    def test_returns_none_when_already_at_one(self) -> None:
        # Stable: no command issued, caller can proceed.
        state = State(time_warp_rate=1.0)
        commands = VesselCommands()
        assert drop_warp_for_critical_section(state, commands, "hovering") is None
        assert commands.time_warp_rate is None

    def test_returns_none_when_in_physics_warp(self) -> None:
        # Physics warp (1, 2, 3, 4) does not pause physics, so the
        # critical section is fine to run. Helper short-circuits anything
        # at or below 1x.
        state = State(time_warp_rate=1.0)
        commands = VesselCommands()
        assert drop_warp_for_critical_section(state, commands, "translating") is None

    def test_does_not_modify_other_command_fields(self) -> None:
        # Helper writes time_warp_rate only; everything else is the
        # action's responsibility.
        state = State(time_warp_rate=50.0)
        commands = VesselCommands()
        drop_warp_for_critical_section(state, commands, "descent")
        assert commands.throttle is None
        assert commands.autopilot is None
        assert commands.sas is None
