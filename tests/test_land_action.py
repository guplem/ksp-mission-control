"""Tests for the LandAction controlled descent controller."""

from __future__ import annotations

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionStatus,
    SpeedMode,
    VesselCommands,
    VesselSituation,
    VesselState,
)
from ksp_mission_control.control.actions.land.action import LandAction


class TestLandActionMetadata:
    """Tests for LandAction class-level metadata."""

    def test_action_id(self) -> None:
        assert LandAction.action_id == "land"

    def test_label(self) -> None:
        assert LandAction.label == "Land"

    def test_has_target_speed_param(self) -> None:
        param_ids = [p.param_id for p in LandAction.params]
        assert "target_speed" in param_ids

    def test_target_speed_param_is_optional_with_default(self) -> None:
        param = next(p for p in LandAction.params if p.param_id == "target_speed")
        assert param.required is False
        assert param.default == 2.0
        assert param.unit == "m/s"


class TestLandActionTick:
    """Tests for the landing PD-controller logic."""

    def _make_started_action(self, target_speed: float = 2.0) -> LandAction:
        action = LandAction()
        state = VesselState(altitude_surface=500.0)
        action.start(state, {"target_speed": target_speed})
        return action

    def test_descending_too_fast_increases_throttle(self) -> None:
        """Falling faster than target speed should boost throttle above 0.5."""
        action = self._make_started_action(target_speed=2.0)
        state = VesselState(altitude_surface=30.0, vertical_speed=-10.0)
        controls = VesselCommands()
        result = action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle is not None
        assert controls.throttle > 0.5
        assert result.status == ActionStatus.RUNNING

    def test_descending_at_target_speed_near_ground(self) -> None:
        """At target speed near ground, throttle should be moderate."""
        action = self._make_started_action(target_speed=2.0)
        state = VesselState(altitude_surface=10.0, vertical_speed=-2.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle is not None
        # Should be roughly around 0.5 when at target speed
        assert 0.2 < controls.throttle < 0.8

    def test_ascending_reduces_throttle(self) -> None:
        """If vessel is ascending during landing, throttle should be low."""
        action = self._make_started_action(target_speed=2.0)
        state = VesselState(altitude_surface=50.0, vertical_speed=5.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle is not None
        assert controls.throttle < 0.5

    def test_throttle_clamped_to_zero(self) -> None:
        action = self._make_started_action(target_speed=2.0)
        state = VesselState(altitude_surface=50.0, vertical_speed=20.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle == 0.0

    def test_throttle_clamped_to_one(self) -> None:
        action = self._make_started_action(target_speed=2.0)
        state = VesselState(altitude_surface=10.0, vertical_speed=-50.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle == 1.0

    def test_sas_enabled_during_tick(self) -> None:
        action = self._make_started_action()
        state = VesselState(altitude_surface=100.0, vertical_speed=-2.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.sas is True

    def test_gear_deployed_below_50m(self) -> None:
        action = self._make_started_action()
        state = VesselState(altitude_surface=40.0, vertical_speed=-2.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.gear is True

    def test_gear_not_deployed_above_50m(self) -> None:
        action = self._make_started_action()
        state = VesselState(altitude_surface=100.0, vertical_speed=-2.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.gear is None

    def test_faster_descent_at_high_altitude(self) -> None:
        """Above 100m, descent rate should be faster than target speed."""
        # Use separate action instances so acceleration estimate doesn't interfere
        action_high = self._make_started_action(target_speed=2.0)
        state_high = VesselState(altitude_surface=300.0, vertical_speed=-2.0)
        controls_high = VesselCommands()
        action_high.tick(state_high, controls_high, dt=0.5, log=ActionLogger())

        action_low = self._make_started_action(target_speed=2.0)
        state_low = VesselState(altitude_surface=30.0, vertical_speed=-2.0)
        controls_low = VesselCommands()
        action_low.tick(state_low, controls_low, dt=0.5, log=ActionLogger())

        # High altitude should have less throttle (wants faster descent)
        assert controls_high.throttle is not None
        assert controls_low.throttle is not None
        assert controls_high.throttle < controls_low.throttle

    def test_lights_on_first_tick(self) -> None:
        action = self._make_started_action()
        state = VesselState(altitude_surface=200.0, vertical_speed=-2.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.lights is True

    def test_speed_mode_surface_on_first_tick(self) -> None:
        action = self._make_started_action()
        state = VesselState(altitude_surface=200.0, vertical_speed=-2.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.speed_mode == SpeedMode.SURFACE

    def test_speed_mode_not_set_after_first_tick(self) -> None:
        action = self._make_started_action()
        state = VesselState(altitude_surface=200.0, vertical_speed=-2.0)
        action.tick(state, VesselCommands(), dt=0.5, log=ActionLogger())
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.speed_mode is None

    def test_lights_only_on_first_tick(self) -> None:
        action = self._make_started_action()
        state = VesselState(altitude_surface=200.0, vertical_speed=-2.0)
        # First tick sets lights
        action.tick(state, VesselCommands(), dt=0.5, log=ActionLogger())
        # Second tick should not set lights
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.lights is None

    def test_brakes_on_landing(self) -> None:
        action = self._make_started_action()
        state = VesselState(
            altitude_surface=0.5,
            vertical_speed=-0.1,
            situation=VesselSituation.LANDED,
        )
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.brakes is True

    def test_succeeds_on_landed(self) -> None:
        action = self._make_started_action()
        state = VesselState(
            altitude_surface=0.5,
            vertical_speed=-0.1,
            situation=VesselSituation.LANDED,
        )
        controls = VesselCommands()
        result = action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_running_while_flying(self) -> None:
        action = self._make_started_action()
        state = VesselState(
            altitude_surface=100.0,
            vertical_speed=-2.0,
            situation=VesselSituation.FLYING,
        )
        controls = VesselCommands()
        result = action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.RUNNING


class TestLandActionStop:
    """Tests for LandAction cleanup on stop."""

    def test_stop_kills_throttle(self) -> None:
        action = LandAction()
        state = VesselState()
        action.start(state, {"target_speed": 2.0})
        controls = VesselCommands()
        action.stop(state, controls, log=ActionLogger())
        assert controls.throttle == 0.0

    def test_stop_disables_sas(self) -> None:
        action = LandAction()
        state = VesselState()
        action.start(state, {"target_speed": 2.0})
        controls = VesselCommands()
        action.stop(state, controls, log=ActionLogger())
        assert controls.sas is False
