# ADR 0002: kRPC as the KSP Communication Layer

## Context

We need a way to read telemetry and send commands to Kerbal Space Program from an external application. Options:

- **kRPC**: Established mod that runs a gRPC-like server inside KSP1, with Python/C#/Java/Lua clients
- **Telemachus**: Older mod with a web-based API, less maintained
- **Direct memory reading**: Fragile, version-dependent, no official support

## Decision

Use **kRPC** (`pip install krpc`) for KSP1.

- Mature, well-documented, active community
- Streaming API for efficient real-time telemetry (callback on value change, no polling)
- Full game control: vessel, orbit, maneuvers, autopilot, time warp, resources
- Python client is the most popular and best-documented

## Consequences

- **Positive**: Complete game API coverage, efficient streaming, good docs
- **Positive**: Protocol-based design means we can mock the entire client for testing
- **Negative**: KSP1 only (kRPC2 for KSP2 is experimental and KSP2 is abandoned)
- **Negative**: kRPC Python client is synchronous, requires thread bridging with Textual's async loop
- **Negative**: Users must install the kRPC mod in KSP (mitigated by auto-installer in setup/)
