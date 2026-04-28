"""Tests for the HoverAction altitude-hold controller."""

from __future__ import annotations

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionStatus,
    SpeedMode,
    State,
    VesselCommands,
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

    def test_has_hover_duration_param(self) -> None:
        param_ids = [p.param_id for p in HoverAction.params]
        assert "hover_duration" in param_ids

    def test_hover_duration_param_is_optional_with_default(self) -> None:
        param = next(p for p in HoverAction.params if p.param_id == "hover_duration")
        assert param.required is False
        assert param.default == 0.0
        assert param.unit == "s"


class TestHoverActionTick:
    """Tests for the hover PD-controller logic."""

    def _make_started_action(self, target: float = 100.0, initial_altitude: float = 0.0) -> HoverAction:
        action = HoverAction()
        state = State(altitude_surface=initial_altitude)
        action.start(
            state,
            {
                "target_altitude": target,
                "hover_duration": 0.0,
                "horizontal_control": 0.0,
                "land_at_end": False,
            },
        )
        return action

    def test_below_target_high_throttle(self) -> None:
        action = self._make_started_action(target=100.0)
        state = State(altitude_surface=50.0)
        controls = VesselCommands()
        result = action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle is not None
        assert controls.throttle > 0.5
        assert result.status == ActionStatus.RUNNING

    def test_above_target_low_throttle(self) -> None:
        action = self._make_started_action(target=100.0)
        state = State(altitude_surface=150.0)
        controls = VesselCommands()
        result = action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle is not None
        assert controls.throttle < 0.5
        assert result.status == ActionStatus.RUNNING

    def test_at_target_mid_throttle(self) -> None:
        action = self._make_started_action(target=100.0)
        state = State(altitude_surface=100.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle is not None
        assert abs(controls.throttle - 0.5) < 0.01

    def test_throttle_clamped_to_zero(self) -> None:
        action = self._make_started_action(target=100.0)
        state = State(altitude_surface=10000.0)  # way above target
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle == 0.0

    def test_throttle_clamped_to_one(self) -> None:
        action = self._make_started_action(target=10000.0)
        state = State(altitude_surface=0.0)  # way below target
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle == 1.0

    def test_sas_enabled_during_tick(self) -> None:
        action = self._make_started_action()
        state = State(altitude_surface=50.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.sas is True

    def test_speed_mode_surface_on_first_tick(self) -> None:
        action = self._make_started_action()
        state = State(altitude_surface=50.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.ui_speed_mode == SpeedMode.SURFACE

    def test_speed_mode_not_set_after_first_tick(self) -> None:
        action = self._make_started_action()
        state = State(altitude_surface=50.0)
        action.tick(state, VesselCommands(), dt=0.5, log=ActionLogger())
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.ui_speed_mode is None

    def test_ascending_faster_than_desired_reduces_throttle(self) -> None:
        """5m below target but ascending at 10 m/s (desired ~2.5) - throttle backs off."""
        action = self._make_started_action(target=100.0)
        state = State(altitude_surface=95.0, speed_vertical=10.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle is not None
        assert controls.throttle < 0.5

    def test_descending_faster_than_desired_increases_throttle(self) -> None:
        """10m above target but falling at 10 m/s (desired ~-5) - throttle boosts."""
        action = self._make_started_action(target=100.0)
        state = State(altitude_surface=110.0, speed_vertical=-10.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle is not None
        assert controls.throttle > 0.5

    def test_at_right_speed_for_distance_gives_hover_throttle(self) -> None:
        """10m below target, ascending at desired speed - throttle near hover point."""
        action = self._make_started_action(target=100.0)
        # desired_vspeed = 0.5 * 10 = 5.0, so vspeed=5.0 is exactly right
        state = State(altitude_surface=90.0, speed_vertical=5.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle is not None
        assert abs(controls.throttle - 0.5) < 0.01

    def test_always_returns_running_when_no_duration(self) -> None:
        action = self._make_started_action()
        for alt in [0.0, 50.0, 100.0, 200.0, 1000.0]:
            state = State(altitude_surface=alt)
            controls = VesselCommands()
            result = action.tick(state, controls, dt=0.5, log=ActionLogger())
            assert result.status == ActionStatus.RUNNING


class TestHoverActionDuration:
    """Tests for hover duration countdown after reaching target."""

    def _make_started_action(self, target: float = 100.0, duration: float = 10.0) -> HoverAction:
        action = HoverAction()
        state = State(altitude_surface=0.0)
        action.start(
            state,
            {
                "target_altitude": target,
                "hover_duration": duration,
                "horizontal_control": 0.0,
                "land_at_end": False,
            },
        )
        return action

    def test_does_not_count_before_reaching_target(self) -> None:
        """Duration timer should not start until altitude is reached."""
        action = self._make_started_action(target=100.0, duration=5.0)
        state = State(altitude_surface=50.0)
        for _ in range(20):
            controls = VesselCommands()
            result = action.tick(state, controls, dt=0.5, log=ActionLogger())
            assert result.status == ActionStatus.RUNNING

    def test_succeeds_after_duration_elapsed(self) -> None:
        action = self._make_started_action(target=100.0, duration=5.0)
        at_target = State(altitude_surface=100.0)
        # First tick reaches target and starts counting (0.5s elapsed)
        action.tick(at_target, VesselCommands(), dt=0.5, log=ActionLogger())
        # Accumulate 4.0s more (8 ticks at 0.5s) - total 4.5s, still running
        for _ in range(8):
            result = action.tick(at_target, VesselCommands(), dt=0.5, log=ActionLogger())
            assert result.status == ActionStatus.RUNNING
        # Next tick: 5.0s total, completes
        result = action.tick(at_target, VesselCommands(), dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_zero_duration_means_indefinite(self) -> None:
        action = self._make_started_action(target=100.0, duration=0.0)
        at_target = State(altitude_surface=100.0)
        for _ in range(100):
            result = action.tick(at_target, VesselCommands(), dt=0.5, log=ActionLogger())
            assert result.status == ActionStatus.RUNNING


class TestHoverActionStop:
    """Tests for HoverAction cleanup on stop."""

    def test_stop_does_not_reset_commands(self) -> None:
        action = HoverAction()
        state = State()
        action.start(
            state,
            {
                "target_altitude": 100.0,
                "hover_duration": 0.0,
                "horizontal_control": 0.0,
                "land_at_end": False,
            },
        )
        controls = VesselCommands()
        action.stop(state, controls, log=ActionLogger())
        # HoverAction.stop() only logs; no command resets
        assert controls.throttle is None
        assert controls.sas is None
