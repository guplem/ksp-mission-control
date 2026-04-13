"""Tests for the TranslateAction orient-then-translate controller."""

from __future__ import annotations

import math

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionStatus,
    VesselCommands,
    VesselState,
)
from ksp_mission_control.control.actions.translate.action import (
    TranslateAction,
    _heading_error,
    _lat_lon_to_meters,
    _target_heading,
)

# Kerbin radius for test calculations
_KERBIN_RADIUS = 600000.0


def _meters_to_lat(meters: float) -> float:
    """Convert a north displacement in meters to latitude degrees (at equator)."""
    return math.degrees(meters / _KERBIN_RADIUS)


def _meters_to_lon(meters: float, ref_lat: float = 0.0) -> float:
    """Convert an east displacement in meters to longitude degrees."""
    return math.degrees(meters / (_KERBIN_RADIUS * math.cos(math.radians(ref_lat))))


class TestLatLonToMeters:
    """Tests for the coordinate conversion helper."""

    def test_zero_displacement(self) -> None:
        north, east = _lat_lon_to_meters(0.0, 0.0, 0.0, 0.0, _KERBIN_RADIUS)
        assert north == 0.0
        assert east == 0.0

    def test_north_displacement(self) -> None:
        north, east = _lat_lon_to_meters(1.0, 0.0, 0.0, 0.0, _KERBIN_RADIUS)
        expected = math.radians(1.0) * _KERBIN_RADIUS
        assert abs(north - expected) < 0.1
        assert abs(east) < 0.1

    def test_east_displacement_at_equator(self) -> None:
        north, east = _lat_lon_to_meters(0.0, 1.0, 0.0, 0.0, _KERBIN_RADIUS)
        expected = math.radians(1.0) * _KERBIN_RADIUS
        assert abs(north) < 0.1
        assert abs(east - expected) < 0.1

    def test_east_displacement_at_60_degrees_latitude(self) -> None:
        north, east = _lat_lon_to_meters(60.0, 1.0, 60.0, 0.0, _KERBIN_RADIUS)
        expected = math.radians(1.0) * _KERBIN_RADIUS * 0.5
        assert abs(north) < 0.1
        assert abs(east - expected) < 0.1

    def test_roundtrip_north(self) -> None:
        delta_lat = _meters_to_lat(50.0)
        north, _east = _lat_lon_to_meters(delta_lat, 0.0, 0.0, 0.0, _KERBIN_RADIUS)
        assert abs(north - 50.0) < 0.01

    def test_roundtrip_east(self) -> None:
        delta_lon = _meters_to_lon(50.0)
        _north, east = _lat_lon_to_meters(0.0, delta_lon, 0.0, 0.0, _KERBIN_RADIUS)
        assert abs(east - 50.0) < 0.01


class TestTargetHeading:
    """Tests for target heading computation."""

    def test_north(self) -> None:
        assert abs(_target_heading(100.0, 0.0) - 0.0) < 0.1

    def test_east(self) -> None:
        assert abs(_target_heading(0.0, 100.0) - 90.0) < 0.1

    def test_south(self) -> None:
        assert abs(_target_heading(-100.0, 0.0) - 180.0) < 0.1

    def test_west(self) -> None:
        assert abs(_target_heading(0.0, -100.0) - 270.0) < 0.1

    def test_northeast(self) -> None:
        assert abs(_target_heading(100.0, 100.0) - 45.0) < 0.1


class TestHeadingError:
    """Tests for signed heading error normalization."""

    def test_zero_error(self) -> None:
        assert abs(_heading_error(90.0, 90.0)) < 0.01

    def test_small_clockwise(self) -> None:
        error = _heading_error(100.0, 90.0)
        assert abs(error - 10.0) < 0.01

    def test_small_counterclockwise(self) -> None:
        error = _heading_error(80.0, 90.0)
        assert abs(error - (-10.0)) < 0.01

    def test_wraps_around_north(self) -> None:
        error = _heading_error(10.0, 350.0)
        assert abs(error - 20.0) < 0.01

    def test_wraps_around_north_reverse(self) -> None:
        error = _heading_error(350.0, 10.0)
        assert abs(error - (-20.0)) < 0.01


class TestTranslateActionMetadata:
    """Tests for TranslateAction class-level metadata."""

    def test_action_id(self) -> None:
        assert TranslateAction.action_id == "translate"

    def test_label(self) -> None:
        assert TranslateAction.label == "Translate"

    def test_has_distance_north_param(self) -> None:
        param_ids = [p.param_id for p in TranslateAction.params]
        assert "distance_north" in param_ids

    def test_distance_north_param_is_optional_with_default(self) -> None:
        param = next(p for p in TranslateAction.params if p.param_id == "distance_north")
        assert param.required is False
        assert param.default == 0.0
        assert param.unit == "m"

    def test_has_distance_east_param(self) -> None:
        param_ids = [p.param_id for p in TranslateAction.params]
        assert "distance_east" in param_ids

    def test_distance_east_param_is_optional_with_default(self) -> None:
        param = next(p for p in TranslateAction.params if p.param_id == "distance_east")
        assert param.required is False
        assert param.default == 0.0
        assert param.unit == "m"

    def test_has_max_speed_param(self) -> None:
        param_ids = [p.param_id for p in TranslateAction.params]
        assert "max_speed" in param_ids

    def test_max_speed_param_is_optional_with_default(self) -> None:
        param = next(p for p in TranslateAction.params if p.param_id == "max_speed")
        assert param.required is False
        assert param.default == 10.0
        assert param.unit == "m/s"


class TestTranslateActionTick:
    """Tests for the orient-then-translate controller logic."""

    _START_LAT = 0.0
    _START_LON = 0.0

    def _default_params(self, **overrides: float) -> dict[str, float]:
        params: dict[str, float] = {
            "distance_north": 0.0,
            "distance_east": 0.0,
            "max_speed": 10.0,
            "max_tilt": 10.0,
        }
        params.update(overrides)
        return params

    def _make_started_action(
        self,
        distance_north: float = 100.0,
        distance_east: float = 0.0,
        max_speed: float = 10.0,
        initial_altitude: float = 100.0,
    ) -> TranslateAction:
        action = TranslateAction()
        state = VesselState(
            altitude_surface=initial_altitude,
            latitude=self._START_LAT,
            longitude=self._START_LON,
            body_radius=_KERBIN_RADIUS,
        )
        action.start(
            state,
            self._default_params(
                distance_north=distance_north,
                distance_east=distance_east,
                max_speed=max_speed,
            ),
        )
        return action

    def _state_at_offset(
        self,
        north_meters: float = 0.0,
        east_meters: float = 0.0,
        altitude: float = 100.0,
        heading: float = 0.0,
    ) -> VesselState:
        """Create a VesselState displaced from the start position."""
        return VesselState(
            altitude_surface=altitude,
            heading=heading,
            latitude=self._START_LAT + _meters_to_lat(north_meters),
            longitude=self._START_LON + _meters_to_lon(east_meters, self._START_LAT),
            body_radius=_KERBIN_RADIUS,
        )

    # --- Altitude hold ---

    def test_maintains_altitude_throttle_at_target(self) -> None:
        action = self._make_started_action(initial_altitude=100.0)
        state = self._state_at_offset(altitude=100.0, heading=0.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle is not None
        assert abs(controls.throttle - 0.5) < 0.01

    def test_below_target_altitude_increases_throttle(self) -> None:
        action = self._make_started_action(initial_altitude=100.0)
        state = self._state_at_offset(altitude=80.0, heading=0.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle is not None
        assert controls.throttle > 0.5

    def test_above_target_altitude_decreases_throttle(self) -> None:
        action = self._make_started_action(initial_altitude=100.0)
        state = self._state_at_offset(altitude=120.0, heading=0.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle is not None
        assert controls.throttle < 0.5

    # --- Autopilot and RCS ---

    def test_autopilot_engaged(self) -> None:
        action = self._make_started_action()
        state = self._state_at_offset(altitude=100.0, heading=0.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.autopilot is True
        assert controls.rcs is True
        assert controls.sas is False

    def test_autopilot_pitch_clamped_near_vertical(self) -> None:
        """Autopilot pitch should be clamped to at least 80 deg (max 10 deg tilt)."""
        action = self._make_started_action()
        state = VesselState(
            altitude_surface=100.0,
            heading=0.0,
            pitch=15.4,
            latitude=self._START_LAT,
            longitude=self._START_LON,
            body_radius=_KERBIN_RADIUS,
        )
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.autopilot_pitch == 80.0  # clamped: max(80, 15.4)

    def test_autopilot_pitch_passes_through_when_upright(self) -> None:
        """When vessel pitch is above the minimum, it passes through unchanged."""
        action = self._make_started_action()
        state = VesselState(
            altitude_surface=100.0,
            heading=0.0,
            pitch=85.0,
            latitude=self._START_LAT,
            longitude=self._START_LON,
            body_radius=_KERBIN_RADIUS,
        )
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.autopilot_pitch == 85.0  # above minimum, passes through

    def test_autopilot_heading_set_to_target_direction(self) -> None:
        """Target is north, autopilot heading should be ~0."""
        action = self._make_started_action(distance_north=100.0, distance_east=0.0)
        state = self._state_at_offset(altitude=100.0, heading=0.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.autopilot_heading is not None
        assert abs(controls.autopilot_heading - 0.0) < 1.0

    def test_autopilot_heading_east_target(self) -> None:
        """Target is east, autopilot heading should be ~90."""
        action = self._make_started_action(distance_north=0.0, distance_east=100.0)
        state = self._state_at_offset(altitude=100.0, heading=0.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.autopilot_heading is not None
        assert abs(controls.autopilot_heading - 90.0) < 1.0

    # --- Orienting phase: heading misaligned ---

    def test_no_forward_translation_while_orienting(self) -> None:
        """When heading is misaligned (>10 deg), translate_forward should be 0."""
        action = self._make_started_action(distance_north=0.0, distance_east=100.0)
        # Heading 0, target is east (90) -> 90 deg error
        state = self._state_at_offset(altitude=100.0, heading=0.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.translate_forward == 0.0

    # --- Translating phase: heading aligned ---

    def test_forward_translation_when_aligned(self) -> None:
        """When heading matches target direction, translate_forward should be positive."""
        action = self._make_started_action(distance_north=100.0, distance_east=0.0)
        state = self._state_at_offset(altitude=100.0, heading=0.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.translate_forward is not None
        assert controls.translate_forward > 0.0

    def test_forward_translation_when_nearly_aligned(self) -> None:
        """Within 10 deg threshold should still translate forward."""
        action = self._make_started_action(distance_north=100.0, distance_east=0.0)
        state = self._state_at_offset(altitude=100.0, heading=5.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.translate_forward is not None
        assert controls.translate_forward > 0.0

    def test_translate_forward_clamped(self) -> None:
        action = self._make_started_action(distance_north=10000.0)
        state = self._state_at_offset(altitude=100.0, heading=0.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.translate_forward is not None
        assert -1.0 <= controls.translate_forward <= 1.0

    # --- Deceleration ---

    def test_decelerates_when_close_to_target(self) -> None:
        action_far = self._make_started_action(distance_north=100.0)
        state_far = self._state_at_offset(altitude=100.0, heading=0.0)
        controls_far = VesselCommands()
        action_far.tick(state_far, controls_far, dt=0.5, log=ActionLogger())

        action_close = self._make_started_action(distance_north=3.0)
        state_close = self._state_at_offset(altitude=100.0, heading=0.0)
        controls_close = VesselCommands()
        action_close.tick(state_close, controls_close, dt=0.5, log=ActionLogger())

        assert controls_far.translate_forward is not None
        assert controls_close.translate_forward is not None
        assert controls_far.translate_forward > controls_close.translate_forward

    # --- Heading-independent direction ---

    def test_east_target_with_east_heading_translates_forward(self) -> None:
        action = self._make_started_action(distance_north=0.0, distance_east=100.0)
        state = self._state_at_offset(altitude=100.0, heading=90.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.translate_forward is not None
        assert controls.translate_forward > 0.0

    def test_west_heading_facing_west_translates_forward(self) -> None:
        action = self._make_started_action(distance_north=0.0, distance_east=-100.0)
        state = self._state_at_offset(altitude=100.0, heading=270.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.translate_forward is not None
        assert controls.translate_forward > 0.0

    # --- Completion ---

    def test_succeeds_when_target_reached_and_slow(self) -> None:
        action = self._make_started_action(distance_north=50.0)
        state_near = self._state_at_offset(north_meters=48.8, altitude=100.0, heading=0.0)
        action.tick(state_near, VesselCommands(), dt=0.5, log=ActionLogger())
        state_stopped = self._state_at_offset(north_meters=49.0, altitude=100.0, heading=0.0)
        controls = VesselCommands()
        result = action.tick(state_stopped, controls, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_does_not_succeed_when_still_far(self) -> None:
        action = self._make_started_action(distance_north=100.0)
        state = self._state_at_offset(altitude=100.0, heading=0.0)
        controls = VesselCommands()
        result = action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.RUNNING

    def test_does_not_succeed_when_close_but_fast(self) -> None:
        action = self._make_started_action(distance_north=50.0)
        state_far = self._state_at_offset(north_meters=46.0, altitude=100.0, heading=0.0)
        action.tick(state_far, VesselCommands(), dt=0.5, log=ActionLogger())
        state_close = self._state_at_offset(north_meters=49.0, altitude=100.0, heading=0.0)
        controls = VesselCommands()
        result = action.tick(state_close, controls, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.RUNNING

    def test_zero_distance_succeeds_immediately(self) -> None:
        action = self._make_started_action(distance_north=0.0, distance_east=0.0)
        state = self._state_at_offset(altitude=100.0, heading=0.0)
        controls = VesselCommands()
        result = action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    # --- Braking ---

    def test_brakes_when_going_too_fast_near_target(self) -> None:
        """When actual speed >> desired speed, heading should flip to retrograde."""
        action = self._make_started_action(distance_north=50.0)
        # First tick far away to establish position
        state_far = self._state_at_offset(north_meters=35.0, altitude=100.0, heading=0.0)
        action.tick(state_far, VesselCommands(), dt=0.5, log=ActionLogger())
        # Second tick: big jump = high velocity, close to target
        # Moved 12m in 0.5s = 24 m/s, but desired speed for 3m remaining is ~3 m/s
        state_close = self._state_at_offset(north_meters=47.0, altitude=100.0, heading=0.0)
        controls = VesselCommands()
        action.tick(state_close, controls, dt=0.5, log=ActionLogger())
        # Should be braking: heading ~180 (retrograde of northward travel)
        assert controls.autopilot_heading is not None
        assert abs(controls.autopilot_heading - 180.0) < 30.0  # roughly retrograde

    def test_no_braking_when_slow(self) -> None:
        """When speed is within desired range, heading should point toward target."""
        action = self._make_started_action(distance_north=100.0)
        # First tick to establish position
        state1 = self._state_at_offset(north_meters=0.0, altitude=100.0, heading=0.0)
        action.tick(state1, VesselCommands(), dt=0.5, log=ActionLogger())
        # Second tick: small move = low velocity, far from target
        state2 = self._state_at_offset(north_meters=0.1, altitude=100.0, heading=0.0)
        controls = VesselCommands()
        action.tick(state2, controls, dt=0.5, log=ActionLogger())
        # Should be pointing toward target (north = 0 degrees), not retrograde
        assert controls.autopilot_heading is not None
        assert abs(controls.autopilot_heading - 0.0) < 10.0

    def test_braking_translate_forward_is_positive(self) -> None:
        """During braking, translate_forward should be positive (pushing against motion)."""
        action = self._make_started_action(distance_north=50.0)
        state_far = self._state_at_offset(north_meters=35.0, altitude=100.0, heading=180.0)
        action.tick(state_far, VesselCommands(), dt=0.5, log=ActionLogger())
        # Big jump to trigger braking
        state_close = self._state_at_offset(north_meters=47.0, altitude=100.0, heading=180.0)
        controls = VesselCommands()
        action.tick(state_close, controls, dt=0.5, log=ActionLogger())
        # Heading aligned with retrograde, translate_forward should be positive
        assert controls.translate_forward is not None
        assert controls.translate_forward >= 0.0


class TestTranslateActionStop:
    """Tests for TranslateAction cleanup on stop."""

    def _default_params(self) -> dict[str, float]:
        return {"distance_north": 100.0, "distance_east": 0.0, "max_speed": 10.0, "max_tilt": 10.0}

    def test_stop_kills_throttle(self) -> None:
        action = TranslateAction()
        state = VesselState(altitude_surface=100.0)
        action.start(state, self._default_params())
        controls = VesselCommands()
        action.stop(state, controls, log=ActionLogger())
        assert controls.throttle == 0.0

    def test_stop_disengages_autopilot(self) -> None:
        action = TranslateAction()
        state = VesselState(altitude_surface=100.0)
        action.start(state, self._default_params())
        controls = VesselCommands()
        action.stop(state, controls, log=ActionLogger())
        assert controls.autopilot is False

    def test_stop_disables_rcs(self) -> None:
        action = TranslateAction()
        state = VesselState(altitude_surface=100.0)
        action.start(state, self._default_params())
        controls = VesselCommands()
        action.stop(state, controls, log=ActionLogger())
        assert controls.rcs is False

    def test_stop_zeroes_translation(self) -> None:
        action = TranslateAction()
        state = VesselState(altitude_surface=100.0)
        action.start(state, self._default_params())
        controls = VesselCommands()
        action.stop(state, controls, log=ActionLogger())
        assert controls.translate_forward == 0.0
