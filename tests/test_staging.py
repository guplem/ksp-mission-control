"""Tests for the auto_stage helper that advances staging when engines run dry."""

from __future__ import annotations

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    PartInfo,
    Parts,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.helpers.staging import StagingMode, auto_stage


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
