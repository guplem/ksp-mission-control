"""Control screen - live telemetry and action execution."""

from __future__ import annotations

from typing import cast

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Footer, Header

from ksp_mission_control.control.actions.base import Action, VesselState
from ksp_mission_control.control.actions.runner import RunnerSnapshot
from ksp_mission_control.control.param_input_modal import ParamInputModal
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
        """Open the parameter dialog for the selected action."""
        if self._session is None:
            return
        action = event.action
        if action.params:
            self.app.push_screen(
                ParamInputModal(action),
                callback=lambda result: self._start_action_with_params(action, result)
                if result is not None
                else None,
            )
        else:
            self._start_action_with_params(action, None)

    def _start_action_with_params(self, action: Action, params: dict[str, float] | None) -> None:
        """Start the action with the given parameters."""
        if self._session is None:
            return
        try:
            self._session.start_action(action, params)
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
        """Called when this screen is no longer current.

        Only shut down when the screen is actually being removed (popped),
        not when a modal is pushed on top. We detect this by checking
        whether the new active screen is a ModalScreen overlay.
        """
        from textual.screen import ModalScreen  # noqa: PLC0415

        if not isinstance(self.app.screen, ModalScreen):
            self._shutdown()

    def on_unmount(self) -> None:
        """Called when the screen is removed from the DOM (app quit)."""
        self._shutdown()

    def action_go_back(self) -> None:
        """Return to the setup screen."""
        self._shutdown()
        self.app.pop_screen()
