"""AlignPlaneAction - tilt the orbit so it passes over a target latitude.

A pure plane change rotates the orbit around the velocity vector at the
chosen burn point. The required normal component follows directly from
the angle between the current and target orbital planes:

    delta_v = 2 * v * sin(|delta_inc| / 2)        (m/s, pure normal)

Where ``v`` is the orbital speed at the burn point and ``delta_inc`` is
the inclination change needed. The lower ``v``, the cheaper the burn.
That is why a plane change at apoapsis (slow) is much cheaper than the
same change at periapsis (fast).

Burn point selection (``crossing`` param):

- ``cheaper`` (default): the equatorial crossing with the lower orbital
  speed. On an elliptical orbit this is whichever node sits closer to
  apoapsis. Same as ``next`` on a perfectly circular orbit.
- ``next``: whichever equatorial crossing comes first in time.
- ``ascending_node``: force the ascending node.
- ``descending_node``: force the descending node.

Special case: an **equatorial current orbit** has no defined ascending
or descending node (every point on the orbit is on the equator). The
action falls back to burning at apoapsis. The new orbit's ascending or
descending node will end up at that apoapsis, depending on whether the
target latitude is positive (we burn ``+normal`` so apoapsis becomes the
new ascending node) or negative (``-normal``, apoapsis becomes the new
descending node).

Direction sign for the normal burn:

- At the ascending node, ``+normal`` raises inclination, ``-normal``
  lowers it.
- At the descending node, the signs are reversed.

This action only matches the *magnitude* of the inclination. The longitude
at which the orbit crosses the target latitude (i.e. RAAN) is set by
when the burn happens; downstream actions like ``deorbit_to_target``
correct for that via burn timing rather than another plane change.
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

# Tolerance for matching the node we requested against State.nodes by ut.
_NODE_UT_MATCH_TOLERANCE: float = 0.001

# Below this inclination (radians) the orbit is treated as equatorial:
# AN and DN are undefined and we burn at apoapsis instead. 0.001 rad is
# about 0.057 degrees, the same threshold the bridge uses to decide
# whether AN/DN are meaningful at all.
_EQUATORIAL_INCLINATION_THRESHOLD: float = 0.001

# Default angular margin: if the current inclination is within this many
# degrees of the target, the action succeeds immediately without burning.
# Loose on purpose: spending tens of m/s to shave a fraction of a degree
# is never worth it for a Kerbin desert landing.
_DEFAULT_MARGIN_DEG: float = 0.5


class Crossing(Enum):
    """Which equatorial crossing to burn at for the plane change."""

    CHEAPER = "cheaper"
    """Pick the crossing with the lower orbital speed: cheapest delta-v."""

    NEXT = "next"
    """Pick the crossing that comes soonest in universal time."""

    ASCENDING_NODE = "ascending_node"
    """Force the ascending node (orbit crossing the equator going north)."""

    DESCENDING_NODE = "descending_node"
    """Force the descending node (orbit crossing the equator going south)."""

    @property
    def display_name(self) -> str:
        """Human-readable label (e.g. 'Ascending Node', 'Cheaper')."""
        return self.value.replace("_", " ").title()


class AlignPlaneAction(Action):
    """Tilt the orbit so it can pass over a target latitude."""

    action_id: ClassVar[str] = "align_plane"
    label: ClassVar[str] = "Align Plane"
    description: ClassVar[str] = "Match orbit inclination to a target latitude via a normal burn"
    params: ClassVar[list[ActionParam]] = [
        ActionParam(
            param_id="target_latitude",
            label="Target Latitude",
            description=(
                "Latitude the orbit must pass over, in degrees. The action sets the orbit inclination "
                "to |target_latitude|. Sign of the latitude only matters when the current orbit is "
                "equatorial: it determines whether apoapsis becomes the new ascending node "
                "(target_latitude > 0) or the new descending node (target_latitude < 0)."
            ),
            required=True,
            param_type=ParamType.FLOAT,
            default=None,
            unit="deg",
        ),
        ActionParam(
            param_id="crossing",
            label="Crossing",
            description=(
                "Where to perform the plane change. 'cheaper' (default) picks the equatorial node with "
                "the lower orbital speed. 'next' picks the soonest in time. 'ascending_node' and "
                "'descending_node' force a specific node. Ignored when the current orbit is equatorial: "
                "in that case the action always burns at apoapsis."
            ),
            required=False,
            param_type=ParamType.STR,
            default=Crossing.CHEAPER.value,
        ),
        ActionParam(
            param_id="margin_deg",
            label="Margin",
            description=(
                "If the current inclination is already within this many degrees of |target_latitude|, "
                "the action succeeds without burning. Loose by default because shaving fractions of a "
                "degree off inclination is rarely worth the delta-v."
            ),
            required=False,
            param_type=ParamType.FLOAT,
            default=_DEFAULT_MARGIN_DEG,
            unit="deg",
        ),
        STAGING_MODE_PARAM,
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        self._target_latitude_deg: float = float(param_values["target_latitude"])
        if not -90.0 <= self._target_latitude_deg <= 90.0:
            raise ValueError(f"target_latitude must be in [-90, 90], got {self._target_latitude_deg}.")

        raw_crossing = param_values["crossing"]
        try:
            self._crossing: Crossing = Crossing(str(raw_crossing).lower())
        except ValueError:
            valid = ", ".join(c.value for c in Crossing)
            raise ValueError(f"Unknown crossing '{raw_crossing}'. Valid: {valid}") from None

        self._margin_deg: float = float(param_values["margin_deg"])
        if self._margin_deg < 0.0:
            raise ValueError(f"margin_deg must be non-negative, got {self._margin_deg}.")

        self._staging_mode: StagingMode | None = parse_staging_mode(param_values["staging_mode"])
        self._node_ut: float | None = None

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        target_inc_rad = math.radians(abs(self._target_latitude_deg))
        delta_inc_rad = target_inc_rad - state.orbit_inclination

        if abs(delta_inc_rad) <= math.radians(self._margin_deg):
            # Inclination is on target. Clean up any leftover node we created
            # before exiting (typical case: the burn just completed and the
            # vessel is now aligned).
            commands.throttle = 0.0
            commands.autopilot = False
            if self._node_ut is not None:
                commands.remove_node_at_ut = self._node_ut
            return ActionResult(
                status=ActionStatus.SUCCEEDED,
                message=(
                    f"Plane aligned: inclination {math.degrees(state.orbit_inclination):.2f}° "
                    f"within {self._margin_deg:.2f}° of target {abs(self._target_latitude_deg):.2f}°."
                ),
            )

        node = self._find_our_node(state)
        if node is None:
            return self._plan_burn(state, commands, delta_inc_rad, log)

        if execute_node(state, commands, node, self._staging_mode, dt, log):
            commands.remove_node_at_ut = node.ut
            commands.autopilot = False
            commands.throttle = 0.0
            return ActionResult(
                status=ActionStatus.SUCCEEDED,
                message=f"Plane aligned: inclination {math.degrees(state.orbit_inclination):.2f}°.",
            )

        if state.thrust_available <= 0.0 and commands.stage is not True:
            return ActionResult(
                status=ActionStatus.FAILED,
                message=f"Failed: no thrust available. dv_remaining={node.delta_v_remaining:.1f} m/s",
            )

        return ActionResult(
            status=ActionStatus.RUNNING,
            message=f"Burning to align plane: dv_remaining={node.delta_v_remaining:.1f} m/s",
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

    def _plan_burn(self, state: State, commands: VesselCommands, delta_inc_rad: float, log: ActionLogger) -> ActionResult:
        """Pick the burn point and request a normal-only maneuver node."""
        if state.body_gm <= 0.0 or state.orbit_semi_major_axis <= 0.0:
            return ActionResult(
                status=ActionStatus.FAILED,
                message="Cannot align plane: invalid orbit (no gravitational parameter or semi-major axis).",
            )

        burn = self._pick_burn_point(state)
        if burn is None:
            return ActionResult(
                status=ActionStatus.FAILED,
                message=(f"Cannot align plane via {self._crossing.display_name}: ascending/descending node is undefined for the current orbit."),
            )
        burn_ut, burn_speed, at_ascending_node, burn_label = burn

        if burn_speed <= 0.0:
            return ActionResult(
                status=ActionStatus.FAILED,
                message=f"Cannot align plane: invalid orbital speed at burn point ({burn_speed:.1f} m/s).",
            )

        dv_magnitude = 2.0 * burn_speed * math.sin(abs(delta_inc_rad) / 2.0)

        # +normal raises inclination at the ascending node, -normal at the
        # descending node. When delta_inc < 0 (we are lowering inclination),
        # both signs flip.
        raises_inclination = delta_inc_rad > 0
        if at_ascending_node:
            normal_dv = dv_magnitude if raises_inclination else -dv_magnitude
        else:
            normal_dv = -dv_magnitude if raises_inclination else dv_magnitude

        commands.create_node = Maneuver(ut=burn_ut, normal=normal_dv)
        self._node_ut = burn_ut

        log.info(
            f"Planned plane change at {burn_label}: "
            f"current inc {math.degrees(state.orbit_inclination):.2f}° -> target {abs(self._target_latitude_deg):.2f}° "
            f"(dv={normal_dv:+.1f} m/s normal at v={burn_speed:.1f} m/s, ut={burn_ut:.1f})"
        )
        return ActionResult(
            status=ActionStatus.RUNNING,
            message=f"Planning plane change at {burn_label} (dv={dv_magnitude:.1f} m/s)",
        )

    def _pick_burn_point(self, state: State) -> tuple[float, float, bool, str] | None:
        """Return ``(burn_ut, burn_speed, at_ascending_node, label)`` or ``None``.

        When the current orbit is equatorial, returns apoapsis with
        ``at_ascending_node`` set per the sign of ``target_latitude`` (so
        the resulting AN/DN of the new inclined orbit ends up at apoapsis).
        Otherwise picks AN or DN per the ``crossing`` parameter.
        """
        if state.orbit_inclination < _EQUATORIAL_INCLINATION_THRESHOLD:
            apo_radius = state.orbit_apoapsis + state.body_radius
            if apo_radius <= 0.0:
                return None
            apo_speed = math.sqrt(state.body_gm * max(0.0, 2.0 / apo_radius - 1.0 / state.orbit_semi_major_axis))
            burn_ut = state.universal_time + state.orbit_apoapsis_time_to
            # For an equatorial start, the burn defines the new AN or DN.
            # Positive target latitude -> apoapsis becomes new AN; negative -> new DN.
            at_ascending_node = self._target_latitude_deg >= 0.0
            label = f"apoapsis (equatorial start; sets new {'AN' if at_ascending_node else 'DN'})"
            return burn_ut, apo_speed, at_ascending_node, label

        an_ut = state.orbit_ascending_node_ut
        dn_ut = state.orbit_descending_node_ut
        an_speed = state.orbit_ascending_node_speed
        dn_speed = state.orbit_descending_node_speed
        an_defined = math.isfinite(an_ut)
        dn_defined = math.isfinite(dn_ut)

        if self._crossing is Crossing.ASCENDING_NODE:
            if not an_defined:
                return None
            return an_ut, an_speed, True, "ascending node"
        if self._crossing is Crossing.DESCENDING_NODE:
            if not dn_defined:
                return None
            return dn_ut, dn_speed, False, "descending node"
        if self._crossing is Crossing.NEXT:
            if an_defined and (not dn_defined or an_ut <= dn_ut):
                return an_ut, an_speed, True, "next crossing (AN)"
            if dn_defined:
                return dn_ut, dn_speed, False, "next crossing (DN)"
            return None
        # CHEAPER: lower speed wins. Ties go to AN.
        if an_defined and (not dn_defined or an_speed <= dn_speed):
            return an_ut, an_speed, True, "cheaper crossing (AN)"
        if dn_defined:
            return dn_ut, dn_speed, False, "cheaper crossing (DN)"
        return None
