"""Telemetry alert level evaluation for color-coded telemetry display.

Pure functions that evaluate State fields and return an AlertLevel.
No Textual or kRPC imports - fully testable with constructed states.
"""

from __future__ import annotations

from enum import IntEnum

from ksp_mission_control.control.actions.base import State, VesselSituation

# Thresholds are tuned for typical KSP gameplay.
# WARNING = approaching danger, CRITICAL = immediate risk.

_RESOURCE_WARNING = 0.15
_RESOURCE_CRITICAL = 0.05
_ELECTRIC_WARNING = 0.20
_ELECTRIC_CRITICAL = 0.05


class AlertLevel(IntEnum):
    """Severity level for a telemetry value. Higher = worse."""

    NORMAL = 0
    WARNING = 1
    CRITICAL = 2


# Color mapping: AlertLevel -> CSS variable name (for resolve_theme_colors)
ALERT_COLOR_VARIABLE: dict[AlertLevel, str] = {
    AlertLevel.NORMAL: "foreground",
    AlertLevel.WARNING: "warning",
    AlertLevel.CRITICAL: "error",
}


def _resource_alert(fraction: float, max_amount: float, warning: float, critical: float) -> AlertLevel:
    """Evaluate a resource fraction against thresholds. Returns NORMAL if no capacity."""
    if max_amount <= 0.0:
        return AlertLevel.NORMAL
    if fraction <= critical:
        return AlertLevel.CRITICAL
    if fraction <= warning:
        return AlertLevel.WARNING
    return AlertLevel.NORMAL


# --- Resources ---


def evaluate_electric_charge(state: State) -> AlertLevel:
    return _resource_alert(
        state.resource_electric_charge_fraction,
        state.resource_electric_charge_max,
        _ELECTRIC_WARNING,
        _ELECTRIC_CRITICAL,
    )


def evaluate_liquid_fuel(state: State) -> AlertLevel:
    return _resource_alert(
        state.resource_liquid_fuel_fraction,
        state.resource_liquid_fuel_max,
        _RESOURCE_WARNING,
        _RESOURCE_CRITICAL,
    )


def evaluate_oxidizer(state: State) -> AlertLevel:
    return _resource_alert(
        state.resource_oxidizer_fraction,
        state.resource_oxidizer_max,
        _RESOURCE_WARNING,
        _RESOURCE_CRITICAL,
    )


def evaluate_mono_propellant(state: State) -> AlertLevel:
    return _resource_alert(
        state.resource_mono_propellant_fraction,
        state.resource_mono_propellant_max,
        _RESOURCE_WARNING,
        _RESOURCE_CRITICAL,
    )


# --- Structural / survivability ---


def evaluate_g_force(state: State) -> AlertLevel:
    if state.g_force >= 8.0:
        return AlertLevel.CRITICAL
    if state.g_force >= 4.0:
        return AlertLevel.WARNING
    return AlertLevel.NORMAL


def evaluate_dynamic_pressure(state: State) -> AlertLevel:
    kpa = state.pressure_dynamic / 1000.0
    if kpa >= 40.0:
        return AlertLevel.CRITICAL
    if kpa >= 20.0:
        return AlertLevel.WARNING
    return AlertLevel.NORMAL


# --- Flight safety ---


def evaluate_time_to_impact(state: State) -> AlertLevel:
    if state.is_landed or not state.is_descending:
        return AlertLevel.NORMAL
    tti = state.altitude_time_to_impact
    if tti <= 10.0:
        return AlertLevel.CRITICAL
    if tti <= 30.0:
        return AlertLevel.WARNING
    return AlertLevel.NORMAL


def evaluate_twr(state: State) -> AlertLevel:
    # TWR only matters during active flight (not landed, not in stable orbit)
    if state.is_landed or state.situation in (VesselSituation.ORBITING, VesselSituation.ESCAPING):
        return AlertLevel.NORMAL
    if state.thrust == 0.0:
        return AlertLevel.NORMAL
    twr = state.twr
    if twr < 1.0:
        return AlertLevel.CRITICAL
    if twr < 1.2:
        return AlertLevel.WARNING
    return AlertLevel.NORMAL


def evaluate_engine_flameouts(state: State) -> AlertLevel:
    if state.engine_flameout_count > 0:
        return AlertLevel.WARNING
    return AlertLevel.NORMAL


def evaluate_fuel_fraction(state: State) -> AlertLevel:
    if state.mass <= 0.0:
        return AlertLevel.NORMAL
    fraction = state.fuel_fraction
    if fraction <= _RESOURCE_CRITICAL:
        return AlertLevel.CRITICAL
    if fraction <= _RESOURCE_WARNING:
        return AlertLevel.WARNING
    return AlertLevel.NORMAL


# --- Communications ---


def evaluate_comms_connected(state: State) -> AlertLevel:
    if not state.comms_connected:
        return AlertLevel.CRITICAL
    return AlertLevel.NORMAL


def evaluate_comms_signal_strength(state: State) -> AlertLevel:
    if state.comms_signal_strength <= 0.0:
        return AlertLevel.CRITICAL
    if state.comms_signal_strength < 0.3:
        return AlertLevel.WARNING
    return AlertLevel.NORMAL


# --- Orbital safety ---


def evaluate_periapsis(state: State) -> AlertLevel:
    if state.situation not in (VesselSituation.ORBITING, VesselSituation.ESCAPING):
        return AlertLevel.NORMAL
    if state.orbit_periapsis < 0.0:
        return AlertLevel.CRITICAL
    if state.orbit_periapsis < state.body_atmosphere_depth:
        return AlertLevel.WARNING
    return AlertLevel.NORMAL
