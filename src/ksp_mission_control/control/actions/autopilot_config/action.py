"""AutopilotConfigAction - tune the kRPC autopilot PID configuration.

One-shot action: sends an ``AutopilotConfig`` command and succeeds in a
single tick. Each scalar parameter is replicated to all three axes
(pitch, yaw, roll). Fields the user omits fall back to the kRPC defaults
defined on ``AutopilotConfig``, so a step with no params resets the
autopilot to its default tuning.

Useful knobs to dampen a wobbling vessel (resonance with the autopilot):

- Raise ``time_to_peak`` for a slower, less reactive turn.
- Raise ``stopping_time`` to lower the maximum angular velocity.
- Raise ``deceleration_time`` for a smoother approach near target.
- Raise ``attenuation_angle`` to start slowing earlier near target.
"""

from __future__ import annotations

from typing import Any, ClassVar

from ksp_mission_control.control.actions.base import (
    Action,
    ActionLogger,
    ActionParam,
    ActionResult,
    ActionStatus,
    AutopilotConfig,
    ParamType,
    State,
    VesselCommands,
)


class AutopilotConfigAction(Action):
    """Tune the kRPC autopilot PID configuration."""

    action_id: ClassVar[str] = "autopilot_config"
    label: ClassVar[str] = "Tune Autopilot"
    description: ClassVar[str] = "Adjust the kRPC autopilot PID tuning (scalar values replicated to all axes)"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="time_to_peak",
            label="Time to Peak",
            description="Target seconds to reach the target orientation. Higher = less reactive turn. kRPC default: 3.0.",
            required=False,
            param_type=ParamType.FLOAT,
            unit="s",
        ),
        ActionParam(
            param_id="overshoot",
            label="Overshoot",
            description="Target overshoot fraction (0.01 = 1%). Lower = more precise but slower to settle. kRPC default: 0.01.",
            required=False,
            param_type=ParamType.FLOAT,
        ),
        ActionParam(
            param_id="stopping_time",
            label="Stopping Time",
            description="Max seconds to kill angular rotation. Higher = lower maximum angular velocity. kRPC default: 0.5.",
            required=False,
            param_type=ParamType.FLOAT,
            unit="s",
        ),
        ActionParam(
            param_id="deceleration_time",
            label="Deceleration Time",
            description="Seconds to decelerate near the target. Higher = smoother but slower approach. kRPC default: 5.0.",
            required=False,
            param_type=ParamType.FLOAT,
            unit="s",
        ),
        ActionParam(
            param_id="attenuation_angle",
            label="Attenuation Angle",
            description="Angle (degrees) at which velocity attenuation begins near the target. kRPC default: 1.0.",
            required=False,
            param_type=ParamType.FLOAT,
            unit="deg",
        ),
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        def _positive_or_none(name: str) -> float | None:
            raw = param_values.get(name)
            if raw is None:
                return None
            value = float(raw)
            if value <= 0.0:
                raise ValueError(f"{name} must be positive (got {value})")
            return value

        self._time_to_peak: float | None = _positive_or_none("time_to_peak")
        self._overshoot: float | None = _positive_or_none("overshoot")
        self._stopping_time: float | None = _positive_or_none("stopping_time")
        self._deceleration_time: float | None = _positive_or_none("deceleration_time")
        self._attenuation_angle: float | None = _positive_or_none("attenuation_angle")

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        kwargs: dict[str, Any] = {}
        parts: list[str] = []

        scalar_fields: list[tuple[str, float | None]] = [
            ("time_to_peak", self._time_to_peak),
            ("overshoot", self._overshoot),
            ("stopping_time", self._stopping_time),
            ("deceleration_time", self._deceleration_time),
            ("attenuation_angle", self._attenuation_angle),
        ]
        for field_name, value in scalar_fields:
            if value is None:
                continue
            kwargs[field_name] = (value, value, value)
            parts.append(f"{field_name}={value}")

        commands.autopilot_config = AutopilotConfig(**kwargs)

        message = "Autopilot tuned: " + ", ".join(parts) if parts else "Autopilot tuning reset to kRPC defaults"
        return ActionResult(status=ActionStatus.SUCCEEDED, message=message)

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        pass
