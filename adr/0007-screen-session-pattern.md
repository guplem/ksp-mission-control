# ADR 0007: Screen + Session/Runner Separation of Concerns

## Context

Textual screens were accumulating multiple responsibilities: UI composition, event handling, business logic (poll loops, check sequencing), connection lifecycle management, and state ownership. This made the core logic untestable without spinning up a full Textual test harness, and made screens harder to understand as they grew.

Two screens were affected:
- `ControlScreen` (~148 lines) owned the kRPC connection, `ActionRunner`, `threading.Event`, the poll loop, and shutdown/abort logic.
- `SetupScreen` (~178 lines) owned the check list, results dict, sequential execution with short-circuit, and display update logic.

The sub-feature screens (`KrpcCommsScreen`, `VesselScreen`, `KrpcSetupScreen`) were already thin, delegating to existing logic classes (`check.run()`, `locator.py`, `installer.py`).

## Decision

Extract business logic from screens into dedicated classes that communicate via typed callbacks. Screens become thin UI glue.

**`ControlSession`** (`control/session.py`) owns:
- The kRPC connection
- The `ActionRunner` instance
- The `threading.Event` for shutdown
- The blocking poll loop (`run_poll_loop()`)
- Action start/abort/shutdown lifecycle

It takes `on_update(VesselState, RunnerSnapshot)` and `on_error(str)` callbacks in its constructor. It has no Textual imports.

**`CheckRunner`** (`setup/check_runner.py`) owns:
- The check list and results dict
- Sequential execution with short-circuit on failure
- The `all_passed` property

It takes an `on_update(check_id, label, result, running)` callback. It has no Textual imports.

Screens wrap these callbacks with `app.call_from_thread()` to bridge from worker threads to the UI thread. Screens remain responsible for:
- Widget composition (`compose()`)
- Textual event handling (bindings, button presses, lifecycle hooks)
- Threading (`@work(thread=True)`, `set_interval`)
- Updating widgets from callback data

## Consequences

- **Positive**: Core business logic is testable with plain synchronous unit tests, no Textual harness needed. `ControlSession` and `CheckRunner` tests run in ~0.04s.
- **Positive**: Screens are simpler and focused on UI concerns. `ControlScreen` dropped from ~148 to ~100 lines.
- **Positive**: The callback pattern is consistent and reusable for future features.
- **Negative**: One more file per feature (session/runner alongside screen). Acceptable given the testability and clarity gains.
- **Negative**: The callback bridge adds a small amount of indirection between logic and UI updates.
