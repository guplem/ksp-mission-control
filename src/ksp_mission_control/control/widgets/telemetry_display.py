"""TelemetryDisplayWidget - displays live vessel telemetry."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static

from ksp_mission_control.control.actions.base import VesselState


class TelemetryDisplayWidget(Static):
    """Displays formatted vessel telemetry text."""

    DEFAULT_CSS = """
    #telemetry-title {
        padding: 0 0 1 0;
    }
    """

    def __init__(self, *, mode: str, id: str | None = None) -> None:  # noqa: A002
        super().__init__(id=id)
        self._mode = mode

    def compose(self) -> ComposeResult:
        yield Static(f"[b]Control View[/b] ({self._mode})", id="telemetry-title")
        yield Static("Connecting...", id="telemetry-content")

    def update_vessel_state(self, state: VesselState) -> None:
        """Format and display the current vessel state."""
        self.query_one("#telemetry-content", Static).update(_format_vessel_state(state))

    def show_error(self, message: str) -> None:
        """Display an error message in place of telemetry."""
        self.query_one("#telemetry-content", Static).update(message)


def _format_vessel_state(state: VesselState) -> str:
    """Format a VesselState into a human-readable string."""
    return "\n".join(
        [
            f"Vessel:          {state.vessel_name}",
            f"Situation:       {state.situation}",
            f"MET:             {state.met:.1f}s",
            "",
            "--- Flight ---",
            f"Altitude (sea):  {state.altitude_sea:.0f} m",
            f"Altitude (srf):  {state.altitude_surface:.0f} m",
            f"Speed (orbit):   {state.orbital_speed:.1f} m/s",
            f"Speed (surface): {state.surface_speed:.1f} m/s",
            f"Vertical speed:  {state.vertical_speed:.1f} m/s",
            f"Latitude:        {state.latitude:.4f}",
            f"Longitude:       {state.longitude:.4f}",
            "",
            "--- Orbit ---",
            f"Body:            {state.body}",
            f"Apoapsis:        {state.apoapsis:.0f} m",
            f"Periapsis:       {state.periapsis:.0f} m",
            f"Inclination:     {state.inclination:.2f} deg",
            f"Eccentricity:    {state.eccentricity:.4f}",
            f"Period:          {state.period:.1f} s",
            "",
            "--- Resources ---",
            f"Electric charge: {state.electric_charge:.1f}",
            f"Liquid fuel:     {state.liquid_fuel:.1f}",
            f"Oxidizer:        {state.oxidizer:.1f}",
            f"Mono propellant: {state.mono_propellant:.1f}",
        ]
    )
