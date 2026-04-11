"""Control screen - live telemetry and action execution."""

from __future__ import annotations

from typing import cast

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Footer, Header

from ksp_mission_control.control.actions.base import VesselState
from ksp_mission_control.control.actions.runner import RunnerSnapshot
from ksp_mission_control.control.session import ControlSession
from ksp_mission_control.control.widgets.action_list import ActionListWidget
from ksp_mission_control.control.widgets.telemetry_display import TelemetryDisplayWidget


class ControlScreen(Screen[None]):
    """Control screen with live telemetry and vessel action execution.

    This screen is thin UI glue. Business logic (poll loop, connection
    lifecycle, action orchestration) lives in :class:`ControlSession`.
    """

    CSS_PATH = "style.tcss"

    BINDINGS = [
        ("escape", "go_back", "Back to Setup"),
        ("q", "app.quit", "Quit"),
        ("a", "abort_action", "Abort Action"),
    ]

    def __init__(self, demo: bool = False) -> None:
        super().__init__()
        self._demo = demo
        self._session: ControlSession | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        mode = "DEMO" if self._demo else "LIVE"
        with Horizontal(id="control-split"):
            yield TelemetryDisplayWidget(mode=mode, id="telemetry-display")
            yield ActionListWidget(id="action-list")
        yield Footer()

    def on_mount(self) -> None:
        from ksp_mission_control.app import MissionControlApp  # noqa: PLC0415

        config_manager = cast(MissionControlApp, self.app).config_manager
        self._session = ControlSession(
            demo=self._demo,
            on_update=lambda s, r: self.app.call_from_thread(self._update_ui, s, r),
            on_error=lambda msg: self.app.call_from_thread(self._show_error, msg),
            config_manager=config_manager,
        )

        if self._demo:
            self.set_interval(0.5, self._session.demo_tick)
        else:
            self._start_live_polling()

    @work(thread=True)
    def _start_live_polling(self) -> None:
        """Run the session's blocking poll loop in a worker thread."""
        if self._session is not None:
            self._session.run_poll_loop()

    def _update_ui(self, state: VesselState, runner_state: RunnerSnapshot) -> None:
        """Update both the telemetry display and action list status."""
        self.query_one("#telemetry-display", TelemetryDisplayWidget).update_vessel_state(state)
        self.query_one("#action-list", ActionListWidget).update_running(runner_state.action_id)

    def _show_error(self, message: str) -> None:
        self.query_one("#telemetry-display", TelemetryDisplayWidget).show_error(message)

    def on_action_list_widget_selected(self, event: ActionListWidget.Selected) -> None:
        """Start the selected action with default parameters."""
        if self._session is None:
            return
        try:
            self._session.start_action(event.action)
        except ValueError as exc:
            self.notify(str(exc), severity="error")

    def action_abort_action(self) -> None:
        """Abort the currently running action."""
        if self._session is None:
            return
        self._session.abort()
        self.query_one("#action-list", ActionListWidget).update_running(None)

    def _shutdown(self) -> None:
        """Signal the session to stop and clean up."""
        if self._session is not None:
            self._session.shutdown()

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
