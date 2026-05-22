"""Flight plan data structures and parser.

A flight plan is a text file where each line is an action ID followed by
space-separated key=value parameters. Example:

    # Hover then land
    hover  target_altitude=100  hover_duration=30
    land   target_speed=2

A line of the form ``@parallel <relative-path>`` becomes a ``ParallelStep``
in its position. When the executor reaches it, it spawns the referenced
sub-plan as a parallel track and immediately advances to the next step.

A bare ``@hidden`` directive marks the plan as a sub-plan: it can still be
spawned via ``@parallel`` from another plan, but it does not appear in the
top-level flight plan picker.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ksp_mission_control.control.actions.base import Action, ParamType
from ksp_mission_control.control.actions.registry import get_available_actions


@dataclass(frozen=True)
class FlightPlanStep:
    """Step that runs an action."""

    action_id: str
    param_values: dict[str, Any]


@dataclass(frozen=True)
class ParallelStep:
    """Step that spawns a parallel sub-plan track when reached.

    ``plan_path`` is a path relative to the ``plans/`` directory.
    """

    plan_path: str

    @property
    def plan_name(self) -> str:
        """Stem of the referenced .plan file (used as the track name)."""
        return Path(self.plan_path).stem


PlanStep = FlightPlanStep | ParallelStep
"""Either an action step or a parallel-spawn step."""


@dataclass(frozen=True)
class FlightPlan:
    """Ordered sequence of plan steps to execute.

    Steps execute strictly in order. ``ParallelStep`` entries spawn
    sub-plans as parallel tracks at the moment they are reached, then
    advance immediately to the next step.
    """

    name: str
    steps: tuple[PlanStep, ...]
    craft: str | None = None
    is_hidden: bool = False


def _parse_param_value(raw: str, param_type: ParamType) -> float | bool | str:
    """Convert a raw string value to the correct type."""
    if param_type == ParamType.FLOAT:
        return float(raw)
    if param_type == ParamType.INT:
        return int(raw)
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
            # Bare token (no =): treat as a boolean flag set to True
            key = token
            if key not in param_lookup:
                available = list(param_lookup.keys())
                raise ValueError(f"Unknown parameter {key!r} for action {action.action_id!r}. Available: {available}")
            param = param_lookup[key]
            if param.param_type != ParamType.BOOL:
                raise ValueError(
                    f"Parameter {key!r} for action {action.action_id!r} requires a value (key=value). "
                    f"Bare flags are only supported for boolean parameters."
                )
            result[key] = True
            continue
        key, raw_value = token.split("=", 1)
        if key not in param_lookup:
            available = list(param_lookup.keys())
            raise ValueError(f"Unknown parameter {key!r} for action {action.action_id!r}. Available: {available}")
        param = param_lookup[key]
        result[key] = _parse_param_value(raw_value, param.param_type)

    return result


def parse_flight_plan_text(text: str, name: str = "inline") -> FlightPlan:
    """Parse raw plan text into a FlightPlan.

    Same syntax as .plan files on disk: blank lines and ``#`` comments are
    ignored, ``@parallel <path>`` becomes a ``ParallelStep``, ``@craft <name>``
    sets the required craft, and a bare ``@hidden`` marks the plan as a
    sub-plan. ``name`` is stored on the resulting FlightPlan and used in
    error messages.

    Raises ValueError on unknown actions, invalid params, or empty plans.
    """
    actions = get_available_actions()
    steps: list[PlanStep] = []
    craft: str | None = None
    is_hidden: bool = False

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line == "@parallel" or line.startswith("@parallel "):
            parallel_path = line[len("@parallel") :].strip()
            if not parallel_path:
                raise ValueError(f"Line {line_number}: @parallel requires a file path")
            steps.append(ParallelStep(plan_path=parallel_path))
            continue

        if line == "@craft" or line.startswith("@craft "):
            craft_name = line[len("@craft") :].strip()
            if not craft_name:
                raise ValueError(f"Line {line_number}: @craft requires a craft name")
            if craft is not None:
                raise ValueError(f"Line {line_number}: duplicate @craft directive")
            craft = craft_name
            continue

        if line == "@hidden":
            is_hidden = True
            continue
        if line.startswith("@hidden "):
            raise ValueError(f"Line {line_number}: @hidden takes no arguments")

        tokens = line.split()
        action_id = tokens[0]
        try:
            action = _resolve_action(action_id, actions)
            param_values = _parse_line_params(tokens[1:], action)
        except ValueError as exc:
            raise ValueError(f"Line {line_number}: {exc}") from exc

        steps.append(FlightPlanStep(action_id=action_id, param_values=param_values))

    if not steps:
        raise ValueError(f"Flight plan {name!r} has no steps")

    return FlightPlan(
        name=name,
        steps=tuple(steps),
        craft=craft,
        is_hidden=is_hidden,
    )


def parse_flight_plan(path: Path) -> FlightPlan:
    """Parse a .plan file into a FlightPlan.

    Reads the file and delegates to :func:`parse_flight_plan_text`. The
    resulting FlightPlan's ``name`` is the file stem.
    """
    text = path.read_text(encoding="utf-8")
    return parse_flight_plan_text(text, name=path.stem)
