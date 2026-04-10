# ADR 0003: uv as the Package Manager

## Context

We need a Python package manager for dependency resolution, virtual environment management, and running scripts. Options:

- **uv**: Fast Rust-based package manager, drop-in pip replacement, handles venvs
- **pip + venv**: Standard but slow, no lockfile, manual venv management
- **poetry**: Feature-rich but slower, heavier configuration
- **pdm**: PEP 582 support, less widely adopted

## Decision

Use **uv** for all package management.

- 10-100x faster than pip for dependency resolution and installation
- Handles virtual environments transparently (`uv sync`, `uv run`)
- Compatible with standard `pyproject.toml` (no lock-in)
- Growing adoption in the Python ecosystem

## Consequences

- **Positive**: Fast installs, simple workflow (`uv sync` then `uv run`)
- **Positive**: Standard pyproject.toml means users can still use pip if they prefer
- **Negative**: Users need to install uv (mitigated by simple one-line installer)
- **Negative**: Newer tool, less Stack Overflow answers (but good docs)
