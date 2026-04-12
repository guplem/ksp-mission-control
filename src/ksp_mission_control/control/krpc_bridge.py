"""Bridge between kRPC connection and the action system's pure types.

Reads kRPC state into VesselState and applies VesselCommands back to kRPC.
All kRPC-specific access is isolated here so the rest of the control
module stays decoupled from the game connection.
"""

from __future__ import annotations

from ksp_mission_control.control.actions.base import VesselCommands, VesselState


def read_vessel_state(conn: object) -> VesselState:
    """Read current vessel telemetry from a kRPC connection into a VesselState."""
    vessel = conn.space_center.active_vessel  # type: ignore[attr-defined]
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


def apply_controls(conn: object, controls: VesselCommands) -> None:
    """Apply non-None control values to the vessel via kRPC."""
    vessel = conn.space_center.active_vessel  # type: ignore[attr-defined]
    vc = vessel.control
    if controls.throttle is not None:
        vc.throttle = controls.throttle
    if controls.sas is not None:
        vc.sas = controls.sas
    if controls.rcs is not None:
        vc.rcs = controls.rcs
    if controls.stage is not None and controls.stage:
        vc.activate_next_stage()
