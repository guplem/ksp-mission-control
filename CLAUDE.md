# CLAUDE.md

This file provides guidance to AI Agents when working with code in this repository.

KSP Mission Control is a Python TUI application that connects to Kerbal Space Program via the kRPC mod. It provides a terminal-based mission control console with live telemetry, vessel control, maneuver planning, and mission logging. Built with Textual (TUI framework) and kRPC (game bridge).

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
| Install deps | `uv sync --dev` | Includes test/lint/type-check tools |
| Run app | `uv run ksp-mc` | Or `uv run python -m ksp_mission_control` |
| Run demo mode | `uv run ksp-mc --demo` | Mock data, no KSP needed |
| Run tests | `uv run pytest` | TDD: write failing test first |
| Run single test | `uv run pytest tests/test_foo.py -k test_name` | |
| Lint | `uv run ruff check src/ tests/` | |
| Format | `uv run ruff format src/ tests/` | |
| Type check | `uv run mypy` | Strict mode enabled |
| Dev mode (live CSS) | `uv run textual run --dev src/ksp_mission_control/app.py` | Hot-reloads CSS changes |

## Architecture

```
src/ksp_mission_control/
├── app.py              # Textual App subclass, entry point
├── config.py           # AppConfig dataclass + ConfigManager (JSON persistence)
├── theme.py            # Custom Textual theme
├── style.tcss          # App-level global styles
├── control/            # Control room feature
│   ├── screen.py       # ControlScreen (live telemetry, vessel control)
│   ├── style.tcss      # Control-screen styles
│   ├── actions/        # Action execution system (ADR 0006)
│   │   ├── base.py     # Action ABC, VesselState, VesselControls, ActionParam, enums
│   │   ├── runner.py   # ActionRunner (step-based executor)
│   │   ├── registry.py # get_available_actions() factory
│   │   └── hover/      # Hover altitude-hold action
│   │       └── action.py # HoverAction
│   ├── widgets/        # Control-screen widgets
│   │   └── action_list.py # ActionListWidget (available actions display)
│   └── demo/           # Demo mode data
│       └── provider.py # generate_demo_vessel_state()
├── setup/              # Setup/checklist feature
│   ├── screen.py       # SetupScreen (system readiness checklist)
│   ├── style.tcss      # Setup-screen styles
│   ├── checks.py       # SetupCheck ABC, CheckResult, get_default_checks()
│   ├── kRPC_installer/ # kRPC mod detection + installation
│   │   ├── check.py    # KrpcInstalledCheck
│   │   ├── detector.py # find_ksp_install, is_valid_ksp_install, etc.
│   │   ├── manager.py  # Download + extract kRPC zip
│   │   ├── screen.py   # KrpcSetupScreen (guided installer UI)
│   │   └── style.tcss
│   ├── kRPC_comms/     # kRPC server connectivity check
│   │   └── check.py    # KrpcCommsCheck
│   └── vessel/         # Active vessel detection check
│       └── check.py    # VesselDetectedCheck
├── connection/         # kRPC bridge layer
│   ├── client.py       # KRPCClient (real game connection)
│   ├── mock.py         # MockClient (fake data for dev/demo)
│   ├── streams.py      # StreamManager (kRPC stream subscriptions)
│   └── protocol.py     # MissionClient Protocol (shared interface)
├── models/             # Pure Python dataclasses (no TUI/kRPC imports)
│   ├── telemetry.py    # TelemetryData
│   ├── orbit.py        # OrbitData
│   ├── vessel.py       # VesselState
│   ├── control.py      # ControlState
│   └── events.py       # MissionEvent
└── widgets/            # Shared/reusable Textual Widgets
    └── welcome_view.py # WelcomeView
```

### Module organization rules

This project uses **feature-based modules**, not layer-based. Every feature is a self-contained folder.

- **One feature = one folder**. A feature folder contains its own `screen.py`, `style.tcss`, `check.py`, business logic files, and sub-features as nested folders. No central `screens/` or `styles/` directories.
- **Co-locate styles with screens**. Each screen's `style.tcss` lives next to its `screen.py`. The screen references it via `CSS_PATH = "style.tcss"`. App-level global styles live in the root `style.tcss`.
- **Small, focused files**. One class per file. Each file has a single clear responsibility. Prefer many small files over few large ones.
- **Descriptive file names**. Name files after what they contain: `check.py` for a check class, `detector.py` for detection logic, `manager.py` for orchestration logic. Never `utils.py` or `helpers.py`.
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

### Data flow

```
kRPC Server (KSP) --> connection/ (streams) --> models/ (dataclasses) --> widgets/ (display)
                  <-- connection/ (commands) <-- screens/ (user input) <-- widgets/ (events)
```

- **Unidirectional for reads**: kRPC streams push data, connection layer converts to model dataclasses, widgets render them.
- **Reverse for commands**: widget events bubble up to screen handlers, which call client methods.
- **Models are pure**: no kRPC or Textual imports. This keeps them testable and decoupled.
- **Protocol-based client**: `KRPCClient` and `MockClient` both implement `MissionClient` Protocol. The app picks one at startup.

### Key patterns

- **10 Hz refresh**: `DashboardScreen` uses `set_interval(0.1, refresh)` to read cached stream values and update widgets.
- **Thread bridge**: kRPC calls are synchronous. Use Textual's `@work(thread=True)` for commands, `app.call_from_thread()` for callbacks.
- **CSS theming**: Keep static layout and visual styling in `.tcss`. Use Python style updates only for runtime-dependent values (state, measurements, animations, temporary overrides).

### Textual UI composition and styling rules

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

## Test-Driven Development

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

| ADR | Topic |
|---|---|
| [0001](adr/0001-python-textual-tui.md) | Python + Textual for the TUI framework |
| [0002](adr/0002-krpc-game-bridge.md) | kRPC as the KSP communication layer |
| [0003](adr/0003-uv-package-manager.md) | uv as the package manager |
| [0004](adr/0004-protocol-based-client.md) | Protocol-based client abstraction for testability |
| [0005](adr/0005-tdd-workflow.md) | Test-driven development workflow |
| [0006](adr/0006-action-execution-system.md) | Tick-based action execution system |

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

- kRPC Python client is synchronous. Never call it from Textual's async event loop directly. Always use `@work(thread=True)`.
- Any blocking I/O (sockets, filesystem) in a Textual worker must use `@work(thread=True)`, not an `async` coroutine passed to `run_worker()`. An async coroutine still runs on the event loop thread, so it blocks the UI and prevents status updates from rendering.
- Textual CSS uses `.tcss` extension, not `.css`. The `CSS_PATH` in App/Screen must point to the right file.
- `uv run` is required to execute anything in the project's virtual environment. Plain `python` or `pytest` won't use the right env.
