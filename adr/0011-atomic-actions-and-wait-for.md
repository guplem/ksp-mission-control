# ADR 0011: Atomic Actions and `wait_for` for Preconditions

## Related

- [ADR 0006](0006-action-execution-system.md) - action execution architecture.
- [ADR 0009](0009-action-lifecycle-contract.md) - lifecycle contract for `start`/`tick`/`stop`.
- [`src/ksp_mission_control/control/actions/CLAUDE.md`](../src/ksp_mission_control/control/actions/CLAUDE.md) - file-structure and helpers guide for action authors.

## Context

As actions accumulated, several of them grew parameters that were really just preconditions: gates that block the action from doing its real work until some condition on `State` is met. Examples that existed in the codebase:

- `parachutes.min_altitude` -- "wait until altitude is below X, then deploy".
- `stage.wait_for_no_thrust` -- "wait until thrust is zero, then stage".
- Half-implemented horizontal-travel and "land at end" params on `hover` that were stored but never read.

These conflate two concerns: *the work the action performs* and *when it is allowed to start*. Once that mixing is permitted, it scales badly. Every new action grows a copy of "min altitude", "wait until apoapsis", "wait for biome", and so on, each implemented slightly differently, each requiring its own UI form and tests. The `wait_for` action already exists as the single, composable place for those gates -- but only if every other action stays atomic.

## Decision

Each action does exactly one thing. Preconditions live in a separate `wait_for` step in the flight plan, not as parameters on the action that follows.

### What belongs on an action

A parameter is intrinsic to an action when removing it would make the action incomplete or ambiguous. In practice this means:

1. **Targets / setpoints**: the value the action drives toward. `land.target_speed`, `launch.target_altitude`, `hover.target_altitude`, `translate.distance_north`, `autopilot.pitch`.
2. **Tuning constants**: numbers that shape how the action operates. `aerobreak.max_dynamic_pressure`, `controllability_test.tolerance`, `suborbital_launch.min_throttle`.
3. **Selection filters**: which subjects the action operates on. `science.name`, `science.has-data`, `science.count`.
4. **Completion criteria intrinsic to the action's purpose**: `hover.hover_duration`, `hold_attitude.hold_ticks`, `controllability_test.hold_duration`. These are not preconditions; they describe how long the action runs.
5. **Continuous fault-recovery toggles**: behavior the action evaluates every tick during execution, not once at start. `launch.auto_stage`, `aerobreak.auto_stage`, `suborbital_launch.auto_stage`. These cannot be expressed as a single `wait_for` step because they react to conditions throughout the action's lifetime.

### What does not belong on an action

A parameter is a precondition (and therefore belongs in `wait_for`, not on the action) when it satisfies all of these:

1. It is checked once, at start, against `State`.
2. The action does nothing observable while the condition is unmet.
3. The condition can be expressed as a comparison against a `State` field already exposed (or trivially exposable) on `wait_for`.

When all three hold, the parameter must not exist on the action. Users compose:

```
wait_for  below_altitude=1000
parachutes
```

instead of:

```
parachutes  min_altitude=1000
```

The composed form is longer by one line but the semantics are explicit, the gating logic lives in one place, and `wait_for` already supports combining several conditions in one step.

### Edge cases that are allowed to stay on the action

A precondition can stay on the action when it depends on per-part state that `wait_for` does not see. The current example is `parachutes.wait_for_safe`, which checks each parachute's `safe_to_deploy` flag. The check must be re-evaluated at the moment of deployment (the safety window can close again), so a one-shot gate before the action would be unsafe. This is the exception, not the template; prefer extending `wait_for` over adding a new in-action gate.

A side effect that an action performs to *make its own work possible* can also stay. `parachutes.stage_for_parachutes` stages until parachutes are reachable; the user does not necessarily know how many stages to skip, so splitting it out would push that knowledge into the plan. This is action-internal logic, not a precondition.

### Migration

The cleanup that motivated this ADR removed:

- `parachutes.min_altitude` -- replaced by `wait_for below_altitude=...`.
- `stage.wait_for_no_thrust` -- replaced by `wait_for below_current_thrust=0`.
- `hover.horizontal_control` -- dead (stored, never read). Use `translate` instead.
- `hover.land_at_end` -- dead (stored, never read). Chain `land` after `hover` in the plan.

## Consequences

- **Positive**: Action surfaces shrink. Reading an action tells you exactly what it does, with no hidden gates.
- **Positive**: Gating logic is implemented and tested once, in `wait_for`. Adding a new condition (e.g. "wait until biome changes") makes it available to every action automatically.
- **Positive**: Plan files are more explicit. The reader sees `wait_for ... ; parachutes` and knows what is happening without reading the action's source.
- **Positive**: Removes the temptation to copy-paste min/max gates between actions, each with slightly different naming or behavior.
- **Negative**: Plans become slightly more verbose. A single action call can become two lines.
- **Negative**: Users coming from the old parameters must learn the new pattern. Mitigated by removing the old params outright rather than keeping them as deprecated aliases.
- **Negative**: `wait_for` becomes the central place where new gating conditions are added, so its parameter list will keep growing. This is the correct place for that growth.
