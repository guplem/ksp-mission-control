"""TelemetryDisplayWidget - displays live vessel telemetry."""

from __future__ import annotations

import math

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from ksp_mission_control.control.actions.base import VesselState


class TelemetryDisplayWidget(Static):
    """Displays formatted vessel telemetry in three columns: Flight, Orbit, Resources."""

    DEFAULT_CSS = """
    #telemetry-title {
        padding: 0 0 1 0;
    }

    #telemetry-title.error {
        color: $error;
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
        yield Static("[b]Control View[/b]", id="telemetry-title")
        with Horizontal(id="telemetry-columns"):
            yield Static("Connecting...", id="telemetry-flight", classes="telemetry-column")
            yield Static("", id="telemetry-orbit", classes="telemetry-column")
            yield Static("", id="telemetry-resources", classes="telemetry-column")

    def update_vessel_state(self, state: VesselState) -> None:
        """Format and display the current vessel state across three columns."""
        title = self.query_one("#telemetry-title", Static)
        if title.has_class("error"):
            title.update("[b]Control View[/b]")
            title.remove_class("error")
        self.query_one("#telemetry-flight", Static).update(_format_flight(state))
        self.query_one("#telemetry-orbit", Static).update(_format_orbit(state))
        self.query_one("#telemetry-resources", Static).update(_format_resources(state))

    def show_error(self, message: str) -> None:
        """Display an error message in the title bar, keeping stale telemetry visible."""
        title = self.query_one("#telemetry-title", Static)
        title.update(message)
        title.add_class("error")


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


def _format_flight(state: VesselState) -> str:
    return "\n".join(
        [
            "[b]Overview[/b]",
            f"Vessel:          {state.name}",
            f"Situation:       {state.situation.display_name}",
            f"MET:             {_format_time(state.met)}",
            "",
            "[b]Flight[/b]",
            f"Altitude (srf):  {_format_altitude(state.altitude_surface)}",
            f"Altitude (sea):  {_format_altitude(state.altitude_sea)}",
            f"Vertical speed:  {state.speed_vertical:+.1f} m/s",
            f"Surface speed:   {state.speed_surface:.1f} m/s",
            f"Orbital speed:   {state.speed_orbital:.1f} m/s",
            f"G-force:         {state.g_force:.2f} g",
            "",
            "[b]Position[/b]",
            f"Body:            {state.body_name}",
            f"Latitude:        {state.position_latitude:.4f} deg",
            f"Longitude:       {state.position_longitude:.4f} deg",
            "",
            "[b]Atmosphere[/b]",
            f"Dynamic press.:  {state.pressure_dynamic / 1000:.2f} kPa",
            f"Static press.:   {state.pressure_static / 1000:.2f} kPa",
            f"Drag:            {_format_force(_magnitude(state.aero_drag))}",
            f"Lift:            {_format_force(_magnitude(state.aero_lift))}",
        ]
    )


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
            "[b]Control Inputs[/b]",
            f"Pitch input:     {state.control_input_pitch:+.2f}",
            f"Yaw input:       {state.control_input_yaw:+.2f}",
            f"Roll input:      {state.control_input_roll:+.2f}",
            "",
            "[b]Propulsion[/b]",
            f"TWR:             {state.twr:.2f} / {state.max_twr:.2f}",
            f"Delta-v:         {state.delta_v:.0f} m/s",
            f"Thrust:          {_format_force(state.thrust)} / {_format_force(state.thrust_peak)}",
            f"Mass:            {_format_mass(state.mass)}",
            f"Isp:             {state.engine_impulse_specific:.1f} s",
            f"Fuel fraction:   {state.fuel_fraction * 100:.1f}%",
            f"Flameouts:       {state.engine_flameout_count}",
        ]
    )


def _on_off(value: bool) -> str:
    return "ON" if value else "OFF"


def _format_resources(state: VesselState) -> str:
    return "\n".join(
        [
            "[b]Resources[/b]",
            f"Electric charge: {state.resource_electric_charge:.1f}",
            f"Liquid fuel:     {state.resource_liquid_fuel:.1f}",
            f"Oxidizer:        {state.resource_oxidizer:.1f}",
            f"Mono propellant: {state.resource_mono_propellant:.1f}",
            "",
            "[b]Configuration[/b]",
            f"Throttle:        {state.control_throttle * 100:.0f}%",
            f"Stage:           {state.stage_current} / {state.stage_max}",
            f"SAS:             {_on_off(state.control_sas)}",
            f"SAS mode:        {state.control_sas_mode.display_name if state.control_sas_mode is not None else '-'}",
            f"RCS:             {_on_off(state.control_rcs)}",
            f"Speed mode:      {state.control_ui_speed_mode.display_name}",
            f"Gear:            {_on_off(state.control_gear)}",
            f"Legs:            {_on_off(state.control_legs)}",
            f"Brakes:          {_on_off(state.control_brakes)}",
            f"Lights:          {_on_off(state.control_lights)}",
            f"Abort:           {_on_off(state.control_abort)}",
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
