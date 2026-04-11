# KSP Mission Control

A terminal-based mission control console for **Kerbal Space Program**. Connect to your running KSP game via the [kRPC mod](https://krpc.github.io/krpc/) and monitor telemetry, control your vessel, plan maneuvers, and manage missions -- all from a hacker-aesthetic terminal UI.

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

## Features

- **Live flight telemetry** -- altitude, velocity, g-force, attitude, updated in real-time
- **Orbital parameters** -- apoapsis, periapsis, eccentricity, inclination, period
- **Fuel gauges** -- per-resource progress bars (LiquidFuel, Oxidizer, MonoPropellant, ElectricCharge)
- **Vessel control** -- throttle, staging, SAS/RCS, action groups
- **Maneuver planner** -- create, edit, and delete maneuver nodes
- **Mission log** -- timestamped event timeline
- **Auto kRPC setup** -- detects your KSP installation and installs the kRPC mod for you
- **Demo mode** -- explore the UI with mock data, no KSP required

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

## Development

```bash
# Install with dev dependencies
uv sync --dev

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
2. Create a feature branch
3. Write tests, then implementation
4. Open a PR

## License

MIT -- see [LICENSE](LICENSE).
