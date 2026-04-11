# ADR 0006: Tick-based Action Execution System

## Context

The control screen needs to support automated vessel actions (hover, ascend to orbit, wait-until conditions, etc.). Each action follows a loop: read vessel state, decide what controls to set, repeat. Actions must be testable without a running KSP instance and work identically in demo mode.

## Decision

Implement a tick-based action system where actions are pure functions of `VesselState → VesselControls`, never touching kRPC directly.

Core components:

- **`VesselState`**: frozen dataclass snapshot of vessel telemetry (altitude, speed, orbit, resources). Pure Python — no kRPC or Textual imports.
- **`VesselControls`**: mutable command buffer (throttle, pitch, SAS, etc.). Fields default to `None` meaning "don't change this tick." Actions mutate it; the runner applies non-None fields to kRPC.
- **`Action` ABC**: declares typed parameters (`ActionParam`), implements `start()` / `tick()` / `stop()` lifecycle.
- **`ActionRunner`**: manages the active action. Exposes `step(vessel_state, dt) → VesselControls` called from the control screen's existing poll loop. Does not own a thread.

Data flow:

```
kRPC ──read──▶ VesselState ──▶ runner.step() ──▶ VesselControls ──write──▶ kRPC
```

In demo mode, `VesselState` comes from the demo provider and returned controls are discarded.

## Consequences

- **Positive**: Actions are pure and fully testable — construct a `VesselState`, call `tick()`, assert on `VesselControls`
- **Positive**: Demo mode works identically to live mode (same runner, same actions)
- **Positive**: Adding new actions requires only a new `Action` subclass and a registry entry
- **Positive**: Future flight plans can sequence actions without changing the runner
- **Negative**: `VesselState` must be kept in sync with what kRPC actually provides
- **Negative**: The command buffer pattern adds indirection between action intent and kRPC calls
