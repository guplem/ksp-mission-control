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
from textual.worker import Worker, WorkerState

from ksp_mission_control.control.action_picker import ActionPicker
from ksp_mission_control.control.actions.base import (
    Action,
    LogEntry,
    LogLevel,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.flight_plan import FlightPlan
from ksp_mission_control.control.actions.multi_track_executor import MultiTrackSnapshot, TrackSnapshot
from ksp_mission_control.control.actions.runner import RunnerSnapshot
from ksp_mission_control.control.confirm_exit_dialog import ConfirmExitDialog
from ksp_mission_control.control.flight_plan_picker import FlightPlanPicker
from ksp_mission_control.control.formatting import format_met
from ksp_mission_control.control.manual_command_dialog import ManualCommandDialog
from ksp_mission_control.control.param_input_modal import ParamInputModal
from ksp_mission_control.control.plan_failure_dialog import FailureAction, PlanFailureDialog
from ksp_mission_control.control.science_command_dialog import ScienceCommandDialog
from ksp_mission_control.control.session import ControlSession
from ksp_mission_control.control.tick_record import TickRecord
from ksp_mission_control.control.vessel_spawner import SpawnVesselResult, spawn_vessel_from_craft
from ksp_mission_control.control.widgets.command_history import (
    CommandHistoryWidget,
    format_field_value,
)
from ksp_mission_control.control.widgets.control_panel import ControlPanelWidget
from ksp_mission_control.control.widgets.log_registry import LogRegistryWidget
from ksp_mission_control.control.widgets.telemetry_display import TelemetryDisplayWidget
from ksp_mission_control.control.widgets.warp_controller import WarpControllerWidget


class ViewMode(Enum):
    """Layout modes for the control screen."""

    SPLIT = "split"
    LOGS = "logs"
    TELEMETRY = "telemetry"


_VIEW_MODE_CYCLE = [ViewMode.SPLIT, ViewMode.TELEMETRY, ViewMode.LOGS]

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
        ("escape", "exit", "Exit"),
        ("s", "save_logs", "Save Logs"),
        ("v", "cycle_view", "Cycle View"),
    ]

    def __init__(self, pending_plan: FlightPlan | None = None) -> None:
        super().__init__()
        self._session: ControlSession | None = None
        self._view_mode: ViewMode = ViewMode.SPLIT
        self._showing_failure_dialog: bool = False
        """Guards against re-pushing PlanFailureDialog every poll tick while it is open."""
        self._tick_history: list[TickRecord] = []
        self._tick_index: dict[int, TickRecord] = {}
        self._tick_counter: int = 0
        self._pending_plan: FlightPlan | None = pending_plan
        self._pending_plan_synced: bool = False
        self._selected_tick: int | None = None
        """Single source of truth for which tick the history-aware widgets
        are pinned to. ``None`` means follow live; any int pins all
        widgets (logs, commands, plan steps, telemetry) to that tick."""

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="control-grid"):
            with Container(id="content-area"):
                yield TelemetryDisplayWidget(id="telemetry-display")
                yield LogRegistryWidget(id="log-registry")
            with Vertical(id="sidebar"):
                yield WarpControllerWidget(id="warp-controller")
                yield ControlPanelWidget(id="control-panel")
                yield CommandHistoryWidget(id="command-history")
        yield Footer()

    def on_mount(self) -> None:
        from ksp_mission_control.app import MissionControlApp  # noqa: PLC0415

        config_manager = cast(MissionControlApp, self.app).config_manager
        self._session = ControlSession(
            on_update=lambda state, snapshot, commands, applied_fields, logs, multi_snap: self.app.call_from_thread(
                self._update_ui, state, snapshot, commands, applied_fields, logs, multi_snap
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
        state: State,
        runner_state: RunnerSnapshot,
        commands: VesselCommands,
        applied_fields: frozenset[str],
        logs: list[LogEntry],
        multi_snap: MultiTrackSnapshot,
    ) -> None:
        """Update telemetry, control panel, command history, and log registry."""
        self._tick_counter += 1
        record = TickRecord(
            tick_number=self._tick_counter,
            met=state.met,
            state=state,
            multi_snap=multi_snap,
            logs=list(logs),
            commands=commands,
            applied_fields=applied_fields,
        )
        self._tick_history.append(record)
        self._tick_index[self._tick_counter] = record
        if len(self._tick_history) > _MAX_TICK_HISTORY:
            dropped = self._tick_history.pop(0)
            self._tick_index.pop(dropped.tick_number, None)

        plan_snap = multi_snap.primary
        self.query_one("#telemetry-display", TelemetryDisplayWidget).update_vessel_state(state)
        self.query_one("#warp-controller", WarpControllerWidget).update_state(
            target_rate=state.user_target_warp_rate,
            actual_rate=state.time_warp_rate,
        )
        control_panel = self.query_one("#control-panel", ControlPanelWidget)
        control_panel.update_running(runner_state.action_id)
        control_panel.update_plan(plan_snap, multi_snap=multi_snap)
        control_panel.record_logs(logs, tick_id=self._tick_counter)
        self.query_one("#command-history", CommandHistoryWidget).record_commands(
            commands,
            applied_fields=applied_fields,
            action_label=runner_state.action_label,
            met=state.met,
            tick_id=self._tick_counter,
            status=runner_state.status,
            message=runner_state.message,
        )
        self.query_one("#log-registry", LogRegistryWidget).append_logs(logs, met=state.met, tick_id=self._tick_counter)

        # Sync pending-plan tray on first tick (control panel has mounted by now).
        if not self._pending_plan_synced:
            self._pending_plan_synced = True
            if self._pending_plan is not None:
                control_panel.set_pending_plan(self._pending_plan)

        # Pause and ask when a plan step fails. The executor halts the failed
        # track instead of advancing; the dialog lets the user continue, stop
        # the track, or stop all tracks. The guard stops it re-pushing each tick.
        if self._session is not None and self._session.paused_on_failure and not self._showing_failure_dialog:
            self._showing_failure_dialog = True
            paused = self._session.paused_tracks()
            paused_track = paused[0] if paused else None
            failed_snap = plan_snap
            if paused_track is not None:
                for track in multi_snap.tracks:
                    if track.track_name == paused_track:
                        failed_snap = track.plan_snapshot
                        break
            self.app.push_screen(
                PlanFailureDialog(
                    failed_snap,
                    track_name=paused_track,
                    is_multi_track=multi_snap.is_multi_track,
                ),
                callback=self._handle_failure_dialog,
            )

    def _handle_failure_dialog(self, action: FailureAction | None) -> None:
        """Apply the user's choice from the plan-failure dialog."""
        self._showing_failure_dialog = False
        if self._session is None or action is None:
            return
        paused = self._session.paused_tracks()
        if action == FailureAction.CONTINUE:
            if paused:
                try:
                    self._session.continue_track(paused[0])
                except ValueError as exc:
                    self.notify(str(exc), severity="error")
                    self._log_error(str(exc))
        elif action == FailureAction.STOP_TRACK:
            if paused:
                self._session.stop_track(paused[0])
        elif action == FailureAction.STOP_ALL:
            self._session.stop_plan()
            self.query_one("#control-panel", ControlPanelWidget).update_running(None)

    def _show_error(self, message: str) -> None:
        self._log_error(message)

    def _log_error(self, message: str) -> None:
        """Append an error entry to the log registry so it persists for debugging."""
        last_met = self._tick_history[-1].met if self._tick_history else 0.0
        self.query_one("#log-registry", LogRegistryWidget).append_logs(
            [LogEntry(level=LogLevel.PYTHON_ERROR, message=message)],
            met=last_met,
            tick_id=self._tick_counter,
        )

    def on_log_registry_widget_log_line_clicked(self, event: LogRegistryWidget.LogLineClicked) -> None:
        """Pin all history-aware widgets to the tick of the clicked log line."""
        self._set_selected_tick(event.tick_id)

    def on_control_panel_widget_step_clicked(self, event: ControlPanelWidget.StepClicked) -> None:
        """Pin all history-aware widgets to the tick where the clicked step started."""
        self._set_selected_tick(event.tick_id)

    def on_command_history_widget_tick_changed(self, event: CommandHistoryWidget.TickChanged) -> None:
        """Apply a navigation request from the command-history nav buttons."""
        self._set_selected_tick(event.tick_id)

    def _set_selected_tick(self, tick_id: int | None) -> None:
        """Single source of truth for tick navigation.

        Updates ``self._selected_tick`` and broadcasts to every
        history-aware widget. ``tick_id=None`` means follow live; any
        int pins logs, command history, plan steps, and telemetry to
        that tick. Telemetry needs the historical State snapshot, which
        is resolved from ``_tick_index`` here so the widget itself stays
        ignorant of how state is stored.
        """
        self._selected_tick = tick_id
        self.query_one("#log-registry", LogRegistryWidget).set_selected_tick(tick_id)
        self.query_one("#command-history", CommandHistoryWidget).set_selected_tick(tick_id)
        self.query_one("#control-panel", ControlPanelWidget).set_selected_tick(tick_id)
        telemetry = self.query_one("#telemetry-display", TelemetryDisplayWidget)
        if tick_id is None:
            telemetry.resume_live()
            return
        record = self._tick_index.get(tick_id)
        if record is not None:
            telemetry.show_historical_state(record.state, record.met)

    def on_control_panel_widget_start_action_requested(self, event: ControlPanelWidget.StartActionRequested) -> None:
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
        """Route the selected plan: load the craft if needed, then stage it.

        - No ``@craft``: start the plan immediately on the current vessel.
        - ``@craft`` matches the current vessel: start immediately (no install/launch).
        - ``@craft`` differs (or no current vessel): run the unified
          load + spawn workflow, then enter pending-plan mode so the
          user clicks Launch when ready.
        """
        if plan is None or self._session is None:
            return

        if plan.craft is None:
            self._start_plan(plan)
            return

        craft_path = Path.cwd() / "crafts" / f"{plan.craft}.craft"
        if not craft_path.is_file():
            msg = f"Craft file not found: crafts/{plan.craft}.craft"
            self.notify(msg, severity="error")
            self._log_error(msg)
            return

        from ksp_mission_control.craft import sanitize_craft_name  # noqa: PLC0415

        current_name = self._tick_history[-1].state.name if self._tick_history else ""
        if sanitize_craft_name(current_name) == plan.craft:
            self._start_plan(plan)
            return

        self._spawn_vessel_for_plan(plan)

    @work(thread=True)
    def _spawn_vessel_for_plan(self, plan: FlightPlan) -> tuple[SpawnVesselResult, FlightPlan]:
        """Run the unified vessel spawn workflow, then return result + plan."""
        from ksp_mission_control.app import MissionControlApp  # noqa: PLC0415
        from ksp_mission_control.craft import CraftError  # noqa: PLC0415
        from ksp_mission_control.setup.kRPC_comms.parser import (  # noqa: PLC0415
            resolve_krpc_connection,
        )

        if plan.craft is None:
            raise CraftError("plan has no craft to spawn")
        config_manager = cast(MissionControlApp, self.app).config_manager
        ksp_path_str = config_manager.config.ksp_path
        if ksp_path_str is None:
            raise CraftError("KSP install path not configured")

        result = spawn_vessel_from_craft(
            app=self.app,
            craft_name=plan.craft,
            crafts_dir=Path.cwd() / "crafts",
            ksp_path=Path(ksp_path_str),
            krpc_settings=resolve_krpc_connection(config_manager),
        )
        return result, plan

    def _enter_pending_plan(self, plan: FlightPlan) -> None:
        """Mount the pending-plan tray for *plan* in the control panel."""
        self._pending_plan = plan
        self.query_one("#control-panel", ControlPanelWidget).set_pending_plan(plan)

    def _exit_pending_plan(self) -> None:
        """Clear the pending-plan tray and return the control panel to idle."""
        self._pending_plan = None
        self.query_one("#control-panel", ControlPanelWidget).set_pending_plan(None)

    def on_control_panel_widget_launch_pending_requested(
        self,
        event: ControlPanelWidget.LaunchPendingRequested,
    ) -> None:
        """User clicked Launch in the pending tray: start the plan now."""
        plan = self._pending_plan
        if plan is None:
            return
        self._exit_pending_plan()
        self._start_plan(plan)

    def on_control_panel_widget_cancel_pending_requested(
        self,
        event: ControlPanelWidget.CancelPendingRequested,
    ) -> None:
        """User clicked Cancel in the pending tray: drop the plan, stay in control room."""
        self._exit_pending_plan()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Pick up the result of the vessel-spawner worker.

        On success, stage the plan in the pending-plan tray (the user must
        then click Launch). On error or cancellation, surface a notification
        and leave the screen as it was.
        """
        if event.worker.name != "_spawn_vessel_for_plan":
            return
        if event.state == WorkerState.SUCCESS:
            result, plan = cast(
                tuple[SpawnVesselResult, FlightPlan],
                event.worker.result,
            )
            if result == SpawnVesselResult.SPAWNED:
                self._enter_pending_plan(plan)
            else:
                self.notify("Spawn cancelled.", severity="information")
        elif event.state == WorkerState.ERROR:
            error = event.worker.error
            self.notify(f"Spawn failed: {error}", severity="error", timeout=10)
            self._log_error(f"Spawn failed: {error}")

    def _start_plan(self, plan: FlightPlan) -> None:
        """Start executing a flight plan."""
        if self._session is None:
            return
        try:
            plans_dir = Path.cwd() / "plans"
            self._session.start_plan(plan, plans_dir=plans_dir)
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            self._log_error(str(exc))

    def _handle_manual_command(self, commands: VesselCommands | None) -> None:
        """Queue the manual command for the next poll tick."""
        if commands is None or self._session is None:
            return
        self._session.send_manual_command(commands)

    def on_warp_controller_widget_rate_selected(self, event: WarpControllerWidget.RateSelected) -> None:
        """User clicked a warp rate button: update the session's user target."""
        if self._session is None:
            return
        self._session.set_user_target_warp_rate(event.rate)

    def on_telemetry_display_widget_science_experiment_clicked(self, event: TelemetryDisplayWidget.ScienceExperimentClicked) -> None:
        """Open the science command dialog for the clicked experiment."""
        self.app.push_screen(
            ScienceCommandDialog(event.experiment),
            callback=self._handle_manual_command,
        )

    def _handle_action_with_params(self, action: Action, params: dict[str, float] | None) -> None:
        """Start the action with the given parameters."""
        if self._session is None:
            return
        try:
            self._session.start_action(action, params)
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            self._log_error(str(exc))

    def on_control_panel_widget_stop_run_requested(
        self,
        event: ControlPanelWidget.StopRunRequested,
    ) -> None:
        """User clicked Stop during action/plan execution: stop everything."""
        if self._session is None:
            return
        self._session.stop()
        self.query_one("#control-panel", ControlPanelWidget).update_running(None)
        self.notify("Stopped", timeout=1.5)

    def on_control_panel_widget_finish_run_requested(
        self,
        event: ControlPanelWidget.FinishRunRequested,
    ) -> None:
        """User clicked Finish after every track completed: clear plan state and return to idle."""
        if self._session is None:
            return
        self._session.stop()
        self.query_one("#control-panel", ControlPanelWidget).update_running(None)
        self.notify("Finished", timeout=1.5)

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

    def action_exit(self) -> None:
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


def _build_vessel_state_element(
    parent: Element,
    state: State,
    previous_formatted: dict[str, str] | None,
) -> dict[str, str]:
    """Emit a ``<state>`` child for fields whose formatted value changed.

    Comparing on the formatted string (rather than raw float) eliminates
    ghost deltas caused by sub-precision float jitter on values like
    ``comms_signal_strength`` that round to the same string in both ticks.
    Returns the full formatted-value map for the next tick to compare against.
    """
    current_formatted: dict[str, str] = {}
    changed_fields: list[tuple[str, str]] = []
    for field in fields(state):
        value = getattr(state, field.name)
        formatted = _format_field_value_xml(value)
        current_formatted[field.name] = formatted
        if previous_formatted is not None and previous_formatted.get(field.name) == formatted:
            continue
        changed_fields.append((field.name, formatted))

    if changed_fields:
        state_el = SubElement(parent, "state")
        for name, text in changed_fields:
            child = SubElement(state_el, name)
            child.text = text

    return current_formatted


_TrackSummary = tuple[str, int | None, str | None, str | None]
"""(track_name, step_1_based, action_id, status). step/action/status may be None."""


def _track_summary(track_snap: TrackSnapshot) -> _TrackSummary:
    """Reduce a TrackSnapshot to (name, step, action_id, status) for change detection.

    While an action is running on a track, reports the runner's current
    action and status. Once the runner clears (e.g. last plan step
    succeeded with no follow-up), reports the terminal status of the
    last step so plan completion is captured as a track-state change.
    """
    snap = track_snap.plan_snapshot
    runner = snap.runner
    name = track_snap.track_name

    if runner.action_id is not None:
        step = (snap.current_step_index + 1) if snap.plan_name is not None else None
        status = runner.status.value if runner.status is not None else "running"
        return (name, step, runner.action_id, status)

    if snap.plan_name is not None and snap.step_statuses:
        idx = snap.current_step_index
        if 0 <= idx < len(snap.step_statuses):
            action_id = snap.step_action_ids[idx] if idx < len(snap.step_action_ids) else None
            return (name, idx + 1, action_id, snap.step_statuses[idx].value)

    return (name, None, None, None)


def _emit_tracks_element(parent: Element, summaries: tuple[_TrackSummary, ...]) -> None:
    """Append a ``<tracks>`` block listing each track's current activity."""
    tracks_el = SubElement(parent, "tracks")
    for name, step, action_id, status in summaries:
        track_el = SubElement(tracks_el, "track", name=name)
        if step is not None:
            track_el.set("step", str(step))
        if action_id is not None:
            track_el.set("action", action_id)
        if status is not None:
            track_el.set("status", status)


def _format_tick_history(ticks: list[TickRecord]) -> str:
    """Format all tick records as XML for clipboard export.

    The export trims duplicate information aggressively while keeping the
    plan/action/step context that the control room shows live:

    * State fields appear only when their formatted value changes between
      ticks (eliminates float jitter that rounds to the same string).
    * ``<tracks>`` is emitted only when the per-track activity changes,
      so it acts as a state-machine timeline rather than a per-tick dump.
    * ``<log>`` entries carry ``track`` / ``action`` / ``step`` attributes
      whenever those fields are populated on the LogEntry, mirroring the
      live log registry.
    * Command fields are pruned: a field is emitted when its value or
      delivery category (``sent`` vs ``redundant``) changes versus the
      immediately preceding tick. A gap (field absent for a tick) forces
      the next emission so resumed commands are visible.
    """
    root = Element("ticks")

    previous_state_formatted: dict[str, str] | None = None
    previous_tracks: tuple[_TrackSummary, ...] | None = None
    last_command: dict[str, tuple[int, str, str]] = {}

    for tick_index, tick in enumerate(ticks):
        tick_el = SubElement(root, "tick", number=str(tick.tick_number), met=format_met(tick.met))

        previous_state_formatted = _build_vessel_state_element(tick_el, tick.state, previous_state_formatted)

        current_tracks = tuple(_track_summary(track) for track in tick.multi_snap.tracks)
        if current_tracks != previous_tracks:
            if current_tracks:
                _emit_tracks_element(tick_el, current_tracks)
            previous_tracks = current_tracks

        if tick.logs:
            logs_el = SubElement(tick_el, "logs")
            for entry in tick.logs:
                log_el = SubElement(logs_el, "log", level=entry.level.value)
                if entry.track_name is not None:
                    log_el.set("track", entry.track_name)
                if entry.action_id is not None:
                    log_el.set("action", entry.action_id)
                if entry.plan_step is not None:
                    log_el.set("step", str(entry.plan_step))
                log_el.text = entry.message

        sent_el: Element | None = None
        redundant_el: Element | None = None
        for field in fields(tick.commands):
            value = getattr(tick.commands, field.name)
            if value is None or value == ():
                continue
            formatted = format_field_value(field.name, value)
            category = "sent" if field.name in tick.applied_fields else "redundant"
            previous = last_command.get(field.name)
            unchanged_since_previous_tick = (
                previous is not None and previous[0] == tick_index - 1 and previous[1] == formatted and previous[2] == category
            )
            last_command[field.name] = (tick_index, formatted, category)
            if unchanged_since_previous_tick:
                continue
            if category == "sent":
                if sent_el is None:
                    sent_el = SubElement(tick_el, "commands", type="sent")
                cmd_el = SubElement(sent_el, field.name)
            else:
                if redundant_el is None:
                    redundant_el = SubElement(tick_el, "commands", type="redundant")
                cmd_el = SubElement(redundant_el, field.name)
            cmd_el.text = formatted

        if len(tick_el) == 0:
            SubElement(tick_el, "idle")

    indent(root, space="  ")
    return tostring(root, encoding="unicode", xml_declaration=True) + "\n"
