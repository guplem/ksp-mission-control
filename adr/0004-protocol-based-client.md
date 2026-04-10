# ADR 0004: Protocol-based Client Abstraction for Testability

## Context

The TUI needs game data to display. During development and testing, we can't require a running KSP instance. We need an abstraction that allows swapping between real and mock data sources.

## Decision

Define a `MissionClient` Protocol in `connection/protocol.py`. Both `KRPCClient` (real) and `MockClient` (fake) implement it.

The protocol exposes:
- Read methods returning model dataclasses (TelemetryData, OrbitData, etc.)
- Command methods (set_throttle, toggle_sas, activate_stage, etc.)
- Connection state (`is_connected`)

The app selects the client at startup: `--demo` flag or failed connection uses `MockClient`.

## Consequences

- **Positive**: Full TUI development and testing without KSP running
- **Positive**: Widget tests use MockClient, no network mocking needed
- **Positive**: Demo mode lets users explore the UI before installing kRPC
- **Negative**: Must keep Protocol, KRPCClient, and MockClient in sync manually
