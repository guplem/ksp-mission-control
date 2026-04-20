"""TelemetryDisplayWidget - displays live vessel telemetry."""

from __future__ import annotations

import math

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from ksp_mission_control.control.actions.base import VesselState


class TelemetryDisplayWidget(Static):
    """Displays formatted vessel telemetry in three columns: Flight & Environment, Orbit & Vessel, Controls & Resources."""

    DEFAULT_CSS = """
    #telemetry-header {
        height: auto;
        padding: 0 0 1 0;
    }

    #telemetry-header.error #telemetry-title {
        color: $error;
    }

    #telemetry-title {
        width: 1fr;
    }

    #telemetry-ut {
        width: auto;
    }

    #telemetry-columns {
        height: auto;
    }

    .telemetry-column {
        width: 1fr;
        padding: 0 1;
    }
    """

    def __init__(self, *, id: str | None = None) -> None:  # noqa: A002
        super().__init__(id=id)

    def compose(self) -> ComposeResult:
        with Horizontal(id="telemetry-header"):
            yield Static("[b]Telemetry[/b]", id="telemetry-title")
            yield Static("", id="telemetry-ut")
        with Horizontal(id="telemetry-columns"):
            yield Static("Connecting...", id="telemetry-flight", classes="telemetry-column")
            yield Static("", id="telemetry-orbit", classes="telemetry-column")
            yield Static("", id="telemetry-resources", classes="telemetry-column")

    def update_vessel_state(self, state: VesselState) -> None:
        """Format and display the current vessel state across three columns."""
        header = self.query_one("#telemetry-header", Horizontal)
        if header.has_class("error"):
            header.remove_class("error")
            self.query_one("#telemetry-title", Static).update("[b]Telemetry[/b]")
        self.query_one("#telemetry-ut", Static).update(f"UT: {_format_time(state.universal_time)}")
        self.query_one("#telemetry-flight", Static).update(_format_flight(state))
        self.query_one("#telemetry-orbit", Static).update(_format_orbit(state))
        self.query_one("#telemetry-resources", Static).update(_format_resources(state))

    def show_error(self, message: str) -> None:
        """Display an error message in the title bar, keeping stale telemetry visible."""
        header = self.query_one("#telemetry-header", Horizontal)
        self.query_one("#telemetry-title", Static).update(message)
        header.add_class("error")


def _format_altitude(meters: float) -> str:
    """Format altitude/distance with appropriate unit (m or km)."""
    if abs(meters) >= 100_000:
        return f"{meters / 1000:.1f} km"
    return f"{meters:.0f} m"


def _format_time(seconds: float) -> str:
    """Format seconds into a human-readable duration."""
    if seconds <= 0 or seconds == float("inf"):
        return "N/A"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins:02d}m {secs:02d}s"


def _magnitude(vector: tuple[float, float, float]) -> float:
    """Compute the magnitude of a 3D vector."""
    return math.sqrt(vector[0] ** 2 + vector[1] ** 2 + vector[2] ** 2)


def _format_force(newtons: float) -> str:
    """Format force in N or kN."""
    if newtons >= 1000:
        return f"{newtons / 1000:.1f} kN"
    return f"{newtons:.1f} N"


def _format_mass(kg: float) -> str:
    """Format mass in kg or t."""
    if kg >= 1000:
        return f"{kg / 1000:.2f} t"
    return f"{kg:.1f} kg"


def _format_stage(stage_current: int, stage_max: int) -> str:
    """Format staging as 'fired/total fired'.

    KSP's current_stage is the *next* stage to fire (counts down),
    so stages_fired = stage_max - stage_current + 1 and total = stage_max + 1.
    """
    total = stage_max + 1
    stages_fired = max(0, stage_max - stage_current + 1)
    return f"{stages_fired}/{total} fired"


def _format_flight(state: VesselState) -> str:
    return "\n".join(
        [
            "[b]Overview[/b]",
            f"Vessel:          {state.name}",
            f"Situation:       {state.situation.display_name}",
            f"MET:             {_format_time(state.met)}",
            f"G-force:         {state.g_force:.2f} g",
            "",
            "[b]Altitude[/b]",
            f"Surface:         {_format_altitude(state.altitude_surface)}",
            f"Sea level:       {_format_altitude(state.altitude_sea)}",
            f"Time to impact:  {_format_time(state.altitude_time_to_impact)}",
            "",
            "[b]Speed[/b]",
            f"Vertical:        {state.speed_vertical:+.1f} m/s",
            f"Horizontal:      {state.speed_horizontal:.1f} m/s",
            f"Surface:         {state.speed_surface:.1f} m/s",
            f"Orbital:         {state.speed_orbital:.1f} m/s",
            "",
            "[b]Position[/b]",
            f"Body:            {state.body_name}",
            f"Latitude:        {state.position_latitude:.4f} deg",
            f"Longitude:       {state.position_longitude:.4f} deg",
            "",
            "[b]Atmosphere[/b]",
            f"In atmosphere:   {'Yes' if state.in_atmosphere else 'No'}",
            f"Dynamic press.:  {state.pressure_dynamic / 1000:.2f} kPa",
            f"Static press.:   {state.pressure_static / 1000:.2f} kPa",
            f"Mach:            {state.aero_mach:.2f}",
            f"AoA:             {state.aero_angle_of_attack:.1f} deg",
            f"Terminal vel.:   {state.aero_terminal_velocity:.1f} m/s",
            f"Drag:            {_format_force(_magnitude(state.aero_drag))}",
            f"Lift:            {_format_force(_magnitude(state.aero_lift))}",
        ]
    )


def _on_off(value: bool) -> str:
    return "ON" if value else "OFF"


def _format_orbit(state: VesselState) -> str:
    return "\n".join(
        [
            "[b]Orbit[/b]",
            f"Apoapsis:        {_format_altitude(state.orbit_apoapsis)}",
            f"T to apoapsis:   {_format_time(state.orbit_apoapsis_time_to)}",
            f"Periapsis:       {_format_altitude(state.orbit_periapsis)}",
            f"T to periapsis:  {_format_time(state.orbit_periapsis_time_to)}",
            f"Inclination:     {state.orbit_inclination:.2f} deg",
            f"Eccentricity:    {state.orbit_eccentricity:.4f}",
            f"Period:          {_format_time(state.orbit_period)}",
            "",
            "[b]Orientation[/b]",
            f"Pitch:           {state.orientation_pitch:.1f} deg",
            f"Heading:         {state.orientation_heading:.1f} deg",
            f"Roll:            {state.orientation_roll:.1f} deg",
            "",
            "[b]Propulsion[/b]",
            f"TWR:             {state.twr:.2f} / {state.max_twr:.2f}",
            f"Delta-v:         {state.delta_v:.0f} m/s",
            f"Thrust:          {_format_force(state.thrust)} / {_format_force(state.thrust_peak)}",
            f"Mass:            {_format_mass(state.mass)}",
            f"Isp:             {state.engine_impulse_specific:.1f} s",
            f"Fuel fraction:   {state.fuel_fraction * 100:.1f}%",
            f"Flameouts:       {state.engine_flameout_count}",
            "",
            "[b]Comms[/b]",
            f"Connected:       {_on_off(state.comms_connected)}",
            f"Signal:          {state.comms_signal_strength * 100:.0f}%",
        ]
    )


def _format_resource(amount: float, fraction: float) -> str:
    """Format a resource as 'amount units (percent%)'."""
    return f"{amount:.1f} ({fraction * 100:.0f}%)"


def _format_resources(state: VesselState) -> str:
    return "\n".join(
        [
            "[b]Resources[/b]",
            f"Electric charge: {_format_resource(state.resource_electric_charge, state.resource_electric_charge_fraction)}",
            f"Liquid fuel:     {_format_resource(state.resource_liquid_fuel, state.resource_liquid_fuel_fraction)}",
            f"Oxidizer:        {_format_resource(state.resource_oxidizer, state.resource_oxidizer_fraction)}",
            f"Mono propellant: {_format_resource(state.resource_mono_propellant, state.resource_mono_propellant_fraction)}",
            "",
            "[b]Controls[/b]",
            f"Throttle:        {state.control_throttle * 100:.0f}%",
            f"Stage:           {_format_stage(state.stage_current, state.stage_max)}",
            f"SAS:             {_on_off(state.control_sas)}",
            f"SAS mode:        {state.control_sas_mode.display_name if state.control_sas_mode is not None else '-'}",
            f"RCS:             {_on_off(state.control_rcs)}",
            "",
            "[b]Toggles[/b]",
            f"Gear:            {_on_off(state.control_gear)}",
            f"Legs:            {_on_off(state.control_legs)}",
            f"Brakes:          {_on_off(state.control_brakes)}",
            f"Lights:          {_on_off(state.control_lights)}",
            f"Abort:           {_on_off(state.control_abort)}",
            "",
            "[b]Inputs[/b]",
            f"Pitch:           {state.control_input_pitch:+.2f}",
            f"Yaw:             {state.control_input_yaw:+.2f}",
            f"Roll:            {state.control_input_roll:+.2f}",
            "",
            "[b]Deployables[/b]",
            f"Parachutes:      {_on_off(state.control_deployable_parachutes)}",
            f"Solar panels:    {_on_off(state.control_deployable_solar_panels)}",
            f"Antennas:        {_on_off(state.control_deployable_antennas)}",
            f"Radiators:       {_on_off(state.control_deployable_radiators)}",
            f"Cargo bays:      {_on_off(state.control_deployable_cargo_bays)}",
            f"Intakes:         {_on_off(state.control_deployable_intakes)}",
        ]
    )
