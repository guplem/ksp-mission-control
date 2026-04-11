"""Control screen - barebones debug view showing raw kRPC data."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header, Static
from textual import work


class ControlScreen(Screen[None]):
    """Debug screen that dumps raw kRPC telemetry to verify data reception."""

    CSS_PATH = "style.tcss"

    BINDINGS = [
        ("escape", "go_back", "Back to Setup"),
        ("q", "app.quit", "Quit"),
    ]

    def __init__(self, demo: bool = False) -> None:
        super().__init__()
        self._demo = demo
        self._conn: object | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        mode = "DEMO" if self._demo else "LIVE"
        yield Static(f"[b]Debug View[/b] ({mode})\nConnecting...", id="debug-output")
        yield Footer()

    def on_mount(self) -> None:
        if self._demo:
            self._start_demo_polling()
        else:
            self._connect_and_poll()

    @work(thread=True)
    def _connect_and_poll(self) -> None:
        import krpc  # noqa: PLC0415
        import time

        try:
            self._conn = krpc.connect(name="KSP-MC Debug")
            conn = self._conn
        except Exception as exc:
            self.app.call_from_thread(self._update_output, f"Connection failed: {exc}")
            return

        while self.is_current:
            try:
                vessel = conn.space_center.active_vessel  # type: ignore[union-attr]
                flight = vessel.flight(vessel.orbit.body.reference_frame)
                orbit = vessel.orbit

                lines = [
                    f"[b]Debug View (LIVE)[/b]",
                    "",
                    f"Vessel:          {vessel.name}",
                    f"Situation:       {vessel.situation}",
                    f"MET:             {vessel.met:.1f}s",
                    "",
                    "--- Flight ---",
                    f"Altitude (sea):  {flight.mean_altitude:.0f} m",
                    f"Altitude (srf):  {flight.surface_altitude:.0f} m",
                    f"Speed (orbit):   {orbit.speed:.1f} m/s",
                    f"Speed (surface): {flight.speed:.1f} m/s",
                    f"Vertical speed:  {flight.vertical_speed:.1f} m/s",
                    f"Latitude:        {flight.latitude:.4f}",
                    f"Longitude:       {flight.longitude:.4f}",
                    "",
                    "--- Orbit ---",
                    f"Body:            {orbit.body.name}",
                    f"Apoapsis:        {orbit.apoapsis_altitude:.0f} m",
                    f"Periapsis:       {orbit.periapsis_altitude:.0f} m",
                    f"Inclination:     {orbit.inclination:.2f} deg",
                    f"Eccentricity:    {orbit.eccentricity:.4f}",
                    f"Period:          {orbit.period:.1f} s",
                    "",
                    "--- Resources ---",
                    f"Electric charge: {vessel.resources.amount('ElectricCharge'):.1f}",
                    f"Liquid fuel:     {vessel.resources.amount('LiquidFuel'):.1f}",
                    f"Oxidizer:        {vessel.resources.amount('Oxidizer'):.1f}",
                    f"Mono propellant: {vessel.resources.amount('MonoPropellant'):.1f}",
                ]
                self.app.call_from_thread(self._update_output, "\n".join(lines))
            except Exception as exc:
                self.app.call_from_thread(self._update_output, f"Error reading data: {exc}")
            time.sleep(0.5)

    def _start_demo_polling(self) -> None:
        from ksp_mission_control.control.demo.provider import generate_demo_telemetry

        self._demo_tick = 0

        def tick() -> None:
            self._demo_tick += 1
            self._update_output(generate_demo_telemetry(self._demo_tick))

        self.set_interval(0.5, tick)

    def _update_output(self, text: str) -> None:
        self.query_one("#debug-output", Static).update(text)

    def action_go_back(self) -> None:
        """Return to the setup screen."""
        if self._conn is not None:
            try:
                self._conn.close()  # type: ignore[union-attr]
            except Exception:
                pass
        self.app.pop_screen()
