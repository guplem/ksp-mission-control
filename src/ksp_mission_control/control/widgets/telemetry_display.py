"""TelemetryDisplayWidget - displays live vessel telemetry."""

from __future__ import annotations

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

    def __init__(self, *, mode: str, id: str | None = None) -> None:  # noqa: A002
        super().__init__(id=id)
        self._mode = mode

    def compose(self) -> ComposeResult:
        yield Static(f"[b]Control View[/b] ({self._mode})", id="telemetry-title")
        with Horizontal(id="telemetry-columns"):
            yield Static("Connecting...", id="telemetry-flight", classes="telemetry-column")
            yield Static("", id="telemetry-orbit", classes="telemetry-column")
            yield Static("", id="telemetry-resources", classes="telemetry-column")

    def update_vessel_state(self, state: VesselState) -> None:
        """Format and display the current vessel state across three columns."""
        title = self.query_one("#telemetry-title", Static)
        if title.has_class("error"):
            title.update(f"[b]Control View[/b] ({self._mode})")
            title.remove_class("error")
        self.query_one("#telemetry-flight", Static).update(_format_flight(state))
        self.query_one("#telemetry-orbit", Static).update(_format_orbit(state))
        self.query_one("#telemetry-resources", Static).update(_format_resources(state))

    def show_error(self, message: str) -> None:
        """Display an error message in the title bar, keeping stale telemetry visible."""
        title = self.query_one("#telemetry-title", Static)
        title.update(message)
        title.add_class("error")


def _format_flight(state: VesselState) -> str:
    return "\n".join(
        [
            "[b]Overview[/b]",
            f"Vessel:          {state.vessel_name}",
            f"Situation:       {state.situation.split('.')[-1].replace('_', ' ').title()}",
            f"MET:             {state.met:.1f}s",
            "",
            "[b]Flight[/b]",
            f"Altitude (sea):  {state.altitude_sea:.0f} m",
            f"Altitude (srf):  {state.altitude_surface:.0f} m",
            f"Speed (orbit):   {state.orbital_speed:.1f} m/s",
            f"Speed (surface): {state.surface_speed:.1f} m/s",
            f"Vertical speed:  {state.vertical_speed:.1f} m/s",
            f"Latitude:        {state.latitude:.4f}",
            f"Longitude:       {state.longitude:.4f}",
        ]
    )


def _format_orbit(state: VesselState) -> str:
    return "\n".join(
        [
            "[b]Orbit[/b]",
            f"Body:            {state.body}",
            f"Apoapsis:        {state.apoapsis:.0f} m",
            f"Periapsis:       {state.periapsis:.0f} m",
            f"Inclination:     {state.inclination:.2f} deg",
            f"Eccentricity:    {state.eccentricity:.4f}",
            f"Period:          {state.period:.1f} s",
            "",
            "[b]Orientation[/b]",
            f"Pitch:           {state.pitch:.1f} deg",
            f"Heading:         {state.heading:.1f} deg",
            f"Roll:            {state.roll:.1f} deg",
        ]
    )


def _format_resources(state: VesselState) -> str:
    return "\n".join(
        [
            "[b]Resources[/b]",
            f"Electric charge: {state.electric_charge:.1f}",
            f"Liquid fuel:     {state.liquid_fuel:.1f}",
            f"Oxidizer:        {state.oxidizer:.1f}",
            f"Mono propellant: {state.mono_propellant:.1f}",
            "",
            "[b]Configuration[/b]",
            f"Throttle:        {state.throttle * 100:.0f}%",
            f"SAS:             {'ON' if state.sas else 'OFF'}",
            f"SAS mode:        {state.sas_mode.split('.')[-1].replace('_', ' ').title() if state.sas_mode else 'N/A'}",
            f"RCS:             {'ON' if state.rcs else 'OFF'}",
            f"Stage:           {state.current_stage} / {state.max_stages}",
        ]
    )
