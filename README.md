# KSP Mission Control

A terminal-based mission control console for **Kerbal Space Program**. Connect to your running KSP game via the [kRPC mod](https://krpc.github.io/krpc/) and monitor telemetry, control your vessel, plan maneuvers, and manage missions -- all from a hacker-aesthetic terminal UI.

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

## Features

- **Live flight telemetry** -- 3-column display: flight data, orbital parameters, resources and configuration, updated every 0.5s
- **Automated vessel actions** -- tick-based action system with parameter input. Ships with Hover (PD altitude-hold) and Land (controlled descent) actions
- **Flight plans** -- load multi-step mission plans from `.plan` text files. Steps execute sequentially with per-step status tracking, auto-advance on success, and a failure dialog to continue or abort
- **Action debug console** -- scrolling, color-coded log (DEBUG/INFO/WARN/ERROR) with MET timestamps showing action internals
- **Command history** -- paginated record of every command sent to the vessel, showing which fields were actually applied vs redundant
- **Auto kRPC setup** -- detects your KSP installation and installs the kRPC mod for you
- **Connection resilience** -- auto-reconnect on connection loss, kRPC call timeouts, graceful handling of missing vessels
- **Demo mode** -- explore the full UI with mock data, no KSP required

## Prerequisites

- [Kerbal Space Program](https://store.steampowered.com/app/220200/Kerbal_Space_Program/) (KSP 1.x)
- [uv](https://docs.astral.sh/uv/) (Python package manager)

## Installation

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/ksp-mission-control.git
cd ksp-mission-control

# Install dependencies
uv sync

# Run the app
uv run ksp-mc
```

On first run, the app will check for the kRPC mod in your KSP installation and guide you through setup if needed.

## Quick Start

1. **Launch KSP** and load a save with a vessel on the launchpad or in orbit
2. **Run ksp-mc**: `uv run ksp-mc`
3. **Connect** to the kRPC server (default: `localhost:50000`)
4. **Monitor and control** your mission from the terminal

To try the UI without KSP running:

```bash
uv run ksp-mc --demo
```

## Flight Plans

Create `.plan` files in the `plans/` directory. Each line is an action ID followed by space-separated `key=value` parameters:

```
# Hover at 50m for 5 seconds, then land
hover  target_altitude=50  hover_duration=5
land   target_speed=2
```

- Lines starting with `#` are comments
- Empty lines are ignored
- Missing optional parameters use the action's defaults

Load a plan from the control screen using the **Load Flight Plan** button.

## Development

```bash
# Install with dev dependencies
uv sync --dev

# Install git hook (auto-formats and lints on commit)
git config core.hooksPath hooks

# Run with Textual dev mode (live CSS reload)
uv run textual run --dev src/ksp_mission_control/app.py

# Run with Textual dev mode (live CSS reload)
uv run textual serve --dev src/ksp_mission_control/app.py

# Access the Textual console for debugging (in another terminal you must run the app with --dev)
uv run textual console
```

### Validations

```bash
# Run tests
uv run pytest

# Lint
uv run ruff check src/ tests/

# Type check
uv run mypy
```

## Contributing

Contributions are welcome! This project follows TDD -- write a failing test first, then implement.

1. Fork the repo
2. `uv sync --dev && git config core.hooksPath hooks`
3. Create a feature branch
4. Write tests, then implementation
5. Open a PR

## License

MIT -- see [LICENSE](LICENSE).
