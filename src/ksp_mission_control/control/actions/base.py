"""Core types for the action execution system.

Defines the Action ABC, VesselState, VesselControls, and supporting types.
Actions are pure functions of VesselState → VesselControls, never touching
kRPC directly. See ADR 0006 for rationale.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar


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
class VesselControls:
    """Mutable command buffer for vessel control outputs.

    All fields default to None meaning "don't change this tick."
    Actions mutate this in tick(); the runner applies non-None fields to kRPC.
    """

    throttle: float | None = field(default=None)
    pitch: float | None = field(default=None)
    heading: float | None = field(default=None)
    sas: bool | None = field(default=None)
    rcs: bool | None = field(default=None)
    stage: bool | None = field(default=None)


class Action(ABC):
    """Base class for a vessel action.

    Subclasses declare ClassVar metadata and implement the tick lifecycle.
    Actions never touch kRPC directly — they read VesselState and mutate
    VesselControls.
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
    def tick(self, state: VesselState, controls: VesselControls, dt: float) -> ActionResult:
        """Execute one step of the action.

        Read from *state*, mutate *controls* to express desired changes,
        and return an ActionResult indicating lifecycle status.
        """

    def stop(self, controls: VesselControls) -> None:
        """Clean up on abort or completion.

        Default implementation kills throttle (safe default).
        Subclasses override for custom cleanup.
        """
        controls.throttle = 0.0
