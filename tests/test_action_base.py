"""Tests for the action execution system core types."""

from __future__ import annotations

import math

import pytest

from ksp_mission_control.control.actions.base import (
    ActionParam,
    ActionResult,
    ActionStatus,
    AutopilotConfig,
    AutopilotDirection,
    ParamType,
    ReferenceFrame,
    SpeedMode,
    VesselCommands,
    VesselSituation,
    VesselState,
)


class TestActionStatus:
    """Tests for the ActionStatus enum."""

    def test_has_expected_members(self) -> None:
        assert ActionStatus.PENDING.value == "pending"
        assert ActionStatus.RUNNING.value == "running"
        assert ActionStatus.SUCCEEDED.value == "succeeded"
        assert ActionStatus.FAILED.value == "failed"


class TestParamType:
    """Tests for the ParamType enum."""

    def test_has_expected_members(self) -> None:
        assert ParamType.FLOAT.value == "float"
        assert ParamType.BOOL.value == "bool"
        assert ParamType.STR.value == "str"


class TestActionResult:
    """Tests for the ActionResult frozen dataclass."""

    def test_construction_with_status_only(self) -> None:
        result = ActionResult(status=ActionStatus.RUNNING)
        assert result.status == ActionStatus.RUNNING
        assert result.message == ""

    def test_construction_with_message(self) -> None:
        result = ActionResult(status=ActionStatus.FAILED, message="Engine flameout")
        assert result.status == ActionStatus.FAILED
        assert result.message == "Engine flameout"

    def test_is_frozen(self) -> None:
        result = ActionResult(status=ActionStatus.RUNNING)
        with pytest.raises(AttributeError):
            result.status = ActionStatus.FAILED  # type: ignore[misc]


class TestActionParam:
    """Tests for the ActionParam typed parameter descriptor."""

    def test_required_param_without_default(self) -> None:
        param = ActionParam(
            param_id="target_altitude",
            label="Target Altitude",
            description="Altitude to hold",
            required=True,
        )
        assert param.param_id == "target_altitude"
        assert param.required is True
        assert param.default is None
        assert param.unit == ""

    def test_optional_param_with_default(self) -> None:
        param = ActionParam(
            param_id="target_altitude",
            label="Target Altitude",
            description="Altitude to hold",
            required=False,
            default=100.0,
            unit="m",
        )
        assert param.required is False
        assert param.default == 100.0
        assert param.unit == "m"

    def test_is_frozen(self) -> None:
        param = ActionParam(param_id="x", label="X", description="x", required=True)
        with pytest.raises(AttributeError):
            param.param_id = "y"  # type: ignore[misc]


class TestVesselState:
    """Tests for the VesselState frozen dataclass."""

    def test_defaults_to_zeros_and_empty_strings(self) -> None:
        state = VesselState()
        assert state.altitude_sea == 0.0
        assert state.altitude_surface == 0.0
        assert state.vertical_speed == 0.0
        assert state.surface_speed == 0.0
        assert state.orbital_speed == 0.0
        assert state.apoapsis == 0.0
        assert state.periapsis == 0.0
        assert state.met == 0.0
        assert state.vessel_name == ""
        assert state.situation == VesselSituation.PRE_LAUNCH
        assert state.body == ""
        assert state.latitude == 0.0
        assert state.longitude == 0.0
        assert state.inclination == 0.0
        assert state.eccentricity == 0.0
        assert state.period == 0.0
        assert state.pitch == 0.0
        assert state.heading == 0.0
        assert state.roll == 0.0
        assert state.autopilot_error == 0.0
        assert state.autopilot_pitch_error == 0.0
        assert state.autopilot_heading_error == 0.0
        assert state.autopilot_roll_error == 0.0
        assert state.throttle == 0.0
        assert state.sas is False
        assert state.speed_mode == SpeedMode.ORBIT
        assert state.rcs is False
        assert state.current_stage == 0
        assert state.max_stages == 0
        assert state.electric_charge == 0.0
        assert state.liquid_fuel == 0.0
        assert state.oxidizer == 0.0
        assert state.mono_propellant == 0.0

    def test_autopilot_error_partial_construction(self) -> None:
        state = VesselState(autopilot_error=5.2, autopilot_heading_error=-3.1)
        assert state.autopilot_error == 5.2
        assert state.autopilot_heading_error == -3.1
        assert state.autopilot_pitch_error == 0.0  # default
        assert state.autopilot_roll_error == 0.0  # default

    def test_partial_construction(self) -> None:
        state = VesselState(altitude_surface=50.0, vertical_speed=-2.5)
        assert state.altitude_surface == 50.0
        assert state.vertical_speed == -2.5
        assert state.altitude_sea == 0.0  # default

    def test_is_frozen(self) -> None:
        state = VesselState()
        with pytest.raises(AttributeError):
            state.altitude_sea = 100.0  # type: ignore[misc]


class TestVesselCommands:
    """Tests for the VesselCommands mutable command buffer."""

    def test_defaults_to_none(self) -> None:
        controls = VesselCommands()
        assert controls.throttle is None
        assert controls.autopilot is None
        assert controls.autopilot_pitch is None
        assert controls.autopilot_heading is None
        assert controls.autopilot_roll is None
        assert controls.autopilot_direction is None
        assert controls.autopilot_config is None
        assert controls.sas is None
        assert controls.rcs is None
        assert controls.stage is None

    def test_mutation(self) -> None:
        controls = VesselCommands()
        controls.throttle = 0.8
        controls.sas = True
        assert controls.throttle == 0.8
        assert controls.sas is True
        assert controls.autopilot_pitch is None  # untouched

    def test_autopilot_direction_mutation(self) -> None:
        controls = VesselCommands()
        controls.autopilot_direction = AutopilotDirection(
            vector=(1.0, 0.0, 0.0),
            reference_frame=ReferenceFrame.VESSEL_ORBITAL,
        )
        assert controls.autopilot_direction is not None
        assert controls.autopilot_direction.vector == (1.0, 0.0, 0.0)
        assert controls.autopilot_direction.reference_frame == ReferenceFrame.VESSEL_ORBITAL

    def test_autopilot_config_mutation(self) -> None:
        controls = VesselCommands()
        controls.autopilot_config = AutopilotConfig(time_to_peak=(1.0, 1.0, 1.0))
        assert controls.autopilot_config is not None
        assert controls.autopilot_config.auto_tune is True
        assert controls.autopilot_config.time_to_peak == (1.0, 1.0, 1.0)

    def test_autopilot_roll_with_nan(self) -> None:
        controls = VesselCommands()
        controls.autopilot_roll = float("nan")
        assert math.isnan(controls.autopilot_roll)


class TestReferenceFrame:
    """Tests for the ReferenceFrame enum."""

    def test_has_expected_members(self) -> None:
        assert ReferenceFrame.VESSEL_SURFACE.value == "vessel_surface"
        assert ReferenceFrame.VESSEL_ORBITAL.value == "vessel_orbital"
        assert ReferenceFrame.VESSEL.value == "vessel"
        assert ReferenceFrame.BODY.value == "body"
        assert ReferenceFrame.BODY_NON_ROTATING.value == "body_non_rotating"

    def test_display_name(self) -> None:
        assert ReferenceFrame.VESSEL_SURFACE.display_name == "Vessel Surface"
        assert ReferenceFrame.BODY_NON_ROTATING.display_name == "Body Non Rotating"


class TestAutopilotDirection:
    """Tests for the AutopilotDirection frozen dataclass."""

    def test_construction(self) -> None:
        direction = AutopilotDirection(
            vector=(0.0, 1.0, 0.0),
            reference_frame=ReferenceFrame.VESSEL_SURFACE,
        )
        assert direction.vector == (0.0, 1.0, 0.0)
        assert direction.reference_frame == ReferenceFrame.VESSEL_SURFACE

    def test_is_frozen(self) -> None:
        direction = AutopilotDirection(
            vector=(1.0, 0.0, 0.0),
            reference_frame=ReferenceFrame.BODY,
        )
        with pytest.raises(AttributeError):
            direction.vector = (0.0, 0.0, 1.0)  # type: ignore[misc]

    def test_equality(self) -> None:
        direction_a = AutopilotDirection(
            vector=(1.0, 0.0, 0.0), reference_frame=ReferenceFrame.VESSEL_ORBITAL
        )
        direction_b = AutopilotDirection(
            vector=(1.0, 0.0, 0.0), reference_frame=ReferenceFrame.VESSEL_ORBITAL
        )
        direction_c = AutopilotDirection(
            vector=(0.0, 1.0, 0.0), reference_frame=ReferenceFrame.VESSEL_ORBITAL
        )
        assert direction_a == direction_b
        assert direction_a != direction_c


class TestAutopilotConfig:
    """Tests for the AutopilotConfig frozen dataclass."""

    def test_defaults_are_krpc_defaults(self) -> None:
        cfg = AutopilotConfig()
        assert cfg.auto_tune is True
        assert cfg.time_to_peak == (3.0, 3.0, 3.0)
        assert cfg.overshoot == (0.01, 0.01, 0.01)
        assert cfg.stopping_time == (0.5, 0.5, 0.5)
        assert cfg.deceleration_time == (5.0, 5.0, 5.0)
        assert cfg.attenuation_angle == (1.0, 1.0, 1.0)
        assert cfg.roll_threshold == 5.0
        assert cfg.pitch_pid_gains is None
        assert cfg.yaw_pid_gains is None
        assert cfg.roll_pid_gains is None

    def test_auto_constant_equals_default(self) -> None:
        assert AutopilotConfig() == AutopilotConfig.AUTO
        assert AutopilotConfig.AUTO.auto_tune is True

    def test_manual_config(self) -> None:
        cfg = AutopilotConfig(
            auto_tune=False,
            pitch_pid_gains=(2.0, 0.0, 0.5),
            yaw_pid_gains=(2.0, 0.0, 0.5),
            roll_pid_gains=(1.0, 0.0, 0.3),
        )
        assert cfg.auto_tune is False
        assert cfg.pitch_pid_gains == (2.0, 0.0, 0.5)
        assert cfg.yaw_pid_gains == (2.0, 0.0, 0.5)
        assert cfg.roll_pid_gains == (1.0, 0.0, 0.3)

    def test_auto_tune_with_custom_targets(self) -> None:
        cfg = AutopilotConfig(time_to_peak=(1.0, 1.0, 1.0), overshoot=(0.05, 0.05, 0.05))
        assert cfg.auto_tune is True
        assert cfg.time_to_peak == (1.0, 1.0, 1.0)
        assert cfg.overshoot == (0.05, 0.05, 0.05)

    def test_is_frozen(self) -> None:
        cfg = AutopilotConfig()
        with pytest.raises(AttributeError):
            cfg.auto_tune = False  # type: ignore[misc]

    def test_equality(self) -> None:
        assert AutopilotConfig() == AutopilotConfig()
        assert AutopilotConfig() != AutopilotConfig(auto_tune=False)
