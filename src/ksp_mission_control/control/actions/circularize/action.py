"""CircularizeAction - raise the periapsis (at apoapsis) or lower the apoapsis (at periapsis).

The action computes the prograde delta-v required for a circular orbit at
the chosen apse using the vis-viva equation, requests a kRPC maneuver
node at that apse, and then drives the vessel through the burn via the
shared ``execute_node`` helper. No ``wait_for`` is required before the
action - the executor itself orients and waits for the burn window.

Vis-viva at radius r from a parent body with gravitational parameter mu:

    v_current  = sqrt(mu * (2/r - 1/a))    # speed on the current orbit
    v_circular = sqrt(mu / r)              # speed needed for a circle at r
    delta_v    = v_circular - v_current    # positive  -> prograde
                                           # negative  -> retrograde

When circularizing at apoapsis the vessel is below circular speed
(delta_v > 0, prograde burn). At periapsis the vessel is above circular
speed (delta_v < 0, retrograde burn). The same Maneuver field is used in
both cases; a negative prograde value is a retrograde burn.
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


class Apse(Enum):
    """Which apse to circularize at."""

    APOAPSIS = "apoapsis"
    PERIAPSIS = "periapsis"

    @property
    def display_name(self) -> str:
        return self.value.title()


class CircularizeAction(Action):
    """Circularize the orbit at the chosen apse via a planned maneuver node."""

    action_id: ClassVar[str] = "circularize"
    label: ClassVar[str] = "Circularize"
    description: ClassVar[str] = "Circularize the orbit at apoapsis or periapsis"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="apse",
            label="Apse",
            description="Which apse to circularize at: 'apoapsis' raises the periapsis, 'periapsis' lowers the apoapsis.",
            required=False,
            param_type=ParamType.STR,
            default="apoapsis",
        ),
        STAGING_MODE_PARAM,
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        raw_apse = param_values["apse"]
        try:
            self._apse: Apse = Apse(str(raw_apse).lower())
        except ValueError:
            valid = ", ".join(a.value for a in Apse)
            raise ValueError(f"Unknown apse '{raw_apse}'. Valid: {valid}") from None
        self._staging_mode: StagingMode | None = parse_staging_mode(param_values["staging_mode"])
        # ut of the node this action created, captured on first tick so we
        # can find it again across ticks even if other nodes get inserted.
        self._node_ut: float | None = None

        # Capture the warp rate to restore on completion (see ADR 0012).
        self._initial_warp_rate: float = state.time_warp_rate

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        # Track the highest warp seen so ``stop()`` can restore it (ADR 0012).
        if state.time_warp_rate > self._initial_warp_rate:
            self._initial_warp_rate = state.time_warp_rate

        node = self._find_our_node(state)

        if node is None:
            return self._request_node(state, commands, log)

        if execute_node(state, commands, node, self._staging_mode, dt, log, restore_warp_rate=self._initial_warp_rate):
            commands.remove_node_at_ut = node.ut
            commands.autopilot = False
            commands.throttle = 0.0
            return ActionResult(
                status=ActionStatus.SUCCEEDED,
                message=f"Circularized at {self._apse.display_name} (e={state.orbit_eccentricity:.4f})",
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
            message=f"Burn to circularize at {self._apse.display_name}: dv_remaining={node.delta_v_remaining:.1f} m/s",
        )

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        commands.throttle = 0.0
        commands.autopilot = False
        if self._node_ut is not None:
            commands.remove_node_at_ut = self._node_ut
        # Restore the warp rate the user had before the action ran (ADR 0012).
        if self._initial_warp_rate > 1.0:
            commands.time_warp_rate = self._initial_warp_rate

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
        """Compute vis-viva for the chosen apse and request node creation."""
        if state.body_gm <= 0.0 or state.orbit_semi_major_axis <= 0.0:
            return ActionResult(
                status=ActionStatus.FAILED,
                message="Cannot circularize: invalid orbit (no gravitational parameter or semi-major axis).",
            )

        if self._apse is Apse.APOAPSIS:
            apse_altitude = state.orbit_apoapsis
            time_to_apse = state.orbit_apoapsis_time_to
        else:
            apse_altitude = state.orbit_periapsis
            time_to_apse = state.orbit_periapsis_time_to

        radius = apse_altitude + state.body_radius
        if radius <= 0.0:
            return ActionResult(
                status=ActionStatus.FAILED,
                message=f"Cannot circularize at {self._apse.display_name}: target radius is non-positive.",
            )

        mu = state.body_gm
        v_current = math.sqrt(mu * (2.0 / radius - 1.0 / state.orbit_semi_major_axis))
        v_circular = math.sqrt(mu / radius)
        delta_v = v_circular - v_current

        node_ut = state.universal_time + time_to_apse
        commands.create_node = Maneuver(ut=node_ut, prograde=delta_v)
        self._node_ut = node_ut

        log.info(f"Planned circularization at {self._apse.display_name}: dv={delta_v:+.1f} m/s, in {time_to_apse:.0f}s, ut={node_ut:.1f}")
        return ActionResult(
            status=ActionStatus.RUNNING,
            message=f"Planning circularization at {self._apse.display_name} (dv={delta_v:+.1f} m/s)",
        )
