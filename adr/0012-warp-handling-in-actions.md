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
2. At the start of each critical section, write `commands.time_warp_rate = 1.0` (or call `execute_node`, which does it progressively for burns).
3. In `stop()`, if `state.user_target_warp_rate > 1.0`, write `commands.time_warp_rate = state.user_target_warp_rate`. The runner calls `stop()` on every termination path (`SUCCEEDED`, `FAILED`, user abort).

`execute_node` reads `state.user_target_warp_rate` directly on every burn-complete return path: no `restore_warp_rate` parameter, no caller-supplied value. The two restores (helper on success, action's `stop()` on every path) write the same value, so success simply restores twice into the same `commands` buffer.

### Two flavours of drop

- **Burn-driven actions** delegate to `execute_node`. The helper steps the warp rate down one rails-warp level per tick (e.g. `1000x -> 100x -> 50x -> 10x -> 5x -> 1x`) once the burn is close enough that one tick at the current rate could put the next check past the burn. The threshold is `dt * current_rate * 2.0 + 5.0` game seconds: scaled to the current rate so high warp gets enough lead time, but progressive so we never drop to 1x while the burn is still hundreds of game seconds away.
- **Other critical sections** (e.g. `deorbit_to_target`'s iterative refinement loop, or atmospheric controllers in `land` / `hover` / `translate` / `aerobreak`) snap-drop warp directly in `tick()` and return `RUNNING` with a message. Subsequent ticks see `state.time_warp_rate` at 1x and the critical code runs.

### Two critical sections in one action

`deorbit_to_target` has two distinct critical sections: the iterative refinement loop (before the burn) and the burn itself. Between them is a cold coast that can run at any warp.

The action handles this with:

- Snap-drop warp to 1x while refining.
- Resume warp to `state.user_target_warp_rate` once converged (only once, guarded by a `_refinement_warp_resumed` flag so subsequent ticks do not re-issue the command).
- Let `execute_node` step warp down again as the burn approaches.
- Restore in `stop()`.

### What plans look like

Authors set warp once and let each maneuver action manage itself:

```
time_warp    target_multiplier=100
align_plane  target_latitude=-5.0
deorbit_to_target target_latitude=-5.0 target_longitude=-110.0 drag_bias_km=60
time_warp    target_multiplier=1
```

The `time_warp 1x` line at the end is for the plan's *next* phase (reentry). Each maneuver drops and restores 100x internally by reading from the session value `time_warp` already updated.

Hedging warp re-arms after each maneuver (`# Kerbal might have stopped the time warp`) is no longer needed. KSP refusing the warp does not affect the session value, so the next maneuver still sees `state.user_target_warp_rate = 100` and will keep trying to use that warp once altitude allows.

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
- An aborted maneuver restores warp, because `stop()` runs on abort and reads the live state.
- Actions no longer carry `self._initial_warp_rate`; their `start()` and `tick()` lose the warp bookkeeping entirely. Reduces per-action surface area.
- Two tuning knobs in `helpers/maneuver_node.py` shape the step-down threshold: `_WARP_STEP_DOWN_TICK_MARGIN` (per-tick multiplier, default 2.0) and `_WARP_STEP_DOWN_GAME_SECONDS_SAFETY` (fixed slack, default 5.0). Raise the margin if observed burns start while warp is still stepping down; raise the safety if the burn ever fires on the same tick the last step lands. Both are conservative defaults; lower only with log evidence.
