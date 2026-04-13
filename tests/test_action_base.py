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
        assert state.dynamic_pressure == 0.0
        assert state.static_pressure == 0.0
        assert state.drag == 0.0
        assert state.lift == 0.0
        assert state.g_force == 0.0
        assert state.time_to_apoapsis == 0.0
        assert state.time_to_periapsis == 0.0
        assert state.mass == 0.0
        assert state.dry_mass == 0.0
        assert state.available_thrust == 0.0
        assert state.max_thrust == 0.0
        assert state.specific_impulse == 0.0
        assert state.surface_gravity == 9.81
        assert state.body_has_atmosphere is True
        assert state.body_atmosphere_depth == 70000.0
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


class TestVesselStateDerived:
    """Tests for derived @property methods on VesselState."""

    def test_twr_normal(self) -> None:
        state = VesselState(available_thrust=50000.0, mass=5000.0, surface_gravity=9.81)
        expected = 50000.0 / (5000.0 * 9.81)
        assert abs(state.twr - expected) < 0.001

    def test_twr_zero_mass(self) -> None:
        state = VesselState(available_thrust=50000.0, mass=0.0, surface_gravity=9.81)
        assert state.twr == 0.0

    def test_twr_zero_gravity(self) -> None:
        state = VesselState(available_thrust=50000.0, mass=5000.0, surface_gravity=0.0)
        assert state.twr == 0.0

    def test_max_twr(self) -> None:
        state = VesselState(max_thrust=60000.0, mass=5000.0, surface_gravity=9.81)
        expected = 60000.0 / (5000.0 * 9.81)
        assert abs(state.max_twr - expected) < 0.001

    def test_delta_v_normal(self) -> None:
        state = VesselState(specific_impulse=320.0, mass=5000.0, dry_mass=2000.0)
        expected = 320.0 * 9.80665 * math.log(5000.0 / 2000.0)
        assert abs(state.delta_v - expected) < 0.01

    def test_delta_v_no_engines(self) -> None:
        state = VesselState(specific_impulse=0.0, mass=5000.0, dry_mass=2000.0)
        assert state.delta_v == 0.0

    def test_delta_v_no_fuel(self) -> None:
        state = VesselState(specific_impulse=320.0, mass=2000.0, dry_mass=2000.0)
        assert state.delta_v == 0.0

    def test_delta_v_zero_dry_mass(self) -> None:
        state = VesselState(specific_impulse=320.0, mass=5000.0, dry_mass=0.0)
        assert state.delta_v == 0.0

    def test_fuel_fraction_normal(self) -> None:
        state = VesselState(mass=5000.0, dry_mass=2000.0)
        assert abs(state.fuel_fraction - 0.6) < 0.001

    def test_fuel_fraction_no_fuel(self) -> None:
        state = VesselState(mass=2000.0, dry_mass=2000.0)
        assert state.fuel_fraction == 0.0

    def test_fuel_fraction_zero_mass(self) -> None:
        state = VesselState(mass=0.0, dry_mass=0.0)
        assert state.fuel_fraction == 0.0

    def test_time_to_impact_descending(self) -> None:
        state = VesselState(altitude_surface=100.0, vertical_speed=-10.0)
        assert abs(state.time_to_impact - 10.0) < 0.001

    def test_time_to_impact_ascending(self) -> None:
        state = VesselState(altitude_surface=100.0, vertical_speed=5.0)
        assert state.time_to_impact == float("inf")

    def test_time_to_impact_hovering(self) -> None:
        state = VesselState(altitude_surface=100.0, vertical_speed=0.0)
        assert state.time_to_impact == float("inf")

    def test_time_to_impact_on_ground(self) -> None:
        state = VesselState(altitude_surface=0.0, vertical_speed=-2.0)
        assert state.time_to_impact == float("inf")

    def test_in_atmosphere(self) -> None:
        assert VesselState(static_pressure=101325.0).in_atmosphere is True
        assert VesselState(static_pressure=0.0).in_atmosphere is False

    def test_above_atmosphere_in_space(self) -> None:
        state = VesselState(
            altitude_sea=80000.0, body_has_atmosphere=True, body_atmosphere_depth=70000.0
        )
        assert state.above_atmosphere is True

    def test_above_atmosphere_inside(self) -> None:
        state = VesselState(
            altitude_sea=50000.0, body_has_atmosphere=True, body_atmosphere_depth=70000.0
        )
        assert state.above_atmosphere is False

    def test_above_atmosphere_no_atmosphere_body(self) -> None:
        state = VesselState(altitude_sea=100.0, body_has_atmosphere=False)
        assert state.above_atmosphere is True

    def test_has_atmosphere_true(self) -> None:
        state = VesselState(static_pressure=101325.0)
        assert state.has_atmosphere is True

    def test_has_atmosphere_false_in_vacuum(self) -> None:
        state = VesselState(static_pressure=0.0)
        assert state.has_atmosphere is False

    def test_is_suborbital(self) -> None:
        assert VesselState(situation=VesselSituation.SUB_ORBITAL).is_suborbital is True
        assert VesselState(situation=VesselSituation.FLYING).is_suborbital is False
        assert VesselState(situation=VesselSituation.ORBITING).is_suborbital is False

    def test_is_landed(self) -> None:
        assert VesselState(situation=VesselSituation.LANDED).is_landed is True
        assert VesselState(situation=VesselSituation.SPLASHED).is_landed is True
        assert VesselState(situation=VesselSituation.FLYING).is_landed is False
        assert VesselState(situation=VesselSituation.ORBITING).is_landed is False

    def test_is_flying(self) -> None:
        assert VesselState(situation=VesselSituation.FLYING).is_flying is True
        assert VesselState(situation=VesselSituation.SUB_ORBITAL).is_flying is True
        assert VesselState(situation=VesselSituation.ORBITING).is_flying is False
        assert VesselState(situation=VesselSituation.LANDED).is_flying is False

    def test_is_orbiting(self) -> None:
        assert VesselState(situation=VesselSituation.ORBITING).is_orbiting is True
        assert VesselState(situation=VesselSituation.ESCAPING).is_orbiting is True
        assert VesselState(situation=VesselSituation.FLYING).is_orbiting is False
        assert VesselState(situation=VesselSituation.LANDED).is_orbiting is False

    def test_is_ascending(self) -> None:
        assert VesselState(vertical_speed=5.0).is_ascending is True
        assert VesselState(vertical_speed=-5.0).is_ascending is False
        assert VesselState(vertical_speed=0.0).is_ascending is False

    def test_is_descending(self) -> None:
        assert VesselState(vertical_speed=-5.0).is_descending is True
        assert VesselState(vertical_speed=5.0).is_descending is False
        assert VesselState(vertical_speed=0.0).is_descending is False


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
