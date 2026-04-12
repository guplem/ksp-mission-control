"""Bridge between kRPC connection and the action system's pure types.

Reads kRPC state into VesselState and applies VesselCommands back to kRPC.
All kRPC-specific access is isolated here so the rest of the control
module stays decoupled from the game connection.
"""

from __future__ import annotations

from dataclasses import fields

from ksp_mission_control.control.actions.base import (
    SASMode,
    VesselCommands,
    VesselSituation,
    VesselState,
)

# Command fields that have a matching field in VesselState for comparison.
# Excluded from comparison (always applied when non-None):
#   pitch/heading: command = target angle, state = current orientation
#   stage: one-shot trigger
#   input_*/translate_*: transient axis inputs, no persistent state
#   wheels: kRPC write-only, no readable state
_COMPARABLE_FIELDS: dict[str, str] = {
    "throttle": "throttle",
    "sas": "sas",
    "sas_mode": "sas_mode",
    "rcs": "rcs",
    "gear": "gear",
    "legs": "legs",
    "lights": "lights",
    "brakes": "brakes",
    "abort": "abort",
    "solar_panels": "solar_panels",
    "antennas": "antennas",
    "cargo_bays": "cargo_bays",
    "intakes": "intakes",
    "parachutes": "parachutes",
    "radiators": "radiators",
}


def _parse_sas_mode(raw: str) -> SASMode:
    """Convert a kRPC SAS mode string to a SASMode enum.

    kRPC ``str(control.sas_mode)`` returns ``'SASMode.radial'``.
    Extracts the member name and looks it up in our enum.
    """
    name = raw.split(".")[-1] if "." in raw else raw
    return SASMode(name)


def _parse_vessel_situation(raw: str) -> VesselSituation:
    """Convert a kRPC vessel situation string to a VesselSituation enum.

    kRPC ``str(vessel.situation)`` returns ``'VesselSituation.flying'``.
    Extracts the member name and looks it up in our enum.
    """
    name = raw.split(".")[-1] if "." in raw else raw
    return VesselSituation(name)


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
        situation=_parse_vessel_situation(str(vessel.situation)),
        body=orbit.body.name,
        body_radius=orbit.body.equatorial_radius,
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
        sas_mode=_parse_sas_mode(str(control.sas_mode)),
        rcs=control.rcs,
        gear=control.gear,
        legs=control.legs,
        lights=control.lights,
        brakes=control.brakes,
        abort=control.abort,
        current_stage=control.current_stage,
        max_stages=max((p.stage for p in vessel.parts.all), default=0),
        solar_panels=control.solar_panels,
        antennas=control.antennas,
        cargo_bays=control.cargo_bays,
        intakes=control.intakes,
        parachutes=control.parachutes,
        radiators=control.radiators,
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

    # Throttle & staging
    if controls.throttle is not None:
        vc.throttle = controls.throttle
    if controls.stage is not None and controls.stage:
        vc.activate_next_stage()

    # Rotation axes
    if controls.input_pitch is not None:
        vc.pitch = controls.input_pitch
    if controls.input_yaw is not None:
        vc.yaw = controls.input_yaw
    if controls.input_roll is not None:
        vc.roll = controls.input_roll

    # Translation axes (RCS)
    if controls.translate_forward is not None:
        vc.forward = controls.translate_forward
    if controls.translate_right is not None:
        vc.right = controls.translate_right
    if controls.translate_up is not None:
        vc.up = controls.translate_up

    # Systems
    if controls.sas is not None:
        vc.sas = controls.sas
    if controls.sas_mode is not None:
        krpc_sas = getattr(conn.space_center.SASMode, controls.sas_mode.value, None)  # type: ignore[attr-defined]
        if krpc_sas is not None:
            vc.sas_mode = krpc_sas
    if controls.rcs is not None:
        vc.rcs = controls.rcs
    if controls.gear is not None:
        vc.gear = controls.gear
    if controls.legs is not None:
        vc.legs = controls.legs
    if controls.lights is not None:
        vc.lights = controls.lights
    if controls.brakes is not None:
        vc.brakes = controls.brakes
    if controls.wheels is not None:
        vc.wheels = controls.wheels
    if controls.abort is not None:
        vc.abort = controls.abort

    # Deployables
    if controls.solar_panels is not None:
        vc.solar_panels = controls.solar_panels
    if controls.antennas is not None:
        vc.antennas = controls.antennas
    if controls.cargo_bays is not None:
        vc.cargo_bays = controls.cargo_bays
    if controls.intakes is not None:
        vc.intakes = controls.intakes
    if controls.parachutes is not None:
        vc.parachutes = controls.parachutes
    if controls.radiators is not None:
        vc.radiators = controls.radiators
