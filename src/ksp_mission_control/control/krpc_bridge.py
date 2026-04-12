"""Bridge between kRPC connection and the action system's pure types.

Reads kRPC state into VesselState and applies VesselCommands back to kRPC.
All kRPC-specific access is isolated here so the rest of the control
module stays decoupled from the game connection.
"""

from __future__ import annotations

from dataclasses import fields

from ksp_mission_control.control.actions.base import VesselCommands, VesselState

# Command fields that have a matching field in VesselState for comparison.
# pitch/heading are NOT included: command pitch is a target, state pitch is
# the vessel's current orientation. stage is a trigger, not a state.
_COMPARABLE_FIELDS: dict[str, str] = {
    "throttle": "throttle",
    "sas": "sas",
    "rcs": "rcs",
}


class NoActiveVesselError(Exception):
    """Raised when kRPC reports no active vessel.

    This is a transient condition (e.g. player is in the Space Center),
    not a connection failure. The session keeps polling when it catches this.
    """


def read_vessel_state(conn: object) -> VesselState:
    """Read current vessel telemetry from a kRPC connection into a VesselState."""
    vessel = conn.space_center.active_vessel  # type: ignore[attr-defined]
    if vessel is None:
        raise NoActiveVesselError("No active vessel found")
    flight = vessel.flight(vessel.orbit.body.reference_frame)
    orbit = vessel.orbit
    control = vessel.control
    return VesselState(
        altitude_sea=flight.mean_altitude,
        altitude_surface=flight.surface_altitude,
        vertical_speed=flight.vertical_speed,
        surface_speed=flight.speed,
        orbital_speed=orbit.speed,
        apoapsis=orbit.apoapsis_altitude,
        periapsis=orbit.periapsis_altitude,
        met=vessel.met,
        vessel_name=vessel.name,
        situation=str(vessel.situation),
        body=orbit.body.name,
        latitude=flight.latitude,
        longitude=flight.longitude,
        inclination=orbit.inclination,
        eccentricity=orbit.eccentricity,
        period=orbit.period,
        pitch=flight.pitch,
        heading=flight.heading,
        roll=flight.roll,
        throttle=control.throttle,
        sas=control.sas,
        sas_mode=str(control.sas_mode),
        rcs=control.rcs,
        current_stage=control.current_stage,
        max_stages=max((p.stage for p in vessel.parts.all), default=0),
        electric_charge=vessel.resources.amount("ElectricCharge"),
        liquid_fuel=vessel.resources.amount("LiquidFuel"),
        oxidizer=vessel.resources.amount("Oxidizer"),
        mono_propellant=vessel.resources.amount("MonoPropellant"),
    )


def filter_commands(
    commands: VesselCommands, state: VesselState
) -> tuple[VesselCommands, frozenset[str]]:
    """Filter out command fields that already match the vessel's current state.

    Returns:
        - Filtered commands: only fields that differ from the vessel (for kRPC).
        - Applied fields: names of fields that were actually sent.

    Fields without a comparable state equivalent (pitch, heading, stage) are
    always applied when non-None.
    """
    filtered = VesselCommands()
    applied: set[str] = set()

    for field in fields(commands):
        value = getattr(commands, field.name)
        if value is None:
            continue

        state_field = _COMPARABLE_FIELDS.get(field.name)
        if state_field is not None and getattr(state, state_field) == value:
            continue  # Redundant: vessel already has this value

        setattr(filtered, field.name, value)
        applied.add(field.name)

    return filtered, frozenset(applied)


def apply_controls(conn: object, controls: VesselCommands) -> None:
    """Apply non-None control values to the vessel via kRPC."""
    vessel = conn.space_center.active_vessel  # type: ignore[attr-defined]
    if vessel is None:
        raise NoActiveVesselError("No active vessel found")
    vc = vessel.control
    if controls.throttle is not None:
        vc.throttle = controls.throttle
    if controls.sas is not None:
        vc.sas = controls.sas
    if controls.rcs is not None:
        vc.rcs = controls.rcs
    if controls.stage is not None and controls.stage:
        vc.activate_next_stage()
