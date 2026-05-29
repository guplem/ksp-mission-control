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

from ksp_mission_control.control.actions.base import State, VesselCommands


def restore_user_warp(state: State, commands: VesselCommands) -> None:
    """Write the user-intended warp rate to ``commands`` if KSP is not already at it.

    Catches both directions: the user's intent is 100x and KSP dropped
    to 1x for a burn (write 100x), and the user's intent is 1x but KSP
    is sitting at a higher rate (write 1x). Equality skips the write so
    a no-op stop() does not generate noise in the command stream.
    """
    if state.time_warp_rate != state.user_target_warp_rate:
        commands.time_warp_rate = state.user_target_warp_rate
