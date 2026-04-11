"""Action registry - factory for available actions."""

from __future__ import annotations

from ksp_mission_control.control.actions.base import Action


def get_available_actions() -> list[Action]:
    """Return the list of all available actions."""
    from ksp_mission_control.control.actions.hover.action import HoverAction

    return [HoverAction()]
