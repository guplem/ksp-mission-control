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
_DEFAULT_PARAMS: dict[str, float | bool | str | None] = {
    "apoapsis": False,
    "periapsis": False,
    "above_altitude": None,
    "below_altitude": None,
    "above_available_thrust": None,
    "below_available_thrust": None,
    "above_current_thrust": None,
    "below_current_thrust": None,
    "apoapsis_above": None,
    "above_dynamic_pressure": None,
    "time": None,
    "biome": None,
}


def _params(**overrides: float | bool | str | None) -> dict[str, Any]:
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
        assert "70,000" in result.message

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
        assert "1,000" in result.message

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

    def test_biome_defaults_to_none(self) -> None:
        action = WaitForAction()
        state = State(position_biome="")
        action.start(state, _params(biome=None))
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED


class TestBiome:
    """Tests for the biome parameter."""

    def test_waits_when_biome_does_not_match(self) -> None:
        action = WaitForAction()
        state = State(position_biome="Shores")
        action.start(state, _params(biome="Highlands"))
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert "Highlands" in result.message
        assert "Shores" in result.message

    def test_succeeds_when_biome_matches(self) -> None:
        action = WaitForAction()
        state = State(position_biome="Highlands")
        action.start(state, _params(biome="Highlands"))
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_biome_is_case_sensitive(self) -> None:
        action = WaitForAction()
        state = State(position_biome="highlands")
        action.start(state, _params(biome="Highlands"))
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING


class TestApoapsis:
    """Tests for the apoapsis bool parameter."""

    def test_waits_when_apoapsis_not_yet_passed(self) -> None:
        action = WaitForAction()
        state = State(orbit_apoapsis_passed=False, orbit_apoapsis_time_to=45.0)
        action.start(state, _params(apoapsis=True))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert "45" in result.message

    def test_succeeds_when_apoapsis_passed(self) -> None:
        action = WaitForAction()
        state = State(orbit_apoapsis_passed=True)
        action.start(state, _params(apoapsis=True))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_no_condition_when_apoapsis_false(self) -> None:
        action = WaitForAction()
        state = State(orbit_apoapsis_passed=False)
        action.start(state, _params(apoapsis=False))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED


class TestPeriapsis:
    """Tests for the periapsis bool parameter."""

    def test_waits_when_periapsis_not_yet_passed(self) -> None:
        action = WaitForAction()
        state = State(orbit_periapsis_passed=False, orbit_periapsis_time_to=30.0)
        action.start(state, _params(periapsis=True))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert "30" in result.message

    def test_succeeds_when_periapsis_passed(self) -> None:
        action = WaitForAction()
        state = State(orbit_periapsis_passed=True)
        action.start(state, _params(periapsis=True))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_no_condition_when_periapsis_false(self) -> None:
        action = WaitForAction()
        state = State(orbit_periapsis_passed=False)
        action.start(state, _params(periapsis=False))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED


class TestAboveAltitude:
    """Tests for the above_altitude parameter."""

    def test_waits_when_below_altitude(self) -> None:
        action = WaitForAction()
        state = State(altitude_surface=800.0)
        action.start(state, _params(above_altitude=1000.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert "1,000" in result.message

    def test_succeeds_when_above_altitude(self) -> None:
        action = WaitForAction()
        state = State(altitude_surface=1200.0)
        action.start(state, _params(above_altitude=1000.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_succeeds_when_at_exact_altitude(self) -> None:
        action = WaitForAction()
        state = State(altitude_surface=1000.0)
        action.start(state, _params(above_altitude=1000.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED


class TestBelowAltitude:
    """Tests for the below_altitude parameter."""

    def test_waits_when_above_altitude(self) -> None:
        action = WaitForAction()
        state = State(altitude_surface=1200.0)
        action.start(state, _params(below_altitude=1000.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert "1,000" in result.message

    def test_succeeds_when_below_altitude(self) -> None:
        action = WaitForAction()
        state = State(altitude_surface=800.0)
        action.start(state, _params(below_altitude=1000.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_succeeds_when_at_exact_altitude(self) -> None:
        action = WaitForAction()
        state = State(altitude_surface=1000.0)
        action.start(state, _params(below_altitude=1000.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED


class TestAboveAvailableThrust:
    """Tests for the above_available_thrust parameter."""

    def test_waits_when_thrust_below_threshold(self) -> None:
        action = WaitForAction()
        state = State(thrust_available=50.0)
        action.start(state, _params(above_available_thrust=100.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert "100" in result.message

    def test_succeeds_when_thrust_above_threshold(self) -> None:
        action = WaitForAction()
        state = State(thrust_available=150.0)
        action.start(state, _params(above_available_thrust=100.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_succeeds_when_thrust_equals_threshold(self) -> None:
        action = WaitForAction()
        state = State(thrust_available=100.0)
        action.start(state, _params(above_available_thrust=100.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED


class TestBelowAvailableThrust:
    """Tests for the below_available_thrust parameter."""

    def test_waits_when_thrust_above_threshold(self) -> None:
        action = WaitForAction()
        state = State(thrust_available=150.0)
        action.start(state, _params(below_available_thrust=100.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert "100" in result.message

    def test_succeeds_when_thrust_below_threshold(self) -> None:
        action = WaitForAction()
        state = State(thrust_available=50.0)
        action.start(state, _params(below_available_thrust=100.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_succeeds_when_thrust_equals_threshold(self) -> None:
        action = WaitForAction()
        state = State(thrust_available=100.0)
        action.start(state, _params(below_available_thrust=100.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED


class TestAboveCurrentThrust:
    """Tests for the above_current_thrust parameter."""

    def test_waits_when_thrust_below_threshold(self) -> None:
        action = WaitForAction()
        state = State(thrust=50.0)
        action.start(state, _params(above_current_thrust=100.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert "100" in result.message

    def test_succeeds_when_thrust_above_threshold(self) -> None:
        action = WaitForAction()
        state = State(thrust=150.0)
        action.start(state, _params(above_current_thrust=100.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_succeeds_when_thrust_equals_threshold(self) -> None:
        action = WaitForAction()
        state = State(thrust=100.0)
        action.start(state, _params(above_current_thrust=100.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED


class TestBelowCurrentThrust:
    """Tests for the below_current_thrust parameter."""

    def test_waits_when_thrust_above_threshold(self) -> None:
        action = WaitForAction()
        state = State(thrust=150.0)
        action.start(state, _params(below_current_thrust=100.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert "100" in result.message

    def test_succeeds_when_thrust_below_threshold(self) -> None:
        action = WaitForAction()
        state = State(thrust=50.0)
        action.start(state, _params(below_current_thrust=100.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_succeeds_when_thrust_equals_threshold(self) -> None:
        action = WaitForAction()
        state = State(thrust=100.0)
        action.start(state, _params(below_current_thrust=100.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED


class TestTime:
    """Tests for the time parameter."""

    def test_waits_when_elapsed_below_duration(self) -> None:
        action = WaitForAction()
        state_start = State(universal_time=1000.0)
        action.start(state_start, _params(time=10.0))
        state_tick = State(universal_time=1005.0)
        result = action.tick(state_tick, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert "10" in result.message

    def test_succeeds_when_elapsed_meets_duration(self) -> None:
        action = WaitForAction()
        state_start = State(universal_time=1000.0)
        action.start(state_start, _params(time=10.0))
        state_tick = State(universal_time=1010.0)
        result = action.tick(state_tick, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_succeeds_when_elapsed_exceeds_duration(self) -> None:
        action = WaitForAction()
        state_start = State(universal_time=1000.0)
        action.start(state_start, _params(time=10.0))
        state_tick = State(universal_time=1020.0)
        result = action.tick(state_tick, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_elapsed_time_shown_in_message(self) -> None:
        action = WaitForAction()
        state_start = State(universal_time=1000.0)
        action.start(state_start, _params(time=10.0))
        state_tick = State(universal_time=1003.0)
        result = action.tick(state_tick, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert "3" in result.message
