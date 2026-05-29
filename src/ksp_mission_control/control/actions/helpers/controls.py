"""Shared helper for releasing the vessel's active control inputs.

Used by any action that ends a control sequence and wants to leave the
vessel in a neutral state: no throttle, no autopilot hold, no SAS hold.
Centralizes the three-field cleanup so a single change (e.g. also clear
RCS, or zero out translation inputs) propagates to every caller.

Use in ``stop()`` bodies whose action drove throttle, autopilot, or SAS
during ``tick()``. Actions that intentionally hand off an enabled SAS or
autopilot to a downstream step should not call this helper.
"""

from __future__ import annotations

from ksp_mission_control.control.actions.base import VesselCommands


def release_controls(commands: VesselCommands) -> None:
    """Set throttle to 0 and disengage autopilot and SAS.

    Writes three fields on the command buffer; other fields are left
    untouched, so callers can still set further cleanup (e.g.
    ``commands.remove_node_at_ut``) around this call.
    """
    commands.throttle = 0.0
    commands.autopilot = False
    commands.sas = False
