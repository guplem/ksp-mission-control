"""ControllabilityTestAction - diagnostic action to verify vessel attitude control.

Stages, throttles up, then runs through a series of maneuvers testing each
axis independently: roll to a target and back, pitch to a target and back,
heading to a target and back. Each maneuver must hold within tolerance for
a configurable duration before advancing. Logs detailed progress throughout.
"""

from __future__ import annotations

from dataclasses import dataclass
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

_DEFAULT_ROLL_OFFSET = 45.0
_DEFAULT_PITCH_OFFSET = 15.0
_DEFAULT_HEADING_OFFSET = 30.0
_DEFAULT_HOLD_DURATION = 3.0  # seconds within tolerance to pass
_DEFAULT_TOLERANCE = 5.0  # degrees


@dataclass
class _TestStep:
    """A single maneuver step: slew to a target orientation and hold."""

    label: str
    target_pitch: float
    target_heading: float
    target_roll: float
    hold_duration: float


def _normalize_heading(degrees: float) -> float:
    """Normalize a heading angle to the 0-360 range."""
    return degrees % 360.0


def _angle_error(current: float, target: float, wrap_360: bool = False) -> float:
    """Signed angular error from current to target.

    For heading (wrap_360=True), wraps around 360 so the error is in [-180, 180].
    For pitch/roll, returns the simple difference.
    """
    if wrap_360:
        diff = (target - current) % 360.0
        if diff > 180.0:
            diff -= 360.0
        return diff
    return target - current


class ControllabilityTestAction(Action):
    """Stage, throttle up, and test roll/pitch/heading control in sequence."""

    action_id: ClassVar[str] = "controllability_test"
    label: ClassVar[str] = "Controllability Test"
    description: ClassVar[str] = "Test roll, pitch, and heading control with target holds"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="roll_offset",
            label="Roll Offset",
            description="Degrees to roll away from initial orientation",
            required=False,
            param_type=ParamType.FLOAT,
            default=_DEFAULT_ROLL_OFFSET,
            unit="deg",
        ),
        ActionParam(
            param_id="pitch_offset",
            label="Pitch Offset",
            description="Degrees to pitch away from initial orientation",
            required=False,
            param_type=ParamType.FLOAT,
            default=_DEFAULT_PITCH_OFFSET,
            unit="deg",
        ),
        ActionParam(
            param_id="heading_offset",
            label="Heading Offset",
            description="Degrees to turn heading from initial orientation",
            required=False,
            param_type=ParamType.FLOAT,
            default=_DEFAULT_HEADING_OFFSET,
            unit="deg",
        ),
        ActionParam(
            param_id="hold_duration",
            label="Hold Duration",
            description="Seconds to hold within tolerance for each maneuver",
            required=False,
            param_type=ParamType.FLOAT,
            default=_DEFAULT_HOLD_DURATION,
            unit="s",
        ),
        ActionParam(
            param_id="tolerance",
            label="Tolerance",
            description="Degrees of error allowed during hold",
            required=False,
            param_type=ParamType.FLOAT,
            default=_DEFAULT_TOLERANCE,
            unit="deg",
        ),
    ]

    def start(self, state: VesselState, param_values: dict[str, Any]) -> None:
        roll_offset = float(param_values.get("roll_offset", _DEFAULT_ROLL_OFFSET))
        pitch_offset = float(param_values.get("pitch_offset", _DEFAULT_PITCH_OFFSET))
        heading_offset = float(param_values.get("heading_offset", _DEFAULT_HEADING_OFFSET))
        hold_duration = float(param_values.get("hold_duration", _DEFAULT_HOLD_DURATION))
        self._tolerance: float = float(param_values.get("tolerance", _DEFAULT_TOLERANCE))

        # Capture initial orientation as baseline.
        initial_pitch = state.pitch
        initial_heading = state.heading
        initial_roll = state.roll

        target_roll = initial_roll + roll_offset
        target_pitch = min(max(initial_pitch + pitch_offset, -90.0), 90.0)
        target_heading = _normalize_heading(initial_heading + heading_offset)

        # Build the test sequence. Each step holds all three axes; only
        # the axis under test changes between steps.
        self._steps: list[_TestStep] = [
            # Roll test
            _TestStep(
                label=f"Roll to {target_roll:.1f} deg (offset {roll_offset:+.1f})",
                target_pitch=initial_pitch,
                target_heading=initial_heading,
                target_roll=target_roll,
                hold_duration=hold_duration,
            ),
            _TestStep(
                label=f"Roll back to {initial_roll:.1f} deg",
                target_pitch=initial_pitch,
                target_heading=initial_heading,
                target_roll=initial_roll,
                hold_duration=hold_duration,
            ),
            # Pitch test
            _TestStep(
                label=f"Pitch to {target_pitch:.1f} deg (offset {pitch_offset:+.1f})",
                target_pitch=target_pitch,
                target_heading=initial_heading,
                target_roll=initial_roll,
                hold_duration=hold_duration,
            ),
            _TestStep(
                label=f"Pitch back to {initial_pitch:.1f} deg",
                target_pitch=initial_pitch,
                target_heading=initial_heading,
                target_roll=initial_roll,
                hold_duration=hold_duration,
            ),
            # Heading test
            _TestStep(
                label=f"Heading to {target_heading:.1f} deg (offset {heading_offset:+.1f})",
                target_pitch=initial_pitch,
                target_heading=target_heading,
                target_roll=initial_roll,
                hold_duration=hold_duration,
            ),
            _TestStep(
                label=f"Heading back to {initial_heading:.1f} deg",
                target_pitch=initial_pitch,
                target_heading=initial_heading,
                target_roll=initial_roll,
                hold_duration=hold_duration,
            ),
        ]

        self._step_index: int = 0
        self._staged: bool = False
        self._hold_time: float = 0.0  # accumulated seconds within tolerance
        self._slewing: bool = True  # True = slewing to target, False = holding
        self._tick_count: int = 0

    def tick(self, state: VesselState, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        self._tick_count += 1

        # Stage once on the first tick.
        if not self._staged:
            commands.stage = True
            self._staged = True
            log.info("Staged and throttle set to 100%")

        # All steps complete.
        if self._step_index >= len(self._steps):
            log.info(f"All {len(self._steps)} maneuvers passed! Controllability test complete.")
            return ActionResult(status=ActionStatus.SUCCEEDED, message="Controllability test passed")

        step = self._steps[self._step_index]

        # Always command autopilot with current step's targets.
        commands.throttle = 1.0
        commands.autopilot = True
        commands.autopilot_pitch = step.target_pitch
        commands.autopilot_heading = step.target_heading
        commands.autopilot_roll = step.target_roll

        # Compute per-axis errors.
        pitch_err = _angle_error(state.pitch, step.target_pitch)
        heading_err = _angle_error(state.heading, step.target_heading, wrap_360=True)
        roll_err = _angle_error(state.roll, step.target_roll)
        within_tolerance = abs(pitch_err) < self._tolerance and abs(heading_err) < self._tolerance and abs(roll_err) < self._tolerance

        if self._slewing:
            # Slewing to target -- waiting to get within tolerance.
            log.debug(
                f"[{self._step_index + 1}/{len(self._steps)}] SLEW: {step.label} | "
                f"pitch={state.pitch:.1f} (err {pitch_err:+.1f}) "
                f"heading={state.heading:.1f} (err {heading_err:+.1f}) "
                f"roll={state.roll:.1f} (err {roll_err:+.1f}) | "
                f"total_err={state.autopilot_error or 0:.1f}"
            )
            if within_tolerance:
                self._slewing = False
                self._hold_time = 0.0
                log.info(f"[{self._step_index + 1}/{len(self._steps)}] Reached target for '{step.label}' -- starting {step.hold_duration:.1f}s hold")
        else:
            # Holding at target -- accumulating time within tolerance.
            if within_tolerance:
                self._hold_time += dt
                log.debug(
                    f"[{self._step_index + 1}/{len(self._steps)}] HOLD: {step.label} | "
                    f"hold {self._hold_time:.1f}/{step.hold_duration:.1f}s | "
                    f"pitch={state.pitch:.1f} (err {pitch_err:+.1f}) "
                    f"heading={state.heading:.1f} (err {heading_err:+.1f}) "
                    f"roll={state.roll:.1f} (err {roll_err:+.1f})"
                )
            else:
                log.warn(
                    f"[{self._step_index + 1}/{len(self._steps)}] HOLD BROKEN: {step.label} | "
                    f"drifted outside tolerance ({self._tolerance:.1f} deg) -- resetting hold timer | "
                    f"pitch err={pitch_err:+.1f} heading err={heading_err:+.1f} roll err={roll_err:+.1f}"
                )
                self._hold_time = 0.0

            if self._hold_time >= step.hold_duration:
                log.info(
                    f"[{self._step_index + 1}/{len(self._steps)}] "
                    f"PASSED: '{step.label}' held for {step.hold_duration:.1f}s within {self._tolerance:.1f} deg"
                )
                self._step_index += 1
                self._slewing = True
                self._hold_time = 0.0
                # Log next step preview.
                if self._step_index < len(self._steps):
                    next_step = self._steps[self._step_index]
                    log.info(f"[{self._step_index + 1}/{len(self._steps)}] Next maneuver: {next_step.label}")

        return ActionResult(status=ActionStatus.RUNNING)

    def stop(self, state: VesselState, commands: VesselCommands, log: ActionLogger) -> None:
        super().stop(state, commands, log)
        commands.autopilot = False
        commands.throttle = 0.0
