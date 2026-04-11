"""Control screen - live telemetry and action execution."""

from __future__ import annotations

import contextlib
import threading
from typing import cast

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Footer, Header

from ksp_mission_control.control.actions.base import VesselState
from ksp_mission_control.control.actions.runner import ActionRunner, RunnerSnapshot
from ksp_mission_control.control.krpc_bridge import apply_controls, read_vessel_state
from ksp_mission_control.control.widgets.action_list import ActionListWidget
from ksp_mission_control.control.widgets.telemetry_display import TelemetryDisplayWidget
from ksp_mission_control.setup.kRPC_comms.parser import resolve_krpc_connection


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
        self._stop_event = threading.Event()

    def compose(self) -> ComposeResult:
        yield Header()
        mode = "DEMO" if self._demo else "LIVE"
        with Horizontal(id="control-split"):
            yield TelemetryDisplayWidget(mode=mode, id="telemetry-display")
            yield ActionListWidget(id="action-list")
        yield Footer()

    def on_mount(self) -> None:
        if self._demo:
            self._start_demo_polling()
        else:
            self._connect_and_poll()

    @work(thread=True)
    def _connect_and_poll(self) -> None:
        import krpc  # noqa: PLC0415

        try:
            from ksp_mission_control.app import MissionControlApp  # noqa: PLC0415

            config_manager = cast(MissionControlApp, self.app).config_manager
            settings = resolve_krpc_connection(config_manager)
            self._conn = krpc.connect(
                name="KSP-MC Control",
                address=settings.address,
                rpc_port=settings.rpc_port,
                stream_port=settings.stream_port,
            )
            conn = self._conn
        except Exception as exc:
            self.app.call_from_thread(self._show_error, f"Connection failed: {exc}")
            return

        while not self._stop_event.is_set():
            try:
                vessel_state = read_vessel_state(conn)
                controls = self._runner.step(vessel_state, dt=0.5)
                apply_controls(conn, controls)
                runner_state = self._runner.snapshot()
                self.app.call_from_thread(self._update_ui, vessel_state, runner_state)
            except Exception as exc:
                self.app.call_from_thread(self._show_error, f"Error reading data: {exc}")
            self._stop_event.wait(0.5)

    def _start_demo_polling(self) -> None:
        from ksp_mission_control.control.demo.provider import generate_demo_vessel_state

        self._demo_tick = 0

        def tick() -> None:
            self._demo_tick += 1
            vessel_state = generate_demo_vessel_state(self._demo_tick)
            self._runner.step(vessel_state, dt=0.5)
            runner_state = self._runner.snapshot()
            self._update_ui(vessel_state, runner_state)

        self.set_interval(0.5, tick)

    def _update_ui(self, state: VesselState, runner_state: RunnerSnapshot) -> None:
        """Update both the telemetry display and action list status."""
        self.query_one("#telemetry-display", TelemetryDisplayWidget).update_vessel_state(state)
        self.query_one("#action-list", ActionListWidget).update_running(runner_state.action_id)

    def _show_error(self, message: str) -> None:
        self.query_one("#telemetry-display", TelemetryDisplayWidget).show_error(message)

    def on_action_list_widget_selected(self, event: ActionListWidget.Selected) -> None:
        """Start the selected action with default parameters."""
        try:
            self._runner.start_action(event.action)
        except ValueError as exc:
            self.notify(str(exc), severity="error")

    def action_abort_action(self) -> None:
        """Abort the currently running action."""
        controls = self._runner.abort()
        if not self._demo and self._conn is not None:
            with contextlib.suppress(Exception):
                apply_controls(self._conn, controls)
        action_list = self.query_one("#action-list", ActionListWidget)
        action_list.update_running(None)

    def _shutdown(self) -> None:
        """Signal the polling thread to stop and close the kRPC connection."""
        self._stop_event.set()
        if self._runner.snapshot().action_id is not None:
            controls = self._runner.abort()
            if not self._demo and self._conn is not None:
                with contextlib.suppress(Exception):
                    apply_controls(self._conn, controls)
        if self._conn is not None:
            with contextlib.suppress(Exception):
                self._conn.close()  # type: ignore[attr-defined]

    def on_screen_suspend(self) -> None:
        """Called when this screen is no longer current (popped or replaced)."""
        self._shutdown()

    def on_unmount(self) -> None:
        """Called when the screen is removed from the DOM (app quit)."""
        self._shutdown()

    def action_go_back(self) -> None:
        """Return to the setup screen."""
        self._shutdown()
        self.app.pop_screen()
