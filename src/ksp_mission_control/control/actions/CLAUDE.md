# Action authoring guide

This folder holds every vessel action. The action registry auto-discovers any
`<folder>/action.py` that defines an `Action` subclass (see `registry.py`).
Read this and ADR 0009 before adding a new action or modifying an existing one.

This guide covers **file structure, helpers, and idioms specific to writing
an action file**. The lifecycle semantics (what `start`/`tick`/`stop` are
required to do, FAILED vs RUNNING, param access rules, log levels, cleanup
expectations) live in
[ADR 0009 - Action Lifecycle Contract](../../../../adr/0009-action-lifecycle-contract.md).
Read it first. This guide is silent on anything the ADR already specifies.

Other relevant ADRs:
- [0006 - Action Execution System](../../../../adr/0006-action-execution-system.md): architecture (pure `State -> Commands`, no kRPC in actions).
- [0011 - Atomic Actions and `wait_for`](../../../../adr/0011-atomic-actions-and-wait-for.md): what belongs as an action param vs. a `wait_for` precondition.
- [0012 - Warp Handling in Actions](../../../../adr/0012-warp-handling-in-actions.md): the capture-and-restore pattern actions follow when they need to drop time warp for a critical section.

## Folder layout

```
actions/
  base.py                  # Action ABC, State, VesselCommands, enums, ActionParam
  registry.py              # auto-discovers <folder>/action.py
  runner.py                # ActionRunner: step()/start/stop lifecycle
  plan_executor.py         # multi-step plan driver
  multi_track_executor.py  # parallel tracks
  flight_plan.py           # .plan parser
  helpers/                 # shared helpers called BY actions (not lifecycle executors)
    maneuver_node.py       # drive vessel through a maneuver node
    staging.py             # auto-stage on fuel exhaustion / engine flameout
  <action_id>/
    action.py              # exactly one Action subclass; folder name == action_id
```

One folder per action. The folder name and the `action_id` must match.

`helpers/` is for **action-internal helpers**: pure functions/types that
actions call to keep their `tick()` short. It is not for the lifecycle
executors (`runner.py`, `plan_executor.py`, `multi_track_executor.py`)
which run actions from the outside.

## Canonical `action.py` layout

Every action file follows this order. Skip sections that are empty.

```python
"""<ActionName> - one-line summary.

Longer paragraph explaining the algorithm, phases, parameter defaults,
and any non-obvious math. Reference units (m, m/s, N, deg) explicitly.
"""

from __future__ import annotations

# stdlib
import math
from enum import Enum
from typing import Any, ClassVar

# project
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
from ksp_mission_control.control.actions.helpers.<module> import ...  # if needed

# Module-level tuning constants. Always leading underscore, typed.
_TOLERANCE: float = 0.001


# Module-level enums and dataclasses (if any).
class SomeMode(Enum):
    ...


# Module-level helpers (pure functions, no Action class state).
def _module_helper(x: float) -> float:
    ...


class SomeAction(Action):
    """One-line class summary."""

    action_id: ClassVar[str] = "some_action"
    label: ClassVar[str] = "Some Action"
    description: ClassVar[str] = "Short user-facing description."
    params: ClassVar[list[ActionParam]] = [
        ActionParam(...),
        ...
    ]

    def start(self, state: State, param_values: dict[str, Any]) -> None:
        ...

    def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
        ...

    def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
        ...

    # ---- Helpers ------------------------------------------------------
    def _private_helper(self, ...) -> ...:
        ...
```

Layout rules:

- **One Action class per file.** No exceptions.
- **ClassVar order is fixed:** `action_id`, `label`, `description`, `params`.
- **Lifecycle order is fixed:** `start` -> `tick` -> `stop` -> private helpers.
- **Private helpers** live at the bottom of the class, separated by
  `# ---- Helpers ------------------------------------------------------`
  when there are 2 or more. A single one-off helper without the marker is fine.
- **No `__init__` override.** State is initialized in `start()`. The registry
  instantiates actions with no arguments.
- **No section banners outside the helpers marker.** Don't decorate imports,
  constants, or class headers with `# ---` separator lines; one blank line
  between sections is enough.
- **Lightweight phase comments inside long control loops are OK.** For
  `tick()` methods that genuinely have 4+ phases sharing local state
  (`translate.tick()` is the canonical example), a plain numbered comment
  per phase aids navigation. Prefer extracting a helper when a phase is
  self-contained. Avoid box-drawing decorations.

## Deferred validation pattern (`_fail_message`)

ADR 0009 requires `start()` to raise `ValueError` for invalid input. Some
state-dependent checks cannot run that way: by the time the runner calls
`start()` it has already accepted the action, and the validation depends
on `state`. For those, capture a message and surface it on the first tick:

```python
def start(self, state: State, param_values: dict[str, Any]) -> None:
    self._target_altitude: float = float(param_values["target_altitude"])
    self._fail_message: str | None = None
    if self._target_altitude < state.orbit_periapsis:
        self._fail_message = (
            f"Cannot lower apoapsis to {self._target_altitude:.0f}m: "
            f"current periapsis is {state.orbit_periapsis:.0f}m."
        )

def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
    if self._fail_message is not None:
        return ActionResult(status=ActionStatus.FAILED, message=self._fail_message)
    ...
```

Initialize `self._fail_message: str | None = None` even when no deferred
check fires. Use this only when a check needs `state`; never for plain input
validation (raise `ValueError` for those, per ADR 0009).

Examples in tree: `launch`, `change_apse`.

## Time-warp restore pattern

Any action that performs a maneuver burn or iterates state across ticks
has a critical section that needs 1x warp (see ADR 0012 for the full
rationale). Actions do **not** capture warp at start time. They read the
user's intent from `state.user_target_warp_rate`, which the session
plumbs into State each tick.

```python
def start(self, state: State, param_values: dict[str, Any]) -> None:
    ...
    # No warp capture. Do not store state.time_warp_rate.

def tick(self, state: State, commands: VesselCommands, dt: float, log: ActionLogger) -> ActionResult:
    # Drop warp at the start of any non-burn critical section
    # (e.g. an iterative refinement loop or PD controller).
    warp_result = drop_warp_for_critical_section(state, commands, "<dropping_for>")
    if warp_result is not None:
        return warp_result
    ...
    # For maneuver burns, execute_node handles the progressive
    # step-down automatically.

def stop(self, state: State, commands: VesselCommands, log: ActionLogger) -> None:
    # Do NOT call restore_user_warp here. The runner does it after stop()
    # on every termination path (SUCCEEDED, FAILED, external abort).
    release_controls(commands)   # only if the action drove throttle/autopilot/SAS
    ...                          # any action-specific cleanup (remove_node_at_ut, brakes, etc.)
```

The `ActionRunner` calls `restore_user_warp(last_state, commands)` after
every `action.stop(...)` (`runner.stop()`, `runner.step()` on
`SUCCEEDED`, `runner.step()` on `FAILED`). It also reasserts it on each
action's **first tick**, before `tick()` runs, so warp recovers when the
after-`stop()` restore lands inside KSP's post-burn warp lockout (max 1x)
and is clamped. Your `tick()` may still override that same field for a
critical section (drop/step-down); last-write-wins. The helper compares
the live KSP rate against `state.user_target_warp_rate` and skips the
write when they match, so it is cheap to call unconditionally. Per-action
`stop()` bodies must not duplicate it: doing so re-introduces drift if
the contract ever changes.

Examples in tree: `align_plane`, `circularize`, `change_apse`,
`deorbit_to_target`. The latter has two critical sections (a refinement
loop plus the burn) and shows how to drop, resume from
`state.user_target_warp_rate` mid-tick (this is the one place an action
calls `restore_user_warp` itself, because it happens during `tick()`,
not on termination), drop again as the burn approaches, and let the
runner handle the final restore on `stop()`.

## Shared helpers (`helpers/`)

| Helper | Function / constant | Purpose |
|---|---|---|
| `helpers.maneuver_node` | `execute_node(state, commands, node, staging_mode, dt, log)` | Drive the vessel through a kRPC maneuver node. Calls `auto_stage` internally when `staging_mode` is not `None`. Holds the throttle at 0 until the vessel is aligned with the burn vector (within 10 deg), so it never fires while the autopilot is still slewing. Tapers throttle across the last ~8 ticks of the burn (using `dt` and the node's `burn_time_estimate`) so a high-TWR upper stage does not overshoot in the last tick. Returns `True` when the burn completes. |
| `helpers.maneuver_node` | `find_maneuver_node_by_ut(state, node_ut, tolerance=0.001)` | Return the node in `state.nodes` whose ut matches `node_ut`. Use when an action created a node via `commands.create_node` and needs to locate it again on later ticks. Returns `None` if `node_ut` is `None` or no match. |
| `helpers.maneuver_node` | `fail_if_node_has_no_thrust(state, commands, node)` | Return `ActionResult(FAILED, ...)` when the vessel cannot complete the burn. Exempts the tick that just queued a stage (`commands.stage is True`). Returns `None` to continue burning. Use immediately after `execute_node` returns `False`. |
| `helpers.maneuver_node` | `tsiolkovsky_burn_time(...)` | Estimate burn duration from current mass/Isp/thrust. Used by the bridge to populate `ManeuverNode.burn_time_estimate`. |
| `helpers.warp` | `restore_user_warp(state, commands)` | Write `commands.time_warp_rate = state.user_target_warp_rate` when the rates differ. Called by the `ActionRunner` after every `action.stop()`; actions rarely call it directly (the deorbit mid-tick refinement-resume is the one exception). |
| `helpers.warp` | `drop_warp_for_critical_section(state, commands, dropping_for)` | Drop KSP to 1x at the top of `tick()` for non-burn critical sections (PD controllers, refinement loops, position-derivative velocity estimators, orientation waits -- rails warp freezes attitude). Returns `ActionResult(RUNNING, "Dropping warp ...")` when above 1x, `None` when already at 1x. Caller returns the result and re-enters next tick. |
| `helpers.controls` | `release_controls(commands)` | Set `throttle=0`, `autopilot=False`, `sas=False`. Use in `stop()` of any action that drove the vessel's active controls during `tick()`. Other cleanup (RCS, brakes, node removal) stays per-action. |
| `helpers.staging` | `STAGING_MODE_PARAM` | Canonical `staging_mode` `ActionParam`. Add to `params` unchanged. Default is `any_flameout`; users disable it per-step with `staging_mode=off`. |
| `helpers.staging` | `parse_staging_mode(value)` | `str | None -> StagingMode | None`. Accepts a `StagingMode` value (case-insensitive), `"off"`, or empty/`None` for disabled. Use in `start()`. |
| `helpers.staging` | `auto_stage(state, commands, mode, log)` | Stage when fuel depletes or any engine flames out. Accepts `mode=None` (short-circuits). Returns `True` when it set `commands.stage = True`. Node-driven actions do **not** call this directly: `execute_node` does. |

### Auto-staging contract

`auto_stage` is safe to call unconditionally - it short-circuits when
`mode is None`. Use it like this in non-node burn actions
(`launch`, `aerobreak`, `suborbital_launch`):

```python
if auto_stage(state, commands, self._staging_mode, log):
    return ActionResult(status=ActionStatus.RUNNING, message="Staging to next stage")
```

In node-driven actions (`circularize`, `change_apse`) you do not call
`auto_stage` yourself: pass `self._staging_mode` to `execute_node` and
the helper invokes it before throttle decisions, so a spent stage drops
mid-burn and the next tick re-plans burn timing against the new
mass/thrust.

### No-thrust failure pattern

An action whose **goal requires thrust** (reach an apoapsis, brake to a
speed, complete a maneuver node) must fail rather than spin forever once
thrust is exhausted with nothing to stage into. An action whose goal is
**not thrust-bound** (diagnostic attitude tests) calls `auto_stage` for
the ignition/restage convenience but does *not* fail on thrust loss --
holding attitude with zero thrust is still a valid completion.

The exact placement differs by action shape:

**Non-node burn actions** (`launch`, `aerobreak`, `suborbital_launch`)
follow this pattern, in this order:

```python
# 1. Try auto-staging first.
if auto_stage(state, commands, self._staging_mode, log):
    return ActionResult(status=ActionStatus.RUNNING, message="Staging to next stage")

# 2. If there is still no thrust, the action cannot proceed.
if state.thrust_available <= 0.0:
    return ActionResult(status=ActionStatus.FAILED, message="No thrust available")

# 3. Otherwise drive normal flight logic ...
```

Put this block as the first effective check in `tick()` after any
deferred-fail guard.

**Node-driven actions** (`circularize`, `change_apse`, `align_plane`,
`deorbit_to_target`) call `fail_if_node_has_no_thrust` right after
`execute_node` returns `False`. The helper exempts the tick on which
auto-staging just queued a stage (state was read before this tick's
commands apply, so a flameout shows `thrust_available == 0` even though
the next tick will ignite the new stage). Failing in that case would
kill the burn one tick before the new engine gets a chance.

```python
if execute_node(state, commands, node, self._staging_mode, dt, log):
    # ... burn complete, return SUCCEEDED
no_thrust = fail_if_node_has_no_thrust(state, commands, node)
if no_thrust is not None:
    return no_thrust
# ... return RUNNING
```

**Diagnostic / non-burn actions** (`hold_attitude`, `controllability_test`)
call `auto_stage` for first-tick ignition and mid-test restages, but
have no thrust check -- the action's goal is orientation control, not a
delta-v target:

```python
auto_stage(state, commands, self._staging_mode, log)
# ... drive autopilot, throttle, etc. ...
```

## Tests

Every action gets a `tests/test_<action_id>_action.py`. Beyond what ADR 0009
prescribes, cover at least:

- **`tick` helper integration:** for actions using `auto_stage` or
  `execute_node`, exercise both code paths (helper fires vs doesn't).
- **`stop`:** clears every command field the action's `tick()` touched.

Use `State` / `VesselCommands` dataclasses directly; never mock them. For
per-part counts, build a real `Parts(engines=(PartInfo(...),))`.

## Registering a new action

1. Create `actions/<action_id>/action.py` following this guide and ADR 0009.
2. The registry picks up any `Action` subclass automatically.
3. If the action uses a kRPC capability not yet bridged, extend
   `krpc_bridge` first (read/write + filter) following ADR 0006/0008.
4. Add `tests/test_<action_id>_action.py`.
5. Optionally add a `.plan` file under `plans/`.

## Anti-patterns to avoid

- **`__init__` override.** Use `start()` instead.
- **kRPC imports or calls inside an action.** Actions are pure functions of
  `State -> VesselCommands` (ADR 0006).
- **Magic numbers in `tick()`.** Move to module-level `_CONSTANTS`.
- **Multiple Action subclasses in one file.** Each gets its own folder.
- **Section banners inside lifecycle methods.** Extract a helper, or use a
  plain `# N. step` comment for long control loops.
- **Catch-all `try/except`.** Let the runner surface unexpected exceptions.
- **Mutating `state`.** `State` is frozen for a reason.
- **Re-implementing logic that is in `helpers/`.** Call the helper.
