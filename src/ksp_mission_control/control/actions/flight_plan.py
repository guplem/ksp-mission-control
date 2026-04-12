"""Flight plan data structures and parser.

A flight plan is a text file where each line is an action ID followed by
space-separated key=value parameters. Example:

    # Hover then land
    hover  target_altitude=100  hover_duration=30
    land   target_speed=2
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ksp_mission_control.control.actions.base import Action, ParamType
from ksp_mission_control.control.actions.registry import get_available_actions


@dataclass(frozen=True)
class FlightPlanStep:
    """Single step in a flight plan: an action paired with its param values."""

    action_id: str
    param_values: dict[str, Any]


@dataclass(frozen=True)
class FlightPlan:
    """Ordered sequence of action steps to execute."""

    name: str
    steps: tuple[FlightPlanStep, ...]


def _parse_param_value(raw: str, param_type: ParamType) -> float | bool | str:
    """Convert a raw string value to the correct type."""
    if param_type == ParamType.FLOAT:
        return float(raw)
    if param_type == ParamType.BOOL:
        if raw.lower() in ("true", "1", "yes"):
            return True
        if raw.lower() in ("false", "0", "no"):
            return False
        raise ValueError(f"Invalid bool value: {raw!r}")
    return raw


def _resolve_action(action_id: str, actions: list[Action]) -> Action:
    """Find an action by ID from the registry list."""
    for action in actions:
        if action.action_id == action_id:
            return action
    available = [a.action_id for a in actions]
    raise ValueError(f"Unknown action {action_id!r}. Available: {available}")


def _parse_line_params(tokens: list[str], action: Action) -> dict[str, Any]:
    """Parse key=value tokens into a typed param dict for the given action."""
    param_lookup = {p.param_id: p for p in action.params}
    result: dict[str, Any] = {}

    for token in tokens:
        if "=" not in token:
            raise ValueError(
                f"Invalid parameter format {token!r} for action {action.action_id!r}. "
                f"Expected key=value"
            )
        key, raw_value = token.split("=", 1)
        if key not in param_lookup:
            available = list(param_lookup.keys())
            raise ValueError(
                f"Unknown parameter {key!r} for action {action.action_id!r}. Available: {available}"
            )
        param = param_lookup[key]
        result[key] = _parse_param_value(raw_value, param.param_type)

    return result


def parse_flight_plan(path: Path) -> FlightPlan:
    """Parse a .plan file into a FlightPlan.

    Raises ValueError on unknown actions, invalid params, or empty plans.
    """
    actions = get_available_actions()
    steps: list[FlightPlanStep] = []

    text = path.read_text(encoding="utf-8")
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        tokens = line.split()
        action_id = tokens[0]
        try:
            action = _resolve_action(action_id, actions)
            param_values = _parse_line_params(tokens[1:], action)
        except ValueError as exc:
            raise ValueError(f"Line {line_number}: {exc}") from exc

        steps.append(FlightPlanStep(action_id=action_id, param_values=param_values))

    if not steps:
        raise ValueError(f"Flight plan {path.name} has no steps")

    plan_name = path.stem
    return FlightPlan(name=plan_name, steps=tuple(steps))
