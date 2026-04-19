"""Tests for the TranslateAction multi-axis RCS controller."""

from __future__ import annotations

import math

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionStatus,
    SASMode,
    VesselCommands,
    VesselState,
)
from ksp_mission_control.control.actions.translate.action import (
    TranslateAction,
    _lat_lon_to_meters,
    _world_to_vessel,
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


class TestWorldToVessel:
    """Tests for world-space to vessel body-axis projection.

    Returns positive values when the world vector aligns with the positive
    body direction. No kRPC-specific inversions are applied here.
    """

    # --- Level vessel (roll=0, pitch=0): degenerates to heading-only rotation ---

    def test_heading_north_forward_is_north(self) -> None:
        """Facing north, level: north component maps to forward."""
        fwd, right, up = _world_to_vessel(10.0, 0.0, 0.0, 0.0, 0.0)
        assert abs(fwd - 10.0) < 0.01
        assert abs(right) < 0.01
        assert abs(up) < 0.01

    def test_heading_north_east_is_right(self) -> None:
        """Facing north, level: east component maps to right."""
        fwd, right, up = _world_to_vessel(0.0, 10.0, 0.0, 0.0, 0.0)
        assert abs(fwd) < 0.01
        assert abs(right - 10.0) < 0.01
        assert abs(up) < 0.01

    def test_heading_east_north_is_negative_right(self) -> None:
        """Facing east, level: north component maps to negative right (left)."""
        fwd, right, up = _world_to_vessel(10.0, 0.0, 90.0, 0.0, 0.0)
        assert abs(fwd) < 0.01
        assert abs(right - (-10.0)) < 0.01
        assert abs(up) < 0.01

    def test_heading_east_east_is_forward(self) -> None:
        """Facing east, level: east component maps to forward."""
        fwd, right, up = _world_to_vessel(0.0, 10.0, 90.0, 0.0, 0.0)
        assert abs(fwd - 10.0) < 0.01
        assert abs(right) < 0.01

    def test_heading_south_north_is_backward(self) -> None:
        """Facing south, level: north component maps to backward (negative forward)."""
        fwd, right, up = _world_to_vessel(10.0, 0.0, 180.0, 0.0, 0.0)
        assert abs(fwd - (-10.0)) < 0.01
        assert abs(right) < 0.01

    def test_heading_west_east_is_backward(self) -> None:
        """Facing west, level: east maps to backward."""
        fwd, right, up = _world_to_vessel(0.0, 10.0, 270.0, 0.0, 0.0)
        assert abs(fwd - (-10.0)) < 0.01
        assert abs(right) < 0.01

    # --- Rolled vessel (roll=-90): body right is vertical, body up is horizontal ---

    def test_roll_minus90_north_maps_to_up(self) -> None:
        """Facing west, roll=-90, pitch=0: north maps entirely to body up."""
        fwd, right, up = _world_to_vessel(10.0, 0.0, 270.0, 0.0, -90.0)
        assert abs(fwd) < 0.01
        assert abs(right) < 0.01
        assert abs(up - 10.0) < 0.01

    def test_roll_minus90_east_maps_to_backward(self) -> None:
        """Facing west, roll=-90, pitch=0: east maps to backward (negative forward)."""
        fwd, right, up = _world_to_vessel(0.0, 10.0, 270.0, 0.0, -90.0)
        assert abs(fwd - (-10.0)) < 0.01
        assert abs(right) < 0.01
        assert abs(up) < 0.01

    def test_roll_minus90_with_pitch_north_maps_mostly_to_up(self) -> None:
        """Facing west, roll=-90, pitch=15: north maps mostly to body up."""
        fwd, right, up = _world_to_vessel(10.0, 0.0, 270.0, 15.0, -90.0)
        assert abs(up) > 9.0  # Mostly in body up
        assert abs(fwd) < 1.0
        assert abs(right) < 1.0


class TestTranslateActionMetadata:
    """Tests for TranslateAction class-level metadata."""

    def test_action_id(self) -> None:
        assert TranslateAction.action_id == "translate"

    def test_label(self) -> None:
        assert TranslateAction.label == "Translate"

    def test_has_distance_north_param(self) -> None:
        param_ids = [p.param_id for p in TranslateAction.params]
        assert "distance_north" in param_ids

    def test_has_distance_east_param(self) -> None:
        param_ids = [p.param_id for p in TranslateAction.params]
        assert "distance_east" in param_ids

    def test_has_max_speed_param(self) -> None:
        param_ids = [p.param_id for p in TranslateAction.params]
        assert "max_speed" in param_ids


class TestTranslateActionTick:
    """Tests for the multi-axis RCS translation controller."""

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
    ) -> TranslateAction:
        action = TranslateAction()
        state = VesselState(
            altitude_surface=initial_altitude,
            position_latitude=self._START_LAT,
            position_longitude=self._START_LON,
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
        pitch: float = 0.0,
        roll: float = 0.0,
    ) -> VesselState:
        return VesselState(
            altitude_surface=altitude,
            orientation_heading=heading,
            orientation_pitch=pitch,
            orientation_roll=roll,
            position_latitude=self._START_LAT + _meters_to_lat(north_meters),
            position_longitude=self._START_LON + _meters_to_lon(east_meters, self._START_LAT),
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

    # --- SAS and RCS ---

    def test_sas_radial_and_rcs_enabled(self) -> None:
        action = self._make_started_action()
        state = self._state_at_offset(altitude=100.0, heading=0.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.sas is True
        assert controls.sas_mode == SASMode.RADIAL
        assert controls.rcs is True

    # --- Level vessel (roll=0): forward and right used ---

    def test_north_target_facing_north_level(self) -> None:
        """Target north, facing north, level: positive translate_forward."""
        action = self._make_started_action(distance_north=100.0, distance_east=0.0)
        state = self._state_at_offset(altitude=100.0, heading=0.0, roll=0.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.translate_forward is not None
        assert controls.translate_forward > 0.0
        assert controls.translate_right is not None
        assert abs(controls.translate_right) < 0.01

    def test_east_target_facing_north_level(self) -> None:
        """Target east, facing north, level: positive translate_right."""
        action = self._make_started_action(distance_north=0.0, distance_east=100.0)
        state = self._state_at_offset(altitude=100.0, heading=0.0, roll=0.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.translate_right is not None
        assert controls.translate_right > 0.0
        assert controls.translate_forward is not None
        assert abs(controls.translate_forward) < 0.01

    def test_east_target_facing_east_level(self) -> None:
        """Target east, facing east, level: positive translate_forward."""
        action = self._make_started_action(distance_north=0.0, distance_east=100.0)
        state = self._state_at_offset(altitude=100.0, heading=90.0, roll=0.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.translate_forward is not None
        assert controls.translate_forward > 0.0

    def test_south_target_facing_north_level(self) -> None:
        """Target south, facing north, level: negative translate_forward."""
        action = self._make_started_action(distance_north=-100.0, distance_east=0.0)
        state = self._state_at_offset(altitude=100.0, heading=0.0, roll=0.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.translate_forward is not None
        assert controls.translate_forward < 0.0

    # --- Rolled vessel (roll=-90): translate_up drives horizontal motion ---

    def test_north_target_facing_west_rolled(self) -> None:
        """Target north, heading 270, roll -90: body up = north, so positive translate_up."""
        action = self._make_started_action(distance_north=100.0, distance_east=0.0)
        state = self._state_at_offset(altitude=100.0, heading=270.0, pitch=0.0, roll=-90.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.translate_up is not None
        assert controls.translate_up > 0.0
        assert controls.translate_forward is not None
        assert abs(controls.translate_forward) < 0.01
        assert controls.translate_right is not None
        assert abs(controls.translate_right) < 0.01

    def test_east_target_facing_west_rolled(self) -> None:
        """Target east, heading 270, roll -90: body forward = west, so negative translate_forward."""
        action = self._make_started_action(distance_north=0.0, distance_east=100.0)
        state = self._state_at_offset(altitude=100.0, heading=270.0, pitch=0.0, roll=-90.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.translate_forward is not None
        assert controls.translate_forward < 0.0
        assert controls.translate_up is not None
        assert abs(controls.translate_up) < 0.01

    # --- RCS clamped ---

    def test_translate_forward_clamped(self) -> None:
        action = self._make_started_action(distance_north=10000.0)
        state = self._state_at_offset(altitude=100.0, heading=0.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.translate_forward is not None
        assert -1.0 <= controls.translate_forward <= 1.0

    def test_translate_right_clamped(self) -> None:
        action = self._make_started_action(distance_east=10000.0)
        state = self._state_at_offset(altitude=100.0, heading=0.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.translate_right is not None
        assert -1.0 <= controls.translate_right <= 1.0

    def test_translate_up_clamped(self) -> None:
        action = self._make_started_action(distance_north=10000.0)
        state = self._state_at_offset(altitude=100.0, heading=270.0, roll=-90.0)
        controls = VesselCommands()
        action.tick(state, controls, dt=0.5, log=ActionLogger())
        assert controls.translate_up is not None
        assert -1.0 <= controls.translate_up <= 1.0

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
        assert controls.translate_up == 0.0
