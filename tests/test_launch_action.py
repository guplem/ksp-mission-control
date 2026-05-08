"""Tests for LaunchAction."""

from __future__ import annotations

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionStatus,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.launch.action import (
    LaunchAction,
    _inclination_to_heading,
)


class TestInclinationToHeading:
    def test_equatorial_east(self) -> None:
        assert _inclination_to_heading(0.0) == 90.0

    def test_polar(self) -> None:
        assert abs(_inclination_to_heading(90.0) - 0.0) < 0.001

    def test_negative_inclination_southeast(self) -> None:
        heading = _inclination_to_heading(-5.0)
        assert heading > 90.0


class TestLaunchActionDefaultInclination:
    """When no inclination is given, the default must be reachable from the launch latitude."""

    def _make_state(self, latitude: float = -0.1) -> State:
        return State(
            position_latitude=latitude,
            orbit_inclination=0.0,
            altitude_sea=75.0,
            altitude_surface=75.0,
            body_has_atmosphere=True,
            body_atmosphere_depth=70_000.0,
            thrust_available=100.0,
        )

    def _start(self, latitude: float = -0.1) -> LaunchAction:
        action = LaunchAction()
        action.start(
            self._make_state(latitude),
            {
                "target_altitude": None,
                "target_inclination": None,
                "turn_start_altitude": None,
                "turn_end_altitude": None,
            },
        )
        return action

    def test_no_fail_message_when_no_inclination_given(self) -> None:
        action = self._start(latitude=-0.1)
        assert action._fail_message is None

    def test_default_inclination_equals_abs_latitude(self) -> None:
        action = self._start(latitude=-0.1)
        assert action._target_inclination == 0.1

    def test_default_inclination_positive_latitude(self) -> None:
        action = self._start(latitude=5.0)
        assert action._target_inclination == 5.0

    def test_first_tick_does_not_fail(self) -> None:
        action = self._start(latitude=-0.1)
        commands = VesselCommands()
        log = ActionLogger()
        result = action.tick(self._make_state(latitude=-0.1), commands, 0.5, log)
        assert result.status != ActionStatus.FAILED
