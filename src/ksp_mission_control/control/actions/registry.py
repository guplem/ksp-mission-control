"""Action registry - auto-discovers actions from subdirectories."""

from __future__ import annotations

import importlib
from inspect import isclass
from pathlib import Path

from ksp_mission_control.control.actions.base import Action

_ACTIONS_DIR = Path(__file__).parent


def get_available_actions() -> list[Action]:
    """Return the list of all available actions.

    Scans each subdirectory of the actions package for an ``action.py`` module,
    reloads it (so code changes take effect without restarting the app), and
    instantiates any Action subclass found.
    """
    actions: list[Action] = []

    for subfolder in sorted(_ACTIONS_DIR.iterdir()):
        action_file = subfolder / "action.py"
        if not action_file.is_file():
            continue

        module_name = f"ksp_mission_control.control.actions.{subfolder.name}.action"
        module = importlib.import_module(module_name)
        importlib.reload(module)

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isclass(attr) and issubclass(attr, Action) and attr is not Action:
                actions.append(attr())

    return actions
