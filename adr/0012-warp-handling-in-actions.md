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

The first implementation of this was a unilateral drop inside `execute_node`: when the burn was about to start, set `commands.time_warp_rate = 1.0`. That works for the burn, but it is one-way -- warp stays at 1x after the action ends, so every flight plan grew a `time_warp target_multiplier=100` line after every maneuver to undo it. Plans became long and hard to read, and the asymmetry leaked into the user's mental model.

## Decision

Actions that have a critical section requiring 1x **capture the user's warp rate before that critical section, drop to 1x for the duration, and restore the captured rate on completion**. The capture is best-effort: it is the highest warp rate the action observed across its ticks.

### The contract

Every action that performs a maneuver burn, runs an iterative replanning loop, or runs a tick-to-tick feedback controller (PD throttle, position-derivative velocity estimator, etc.):

1. In `start()`, set `self._initial_warp_rate: float = state.time_warp_rate`.
2. In `tick()`, update `self._initial_warp_rate = max(self._initial_warp_rate, state.time_warp_rate)` at the top of the body, before any other state-dependent logic. Max-tracking handles the same-tick race where the preceding plan step's `time_warp` command has been written to the buffer but not yet applied to kRPC.
3. At the start of each critical section, write `commands.time_warp_rate = 1.0`. Where this lives depends on the action shape:
   - **Burn-driven actions** delegate to `execute_node`. The helper drops warp once the burn is within a real-time buffer (5 seconds, scaled by current warp rate) and restores `restore_warp_rate` on every burn-complete return path. Pass `restore_warp_rate=self._initial_warp_rate` so the helper handles success cleanup symmetrically.
   - **Other critical sections** (e.g. `deorbit_to_target`'s iterative refinement loop, or atmospheric controllers in `land` / `hover` / `translate` / `aerobreak`) drop warp directly in `tick()` and return `RUNNING` with a message. Subsequent ticks see `state.time_warp_rate` at 1x and the critical code runs.
4. In `stop()`, if `self._initial_warp_rate > 1.0`, write `commands.time_warp_rate = self._initial_warp_rate`. The runner calls `stop()` on every termination path (`SUCCEEDED`, `FAILED`, user abort). Even though `execute_node` already restored on successful burn-complete returns, this `stop()` write covers abort and failure paths that bypass that helper return.

The "drop and restore go as close to the critical code as possible" principle means the drop is local to the loop that needs 1x, not at the action's entry point. For burn actions that boils down to `execute_node`. For atmospheric controllers it boils down to the first thing `tick()` does. The action-level `stop()` restore is a safety net, not the primary restore path.

### Why max-tracking

`start()` runs in the same poll cycle where the preceding plan step's commands are still in transit -- they have been written to the buffer but not yet applied to kRPC. A flight plan like

```
time_warp    target_multiplier=100
align_plane  target_latitude=-5.0
```

starts `align_plane` while `state.time_warp_rate` still reads 1x. KSP ramps up over the next several poll cycles. Max-tracking in `tick()` lets the action observe the user's actual target rate as soon as KSP catches up, and never lowers the captured value when `execute_node` later drops warp for the burn.

### Why restore lives in `stop()`

`runner.step()` calls `action.stop()` on every terminal path: `SUCCEEDED`, `FAILED`, and external abort. `stop()` shares the same `VesselCommands` buffer that the final `tick()` wrote to, so whatever `stop()` writes is what the bridge sends. Putting the restore in `stop()` covers all three paths in one place; the action does not need separate restoration branches in its success and failure code.

### Two critical sections in one action

`deorbit_to_target` has two distinct critical sections: the iterative refinement loop (before the burn) and the burn itself. Between them is a cold coast that can run at any warp.

The action handles this with:

- Drop warp to 1x while refining.
- Restore warp to `self._initial_warp_rate` once converged (only once, guarded by a `_refinement_warp_resumed` flag so subsequent ticks do not re-issue the command).
- Let `execute_node` drop warp again as the burn approaches.
- Restore in `stop()`.

Other actions with multiple critical sections follow the same pattern: explicit drop at the start of each, explicit resume between them, and a single restore in `stop()` as the final safety net.

### What plans look like

Authors set warp once and let each maneuver action manage itself:

```
time_warp    target_multiplier=100
align_plane  target_latitude=-5.0
deorbit_to_target target_latitude=-5.0 target_longitude=-110.0 drag_bias_km=60
time_warp    target_multiplier=1
```

The `time_warp 1x` line at the end is for the plan's *next* phase (reentry), not for resetting warp after the maneuvers. Each maneuver drops and restores 100x internally.

### What plans should not do

**Do not manually drop warp before an auto-managed maneuver.** A pattern like

```
time_warp    target_multiplier=100
wait_for     time_before_apoapsis=60
time_warp    target_multiplier=1
circularize  apse=periapsis
```

forces `circularize` to capture 1x as its initial rate (max-tracking only rises) and restore 1x on completion. The high warp the user wanted for the *next* step is lost. Drop `time_warp 1x` from this pattern; let `circularize` handle its own warp drop near the burn.

The exception is when the plan genuinely wants warp at 1x for a non-maneuver step that follows (a `wait_for time=10` that is supposed to be ten real seconds, for instance). In that case the explicit `time_warp 1x` is correct and the next maneuver action will capture 1x; this is intentional and the plan stays explicit about what warp it expects.

## Consequences

- `time_warp` is the single user-facing knob for warp; everything else flows from the captured rate.
- Plans are roughly half as long around the orbital sections, and the bookkeeping around each maneuver disappears.
- A maneuver action that is aborted mid-coast also restores warp, because `stop()` runs on abort.
- The capture is fragile when the user explicitly drops warp immediately before a maneuver -- max-tracking will pick up the pre-drop value and restore that on completion. The pattern documents this so plan authors can avoid it.
- The `_WARP_DROP_REAL_SECONDS_BEFORE_BURN` constant in `helpers/maneuver_node.py` is the single tuning knob for how much real-time margin KSP gets to spin warp down before the burn starts. Raise it if observed burns start while warp is still spinning down; lower it if too much warp is wasted on the buffer.
