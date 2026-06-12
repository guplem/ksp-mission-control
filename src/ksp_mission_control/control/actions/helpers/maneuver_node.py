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
             Autopilot points at burn_vector_remaining. Throttle stays 0
             until the vessel's facing is within _BURN_ALIGNMENT_TOLERANCE_DEG
             of the burn vector (the alignment gate), so the engine never
             fires while the autopilot is still slewing onto the new
             direction. Once aligned, throttle is full while
             burn_time_estimate >> dt and tapers to
             ``burn_time_estimate / (dt * _TAPER_MARGIN)`` as the burn
             approaches completion, so the engine ramps down across the
             last ~_TAPER_MARGIN ticks instead of overshooting on the
             final tick.
    Done:    delta_v_remaining <= _BURN_COMPLETE_DV, OR the remaining
             burn vector has flipped retrograde of the original planned
             direction (i.e. dot(burn_vector, burn_vector_remaining) <= 0,
             meaning the optimal burn moment has already been passed).
             Throttle = 0, helper returns True.

``burn_start_ut`` is recomputed every tick from current mass, Isp, and
available thrust via the Tsiolkovsky rocket equation, so changes during
the burn (staging, drained tanks) self-correct.

Auto-staging is handled in-helper: pass a non-None ``staging_mode`` and
``auto_stage`` is invoked before throttle decisions so a spent stage is
dropped mid-burn without the caller wiring the check itself. The helper
does not surface a separate "no thrust" signal; callers that need to fail
on thrust exhaustion check ``state.thrust_available`` after the helper
returns ``False``.
"""

from __future__ import annotations

import math

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionResult,
    ActionStatus,
    AutopilotDirection,
    ManeuverNode,
    ReferenceFrame,
    State,
    VesselCommands,
    angle_between,
)
from ksp_mission_control.control.actions.helpers.staging import StagingMode, auto_stage

# Default tolerance for matching a maneuver node by its planned ut. The bridge
# writes back the same ut we set in Maneuver.ut, so this tolerance only protects
# against round-trip float jitter, not real timing drift.
_NODE_UT_MATCH_TOLERANCE: float = 0.001

# Burn is considered complete when remaining delta-v drops below this
# threshold. 0.1 m/s matches the kRPC tutorial's deadband and keeps small
# numerical drift from re-triggering the burn after completion.
_BURN_COMPLETE_DV: float = 0.1

# Standard gravity, used in Tsiolkovsky (Isp seconds -> exhaust velocity).
_STANDARD_GRAVITY: float = 9.80665

# Throttle taper margin. Throttle starts tapering when the remaining burn
# at full thrust would take less than ``_TAPER_MARGIN * dt`` seconds, so
# the engine ramps down over the last ~8 ticks instead of slamming to full
# until the final tick. Wider margin = softer landing with more low-throttle
# ticks near completion, trading a little burn-window efficiency for better
# autopilot tracking at small remaining dv (where the burn vector is
# noise-dominated and a misaligned full-tick impulse easily overshoots).
# Raised from 3 to 8 after two deorbit burns (~1.6s at full throttle on a
# high-TWR stage, so the whole burn fit in 2-3 ticks) overshot by 5-10 m/s,
# each worth ~80-100 km of landing error.
_TAPER_MARGIN: float = 8.0

# Maximum angular error (degrees) between the vessel's facing and the
# remaining burn vector before the helper opens the throttle. The autopilot
# is pointed at the burn vector every tick, but slewing the vessel takes
# time; firing before it arrives deposits delta-v off-axis and corrupts the
# orbit. 10 deg matches wait_for's orientation margin: loose enough that a
# wobbly craft settles into the window without stalling the burn, tight
# enough that under 2% of thrust goes off-axis (cos 10 deg = 0.985).
_BURN_ALIGNMENT_TOLERANCE_DEG: float = 10.0

# Per-tick safety margin for the warp step-down threshold. The helper
# triggers a one-level drop when one tick's worth of game time at the
# current rate, multiplied by this factor, would put the next check past
# the burn. 2.0 leaves one extra tick of headroom against tick-rate jitter.
_WARP_STEP_DOWN_TICK_MARGIN: float = 2.0

# Fixed game-time slack added on top of the per-tick margin so the final
# drop to 1x lands well before the burn starts. The buffer here is paid
# at 1x (after the drop), so 15 game seconds = 15 real seconds of cold
# coast at 1x before the burn. That gives KSP physics time to settle
# after the warp transition and the autopilot time to track the new burn
# direction without entering the burn window mid-transient.
_WARP_STEP_DOWN_GAME_SECONDS_SAFETY: float = 15.0

# KSP rails-warp levels, ascending. The helper steps the warp rate down
# through these levels one entry at a time, one drop per tick, so that
# high warp (e.g. 1000x) does not require predicting hundreds of game
# seconds ahead and waiting through them at 1x. Physics-warp levels
# (1, 2, 3, 4) are not included because rails warp is the relevant mode
# for any orbital maneuver burn -- the drop is a no-op while in physics
# warp anyway.
_RAILS_WARP_LEVELS: tuple[int, ...] = (1, 5, 10, 50, 100, 1000, 10000, 100000)


def _next_lower_rails_warp_rate(current_rate: float) -> float:
    """Return the next rails-warp level strictly below ``current_rate``.

    Returns ``1.0`` when ``current_rate`` is already at or below the
    lowest level. The match uses ``level < current_rate`` so that a
    perfectly equal level steps to the one below (e.g. 50x -> 10x).
    """
    for level in reversed(_RAILS_WARP_LEVELS):
        if level < current_rate:
            return float(level)
    return 1.0


def execute_node(
    state: State,
    commands: VesselCommands,
    node: ManeuverNode,
    staging_mode: StagingMode | None,
    dt: float,
    log: ActionLogger,
) -> bool:
    """Drive the vessel through one maneuver node.

    Sets ``commands.autopilot`` and ``commands.autopilot_direction`` to
    point along the node's remaining burn vector every tick. Throttles to
    0 while still coasting, and also once the burn window is entered until
    the vessel is aligned within ``_BURN_ALIGNMENT_TOLERANCE_DEG`` of the
    burn vector; only then does it throttle up. When ``staging_mode`` is
    not ``None``, also delegates to
    ``auto_stage`` so spent stages drop without caller wiring. Returns
    ``True`` when ``node.delta_v_remaining`` falls below the completion
    threshold.

    Warp restore is handled by the ``ActionRunner`` after ``stop()`` runs
    (ADR 0012), so this helper does not write ``time_warp_rate`` on the
    burn-complete return path.

    The caller is responsible for the rest of the cleanup after
    completion: setting ``commands.remove_node_at_ut`` and disengaging the
    autopilot.
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

    # Overshoot detection: once the remaining burn vector points retrograde
    # of the originally planned burn vector, the optimal burn moment has
    # passed. The residual vector is now small enough that its direction is
    # noise-dominated, so the autopilot cannot realign in time and any
    # further throttle deposits dv in roughly the wrong direction, pushing
    # the magnitude further from zero. Stop here; the residual is below
    # what we can correct at the current tick rate.
    burn_dot = (
        node.burn_vector[0] * node.burn_vector_remaining[0]
        + node.burn_vector[1] * node.burn_vector_remaining[1]
        + node.burn_vector[2] * node.burn_vector_remaining[2]
    )
    if burn_dot <= 0.0:
        commands.throttle = 0.0
        log.info(f"Maneuver complete (overshoot detected, dv_remaining={node.delta_v_remaining:.2f} m/s)")
        return True

    # Auto-stage before throttle decisions so a spent stage is dropped
    # mid-burn and the next tick re-plans burn timing against the new
    # mass/thrust. Short-circuits when staging_mode is None.
    auto_stage(state, commands, staging_mode, log)

    # If burn_time is not computable (no thrust, no fuel, or engines off)
    # stay cold rather than commanding throttle into a vessel that cannot
    # burn. This protects against runaway throttle commands during stages
    # or flameouts; once thrust returns, the next tick will plan the burn.
    if not math.isfinite(node.burn_time_estimate):
        commands.throttle = 0.0
        log.warn(f"Cannot plan burn: thrust={state.thrust_available:.1f}N, isp_vac={state.engine_impulse_specific_vacuum:.1f}s")
        return False

    burn_start_ut = node.ut - node.burn_time_estimate / 2.0

    # If a plan put the vessel under time warp to cross the coast quickly,
    # step the rate down one rails-warp level when one tick's worth of
    # game time at the current rate could put the next check past the
    # burn. The progressive step-down avoids the "jump from 1000x to 1x
    # while still 500s away, then idle for 500s real" failure mode that
    # a single fixed buffer suffers from at high warp rates.
    if state.time_warp_rate > 1.0:
        tick_game_time = dt * state.time_warp_rate
        drop_threshold = tick_game_time * _WARP_STEP_DOWN_TICK_MARGIN + _WARP_STEP_DOWN_GAME_SECONDS_SAFETY
        if state.universal_time + drop_threshold >= burn_start_ut:
            next_rate = _next_lower_rails_warp_rate(state.time_warp_rate)
            commands.time_warp_rate = next_rate
            log.info(
                f"Stepping warp down to {next_rate:g}x: burn starts in "
                f"{burn_start_ut - state.universal_time:.1f}s game time "
                f"(was {state.time_warp_rate:g}x, threshold {drop_threshold:.1f}s game)."
            )

    if state.universal_time < burn_start_ut:
        commands.throttle = 0.0
        log.debug(
            f"Coasting to burn: ut_to_start={burn_start_ut - state.universal_time:.1f}s, "
            f"burn_time={node.burn_time_estimate:.1f}s, dv_remaining={node.delta_v_remaining:.1f} m/s"
        )
        return False

    # Alignment gate: the burn window is open, but do not fire until the
    # vessel has actually slewed onto the burn vector. The autopilot is
    # already commanded toward burn_vector_remaining above; rotating there
    # takes time, and a full-throttle tick while still misaligned deposits
    # delta-v off-axis and corrupts the orbit. This bites hardest when the
    # node sits close in time relative to the burn duration (e.g. raising
    # apoapsis from a near-circular orbit), where burn_start_ut falls in the
    # past and the window is already open on the first tick. Throttle stays
    # 0 while we keep orienting; thrust is still available, so the caller's
    # no-thrust check does not false-fail during the hold.
    alignment_error = angle_between(state.orientation_direction_body_non_rotating, node.burn_vector_remaining)
    if alignment_error > _BURN_ALIGNMENT_TOLERANCE_DEG:
        commands.throttle = 0.0
        log.debug(
            f"Holding burn: {alignment_error:.1f} deg off burn vector "
            f"(tolerance {_BURN_ALIGNMENT_TOLERANCE_DEG:.1f} deg), dv_remaining={node.delta_v_remaining:.1f} m/s"
        )
        return False

    # Taper throttle as the burn approaches completion. Without this, a
    # full-throttle final tick overshoots by (thrust / mass) * dt m/s, the
    # node's remaining burn vector flips retrograde, and the next tick
    # over-corrects in the opposite direction; the loop oscillates around
    # zero until fuel runs out. Scaling throttle by burn_time / (dt * margin)
    # means the engine ramps down across the last ~_TAPER_MARGIN ticks.
    commands.throttle = min(1.0, node.burn_time_estimate / (dt * _TAPER_MARGIN))
    log.debug(
        f"Burning: dv_remaining={node.delta_v_remaining:.1f} m/s, burn_time_left~{node.burn_time_estimate:.1f}s, throttle={commands.throttle:.2f}"
    )
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


def find_maneuver_node_by_ut(
    state: State,
    node_ut: float | None,
    tolerance: float = _NODE_UT_MATCH_TOLERANCE,
) -> ManeuverNode | None:
    """Return the node in ``state.nodes`` whose ut matches ``node_ut``.

    Returns ``None`` when ``node_ut`` is ``None`` (the caller has not
    requested a node yet) or when no node in state matches within
    ``tolerance``. Used by actions that create a node via
    ``commands.create_node`` and later need to locate it across ticks,
    even when other nodes get inserted in between.
    """
    if node_ut is None:
        return None
    for candidate in state.nodes:
        if abs(candidate.ut - node_ut) <= tolerance:
            return candidate
    return None


def fail_if_node_has_no_thrust(
    state: State,
    commands: VesselCommands,
    node: ManeuverNode,
) -> ActionResult | None:
    """Return a FAILED ActionResult when the vessel cannot complete the burn.

    Used by node-driven actions after ``execute_node`` returns. The check
    exempts the tick on which ``auto_stage`` just queued a stage (state
    was read before this tick's command applies, so a flameout shows
    zero thrust even though the next stage will ignite next tick).
    Returns ``None`` when there is still thrust or a stage is pending,
    so the caller can continue burning.
    """
    if state.thrust_available <= 0.0 and commands.stage is not True:
        return ActionResult(
            status=ActionStatus.FAILED,
            message=f"Failed: no thrust available. dv_remaining={node.delta_v_remaining:.1f} m/s",
        )
    return None
