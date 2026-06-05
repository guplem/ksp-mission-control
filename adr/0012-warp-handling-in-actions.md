# ADR 0012: Warp Handling in Actions

## Related

- [ADR 0006](0006-action-execution-system.md) - action execution architecture.
- [ADR 0009](0009-action-lifecycle-contract.md) - lifecycle contract for `start`/`tick`/`stop`.
- [`src/ksp_mission_control/control/actions/CLAUDE.md`](../src/ksp_mission_control/control/actions/CLAUDE.md) - file-structure and helpers guide for action authors.

## Context

The `time_warp` action lets a flight plan request a KSP simulation-speed multiplier (1, 2, 3, 4 for physics warp; 1, 5, 10, 50, 100, 1000, 10000, 100000 for rails warp). High warp is essential for long orbital coasts -- a Hohmann transfer takes 20+ minutes of game time, and watching that pass at 1x is unworkable.

But warp is incompatible with two things actions need to do:

1. **Burning a maneuver node.** KSP's physics is unstable above 4x physics warp; rails warp pauses physics simulation entirely. A throttle command issued under rails warp has no effect, and even at modest physics warp the autopilot cannot settle on a target direction. The burn must happen at 1x.
2. **Iterative refinement.** `deorbit_to_target` replans its node each tick based on the bridge's predicted impact. At 100x, one poll covers 50 seconds of game time, and the loop's burn UT shifts faster than the refinement can converge. Any action whose tick-to-tick reasoning depends on state being approximately the same at the next tick needs 1x.

### Earlier approach (deprecated)

The first version of this captured `state.time_warp_rate` in `start()`, used `max(self._initial_warp_rate, state.time_warp_rate)` tracking in `tick()` to catch up after same-tick races, and restored the captured value in `stop()`. That worked for the happy path, but it had a subtle failure mode: the capture was only as good as `State.time_warp_rate`, which reports KSP's *achieved* rate, not the user's *intended* rate. When KSP refused a rate (altitude cap kicks in, vessel still rotating from autopilot-disengage, low-altitude orbits clamp to 50x even when the plan asked for 100x), the captured value stuck at 1x and the next action restored 1x. The bug showed up in the wild as `align_plane` running its whole coast at 1x because the preceding `circularize.stop()`'s 100x restore was silently dropped by KSP.

## Decision

Move the source of truth for "what warp does the user want" out of per-action captures into a single session-level value, surfaced to actions as `State.user_target_warp_rate`. Actions never capture; they always read.

### The contract

`ControlSession._user_target_warp_rate` is the single source of truth, defaulting to `1.0`. It is mutated by exactly two things:

- The **warp controller widget** on the control screen (the user clicking a rails-warp level).
- The **`time_warp` action** when it runs in a plan, by writing `commands.user_target_warp_rate` alongside `commands.time_warp_rate`. The session reads and clears this field in `_poll_tick`, never sending it to kRPC.

Every poll tick the session uses `dataclasses.replace` to inject its value into `State.user_target_warp_rate` before handing State to the executor. Actions read that field whenever they need to know what to restore to.

Every action that performs a maneuver burn, runs an iterative replanning loop, or runs a tick-to-tick feedback controller (PD throttle, position-derivative velocity estimator, etc.):

1. **No capture in `start()`.** Do not store `state.time_warp_rate` anywhere. No `self._initial_warp_rate` attribute, no max-tracking in `tick()`.
2. At the start of each critical section, call `drop_warp_for_critical_section(state, commands, "<dropping_for>")` from `helpers/warp.py` and return its result if non-`None`. The helper writes `commands.time_warp_rate = 1.0` and returns `ActionResult(RUNNING, ...)`; the action's caller-facing message names the section it is about to run. For maneuver burns, `execute_node` steps warp down progressively across multiple ticks instead.
3. **Do not call `restore_user_warp` in `stop()`.** The `ActionRunner` calls `restore_user_warp(last_state, commands)` automatically after every `action.stop()` (external stop, `SUCCEEDED`, and `FAILED` paths). Per-action stop bodies only need to release controls and any other action-specific cleanup (e.g. `commands.remove_node_at_ut = self._node_ut` for node-driven actions, `release_controls(commands)` from `helpers/controls.py` for the common throttle/autopilot/SAS reset).

The helper writes `commands.time_warp_rate = state.user_target_warp_rate` if (and only if) the live KSP rate differs from the user's target. Centralizing the condition in `restore_user_warp` covers both directions: a critical section dropped KSP below the user's target (write up), or the user dropped their intent to 1x while KSP was still high (write down). Equality skips the write so a stable tick produces no redundant command.

`execute_node` does not call `restore_user_warp` on its burn-complete return paths either. The runner's call after the action returns `SUCCEEDED` (and `stop()` runs) covers it in the same poll tick.

### Reasserting at action start

The runner also reasserts the user's target on the **first tick of every action**, calling `restore_user_warp(state, commands)` before `action.tick()` runs. This closes a timing gap in the after-`stop()` restore: that restore fires on the exact tick an action ends, and for a burn action that is the burn-completion tick -- the moment KSP's post-burn warp lockout is most likely still active (`State.time_warp_rate_max == 1`). KSP silently clamps the restored rate to 1x, and with no retry the warp stayed at 1x for the entire following coast. (This is the same "KSP refused the rate" failure as the deprecated capture approach above, just triggered by *when* the single restore fires rather than *what value* it carries.) Reasserting on the next action's first tick lands one poll later, after the lockout lifts, so the warp recovers.

The action's own `tick()` runs immediately after and may overwrite `commands.time_warp_rate`: a burn action's `execute_node` steps it down as the burn nears, and a 1x-critical section's `drop_warp_for_critical_section` drops it. Last-write-wins within the tick, so reasserting at start never fights an action that needs a lower rate -- it only re-applies the user's intent for actions (coasts, waits) that do not touch warp.

That last-write-wins reasoning holds **within a single track**, where the action's own `tick()` is the last writer of its warp. Across **parallel tracks** it does not: each track produces commands independently, and `MultiTrackExecutor._merge_commands` combines them. A sibling track that reasserts the user's cruise warp on its first tick can merge *after* a burn track that just dropped to 1x, overriding it and sending the burn back to high warp. To close this, the cross-track merge resolves `time_warp_rate` by **minimum, not last-write-wins**: the slowest requested rate wins, so any track in a critical section keeps the shared warp low regardless of merge order.

### Two flavours of drop

- **Burn-driven actions** delegate to `execute_node`. The helper steps the warp rate down one rails-warp level per tick (e.g. `1000x -> 100x -> 50x -> 10x -> 5x -> 1x`) once the burn is close enough that one tick at the current rate could put the next check past the burn. The threshold is `dt * current_rate * 2.0 + 5.0` game seconds: scaled to the current rate so high warp gets enough lead time, but progressive so we never drop to 1x while the burn is still hundreds of game seconds away.
- **Other critical sections** (e.g. `deorbit_to_target`'s iterative refinement loop, or atmospheric controllers in `land` / `hover` / `translate` / `aerobreak`) call `drop_warp_for_critical_section` directly in `tick()` and return its `RUNNING` result. Subsequent ticks see `state.time_warp_rate` at 1x and the critical code runs. `wait_for` does the same while waiting for an `orientation`: rails warp freezes vessel attitude, so an orientation wait under warp would never complete (and the start-of-action reassert above would otherwise leave it spinning under warp). Only `orientation` drops warp -- positional and time conditions advance under warp, so those waits keep warping.

### Two critical sections in one action

`deorbit_to_target` has two distinct critical sections: the iterative refinement loop (before the burn) and the burn itself. Between them is a cold coast that can run at any warp.

The action handles this with:

- `drop_warp_for_critical_section` while refining.
- Resume warp to `state.user_target_warp_rate` once converged (only once, guarded by a `_refinement_warp_resumed` flag so subsequent ticks do not re-issue the command). This is a *mid-tick* `restore_user_warp` call from inside `tick()`, not a `stop()` call.
- Let `execute_node` step warp down again as the burn approaches.
- The runner restores warp after `stop()` on every termination path.

### What plans look like

Authors set warp once and let each maneuver action manage itself:

```
time_warp    target_multiplier=100
align_plane  target_latitude=-5.0
deorbit_to_target target_latitude=-5.0 target_longitude=-110.0 drag_bias_km=60
time_warp    target_multiplier=1
```

The `time_warp 1x` line at the end is for the plan's *next* phase (reentry). Each maneuver drops and restores 100x internally by reading from the session value `time_warp` already updated.

Hedging warp re-arms after each maneuver (`# Kerbal might have stopped the time warp`) is no longer needed. KSP refusing the warp does not affect the session value, so the next maneuver still sees `state.user_target_warp_rate = 100` and will keep trying to use that warp once altitude allows. Because the runner reasserts the target on each action's first tick, a coast or wait that follows a maneuver picks the warp back up automatically. A bare `time_warp` step (no `target_multiplier`) remains available to re-send the rate mid-action if KSP dropped it during a single long-running action.

### What plans should not do

**Do not manually drop warp before an auto-managed maneuver** unless the plan really wants 1x for the *next* non-maneuver step. A pattern like

```
time_warp    target_multiplier=1
circularize  apse=periapsis
```

will explicitly set the session's user target to 1x, so `circularize` will not restore high warp on completion. Use `time_warp 1x` only when you genuinely want 1x to persist.

## Consequences

- `time_warp` and the warp controller widget are the only ways to change the user's target rate; everything else flows from `State.user_target_warp_rate`.
- Plans are shorter and survive KSP refusing a warp set (altitude caps, vessel-not-settled rejection): the next action still reads the user's intent.
- An aborted maneuver restores warp, because the runner calls `restore_user_warp` after `stop()` on every termination path.
- The runner reasserts the user's target on each action's *first tick* as well as after `stop()`. This closes the gap where the after-`stop()` restore landed on a burn-completion tick inside KSP's warp lockout (`time_warp_rate_max == 1`) and was silently clamped, stranding the following coast at 1x. `wait_for` correspondingly drops warp while waiting for an `orientation`, since the reassert would otherwise leave it spinning under rails warp.
- Actions no longer carry `self._initial_warp_rate`; their `start()` and `tick()` lose the warp bookkeeping entirely. Per-action `stop()` bodies no longer call `restore_user_warp` either. Reduces per-action surface area.
- Two tuning knobs in `helpers/maneuver_node.py` shape the step-down threshold: `_WARP_STEP_DOWN_TICK_MARGIN` (per-tick multiplier, default 2.0) and `_WARP_STEP_DOWN_GAME_SECONDS_SAFETY` (fixed slack, default 5.0). Raise the margin if observed burns start while warp is still stepping down; raise the safety if the burn ever fires on the same tick the last step lands. Both are conservative defaults; lower only with log evidence.
- Across parallel tracks, `time_warp_rate` merges by **minimum**, not last-write-wins (`_merge_commands` in `multi_track_executor.py`). The first-tick reassert is safe within one track, where the action's own `tick()` writes last; across tracks a sibling's reassert could merge after a burn track's drop and speed the burn back up. Minimum-wins lets any track in a critical section keep the shared warp low. The failure it fixes: a science track firing back-to-back experiments alongside a `circularize` burn pinned warp at 100x through apoapsis, so the burn (deferred until warp finally fell at apoapsis) ran entirely on the descending arc and left an eccentric orbit instead of a circular one.
