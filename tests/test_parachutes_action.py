"""Tests for the ParachutesAction deployment."""

from __future__ import annotations

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionStatus,
    PartInfo,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.parachutes.action import ParachutesAction


class TestParachutesActionMetadata:
    """Tests for ParachutesAction class-level metadata."""

    def test_action_id(self) -> None:
        assert ParachutesAction.action_id == "parachutes"

    def test_label(self) -> None:
        assert ParachutesAction.label == "Deploy Parachutes"

    def test_has_min_altitude_param(self) -> None:
        param_ids = [p.param_id for p in ParachutesAction.params]
        assert "min_altitude" in param_ids

    def test_has_stage_for_parachutes_param(self) -> None:
        param_ids = [p.param_id for p in ParachutesAction.params]
        assert "stage_for_parachutes" in param_ids


class TestParachutesActionTick:
    """Tests for parachute deployment logic."""

    def _make_started_action(
        self,
        min_altitude: float | None = 3_000.0,
        initial_altitude: float = 0.0,
        stage_for_parachutes: bool = False,
    ) -> ParachutesAction:
        action = ParachutesAction()
        state = State(altitude_surface=initial_altitude)
        action.start(
            state,
            {
                "min_altitude": min_altitude,
                "stage_for_parachutes": stage_for_parachutes,
            },
        )
        return action

    def test_fails_when_no_parachutes(self) -> None:
        action = self._make_started_action(min_altitude=None)
        state = State(altitude_surface=1000.0, parts_parachutes=())
        commands = VesselCommands()
        result = action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.FAILED

    def test_waits_above_min_altitude(self) -> None:
        action = self._make_started_action(min_altitude=3000.0)
        state = State(
            altitude_surface=5000.0,
            stage_current=3,
            parts_parachutes=(PartInfo(3, "stowed"), PartInfo(3, "stowed")),
        )
        commands = VesselCommands()
        result = action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert commands.deployable_parachutes is None

    def test_deploys_when_in_current_stage(self) -> None:
        action = self._make_started_action(min_altitude=3000.0)
        state = State(
            altitude_surface=2500.0,
            stage_current=3,
            parts_parachutes=(PartInfo(3, "stowed"), PartInfo(3, "stowed")),
        )
        commands = VesselCommands()
        result = action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED
        assert commands.deployable_parachutes is True

    def test_deploys_immediately_when_no_altitude_set(self) -> None:
        action = self._make_started_action(min_altitude=None)
        state = State(
            altitude_surface=50000.0,
            stage_current=3,
            parts_parachutes=(PartInfo(3, "stowed"),),
        )
        commands = VesselCommands()
        result = action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED
        assert commands.deployable_parachutes is True

    def test_stages_when_no_parachutes_in_current_stage(self) -> None:
        action = self._make_started_action(
            min_altitude=None,
            stage_for_parachutes=True,
        )
        state = State(
            altitude_surface=1000.0,
            stage_current=5,
            parts_parachutes=(PartInfo(3, "stowed"), PartInfo(3, "stowed")),
        )
        commands = VesselCommands()
        result = action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert commands.stage is True
        assert commands.deployable_parachutes is None

    def test_deploys_when_parachutes_in_current_stage(self) -> None:
        action = self._make_started_action(
            min_altitude=None,
            stage_for_parachutes=True,
        )
        state = State(
            altitude_surface=1000.0,
            stage_current=3,
            parts_parachutes=(PartInfo(3, "stowed"), PartInfo(3, "stowed")),
        )
        commands = VesselCommands()
        result = action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED
        assert commands.deployable_parachutes is True

    def test_fails_when_not_in_stage_and_staging_disabled(self) -> None:
        action = self._make_started_action(
            min_altitude=None,
            stage_for_parachutes=False,
        )
        state = State(
            altitude_surface=1000.0,
            stage_current=5,
            parts_parachutes=(PartInfo(3, "stowed"),),
        )
        commands = VesselCommands()
        result = action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.FAILED
        assert commands.deployable_parachutes is None
