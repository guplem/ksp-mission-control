"""Control screen - live telemetry and action execution."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import cast

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from ksp_mission_control.control.actions.base import VesselControls, VesselState
from ksp_mission_control.control.actions.runner import ActionRunner, RunnerSnapshot
from ksp_mission_control.control.widgets.action_list import ActionListWidget
from ksp_mission_control.setup.checks import KRPC_DEFAULT_RPC_PORT, KRPC_DEFAULT_STREAM_PORT
from ksp_mission_control.setup.kRPC_comms.parser import (
    KrpcSettingsParseError,
    parse_krpc_settings,
)


class ControlScreen(Screen[None]):
    """Control screen with live telemetry and vessel action execution."""

    CSS_PATH = "style.tcss"

    BINDINGS = [
        ("escape", "go_back", "Back to Setup"),
        ("q", "app.quit", "Quit"),
        ("a", "abort_action", "Abort Action"),
    ]

    def __init__(self, demo: bool = False) -> None:
        super().__init__()
        self._demo = demo
        self._conn: object | None = None
        self._runner = ActionRunner()

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="control-split"):
            mode = "DEMO" if self._demo else "LIVE"
            yield Static(f"[b]Control View[/b] ({mode})\nConnecting...", id="debug-output")
            yield ActionListWidget(id="action-list")
        yield Footer()

    def on_mount(self) -> None:
        if self._demo:
            self._start_demo_polling()
        else:
            self._connect_and_poll()

    @work(thread=True)
    def _connect_and_poll(self) -> None:
        import time  # noqa: PLC0415

        import krpc  # noqa: PLC0415

        try:
            host, rpc_port, stream_port = self._resolve_connection()
            self._conn = krpc.connect(
                name="KSP-MC Control",
                address=host,
                rpc_port=rpc_port,
                stream_port=stream_port,
            )
            conn = self._conn
        except Exception as exc:
            self.app.call_from_thread(self._update_output, f"Connection failed: {exc}")
            return

        while self.is_current:
            try:
                vessel_state = self._read_vessel_state(conn)
                controls = self._runner.step(vessel_state, dt=0.5)
                self._apply_controls(conn, controls)
                text = _format_vessel_state(vessel_state, "LIVE")
                snapshot = self._runner.snapshot()
                self.app.call_from_thread(self._update_ui, text, snapshot)
            except Exception as exc:
                self.app.call_from_thread(self._update_output, f"Error reading data: {exc}")
            time.sleep(0.5)

    def _start_demo_polling(self) -> None:
        from ksp_mission_control.control.demo.provider import generate_demo_vessel_state

        self._demo_tick = 0

        def tick() -> None:
            self._demo_tick += 1
            vessel_state = generate_demo_vessel_state(self._demo_tick)
            self._runner.step(vessel_state, dt=0.5)  # controls discarded in demo
            text = _format_vessel_state(vessel_state, "DEMO")
            snapshot = self._runner.snapshot()
            self._update_ui(text, snapshot)

        self.set_interval(0.5, tick)

    def _read_vessel_state(self, conn: object) -> VesselState:
        """Read current vessel telemetry from kRPC into a VesselState."""
        vessel = conn.space_center.active_vessel  # type: ignore[attr-defined]
        flight = vessel.flight(vessel.orbit.body.reference_frame)
        orbit = vessel.orbit
        return VesselState(
            altitude_sea=flight.mean_altitude,
            altitude_surface=flight.surface_altitude,
            vertical_speed=flight.vertical_speed,
            surface_speed=flight.speed,
            orbital_speed=orbit.speed,
            apoapsis=orbit.apoapsis_altitude,
            periapsis=orbit.periapsis_altitude,
            met=vessel.met,
            vessel_name=vessel.name,
            situation=str(vessel.situation),
            body=orbit.body.name,
            latitude=flight.latitude,
            longitude=flight.longitude,
            inclination=orbit.inclination,
            eccentricity=orbit.eccentricity,
            period=orbit.period,
            electric_charge=vessel.resources.amount("ElectricCharge"),
            liquid_fuel=vessel.resources.amount("LiquidFuel"),
            oxidizer=vessel.resources.amount("Oxidizer"),
            mono_propellant=vessel.resources.amount("MonoPropellant"),
        )

    def _apply_controls(self, conn: object, controls: VesselControls) -> None:
        """Apply non-None control values to the vessel via kRPC."""
        vessel = conn.space_center.active_vessel  # type: ignore[attr-defined]
        vc = vessel.control
        if controls.throttle is not None:
            vc.throttle = controls.throttle
        if controls.sas is not None:
            vc.sas = controls.sas
        if controls.rcs is not None:
            vc.rcs = controls.rcs
        if controls.stage is not None and controls.stage:
            vc.activate_next_stage()

    def _update_ui(self, text: str, snapshot: RunnerSnapshot) -> None:
        """Update both the telemetry display and action list status."""
        self._update_output(text)
        action_list = self.query_one("#action-list", ActionListWidget)
        action_list.update_running(snapshot.action_id)

    def _update_output(self, text: str) -> None:
        self.query_one("#debug-output", Static).update(text)

    def on_action_list_widget_selected(self, event: ActionListWidget.Selected) -> None:
        """Start the selected action with default parameters."""
        try:
            self._runner.start_action(event.action)
        except ValueError as exc:
            self.notify(str(exc), severity="error")

    def action_abort_action(self) -> None:
        """Abort the currently running action."""
        controls = self._runner.abort()
        # Apply cleanup controls in live mode
        if not self._demo and self._conn is not None:
            with contextlib.suppress(Exception):
                self._apply_controls(self._conn, controls)
        action_list = self.query_one("#action-list", ActionListWidget)
        action_list.update_running(None)

    def _resolve_connection(self) -> tuple[str, int, int]:
        """Read connection details from kRPC settings, falling back to defaults."""
        from ksp_mission_control.app import MissionControlApp  # noqa: PLC0415

        stored_path = cast(MissionControlApp, self.app).config_manager.config.ksp_path
        if stored_path is not None:
            try:
                settings = parse_krpc_settings(Path(stored_path))
                return settings.address, settings.rpc_port, settings.stream_port
            except KrpcSettingsParseError:
                pass
        return "127.0.0.1", KRPC_DEFAULT_RPC_PORT, KRPC_DEFAULT_STREAM_PORT

    def action_go_back(self) -> None:
        """Return to the setup screen."""
        # Abort any running action
        if self._runner.snapshot().action_id is not None:
            self.action_abort_action()
        if self._conn is not None:
            with contextlib.suppress(Exception):
                self._conn.close()  # type: ignore[attr-defined]
        self.app.pop_screen()


def _format_vessel_state(state: VesselState, mode: str) -> str:
    """Format a VesselState into a human-readable debug string."""
    return "\n".join([
        f"[b]Control View ({mode})[/b]",
        "",
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
    ])
