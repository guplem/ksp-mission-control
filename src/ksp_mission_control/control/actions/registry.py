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
    import ksp_mission_control.control.actions.parachutes.action as parachutes_module
    import ksp_mission_control.control.actions.sas.action as sas_module
    import ksp_mission_control.control.actions.science.action as science_module
    import ksp_mission_control.control.actions.stage.action as stage_module
    import ksp_mission_control.control.actions.throttle.action as throttle_module
    import ksp_mission_control.control.actions.translate.action as translate_module
    import ksp_mission_control.control.actions.wait_for.action as wait_for_module

    # 2. Reload to pick up code changes without restarting the app
    importlib.reload(parachutes_module)
    importlib.reload(controllability_test_module)
    importlib.reload(hold_attitude_module)
    importlib.reload(hover_module)
    importlib.reload(land_module)
    importlib.reload(launch_module)
    importlib.reload(sas_module)
    importlib.reload(science_module)
    importlib.reload(stage_module)
    importlib.reload(throttle_module)
    importlib.reload(translate_module)
    importlib.reload(wait_for_module)

    # 3. Instantiate and return
    return [
        parachutes_module.ParachutesAction(),
        controllability_test_module.ControllabilityTestAction(),
        hold_attitude_module.HoldAttitudeAction(),
        hover_module.HoverAction(),
        land_module.LandAction(),
        launch_module.LaunchAction(),
        sas_module.SasAction(),
        science_module.ExecuteScienceAction(),
        stage_module.StageAction(),
        throttle_module.ThrottleAction(),
        translate_module.TranslateAction(),
        wait_for_module.WaitForAction(),
    ]
