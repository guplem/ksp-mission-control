"""Action registry - factory for available actions."""

from __future__ import annotations

import importlib

from ksp_mission_control.control.actions.base import Action


def get_available_actions() -> list[Action]:
    """Return the list of all available actions.

    Reloads action modules from disk each call so code changes
    take effect without restarting the app.
    """

    # 1. Import
    import ksp_mission_control.control.actions.hover.action as hover_module
    import ksp_mission_control.control.actions.land.action as land_module

    # 2. Reload to pick up code changes without restarting the app
    importlib.reload(hover_module)
    importlib.reload(land_module)

    # 3. Instantiate and return
    return [hover_module.HoverAction(), land_module.LandAction()]
