"""Shared helper for auto-staging a vessel when engines run out of fuel.

Used by any action that wants to advance the staging sequence automatically
during a burn or ascent: ``LaunchAction``, ``AerobreakAction``, future
descent/transfer actions, etc. The helper is stateless. Callers pass the
current ``State``, the desired ``StagingMode``, and a mutable
``VesselCommands`` buffer; the helper sets ``commands.stage = True`` when
staging is warranted and returns ``True`` so the caller knows a stage was
commanded this tick.

Two modes:

``StagingMode.FULL_DEPLETION``:
    Stage only when total available thrust has dropped to zero (every
    currently-active engine has flamed out) AND inactive engines remain
    to ignite. Conservative; never drops a partly-functional booster
    cluster.

``StagingMode.ANY_FLAMEOUT``:
    Stage as soon as ANY currently-active engine has flamed out, even
    when other engines still produce thrust. Useful for asparagus-style
    designs: spent corner boosters are deadweight, and dropping them
    mid-burn preserves delta-v on the inner stack. Also covers the
    full-depletion case (every active engine flamed out implies at
    least one flameout).
"""

from __future__ import annotations

from enum import Enum

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionParam,
    ParamType,
    State,
    VesselCommands,
)


class StagingMode(Enum):
    """Trigger condition for ``auto_stage``."""

    FULL_DEPLETION = "full_depletion"
    """Stage only when no thrust is available and inactive engines remain."""

    ANY_FLAMEOUT = "any_flameout"
    """Stage as soon as any active engine flames out (drops spent side boosters)."""


# Shared param descriptor: every action that opts into auto-staging declares
# the same parameter, so .plan files and the UI present a uniform interface.
STAGING_MODE_PARAM: ActionParam = ActionParam(
    param_id="staging_mode",
    label="Staging Mode",
    description=(
        "Automatic staging trigger. "
        "'full_depletion' stages when all active engines have flamed out and an inactive engine is waiting. "
        "'any_flameout' also stages as soon as a single engine flames out, useful for dropping spent asparagus side boosters. "
        "Omit (or leave blank) for no auto-staging."
    ),
    required=False,
    param_type=ParamType.STR,
    default=None,
)


def parse_staging_mode(value: object) -> StagingMode | None:
    """Parse a ``staging_mode`` param value into an optional StagingMode.

    ``None`` (or an empty/whitespace string) means "no auto-staging". A
    non-empty string must match a StagingMode value, case-insensitive.
    Raises ``ValueError`` on any other input.
    """
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    try:
        return StagingMode(text)
    except ValueError:
        valid = ", ".join(m.value for m in StagingMode)
        raise ValueError(f"Unknown staging_mode '{value}'. Valid: {valid} (or omit for off).") from None


def auto_stage(
    state: State,
    commands: VesselCommands,
    mode: StagingMode | None,
    log: ActionLogger,
) -> bool:
    """Stage the vessel if the chosen condition is met.

    Returns ``True`` when ``commands.stage`` was set to True this call.
    Returns ``False`` when ``mode`` is ``None`` (auto-staging disabled),
    when the vessel is already at the final stage, or when the trigger
    condition has not been met. The caller can therefore use the helper
    unconditionally: ``if auto_stage(...): return RUNNING("Staging")``.

    The caller keeps control of throttle, autopilot, and so on; this helper
    only mutates ``commands.stage``.
    """
    if mode is None:
        return False
    if state.stage_current <= 0:
        return False

    flameouts = state.parts.engines_flameout()
    inactive = state.parts.engines_inactive()

    # ANY_FLAMEOUT: drop spent boosters eagerly. We require either inactive
    # engines waiting to ignite next, OR remaining thrust on the inner
    # stack; otherwise staging would jettison our only thrust source.
    if mode is StagingMode.ANY_FLAMEOUT and flameouts > 0 and (inactive > 0 or state.thrust_available > 0.0):
        commands.stage = True
        log.info(
            f"Auto-stage (any flameout): dropping {flameouts} spent engine(s); thrust_available={state.thrust_available:.0f}N, inactive={inactive}"
        )
        return True

    # FULL_DEPLETION (and ANY_FLAMEOUT fallback): stage when total thrust
    # has dropped to zero and inactive engines remain to ignite.
    if state.thrust_available <= 0.0 and inactive > 0:
        commands.stage = True
        log.info(f"Auto-stage (full depletion): no thrust, igniting next stage ({inactive} inactive engine(s) waiting)")
        return True

    return False
