"""Tests for telemetry alert level evaluation."""

from __future__ import annotations

from ksp_mission_control.control.actions.base import State, VesselSituation
from ksp_mission_control.control.widgets.telemetry_alerts import (
    AlertLevel,
    evaluate_comms_connected,
    evaluate_comms_signal_strength,
    evaluate_dynamic_pressure,
    evaluate_electric_charge,
    evaluate_engine_flameouts,
    evaluate_fuel_fraction,
    evaluate_g_force,
    evaluate_liquid_fuel,
    evaluate_mono_propellant,
    evaluate_oxidizer,
    evaluate_periapsis,
    evaluate_time_to_impact,
    evaluate_twr,
)


class TestAlertLevelEnum:
    def test_severity_ordering(self) -> None:
        assert AlertLevel.NORMAL.value < AlertLevel.WARNING.value < AlertLevel.CRITICAL.value


# --- Resources ---


class TestElectricCharge:
    def test_full_charge_is_normal(self) -> None:
        state = State(resource_electric_charge=80.0, resource_electric_charge_max=100.0)
        assert evaluate_electric_charge(state) == AlertLevel.NORMAL

    def test_low_charge_is_warning(self) -> None:
        state = State(resource_electric_charge=15.0, resource_electric_charge_max=100.0)
        assert evaluate_electric_charge(state) == AlertLevel.WARNING

    def test_critical_charge(self) -> None:
        state = State(resource_electric_charge=3.0, resource_electric_charge_max=100.0)
        assert evaluate_electric_charge(state) == AlertLevel.CRITICAL

    def test_zero_max_is_normal(self) -> None:
        """No electric charge capacity at all (e.g. debris) should not warn."""
        state = State(resource_electric_charge=0.0, resource_electric_charge_max=0.0)
        assert evaluate_electric_charge(state) == AlertLevel.NORMAL


class TestLiquidFuel:
    def test_plenty_fuel_is_normal(self) -> None:
        state = State(resource_liquid_fuel=80.0, resource_liquid_fuel_max=100.0)
        assert evaluate_liquid_fuel(state) == AlertLevel.NORMAL

    def test_low_fuel_is_warning(self) -> None:
        state = State(resource_liquid_fuel=10.0, resource_liquid_fuel_max=100.0)
        assert evaluate_liquid_fuel(state) == AlertLevel.WARNING

    def test_critical_fuel(self) -> None:
        state = State(resource_liquid_fuel=3.0, resource_liquid_fuel_max=100.0)
        assert evaluate_liquid_fuel(state) == AlertLevel.CRITICAL

    def test_zero_max_is_normal(self) -> None:
        state = State(resource_liquid_fuel=0.0, resource_liquid_fuel_max=0.0)
        assert evaluate_liquid_fuel(state) == AlertLevel.NORMAL


class TestOxidizer:
    def test_plenty_is_normal(self) -> None:
        state = State(resource_oxidizer=80.0, resource_oxidizer_max=100.0)
        assert evaluate_oxidizer(state) == AlertLevel.NORMAL

    def test_low_is_warning(self) -> None:
        state = State(resource_oxidizer=10.0, resource_oxidizer_max=100.0)
        assert evaluate_oxidizer(state) == AlertLevel.WARNING

    def test_critical(self) -> None:
        state = State(resource_oxidizer=3.0, resource_oxidizer_max=100.0)
        assert evaluate_oxidizer(state) == AlertLevel.CRITICAL


class TestMonoPropellant:
    def test_plenty_is_normal(self) -> None:
        state = State(resource_mono_propellant=80.0, resource_mono_propellant_max=100.0)
        assert evaluate_mono_propellant(state) == AlertLevel.NORMAL

    def test_low_is_warning(self) -> None:
        state = State(resource_mono_propellant=10.0, resource_mono_propellant_max=100.0)
        assert evaluate_mono_propellant(state) == AlertLevel.WARNING

    def test_critical(self) -> None:
        state = State(resource_mono_propellant=3.0, resource_mono_propellant_max=100.0)
        assert evaluate_mono_propellant(state) == AlertLevel.CRITICAL


# --- Structural / survivability ---


class TestGForce:
    def test_normal_g(self) -> None:
        state = State(g_force=2.0)
        assert evaluate_g_force(state) == AlertLevel.NORMAL

    def test_high_g_warning(self) -> None:
        state = State(g_force=5.0)
        assert evaluate_g_force(state) == AlertLevel.WARNING

    def test_extreme_g_critical(self) -> None:
        state = State(g_force=9.0)
        assert evaluate_g_force(state) == AlertLevel.CRITICAL


class TestDynamicPressure:
    def test_low_pressure_normal(self) -> None:
        state = State(pressure_dynamic=5000.0)  # 5 kPa
        assert evaluate_dynamic_pressure(state) == AlertLevel.NORMAL

    def test_high_pressure_warning(self) -> None:
        state = State(pressure_dynamic=25000.0)  # 25 kPa
        assert evaluate_dynamic_pressure(state) == AlertLevel.WARNING

    def test_extreme_pressure_critical(self) -> None:
        state = State(pressure_dynamic=45000.0)  # 45 kPa
        assert evaluate_dynamic_pressure(state) == AlertLevel.CRITICAL


# --- Flight safety ---


class TestTimeToImpact:
    def test_high_altitude_normal(self) -> None:
        state = State(altitude_surface=5000.0, speed_vertical=-10.0)
        assert evaluate_time_to_impact(state) == AlertLevel.NORMAL

    def test_close_to_ground_warning(self) -> None:
        state = State(altitude_surface=200.0, speed_vertical=-10.0)
        assert evaluate_time_to_impact(state) == AlertLevel.WARNING

    def test_imminent_impact_critical(self) -> None:
        state = State(altitude_surface=50.0, speed_vertical=-10.0)
        assert evaluate_time_to_impact(state) == AlertLevel.CRITICAL

    def test_ascending_is_normal(self) -> None:
        state = State(altitude_surface=50.0, speed_vertical=10.0)
        assert evaluate_time_to_impact(state) == AlertLevel.NORMAL

    def test_landed_is_normal(self) -> None:
        state = State(
            altitude_surface=0.0,
            speed_vertical=0.0,
            situation=VesselSituation.LANDED,
        )
        assert evaluate_time_to_impact(state) == AlertLevel.NORMAL


class TestTWR:
    def test_good_twr_normal(self) -> None:
        state = State(thrust=15000.0, mass=1000.0, body_gravity=9.81)
        assert evaluate_twr(state) == AlertLevel.NORMAL

    def test_marginal_twr_warning(self) -> None:
        state = State(thrust=11000.0, mass=1000.0, body_gravity=9.81)
        assert evaluate_twr(state) == AlertLevel.WARNING

    def test_insufficient_twr_critical(self) -> None:
        state = State(thrust=9000.0, mass=1000.0, body_gravity=9.81)
        assert evaluate_twr(state) == AlertLevel.CRITICAL

    def test_zero_thrust_landed_is_normal(self) -> None:
        """TWR doesn't matter when landed."""
        state = State(
            thrust=0.0,
            mass=1000.0,
            body_gravity=9.81,
            situation=VesselSituation.LANDED,
        )
        assert evaluate_twr(state) == AlertLevel.NORMAL

    def test_zero_thrust_orbiting_is_normal(self) -> None:
        """TWR doesn't matter in stable orbit."""
        state = State(
            thrust=0.0,
            mass=1000.0,
            body_gravity=9.81,
            situation=VesselSituation.ORBITING,
        )
        assert evaluate_twr(state) == AlertLevel.NORMAL


class TestEngineFlameouts:
    def test_no_flameouts_normal(self) -> None:
        state = State(engine_flameout_count=0)
        assert evaluate_engine_flameouts(state) == AlertLevel.NORMAL

    def test_any_flameout_is_warning(self) -> None:
        state = State(engine_flameout_count=1)
        assert evaluate_engine_flameouts(state) == AlertLevel.WARNING

    def test_multiple_flameouts_warning(self) -> None:
        state = State(engine_flameout_count=3)
        assert evaluate_engine_flameouts(state) == AlertLevel.WARNING


class TestFuelFraction:
    def test_plenty_fuel_normal(self) -> None:
        state = State(mass=1000.0, mass_dry=500.0)
        assert evaluate_fuel_fraction(state) == AlertLevel.NORMAL

    def test_low_fuel_warning(self) -> None:
        state = State(mass=1000.0, mass_dry=900.0)
        assert evaluate_fuel_fraction(state) == AlertLevel.WARNING

    def test_critical_fuel(self) -> None:
        state = State(mass=1000.0, mass_dry=960.0)
        assert evaluate_fuel_fraction(state) == AlertLevel.CRITICAL


# --- Communications ---


class TestCommsConnected:
    def test_connected_normal(self) -> None:
        state = State(comms_connected=True)
        assert evaluate_comms_connected(state) == AlertLevel.NORMAL

    def test_disconnected_critical(self) -> None:
        state = State(comms_connected=False)
        assert evaluate_comms_connected(state) == AlertLevel.CRITICAL


class TestCommsSignalStrength:
    def test_strong_signal_normal(self) -> None:
        state = State(comms_signal_strength=0.8)
        assert evaluate_comms_signal_strength(state) == AlertLevel.NORMAL

    def test_weak_signal_warning(self) -> None:
        state = State(comms_signal_strength=0.2)
        assert evaluate_comms_signal_strength(state) == AlertLevel.WARNING

    def test_no_signal_critical(self) -> None:
        state = State(comms_signal_strength=0.0)
        assert evaluate_comms_signal_strength(state) == AlertLevel.CRITICAL


# --- Orbital safety ---


class TestPeriapsis:
    def test_safe_orbit_normal(self) -> None:
        state = State(
            orbit_periapsis=100_000.0,
            body_atmosphere_depth=70_000.0,
            situation=VesselSituation.ORBITING,
        )
        assert evaluate_periapsis(state) == AlertLevel.NORMAL

    def test_periapsis_in_atmosphere_warning(self) -> None:
        state = State(
            orbit_periapsis=50_000.0,
            body_atmosphere_depth=70_000.0,
            situation=VesselSituation.ORBITING,
        )
        assert evaluate_periapsis(state) == AlertLevel.WARNING

    def test_negative_periapsis_critical(self) -> None:
        state = State(
            orbit_periapsis=-50_000.0,
            body_atmosphere_depth=70_000.0,
            situation=VesselSituation.ORBITING,
        )
        assert evaluate_periapsis(state) == AlertLevel.CRITICAL

    def test_not_orbiting_is_normal(self) -> None:
        """Periapsis alert only matters when in orbit."""
        state = State(
            orbit_periapsis=-100.0,
            body_atmosphere_depth=70_000.0,
            situation=VesselSituation.FLYING,
        )
        assert evaluate_periapsis(state) == AlertLevel.NORMAL
