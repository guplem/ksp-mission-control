"""Bridge between kRPC connection and the action system's pure types.

Reads kRPC state into VesselState and applies VesselCommands back to kRPC.
All kRPC-specific access is isolated here so the rest of the control
module stays decoupled from the game connection.
"""

from __future__ import annotations

import math
from dataclasses import fields

from ksp_mission_control.control.actions.base import (
    ImpactPrediction,
    ManeuverNode,
    ParachuteInfo,
    PartInfo,
    Parts,
    ReferenceFrame,
    SASMode,
    ScienceAction,
    ScienceExperiment,
    ScienceSituation,
    SpeedMode,
    State,
    VesselCommands,
    VesselSituation,
)
from ksp_mission_control.control.actions.helpers.impact_prediction import find_impact_ut
from ksp_mission_control.control.actions.helpers.maneuver_node import tsiolkovsky_burn_time

# Cheap reject for impact prediction: if the trajectory's periapsis is above
# this altitude (in meters above sea level), the orbit does not intersect any
# KSP terrain. Kerbin's highest peak is roughly 6.8 km; this margin keeps the
# bisection from being invoked for any stable orbit.
_IMPACT_PREDICTION_MAX_PERIAPSIS: float = 10_000.0

# Inclination (radians) below which the equatorial ascending/descending nodes
# are not well defined. 0.001 rad is roughly 0.057 degrees.
_EQUATORIAL_INCLINATION_TOLERANCE: float = 0.001

# Tolerance for matching a maneuver node by ut. kRPC does not change the
# ut of a node after creation (unless someone drags it in-game), so an
# exact float match is normally fine; the tolerance absorbs round-trip
# float jitter through the kRPC protocol.
_NODE_UT_MATCH_TOLERANCE: float = 0.001

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
    "stage_lock": "control_stage_lock",
    "reaction_wheels": "control_reaction_wheels",
    "wheel_throttle": "control_wheel_throttle",
    "wheel_steering": "control_wheel_steering",
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


def _derive_science_situation(situation: VesselSituation, altitude_sea: float, body: object) -> ScienceSituation:
    """Derive the science (experiment) situation from vessel state and body thresholds.

    KSP gates science experiments on the body-relative situation, which is not
    the same as ``vessel.situation``. The thresholds between "low" and "high"
    come from the body (``flying_high_altitude_threshold``,
    ``space_high_altitude_threshold``). Falls back to safe defaults if the
    thresholds are unavailable on older kRPC versions.
    """
    if situation in (VesselSituation.LANDED, VesselSituation.PRE_LAUNCH):
        return ScienceSituation.SURFACE_LANDED
    if situation == VesselSituation.SPLASHED:
        return ScienceSituation.SURFACE_SPLASHED
    if situation == VesselSituation.FLYING:
        try:
            flying_high_threshold = float(body.flying_high_altitude_threshold)  # type: ignore[attr-defined]
        except (AttributeError, Exception):
            flying_high_threshold = float("inf")
        if altitude_sea >= flying_high_threshold:
            return ScienceSituation.ATMOSPHERE_HIGH
        return ScienceSituation.ATMOSPHERE_LOW
    try:
        space_high_threshold = float(body.space_high_altitude_threshold)  # type: ignore[attr-defined]
    except (AttributeError, Exception):
        space_high_threshold = float("inf")
    if altitude_sea >= space_high_threshold:
        return ScienceSituation.SPACE_HIGH
    return ScienceSituation.SPACE_LOW


def _parse_part_state(raw: str) -> str:
    """Extract the member name from a kRPC part state enum string.

    kRPC ``str(chute.state)`` returns ``'ParachuteState.stowed'``.
    Returns the lowercase member name (e.g. ``'stowed'``).
    """
    return raw.split(".")[-1] if "." in raw else raw


def _read_parachute_state(chute: object, part: object) -> str:
    """Read the parachute state, falling back to module events on kRPC bug.

    Tries the kRPC ``chute.state`` property first. If that raises (kRPC
    RealChutes misdetection bug), infers state from ModuleParachute events:
    - 'Deploy Chute' available -> 'stowed'
    - 'Arm Chute' available -> 'stowed' (armed variant not distinguishable)
    - 'Cut Chute' available (no Deploy) -> 'deployed'
    - neither -> 'cut'
    """
    try:
        return _parse_part_state(str(chute.state))  # type: ignore[attr-defined]
    except Exception:
        pass
    # Fallback: infer from ModuleParachute events
    try:
        for module in part.modules:  # type: ignore[attr-defined]
            if module.name == "ModuleParachute":
                events: list[str] = list(module.events)
                if "Deploy Chute" in events:
                    return "stowed"
                if "Cut Chute" in events:
                    return "deployed"
                return "cut"
    except Exception:
        pass
    return "unknown"


def _read_parachute_module_fields(part: object) -> tuple[bool, float, float]:
    """Read parachute-specific fields from the generic ModuleParachute module.

    Returns (safe_to_deploy, deploy_semi_min_pressure, deploy_full_altitude).
    Falls back to defaults if the module or fields are not found.
    """
    try:
        for module in part.modules:  # type: ignore[attr-defined]
            if module.name == "ModuleParachute":
                safe_str = module.get_field("Safe to deploy?")
                safe_to_deploy = safe_str.strip().lower() == "safe"

                pressure_str = module.get_field("Min Pressure")
                deploy_semi_min_pressure = float(pressure_str)

                altitude_str = module.get_field("Altitude")
                deploy_full_altitude = float(altitude_str)

                return safe_to_deploy, deploy_semi_min_pressure, deploy_full_altitude
    except Exception:
        pass
    return False, 0.04, 1000.0


def _apply_science_action(experiment: object, action: ScienceAction) -> None:
    """Apply a ScienceAction to a single kRPC experiment object.

    For RUN, guards against experiments that already have data or are unavailable.
    """
    if action == ScienceAction.RUN:
        if experiment.available and not experiment.has_data:  # type: ignore[attr-defined]
            experiment.run()  # type: ignore[attr-defined]
    elif action == ScienceAction.RESET:
        experiment.reset()  # type: ignore[attr-defined]
    elif action == ScienceAction.DUMP:
        experiment.dump()  # type: ignore[attr-defined]
    elif action == ScienceAction.TRANSMIT:
        experiment.transmit()  # type: ignore[attr-defined]


def _compute_equatorial_nodes(orbit: object, current_ut: float) -> tuple[float, float, float, float]:
    """Compute the next ascending/descending node UTs and orbital speeds.

    AN (ascending node) is where the orbit crosses the equator going
    north; DN where it crosses going south. In Keplerian terms, AN sits
    at true anomaly ``-argument_of_periapsis`` (mod 2 pi) and DN at
    ``pi - argument_of_periapsis``. kRPC's ``ut_at_true_anomaly`` then
    propagates through Kepler's equation to give the next universal time.

    Returns ``(an_ut, dn_ut, an_speed, dn_speed)``. Infinite UTs and zero
    speeds are returned when the orbit is too close to equatorial for AN/DN
    to be meaningful, or when any kRPC field needed for the computation is
    unavailable.
    """
    try:
        inclination = float(orbit.inclination)  # type: ignore[attr-defined]
        if abs(inclination) < _EQUATORIAL_INCLINATION_TOLERANCE:
            return float("inf"), float("inf"), 0.0, 0.0
        omega = float(orbit.argument_of_periapsis)  # type: ignore[attr-defined]
    except (AttributeError, Exception):
        return float("inf"), float("inf"), 0.0, 0.0

    two_pi = 2.0 * math.pi
    an_true_anomaly = (-omega) % two_pi
    dn_true_anomaly = (math.pi - omega) % two_pi

    try:
        an_ut = float(orbit.ut_at_true_anomaly(an_true_anomaly))  # type: ignore[attr-defined]
        dn_ut = float(orbit.ut_at_true_anomaly(dn_true_anomaly))  # type: ignore[attr-defined]
        period = float(orbit.period)  # type: ignore[attr-defined]
        # ut_at_true_anomaly can return a UT in the past; bump to the next
        # crossing so callers always get a future event.
        while an_ut < current_ut and period > 0.0:
            an_ut += period
        while dn_ut < current_ut and period > 0.0:
            dn_ut += period
        an_radius = float(orbit.radius_at(an_ut))  # type: ignore[attr-defined]
        dn_radius = float(orbit.radius_at(dn_ut))  # type: ignore[attr-defined]
        mu = float(orbit.body.gravitational_parameter)  # type: ignore[attr-defined]
        sma = float(orbit.semi_major_axis)  # type: ignore[attr-defined]
        an_speed = math.sqrt(mu * (2.0 / an_radius - 1.0 / sma))
        dn_speed = math.sqrt(mu * (2.0 / dn_radius - 1.0 / sma))
    except (AttributeError, ValueError, ZeroDivisionError, Exception):
        return float("inf"), float("inf"), 0.0, 0.0

    return an_ut, dn_ut, an_speed, dn_speed


def _compute_impact_prediction(vessel: object, body: object, current_ut: float) -> ImpactPrediction | None:
    """Predict where the active trajectory crosses sea level.

    Uses the first future maneuver node's post-burn orbit when one is
    planned; otherwise uses the vessel's current orbit. Returns ``None``
    when the trajectory does not impact within one period.
    """
    try:
        nodes = list(vessel.control.nodes)  # type: ignore[attr-defined]
    except (AttributeError, Exception):
        nodes = []

    target_orbit: object
    start_ut: float
    source: str
    if nodes and float(getattr(nodes[0], "ut", current_ut)) > current_ut:
        target_orbit = nodes[0].orbit  # type: ignore[attr-defined]
        start_ut = float(nodes[0].ut)  # type: ignore[attr-defined]
        source = "next_node_orbit"
    else:
        target_orbit = vessel.orbit  # type: ignore[attr-defined]
        start_ut = current_ut
        source = "current_orbit"

    try:
        periapsis_altitude = float(target_orbit.periapsis_altitude)  # type: ignore[attr-defined]
        period = float(target_orbit.period)  # type: ignore[attr-defined]
    except (AttributeError, Exception):
        return None

    if periapsis_altitude > _IMPACT_PREDICTION_MAX_PERIAPSIS:
        return None
    if period <= 0.0:
        # Parabolic / hyperbolic trajectories: no closed period. Skip for now.
        return None

    try:
        frame = body.reference_frame  # type: ignore[attr-defined]

        def sample_altitude(ut: float) -> float:
            position = target_orbit.position_at(ut, frame)  # type: ignore[attr-defined]
            return float(body.altitude_at_position(position, frame))  # type: ignore[attr-defined]

        impact_ut = find_impact_ut(sample_altitude, start_ut=start_ut, end_ut=start_ut + period)
        if impact_ut is None:
            return None
        impact_position = target_orbit.position_at(impact_ut, frame)  # type: ignore[attr-defined]
        latitude = float(body.latitude_at_position(impact_position, frame))  # type: ignore[attr-defined]
        longitude = float(body.longitude_at_position(impact_position, frame))  # type: ignore[attr-defined]
    except (AttributeError, Exception):
        return None

    # Wrap longitude into (-180, 180].
    longitude = ((longitude + 180.0) % 360.0) - 180.0

    try:
        terrain = float(body.surface_height(latitude, longitude))  # type: ignore[attr-defined]
    except (AttributeError, Exception):
        terrain = 0.0

    return ImpactPrediction(
        latitude=latitude,
        longitude=longitude,
        altitude_terrain=terrain,
        time_to_ballistic_impact=impact_ut - current_ut,
        source=source,
    )


class NoActiveVesselError(Exception):
    """Raised when kRPC reports no active vessel.

    This is a transient condition (e.g. player is in the Space Center),
    not a connection failure. The session keeps polling when it catches this.
    """


def read_vessel_state(conn: object) -> State:
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
    # Detect engagement from ap.error alone, then read per-axis errors
    # independently. Individual axis errors can raise even when engaged
    # (e.g. roll_error when target_roll is NaN / roll targeting disabled).
    try:
        ap_error: float | None = ap.error
        ap_engaged = True
    except Exception:
        ap_error = None
        ap_engaged = False
    if ap_engaged:
        try:
            ap_pitch_error: float | None = ap.pitch_error
        except Exception:
            ap_pitch_error = None
        try:
            ap_heading_error: float | None = ap.heading_error
        except Exception:
            ap_heading_error = None
        try:
            ap_roll_error: float | None = ap.roll_error
        except Exception:
            ap_roll_error = None
    else:
        ap_pitch_error = None
        ap_heading_error = None
        ap_roll_error = None
    # navball.speed_mode may not be available in all kRPC versions.
    try:
        speed_mode_raw = str(conn.space_center.navball.speed_mode)  # type: ignore[attr-defined]
    except (AttributeError, Exception):
        speed_mode_raw = "orbit"
    # CommNet status may not be available on all vessels or kRPC versions.
    try:
        comms_connected = vessel.comms.can_communicate
        comms_signal_strength = vessel.comms.signal_strength
    except (AttributeError, Exception):
        comms_connected = False
        comms_signal_strength = 0.0
    # SOI transition time: NaN when no transition is upcoming.
    try:
        soi_time_raw = orbit.time_to_soi_change
        import math as _math

        orbit_soi_time_to_change = float("inf") if _math.isnan(soi_time_raw) else soi_time_raw
    except (AttributeError, Exception):
        orbit_soi_time_to_change = float("inf")
    # Science experiments: build a snapshot of every experiment on the vessel.
    science_experiments: list[ScienceExperiment] = []
    try:
        for idx, exp in enumerate(vessel.parts.experiments):
            try:
                sci_value = sum(d.science_value for d in exp.data) if exp.has_data else 0.0
            except Exception:
                sci_value = 0.0
            try:
                subject = exp.science_subject
                sci_cap = subject.science_cap if subject else 0.0
            except Exception:
                sci_cap = 0.0
            try:
                part_tag = exp.part.tag
            except (AttributeError, Exception):
                part_tag = ""
            science_experiments.append(
                ScienceExperiment(
                    index=idx,
                    name=exp.name,
                    title=exp.title,
                    part_title=exp.part.title,
                    name_tag=part_tag,
                    available=exp.available,
                    has_data=exp.has_data,
                    inoperable=exp.inoperable,
                    rerunnable=exp.rerunnable,
                    deployed=exp.deployed,
                    biome=exp.biome,
                    science_value=sci_value,
                    science_cap=sci_cap,
                )
            )
    except Exception:
        science_experiments = []

    # Parts: parachutes
    # kRPC's Parachute wrapper has a bug that misidentifies stock parachutes as
    # RealChutes, breaking chute.state/deploy_full_altitude/deploy_semi_min_pressure.
    # We read state and fields from the generic ModuleParachute module instead.
    parts_parachutes: list[ParachuteInfo] = []
    try:
        for chute in vessel.parts.parachutes:
            part = chute.part
            state = _read_parachute_state(chute, part)
            safe_to_deploy, deploy_semi_min_pressure, deploy_full_altitude = _read_parachute_module_fields(part)
            parts_parachutes.append(
                ParachuteInfo(
                    stage=part.stage,
                    state=state,
                    decouple_stage=part.decouple_stage,
                    safe_to_deploy=safe_to_deploy,
                    deploy_semi_min_pressure=deploy_semi_min_pressure,
                    deploy_full_altitude=deploy_full_altitude,
                )
            )
    except Exception:
        parts_parachutes = []

    # Parts: landing legs
    parts_legs: list[PartInfo] = []
    try:
        for leg in vessel.parts.legs:
            parts_legs.append(PartInfo(stage=leg.part.stage, state=_parse_part_state(str(leg.state)), decouple_stage=leg.part.decouple_stage))
    except Exception:
        parts_legs = []

    # Parts: fairings
    parts_fairings: list[PartInfo] = []
    try:
        for fairing in vessel.parts.fairings:
            fairing_state = "jettisoned" if fairing.jettisoned else "intact"
            parts_fairings.append(PartInfo(stage=fairing.part.stage, state=fairing_state, decouple_stage=fairing.part.decouple_stage))
    except Exception:
        parts_fairings = []

    # Parts: decouplers
    parts_decouplers: list[PartInfo] = []
    try:
        for decoupler in vessel.parts.decouplers:
            decoupler_state = "decoupled" if decoupler.decoupled else "attached"
            parts_decouplers.append(PartInfo(stage=decoupler.part.stage, state=decoupler_state, decouple_stage=decoupler.part.decouple_stage))
    except Exception:
        parts_decouplers = []

    # Parts: launch clamps
    parts_launch_clamps: list[PartInfo] = []
    try:
        for clamp in vessel.parts.launch_clamps:
            parts_launch_clamps.append(PartInfo(stage=clamp.part.stage, state="attached", decouple_stage=clamp.part.decouple_stage))
    except Exception:
        parts_launch_clamps = []

    # Parts: engines
    parts_engines: list[PartInfo] = []
    try:
        for engine in vessel.parts.engines:
            if engine.active and not engine.has_fuel:
                engine_state = "flameout"
            elif engine.active:
                engine_state = "active"
            else:
                engine_state = "inactive"
            parts_engines.append(PartInfo(stage=engine.part.stage, state=engine_state, decouple_stage=engine.part.decouple_stage))
    except Exception:
        parts_engines = []

    # Parts: RCS thrusters
    parts_rcs: list[PartInfo] = []
    try:
        for thruster in vessel.parts.rcs:
            rcs_state = "enabled" if thruster.enabled else "disabled"
            parts_rcs.append(PartInfo(stage=thruster.part.stage, state=rcs_state, decouple_stage=thruster.part.decouple_stage))
    except Exception:
        parts_rcs = []

    # Parts: intakes
    parts_intakes: list[PartInfo] = []
    try:
        for intake in vessel.parts.intakes:
            intake_state = "open" if intake.open else "closed"
            parts_intakes.append(PartInfo(stage=intake.part.stage, state=intake_state, decouple_stage=intake.part.decouple_stage))
    except Exception:
        parts_intakes = []

    # Parts: solar panels
    parts_solar_panels: list[PartInfo] = []
    try:
        for panel in vessel.parts.solar_panels:
            part = panel.part
            parts_solar_panels.append(PartInfo(stage=part.stage, state=_parse_part_state(str(panel.state)), decouple_stage=part.decouple_stage))
    except Exception:
        parts_solar_panels = []

    # Parts: radiators
    parts_radiators: list[PartInfo] = []
    try:
        for radiator in vessel.parts.radiators:
            part = radiator.part
            parts_radiators.append(PartInfo(stage=part.stage, state=_parse_part_state(str(radiator.state)), decouple_stage=part.decouple_stage))
    except Exception:
        parts_radiators = []

    # Parts: cargo bays
    parts_cargo_bays: list[PartInfo] = []
    try:
        for bay in vessel.parts.cargo_bays:
            bay_state = "open" if bay.open else "closed"
            parts_cargo_bays.append(PartInfo(stage=bay.part.stage, state=bay_state, decouple_stage=bay.part.decouple_stage))
    except Exception:
        parts_cargo_bays = []

    # Parts: docking ports
    parts_docking_ports: list[PartInfo] = []
    try:
        for port in vessel.parts.docking_ports:
            part = port.part
            parts_docking_ports.append(PartInfo(stage=part.stage, state=_parse_part_state(str(port.state)), decouple_stage=part.decouple_stage))
    except Exception:
        parts_docking_ports = []

    # Parts: reaction wheels
    parts_reaction_wheels: list[PartInfo] = []
    try:
        for wheel in vessel.parts.reaction_wheels:
            rw_state = "active" if wheel.active else "inactive"
            parts_reaction_wheels.append(PartInfo(stage=wheel.part.stage, state=rw_state, decouple_stage=wheel.part.decouple_stage))
    except Exception:
        parts_reaction_wheels = []

    # Parts: sensors
    parts_sensors: list[PartInfo] = []
    try:
        for sensor in vessel.parts.sensors:
            sensor_state = "active" if sensor.active else "inactive"
            parts_sensors.append(PartInfo(stage=sensor.part.stage, state=sensor_state, decouple_stage=sensor.part.decouple_stage))
    except Exception:
        parts_sensors = []

    # Parts: wheels
    parts_wheels: list[PartInfo] = []
    try:
        for wheel in vessel.parts.wheels:
            parts_wheels.append(PartInfo(stage=wheel.part.stage, state=_parse_part_state(str(wheel.state)), decouple_stage=wheel.part.decouple_stage))
    except Exception:
        parts_wheels = []

    # Parts: lights
    parts_lights: list[PartInfo] = []
    try:
        for light in vessel.parts.lights:
            light_state = "on" if light.active else "off"
            parts_lights.append(PartInfo(stage=light.part.stage, state=light_state, decouple_stage=light.part.decouple_stage))
    except Exception:
        parts_lights = []

    # Parts: antennas
    parts_antennas: list[PartInfo] = []
    try:
        for antenna in vessel.parts.antennas:
            part = antenna.part
            parts_antennas.append(PartInfo(stage=part.stage, state=_parse_part_state(str(antenna.state)), decouple_stage=part.decouple_stage))
    except Exception:
        parts_antennas = []

    # Parts: resource converters
    parts_resource_converters: list[PartInfo] = []
    try:
        for converter in vessel.parts.resource_converters:
            converter_state = "active" if converter.active(index=0) else "inactive"
            part = converter.part
            parts_resource_converters.append(PartInfo(stage=part.stage, state=converter_state, decouple_stage=part.decouple_stage))
    except Exception:
        parts_resource_converters = []

    # Parts: resource harvesters
    parts_resource_harvesters: list[PartInfo] = []
    try:
        for harvester in vessel.parts.resource_harvesters:
            harvester_state = "active" if harvester.active else "inactive"
            part = harvester.part
            parts_resource_harvesters.append(PartInfo(stage=part.stage, state=harvester_state, decouple_stage=part.decouple_stage))
    except Exception:
        parts_resource_harvesters = []

    # Maneuver nodes: snapshot every node on the vessel, in ut order.
    # burn_vector and burn_vector_remaining are captured in the body's
    # non-rotating frame so actions can build AutopilotDirection with
    # ReferenceFrame.BODY_NON_ROTATING without exposing kRPC frame objects.
    # burn_time_estimate uses Tsiolkovsky with current vessel mass, vacuum
    # Isp, and available thrust; kRPC does not expose burn time directly.
    maneuver_nodes: list[ManeuverNode] = []
    try:
        body_non_rotating_frame = orbit.body.non_rotating_reference_frame
        for idx, krpc_node in enumerate(vessel.control.nodes):
            try:
                post = krpc_node.orbit
                maneuver_nodes.append(
                    ManeuverNode(
                        index=idx,
                        ut=krpc_node.ut,
                        time_to=krpc_node.time_to,
                        delta_v=krpc_node.delta_v,
                        delta_v_remaining=krpc_node.remaining_delta_v,
                        prograde=krpc_node.prograde,
                        normal=krpc_node.normal,
                        radial=krpc_node.radial,
                        burn_vector=tuple(krpc_node.burn_vector(body_non_rotating_frame)),
                        burn_vector_remaining=tuple(krpc_node.remaining_burn_vector(body_non_rotating_frame)),
                        burn_time_estimate=tsiolkovsky_burn_time(
                            delta_v=krpc_node.remaining_delta_v,
                            mass=vessel.mass,
                            isp=vessel.vacuum_specific_impulse,
                            thrust=vessel.available_thrust,
                        ),
                        post_burn_orbit_apoapsis=post.apoapsis_altitude,
                        post_burn_orbit_periapsis=post.periapsis_altitude,
                        post_burn_orbit_eccentricity=post.eccentricity,
                        post_burn_orbit_inclination=post.inclination,
                        post_burn_orbit_period=post.period,
                        post_burn_orbit_semi_major_axis=post.semi_major_axis,
                    )
                )
            except Exception:
                continue
    except Exception:
        maneuver_nodes = []

    vessel_situation = _parse_vessel_situation(str(vessel.situation))
    science_situation = _derive_science_situation(
        situation=vessel_situation,
        altitude_sea=flight.mean_altitude,
        body=orbit.body,
    )

    # Equatorial nodes (AN/DN) and ballistic impact prediction.
    # Both are best-effort: failures fall back to "undefined" rather than
    # propagating, so older kRPC versions or partial test mocks still work.
    current_ut: float = float(conn.space_center.ut)  # type: ignore[attr-defined]
    an_ut, dn_ut, an_speed, dn_speed = _compute_equatorial_nodes(orbit, current_ut)
    predicted_impact = _compute_impact_prediction(vessel, orbit.body, current_ut)
    # Vessel forward (nose) direction in each frame the wait_for orientation
    # checks need. kRPC returns a unit vector in the requested frame.
    direction_orbital: tuple[float, float, float] = tuple(vessel.direction(vessel.orbital_reference_frame))
    direction_surface_velocity: tuple[float, float, float] = tuple(vessel.direction(vessel.surface_velocity_reference_frame))
    direction_body_non_rotating: tuple[float, float, float] = tuple(vessel.direction(orbit.body.non_rotating_reference_frame))

    return State(
        altitude_sea=flight.mean_altitude,
        altitude_surface=flight.surface_altitude,
        speed_vertical=flight.vertical_speed,
        speed_surface=flight.speed,
        speed_orbital=orbit.speed,
        speed_horizontal=flight.horizontal_speed,
        pressure_dynamic=flight.dynamic_pressure,
        pressure_static=flight.static_pressure,
        aero_drag=flight.drag,
        aero_lift=flight.lift,
        aero_mach=flight.mach,
        aero_angle_of_attack=flight.angle_of_attack,
        aero_terminal_velocity=flight.terminal_velocity,
        g_force=flight.g_force,
        orbit_apoapsis=orbit.apoapsis_altitude,
        orbit_periapsis=orbit.periapsis_altitude,
        orbit_inclination=orbit.inclination,
        orbit_eccentricity=orbit.eccentricity,
        orbit_period=orbit.period,
        orbit_semi_major_axis=orbit.semi_major_axis,
        orbit_apoapsis_time_to=orbit.time_to_apoapsis,
        orbit_apoapsis_time_from=orbit.period - orbit.time_to_apoapsis,
        orbit_apoapsis_passed=not (0 <= orbit.true_anomaly <= math.pi),
        orbit_periapsis_time_to=orbit.time_to_periapsis,
        orbit_periapsis_time_from=orbit.period - orbit.time_to_periapsis,
        orbit_periapsis_passed=0 < orbit.true_anomaly < math.pi,
        orbit_soi_time_to_change=orbit_soi_time_to_change,
        orbit_ascending_node_ut=an_ut,
        orbit_descending_node_ut=dn_ut,
        orbit_ascending_node_speed=an_speed,
        orbit_descending_node_speed=dn_speed,
        universal_time=current_ut,
        met=vessel.met,
        name=vessel.name,
        situation=vessel_situation,
        mass=vessel.mass,
        mass_dry=vessel.dry_mass,
        thrust=vessel.thrust,
        thrust_available=vessel.available_thrust,
        thrust_peak=vessel.max_thrust,
        engine_impulse_specific=vessel.specific_impulse,
        engine_impulse_specific_vacuum=vessel.vacuum_specific_impulse,
        body_name=orbit.body.name,
        body_radius=orbit.body.equatorial_radius,
        body_gravity=orbit.body.surface_gravity,
        body_has_atmosphere=orbit.body.has_atmosphere,
        body_atmosphere_depth=orbit.body.atmosphere_depth if orbit.body.has_atmosphere else 0.0,
        body_gm=orbit.body.gravitational_parameter,
        body_soi=orbit.body.sphere_of_influence,
        body_rotational_period=getattr(orbit.body, "rotational_period", 21549.425),
        position_biome=vessel.biome,
        position_latitude=flight.latitude,
        position_longitude=flight.longitude,
        orientation_pitch=surface_flight.pitch,
        orientation_heading=surface_flight.heading,
        orientation_roll=surface_flight.roll,
        orientation_direction_orbital=direction_orbital,
        orientation_direction_surface_velocity=direction_surface_velocity,
        orientation_direction_body_non_rotating=direction_body_non_rotating,
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
        control_stage_lock=control.stage_lock,
        control_reaction_wheels=control.reaction_wheels,
        control_wheel_throttle=control.wheel_throttle,
        control_wheel_steering=control.wheel_steering,
        control_translate_forward=control.forward,
        control_translate_right=control.right,
        control_translate_up=control.up,
        stage_current=control.current_stage,
        engine_flameout_count=sum(1 for e in vessel.parts.engines if e.active and not e.has_fuel),
        control_deployable_solar_panels=control.solar_panels,
        control_deployable_antennas=control.antennas,
        control_deployable_cargo_bays=control.cargo_bays,
        control_deployable_intakes=control.intakes,
        control_deployable_parachutes=control.parachutes,
        control_deployable_radiators=control.radiators,
        comms_connected=comms_connected,
        comms_signal_strength=comms_signal_strength,
        resource_electric_charge=vessel.resources.amount("ElectricCharge"),
        resource_liquid_fuel=vessel.resources.amount("LiquidFuel"),
        resource_oxidizer=vessel.resources.amount("Oxidizer"),
        resource_mono_propellant=vessel.resources.amount("MonoPropellant"),
        resource_electric_charge_max=vessel.resources.max("ElectricCharge"),
        resource_liquid_fuel_max=vessel.resources.max("LiquidFuel"),
        resource_oxidizer_max=vessel.resources.max("Oxidizer"),
        resource_mono_propellant_max=vessel.resources.max("MonoPropellant"),
        science_experiments=tuple(science_experiments),
        science_situation=science_situation,
        nodes=tuple(maneuver_nodes),
        predicted_impact=predicted_impact,
        parts=Parts(
            parachutes=tuple(parts_parachutes),
            legs=tuple(parts_legs),
            fairings=tuple(parts_fairings),
            decouplers=tuple(parts_decouplers),
            launch_clamps=tuple(parts_launch_clamps),
            engines=tuple(parts_engines),
            rcs=tuple(parts_rcs),
            intakes=tuple(parts_intakes),
            solar_panels=tuple(parts_solar_panels),
            radiators=tuple(parts_radiators),
            cargo_bays=tuple(parts_cargo_bays),
            docking_ports=tuple(parts_docking_ports),
            reaction_wheels=tuple(parts_reaction_wheels),
            sensors=tuple(parts_sensors),
            wheels=tuple(parts_wheels),
            lights=tuple(parts_lights),
            antennas=tuple(parts_antennas),
            resource_converters=tuple(parts_resource_converters),
            resource_harvesters=tuple(parts_resource_harvesters),
        ),
    )


def filter_commands(commands: VesselCommands, state: State) -> tuple[VesselCommands, frozenset[str]]:
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
        if value is None or value == ():
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
    if controls.stage_lock is not None:
        vc.stage_lock = controls.stage_lock

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
            ReferenceFrame.VESSEL_SURFACE_VELOCITY: vessel.surface_velocity_reference_frame,
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
    if controls.reaction_wheels is not None:
        vc.reaction_wheels = controls.reaction_wheels
    if controls.wheel_throttle is not None:
        vc.wheel_throttle = controls.wheel_throttle
    if controls.wheel_steering is not None:
        vc.wheel_steering = controls.wheel_steering
    if controls.abort is not None:
        vc.abort = controls.abort
    # Science experiments
    if controls.all_science is not None:
        experiments = vessel.parts.experiments
        for exp in experiments:
            _apply_science_action(exp, controls.all_science)
    if controls.science_commands:
        experiments = vessel.parts.experiments
        for cmd in controls.science_commands:
            if 0 <= cmd.experiment_index < len(experiments):
                _apply_science_action(experiments[cmd.experiment_index], cmd.action)

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

    # Maneuver nodes: remove first so a "replace" pattern (remove + create in
    # the same tick) is unambiguous about ordering.
    if controls.remove_node_at_ut is not None:
        target_ut = controls.remove_node_at_ut
        for krpc_node in list(vc.nodes):
            if abs(krpc_node.ut - target_ut) <= _NODE_UT_MATCH_TOLERANCE:
                krpc_node.remove()
                break
    if controls.create_node is not None:
        burn = controls.create_node
        vc.add_node(burn.ut, prograde=burn.prograde, normal=burn.normal, radial=burn.radial)


def list_launchable_vessels(conn: object) -> list[str]:
    """Return the names of launchable VAB craft in the current save."""
    return list(conn.space_center.launchable_vessels("VAB"))  # type: ignore[attr-defined]


def launch_vessel_from_vab(conn: object, craft_name: str) -> None:
    """Launch a VAB craft to the launch pad via kRPC.

    Recovers any pre-launch vessel before spawning so their crew is returned
    to the astronaut complex rather than going missing.
    """
    sc = conn.space_center  # type: ignore[attr-defined]
    for vessel in list(sc.vessels):
        if "pre_launch" in str(vessel.situation).lower():
            vessel.recover()
    sc.launch_vessel_from_vab(craft_name)


def get_active_vessel_name(conn: object) -> str:
    """Return the active vessel's name. Raises if there is no active vessel."""
    sc = conn.space_center  # type: ignore[attr-defined]
    vessel = sc.active_vessel
    if vessel is None:
        raise NoActiveVesselError("No active vessel")
    return str(vessel.name)
