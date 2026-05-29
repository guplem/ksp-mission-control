"""TimeWarpAction - set the KSP time warp multiplier.

KSP exposes two distinct warp modes:

- Rails warp: 1, 5, 10, 50, 100, 1000, 10000, 100000. On-rails simulation;
  vessel coasts on its orbit while the rest of the universe is paused.
- Physics warp: 1, 2, 3, 4. Physics keeps running, so it is safe in
  atmosphere or near other vessels.

The action takes one optional target multiplier and asks the bridge to pick
the highest available factor whose multiplier does not exceed the request.
The bridge selects rails warp at or above 5x and physics warp below it.
KSP further caps the rate based on altitude and situation (you cannot
rails-warp near the ground), so the achieved ``State.time_warp_rate`` may
be lower than the request. Read it after the action runs to see what stuck.

When ``target_multiplier`` is omitted, the action re-sends the current
``state.user_target_warp_rate`` to KSP without changing the user's intent.
Use this after an earlier set was clamped by KSP (altitude cap, situation)
to retry now that the cap may have lifted.

The action completes on the first tick: it sends the command and returns
SUCCEEDED so the plan advances immediately. KSP ramps to the new rate over
the next frame or two. The warp setting is sticky -- subsequent plan
steps run under the new rate until another ``time_warp`` action changes
it. Use ``target_multiplier=1`` to drop back to real time before a burn
or any other time-sensitive step.

Typical pattern for a long coast::

    time_warp   target_multiplier=100
    wait_for    time_before_next_maneuver=60
    time_warp   target_multiplier=1
    # ... burn step runs at real time

Retry pattern after a likely KSP clamp::

    time_warp   target_multiplier=100
    wait_for    above_altitude=70_000
    time_warp                       # re-sends 100x, now that altitude allows it
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
    State,
    VesselCommands,
)


class TimeWarpAction(Action):
    """Set the KSP time warp to the highest factor that does not exceed a target multiplier."""

    action_id: ClassVar[str] = "time_warp"
    label: ClassVar[str] = "Time Warp"
    description: ClassVar[str] = "Set the time warp multiplier"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="target_multiplier",
            label="Target Multiplier",
            description=(
                "Highest time-warp multiplier the action is allowed to set. "
                "Rails-warp levels are 1, 5, 10, 50, 100, 1000, 10000, 100000; "
                "physics-warp levels are 1, 2, 3, 4. The bridge picks rails warp "
                "for >= 5 and physics warp for the smaller levels. KSP further caps "
                "the achievable rate based on altitude and situation. Use 1 to return "
                "to real time. Leave empty to re-send the current user-target rate "
                "without changing it (useful to retry after a KSP clamp)."
            ),
            required=False,
            param_type=ParamType.FLOAT,
            default=None,
            unit="x",
        ),
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        # ``None`` means "re-send the current user-target rate without
        # changing it". Any explicit value updates the user's intent.
        raw_target = param_values.get("target_multiplier")
        self._target_multiplier: float | None = float(raw_target) if raw_target is not None else None
        if self._target_multiplier is not None and self._target_multiplier < 1.0:
            raise ValueError(f"target_multiplier must be >= 1, got {self._target_multiplier}.")

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        # Two modes:
        # - Explicit target: write both ``time_warp_rate`` (KSP rate) and
        #   ``user_target_warp_rate`` (session intent). Burn-driven actions
        #   consult the session value when they need to know what to restore
        #   to after a critical section.
        # - No target: re-send the current user intent to KSP. Do not write
        #   ``user_target_warp_rate`` so the intent stays as the user set it.
        if self._target_multiplier is None:
            rate = state.user_target_warp_rate
            commands.time_warp_rate = rate
            log.info(f"Re-sending time warp request: {rate:g}x (current {state.time_warp_rate:g}x, KSP cap {state.time_warp_rate_max:g}x).")
            return ActionResult(
                status=ActionStatus.SUCCEEDED,
                message=f"Time warp re-sent at {rate:g}x (was {state.time_warp_rate:g}x).",
            )

        commands.time_warp_rate = self._target_multiplier
        commands.user_target_warp_rate = self._target_multiplier
        if self._target_multiplier > state.time_warp_rate_max:
            log.warn(f"Requested {self._target_multiplier:g}x exceeds KSP's current cap {state.time_warp_rate_max:g}x; bridge will clamp to the cap.")
        log.info(f"Time warp request: {self._target_multiplier:g}x (current {state.time_warp_rate:g}x, KSP cap {state.time_warp_rate_max:g}x).")
        return ActionResult(
            status=ActionStatus.SUCCEEDED,
            message=f"Time warp set to {self._target_multiplier:g}x (was {state.time_warp_rate:g}x).",
        )

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        pass
