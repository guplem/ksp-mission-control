# ADR 0001: Python + Textual for the TUI Framework

## Context

We need a terminal UI framework to build a mission control console that displays live-updating telemetry, interactive controls, and has a hacker/NASA aesthetic. Options considered:

- **Python + Textual**: CSS-styled widgets, async-first, rich text rendering, active development
- **Python + curses**: Low-level, no widgets, manual layout, cross-platform issues on Windows
- **Rust + ratatui**: Fast, but no kRPC client library for Rust
- **Go + bubbletea**: Elm-architecture TUI, but no kRPC client library for Go

## Decision

Use **Python 3.12+ with Textual** (built on Rich).

- kRPC's best-supported client is Python (`pip install krpc`)
- Textual provides CSS-based layout, built-in widgets (DataTable, ProgressBar, Input, Switch), and async support
- Textual's dev tools (`textual run --dev`) enable live CSS reloading during development
- Rich handles formatted text, tables, and progress bars out of the box

## Consequences

- **Positive**: Fast UI development, excellent widget library, native async for real-time updates
- **Positive**: Same language for game bridge and UI means no IPC complexity
- **Negative**: Python is slower than Rust/Go for CPU-intensive rendering, but TUI rendering is not CPU-bound
- **Negative**: Textual is a moving target (frequent API changes), pin versions carefully
