"""Bridge between kRPC connection and the action system's pure types.

Reads kRPC state into VesselState and applies VesselCommands back to kRPC.
All kRPC-specific access is isolated here so the rest of the control
module stays decoupled from the game connection.
"""

from __future__ import annotations

from dataclasses import fields

from ksp_mission_control.control.actions.base import (
    ReferenceFrame,
    SASMode,
    SpeedMode,
    VesselCommands,
    VesselSituation,
    VesselState,
)

# Command fields that have a matching field in VesselState for comparison.
# Excluded from comparison (always applied when non-None):
#   autopilot_direction/autopilot_config: transient configuration, no state equivalent
#   stage: one-shot trigger
#   input_*/translate_*: transient axis inputs, no persistent state
_COMPARABLE_FIELDS: dict[str, str] = {
    "throttle": "control_throttle",
    "autopilot": "control_autopilot",
    "autopilot_pitch": "control_autopilot_target_pitch",
    "autopilot_heading": "control_autopilot_target_heading",
    "autopilot_roll": "control_autopilot_target_roll",
    "sas": "control_sas",
    "sas_mode": "control_sas_mode",
    "ui_speed_mode": "control_ui_speed_mode",
    "rcs": "control_rcs",
    "gear": "control_gear",
    "legs": "control_legs",
    "lights": "control_lights",
    "brakes": "control_brakes",
    "wheels": "control_wheels",
    "abort": "control_abort",
    "translate_forward": "control_translate_forward",
    "translate_right": "control_translate_right",
    "translate_up": "control_translate_up",
    "deployable_solar_panels": "control_deployable_solar_panels",
    "deployable_antennas": "control_deployable_antennas",
    "deployable_cargo_bays": "control_deployable_cargo_bays",
    "deployable_intakes": "control_deployable_intakes",
    "deployable_parachutes": "control_deployable_parachutes",
    "deployable_radiators": "control_deployable_radiators",
}


def _parse_sas_mode(raw: str) -> SASMode:
    """Convert a kRPC SAS mode string to a SASMode enum.

    kRPC ``str(control.sas_mode)`` returns ``'SASMode.radial'``.
    Extracts the member name and looks it up in our enum.
    """
    name = raw.split(".")[-1] if "." in raw else raw
    return SASMode(name)


def _parse_speed_mode(raw: str) -> SpeedMode:
    """Convert a kRPC speed mode string to a SpeedMode enum.

    kRPC ``str(space_center.navball.speed_mode)`` returns ``'SpeedMode.surface'``.
    Extracts the member name and looks it up in our enum.
    """
    name = raw.split(".")[-1] if "." in raw else raw
    return SpeedMode(name)


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
    # Orientation (pitch/heading/roll) must use the surface reference frame
    # to match the kRPC autopilot's target_pitch/target_heading/target_roll,
    # which operate in surface_reference_frame by default.
    surface_flight = vessel.flight(vessel.surface_reference_frame)
    orbit = vessel.orbit
    control = vessel.control
    ap = vessel.auto_pilot
    # Autopilot state: kRPC doesn't expose an 'engaged' property, so we
    # infer it from the autopilot error (which raises when not engaged).
    ap_target_pitch = ap.target_pitch
    ap_target_heading = ap.target_heading
    ap_target_roll = ap.target_roll
    # Autopilot error properties raise when the autopilot is not engaged.
    # We use this to infer the engaged state since kRPC has no 'engaged' property.
    try:
        ap_error: float | None = ap.error
        ap_pitch_error: float | None = ap.pitch_error
        ap_heading_error: float | None = ap.heading_error
        ap_roll_error: float | None = ap.roll_error
        ap_engaged = True
    except Exception:
        ap_error = None
        ap_pitch_error = None
        ap_heading_error = None
        ap_roll_error = None
        ap_engaged = False
    # navball.speed_mode may not be available in all kRPC versions.
    try:
        speed_mode_raw = str(conn.space_center.navball.speed_mode)  # type: ignore[attr-defined]
    except (AttributeError, Exception):
        speed_mode_raw = "orbit"
    return VesselState(
        altitude_sea=flight.mean_altitude,
        altitude_surface=flight.surface_altitude,
        speed_vertical=flight.vertical_speed,
        speed_surface=flight.speed,
        speed_orbital=orbit.speed,
        pressure_dynamic=flight.dynamic_pressure,
        pressure_static=flight.static_pressure,
        aero_drag=flight.drag,
        aero_lift=flight.lift,
        g_force=flight.g_force,
        orbit_apoapsis=orbit.apoapsis_altitude,
        orbit_periapsis=orbit.periapsis_altitude,
        orbit_inclination=orbit.inclination,
        orbit_eccentricity=orbit.eccentricity,
        orbit_period=orbit.period,
        orbit_apoapsis_time_to=orbit.time_to_apoapsis,
        orbit_periapsis_time_to=orbit.time_to_periapsis,
        met=vessel.met,
        name=vessel.name,
        situation=_parse_vessel_situation(str(vessel.situation)),
        mass=vessel.mass,
        mass_dry=vessel.dry_mass,
        thrust=vessel.thrust,
        thrust_available=vessel.available_thrust,
        thrust_peak=vessel.max_thrust,
        engine_impulse_specific=vessel.specific_impulse,
        body_name=orbit.body.name,
        body_radius=orbit.body.equatorial_radius,
        body_gravity=orbit.body.surface_gravity,
        body_has_atmosphere=orbit.body.has_atmosphere,
        body_atmosphere_depth=orbit.body.atmosphere_depth if orbit.body.has_atmosphere else 0.0,
        position_latitude=flight.latitude,
        position_longitude=flight.longitude,
        orientation_pitch=surface_flight.pitch,
        orientation_heading=surface_flight.heading,
        orientation_roll=surface_flight.roll,
        control_input_pitch=control.pitch,
        control_input_yaw=control.yaw,
        control_input_roll=control.roll,
        control_autopilot=ap_engaged,
        control_autopilot_target_pitch=ap_target_pitch,
        control_autopilot_target_heading=ap_target_heading,
        control_autopilot_target_roll=ap_target_roll,
        control_autopilot_error=ap_error,
        control_autopilot_error_pitch=ap_pitch_error,
        control_autopilot_error_heading=ap_heading_error,
        control_autopilot_error_roll=ap_roll_error,
        control_throttle=control.throttle,
        control_sas=control.sas,
        control_sas_mode=_parse_sas_mode(str(control.sas_mode)) if control.sas else None,
        control_ui_speed_mode=_parse_speed_mode(speed_mode_raw),
        control_rcs=control.rcs,
        control_gear=control.gear,
        control_legs=control.legs,
        control_lights=control.lights,
        control_brakes=control.brakes,
        control_wheels=control.wheels,
        control_abort=control.abort,
        control_translate_forward=control.forward,
        control_translate_right=control.right,
        control_translate_up=control.up,
        stage_current=control.current_stage,
        stage_max=max((p.stage for p in vessel.parts.all), default=0),
        engine_flameout_count=sum(1 for e in vessel.parts.engines if e.active and not e.has_fuel),
        control_deployable_solar_panels=control.solar_panels,
        control_deployable_antennas=control.antennas,
        control_deployable_cargo_bays=control.cargo_bays,
        control_deployable_intakes=control.intakes,
        control_deployable_parachutes=control.parachutes,
        control_deployable_radiators=control.radiators,
        resource_electric_charge=vessel.resources.amount("ElectricCharge"),
        resource_liquid_fuel=vessel.resources.amount("LiquidFuel"),
        resource_oxidizer=vessel.resources.amount("Oxidizer"),
        resource_mono_propellant=vessel.resources.amount("MonoPropellant"),
    )


def filter_commands(commands: VesselCommands, state: VesselState) -> tuple[VesselCommands, frozenset[str]]:
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
    orbit = vessel.orbit

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

    # Autopilot (kRPC auto_pilot, separate from SAS)
    # Autopilot and SAS are mutually exclusive: engaging one disables the other.
    ap = vessel.auto_pilot
    if controls.autopilot is not None:
        if controls.autopilot:
            vc.sas = False
            ap.engage()
        else:
            ap.disengage()
    if controls.autopilot_pitch is not None:
        ap.target_pitch = controls.autopilot_pitch
    if controls.autopilot_heading is not None:
        ap.target_heading = controls.autopilot_heading
    if controls.autopilot_roll is not None:
        ap.target_roll = controls.autopilot_roll
    if controls.autopilot_direction is not None:
        direction = controls.autopilot_direction
        frame_map = {
            ReferenceFrame.VESSEL_SURFACE: vessel.surface_reference_frame,
            ReferenceFrame.VESSEL_ORBITAL: vessel.orbital_reference_frame,
            ReferenceFrame.VESSEL: vessel.reference_frame,
            ReferenceFrame.BODY: orbit.body.reference_frame,
            ReferenceFrame.BODY_NON_ROTATING: orbit.body.non_rotating_reference_frame,
        }
        ap.reference_frame = frame_map[direction.reference_frame]
        ap.target_direction = direction.vector
    if controls.autopilot_config is not None:
        cfg = controls.autopilot_config
        ap.auto_tune = cfg.auto_tune
        ap.time_to_peak = cfg.time_to_peak
        ap.overshoot = cfg.overshoot
        ap.stopping_time = cfg.stopping_time
        ap.deceleration_time = cfg.deceleration_time
        ap.attenuation_angle = cfg.attenuation_angle
        ap.roll_threshold = cfg.roll_threshold
        if cfg.pitch_pid_gains is not None:
            ap.pitch_pid_gains = cfg.pitch_pid_gains
        if cfg.yaw_pid_gains is not None:
            ap.yaw_pid_gains = cfg.yaw_pid_gains
        if cfg.roll_pid_gains is not None:
            ap.roll_pid_gains = cfg.roll_pid_gains

    # Systems
    if controls.sas is not None:
        if controls.sas:
            ap.disengage()
        vc.sas = controls.sas
    if controls.sas_mode is not None:
        krpc_sas = getattr(conn.space_center.SASMode, controls.sas_mode.value, None)  # type: ignore[attr-defined]
        if krpc_sas is not None:
            vc.sas_mode = krpc_sas
    if controls.ui_speed_mode is not None:
        krpc_speed = getattr(conn.space_center.SpeedMode, controls.ui_speed_mode.value, None)  # type: ignore[attr-defined]
        if krpc_speed is not None:
            conn.space_center.navball.speed_mode = krpc_speed  # type: ignore[attr-defined]
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
    if controls.deployable_solar_panels is not None:
        vc.solar_panels = controls.deployable_solar_panels
    if controls.deployable_antennas is not None:
        vc.antennas = controls.deployable_antennas
    if controls.deployable_cargo_bays is not None:
        vc.cargo_bays = controls.deployable_cargo_bays
    if controls.deployable_intakes is not None:
        vc.intakes = controls.deployable_intakes
    if controls.deployable_parachutes is not None:
        vc.parachutes = controls.deployable_parachutes
    if controls.deployable_radiators is not None:
        vc.radiators = controls.deployable_radiators
