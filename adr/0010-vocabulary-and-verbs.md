# ADR 0010: Vocabulary and Verbs

## Context

The project mixed two different concepts under overlapping names. `vessel` and `craft` were used interchangeably across class names, file paths, dialog titles, and log messages. The same was true for verbs: "Save Vessel" was an export, "Load Vessel" was a spawn, "Run Action" started an action, and "Cancel" sometimes stopped a running plan. As the surface grew, this drift made the code harder to read and the UI harder to trust.

Establishing a fixed vocabulary lets us name modules, methods, buttons, and log messages from a single source of truth. Any future addition follows the same rules, so a developer or AI agent can predict the right word without checking existing code.

## Decision

### Two distinct nouns

`craft` and `vessel` are not synonyms. They denote different things at different stages of the lifecycle.

| Term | Meaning | Lifecycle |
|---|---|---|
| **craft** | A blueprint. Lives in a `.craft` file. Has no physics, no telemetry, no engines firing. | Exists on disk. |
| **vessel** | A live instance flying in the KSP world. Has telemetry, position, controls. | Created by spawning a craft. Destroyed by recovery, explosion, or crash. |

A craft becomes a vessel only by being spawned. Until that moment, every reference must say "craft", not "vessel". After that moment, every reference must say "vessel", not "craft". Mixed phrasing in the same sentence is a bug.

We do not use `ship`, `rocket`, or `spacecraft`. The project supports more than rockets (hover craft, rovers, planes, science probes), so `rocket` is too narrow. `ship` and `spacecraft` are colloquial and would only blur the craft/vessel split.

### Three workflows for moving craft and vessels

The project moves craft files between three places and instantiates a vessel from them. Each leg of the workflow has its own verb.

| Workflow | Verb | Direction | What actually happens |
|---|---|---|---|
| **Export craft** | `export` | live KSP vessel -> project `crafts/` folder | Read the active vessel's design and write it as a `.craft` file in the project. |
| **Load craft** | `load` | project `crafts/` folder -> KSP `saves/<save>/Ships/VAB/` | Copy the `.craft` file into the KSP save so the game knows about it. |
| **Spawn vessel** | `spawn` | KSP craft (in VAB) -> live vessel on the launch pad | Instantiate the craft as a flying vessel in the world. |

Internally, "spawn vessel from craft" is a composite operation: it loads the craft into KSP if necessary, then spawns the vessel on the pad. The user-facing entry point is "Spawn Vessel"; "Load Craft" appears only as a conflict-resolution dialog when the load step finds an existing copy in the save.

KSP's own UI uses "Launch" for what we call "spawn" (the VAB's Launch button). We diverge from the game's wording on purpose: separating spawn from launch lets us use "launch" exclusively for starting a flight plan, which is more useful internally than matching the game.

### Action verbs

| Concept | Verb | Where it appears |
|---|---|---|
| Start a flight plan | **launch** | Pending-plan tray button, `Launch from Flight Plan` setup button, status messages. |
| Start a single action | **start** | "Start Action" button, `StartActionRequested` event, `action.start()` lifecycle method. |
| Send a one-shot command | **send** | Manual Command and Science Command dialogs. |
| Stop a running plan, track, or action | **stop** | "Stop", "Stop Plan", "Stop Track", "Stop All" buttons; `StopRunRequested` event; `FailureAction.STOP_*` enums. |
| Dismiss a dialog or pre-execution staged item | **cancel** | "Cancel" buttons across all dialogs and the pending-plan tray. |
| Trigger the in-game ABORT action group | **abort** | `VesselCommands.abort` field only. Never used for plan or action UI. |

`abort` is reserved for the kRPC abort action group (the staged emergency-jettison action group bound to Backspace in KSP). It must not appear in plan or action user flows. A user stopping a running plan is using `stop`, not `abort`.

`launch` is overloaded with the `LaunchAction` class, which performs vertical ascent plus gravity turn to apoapsis. The overload is acceptable because in aerospace "launch" is the standard term for that whole maneuver. The action keeps its name.

### Plan lifecycle states

`PENDING -> RUNNING -> SUCCEEDED -> FAILED`. The display renders the full word for every state. Older terse forms ("OK") are removed.

A plan staged but not yet running is referred to as **pending**. The internal field is `_pending_plan`, the method is `set_pending_plan()`, the UI region is the "pending-plan tray". The word `staged` is reserved for KSP staging (booster separation). Do not use `staged` for plans.

### Action message tense

Action messages reported via `ActionResult.message` follow a fixed tense convention so the log reads coherently regardless of which action emitted the line.

- **RUNNING** messages use present continuous: `"Hovering at 100m"`, `"Climbing to apoapsis"`, `"Waiting for periapsis"`.
- **SUCCEEDED** messages use past tense or a static descriptor: `"Reached target apoapsis"`, `"Landed"`, `"Hovered for 30s at 100m"`.
- **FAILED** messages use past tense with a cause: `"Failed: insufficient thrust"`, `"Failed: no parachutes found"`.

`log.debug()`, `log.info()`, `log.warn()`, `log.error()` follow normal English; the tense rule applies only to the structured `message` field of an `ActionResult`.

### Live vessel reference

The single phrase is **active vessel**. Do not use "live vessel", "current vessel", or "the vessel" when "active vessel" would be clearer.

## Consequences

- **Positive**: A new module, button, or log message has exactly one right word. Reviews stop debating whether it should say "load" or "spawn".
- **Positive**: The craft/vessel split mirrors the actual KSP data model (a `.craft` file is a blueprint; an `active_vessel` is the kRPC API). Code matches the domain.
- **Positive**: `abort` reserved for the in-game action group means plan UI cannot accidentally fire ABORT (which can jettison the crew capsule).
- **Negative**: KSP's own VAB uses "Launch" for what we call "spawn". Users new to the project will need to learn the distinction.
- **Negative**: Renaming touched a wide surface (filesystem, modules, UI strings, tests). Acceptable as a one-time cost.
