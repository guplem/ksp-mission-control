"""Tests for the HoverAction altitude-hold controller."""

from __future__ import annotations

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionStatus,
    VesselCommands,
    VesselState,
)
from ksp_mission_control.control.actions.hover.action import HoverAction


class TestHoverActionMetadata:
    """Tests for HoverAction class-level metadata."""

    def test_action_id(self) -> None:
        assert HoverAction.action_id == "hover"

    def test_label(self) -> None:
        assert HoverAction.label == "Hover"

    def test_has_target_altitude_param(self) -> None:
        param_ids = [p.param_id for p in HoverAction.params]
        assert "target_altitude" in param_ids

    def test_target_altitude_param_is_optional_with_default(self) -> None:
        param = next(p for p in HoverAction.params if p.param_id == "target_altitude")
        assert param.required is False
        assert param.default == 100.0
        assert param.unit == "m"


class TestHoverActionTick:
    """Tests for the hover PD-controller logic."""

    def _make_started_action(self, target: float = 100.0) -> HoverAction:
        action = HoverAction()
        action.start({"target_altitude": target})
        return action

    def test_below_target_high_throttle(self) -> None:
        action = self._make_started_action(target=100.0)
        state = VesselState(altitude_surface=50.0)
        controls = VesselCommands()
        result = action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle is not None
        assert controls.throttle > 0.5
        assert result.status == ActionStatus.RUNNING

    def test_above_target_low_throttle(self) -> None:
        action = self._make_started_action(target=100.0)
        state = VesselState(altitude_surface=150.0)
        controls = VesselCommands()
        result = action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle is not None
        assert controls.throttle < 0.5
        assert result.status == ActionStatus.RUNNING

    def test_at_target_mid_throttle(self) -> None:
        action = self._make_started_action(target=100.0)
        state = VesselState(altitude_surface=100.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle is not None
        assert abs(controls.throttle - 0.5) < 0.01

    def test_throttle_clamped_to_zero(self) -> None:
        action = self._make_started_action(target=100.0)
        state = VesselState(altitude_surface=10000.0)  # way above target
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle == 0.0

    def test_throttle_clamped_to_one(self) -> None:
        action = self._make_started_action(target=10000.0)
        state = VesselState(altitude_surface=0.0)  # way below target
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle == 1.0

    def test_sas_enabled_during_tick(self) -> None:
        action = self._make_started_action()
        state = VesselState(altitude_surface=50.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.sas is True

    def test_rising_toward_target_reduces_throttle(self) -> None:
        """Below target but ascending fast - D-term should reduce throttle below 0.5."""
        action = self._make_started_action(target=100.0)
        state = VesselState(altitude_surface=90.0, vertical_speed=5.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle is not None
        assert controls.throttle < 0.5

    def test_falling_away_from_target_increases_throttle(self) -> None:
        """Above target but descending fast - D-term should boost throttle above 0.5."""
        action = self._make_started_action(target=100.0)
        state = VesselState(altitude_surface=110.0, vertical_speed=-5.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle is not None
        assert controls.throttle > 0.5

    def test_damping_prevents_full_throttle_near_target(self) -> None:
        """5m below target but rising at 3 m/s - D-term keeps throttle low."""
        action = self._make_started_action(target=100.0)
        state = VesselState(altitude_surface=95.0, vertical_speed=3.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle is not None
        assert controls.throttle < 0.5

    def test_always_returns_running(self) -> None:
        action = self._make_started_action()
        for alt in [0.0, 50.0, 100.0, 200.0, 1000.0]:
            state = VesselState(altitude_surface=alt)
            controls = VesselCommands()
            result = action.tick(state, controls, dt=0.5, log=ActionLogger())
            assert result.status == ActionStatus.RUNNING


class TestHoverActionStop:
    """Tests for HoverAction cleanup on stop."""

    def test_stop_kills_throttle(self) -> None:
        action = HoverAction()
        action.start({"target_altitude": 100.0})
        controls = VesselCommands()
        action.stop(controls, log=ActionLogger())
        assert controls.throttle == 0.0

    def test_stop_disables_sas(self) -> None:
        action = HoverAction()
        action.start({"target_altitude": 100.0})
        controls = VesselCommands()
        action.stop(controls, log=ActionLogger())
        assert controls.sas is False
