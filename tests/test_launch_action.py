"""Tests for LaunchAction."""

from __future__ import annotations

import math

import pytest

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionStatus,
    PartInfo,
    Parts,
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

    def _start(self, latitude: float = -0.1, staging_mode: str | None = None) -> LaunchAction:
        action = LaunchAction()
        action.start(
            self._make_state(latitude),
            {
                "target_altitude": None,
                "target_inclination": None,
                "turn_start_altitude": None,
                "final_pitch": None,
                "turn_exponent": None,
                "staging_mode": staging_mode,
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


class TestLaunchActionStaging:
    """staging_mode delegates to the auto_stage helper; without it the action fails on thrust loss."""

    def _make_state(
        self,
        thrust_available: float = 0.0,
        engine_states: tuple[str, ...] = ("inactive",),
        stage_current: int = 3,
    ) -> State:
        return State(
            position_latitude=0.0,
            orbit_inclination=0.0,
            altitude_sea=75.0,
            altitude_surface=75.0,
            body_has_atmosphere=True,
            body_atmosphere_depth=70_000.0,
            thrust_available=thrust_available,
            stage_current=stage_current,
            parts=Parts(engines=tuple(PartInfo(stage=0, state=s) for s in engine_states)),
        )

    def _start(self, staging_mode: str | None) -> LaunchAction:
        action = LaunchAction()
        action.start(
            self._make_state(thrust_available=100.0, engine_states=()),
            {
                "target_altitude": None,
                "target_inclination": None,
                "turn_start_altitude": None,
                "final_pitch": None,
                "turn_exponent": None,
                "staging_mode": staging_mode,
            },
        )
        return action

    def test_no_thrust_fails_without_staging_mode(self) -> None:
        action = self._start(staging_mode=None)
        result = action.tick(self._make_state(thrust_available=0.0), VesselCommands(), 0.5, ActionLogger())
        assert result.status == ActionStatus.FAILED

    def test_no_thrust_stages_when_inactive_engines_available(self) -> None:
        action = self._start(staging_mode="full_depletion")
        commands = VesselCommands()
        result = action.tick(
            self._make_state(thrust_available=0.0, engine_states=("flameout", "inactive")),
            commands,
            0.5,
            ActionLogger(),
        )
        assert result.status == ActionStatus.RUNNING
        assert commands.stage is True

    def test_no_thrust_fails_when_no_inactive_engines(self) -> None:
        action = self._start(staging_mode="full_depletion")
        result = action.tick(
            self._make_state(thrust_available=0.0, engine_states=("flameout", "flameout")),
            VesselCommands(),
            0.5,
            ActionLogger(),
        )
        assert result.status == ActionStatus.FAILED

    def test_any_flameout_stages_while_thrust_still_available(self) -> None:
        """ANY_FLAMEOUT drops a spent corner booster mid-burn even when the inner stack still thrusts."""
        action = self._start(staging_mode="any_flameout")
        commands = VesselCommands()
        result = action.tick(
            self._make_state(thrust_available=80_000.0, engine_states=("active", "flameout")),
            commands,
            0.5,
            ActionLogger(),
        )
        assert result.status == ActionStatus.RUNNING
        assert commands.stage is True

    def test_full_depletion_does_not_stage_on_partial_flameout(self) -> None:
        """FULL_DEPLETION holds back while any thrust remains."""
        action = self._start(staging_mode="full_depletion")
        commands = VesselCommands()
        result = action.tick(
            self._make_state(thrust_available=80_000.0, engine_states=("active", "flameout")),
            commands,
            0.5,
            ActionLogger(),
        )
        # Either RUNNING with no stage commanded, or normal flight continues; key invariant: no staging.
        assert commands.stage is None
        assert result.status == ActionStatus.RUNNING

    def test_invalid_staging_mode_string_raises(self) -> None:
        action = LaunchAction()
        with pytest.raises(ValueError, match="Unknown staging_mode"):
            action.start(
                self._make_state(thrust_available=100.0, engine_states=()),
                {
                    "target_altitude": None,
                    "target_inclination": None,
                    "turn_start_altitude": None,
                    "final_pitch": None,
                    "turn_exponent": None,
                    "staging_mode": "bogus",
                },
            )


class TestLaunchActionTurnExponent:
    """turn_exponent reshapes the gravity-turn pitch curve; 1.0 is the original cosine curve."""

    def _pitch_at(self, turn_exponent: float | None, apoapsis: float, target: float = 75_000.0) -> float:
        """Start a launch with the given turn_exponent and return the commanded pitch at ``apoapsis``."""
        action = LaunchAction()
        start_state = State(
            position_latitude=0.0,
            orbit_inclination=0.0,
            altitude_sea=75.0,
            altitude_surface=75.0,
            body_has_atmosphere=True,
            body_atmosphere_depth=70_000.0,
            thrust_available=100.0,
        )
        action.start(
            start_state,
            {
                "target_altitude": target,
                "target_inclination": None,
                "turn_start_altitude": None,
                "final_pitch": None,
                "turn_exponent": turn_exponent,
                "staging_mode": None,
            },
        )
        # altitude_sea well past turn_start so we are in the turn phase, apoapsis below target so RUNNING.
        tick_state = State(
            position_latitude=0.0,
            orbit_inclination=0.0,
            altitude_sea=10_000.0,
            altitude_surface=10_000.0,
            orbit_apoapsis=apoapsis,
            body_has_atmosphere=True,
            body_atmosphere_depth=70_000.0,
            thrust_available=100.0,
        )
        commands = VesselCommands()
        result = action.tick(tick_state, commands, 0.5, ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert commands.autopilot_pitch is not None
        return commands.autopilot_pitch

    def test_param_is_optional_with_default(self) -> None:
        param = next(p for p in LaunchAction.params if p.param_id == "turn_exponent")
        assert param.required is False
        assert param.default == 0.7
        assert param.unit == ""

    def test_exponent_one_matches_original_cosine_curve(self) -> None:
        # exponent 1.0 with final_pitch 0 -> pitch = cos(progress * 90). At 50% progress that is cos(45) * 90.
        pitch = self._pitch_at(1.0, apoapsis=37_500.0)
        assert math.isclose(pitch, math.cos(math.radians(45.0)) * 90.0, rel_tol=1e-6)

    def test_none_resolves_to_default(self) -> None:
        # Omitting the value (None) falls back to the action default, not 1.0.
        assert math.isclose(self._pitch_at(None, 37_500.0), self._pitch_at(0.7, 37_500.0), rel_tol=1e-9)

    def test_lower_exponent_turns_shallower(self) -> None:
        # A more aggressive turn commands a lower pitch (closer to horizon) mid-ascent.
        assert self._pitch_at(0.5, 37_500.0) < self._pitch_at(1.0, 37_500.0)

    def test_higher_exponent_stays_steeper(self) -> None:
        assert self._pitch_at(2.0, 37_500.0) > self._pitch_at(1.0, 37_500.0)

    def test_vertical_start_unaffected_by_exponent(self) -> None:
        # At zero apoapsis progress the pitch is straight up regardless of exponent.
        assert math.isclose(self._pitch_at(0.3, 0.0), 90.0, abs_tol=1e-6)
        assert math.isclose(self._pitch_at(2.0, 0.0), 90.0, abs_tol=1e-6)

    def test_non_positive_exponent_raises(self) -> None:
        for bad in (0.0, -1.0):
            with pytest.raises(ValueError, match="turn_exponent"):
                self._pitch_at(bad, 37_500.0)
