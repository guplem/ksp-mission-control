"""Core types for the action execution system.

Defines the Action ABC, VesselState, VesselCommands, and supporting types.
Actions are pure functions of VesselState → VesselCommands, never touching
kRPC directly. See ADR 0006 for rationale.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar

_STANDARD_GRAVITY = 9.80665  # m/s^2, used in Tsiolkovsky rocket equation


class LogLevel(Enum):
    """Severity level for action debug log entries."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


@dataclass(frozen=True)
class LogEntry:
    """Single log entry emitted by an action."""

    level: LogLevel
    message: str


class ActionLogger:
    """Collects typed log entries during a tick or stop call.

    Actions receive an instance and call ``log.debug()``, ``log.info()``, etc.
    The runner reads ``log.entries`` after the call returns.
    """

    def __init__(self) -> None:
        self.entries: list[LogEntry] = []

    def debug(self, message: str) -> None:
        self.entries.append(LogEntry(level=LogLevel.DEBUG, message=message))

    def info(self, message: str) -> None:
        self.entries.append(LogEntry(level=LogLevel.INFO, message=message))

    def warn(self, message: str) -> None:
        self.entries.append(LogEntry(level=LogLevel.WARN, message=message))

    def error(self, message: str) -> None:
        self.entries.append(LogEntry(level=LogLevel.ERROR, message=message))


class SpeedMode(Enum):
    """Navball speed display mode, matching kRPC's SpeedMode enum members."""

    ORBIT = "orbit"
    SURFACE = "surface"
    TARGET = "target"

    @property
    def display_name(self) -> str:
        """Human-readable label (e.g. 'Orbit', 'Surface')."""
        return self.value.replace("_", " ").title()


class SASMode(Enum):
    """SAS autopilot mode, matching kRPC's SASMode enum members."""

    STABILITY_ASSIST = "stability_assist"
    MANEUVER = "maneuver"
    PROGRADE = "prograde"
    RETROGRADE = "retrograde"
    NORMAL = "normal"
    ANTI_NORMAL = "anti_normal"
    RADIAL = "radial"
    ANTI_RADIAL = "anti_radial"
    TARGET = "target"
    ANTI_TARGET = "anti_target"

    @property
    def display_name(self) -> str:
        """Human-readable label (e.g. 'Radial', 'Anti Normal')."""
        return self.value.replace("_", " ").title()


class VesselSituation(Enum):
    """Flight situation of the vessel, matching kRPC's VesselSituation enum members."""

    PRE_LAUNCH = "pre_launch"
    FLYING = "flying"
    SUB_ORBITAL = "sub_orbital"
    ORBITING = "orbiting"
    ESCAPING = "escaping"
    LANDED = "landed"
    SPLASHED = "splashed"
    DOCKED = "docked"

    @property
    def display_name(self) -> str:
        """Human-readable label (e.g. 'Pre Launch', 'Sub Orbital')."""
        return self.value.replace("_", " ").title()


class ReferenceFrame(Enum):
    """Coordinate reference frame for autopilot direction vectors.

    Maps to kRPC reference frame objects in the bridge. Use with
    AutopilotDirection to point the vessel at an arbitrary 3D vector.

    Members:
        VESSEL_SURFACE: Aligned with the vessel's surface position.
            +x = zenith (up), +y = north, +z = east.
        VESSEL_ORBITAL: Aligned with the vessel's orbital velocity.
            +x = prograde, +y = normal, +z = radial.
        VESSEL: The vessel's own reference frame (moves and rotates with it).
            +x = vessel right, +y = vessel forward, +z = vessel down.
        BODY: Centered on the orbited body, rotates with it.
            Useful for targeting fixed surface locations.
        BODY_NON_ROTATING: Centered on the orbited body, does not rotate.
            Useful for targeting celestial directions.
    """

    VESSEL_SURFACE = "vessel_surface"
    VESSEL_ORBITAL = "vessel_orbital"
    VESSEL = "vessel"
    BODY = "body"
    BODY_NON_ROTATING = "body_non_rotating"

    @property
    def display_name(self) -> str:
        """Human-readable label (e.g. 'Vessel Surface', 'Body Non Rotating')."""
        return self.value.replace("_", " ").title()


class ActionStatus(Enum):
    """Lifecycle status of an action."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class ActionResult:
    """Outcome of a single action tick."""

    status: ActionStatus
    message: str = ""


class ParamType(Enum):
    """Data type of an action parameter."""

    FLOAT = "float"
    BOOL = "bool"
    STR = "str"


@dataclass(frozen=True)
class ActionParam:
    """Typed parameter descriptor for an action.

    Each action declares its parameters as a list of these descriptors.
    The runner validates that all required params are provided before starting.
    """

    param_id: str
    label: str
    description: str
    required: bool
    param_type: ParamType = ParamType.FLOAT
    default: float | bool | str | None = None
    unit: str = ""


@dataclass(frozen=True)
class AutopilotDirection:
    """Target direction for the kRPC autopilot as a 3D vector in a reference frame.

    Instead of pitch/heading angles, this lets you point the vessel at an
    arbitrary direction vector. Useful for orbit-relative maneuvers or
    targeting celestial directions.

    Example::

        # Point prograde in the orbital frame:
        commands.autopilot_direction = AutopilotDirection(
            vector=(1.0, 0.0, 0.0),
            reference_frame=ReferenceFrame.VESSEL_ORBITAL,
        )

    Note: Setting autopilot_direction overrides autopilot_pitch/autopilot_heading.
    """

    vector: tuple[float, float, float]
    """Direction vector (x, y, z) in the chosen reference frame."""
    reference_frame: ReferenceFrame
    """Coordinate frame that the vector is expressed in."""


@dataclass(frozen=True)
class AutopilotConfig:
    """PID tuning configuration for the kRPC autopilot.

    Controls how aggressively the autopilot rotates the vessel toward its
    target orientation. All tuple fields are per-axis: (pitch, yaw, roll).

    By default, kRPC auto-tunes PID gains based on the vessel's moment of
    inertia and available torque. You can adjust auto-tune targets
    (time_to_peak, overshoot) or disable auto-tune entirely and provide
    manual PID gains.

    Examples::

        # Reset to automatic tuning with kRPC defaults:
        commands.autopilot_config = AutopilotConfig.AUTO

        # Auto-tune but respond faster (1s instead of 3s to peak):
        commands.autopilot_config = AutopilotConfig(time_to_peak=(1.0, 1.0, 1.0))

        # Fully manual PID gains (disables auto-tune):
        commands.autopilot_config = AutopilotConfig(
            auto_tune=False,
            pitch_pid_gains=(2.0, 0.0, 0.5),
            yaw_pid_gains=(2.0, 0.0, 0.5),
            roll_pid_gains=(1.0, 0.0, 0.3),
        )

    Fields:
        auto_tune: When True, kRPC calculates PID gains from vessel properties.
            time_to_peak and overshoot guide the auto-tuner. When False, you
            must provide manual PID gains via pitch/yaw/roll_pid_gains.
        time_to_peak: Target time (seconds) to reach the target orientation
            per axis. Lower = snappier response but more overshoot risk.
        overshoot: Target overshoot fraction (0.01 = 1%) per axis.
            Lower = more precise but slower to settle.
        stopping_time: Max time (seconds) to kill angular rotation per axis.
            Controls the maximum angular velocity the autopilot allows.
        deceleration_time: Time (seconds) to decelerate as it approaches the
            target per axis. Higher = smoother but slower approach.
        attenuation_angle: Angle (degrees) at which the autopilot starts
            attenuating velocity per axis. Fine-tuning for near-target behavior.
        roll_threshold: Angle (degrees) the vessel must be within the target
            direction before the autopilot starts correcting roll.
        pitch_pid_gains: Manual (Kp, Ki, Kd) gains for pitch. Ignored when
            auto_tune is True (overwritten by auto-tuner).
        yaw_pid_gains: Manual (Kp, Ki, Kd) gains for yaw.
        roll_pid_gains: Manual (Kp, Ki, Kd) gains for roll.
    """

    AUTO: ClassVar[AutopilotConfig]
    """Convenience constant: automatic tuning with kRPC defaults."""

    auto_tune: bool = True
    time_to_peak: tuple[float, float, float] = (3.0, 3.0, 3.0)
    overshoot: tuple[float, float, float] = (0.01, 0.01, 0.01)
    stopping_time: tuple[float, float, float] = (0.5, 0.5, 0.5)
    deceleration_time: tuple[float, float, float] = (5.0, 5.0, 5.0)
    attenuation_angle: tuple[float, float, float] = (1.0, 1.0, 1.0)
    roll_threshold: float = 5.0
    pitch_pid_gains: tuple[float, float, float] | None = None
    yaw_pid_gains: tuple[float, float, float] | None = None
    roll_pid_gains: tuple[float, float, float] | None = None


AutopilotConfig.AUTO = AutopilotConfig()


@dataclass(frozen=True)
class VesselState:
    """Immutable snapshot of vessel telemetry.

    Pure dataclass — no kRPC or Textual imports. All fields default to
    zero/empty so tests can construct partial states.
    """

    # --- Flight ---
    altitude_sea: float = 0.0
    """Mean altitude above sea level, in meters."""
    altitude_surface: float = 0.0
    """Altitude above the terrain surface, in meters."""
    speed_vertical: float = 0.0
    """Vertical velocity in m/s. Positive = ascending, negative = descending."""
    speed_surface: float = 0.0
    """Speed relative to the surface of the body, in m/s."""
    speed_orbital: float = 0.0
    """Speed relative to the orbited body's center of mass, in m/s."""
    speed_horizontal: float = 0.0
    """Speed component parallel to the surface, in m/s."""

    # --- Atmosphere ---
    pressure_dynamic: float = 0.0
    """Dynamic pressure (0.5 * air_density * velocity^2), in Pascals. 0 in vacuum."""
    pressure_static: float = 0.0
    """Atmospheric static pressure, in Pascals. 0 in vacuum."""
    aero_drag: tuple[float, float, float] = (0.0, 0.0, 0.0)
    """Aerodynamic drag force vector, in Newtons. (0,0,0) in vacuum."""
    aero_lift: tuple[float, float, float] = (0.0, 0.0, 0.0)
    """Aerodynamic lift force vector, in Newtons. (0,0,0) in vacuum."""
    aero_mach: float = 0.0
    """Mach number (speed / speed of sound). 0 in vacuum."""
    aero_angle_of_attack: float = 0.0
    """Angle between vessel orientation and velocity vector, in degrees. 0 in vacuum."""
    aero_terminal_velocity: float = 0.0
    """Speed at which drag equals gravity, in m/s. 0 in vacuum."""
    g_force: float = 0.0
    """Current g-force experienced by the vessel. 1.0 on Kerbin's surface at rest."""

    # --- Orbit ---
    orbit_apoapsis: float = 0.0
    """Highest point of the orbit above sea level, in meters."""
    orbit_periapsis: float = 0.0
    """Lowest point of the orbit above sea level, in meters."""
    orbit_inclination: float = 0.0
    """Orbital inclination relative to the equator, in degrees."""
    orbit_eccentricity: float = 0.0
    """Orbital eccentricity. 0 = circular, 0-1 = elliptical, 1 = parabolic."""
    orbit_period: float = 0.0
    """Time for one complete orbit, in seconds."""
    orbit_apoapsis_time_to: float = 0.0
    """Time until apoapsis, in seconds."""
    orbit_periapsis_time_to: float = 0.0
    """Time until periapsis, in seconds."""
    orbit_soi_time_to: float = float("inf")
    """Time until sphere of influence transition, in seconds. inf if no transition upcoming."""

    # --- Vessel ---
    universal_time: float = 0.0
    """Universal game time, in seconds. Not vessel-specific but needed for maneuver timing."""
    met: float = 0.0
    """Mission Elapsed Time since launch, in seconds."""
    name: str = ""
    """Name of the active vessel."""
    situation: VesselSituation = VesselSituation.PRE_LAUNCH
    """Current flight situation (e.g. PRE_LAUNCH, FLYING, ORBITING, LANDED)."""
    mass: float = 0.0
    """Total vessel mass including fuel, in kilograms."""
    mass_dry: float = 0.0
    """Vessel mass without fuel, in kilograms."""
    thrust: float = 0.0
    """Thrust being produced right now. Accounts for throttle, atmosphere, and fuel. 0 when engines are off."""
    thrust_available: float = 0.0
    """Full-throttle thrust from engines that still have fuel. Excludes flamed-out engines. Does NOT account for throttle."""
    thrust_peak: float = 0.0
    """Full-throttle thrust from ALL active engines, including flamed-out ones. Does NOT account for throttle or fuel state."""
    engine_impulse_specific: float = 0.0
    """Current overall specific impulse, in seconds. 0 if no active engines."""
    engine_impulse_specific_vacuum: float = 0.0
    """Specific impulse in vacuum, in seconds. Reference value for delta-v calculations."""

    # --- Position ---
    body_name: str = ""
    """Name of the celestial body being orbited (e.g. 'Kerbin', 'Mun')."""
    body_radius: float = 600000.0
    """Equatorial radius of the orbited body, in meters. Defaults to Kerbin."""
    body_gravity: float = 9.81
    """Surface gravitational acceleration of the orbited body, in m/s^2. Defaults to Kerbin."""
    body_has_atmosphere: bool = True
    """Whether the orbited body has an atmosphere at all (e.g. Kerbin=True, Mun=False)."""
    body_atmosphere_depth: float = 70000.0
    """Maximum altitude of the body's atmosphere, in meters. 0 if no atmosphere. Kerbin=70km."""
    body_gm: float = 0.0
    """Gravitational parameter (GM) of the orbited body, in m^3/s^2."""
    body_soi: float = 0.0
    """Sphere of influence radius of the orbited body, in meters."""
    position_latitude: float = 0.0
    """Geographic latitude on the body surface, in degrees. -90 to 90."""
    position_longitude: float = 0.0
    """Geographic longitude on the body surface, in degrees. -180 to 180."""

    # --- Orientation ---
    orientation_pitch: float = 0.0
    """Vessel pitch angle in degrees. 0 = horizontal, 90 = straight up."""
    orientation_heading: float = 0.0
    """Vessel heading in degrees. 0 = north, 90 = east, 180 = south, 270 = west."""
    orientation_roll: float = 0.0
    """Vessel roll angle in degrees."""

    # --- Control ---
    control_input_pitch: float = 0.0
    """Current pitch control input. -1.0 = nose down, 1.0 = nose up."""
    control_input_yaw: float = 0.0
    """Current yaw control input. -1.0 = left, 1.0 = right."""
    control_input_roll: float = 0.0
    """Current roll control input. -1.0 = counter-clockwise, 1.0 = clockwise."""
    control_autopilot: bool = False
    """Whether the kRPC autopilot is currently engaged."""
    control_autopilot_target_pitch: float = 0.0
    """Autopilot's current target pitch, in degrees."""
    control_autopilot_target_heading: float = 0.0
    """Autopilot's current target heading, in degrees."""
    control_autopilot_target_roll: float = 0.0
    """Autopilot's current target roll, in degrees. NaN = roll targeting disabled."""
    control_autopilot_error: float | None = None
    """Angular error between current and target direction, in degrees. None when autopilot not engaged."""
    control_autopilot_error_pitch: float | None = None
    """Pitch error between current and target, in degrees. None when autopilot not engaged."""
    control_autopilot_error_heading: float | None = None
    """Heading error between current and target, in degrees. None when autopilot not engaged."""
    control_autopilot_error_roll: float | None = None
    """Roll error between current and target, in degrees. None when autopilot not engaged."""
    control_throttle: float = 0.0
    """Current throttle setting. 0.0 = off, 1.0 = full thrust."""
    control_sas: bool = False
    """Whether the Stability Assist System is enabled."""
    control_sas_mode: SASMode | None = None
    """Active SAS autopilot mode. None when SAS is off."""
    control_ui_speed_mode: SpeedMode = SpeedMode.ORBIT
    """Navball speed display mode (orbit, surface, or target)."""
    control_rcs: bool = False
    """Whether the Reaction Control System is enabled."""
    control_gear: bool = False
    """Whether landing gear is deployed."""
    control_legs: bool = False
    """Whether landing legs are deployed."""
    control_lights: bool = False
    """Whether vessel lights are on."""
    control_brakes: bool = False
    """Whether brakes are engaged."""
    control_wheels: bool = False
    """Whether wheel motors are active."""
    control_abort: bool = False
    """Whether the abort action group has been triggered."""
    control_stage_lock: bool = False
    """Whether staging is locked (prevents accidental staging)."""
    control_reaction_wheels: bool = True
    """Whether reaction wheels are active."""
    control_wheel_throttle: float = 0.0
    """Wheel motor throttle. -1.0 = full reverse, 1.0 = full forward."""
    control_wheel_steering: float = 0.0
    """Wheel steering input. -1.0 = full left, 1.0 = full right."""
    control_translate_forward: float = 0.0
    """RCS translation forward/backward. -1.0 = backward, 1.0 = forward."""
    control_translate_right: float = 0.0
    """RCS translation left/right. -1.0 = left, 1.0 = right."""
    control_translate_up: float = 0.0
    """RCS translation down/up. -1.0 = down, 1.0 = up."""
    stage_current: int = 0
    """Currently active stage number."""
    stage_max: int = 0
    """Total number of stages on the vessel."""
    engine_flameout_count: int = 0
    """Number of active engines that have run out of fuel (flameout)."""

    # --- Deployables ---
    control_deployable_solar_panels: bool = False
    """Whether solar panels are deployed."""
    control_deployable_antennas: bool = False
    """Whether antennas are deployed."""
    control_deployable_cargo_bays: bool = False
    """Whether cargo bays are open."""
    control_deployable_intakes: bool = False
    """Whether air intakes are open."""
    control_deployable_parachutes: bool = False
    """Whether parachutes are deployed."""
    control_deployable_radiators: bool = False
    """Whether radiators are deployed."""

    # --- Comms ---
    comms_connected: bool = False
    """Whether the vessel can communicate with KSC."""
    comms_signal_strength: float = 0.0
    """Signal strength to KSC. 0.0 = no signal, 1.0 = full strength."""

    # --- Resources ---
    resource_electric_charge: float = 0.0
    """Available electric charge, in units."""
    resource_liquid_fuel: float = 0.0
    """Available liquid fuel, in units."""
    resource_oxidizer: float = 0.0
    """Available oxidizer, in units."""
    resource_mono_propellant: float = 0.0
    """Available monopropellant (RCS fuel), in units."""
    resource_electric_charge_max: float = 0.0
    """Maximum electric charge capacity, in units."""
    resource_liquid_fuel_max: float = 0.0
    """Maximum liquid fuel capacity, in units."""
    resource_oxidizer_max: float = 0.0
    """Maximum oxidizer capacity, in units."""
    resource_mono_propellant_max: float = 0.0
    """Maximum monopropellant capacity, in units."""

    # --- Derived properties (computed from raw telemetry) ---

    @property
    def weight(self) -> float:
        """Gravitational force on the vessel (mass * local gravity), in Newtons.

        Returns 0.0 if mass or body gravity is zero.
        """
        return self.mass * self.body_gravity

    @property
    def twr(self) -> float:
        """Current thrust-to-weight ratio (actual thrust at current throttle).

        Returns 0.0 if mass or body gravity is zero.
        """
        if self.weight <= 0.0:
            return 0.0
        return self.thrust / self.weight

    @property
    def max_twr(self) -> float:
        """Maximum thrust-to-weight ratio at full throttle in current conditions.

        Returns 0.0 if mass or body gravity is zero.
        """
        if self.weight <= 0.0:
            return 0.0
        return self.thrust_peak / self.weight

    @property
    def delta_v(self) -> float:
        """Remaining delta-v via Tsiolkovsky rocket equation: Isp * g0 * ln(m0/m1).

        Uses current impulse_specific and standard gravity (9.80665 m/s^2).
        Returns 0.0 if no engines, no fuel, or mass_dry is zero.
        """
        if self.engine_impulse_specific <= 0.0 or self.mass_dry <= 0.0 or self.mass <= self.mass_dry:
            return 0.0
        return self.engine_impulse_specific * _STANDARD_GRAVITY * math.log(self.mass / self.mass_dry)

    @property
    def fuel_fraction(self) -> float:
        """Fraction of vessel mass that is fuel (0.0 to 1.0).

        Returns 0.0 if total mass is zero.
        """
        if self.mass <= 0.0:
            return 0.0
        return (self.mass - self.mass_dry) / self.mass

    @property
    def resource_electric_charge_fraction(self) -> float:
        """Fraction of electric charge remaining (0.0 to 1.0). 0.0 if no capacity."""
        if self.resource_electric_charge_max <= 0.0:
            return 0.0
        return self.resource_electric_charge / self.resource_electric_charge_max

    @property
    def resource_liquid_fuel_fraction(self) -> float:
        """Fraction of liquid fuel remaining (0.0 to 1.0). 0.0 if no capacity."""
        if self.resource_liquid_fuel_max <= 0.0:
            return 0.0
        return self.resource_liquid_fuel / self.resource_liquid_fuel_max

    @property
    def resource_oxidizer_fraction(self) -> float:
        """Fraction of oxidizer remaining (0.0 to 1.0). 0.0 if no capacity."""
        if self.resource_oxidizer_max <= 0.0:
            return 0.0
        return self.resource_oxidizer / self.resource_oxidizer_max

    @property
    def resource_mono_propellant_fraction(self) -> float:
        """Fraction of monopropellant remaining (0.0 to 1.0). 0.0 if no capacity."""
        if self.resource_mono_propellant_max <= 0.0:
            return 0.0
        return self.resource_mono_propellant / self.resource_mono_propellant_max

    @property
    def time_to_impact(self) -> float:
        """Estimated seconds until surface contact, assuming constant descent rate.

        Returns ``float('inf')`` if the vessel is not descending or is on the ground.
        Uses altitude_surface / abs(speed_vertical) as a linear estimate.
        """
        if self.speed_vertical >= 0.0 or self.altitude_surface <= 0.0:
            return float("inf")
        return self.altitude_surface / abs(self.speed_vertical)

    @property
    def in_atmosphere(self) -> bool:
        """Whether the vessel is currently experiencing atmospheric pressure."""
        return self.pressure_static > 0.0

    @property
    def above_atmosphere(self) -> bool:
        """Whether the vessel is above the body's atmosphere (or the body has none).

        True if the body has no atmosphere, or the vessel's sea-level altitude
        exceeds the atmosphere depth.
        """
        if not self.body_has_atmosphere:
            return True
        return self.altitude_sea > self.body_atmosphere_depth

    @property
    def has_atmosphere(self) -> bool:
        """Whether the vessel is currently in an atmosphere (static pressure > 0)."""
        return self.pressure_static > 0.0

    @property
    def is_landed(self) -> bool:
        """Whether the vessel is on the ground (LANDED or SPLASHED)."""
        return self.situation in (VesselSituation.LANDED, VesselSituation.SPLASHED)

    @property
    def is_flying(self) -> bool:
        """Whether the vessel is in atmospheric flight (FLYING or SUB_ORBITAL)."""
        return self.situation in (VesselSituation.FLYING, VesselSituation.SUB_ORBITAL)

    @property
    def is_suborbital(self) -> bool:
        """Whether the vessel is on a suborbital trajectory."""
        return self.situation == VesselSituation.SUB_ORBITAL

    @property
    def is_orbiting(self) -> bool:
        """Whether the vessel is in a stable orbit or escaping (ORBITING or ESCAPING)."""
        return self.situation in (VesselSituation.ORBITING, VesselSituation.ESCAPING)

    @property
    def is_ascending(self) -> bool:
        """Whether the vessel is moving upward (positive vertical speed)."""
        return self.speed_vertical > 0.0

    @property
    def is_descending(self) -> bool:
        """Whether the vessel is moving downward (negative vertical speed)."""
        return self.speed_vertical < 0.0


@dataclass
class VesselCommands:
    """Mutable command buffer for vessel control outputs.

    All fields default to None meaning "don't change this tick."
    Actions mutate this in tick(); the runner applies non-None fields to kRPC.
    """

    # --- Throttle & staging ---
    throttle: float | None = None
    """Main engine throttle. 0.0 = off, 1.0 = full thrust."""
    stage: bool | None = None
    """Set to True to activate the next stage this tick."""
    stage_lock: bool | None = None
    """Lock/unlock staging. True = prevent staging, False = allow staging."""

    # --- Rotation axes (-1.0 to 1.0, raw stick input) ---
    input_pitch: float | None = None
    """Pitch axis input. -1.0 = nose down, 1.0 = nose up."""
    input_yaw: float | None = None
    """Yaw axis input. -1.0 = left, 1.0 = right."""
    input_roll: float | None = None
    """Roll axis input. -1.0 = counter-clockwise, 1.0 = clockwise."""

    # --- Translation axes (-1.0 to 1.0, RCS input) ---
    translate_forward: float | None = None
    """RCS forward/backward. -1.0 = backward, 1.0 = forward."""
    translate_right: float | None = None
    """RCS left/right. -1.0 = left, 1.0 = right."""
    translate_up: float | None = None
    """RCS down/up. -1.0 = down, 1.0 = up."""

    # --- Autopilot (kRPC auto_pilot, separate from SAS) ---
    autopilot: bool | None = None
    """kRPC autopilot. True = engage, False = disengage. Overrides SAS when active."""
    autopilot_pitch: float | None = None
    """Autopilot target pitch in degrees. 0 = horizontal, 90 = straight up."""
    autopilot_heading: float | None = None
    """Autopilot target heading in degrees. 0 = north, 90 = east, 180 = south, 270 = west."""
    autopilot_roll: float | None = None
    """Autopilot target roll in degrees. Set to NaN to disable roll targeting."""
    autopilot_direction: AutopilotDirection | None = None
    """Target direction as a 3D vector. Overrides autopilot_pitch/autopilot_heading when set."""
    autopilot_config: AutopilotConfig | None = None
    """PID tuning for the autopilot. None = don't change. AutopilotConfig.AUTO = reset to auto."""

    # --- Systems ---
    sas: bool | None = None
    """Stability Assist System. True = enable, False = disable."""
    sas_mode: SASMode | None = None
    """SAS autopilot mode."""
    ui_speed_mode: SpeedMode | None = None
    """Navball speed display mode."""
    rcs: bool | None = None
    """Reaction Control System. True = enable, False = disable."""
    gear: bool | None = None
    """Landing gear. True = deploy, False = retract."""
    legs: bool | None = None
    """Landing legs. True = deploy, False = retract."""
    lights: bool | None = None
    """Vessel lights. True = on, False = off."""
    brakes: bool | None = None
    """Brakes. True = engage, False = release."""
    wheels: bool | None = None
    """Wheel motor. True = on, False = off."""
    reaction_wheels: bool | None = None
    """Reaction wheels. True = active, False = disabled."""
    wheel_throttle: float | None = None
    """Wheel motor throttle. -1.0 = full reverse, 1.0 = full forward."""
    wheel_steering: float | None = None
    """Wheel steering. -1.0 = full left, 1.0 = full right."""
    abort: bool | None = None
    """Abort action group. True = trigger."""

    # --- Deployables ---
    deployable_solar_panels: bool | None = None
    """Solar panels. True = deploy, False = retract."""
    deployable_antennas: bool | None = None
    """Antennas. True = deploy, False = retract."""
    deployable_cargo_bays: bool | None = None
    """Cargo bays. True = open, False = close."""
    deployable_intakes: bool | None = None
    """Air intakes. True = open, False = close."""
    deployable_parachutes: bool | None = None
    """Parachutes. True = deploy."""
    deployable_radiators: bool | None = None
    """Radiators. True = deploy, False = retract."""


class Action(ABC):
    """Base class for a vessel action.

    Subclasses declare ClassVar metadata and implement the tick lifecycle.
    Actions never touch kRPC directly — they read VesselState and mutate
    VesselCommands.
    """

    action_id: ClassVar[str]
    """Unique identifier for this action type."""

    label: ClassVar[str]
    """Human-readable name shown in the action list."""

    description: ClassVar[str]
    """Short description of what this action does."""

    params: ClassVar[list[ActionParam]]
    """Typed parameter descriptors for this action."""

    @abstractmethod
    def start(self, state: VesselState, param_values: dict[str, Any]) -> None:
        """Initialize internal state from parameter values.

        Called once before the first tick. *state* is the current vessel
        telemetry so actions can capture initial conditions.
        """

    @abstractmethod
    def tick(self, state: VesselState, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        """Execute one step of the action.

        Read from *state*, mutate *commands* to express desired changes,
        call *log.debug()/.info()/.warn()/.error()* to emit messages,
        and return an ActionResult indicating lifecycle status.
        """

    def stop(self, state: VesselState, commands: VesselCommands, log: ActionLogger) -> None:
        """Clean up on abort or completion.

        Default implementation logs the stop. Subclasses override for custom
        cleanup. *state* is the last known vessel telemetry so actions can
        make informed cleanup decisions.
        """
        log.info(f"{self.label} stopped")
