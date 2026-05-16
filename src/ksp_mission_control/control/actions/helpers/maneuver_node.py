"""Shared helper for executing a maneuver node.

Used by any action that drives the vessel through a kRPC maneuver node:
circularize, raise/lower orbit, Hohmann transfers, etc. The helper is
stateless. Callers pass the current ``State``, the ``ManeuverNode`` to
execute, and a mutable ``VesselCommands`` buffer; the helper sets
autopilot direction and throttle each tick and returns ``True`` once the
burn is complete.

Phases:
    Cold:    state.universal_time < burn_start_ut.
             Autopilot points at burn_vector_remaining, throttle = 0.
    Burn:    state.universal_time >= burn_start_ut.
             Autopilot points at burn_vector_remaining, throttle = 1.
    Done:    delta_v_remaining <= _BURN_COMPLETE_DV.
             Throttle = 0, helper returns True.

``burn_start_ut`` is recomputed every tick from current mass, Isp, and
available thrust via the Tsiolkovsky rocket equation, so changes during
the burn (staging, drained tanks) self-correct.
"""

from __future__ import annotations

import math

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    AutopilotDirection,
    ManeuverNode,
    ReferenceFrame,
    State,
    VesselCommands,
)

# Burn is considered complete when remaining delta-v drops below this
# threshold. 0.1 m/s matches the kRPC tutorial's deadband and keeps small
# numerical drift from re-triggering the burn after completion.
_BURN_COMPLETE_DV: float = 0.1

# Standard gravity, used in Tsiolkovsky (Isp seconds -> exhaust velocity).
_STANDARD_GRAVITY: float = 9.80665


def execute_node(
    state: State,
    commands: VesselCommands,
    node: ManeuverNode,
    log: ActionLogger,
) -> bool:
    """Drive the vessel through one maneuver node.

    Sets ``commands.autopilot`` and ``commands.autopilot_direction`` to
    point along the node's remaining burn vector every tick. Throttles to
    0 while still coasting; throttles to 1 once the burn window is
    entered. Returns ``True`` when ``node.delta_v_remaining`` falls below
    the completion threshold.

    The caller is responsible for cleanup after completion (e.g. setting
    ``commands.remove_node_at_ut`` and disengaging the autopilot).
    """
    # Always orient toward the remaining burn direction. Using the
    # remaining vector (not the initial one) means orientation tracks the
    # corrected direction if part of the burn has already executed.
    commands.autopilot = True
    commands.autopilot_direction = AutopilotDirection(
        vector=node.burn_vector_remaining,
        reference_frame=ReferenceFrame.BODY_NON_ROTATING,
    )

    if node.delta_v_remaining <= _BURN_COMPLETE_DV:
        commands.throttle = 0.0
        log.info(f"Maneuver complete (dv_remaining={node.delta_v_remaining:.2f} m/s)")
        return True

    # If burn_time is not computable (no thrust, no fuel, or engines off)
    # stay cold rather than commanding throttle into a vessel that cannot
    # burn. This protects against runaway throttle commands during stages
    # or flameouts; once thrust returns, the next tick will plan the burn.
    if not math.isfinite(node.burn_time_estimate):
        commands.throttle = 0.0
        log.warn(f"Cannot plan burn: thrust={state.thrust_available:.1f}N, isp_vac={state.engine_impulse_specific_vacuum:.1f}s")
        return False

    burn_start_ut = node.ut - node.burn_time_estimate / 2.0

    if state.universal_time < burn_start_ut:
        commands.throttle = 0.0
        log.debug(
            f"Coasting to burn: ut_to_start={burn_start_ut - state.universal_time:.1f}s, "
            f"burn_time={node.burn_time_estimate:.1f}s, dv_remaining={node.delta_v_remaining:.1f} m/s"
        )
        return False

    commands.throttle = 1.0
    log.debug(f"Burning: dv_remaining={node.delta_v_remaining:.1f} m/s, burn_time_left~{node.burn_time_estimate:.1f}s")
    return False


def tsiolkovsky_burn_time(delta_v: float, mass: float, isp: float, thrust: float) -> float:
    """Estimate burn duration for a given delta-v.

    Tsiolkovsky: m1 = m0 / exp(dv / (Isp * g0)); flow = F / (Isp * g0);
    burn_time = (m0 - m1) / flow.

    Returns ``float('inf')`` if any input would make the burn impossible
    (no thrust, zero Isp, zero mass). Callers should treat that as
    "stay cold; we can't compute when to start".

    Used by the bridge to pre-compute ``ManeuverNode.burn_time_estimate``
    each tick from current vessel mass, vacuum Isp, and available thrust.
    """
    if thrust <= 0.0 or isp <= 0.0 or mass <= 0.0:
        return float("inf")
    exhaust_velocity = isp * _STANDARD_GRAVITY
    final_mass = mass / math.exp(delta_v / exhaust_velocity)
    flow_rate = thrust / exhaust_velocity
    return (mass - final_mass) / flow_rate
