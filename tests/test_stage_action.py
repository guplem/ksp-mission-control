"""Tests for the StageAction."""

from __future__ import annotations

from typing import Any

import pytest

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionStatus,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.stage.action import StageAction

ParamValue = int | None

_DEFAULT_PARAMS: dict[str, Any] = {"until": None}


def _params(**overrides: ParamValue) -> dict[str, Any]:
    return {**_DEFAULT_PARAMS, **overrides}


def _tick(action: StageAction, state: State) -> tuple[VesselCommands, Any]:
    commands = VesselCommands()
    result = action.tick(state, commands, 0.5, ActionLogger())
    return commands, result


class TestOneShot:
    def test_stages_once_and_succeeds(self) -> None:
        action = StageAction()
        state = State(stage_current=3)
        action.start(state, _params())
        commands, result = _tick(action, state)
        assert commands.stage is True
        assert result.status == ActionStatus.SUCCEEDED
        assert "stage 3" in result.message

    def test_fails_when_already_at_stage_zero(self) -> None:
        action = StageAction()
        state = State(stage_current=0)
        action.start(state, _params())
        commands, result = _tick(action, state)
        assert commands.stage is None
        assert result.status == ActionStatus.FAILED
        assert "already at stage 0" in result.message


class TestUntil:
    def test_stages_repeatedly_while_above_target(self) -> None:
        action = StageAction()
        state = State(stage_current=4)
        action.start(state, _params(until=0))
        commands, result = _tick(action, state)
        assert commands.stage is True
        assert result.status == ActionStatus.RUNNING

    def test_succeeds_when_stage_current_reaches_target(self) -> None:
        action = StageAction()
        state = State(stage_current=4)
        action.start(state, _params(until=2))
        # Simulate progressing toward target by feeding decreasing stage_current.
        for stage in (4, 3):
            commands, result = _tick(action, State(stage_current=stage))
            assert commands.stage is True
            assert result.status == ActionStatus.RUNNING

        commands, result = _tick(action, State(stage_current=2))
        assert commands.stage is None
        assert result.status == ActionStatus.SUCCEEDED

    def test_succeeds_immediately_when_already_at_or_below_target(self) -> None:
        action = StageAction()
        state = State(stage_current=1)
        action.start(state, _params(until=2))
        commands, result = _tick(action, state)
        assert commands.stage is None
        assert result.status == ActionStatus.SUCCEEDED

    def test_until_zero_stops_at_final_stage(self) -> None:
        action = StageAction()
        state = State(stage_current=1)
        action.start(state, _params(until=0))
        # Stage 1 is the last fireable stage; activating it leaves stage_current = 0.
        commands, result = _tick(action, state)
        assert commands.stage is True
        assert result.status == ActionStatus.RUNNING

        commands, result = _tick(action, State(stage_current=0))
        assert commands.stage is None
        assert result.status == ActionStatus.SUCCEEDED

    def test_rejects_negative_until(self) -> None:
        action = StageAction()
        with pytest.raises(ValueError, match="'until' must be >= 0"):
            action.start(State(stage_current=3), _params(until=-1))
