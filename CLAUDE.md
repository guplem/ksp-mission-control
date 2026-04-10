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
├── screens/            # Textual Screens
│   ├── connect.py      # ConnectionScreen (IP/port, demo mode)
│   ├── dashboard.py    # DashboardScreen (main grid layout)
│   └── setup.py        # SetupScreen (kRPC mod installation)
├── setup/              # KSP/kRPC detection and installation
│   ├── detector.py     # Find KSP install path
│   └── installer.py    # Download and install kRPC mod
├── widgets/            # Custom Textual Widgets
│   ├── telemetry_panel.py
│   ├── orbit_panel.py
│   ├── fuel_gauge.py
│   ├── vessel_control.py
│   ├── maneuver_panel.py
│   ├── attitude_indicator.py
│   └── mission_log.py
└── styles/             # Textual CSS
    ├── app.tcss        # Global theme (dark, green/amber terminal)
    ├── connect.tcss
    ├── dashboard.tcss
    └── widgets.tcss
```

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
- **CSS theming**: All visual styling in `.tcss` files. Widget classes set IDs/classes, CSS handles layout and colors.

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
- Textual CSS uses `.tcss` extension, not `.css`. The `CSS_PATH` in App/Screen must point to the right file.
- `uv run` is required to execute anything in the project's virtual environment. Plain `python` or `pytest` won't use the right env.
