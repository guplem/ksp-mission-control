"""RunScienceAction - activate all science experiments on the vessel.

Triggers every available science experiment that doesn't already have data.
Optionally waits until the vessel reaches apoapsis (vertical speed crosses
zero) before triggering, which is useful for suborbital science flights.
"""

from __future__ import annotations

from typing import Any, ClassVar

from ksp_mission_control.control.actions.base import (
    Action,
    ActionLogger,
    ActionParam,
    ActionResult,
    ActionStatus,
    ParamType,
    ScienceAction,
    VesselCommands,
    VesselState,
)


class RunScienceAction(Action):
    """Activate all science experiments, optionally waiting for apoapsis."""

    action_id: ClassVar[str] = "run_science"
    label: ClassVar[str] = "Run Science"
    description: ClassVar[str] = "Activate all science experiments on the vessel"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="wait_for_apoapsis",
            label="Wait for Apoapsis",
            description="Wait until the vessel reaches its highest point before running experiments",
            required=False,
            param_type=ParamType.BOOL,
            default=False,
        ),
    ]

    def start(self, state: VesselState, param_values: dict[str, Any]) -> None:
        self._wait_for_apoapsis: bool = bool(param_values.get("wait_for_apoapsis", False))
        self._triggered: bool = False
        self._was_ascending: bool = state.speed_vertical > 0.0

    def tick(self, state: VesselState, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:

        if self._wait_for_apoapsis:
            now_ascending = state.speed_vertical > 0.0

            if self._was_ascending and not now_ascending:
                # Crossed apoapsis: vertical speed went from positive to non-positive.
                available_count = sum(1 for e in state.science_experiments if e.available and not e.has_data)
                log.info(f"Apoapsis reached at {state.altitude_sea:.0f}m, running {available_count} science experiment(s)")
                commands.all_science = ScienceAction.RUN
                return ActionResult(status=ActionStatus.SUCCEEDED, message="Science experiments activated at apoapsis")

            self._was_ascending = now_ascending
            log.debug(f"Waiting for apoapsis (vertical speed: {state.speed_vertical:.1f} m/s)")
            return ActionResult(status=ActionStatus.RUNNING)

        # No wait: trigger immediately.
        available_count = sum(1 for e in state.science_experiments if e.available and not e.has_data)
        log.info(f"Running {available_count} science experiment(s)")
        commands.all_science = ScienceAction.RUN
        return ActionResult(status=ActionStatus.SUCCEEDED, message="Science experiments activated")

    def stop(self, state: VesselState, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)
