# CLAUDE.md

This file provides guidance to AI Agents when working with code in this repository.

KSP Mission Control is a Python TUI application that connects to Kerbal Space Program via the kRPC mod (ADR 0002). It provides a terminal-based mission control console with live telemetry, vessel control, maneuver planning, and mission logging. Built with Python + Textual (ADR 0001) and kRPC (game bridge).

**Before implementing any non-trivial feature**, run the `pattern-scout` agent.
**Before/after changes touching architecture**, run the `adr-checker` agent.
**After writing or modifying code**, run the `test-runner` agent.
**After changes affecting documented content**, run the `docs-checker` agent.
**When the user's request is broad or exploratory**, ask whether to run `/research-agents`.

## Living Document

| Discovery | Where to write |
|---|---|
| Cross-project preference or pattern | `~/.claude/CLAUDE.md` |
| Project-specific constraint, gotcha, or pattern | This file |
| Wrong or outdated instruction | Correct it in place |

## Documentation Structure

| File | Audience | Content |
|---|---|---|
| `README.md` | Humans | What it is, install, run, features |
| `CLAUDE.md` | AI agents | Architecture, patterns, rules, gotchas |

## Development Commands

| Task | Command | Notes |
|---|---|---|
| Install deps | `uv sync --dev` | uv is the only package manager (ADR 0003) |
| Install hooks | `git config core.hooksPath hooks` | Auto-runs ruff fix + format on commit |
| Run app | `uv run ksp-mc` | Or `uv run python -m ksp_mission_control` |
| Run tests | `uv run pytest` | TDD: write failing test first |
| Run single test | `uv run pytest tests/test_foo.py -k test_name` | |
| Lint | `uv run ruff check src/ tests/` | |
| Format | `uv run ruff format src/ tests/` | |
| Type check | `uv run mypy` | Strict mode enabled |
| Dev mode (live CSS) | `uv run textual run --dev src/ksp_mission_control/app.py` | Hot-reloads CSS changes |

## Architecture

```
src/ksp_mission_control/
├── app.py                # Textual App subclass, entry point
├── config.py             # AppConfig dataclass + ConfigManager (JSON persistence)
├── theme.py              # Custom Textual theme
├── style.tcss            # App-level global styles
├── control/              # Control room feature
│   ├── screen.py         # ControlScreen (thin UI glue, delegates to session) (ADR 0007)
│   ├── session.py        # ControlSession (poll loop, connection, PlanExecutor) (ADR 0007)
│   ├── style.tcss        # Control-screen grid layout (4x2: telemetry, actions, console, history)
│   ├── formatting.py     # Shared formatting: format_met(), resolve_theme_colors()
│   ├── krpc_bridge.py    # kRPC I/O: read/write + filter_commands() + NoActiveVesselError
│   ├── param_input_modal.py    # ParamInputModal (parameter collection before action start)
│   ├── action_picker.py       # ActionPicker (modal for selecting an action to run)
│   ├── flight_plan_picker.py  # FlightPlanPicker (modal for selecting .plan files)
│   ├── plan_failure_dialog.py # PlanFailureDialog (continue/abort on step failure)
│   ├── actions/          # Action execution system (ADR 0006)
│   │   ├── base.py       # Action ABC, VesselState, VesselCommands, ActionLogger, enums
│   │   ├── runner.py     # ActionRunner (step-based executor), StepResult
│   │   ├── plan_executor.py # PlanExecutor (wraps ActionRunner, chains plan steps)
│   │   ├── flight_plan.py   # FlightPlan, FlightPlanStep, parse_flight_plan()
│   │   ├── registry.py   # get_available_actions() factory
│   │   ├── hover/        # Hover altitude-hold action
│   │   │   └── action.py # HoverAction (PD controller, hover duration)
│   │   ├── land/         # Landing action
│   │   │   └── action.py # LandAction (controlled descent PD controller)
│   │   └── translate/    # Translation action
│   │       └── action.py # TranslateAction (RCS translation control)
│   ├── widgets/          # Control-screen widgets
│   │   ├── telemetry_display.py # TelemetryDisplayWidget (3-column: flight, orbit, resources)
│   │   ├── action_list.py       # ActionListWidget (launch buttons, running status, plan steps)
│   │   ├── debug_console.py     # DebugConsoleWidget (scrolling color-coded action logs)
│   │   └── command_history.py   # CommandHistoryWidget (paginated command history with navigation)
├── setup/                # Setup/checklist feature
│   ├── screen.py         # SetupScreen (thin UI glue, delegates to CheckRunner) (ADR 0007)
│   ├── check_runner.py   # CheckRunner (sequential check execution logic) (ADR 0007)
│   ├── style.tcss        # Setup-screen styles
│   ├── checks.py         # SetupCheck ABC, CheckResult, get_default_checks()
│   ├── kRPC_installer/   # kRPC mod detection + installation
│   │   ├── check.py      # KrpcInstalledCheck
│   │   ├── locator.py    # find_ksp_install, is_valid_ksp_install, etc.
│   │   ├── installer.py  # Download + extract kRPC zip
│   │   ├── screen.py     # KrpcSetupScreen (guided installer UI)
│   │   └── style.tcss
│   ├── kRPC_comms/       # kRPC server connectivity check
│   │   ├── check.py      # KrpcCommsCheck
│   │   ├── parser.py     # Parse kRPC settings.cfg + resolve_krpc_connection()
│   │   ├── screen.py     # KrpcCommsScreen (connectivity help + test button)
│   │   └── style.tcss
│   ├── vessel/           # Active vessel detection check
│   │   ├── check.py      # VesselDetectedCheck
│   │   ├── screen.py     # VesselScreen (vessel help + check button)
│   │   └── style.tcss
│   └── widgets/          # Setup-screen widgets
│       └── welcome_widget.py # WelcomeWidget
└── widgets/              # Shared/reusable Textual Widgets
    └── welcome_view.py   # WelcomeView

plans/                        # Flight plan files (.plan)
├── hover-and-land.plan       # Hover then land
└── altitude-steps.plan       # Step through altitudes then land
```

### Module organization rules

This project uses **feature-based modules**, not layer-based. Every feature is a self-contained folder.

- **One feature = one folder**. A feature folder contains its own `screen.py`, `style.tcss`, `check.py`, business logic files, and sub-features as nested folders. No central `screens/` or `styles/` directories.
- **Co-locate styles with screens**. Each screen's `style.tcss` lives next to its `screen.py`. The screen references it via `CSS_PATH = "style.tcss"`. App-level global styles live in the root `style.tcss`. Screen styles should only contain layout rules for how widgets are arranged (sizing, spacing, borders between panels), not widget-internal styling.
- **Widget styles use `DEFAULT_CSS`**. Textual's `CSS_PATH` only works on `Screen` and `App`, not on `Widget`. Widgets own their internal styles via a `DEFAULT_CSS` class-level string. Keep these rules scoped to the widget's own children (e.g. title padding, internal list height). The parent screen controls the widget's external layout (width, padding, borders).
- **Small, focused files**. One class per file. Each file has a single clear responsibility. Prefer many small files over few large ones.
- **Descriptive file names**. Name files after what they contain: `check.py` for a check class, `locator.py` for path-finding logic, `installer.py` for download/install logic. Never `utils.py` or `helpers.py`.
- **Sub-features nest as subfolders**. If a feature has distinct sub-concerns (e.g. `setup/` has `kRPC_installer/`, `kRPC_comms/`, `vessel/`), each gets its own folder with its own files.
- **Shared code stays at the parent level**. Base classes and shared types (e.g. `SetupCheck`, `CheckResult`) live in the parent module (e.g. `setup/checks.py`), not duplicated in sub-features.

### Code style rules

- **`ClassVar` over abstract properties** for static per-class metadata. If a value never changes per instance, declare it as a `ClassVar` annotation on the ABC and set it as a plain class attribute in subclasses. Reserve `@abstractmethod` for methods with actual logic.
- **Explicit type annotations** on all class attributes, function parameters, and return types. Annotate instance attributes in `__init__` when the type is not obvious from the assignment.
- **No over-engineering**. No base classes, abstractions, or indirection until you have at least two concrete uses. Three similar lines of code is better than a premature abstraction.
- **No unnecessary wrappers**. Every container, wrapper, or structural element must have a purpose. Don't wrap a single widget in a `HorizontalGroup`; don't add a `Center` around something that doesn't need centering. If a wrapper has only one child and adds no layout behavior, remove it.
- **Single source of truth for logic**. Never reimplement logic that already exists in another class. If a check class validates something, screens should call that check rather than duplicating the validation inline. When adding a UI action that mirrors an existing operation (e.g. a "test connection" button for a connectivity check), call the existing check's `run()` method instead of reimplementing it.
- **Top-level imports over lazy inline imports**. Import dependencies at the top of the file. Only use inline imports when strictly necessary to break circular dependencies.
- **`cast()` over `type: ignore`**. When accessing app-specific attributes (e.g. `self.app.config_manager`), use `cast(MissionControlApp, self.app)` instead of `# type: ignore` comments.
- **Data-driven dispatch over hardcoded branching**. Don't write `if check_id == "check-krpc": import FooScreen`. Instead, let objects carry their own metadata (e.g. `check.screen`) and dispatch generically. New entries should not require editing unrelated code.
- **Resolve state in `__init__`, not in lifecycle hooks**. If a value can be computed at construction time, do it in `__init__`. Keep `on_mount` / `compose` simple and free of conditional setup logic. Avoid dual-path initialization (e.g. separate codepaths for "explicit" vs "default" arguments).
- **Keep screens thin**. Screens should only compose widgets, handle Textual events/bindings, and bridge between logic classes and the UI. If a screen owns a poll loop, manages a connection, or runs sequential business logic, extract that into a dedicated class (e.g. `ControlSession`, `CheckRunner`) that takes typed callbacks and has no Textual imports.
- **Descriptive names everywhere**. No single-letter variables except `_` for intentionally unused values. Lambda parameters must be named: `lambda state, snapshot, commands:` not `lambda s, r, c:`.
- **Cache with `None` init pattern**. For lazy-resolved values (e.g. theme colors that need `self.app`), initialize to `None` in `__init__` and check `if self._x is None` on first use. Never use `hasattr` for caching.

### Data flow

```
kRPC --read--> krpc_bridge --> VesselState --> PlanExecutor.step() --> VesselCommands
                                                      |
                                              ActionRunner.step()
                                              (single action tick)
                                                      |
                                              filter_commands(commands, state)
                                                    |              |
                                              applied_fields   filtered commands
                                                    |              |
                                                    |       krpc_bridge --write--> kRPC
                                                    |
                                  ControlSession (owns connection + executor + poll loop)
                                      |                                      |
                                  on_update callback                    on_error callback
                                      |                                      |
                                  ControlScreen (UI glue: call_from_thread -> widgets)
```

- **Read path**: `krpc_bridge.read_vessel_state()` reads kRPC telemetry into a pure `VesselState` dataclass.
- **Action loop**: `PlanExecutor.step()` delegates to `ActionRunner.step()`, which passes `VesselState` to the current action's `tick()`, mutating a `VesselCommands` buffer. When a plan is active, PlanExecutor detects action completion and auto-advances to the next step.
- **Command filtering**: `filter_commands()` compares each command field against the vessel's current state. Only fields that differ are sent to kRPC. Returns `applied_fields` (which fields were actually sent) for the UI.
- **Write path**: `krpc_bridge.apply_controls()` writes the filtered commands to kRPC.
- **Session/screen split**: `ControlSession` owns the poll loop and calls `on_update`/`on_error` callbacks. `ControlScreen` wraps these callbacks with `call_from_thread()` to bridge to the UI thread.
- **Models are pure (ADR 0004)**: `VesselState` and `VesselCommands` have no kRPC or Textual imports. Actions are testable with constructed states.
- **Flight plans**: Text files (`.plan`) parsed by `parse_flight_plan()`. Each line is `action_id key=value ...`. Plans are loaded via `FlightPlanPicker` modal. On step failure, `PlanFailureDialog` asks user to continue or abort.

### Key patterns

- **Screen + session/runner pattern (ADR 0007)**: Screens are thin UI glue. Business logic (poll loops, check sequencing, connection lifecycle) lives in dedicated classes (`ControlSession`, `CheckRunner`) that communicate via typed callbacks. These logic classes have no Textual dependency and are independently testable. Screens wrap callbacks with `app.call_from_thread()` to bridge from worker threads to the UI thread.
- **Two-loop poll architecture**: `ControlSession.run_poll_loop()` has an outer loop (reconnect on connection death) and inner loop (poll every 0.5s). Errors are either *transient* (keep polling: `NoActiveVesselError`, generic) or *connection dead* (break to reconnect: `FutureTimeout`, `ConnectionError`). Each kRPC call runs in a `ThreadPoolExecutor` with a 10s timeout to detect hung connections.
- **Thread bridge**: kRPC calls are synchronous. Use Textual's `@work(thread=True)` for blocking I/O, `app.call_from_thread()` to push updates to the UI thread.
- **Action tick lifecycle**: Actions implement `start()` / `tick(state, commands, dt, log)` / `stop(commands, log)`. The `ActionRunner` calls `tick()` each poll iteration and auto-stops on SUCCEEDED or FAILED. Actions emit debug messages via `ActionLogger` (DEBUG, INFO, WARN, ERROR levels). Actions never touch kRPC directly.
- **Command buffer + filtering**: `VesselCommands` fields default to `None` ("don't change"). Actions set only the fields they care about. `filter_commands()` compares against vessel state and only sends fields that differ. The UI shows all intended values but dims redundant ones.
- **Theme color resolution**: Widgets that need theme colors in Rich markup (where CSS variables aren't available) use `resolve_theme_colors(app, mapping)` from `formatting.py`. Results are cached after first call.
- **CSS theming**: Keep static layout and visual styling in `.tcss`. Use Python style updates only for runtime-dependent values (state, measurements, animations, temporary overrides).
- **Flight plan execution**: `PlanExecutor` wraps `ActionRunner` and manages step-to-step transitions. It detects action completion by comparing runner snapshots before/after `step()` and checking logs for "succeeded"/"failed". On success, it auto-starts the next step. On failure, it pauses and sets `paused_on_failure` for the UI to show a dialog. Plans are stored as `.plan` text files in the `plans/` directory.

### Textual UI composition and styling rules (ADR 0001)

Use this separation of concerns for all Textual UI work:

- **Compose + containers define structure**: Use `compose()` and container hierarchy (`Vertical`, `Horizontal`, `Center`, `Middle`, etc.) to define parent/child relationships and layout intent.
- **`.tcss` defines static presentation**: Put fixed spacing, sizing, colors, typography, and other non-dynamic visual rules in `.tcss`. Layout alignment (`content-align`, `align-horizontal`, `align-vertical`) should be handled by Textual container widgets (`Center`, `Middle`, etc.) in `compose()`, not in `.tcss`.
- **Python style mutations are runtime-only**: Use `widget.styles.*` in Python only for dynamic behavior (state-driven changes, measurements, animations, temporary overrides).

Preferred compose style:

- Use **constructor nesting** for simple single-child wrappers (typically 1 to 2 levels), for example one-liners like `Middle(Center(WelcomeView()))`.
- Use **`with` blocks** when a container has multiple siblings or nesting depth exceeds 2 levels, because it is easier to read and maintain.
- Choose whichever is clearest, but do not move fixed visual styling from `.tcss` into Python.

Default policy for agents:

- If a style value is static, place it in `.tcss`.
- If a style value depends on runtime state, Python may set it.
- Prefer IDs/classes + `.tcss` over repeated inline Python style assignments.

## Test-Driven Development (ADR 0005)

This project follows red-green TDD:

1. **Red**: Write a failing test for the behavior you want
2. **Green**: Write the minimum code to make it pass
3. **Refactor**: Clean up while keeping tests green

Test structure mirrors source: `tests/test_<module>.py` for each source module.

- Models: test construction, defaults, edge values
- Mock client: test that it produces valid model instances
- Widgets: use Textual's `pilot` for async widget testing
- Setup: test KSP path detection, mock filesystem for installer

## Architecture Decision Records (ADRs)

Format: `adr/NNNN-short-title.md` with Context, Decision, Consequences sections.

| ADR | Topic | Read when... |
|---|---|---|
| [0001](adr/0001-python-textual-tui.md) | Python + Textual for the TUI framework | Adding/changing UI, screens, widgets, or CSS |
| [0002](adr/0002-krpc-game-bridge.md) | kRPC as the KSP communication layer | Touching krpc_bridge, connection logic, or telemetry |
| [0003](adr/0003-uv-package-manager.md) | uv as the package manager | Adding dependencies or changing build config |
| [0004](adr/0004-protocol-based-client.md) | Protocol-based client abstraction for testability | Changing data sources or mock strategy |
| [0005](adr/0005-tdd-workflow.md) | Test-driven development workflow | Writing or restructuring tests |
| [0006](adr/0006-action-execution-system.md) | Tick-based action execution system | Adding actions, changing runner, or modifying the control loop |
| [0007](adr/0007-screen-session-pattern.md) | Screen + session/runner separation of concerns | Adding new screens or refactoring screen logic |

When to create a new ADR: any decision involving trade-offs between alternatives, especially around dependencies, architecture boundaries, or data flow.

## GitHub Issues, PRs, and Other Artifacts

- Always self-assign PRs with `--assignee @me`
- Always link PRs to issues using `Closes #N`
- Always add `waiting-for-human-check` label (create with `gh label create waiting-for-human-check --color FBCA04` if it doesn't exist)

## Self-Updating Rules

Add a rule here when:
- A competent agent would get it wrong without the rule
- The rule saves significant debugging time
- The pattern is non-obvious from reading the code

## Gotchas

- **Use dataclass `__eq__`**: `@dataclass` auto-generates field-by-field equality. Don't reimplement comparison helpers manually.
- kRPC Python client is synchronous (ADR 0002). Never call it from Textual's async event loop directly. Always use `@work(thread=True)`. Wrap kRPC calls in a `ThreadPoolExecutor` with a timeout to detect hung connections.
- Any blocking I/O (sockets, filesystem) in a Textual worker must use `@work(thread=True)`, not an `async` coroutine passed to `run_worker()`. An async coroutine still runs on the event loop thread, so it blocks the UI and prevents status updates from rendering.
- Textual CSS uses `.tcss` extension, not `.css`. The `CSS_PATH` in App/Screen must point to the right file.
- `uv run` is required to execute anything in the project's virtual environment. Plain `python` or `pytest` won't use the right env.
