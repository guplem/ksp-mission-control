# ADR 0009: Action Lifecycle Contract

## Context

As the number of actions grows, inconsistencies have appeared in how actions handle parameter storage, type conversion, validation, error reporting, and cleanup. Some actions use `param_values.get()` with inline defaults, others use bracket access; some validate enums, others don't; some re-validate params in `tick()`, others trust `start()`. This makes actions harder to review, debug, and extend.

A standard lifecycle contract ensures every action follows the same patterns, making behavior predictable and reducing bugs from inconsistent validation or missing type conversions.

## Decision

Define a strict contract for the three Action lifecycle methods: `start()`, `tick()`, and `stop()`. All actions must follow this contract.

### `start(state, param_values)` -- Initialize and Validate

**Purpose**: Store parameter values, convert types, validate correctness, and snapshot initial state. After `start()` returns, the action is fully configured and ready to tick.

**Rules**:

1. **Bracket access only**: Use `param_values["key"]`, never `.get()`. The runner's `_resolve_params()` guarantees every declared param key exists in the dict (fills defaults for optional params, raises for missing required params). Using `.get()` with a fallback silently masks bugs where a param is missing from the declaration.

2. **Explicit type conversion**: Always convert values to their target type: `float()`, `int()`, `bool()`. Even if the value is already the correct type, the conversion serves as documentation and catches unexpected types early. For nullable params, convert only when not None:
   ```python
   raw = param_values["target_altitude"]
   self._target_altitude: float | None = float(raw) if raw is not None else None
   ```

3. **Validate values**: Check that values are within acceptable ranges and that enum values are valid members. Raise `ValueError` with a descriptive message listing valid options:
   ```python
   try:
       self._mode = SASMode(param_values["mode"])
   except ValueError:
       valid = ", ".join(m.value for m in SASMode)
       raise ValueError(f"Unknown SAS mode '{param_values['mode']}'. Valid: {valid}") from None
   ```

4. **Check cross-param compatibility**: If params are mutually exclusive or interdependent, validate that here. Example: throttle_level and twr cannot both be set.

5. **Raise `ValueError`**: All validation failures raise `ValueError` with a message that helps the user fix the input. Never silently ignore invalid values.

6. **Private attributes**: Store all params as private instance attributes (`self._name`). Public attributes are reserved for ClassVar metadata.

7. **Snapshot initial state**: If the action needs reference points (initial altitude, orientation, position), capture them at the end of `start()` after all params are validated.

### `tick(state, commands, dt, log)` -- Assume Valid, Act

**Purpose**: Read current vessel state, decide what commands to issue, and report progress. This is the action's main loop body.

**Rules**:

1. **Trust `start()`**: All params were validated in `start()`. Never re-check param validity in `tick()`. If `start()` accepted the values, they are correct for the lifetime of the action.

2. **Return FAILED only for unrecoverable runtime conditions**: Things that make the action's goal impossible and that could not have been validated at start time. Examples:
   - No parachutes found on the vessel (parts were destroyed)
   - Already at stage 0 (cannot stage further)
   - No thrust available when thrust is required (engines destroyed or out of fuel)

   These are vessel-state problems, not param-validation problems.

3. **Return RUNNING** while making progress toward the goal.

4. **Return SUCCEEDED** when the goal is achieved.

5. **Log appropriately**: Use `log.debug()` for per-tick telemetry, `log.info()` for milestones (reached altitude, deployed gear), `log.warn()` for concerning deviations, `log.error()` for conditions that may lead to failure.

### `stop(state, commands, log)` -- Cleanup Only

**Purpose**: Return the vessel to a safe idle state. Called automatically when the action finishes (succeeded or failed) or is aborted by the user.

**Rules**:

1. **Call `super().stop()` first**: The base implementation logs a stop message.

2. **Set cleanup commands only**: Zero throttle, disengage autopilot, engage brakes, disable RCS, zero translation axes. Only set commands that undo what the action's `tick()` was actively controlling.

3. **Most actions need no cleanup**: If the action is one-shot (stage, set SAS mode, set throttle, run science), `stop()` should just call `super().stop()` and return. Only continuous actions that leave the vessel in an active state (engines running, autopilot engaged, RCS translating) need explicit cleanup.

4. **No business logic**: No conditional checks, no state inspection beyond what's needed to decide cleanup. `stop()` is not a second `tick()`.

## Consequences

- **Positive**: All actions follow a single, predictable pattern. Reading one action teaches you how all actions work.
- **Positive**: Bugs from missing type conversions or inconsistent validation are eliminated.
- **Positive**: `tick()` is simpler because it doesn't need defensive param checks.
- **Positive**: New action authors have a clear contract to follow.
- **Negative**: Existing actions need a one-time cleanup pass to conform.
- **Negative**: Some validation that was "close to the usage" in `tick()` moves to `start()`, which is further from where the value is used. The trade-off is worth it for consistency and fail-fast behavior.
