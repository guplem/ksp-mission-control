# Action Execution System — Full Plan

## Vision

Transform the control screen from a passive telemetry viewer into an interactive vessel automation platform. Users select predefined actions (hover, ascend, circularize...) from a panel, the system executes them tick-by-tick, and eventually chains them into full flight plans that fly a mission from launch to landing.

## Core Principle

Actions never touch kRPC. They are pure functions:

```
VesselState (what the vessel looks like) → VesselControls (what to do next)
```

A runner sits in between, feeding state in and applying controls out. This makes every action testable without a game running, and identical in live and demo modes.

## Data Flow

```
                    ┌─────────────┐
                    │   kRPC /    │
                    │   Demo      │
                    └──────┬──────┘
                           │ read
                           ▼
                    ┌─────────────┐
                    │ VesselState │  (immutable snapshot)
                    └──────┬──────┘
                           │
                           ▼
              ┌────────────────────────┐
              │     ActionRunner       │
              │  ┌──────────────────┐  │
              │  │  Active Action   │  │
              │  │  tick(state,     │  │
              │  │       controls,  │  │
              │  │       dt)        │  │
              │  └──────────────────┘  │
              └────────────┬───────────┘
                           │
                           ▼
                   ┌───────────────┐
                   │VesselControls │  (command buffer)
                   └───────┬───────┘
                           │ apply non-None fields
                           ▼
                    ┌─────────────┐
                    │   kRPC /    │
                    │   discard   │
                    └─────────────┘
```

## Phases

### Phase 1: Foundation + Hover (this round) ✅

**Goal**: Establish the action framework and prove it with one simple action.

**What was built**:
- **Action ABC** with typed parameter descriptors (`ActionParam`), a `start/tick/stop` lifecycle, and ClassVar metadata
- **VesselState** (immutable telemetry snapshot) and **VesselControls** (mutable command buffer where `None` = don't change)
- **ActionRunner** — stateless step-based executor. The control screen's poll loop calls `runner.step()` each tick. Runner validates parameters, handles auto-stop on success/failure, and provides thread-safe snapshots for the UI
- **HoverAction** — proportional altitude-hold controller (P-controller on throttle, SAS enabled)
- **ActionListWidget** — action panel in the control screen showing available actions with a running indicator
- **Split control layout** — telemetry on the left, action list on the right
- **Demo mode** refactored to produce `VesselState` dataclass instead of raw strings, sharing the same rendering path as live mode
- **42 tests** covering base types, runner lifecycle/validation, and hover controller logic

**Key decisions**:
- No `FailurePolicy` yet — only one action, user aborts manually via keybinding
- Actions declare `params: ClassVar[list[ActionParam]]` with `required` bool and optional defaults
- `stop(controls)` receives a command buffer so cleanup actions (throttle zero, SAS off) are applied through the same path as normal ticks
- Runner does not own a thread — called from the existing poll loop

---

### Phase 2: Parameter Input Dialog

**Goal**: Let users configure action parameters before starting.

**What to build**:
- A `ModalScreen` that renders an action's `ActionParam` list as input fields
- Pre-fills defaults, validates required params, shows units as hints
- On submit, passes the edited `param_values` dict to `runner.start_action()`
- Selecting an action in the list opens this dialog instead of starting immediately

**Flow**:
```
User selects action → Parameter dialog opens → User edits values → Submit → Action starts
```

---

### Phase 3: More Actions

**Goal**: Build a library of useful standalone actions.

**Candidate actions**:
- **LaunchAction** — stage, set throttle to max, point up
- **GravityTurnAction** — gradual pitch-over based on altitude
- **CircularizeAction** — compute and execute a circularization burn at apoapsis
- **WaitUntilAction** — tick does nothing, succeeds when a condition on VesselState is met (e.g. `altitude > X`, `time_to_apoapsis < Y`)
- **DeorbitAction** — retrograde burn to lower periapsis
- **LandingAction** — suicide burn / controlled descent

Each action is a self-contained folder under `control/actions/` with its own `action.py`. Adding a new action = write the class + register it.

---

### Phase 4: Flight Plan System

**Goal**: Chain actions into a sequential mission plan.

**What to build**:
- **FlightPlan** dataclass — an ordered list of `(action_id, param_values)` entries
- **FlightPlanRunner** — wraps ActionRunner, advances to the next action when the current one succeeds, aborts the plan on failure
- **Text-based flight plan format** — one action per line, parseable from a file:
  ```
  launch
  gravity_turn  start_altitude=1000  end_altitude=40000
  wait_until    time_to_apoapsis<30
  circularize
  ```
- **Flight plan UI** — display the plan as a list with current/completed/pending indicators

**Flow**:
```
Load plan → Start → Action 1 runs → succeeds → Action 2 runs → ... → Plan complete
                                   → fails → Plan aborted (or retry, based on policy)
```

This is where `FailurePolicy` (abort / retry / skip) becomes relevant — add it to the Action ABC at this stage.

---

### Phase 5: Full Orbit-and-Back Mission

**Goal**: Demonstrate the system end-to-end with a complete mission profile.

**What to build**:
- A flight plan file that takes a vessel from the launchpad to orbit and back:
  ```
  launch
  gravity_turn  start_altitude=1000  end_altitude=45000
  wait_until    time_to_apoapsis<20
  circularize   target_altitude=80000
  wait_until    true_anomaly>180
  deorbit       target_periapsis=30000
  wait_until    altitude_surface<5000
  landing       target_speed=5
  ```
- Tuning and testing of each action's control logic for a stock KSP vessel
- Demo mode simulation that fakes a plausible mission trajectory

---

## Architecture at a Glance

```
control/
├── screen.py                 # ControlScreen — split layout, poll loop, runner integration
├── style.tcss                # Split pane styles
├── actions/
│   ├── base.py               # Action ABC, VesselState, VesselControls, ActionParam, enums
│   ├── runner.py             # ActionRunner (step-based executor)
│   ├── registry.py           # get_available_actions() factory
│   ├── hover/
│   │   └── action.py         # HoverAction
│   ├── launch/               # (Phase 3)
│   ├── gravity_turn/         # (Phase 3)
│   ├── circularize/          # (Phase 3)
│   ├── wait_until/           # (Phase 3)
│   └── flight_plan/          # (Phase 4)
│       ├── plan.py           # FlightPlan dataclass
│       ├── runner.py         # FlightPlanRunner
│       └── parser.py         # Text format parser
├── widgets/
│   ├── action_list.py        # ActionListWidget
│   └── param_dialog.py       # Parameter input modal (Phase 2)
└── demo/
    └── provider.py           # generate_demo_vessel_state()
```

## Testing Strategy

Actions are pure functions — no mocking needed for the core logic:

```
Construct VesselState → call tick() → assert on VesselControls + ActionResult
```

- **Unit tests**: Each action tested in isolation with crafted VesselState inputs
- **Runner tests**: Lifecycle (start/step/abort), auto-stop, parameter validation
- **Integration tests**: Control screen with Textual pilot (widget mounting, action selection, demo mode)
- **Flight plan tests**: Plan parsing, sequential execution, failure handling
