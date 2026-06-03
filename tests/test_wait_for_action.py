"""Tests for the WaitForAction."""

from __future__ import annotations

from typing import Any

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionStatus,
    ManeuverNode,
    ScienceSituation,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.wait_for.action import (
    _DEFAULT_ORIENTATION_MARGIN_DEG,
    WaitForAction,
)

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
    "below_time_to_impact": None,
    "time": None,
    "time_before_next_maneuver": None,
    "time_before_apoapsis": None,
    "time_before_periapsis": None,
    "biome": None,
    "situation": None,
    "science_situation": None,
    "orientation": None,
    "orientation_margin": _DEFAULT_ORIENTATION_MARGIN_DEG,
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


class TestBelowTimeToImpact:
    """Tests for the below_time_to_impact parameter."""

    def test_waits_when_time_to_impact_above_threshold(self) -> None:
        action = WaitForAction()
        state = State(altitude_surface=1000.0, speed_vertical=-50.0)  # 20s to impact
        action.start(state, _params(below_time_to_impact=10.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert "10" in result.message
        assert "20" in result.message

    def test_succeeds_when_time_to_impact_below_threshold(self) -> None:
        action = WaitForAction()
        state = State(altitude_surface=200.0, speed_vertical=-50.0)  # 4s to impact
        action.start(state, _params(below_time_to_impact=10.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_succeeds_when_time_to_impact_equals_threshold(self) -> None:
        action = WaitForAction()
        state = State(altitude_surface=500.0, speed_vertical=-50.0)  # 10s to impact
        action.start(state, _params(below_time_to_impact=10.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_waits_when_not_descending(self) -> None:
        # linear_time_to_impact is inf when vessel is not descending.
        action = WaitForAction()
        state = State(altitude_surface=1000.0, speed_vertical=10.0)
        action.start(state, _params(below_time_to_impact=10.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING

    def test_defaults_to_none(self) -> None:
        action = WaitForAction()
        state = State(altitude_surface=1000.0, speed_vertical=-50.0)
        action.start(state, _params(below_time_to_impact=None))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
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


class TestScienceSituation:
    """Tests for the science_situation parameter."""

    def test_waits_when_science_situation_does_not_match(self) -> None:
        action = WaitForAction()
        state = State(science_situation=ScienceSituation.ATMOSPHERE_LOW)
        action.start(state, _params(science_situation="space_low"))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert "space_low" in result.message
        assert "atmosphere_low" in result.message

    def test_succeeds_when_science_situation_matches(self) -> None:
        action = WaitForAction()
        state = State(science_situation=ScienceSituation.SPACE_LOW)
        action.start(state, _params(science_situation="space_low"))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_accepts_uppercase_value(self) -> None:
        action = WaitForAction()
        state = State(science_situation=ScienceSituation.SURFACE_LANDED)
        action.start(state, _params(science_situation="SURFACE_LANDED"))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_defaults_to_none(self) -> None:
        action = WaitForAction()
        state = State(science_situation=ScienceSituation.SPACE_HIGH)
        action.start(state, _params(science_situation=None))
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


class TestOrientation:
    """Tests for the orientation parameter."""

    def test_succeeds_when_pointed_prograde(self) -> None:
        action = WaitForAction()
        # Vessel forward exactly matches prograde (+y in orbital frame).
        state = State(orientation_direction_orbital=(0.0, 1.0, 0.0))
        action.start(state, _params(orientation="prograde"))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_waits_when_off_prograde_beyond_margin(self) -> None:
        action = WaitForAction()
        # 45° away from prograde, default 10° margin.
        import math

        state = State(orientation_direction_orbital=(0.0, math.cos(math.radians(45.0)), math.sin(math.radians(45.0))))
        action.start(state, _params(orientation="prograde"))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert "prograde" in result.message
        assert "45" in result.message

    def test_succeeds_when_within_default_margin(self) -> None:
        action = WaitForAction()
        # ~5° off prograde, within the default 10° margin.
        import math

        state = State(orientation_direction_orbital=(0.0, math.cos(math.radians(5.0)), math.sin(math.radians(5.0))))
        action.start(state, _params(orientation="prograde"))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_custom_margin_tighter(self) -> None:
        action = WaitForAction()
        # 5° off prograde, but margin tightened to 2°.
        import math

        state = State(orientation_direction_orbital=(0.0, math.cos(math.radians(5.0)), math.sin(math.radians(5.0))))
        action.start(state, _params(orientation="prograde", orientation_margin=2.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING

    def test_retrograde(self) -> None:
        action = WaitForAction()
        state = State(orientation_direction_orbital=(0.0, -1.0, 0.0))
        action.start(state, _params(orientation="retrograde"))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_retrograde_fails_when_facing_prograde(self) -> None:
        action = WaitForAction()
        state = State(orientation_direction_orbital=(0.0, 1.0, 0.0))
        action.start(state, _params(orientation="retrograde"))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING

    def test_radial_uses_negative_x_in_orbital_frame(self) -> None:
        # KSP "radial" marker points away from the body. In the kRPC orbital
        # frame the +x axis is anti-radial (toward body), so radial-out is -x.
        action = WaitForAction()
        state = State(orientation_direction_orbital=(-1.0, 0.0, 0.0))
        action.start(state, _params(orientation="radial"))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_anti_radial_uses_positive_x(self) -> None:
        action = WaitForAction()
        state = State(orientation_direction_orbital=(1.0, 0.0, 0.0))
        action.start(state, _params(orientation="anti_radial"))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_normal_and_anti_normal(self) -> None:
        action_normal = WaitForAction()
        state_normal = State(orientation_direction_orbital=(0.0, 0.0, 1.0))
        action_normal.start(state_normal, _params(orientation="normal"))
        assert action_normal.tick(state_normal, VesselCommands(), 0.5, ActionLogger()).status == ActionStatus.SUCCEEDED

        action_anti = WaitForAction()
        state_anti = State(orientation_direction_orbital=(0.0, 0.0, -1.0))
        action_anti.start(state_anti, _params(orientation="anti_normal"))
        assert action_anti.tick(state_anti, VesselCommands(), 0.5, ActionLogger()).status == ActionStatus.SUCCEEDED

    def test_surface_prograde_uses_surface_velocity_frame(self) -> None:
        action = WaitForAction()
        # Pointing prograde in surface-velocity frame, but NOT in orbital frame.
        state = State(
            orientation_direction_orbital=(1.0, 0.0, 0.0),
            orientation_direction_surface_velocity=(0.0, 1.0, 0.0),
        )
        action.start(state, _params(orientation="surface_prograde"))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_maneuver_fails_when_no_node(self) -> None:
        action = WaitForAction()
        state = State(nodes=())
        action.start(state, _params(orientation="maneuver"))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.FAILED
        assert "maneuver" in result.message.lower()
        assert "no" in result.message.lower() or "none" in result.message.lower() or "requires" in result.message.lower()

    def test_maneuver_succeeds_when_pointed_along_burn_vector(self) -> None:
        action = WaitForAction()
        node = ManeuverNode(
            index=0,
            ut=1000.0,
            time_to=60.0,
            delta_v=100.0,
            delta_v_remaining=100.0,
            prograde=100.0,
            normal=0.0,
            radial=0.0,
            burn_vector=(0.0, 100.0, 0.0),
            burn_vector_remaining=(0.0, 100.0, 0.0),
            burn_time_estimate=10.0,
            post_burn_orbit_apoapsis=80_000.0,
            post_burn_orbit_periapsis=80_000.0,
            post_burn_orbit_eccentricity=0.0,
            post_burn_orbit_inclination=0.0,
            post_burn_orbit_period=2400.0,
            post_burn_orbit_semi_major_axis=680_000.0,
        )
        state = State(nodes=(node,), orientation_direction_body_non_rotating=(0.0, 1.0, 0.0))
        action.start(state, _params(orientation="maneuver"))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_accepts_uppercase_value(self) -> None:
        action = WaitForAction()
        state = State(orientation_direction_orbital=(0.0, 1.0, 0.0))
        action.start(state, _params(orientation="PROGRADE"))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_unknown_orientation_raises(self) -> None:
        import pytest

        action = WaitForAction()
        with pytest.raises(ValueError, match="Unknown orientation"):
            action.start(State(), _params(orientation="sideways"))

    def test_defaults_to_none(self) -> None:
        action = WaitForAction()
        # Direction is zero vector (no real data) but no orientation param set.
        state = State()
        action.start(state, _params(orientation=None))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED


def _node_at(time_to: float) -> ManeuverNode:
    """Build a ManeuverNode with the specified time_to and benign defaults."""
    return ManeuverNode(
        index=0,
        ut=1_000.0 + time_to,
        time_to=time_to,
        delta_v=100.0,
        delta_v_remaining=100.0,
        prograde=100.0,
        normal=0.0,
        radial=0.0,
        burn_vector=(0.0, 100.0, 0.0),
        burn_vector_remaining=(0.0, 100.0, 0.0),
        burn_time_estimate=10.0,
        post_burn_orbit_apoapsis=80_000.0,
        post_burn_orbit_periapsis=80_000.0,
        post_burn_orbit_eccentricity=0.0,
        post_burn_orbit_inclination=0.0,
        post_burn_orbit_period=2_400.0,
        post_burn_orbit_semi_major_axis=680_000.0,
    )


class TestTimeBeforeNextManeuver:
    def test_waits_when_node_is_far_away(self) -> None:
        action = WaitForAction()
        state = State(nodes=(_node_at(time_to=300.0),))
        action.start(state, _params(time_before_next_maneuver=60.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert "300" in result.message

    def test_succeeds_when_node_is_close(self) -> None:
        action = WaitForAction()
        state = State(nodes=(_node_at(time_to=45.0),))
        action.start(state, _params(time_before_next_maneuver=60.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_fails_when_no_node_exists(self) -> None:
        action = WaitForAction()
        state = State(nodes=())
        action.start(state, _params(time_before_next_maneuver=60.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.FAILED
        assert "maneuver node" in result.message.lower()


class TestTimeBeforeApoapsis:
    def test_waits_when_apoapsis_is_far(self) -> None:
        action = WaitForAction()
        state = State(orbit_apoapsis_time_to=600.0)
        action.start(state, _params(time_before_apoapsis=60.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING

    def test_succeeds_when_apoapsis_is_close(self) -> None:
        action = WaitForAction()
        state = State(orbit_apoapsis_time_to=30.0)
        action.start(state, _params(time_before_apoapsis=60.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED


class TestTimeBeforePeriapsis:
    def test_waits_when_periapsis_is_far(self) -> None:
        action = WaitForAction()
        state = State(orbit_periapsis_time_to=600.0)
        action.start(state, _params(time_before_periapsis=60.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING

    def test_succeeds_when_periapsis_is_close(self) -> None:
        action = WaitForAction()
        state = State(orbit_periapsis_time_to=15.0)
        action.start(state, _params(time_before_periapsis=60.0))
        result = action.tick(state, VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED


class TestOrientationWarpDrop:
    """Reaching an orientation needs the vessel to rotate, which rails warp
    freezes; wait_for drops to 1x while waiting, and only for orientation."""

    def test_drops_warp_while_waiting_for_orientation(self) -> None:
        import math

        action = WaitForAction()
        # 45 deg off prograde under 100x warp: must drop to 1x to slew.
        state = State(
            orientation_direction_orbital=(0.0, math.cos(math.radians(45.0)), math.sin(math.radians(45.0))),
            time_warp_rate=100.0,
        )
        action.start(state, _params(orientation="prograde"))
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert commands.time_warp_rate == 1.0

    def test_no_warp_command_at_1x_while_waiting(self) -> None:
        import math

        action = WaitForAction()
        state = State(
            orientation_direction_orbital=(0.0, math.cos(math.radians(45.0)), math.sin(math.radians(45.0))),
            time_warp_rate=1.0,
        )
        action.start(state, _params(orientation="prograde"))
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert commands.time_warp_rate is None
        assert "orientation" in result.message

    def test_no_warp_drop_when_already_aligned(self) -> None:
        action = WaitForAction()
        state = State(orientation_direction_orbital=(0.0, 1.0, 0.0), time_warp_rate=100.0)
        action.start(state, _params(orientation="prograde"))
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED
        assert commands.time_warp_rate is None

    def test_positional_wait_does_not_drop_warp(self) -> None:
        # A non-orientation wait (apoapsis) must keep warping: positional state
        # advances under warp, so we do not drop it.
        action = WaitForAction()
        state = State(orbit_apoapsis_passed=False, time_warp_rate=100.0)
        action.start(state, _params(apoapsis=True))
        commands = VesselCommands()
        result = action.tick(state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert commands.time_warp_rate is None
