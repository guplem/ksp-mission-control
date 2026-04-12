"""Core types for the action execution system.

Defines the Action ABC, VesselState, VesselCommands, and supporting types.
Actions are pure functions of VesselState → VesselCommands, never touching
kRPC directly. See ADR 0006 for rationale.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar


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
    default: float | None = None
    unit: str = ""


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
    vertical_speed: float = 0.0
    """Vertical velocity in m/s. Positive = ascending, negative = descending."""
    surface_speed: float = 0.0
    """Speed relative to the surface of the body, in m/s."""
    orbital_speed: float = 0.0
    """Speed relative to the orbited body's center of mass, in m/s."""

    # --- Orbit ---
    apoapsis: float = 0.0
    """Highest point of the orbit above sea level, in meters."""
    periapsis: float = 0.0
    """Lowest point of the orbit above sea level, in meters."""
    inclination: float = 0.0
    """Orbital inclination relative to the equator, in degrees."""
    eccentricity: float = 0.0
    """Orbital eccentricity. 0 = circular, 0-1 = elliptical, 1 = parabolic."""
    period: float = 0.0
    """Time for one complete orbit, in seconds."""

    # --- Vessel ---
    met: float = 0.0
    """Mission Elapsed Time since launch, in seconds."""
    vessel_name: str = ""
    """Name of the active vessel."""
    situation: str = ""
    """Current flight situation (e.g. 'pre_launch', 'flying', 'orbiting', 'landed')."""

    # --- Position ---
    body: str = ""
    """Name of the celestial body being orbited (e.g. 'Kerbin', 'Mun')."""
    latitude: float = 0.0
    """Geographic latitude on the body surface, in degrees. -90 to 90."""
    longitude: float = 0.0
    """Geographic longitude on the body surface, in degrees. -180 to 180."""

    # --- Orientation ---
    pitch: float = 0.0
    """Vessel pitch angle in degrees. 0 = horizontal, 90 = straight up."""
    heading: float = 0.0
    """Vessel heading in degrees. 0 = north, 90 = east, 180 = south, 270 = west."""
    roll: float = 0.0
    """Vessel roll angle in degrees."""

    # --- Configuration ---
    throttle: float = 0.0
    """Current throttle setting. 0.0 = off, 1.0 = full thrust."""
    sas: bool = False
    """Whether the Stability Assist System is enabled."""
    sas_mode: SASMode = SASMode.STABILITY_ASSIST
    """Active SAS autopilot mode."""
    rcs: bool = False
    """Whether the Reaction Control System is enabled."""
    gear: bool = False
    """Whether landing gear is deployed."""
    legs: bool = False
    """Whether landing legs are deployed."""
    lights: bool = False
    """Whether vessel lights are on."""
    brakes: bool = False
    """Whether brakes are engaged."""
    abort: bool = False
    """Whether the abort action group has been triggered."""
    current_stage: int = 0
    """Currently active stage number."""
    max_stages: int = 0
    """Total number of stages on the vessel."""

    # --- Deployables ---
    solar_panels: bool = False
    """Whether solar panels are deployed."""
    antennas: bool = False
    """Whether antennas are deployed."""
    cargo_bays: bool = False
    """Whether cargo bays are open."""
    intakes: bool = False
    """Whether air intakes are open."""
    parachutes: bool = False
    """Whether parachutes are deployed."""
    radiators: bool = False
    """Whether radiators are deployed."""

    # --- Resources ---
    electric_charge: float = 0.0
    """Available electric charge, in units."""
    liquid_fuel: float = 0.0
    """Available liquid fuel, in units."""
    oxidizer: float = 0.0
    """Available oxidizer, in units."""
    mono_propellant: float = 0.0
    """Available monopropellant (RCS fuel), in units."""


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

    # --- Autopilot target angles ---
    pitch: float | None = None
    """Target pitch angle in degrees. 0 = horizontal, 90 = straight up."""
    heading: float | None = None
    """Target heading in degrees. 0 = north, 90 = east, 180 = south, 270 = west."""

    # --- Systems ---
    sas: bool | None = None
    """Stability Assist System. True = enable, False = disable."""
    sas_mode: SASMode | None = None
    """SAS autopilot mode."""
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
    abort: bool | None = None
    """Abort action group. True = trigger."""

    # --- Deployables ---
    solar_panels: bool | None = None
    """Solar panels. True = deploy, False = retract."""
    antennas: bool | None = None
    """Antennas. True = deploy, False = retract."""
    cargo_bays: bool | None = None
    """Cargo bays. True = open, False = close."""
    intakes: bool | None = None
    """Air intakes. True = open, False = close."""
    parachutes: bool | None = None
    """Parachutes. True = deploy."""
    radiators: bool | None = None
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
    def start(self, param_values: dict[str, Any]) -> None:
        """Initialize internal state from parameter values.

        Called once before the first tick.
        """

    @abstractmethod
    def tick(
        self, state: VesselState, commands: VesselCommands, dt: float, log: ActionLogger
    ) -> ActionResult:
        """Execute one step of the action.

        Read from *state*, mutate *commands* to express desired changes,
        call *log.debug()/.info()/.warn()/.error()* to emit messages,
        and return an ActionResult indicating lifecycle status.
        """

    def stop(self, commands: VesselCommands, log: ActionLogger) -> None:
        """Clean up on abort or completion.

        Default implementation kills throttle (safe default).
        Subclasses override for custom cleanup.
        """
        commands.throttle = 0.0
