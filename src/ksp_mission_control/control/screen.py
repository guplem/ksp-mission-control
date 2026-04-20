"""Control screen - live telemetry and action execution."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import cast
from xml.etree.ElementTree import Element, SubElement, indent, tostring

from textual import work
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header

from ksp_mission_control.control.action_picker import ActionPicker
from ksp_mission_control.control.actions.base import (
    Action,
    LogEntry,
    VesselCommands,
    VesselSituation,
    VesselState,
)
from ksp_mission_control.control.actions.flight_plan import FlightPlan
from ksp_mission_control.control.actions.plan_executor import PlanSnapshot
from ksp_mission_control.control.actions.runner import RunnerSnapshot
from ksp_mission_control.control.confirm_exit_dialog import ConfirmExitDialog
from ksp_mission_control.control.flight_plan_picker import FlightPlanPicker
from ksp_mission_control.control.formatting import format_met
from ksp_mission_control.control.manual_command_dialog import ManualCommandDialog
from ksp_mission_control.control.param_input_modal import ParamInputModal
from ksp_mission_control.control.plan_failure_dialog import PlanFailureDialog
from ksp_mission_control.control.session import ControlSession
from ksp_mission_control.control.tick_record import TickRecord
from ksp_mission_control.control.widgets.command_history import (
    CommandHistoryWidget,
    format_field_value,
)
from ksp_mission_control.control.widgets.control_panel import ControlPanelWidget
from ksp_mission_control.control.widgets.log_registry import LogRegistryWidget
from ksp_mission_control.control.widgets.telemetry_display import TelemetryDisplayWidget


class ViewMode(Enum):
    """Layout modes for the control screen."""

    SPLIT = "split"
    LOGS = "logs"
    TELEMETRY = "telemetry"


_VIEW_MODE_CYCLE = [ViewMode.SPLIT, ViewMode.LOGS, ViewMode.TELEMETRY]

_MAX_TICK_HISTORY = 10_000
"""Maximum number of tick records to keep for clipboard export."""


class ControlScreen(Screen[None]):
    """Control screen with live telemetry and vessel action execution.

    This screen is thin UI glue. Business logic (poll loop, connection
    lifecycle, action orchestration) lives in :class:`ControlSession`.
    """

    AUTO_FOCUS = ""
    CSS_PATH = "style.tcss"

    BINDINGS = [
        ("escape", "clear", "Clear"),
        ("c", "cancel", "Cancel"),
        ("a", "abort", "Abort!"),
        ("s", "save_logs", "Save Logs"),
        ("v", "cycle_view", "Cycle View"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._session: ControlSession | None = None
        self._view_mode: ViewMode = ViewMode.SPLIT
        self._showing_failure_dialog: bool = False
        self._tick_history: list[TickRecord] = []
        self._tick_counter: int = 0

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="control-grid"):
            with Container(id="content-area"):
                yield TelemetryDisplayWidget(id="telemetry-display")
                yield LogRegistryWidget(id="log-registry")
            with Vertical(id="sidebar"):
                yield ControlPanelWidget(id="control-panel")
                yield CommandHistoryWidget(id="command-history")
        yield Footer()

    def on_mount(self) -> None:
        from ksp_mission_control.app import MissionControlApp  # noqa: PLC0415

        config_manager = cast(MissionControlApp, self.app).config_manager
        self._session = ControlSession(
            on_update=lambda state, snapshot, commands, applied_fields, logs, plan_snap: self.app.call_from_thread(
                self._update_ui, state, snapshot, commands, applied_fields, logs, plan_snap
            ),
            on_error=lambda message: self.app.call_from_thread(self._show_error, message),
            config_manager=config_manager,
        )
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
        """Update telemetry, control panel, command history, and log registry."""
        self._tick_counter += 1
        self._tick_history.append(
            TickRecord(
                tick_number=self._tick_counter,
                met=state.met,
                state=state,
                action_label=runner_state.action_label,
                action_status=runner_state.status,
                logs=list(logs),
                commands=commands,
                applied_fields=applied_fields,
            )
        )
        if len(self._tick_history) > _MAX_TICK_HISTORY:
            self._tick_history.pop(0)

        self.query_one("#telemetry-display", TelemetryDisplayWidget).update_vessel_state(state)
        control_panel = self.query_one("#control-panel", ControlPanelWidget)
        control_panel.update_running(runner_state.action_id)
        control_panel.update_plan(plan_snap)
        self.query_one("#command-history", CommandHistoryWidget).record_commands(
            commands,
            applied_fields=applied_fields,
            action_label=runner_state.action_label,
            met=state.met,
            tick_id=self._tick_counter,
            status=runner_state.status,
        )
        self.query_one("#log-registry", LogRegistryWidget).append_logs(logs, met=state.met, tick_id=self._tick_counter)

        # Show failure dialog if plan is paused on failure
        if self._session is not None and self._session.paused_on_failure and not self._showing_failure_dialog:
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
            self.query_one("#control-panel", ControlPanelWidget).update_running(None)

    def _show_error(self, message: str) -> None:
        self.query_one("#telemetry-display", TelemetryDisplayWidget).show_error(message)

    def on_command_history_widget_tick_changed(self, event: CommandHistoryWidget.TickChanged) -> None:
        """Highlight logs matching the previewed command, or clear highlighting."""
        console = self.query_one("#log-registry", LogRegistryWidget)
        console.set_following(event.following)
        console.highlight_tick(event.tick_id)

    def on_control_panel_widget_run_action_requested(self, event: ControlPanelWidget.RunActionRequested) -> None:
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
                callback=lambda result: self._handle_action_with_params(action, result) if result is not None else None,
            )
        else:
            self._handle_action_with_params(action, None)

    def on_control_panel_widget_load_plan_requested(self, event: ControlPanelWidget.LoadPlanRequested) -> None:
        """Open the flight plan picker."""
        self.app.push_screen(
            FlightPlanPicker(),
            callback=self._handle_plan_selected,
        )

    def on_control_panel_widget_manual_command_requested(self, event: ControlPanelWidget.ManualCommandRequested) -> None:
        """Open the manual command dialog."""
        self.app.push_screen(
            ManualCommandDialog(),
            callback=self._handle_manual_command,
        )

    def _handle_plan_selected(self, plan: FlightPlan | None) -> None:
        """Start the selected flight plan."""
        if plan is None or self._session is None:
            return
        try:
            self._session.start_plan(plan)
        except ValueError as exc:
            self.notify(str(exc), severity="error")

    def _handle_manual_command(self, commands: VesselCommands | None) -> None:
        """Queue the manual command for the next poll tick."""
        if commands is None or self._session is None:
            return
        self._session.send_manual_command(commands)

    def _handle_action_with_params(self, action: Action, params: dict[str, float] | None) -> None:
        """Start the action with the given parameters."""
        if self._session is None:
            return
        try:
            self._session.start_action(action, params)
        except ValueError as exc:
            self.notify(str(exc), severity="error")

    def action_cancel(self) -> None:
        """Cancel the currently running action or flight plan."""
        if self._session is None:
            return
        if self._session.snapshot().action_id is None:
            self.notify("Nothing to cancel", severity="warning", timeout=1.5)
            return
        self._session.abort()
        self.query_one("#control-panel", ControlPanelWidget).update_running(None)
        self.notify("Cancelled", timeout=1.5)

    def action_abort(self) -> None:
        """Trigger the in-game abort action group."""
        if self._session is None:
            return
        last_state = self._tick_history[-1].state if self._tick_history else None
        if last_state is not None and last_state.situation == VesselSituation.PRE_LAUNCH:
            self.notify("Cannot abort before launch", severity="warning", timeout=1.5)
            return
        self._session.send_manual_command(VesselCommands(abort=True))
        self.notify("ABORT!", severity="error", timeout=3)

    def action_save_logs(self) -> None:
        """Save the full tick-by-tick log to file and copy the path to clipboard."""
        if not self._tick_history:
            self.notify("No ticks recorded yet", severity="warning")
            return
        text = _format_tick_history(self._tick_history)

        log_dir = Path("flight_logs")
        log_dir.mkdir(exist_ok=True)
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
        log_path = log_dir / f"log_{timestamp}.xml"
        log_path.write_text(text, encoding="utf-8")

        self.app.copy_to_clipboard(str(log_path))
        self.notify(f"Saved {len(self._tick_history)} ticks to {log_path} (path copied)")

    def action_cycle_view(self) -> None:
        """Cycle through Split / Logs / Telemetry view modes."""
        current_index = _VIEW_MODE_CYCLE.index(self._view_mode)
        self._view_mode = _VIEW_MODE_CYCLE[(current_index + 1) % len(_VIEW_MODE_CYCLE)]
        self._apply_view_mode()

    def _apply_view_mode(self) -> None:
        """Apply the current view mode by toggling content area grid rows."""
        content = self.query_one("#content-area", Container)
        content.remove_class("logs-only", "telemetry-only")

        if self._view_mode == ViewMode.LOGS:
            content.add_class("logs-only")
        elif self._view_mode == ViewMode.TELEMETRY:
            content.add_class("telemetry-only")

        self.notify(f"View: {self._view_mode.value.title()}", timeout=1.5)

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

    def action_clear(self) -> None:
        """Ask the user to confirm, then shut down and return to setup."""
        self.app.push_screen(
            ConfirmExitDialog(),
            callback=self._handle_exit_confirmed,
        )

    def _handle_exit_confirmed(self, confirmed: bool | None) -> None:
        """Handle the result of the exit confirmation dialog."""
        if confirmed:
            self._shutdown()
            self.app.pop_screen()


def _format_field_value_xml(value: object) -> str:
    """Format a VesselState field value for XML export."""
    if isinstance(value, float):
        return f"{value:.4f}"
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def _build_vessel_state_element(parent: Element, state: VesselState, previous_state: VesselState | None) -> None:
    """Add vessel state fields that changed since *previous_state* under *parent*.

    If *previous_state* is ``None`` (first tick), all fields are included.
    """
    changed_fields: list[tuple[str, str]] = []
    for field in fields(state):
        value = getattr(state, field.name)
        if previous_state is not None and getattr(previous_state, field.name) == value:
            continue
        changed_fields.append((field.name, _format_field_value_xml(value)))

    if not changed_fields:
        return

    state_el = SubElement(parent, "state")
    for name, text in changed_fields:
        child = SubElement(state_el, name)
        child.text = text


def _format_tick_history(ticks: list[TickRecord]) -> str:
    """Format all tick records as XML for clipboard export.

    State fields are delta-compressed: only fields that changed since the
    previous tick are included. Commands already omit ``None`` fields.
    Logs are always included in full.
    """
    root = Element("ticks")

    previous_state: VesselState | None = None
    for tick in ticks:
        tick_el = SubElement(root, "tick", number=str(tick.tick_number), met=format_met(tick.met))

        action_text = tick.action_label or "No action"
        if tick.action_status is not None:
            action_text += f" ({tick.action_status.value})"
        tick_el.set("action", action_text)

        # Vessel state (delta from previous tick)
        _build_vessel_state_element(tick_el, tick.state, previous_state)
        previous_state = tick.state

        # Logs
        if tick.logs:
            logs_el = SubElement(tick_el, "logs")
            for entry in tick.logs:
                log_el = SubElement(logs_el, "log", level=entry.level.value)
                log_el.text = entry.message

        # Commands
        has_sent = False
        has_redundant = False
        sent_el: Element | None = None
        redundant_el: Element | None = None

        for field in fields(tick.commands):
            value = getattr(tick.commands, field.name)
            if value is None:
                continue
            formatted = format_field_value(field.name, value)
            if field.name in tick.applied_fields:
                if not has_sent:
                    sent_el = SubElement(tick_el, "commands", type="sent")
                    has_sent = True
                cmd_el = SubElement(sent_el, field.name)  # type: ignore[arg-type]
                cmd_el.text = formatted
            else:
                if not has_redundant:
                    redundant_el = SubElement(tick_el, "commands", type="redundant")
                    has_redundant = True
                cmd_el = SubElement(redundant_el, field.name)  # type: ignore[arg-type]
                cmd_el.text = formatted

        if not tick.logs and not has_sent and not has_redundant:
            SubElement(tick_el, "idle")

    indent(root, space="  ")
    return tostring(root, encoding="unicode", xml_declaration=True) + "\n"
