"""Tests for the action execution system core types."""

from __future__ import annotations

import pytest

from ksp_mission_control.control.actions.base import (
    ActionParam,
    ActionResult,
    ActionStatus,
    VesselControls,
    VesselState,
)


class TestActionStatus:
    """Tests for the ActionStatus enum."""

    def test_has_expected_members(self) -> None:
        assert ActionStatus.PENDING.value == "pending"
        assert ActionStatus.RUNNING.value == "running"
        assert ActionStatus.SUCCEEDED.value == "succeeded"
        assert ActionStatus.FAILED.value == "failed"


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
        param = ActionParam(
            param_id="x", label="X", description="x", required=True
        )
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
        assert state.situation == ""
        assert state.body == ""
        assert state.latitude == 0.0
        assert state.longitude == 0.0
        assert state.inclination == 0.0
        assert state.eccentricity == 0.0
        assert state.period == 0.0
        assert state.electric_charge == 0.0
        assert state.liquid_fuel == 0.0
        assert state.oxidizer == 0.0
        assert state.mono_propellant == 0.0

    def test_partial_construction(self) -> None:
        state = VesselState(altitude_surface=50.0, vertical_speed=-2.5)
        assert state.altitude_surface == 50.0
        assert state.vertical_speed == -2.5
        assert state.altitude_sea == 0.0  # default

    def test_is_frozen(self) -> None:
        state = VesselState()
        with pytest.raises(AttributeError):
            state.altitude_sea = 100.0  # type: ignore[misc]


class TestVesselControls:
    """Tests for the VesselControls mutable command buffer."""

    def test_defaults_to_none(self) -> None:
        controls = VesselControls()
        assert controls.throttle is None
        assert controls.pitch is None
        assert controls.heading is None
        assert controls.sas is None
        assert controls.rcs is None
        assert controls.stage is None

    def test_mutation(self) -> None:
        controls = VesselControls()
        controls.throttle = 0.8
        controls.sas = True
        assert controls.throttle == 0.8
        assert controls.sas is True
        assert controls.pitch is None  # untouched
