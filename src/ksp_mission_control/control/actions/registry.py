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
    import ksp_mission_control.control.actions.controllability_test.action as controllability_test_module
    import ksp_mission_control.control.actions.hold_attitude.action as hold_attitude_module
    import ksp_mission_control.control.actions.hover.action as hover_module
    import ksp_mission_control.control.actions.land.action as land_module
    import ksp_mission_control.control.actions.launch.action as launch_module
    import ksp_mission_control.control.actions.translate.action as translate_module

    # 2. Reload to pick up code changes without restarting the app
    importlib.reload(controllability_test_module)
    importlib.reload(hold_attitude_module)
    importlib.reload(hover_module)
    importlib.reload(land_module)
    importlib.reload(launch_module)
    importlib.reload(translate_module)

    # 3. Instantiate and return
    return [
        controllability_test_module.ControllabilityTestAction(),
        hold_attitude_module.HoldAttitudeAction(),
        hover_module.HoverAction(),
        land_module.LandAction(),
        launch_module.LaunchAction(),
        translate_module.TranslateAction(),
    ]
