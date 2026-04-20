# ADR 0008: VesselState and VesselCommands Naming Convention

## Context

`VesselState` has grown to 50+ fields mapped from kRPC telemetry, and `VesselCommands` mirrors the commandable subset. As we add more fields (atmospheric flight data, orbital mechanics, communications, resource capacities), we need a consistent, rule-based naming convention so that any developer or AI agent can predict the correct name for a new field without checking existing code.

kRPC's own naming is inconsistent (mixing camelCase, different object hierarchies, abbreviations) and organized by API object (`vessel.flight()`, `vessel.orbit`, `vessel.control`). Our naming should be organized by semantic domain instead.

## Decision

### Core principles

1. **Implied vessel**: `VesselState` IS the vessel's state. No `vessel_` prefix on any field. Every field is implicitly "of the vessel."

2. **Semantic group prefix**: Fields are grouped by domain concept, not by kRPC API object. The prefix answers "what kind of measurement is this?" not "which kRPC object did it come from."

3. **Entity prefix for external objects**: Properties of external objects (the orbited body, the orbit itself) use an entity prefix because they describe something other than the vessel: `body_*`, `orbit_*`.

4. **Entity-first ordering**: Within a group, the subject comes before the qualifier. `orbit_apoapsis_time_to` not `orbit_time_to_apoapsis`. The first word after the group prefix identifies what we're measuring; subsequent words narrow it.

5. **Variant suffixes**: When multiple variants of the same concept exist, the base concept comes first and the variant is suffixed: `thrust`, `thrust_available`, `thrust_peak`; `mass`, `mass_dry`.

6. **Domain abbreviations allowed**: Well-known orbital mechanics and KSP abbreviations are permitted when the full name would be excessively verbose: `soi` (sphere of influence), `gm` (gravitational parameter), `isp` (specific impulse), `twr` (thrust-to-weight ratio), `met` (mission elapsed time). The abbreviation must be universally understood in the KSP/orbital mechanics domain. When in doubt, use the full name.

7. **Ungrouped fundamentals**: A small set of core vessel-identity fields have no prefix: `met`, `name`, `situation`, `g_force`, `universal_time`. These are vessel-level or game-level scalars that don't belong to any semantic group.

### Semantic groups

| Prefix | Domain | Examples |
|---|---|---|
| `altitude_` | Height measurements | `altitude_sea`, `altitude_surface` |
| `speed_` | Velocity / speed measurements | `speed_vertical`, `speed_surface`, `speed_orbital` |
| `pressure_` | Atmospheric pressure | `pressure_dynamic`, `pressure_static` |
| `aero_` | Aerodynamic forces, coefficients, and derived quantities | `aero_drag`, `aero_lift`, `aero_mach`, `aero_angle_of_attack` |
| `orbit_` | Orbital parameters (entity prefix) | `orbit_apoapsis`, `orbit_eccentricity`, `orbit_period` |
| `body_` | Celestial body properties (entity prefix) | `body_name`, `body_gravity`, `body_radius` |
| `position_` | Geographic coordinates on the body | `position_latitude`, `position_longitude` |
| `orientation_` | Vessel attitude angles | `orientation_pitch`, `orientation_heading`, `orientation_roll` |
| `mass_` | Vessel mass variants | `mass`, `mass_dry` |
| `thrust_` | Thrust variants | `thrust`, `thrust_available`, `thrust_peak` |
| `engine_` | Engine-specific properties | `engine_impulse_specific`, `engine_flameout_count` |
| `stage_` | Staging info | `stage_current`, `stage_max` |
| `resource_` | Consumable resources (amount, capacity, fraction) | `resource_liquid_fuel`, `resource_liquid_fuel_max` |
| `control_` | Commandable state (readable AND writable via VesselCommands) | `control_throttle`, `control_sas`, `control_autopilot` |
| `comms_` | Communication link status | `comms_connected`, `comms_signal_strength` |

### Sub-groups under `control_`

The `control_` group has nested sub-groups for related controls:

| Sub-prefix | Domain | Examples |
|---|---|---|
| `control_input_` | Raw rotation axis inputs (-1 to 1) | `control_input_pitch`, `control_input_yaw`, `control_input_roll` |
| `control_autopilot_` | kRPC autopilot state and targets | `control_autopilot`, `control_autopilot_target_pitch`, `control_autopilot_error` |
| `control_sas_` | SAS state and mode | `control_sas`, `control_sas_mode` |
| `control_ui_` | UI-only display settings | `control_ui_speed_mode` |
| `control_deployable_` | Deployable component state | `control_deployable_solar_panels`, `control_deployable_parachutes` |
| `control_translate_` | RCS translation axes (-1 to 1) | `control_translate_forward`, `control_translate_right`, `control_translate_up` |

### VesselCommands naming rule

`VesselCommands` fields mirror `control_*` state fields with the `control_` prefix stripped. This is a mechanical transformation:

- State: `control_throttle` -> Command: `throttle`
- State: `control_autopilot_target_pitch` -> Command: `autopilot_pitch` (target is implicit in a command)
- State: `control_sas` -> Command: `sas`
- State: `control_deployable_solar_panels` -> Command: `deployable_solar_panels`

Commands also include one-shot triggers that have no state equivalent: `stage`.

### Resource naming pattern

Resources follow a three-tier pattern using variant suffixes:

- `resource_liquid_fuel` - current amount (raw telemetry)
- `resource_liquid_fuel_max` - maximum capacity (raw telemetry)
- `resource_liquid_fuel_fraction` - derived property (amount / max, 0.0 to 1.0)

This mirrors the `thrust` / `thrust_available` / `thrust_peak` pattern and the existing `fuel_fraction` property.

### Derived properties

Computed values that combine multiple raw fields are implemented as `@property` methods on `VesselState`, not as stored fields. They use the most natural name without necessarily following group prefixes:

- `weight` (mass * body_gravity)
- `twr` (thrust / weight)
- `max_twr` (thrust_peak / weight)
- `delta_v` (Tsiolkovsky equation)
- `fuel_fraction` (mass ratio)
- `time_to_impact` (altitude / descent rate)
- `in_atmosphere`, `above_atmosphere`, `is_landed`, `is_flying`, etc.

### Deciding which group a new field belongs to

Ask: "What domain concept does this measurement describe?"

- If it's a height above something -> `altitude_`
- If it's how fast the vessel moves -> `speed_`
- If it depends on atmosphere / aerodynamics -> `aero_` (for forces, coefficients, dimensionless numbers like Mach) or `pressure_` (for pressure measurements)
- If it describes the orbit's shape or timing -> `orbit_`
- If it describes the celestial body -> `body_`
- If it's a state that can be commanded -> `control_`
- If it's a consumable amount/capacity -> `resource_`

When a field could fit two groups, prefer the more specific one. Mach number could be `speed_` (it relates to velocity) but it's an aerodynamic quantity that only exists in atmosphere, so `aero_` is more precise.

## Consequences

- **Positive**: Any developer can predict the correct name for a new field by following the rules, without searching existing code.
- **Positive**: IDE autocomplete works naturally: type `orbit_` to see all orbital fields, `control_autopilot_` for all autopilot state.
- **Positive**: The mechanical VesselCommands rule (strip `control_`) eliminates naming debates for new commands.
- **Negative**: Some names are verbose (`body_atmosphere_depth`). We accept this trade-off for self-documentation, with well-known domain abbreviations as a relief valve.
- **Negative**: Adding a new semantic group requires updating this ADR and CLAUDE.md.
