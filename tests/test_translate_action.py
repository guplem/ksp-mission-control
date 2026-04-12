"""Tests for the TranslateAction hovering translation controller."""

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
    _lat_lon_to_meters,
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
        """1 degree north at equator on Kerbin should be ~10,472m."""
        north, east = _lat_lon_to_meters(1.0, 0.0, 0.0, 0.0, _KERBIN_RADIUS)
        expected = math.radians(1.0) * _KERBIN_RADIUS
        assert abs(north - expected) < 0.1
        assert abs(east) < 0.1

    def test_east_displacement_at_equator(self) -> None:
        """1 degree east at equator should equal 1 degree north (cos(0)=1)."""
        north, east = _lat_lon_to_meters(0.0, 1.0, 0.0, 0.0, _KERBIN_RADIUS)
        expected = math.radians(1.0) * _KERBIN_RADIUS
        assert abs(north) < 0.1
        assert abs(east - expected) < 0.1

    def test_east_displacement_at_60_degrees_latitude(self) -> None:
        """1 degree east at 60N should be half of 1 degree at equator (cos(60)=0.5)."""
        north, east = _lat_lon_to_meters(60.0, 1.0, 60.0, 0.0, _KERBIN_RADIUS)
        expected = math.radians(1.0) * _KERBIN_RADIUS * 0.5
        assert abs(north) < 0.1
        assert abs(east - expected) < 0.1

    def test_roundtrip_north(self) -> None:
        """Converting 50m north to lat and back should give ~50m."""
        delta_lat = _meters_to_lat(50.0)
        north, east = _lat_lon_to_meters(delta_lat, 0.0, 0.0, 0.0, _KERBIN_RADIUS)
        assert abs(north - 50.0) < 0.01

    def test_roundtrip_east(self) -> None:
        """Converting 50m east to lon and back should give ~50m."""
        delta_lon = _meters_to_lon(50.0)
        north, east = _lat_lon_to_meters(0.0, delta_lon, 0.0, 0.0, _KERBIN_RADIUS)
        assert abs(east - 50.0) < 0.01


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
    """Tests for the translation controller logic."""

    # Starting lat/lon for all tests (equator, prime meridian)
    _START_LAT = 0.0
    _START_LON = 0.0

    def _default_params(self, **overrides: float) -> dict[str, float]:
        params: dict[str, float] = {
            "distance_north": 0.0,
            "distance_east": 0.0,
            "max_speed": 10.0,
        }
        params.update(overrides)
        return params

    def _make_started_action(
        self,
        distance_north: float = 100.0,
        distance_east: float = 0.0,
        max_speed: float = 10.0,
        initial_altitude: float = 100.0,
        heading: float = 0.0,
    ) -> TranslateAction:
        action = TranslateAction()
        state = VesselState(
            altitude_surface=initial_altitude,
            heading=heading,
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
        surface_speed: float = 0.0,
    ) -> VesselState:
        """Create a VesselState displaced from the start position by the given meters."""
        return VesselState(
            altitude_surface=altitude,
            heading=heading,
            surface_speed=surface_speed,
            latitude=self._START_LAT + _meters_to_lat(north_meters),
            longitude=self._START_LON + _meters_to_lon(east_meters, self._START_LAT),
            body_radius=_KERBIN_RADIUS,
        )

    # --- Altitude hold ---

    def test_maintains_altitude_throttle_at_target(self) -> None:
        """At target altitude with zero vertical speed, throttle should be ~0.5."""
        action = self._make_started_action(initial_altitude=100.0)
        state = self._state_at_offset(altitude=100.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle is not None
        assert abs(controls.throttle - 0.5) < 0.01

    def test_below_target_altitude_increases_throttle(self) -> None:
        """If vessel drops below starting altitude, throttle should increase."""
        action = self._make_started_action(initial_altitude=100.0)
        state = self._state_at_offset(altitude=80.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle is not None
        assert controls.throttle > 0.5

    def test_above_target_altitude_decreases_throttle(self) -> None:
        """If vessel rises above starting altitude, throttle should decrease."""
        action = self._make_started_action(initial_altitude=100.0)
        state = self._state_at_offset(altitude=120.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.throttle is not None
        assert controls.throttle < 0.5

    # --- SAS and RCS ---

    def test_sas_enabled_radial_mode(self) -> None:
        action = self._make_started_action()
        state = self._state_at_offset(altitude=100.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.sas is True
        assert controls.rcs is True

    # --- Horizontal translation: heading=0 (facing north) ---

    def test_north_translation_facing_north_sets_forward(self) -> None:
        """Moving north while facing north should use translate_forward > 0."""
        action = self._make_started_action(distance_north=100.0, distance_east=0.0)
        state = self._state_at_offset(altitude=100.0, heading=0.0)
        controls = VesselCommands()
        result = action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.translate_forward is not None
        assert controls.translate_forward > 0.0
        assert result.status == ActionStatus.RUNNING

    def test_south_translation_facing_north_sets_backward(self) -> None:
        """Moving south while facing north should use translate_forward < 0."""
        action = self._make_started_action(distance_north=-100.0, distance_east=0.0)
        state = self._state_at_offset(altitude=100.0, heading=0.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.translate_forward is not None
        assert controls.translate_forward < 0.0

    def test_east_translation_facing_north_sets_right(self) -> None:
        """Moving east while facing north should use translate_right > 0."""
        action = self._make_started_action(distance_north=0.0, distance_east=100.0)
        state = self._state_at_offset(altitude=100.0, heading=0.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.translate_right is not None
        assert controls.translate_right > 0.0

    def test_west_translation_facing_north_sets_left(self) -> None:
        """Moving west while facing north should use translate_right < 0."""
        action = self._make_started_action(distance_north=0.0, distance_east=-100.0)
        state = self._state_at_offset(altitude=100.0, heading=0.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.translate_right is not None
        assert controls.translate_right < 0.0

    # --- Heading-relative decomposition ---

    def test_north_translation_facing_east_sets_left(self) -> None:
        """Moving north while facing east (heading=90) should use translate_right < 0."""
        action = self._make_started_action(distance_north=100.0, distance_east=0.0)
        state = self._state_at_offset(altitude=100.0, heading=90.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.translate_right is not None
        assert controls.translate_right < 0.0

    def test_east_translation_facing_east_sets_forward(self) -> None:
        """Moving east while facing east (heading=90) should use translate_forward > 0."""
        action = self._make_started_action(distance_north=0.0, distance_east=100.0)
        state = self._state_at_offset(altitude=100.0, heading=90.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.translate_forward is not None
        assert controls.translate_forward > 0.0

    # --- RCS clamping ---

    def test_translate_forward_clamped(self) -> None:
        """RCS commands should be clamped to [-1, 1]."""
        action = self._make_started_action(distance_north=10000.0)
        state = self._state_at_offset(altitude=100.0, heading=0.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.translate_forward is not None
        assert -1.0 <= controls.translate_forward <= 1.0

    def test_translate_right_clamped(self) -> None:
        """RCS commands should be clamped to [-1, 1]."""
        action = self._make_started_action(distance_east=10000.0)
        state = self._state_at_offset(altitude=100.0, heading=0.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.translate_right is not None
        assert -1.0 <= controls.translate_right <= 1.0

    # --- Completion ---

    def test_succeeds_when_target_reached_and_slow(self) -> None:
        """Should succeed when vessel is within 2m of target and moving slowly."""
        action = self._make_started_action(distance_north=50.0)
        # Vessel has moved 49m north (within 2m threshold), moving slowly
        state = self._state_at_offset(
            north_meters=49.0, altitude=100.0, heading=0.0, surface_speed=0.5
        )
        controls = VesselCommands()
        result = action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_does_not_succeed_when_still_far(self) -> None:
        """Should keep running when far from target."""
        action = self._make_started_action(distance_north=100.0)
        state = self._state_at_offset(altitude=100.0, heading=0.0, surface_speed=0.0)
        controls = VesselCommands()
        result = action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.RUNNING

    def test_does_not_succeed_when_close_but_fast(self) -> None:
        """Should keep running when near target but still moving fast."""
        action = self._make_started_action(distance_north=50.0)
        # Within 2m but moving at 5 m/s (above 1 m/s threshold)
        state = self._state_at_offset(
            north_meters=49.0, altitude=100.0, heading=0.0, surface_speed=5.0
        )
        controls = VesselCommands()
        result = action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.RUNNING

    # --- Deceleration ---

    def test_decelerates_when_close_to_target(self) -> None:
        """RCS input should be smaller when close to target than when far."""
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
        assert abs(controls_far.translate_forward) > abs(controls_close.translate_forward)

    # --- Zero distance ---

    def test_zero_distance_succeeds_immediately(self) -> None:
        """If both distances are 0, should succeed on first tick."""
        action = self._make_started_action(distance_north=0.0, distance_east=0.0)
        state = self._state_at_offset(altitude=100.0, heading=0.0, surface_speed=0.0)
        controls = VesselCommands()
        result = action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED


class TestTranslateActionStop:
    """Tests for TranslateAction cleanup on stop."""

    def _default_params(self) -> dict[str, float]:
        return {"distance_north": 100.0, "distance_east": 0.0, "max_speed": 10.0}

    def test_stop_kills_throttle(self) -> None:
        action = TranslateAction()
        state = VesselState(altitude_surface=100.0)
        action.start(state, self._default_params())
        controls = VesselCommands()
        action.stop(state, controls, log=ActionLogger())
        assert controls.throttle == 0.0

    def test_stop_disables_sas(self) -> None:
        action = TranslateAction()
        state = VesselState(altitude_surface=100.0)
        action.start(state, self._default_params())
        controls = VesselCommands()
        action.stop(state, controls, log=ActionLogger())
        assert controls.sas is False

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
        assert controls.translate_right == 0.0
