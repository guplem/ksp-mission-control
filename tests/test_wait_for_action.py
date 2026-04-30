"""Tests for the WaitForAction."""

from __future__ import annotations

from typing import Any

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionStatus,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.wait_for.action import WaitForAction

# Default param dict matching ActionParam defaults. Tests override only the
# params they care about, keeping each test focused on a single condition.
_DEFAULT_PARAMS: dict[str, float | bool | None] = {
    "apoapsis": False,
    "periapsis": False,
    "above_altitude": None,
    "below_altitude": None,
    "above_available_thrust": None,
    "below_available_thrust": None,
    "apoapsis_above": None,
    "above_dynamic_pressure": None,
    "time": None,
}


def _params(**overrides: float | bool | None) -> dict[str, Any]:
    """Return a full param dict with overrides applied."""
    return {**_DEFAULT_PARAMS, **overrides}


class TestApoapsisAbove:
    """Tests for the apoapsis_above parameter."""

    def test_waits_when_apoapsis_below_threshold(self) -> None:
        action = WaitForAction()
        state = State(orbit_apoapsis=50_000.0)
        action.start(state, _params(apoapsis_above=70_000.0))
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert "70000" in result.message

    def test_succeeds_when_apoapsis_above_threshold(self) -> None:
        action = WaitForAction()
        state = State(orbit_apoapsis=75_000.0)
        action.start(state, _params(apoapsis_above=70_000.0))
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_succeeds_when_apoapsis_equals_threshold(self) -> None:
        action = WaitForAction()
        state = State(orbit_apoapsis=70_000.0)
        action.start(state, _params(apoapsis_above=70_000.0))
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED


class TestAboveDynamicPressure:
    """Tests for the above_dynamic_pressure parameter."""

    def test_waits_when_pressure_below_threshold(self) -> None:
        action = WaitForAction()
        state = State(pressure_dynamic=500.0)
        action.start(state, _params(above_dynamic_pressure=1000.0))
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert "1000" in result.message

    def test_succeeds_when_pressure_above_threshold(self) -> None:
        action = WaitForAction()
        state = State(pressure_dynamic=1500.0)
        action.start(state, _params(above_dynamic_pressure=1000.0))
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_succeeds_when_pressure_equals_threshold(self) -> None:
        action = WaitForAction()
        state = State(pressure_dynamic=1000.0)
        action.start(state, _params(above_dynamic_pressure=1000.0))
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED


class TestCombinedConditions:
    """Tests that multiple conditions must all be met."""

    def test_waits_when_only_apoapsis_met(self) -> None:
        action = WaitForAction()
        state = State(orbit_apoapsis=80_000.0, pressure_dynamic=500.0)
        action.start(state, _params(apoapsis_above=70_000.0, above_dynamic_pressure=1000.0))
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING

    def test_succeeds_when_all_conditions_met(self) -> None:
        action = WaitForAction()
        state = State(orbit_apoapsis=80_000.0, pressure_dynamic=1500.0)
        action.start(state, _params(apoapsis_above=70_000.0, above_dynamic_pressure=1000.0))
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED


class TestDefaultParams:
    """Tests that new params default to inactive (no condition)."""

    def test_apoapsis_above_defaults_to_none(self) -> None:
        action = WaitForAction()
        state = State(orbit_apoapsis=0.0)
        action.start(state, _params(apoapsis_above=None))
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_above_dynamic_pressure_defaults_to_none(self) -> None:
        action = WaitForAction()
        state = State(pressure_dynamic=0.0)
        action.start(state, _params(above_dynamic_pressure=None))
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED
