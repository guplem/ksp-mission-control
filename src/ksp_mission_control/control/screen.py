"""Control screen - live telemetry and action execution."""

from __future__ import annotations

from typing import cast

from textual import work
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Header

from ksp_mission_control.control.action_picker import ActionPicker
from ksp_mission_control.control.actions.base import Action, LogEntry, VesselCommands, VesselState
from ksp_mission_control.control.actions.flight_plan import FlightPlan
from ksp_mission_control.control.actions.plan_executor import PlanSnapshot
from ksp_mission_control.control.actions.runner import RunnerSnapshot
from ksp_mission_control.control.flight_plan_picker import FlightPlanPicker
from ksp_mission_control.control.param_input_modal import ParamInputModal
from ksp_mission_control.control.plan_failure_dialog import PlanFailureDialog
from ksp_mission_control.control.session import ControlSession
from ksp_mission_control.control.widgets.action_list import ActionListWidget
from ksp_mission_control.control.widgets.command_history import CommandHistoryWidget
from ksp_mission_control.control.widgets.debug_console import DebugConsoleWidget
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
        self._showing_failure_dialog: bool = False

    def compose(self) -> ComposeResult:
        yield Header()
        mode = "DEMO" if self._demo else "LIVE"
        with Container(id="control-grid"):
            yield TelemetryDisplayWidget(mode=mode, id="telemetry-display")
            yield ActionListWidget(id="action-list")
            yield DebugConsoleWidget(id="debug-console")
            yield CommandHistoryWidget(id="command-history")
        yield Footer()

    def on_mount(self) -> None:
        from ksp_mission_control.app import MissionControlApp  # noqa: PLC0415

        config_manager = cast(MissionControlApp, self.app).config_manager
        self._session = ControlSession(
            demo=self._demo,
            on_update=lambda state, snapshot, commands, applied_fields, logs, plan_snap: (
                self.app.call_from_thread(
                    self._update_ui, state, snapshot, commands, applied_fields, logs, plan_snap
                )
            ),
            on_error=lambda message: self.app.call_from_thread(self._show_error, message),
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

    def _update_ui(
        self,
        state: VesselState,
        runner_state: RunnerSnapshot,
        commands: VesselCommands,
        applied_fields: frozenset[str],
        logs: list[LogEntry],
        plan_snap: PlanSnapshot,
    ) -> None:
        """Update telemetry, action list, command history, and debug console."""
        self.query_one("#telemetry-display", TelemetryDisplayWidget).update_vessel_state(state)
        action_list = self.query_one("#action-list", ActionListWidget)
        action_list.update_running(runner_state.action_id)
        action_list.update_plan(plan_snap)
        self.query_one("#command-history", CommandHistoryWidget).record_commands(
            commands,
            applied_fields=applied_fields,
            action_label=runner_state.action_label,
            met=state.met,
            status=runner_state.status,
        )
        self.query_one("#debug-console", DebugConsoleWidget).append_logs(logs, met=state.met)

        # Show failure dialog if plan is paused on failure
        if (
            self._session is not None
            and self._session.paused_on_failure
            and not self._showing_failure_dialog
        ):
            self._showing_failure_dialog = True
            self.app.push_screen(
                PlanFailureDialog(plan_snap),
                callback=self._handle_failure_dialog,
            )

    def _handle_failure_dialog(self, continue_plan: bool | None) -> None:
        """Handle the result of the failure confirmation dialog."""
        self._showing_failure_dialog = False
        if self._session is None:
            return
        if continue_plan:
            try:
                self._session.continue_plan()
            except ValueError as exc:
                self.notify(str(exc), severity="error")
        else:
            self._session.abort_plan()
            self.query_one("#action-list", ActionListWidget).update_running(None)

    def _show_error(self, message: str) -> None:
        self.query_one("#telemetry-display", TelemetryDisplayWidget).show_error(message)

    def on_action_list_widget_run_action_requested(
        self, event: ActionListWidget.RunActionRequested
    ) -> None:
        """Open the action picker dialog."""
        self.app.push_screen(
            ActionPicker(),
            callback=self._handle_action_picked,
        )

    def _handle_action_picked(self, action: Action | None) -> None:
        """Handle the selected action from the picker."""
        if action is None or self._session is None:
            return
        if action.params:
            self.app.push_screen(
                ParamInputModal(action),
                callback=lambda result: (
                    self._handle_action_with_params(action, result) if result is not None else None
                ),
            )
        else:
            self._handle_action_with_params(action, None)

    def on_action_list_widget_load_plan_requested(
        self, event: ActionListWidget.LoadPlanRequested
    ) -> None:
        """Open the flight plan picker."""
        self.app.push_screen(
            FlightPlanPicker(),
            callback=self._handle_plan_selected,
        )

    def _handle_plan_selected(self, plan: FlightPlan | None) -> None:
        """Start the selected flight plan."""
        if plan is None or self._session is None:
            return
        try:
            self._session.start_plan(plan)
        except ValueError as exc:
            self.notify(str(exc), severity="error")

    def _handle_action_with_params(self, action: Action, params: dict[str, float] | None) -> None:
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
