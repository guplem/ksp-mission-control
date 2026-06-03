"""Shared helper for restoring the user's intended time-warp rate.

Used by any action that drops warp for a critical section and needs to
hand control back to the user's intent on completion or abort
(see ADR 0012). The single source of truth for what the user wants is
``state.user_target_warp_rate``; this helper compares it against the
live KSP rate and emits a write only when they differ, so a stable
"already at the right rate" tick produces no redundant command.

Centralizing the policy here means changes to the restore condition
(e.g. adding a float tolerance, or always rewriting regardless of
current state) live in one place instead of nine action stop() bodies
and two ``execute_node`` return paths.
"""

from __future__ import annotations

from ksp_mission_control.control.actions.base import (
    ActionResult,
    ActionStatus,
    State,
    VesselCommands,
)


def restore_user_warp(state: State, commands: VesselCommands) -> None:
    """Write the user-intended warp rate to ``commands`` if KSP is not already at it.

    Catches both directions: the user's intent is 100x and KSP dropped
    to 1x for a burn (write 100x), and the user's intent is 1x but KSP
    is sitting at a higher rate (write 1x). Equality skips the write so
    a no-op stop() does not generate noise in the command stream.
    """
    if state.time_warp_rate != state.user_target_warp_rate:
        commands.time_warp_rate = state.user_target_warp_rate


def drop_warp_for_critical_section(
    state: State,
    commands: VesselCommands,
    dropping_for: str,
) -> ActionResult | None:
    """Drop KSP to 1x warp before a critical section; return RUNNING or None.

    Returns an ``ActionResult(RUNNING)`` when ``state.time_warp_rate``
    is above 1x, so the caller's ``tick()`` can return it immediately and
    re-enter on the next poll with warp at 1x. Returns ``None`` when
    warp is already at or below 1x and the caller can proceed.

    Used at the top of ``tick()`` by any action whose feedback loop
    requires 1x: PD altitude/velocity controllers, iterative replanning
    loops, position-derivative velocity estimators, and orientation waits
    (rails warp freezes vessel attitude). ``dropping_for`` is woven into
    the user-facing message (e.g. ``"hovering"``, ``"refining deorbit"``).
    """
    if state.time_warp_rate > 1.0:
        commands.time_warp_rate = 1.0
        return ActionResult(
            status=ActionStatus.RUNNING,
            message=f"Dropping warp ({state.time_warp_rate:g}x -> 1x) before {dropping_for}.",
        )
    return None
