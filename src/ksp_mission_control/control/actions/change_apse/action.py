"""ChangeApseAction - raise or lower one apse to a target altitude.

Burns at the *opposite* apse to set the chosen apse (``target``) to
``target_altitude``. The burn point's radius is preserved (a prograde or
retrograde burn at an apse only moves the opposite apse). Use this to
raise an apoapsis for transfers, or lower a periapsis for reentry.

Vis-viva at the burn radius r (the current opposite-apse radius), with
parent body gravitational parameter mu and post-burn semi-major axis
a_new = (r + r_target) / 2:

    v_current = sqrt(mu * (2/r - 1/a_current))
    v_new     = sqrt(mu * (2/r - 1/a_new))
    delta_v   = v_new - v_current        # positive  -> prograde (raises target apse)
                                         # negative  -> retrograde (lowers target apse)

Phases
------
1. **Plan**: First tick computes vis-viva and requests a maneuver node at
   the opposite apse via ``commands.create_node``.
2. **Execute**: Once the node appears in ``state.nodes``, the shared
   ``execute_node`` helper orients toward the burn vector and throttles
   when the burn window opens.
3. **Complete**: When the node's remaining delta-v is exhausted, the node
   is removed and the action succeeds.

Parameter defaults
------------------
- ``target``: ``"apoapsis"`` (most common use is raising apoapsis for
  transfers).
- ``target_altitude``: no default; the caller must specify the target.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any, ClassVar

from ksp_mission_control.control.actions.base import (
    Action,
    ActionLogger,
    ActionParam,
    ActionResult,
    ActionStatus,
    Maneuver,
    ManeuverNode,
    ParamType,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.helpers.maneuver_node import execute_node
from ksp_mission_control.control.actions.helpers.staging import (
    STAGING_MODE_PARAM,
    StagingMode,
    parse_staging_mode,
)

# Tolerance used to match the node we requested against state.nodes by ut.
# The bridge writes the same value we set in Maneuver.ut and reads it back
# unchanged; this tolerance only protects against round-trip float jitter.
_NODE_UT_MATCH_TOLERANCE: float = 0.001


class ApseTarget(Enum):
    """Which apse to change."""

    APOAPSIS = "apoapsis"
    PERIAPSIS = "periapsis"

    @property
    def display_name(self) -> str:
        return self.value.title()


class ChangeApseAction(Action):
    """Change the chosen apse to a target altitude via a planned maneuver node."""

    action_id: ClassVar[str] = "change_apse"
    label: ClassVar[str] = "Change Apse"
    description: ClassVar[str] = "Raise or lower an apse to a target altitude"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="target",
            label="Target Apse",
            description=(
                "Which apse to change: 'apoapsis' burns at periapsis to set the new apoapsis; 'periapsis' burns at apoapsis to set the new periapsis."
            ),
            required=False,
            param_type=ParamType.STR,
            default="apoapsis",
        ),
        ActionParam(
            param_id="target_altitude",
            label="Target Altitude",
            description="New altitude for the chosen apse, in meters above sea level.",
            required=True,
            param_type=ParamType.FLOAT,
            default=None,
            unit="m",
        ),
        STAGING_MODE_PARAM,
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        raw_target = param_values["target"]
        try:
            self._target: ApseTarget = ApseTarget(str(raw_target).lower())
        except ValueError:
            valid = ", ".join(t.value for t in ApseTarget)
            raise ValueError(f"Unknown target '{raw_target}'. Valid: {valid}") from None

        self._target_altitude: float = float(param_values["target_altitude"])
        self._staging_mode: StagingMode | None = parse_staging_mode(param_values["staging_mode"])

        # ut of the node this action created, captured on first tick so we
        # can find it again across ticks even if other nodes get inserted.
        self._node_ut: float | None = None

        # Start-time validations whose failure is surfaced on the first tick.
        self._fail_message: str | None = None
        if self._target is ApseTarget.APOAPSIS and self._target_altitude < state.orbit_periapsis:
            self._fail_message = (
                f"Cannot lower apoapsis to {self._target_altitude:,.0f}m: "
                f"current periapsis is {state.orbit_periapsis:,.0f}m. "
                f"Use target='periapsis' to lower periapsis instead."
            )
        elif self._target is ApseTarget.PERIAPSIS and self._target_altitude > state.orbit_apoapsis:
            self._fail_message = (
                f"Cannot raise periapsis to {self._target_altitude:,.0f}m: "
                f"current apoapsis is {state.orbit_apoapsis:,.0f}m. "
                f"Use target='apoapsis' to raise apoapsis instead."
            )

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        if self._fail_message is not None:
            return ActionResult(status=ActionStatus.FAILED, message=self._fail_message)

        node = self._find_our_node(state)

        if node is None:
            return self._request_node(state, commands, log)

        if execute_node(state, commands, node, self._staging_mode, dt, log):
            commands.remove_node_at_ut = node.ut
            commands.autopilot = False
            commands.throttle = 0.0
            return ActionResult(
                status=ActionStatus.SUCCEEDED,
                message=f"Set {self._target.display_name} to {self._target_altitude:,.0f}m",
            )

        # Still burning. execute_node already handled auto-staging this tick.
        # If we have genuinely run out of thrust with nothing to stage into,
        # the burn cannot complete: fail rather than spin forever. But if
        # commands.stage was set this tick (auto_stage queued a stage), the
        # next tick will see the new engine's thrust, so defer the failure.
        if state.thrust_available <= 0.0 and commands.stage is not True:
            return ActionResult(
                status=ActionStatus.FAILED,
                message=f"Failed: no thrust available. dv_remaining={node.delta_v_remaining:.1f} m/s",
            )

        return ActionResult(
            status=ActionStatus.RUNNING,
            message=f"Burning to set {self._target.display_name}: dv_remaining={node.delta_v_remaining:.1f} m/s",
        )

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        commands.throttle = 0.0
        commands.autopilot = False
        if self._node_ut is not None:
            commands.remove_node_at_ut = self._node_ut
        # Restore the user's intended warp rate (ADR 0012). The helper
        # already wrote this on a successful burn-complete return; the
        # write here is the safety net for FAILED and external-abort paths.
        if state.user_target_warp_rate > 1.0:
            commands.time_warp_rate = state.user_target_warp_rate

    # ---- Helpers ------------------------------------------------------

    def _find_our_node(self, state: State) -> ManeuverNode | None:
        """Return the node this action created, or None if it does not exist yet."""
        if self._node_ut is None:
            return None
        for candidate in state.nodes:
            if abs(candidate.ut - self._node_ut) <= _NODE_UT_MATCH_TOLERANCE:
                return candidate
        return None

    def _request_node(self, state: State, commands: VesselCommands, log: ActionLogger) -> ActionResult:
        """Compute vis-viva at the opposite apse and request node creation."""
        if state.body_gm <= 0.0 or state.orbit_semi_major_axis <= 0.0:
            return ActionResult(
                status=ActionStatus.FAILED,
                message="Cannot change apse: invalid orbit (no gravitational parameter or semi-major axis).",
            )

        # Burn at the OPPOSITE apse: a prograde/retrograde burn at an apse
        # leaves that apse's radius unchanged and moves only the other one.
        if self._target is ApseTarget.APOAPSIS:
            burn_altitude = state.orbit_periapsis
            time_to_burn = state.orbit_periapsis_time_to
        else:
            burn_altitude = state.orbit_apoapsis
            time_to_burn = state.orbit_apoapsis_time_to

        r_burn = burn_altitude + state.body_radius
        r_target = self._target_altitude + state.body_radius
        if r_burn <= 0.0 or r_target <= 0.0:
            return ActionResult(
                status=ActionStatus.FAILED,
                message=f"Cannot change {self._target.display_name}: non-positive radius (burn={r_burn:.0f}, target={r_target:.0f}).",
            )

        mu = state.body_gm
        a_new = (r_burn + r_target) / 2.0
        v_current = math.sqrt(mu * (2.0 / r_burn - 1.0 / state.orbit_semi_major_axis))
        v_new = math.sqrt(mu * (2.0 / r_burn - 1.0 / a_new))
        delta_v = v_new - v_current

        node_ut = state.universal_time + time_to_burn
        commands.create_node = Maneuver(ut=node_ut, prograde=delta_v)
        self._node_ut = node_ut

        log.info(
            f"Planned {self._target.display_name} change to {self._target_altitude:,.0f}m: "
            f"dv={delta_v:+.1f} m/s, in {time_to_burn:.0f}s, ut={node_ut:.1f}"
        )
        return ActionResult(
            status=ActionStatus.RUNNING,
            message=f"Planning {self._target.display_name} change (dv={delta_v:+.1f} m/s)",
        )
