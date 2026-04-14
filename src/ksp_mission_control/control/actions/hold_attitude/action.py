"""HoldAttitudeAction - diagnostic action to test autopilot attitude hold.

Stages, sets throttle to 100%, engages the kRPC autopilot targeting the
vessel's current pitch, heading, and roll, then holds for a fixed number
of ticks. Logs the autopilot error each tick so we can verify whether the
autopilot actually maintains the commanded orientation.
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
    VesselCommands,
    VesselState,
)

_DEFAULT_HOLD_TICKS = 100  # number of ticks to hold attitude before succeeding


class HoldAttitudeAction(Action):
    """Stage, throttle up, and hold current attitude for N ticks."""

    action_id: ClassVar[str] = "hold_attitude"
    label: ClassVar[str] = "Hold Attitude"
    description: ClassVar[str] = "Stage, throttle 100%, hold current pitch/heading/roll for N ticks"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="hold_ticks",
            label="Hold Ticks",
            description="Number of ticks to hold attitude before completing",
            required=False,
            param_type=ParamType.FLOAT,
            default=_DEFAULT_HOLD_TICKS,
            unit="ticks",
        ),
    ]

    def start(self, state: VesselState, param_values: dict[str, Any]) -> None:
        self._hold_ticks: int = int(param_values.get("hold_ticks", _DEFAULT_HOLD_TICKS))
        self._tick_count: int = 0
        self._staged: bool = False

        # Capture current orientation as autopilot targets.
        self._target_pitch: float = state.pitch
        self._target_heading: float = state.heading
        self._target_roll: float = state.roll

    def tick(self, state: VesselState, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        self._tick_count += 1

        # Stage once on the first tick.
        if not self._staged:
            commands.stage = True
            self._staged = True
            log.info("Staged")

        # Engage autopilot every tick with the captured targets.
        commands.throttle = 1.0
        commands.autopilot = True
        commands.autopilot_pitch = self._target_pitch
        commands.autopilot_heading = self._target_heading
        commands.autopilot_roll = self._target_roll

        log.debug(
            f"Tick {self._tick_count}/{self._hold_ticks} | "
            f"target pitch={self._target_pitch:.1f} heading={self._target_heading:.1f} roll={self._target_roll:.1f} | "
            f"actual pitch={state.pitch:.1f} heading={state.heading:.1f} roll={state.roll:.1f} | "
            f"error total={state.autopilot_error or 0:.1f} "
            f"pitch_err={state.autopilot_pitch_error or 0:.1f} "
            f"heading_err={state.autopilot_heading_error or 0:.1f} "
            f"roll_err={state.autopilot_roll_error or 0:.1f}"
        )

        if self._tick_count >= self._hold_ticks:
            log.info(f"Hold complete after {self._tick_count} ticks. Final error: {state.autopilot_error or 0:.1f} deg")
            return ActionResult(status=ActionStatus.SUCCEEDED, message="Attitude hold complete")

        return ActionResult(status=ActionStatus.RUNNING)

    def stop(self, state: VesselState, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)
        commands.autopilot = False
        commands.throttle = 0.0
