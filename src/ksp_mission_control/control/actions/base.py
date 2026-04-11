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

    altitude_sea: float = 0.0
    altitude_surface: float = 0.0
    vertical_speed: float = 0.0
    surface_speed: float = 0.0
    orbital_speed: float = 0.0
    apoapsis: float = 0.0
    periapsis: float = 0.0
    met: float = 0.0
    vessel_name: str = ""
    situation: str = ""
    body: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    inclination: float = 0.0
    eccentricity: float = 0.0
    period: float = 0.0
    electric_charge: float = 0.0
    liquid_fuel: float = 0.0
    oxidizer: float = 0.0
    mono_propellant: float = 0.0


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
