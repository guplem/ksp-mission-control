# ADR 0006: Tick-based Action Execution System

## Context

The control screen needs to support automated vessel actions (hover, ascend to orbit, wait-until conditions, etc.). Each action follows a loop: read vessel state, decide what controls to set, repeat. Actions must be testable without a running KSP instance and work identically in demo mode.

The system is designed to grow in phases:
1. Single action execution with hardcoded parameters (current)
2. Parameter input dialog before running an action
3. Text-based flight plan format (sequential action lists)
4. Create Wait-until condition actions (e.g. wait until time-to-apoapsis < 30s) - Just a simple action that won't stop until the condition is met, then returns SUCCEEDED.
5. Full compound flight plans (orbit-and-back)

## Decision

Implement a tick-based action system where actions are pure functions of `VesselState -> VesselControls`, never touching kRPC directly. Inspired by Unity's Update loop pattern.

Core components:

- **`VesselState`**: frozen dataclass snapshot of vessel telemetry (altitude, speed, orbit, resources). Pure Python, no kRPC or Textual imports.
- **`VesselControls`**: mutable command buffer (throttle, pitch, SAS, etc.). Fields default to `None` meaning "don't change this tick." Actions mutate it; the runner applies non-None fields to kRPC.
- **`Action` ABC**: declares typed parameters (`ActionParam`), implements `start()` / `tick()` / `stop()` lifecycle. Each action has `ClassVar` metadata (action_id, label, description, params).
- **`ActionRunner`**: manages the active action. Exposes `step(vessel_state, dt) -> VesselControls` called from the control screen's existing poll loop. Does not own a thread.
- **`ActionListWidget`**: ListView-based UI in the control screen's right pane showing available actions and running status.

Action lifecycle: `start(params)` called once, then `tick(state, controls, dt)` called every 0.5s, returning `ActionResult(status, message)`. When status is SUCCEEDED or FAILED, `stop(controls)` is called automatically. User can abort at any time.

Data flow:

```
kRPC --read--> VesselState --> runner.step() --> VesselControls --write--> kRPC
```

In demo mode, `VesselState` comes from the demo provider and returned controls are discarded.

## Consequences

- **Positive**: Actions are pure and fully testable. Construct a `VesselState`, call `tick()`, assert on `VesselControls`.
- **Positive**: Demo mode works identically to live mode (same runner, same actions).
- **Positive**: Adding new actions requires only a new `Action` subclass and a registry entry.
- **Positive**: Future flight plans can sequence actions by driving the runner without changing the action or runner code.
- **Positive**: The `ActionParam` descriptor pattern enables future UI-driven parameter dialogs.
- **Negative**: `VesselState` must be kept in sync with what kRPC actually provides.
- **Negative**: The command buffer pattern adds indirection between action intent and kRPC calls.
