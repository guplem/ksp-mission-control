"""Tests for the auto_stage helper that advances staging when engines run dry."""

from __future__ import annotations

import pytest

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    PartInfo,
    Parts,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.helpers.staging import (
    STAGING_MODE_PARAM,
    StagingMode,
    auto_stage,
    parse_staging_mode,
)


def _engines(*states: str) -> tuple[PartInfo, ...]:
    """Build a tuple of engine PartInfo with only ``state`` populated.

    Activation stage and decouple stage are irrelevant for auto_stage: it
    operates on aggregate counts (engines_flameout, engines_inactive) and
    on state.thrust_available, not on per-engine staging metadata.
    """
    return tuple(PartInfo(stage=0, state=s) for s in states)


def _state(
    *,
    stage_current: int = 3,
    thrust_available: float = 0.0,
    engines: tuple[PartInfo, ...] = (),
) -> State:
    return State(
        stage_current=stage_current,
        thrust_available=thrust_available,
        parts=Parts(engines=engines),
    )


class TestFullDepletionMode:
    """FULL_DEPLETION stages only when total thrust is zero AND inactive engines remain."""

    def test_stages_when_no_thrust_and_inactive_engines_available(self) -> None:
        state = _state(thrust_available=0.0, engines=_engines("flameout", "inactive"))
        commands = VesselCommands()
        staged = auto_stage(state, commands, StagingMode.FULL_DEPLETION, ActionLogger())
        assert staged is True
        assert commands.stage is True

    def test_does_not_stage_when_thrust_still_available(self) -> None:
        """Even with a flamed-out engine, FULL_DEPLETION holds back while thrust remains."""
        state = _state(thrust_available=50_000.0, engines=_engines("active", "flameout", "inactive"))
        commands = VesselCommands()
        staged = auto_stage(state, commands, StagingMode.FULL_DEPLETION, ActionLogger())
        assert staged is False
        assert commands.stage is None

    def test_does_not_stage_when_no_inactive_engines_to_ignite(self) -> None:
        """At zero thrust with nothing to light next, staging would be wasted."""
        state = _state(thrust_available=0.0, engines=_engines("flameout", "flameout"))
        commands = VesselCommands()
        staged = auto_stage(state, commands, StagingMode.FULL_DEPLETION, ActionLogger())
        assert staged is False
        assert commands.stage is None


class TestAnyFlameoutMode:
    """ANY_FLAMEOUT stages eagerly when at least one active engine has flamed out."""

    def test_stages_on_partial_flameout_while_inner_stack_still_thrusts(self) -> None:
        """Side booster flamed out, central engine still firing: drop the dead weight."""
        state = _state(thrust_available=80_000.0, engines=_engines("active", "flameout"))
        commands = VesselCommands()
        staged = auto_stage(state, commands, StagingMode.ANY_FLAMEOUT, ActionLogger())
        assert staged is True
        assert commands.stage is True

    def test_stages_when_full_depletion_with_inactive_engines(self) -> None:
        """ANY_FLAMEOUT subsumes FULL_DEPLETION: empty stack + inactive next is still a stage."""
        state = _state(thrust_available=0.0, engines=_engines("flameout", "inactive"))
        commands = VesselCommands()
        staged = auto_stage(state, commands, StagingMode.ANY_FLAMEOUT, ActionLogger())
        assert staged is True
        assert commands.stage is True

    def test_does_not_stage_when_flameout_but_no_thrust_and_no_inactive(self) -> None:
        """Staging would jettison the only remaining option (which is already dead). Bail."""
        state = _state(thrust_available=0.0, engines=_engines("flameout", "flameout"))
        commands = VesselCommands()
        staged = auto_stage(state, commands, StagingMode.ANY_FLAMEOUT, ActionLogger())
        assert staged is False
        assert commands.stage is None

    def test_does_not_stage_when_no_engines_flamed_out(self) -> None:
        """All engines healthy: nothing to drop."""
        state = _state(thrust_available=120_000.0, engines=_engines("active", "active"))
        commands = VesselCommands()
        staged = auto_stage(state, commands, StagingMode.ANY_FLAMEOUT, ActionLogger())
        assert staged is False
        assert commands.stage is None


class TestFinalStageGuard:
    """Both modes must refuse to stage once stage_current has reached 0."""

    def test_full_depletion_refuses_at_stage_zero(self) -> None:
        state = _state(stage_current=0, thrust_available=0.0, engines=_engines("flameout", "inactive"))
        commands = VesselCommands()
        staged = auto_stage(state, commands, StagingMode.FULL_DEPLETION, ActionLogger())
        assert staged is False
        assert commands.stage is None

    def test_any_flameout_refuses_at_stage_zero(self) -> None:
        state = _state(stage_current=0, thrust_available=80_000.0, engines=_engines("active", "flameout"))
        commands = VesselCommands()
        staged = auto_stage(state, commands, StagingMode.ANY_FLAMEOUT, ActionLogger())
        assert staged is False
        assert commands.stage is None


class TestLogging:
    """Helper emits an info log describing which trigger fired."""

    def test_full_depletion_log_mentions_full_depletion(self) -> None:
        state = _state(thrust_available=0.0, engines=_engines("flameout", "inactive"))
        log = ActionLogger()
        auto_stage(state, VesselCommands(), StagingMode.FULL_DEPLETION, log)
        assert any("full depletion" in entry.message.lower() for entry in log.entries)

    def test_any_flameout_log_mentions_flameout(self) -> None:
        state = _state(thrust_available=80_000.0, engines=_engines("active", "flameout"))
        log = ActionLogger()
        auto_stage(state, VesselCommands(), StagingMode.ANY_FLAMEOUT, log)
        assert any("flameout" in entry.message.lower() for entry in log.entries)


class TestStagingModeParamDefault:
    """``STAGING_MODE_PARAM`` defaults to ANY_FLAMEOUT so plans get auto-staging without opting in."""

    def test_param_default_is_any_flameout(self) -> None:
        assert STAGING_MODE_PARAM.default == StagingMode.ANY_FLAMEOUT.value

    def test_default_parses_back_to_any_flameout(self) -> None:
        """A plan omitting staging_mode resolves to the param default, which must parse cleanly."""
        assert parse_staging_mode(STAGING_MODE_PARAM.default) is StagingMode.ANY_FLAMEOUT


class TestParseStagingMode:
    """``parse_staging_mode`` accepts the enum values, the 'off' sentinel, and empty/None for off."""

    def test_none_is_off(self) -> None:
        assert parse_staging_mode(None) is None

    def test_empty_string_is_off(self) -> None:
        assert parse_staging_mode("") is None

    def test_whitespace_only_is_off(self) -> None:
        assert parse_staging_mode("   ") is None

    def test_off_keyword_is_off(self) -> None:
        assert parse_staging_mode("off") is None

    def test_off_keyword_is_case_insensitive(self) -> None:
        assert parse_staging_mode("OFF") is None
        assert parse_staging_mode("Off") is None

    def test_off_keyword_strips_whitespace(self) -> None:
        assert parse_staging_mode("  off  ") is None

    def test_full_depletion_keyword(self) -> None:
        assert parse_staging_mode("full_depletion") is StagingMode.FULL_DEPLETION

    def test_any_flameout_keyword(self) -> None:
        assert parse_staging_mode("any_flameout") is StagingMode.ANY_FLAMEOUT

    def test_enum_keyword_is_case_insensitive(self) -> None:
        assert parse_staging_mode("ANY_FLAMEOUT") is StagingMode.ANY_FLAMEOUT

    def test_unknown_value_lists_off_in_error(self) -> None:
        """Error message must mention the 'off' keyword so the user knows how to disable."""
        with pytest.raises(ValueError, match=r"Unknown staging_mode 'bogus'.*off"):
            parse_staging_mode("bogus")
