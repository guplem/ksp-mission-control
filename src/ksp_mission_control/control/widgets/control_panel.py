"""ControlPanelWidget - displays running action status and flight plan steps.

When idle, shows buttons: "Start Action", "Load Flight Plan", and "Manual Command".
When a plan is pending but not running, shows a pending-plan tray with
"Launch", "Manual Command", and "Cancel" buttons.
When a single action is running, shows its status.
When a flight plan is active, shows each step as a clickable list item.
Clicking a step that has already started posts a ``StepClicked`` message with
the tick at which that step's ``ACTION_START`` log was recorded, so the screen
can navigate logs, command history, and historical telemetry to that point.
When every track has finished (all step statuses terminal), the Stop button
is replaced by a "Finish" button so the user can acknowledge completion and
return the panel to idle.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import Button, ListItem, ListView, Static

from ksp_mission_control.control.actions.base import LogEntry, LogLevel
from ksp_mission_control.control.actions.flight_plan import FlightPlan
from ksp_mission_control.control.actions.multi_track_executor import MultiTrackSnapshot
from ksp_mission_control.control.actions.plan_executor import PlanSnapshot, StepStatus
from ksp_mission_control.control.actions.registry import get_available_actions
from ksp_mission_control.control.formatting import resolve_theme_colors

StepKey = tuple[str | None, int]
"""Identifies a step within a (possibly multi-track) plan: (track_name, plan_step)."""

_STATUS_VARIABLE: dict[StepStatus, str] = {
    StepStatus.PENDING: "foreground-darken-2",
    StepStatus.RUNNING: "accent",
    StepStatus.SUCCEEDED: "success",
    StepStatus.FAILED: "error",
}

_STATUS_LABELS: dict[StepStatus, str] = {
    StepStatus.PENDING: "PENDING",
    StepStatus.RUNNING: "RUNNING",
    StepStatus.SUCCEEDED: "SUCCEEDED",
    StepStatus.FAILED: "FAILED",
}

_STATUS_LABEL_WIDTH = max(len(label) for label in _STATUS_LABELS.values())


class ControlPanelWidget(Static):
    """Displays action/plan status and launch buttons when idle."""

    DEFAULT_CSS = """
    #control-panel-title {
        padding: 0 0 1 0;
    }

    #action-status-content {
        height: auto;
    }

    #plan-steps-list {
        height: auto;
        background: transparent;
    }

    #plan-steps-list ListItem {
        height: auto;
        padding: 0 0 0 1;
        background: transparent;
        border-left: solid $surface-lighten-2;
    }

    #plan-steps-list ListItem.-highlight {
        background: $block-hover-background;
        border-left: solid $primary;
    }

    #plan-steps-list:focus ListItem.-highlight {
        background: $block-hover-background;
        border-left: solid $primary;
    }

    #plan-steps-list ListItem Static {
        height: auto;
        padding: 0;
    }

    #pending-plan-info {
        height: auto;
        padding: 0 0 1 0;
    }

    .action-btn {
        margin-top: 1;
        width: 100%;
    }

    """

    class StartActionRequested(Message):
        """Posted when the user clicks the Start Action button."""

    class LoadPlanRequested(Message):
        """Posted when the user clicks the Load Flight Plan button."""

    class ManualCommandRequested(Message):
        """Posted when the user clicks any Manual Command button (idle or pending)."""

    class LaunchPendingRequested(Message):
        """Posted when the user clicks Launch in the pending-plan tray."""

    class CancelPendingRequested(Message):
        """Posted when the user clicks Cancel in the pending-plan tray."""

    class StopRunRequested(Message):
        """Posted when the user clicks Stop during action/plan execution."""

    class FinishRunRequested(Message):
        """Posted when the user clicks Finish after every track has completed."""

    class StepClicked(Message):
        """Posted when the user clicks a started step in the plan steps list.

        ``tick_id`` is the tick at which the step's ``ACTION_START`` log was
        recorded, so the screen can navigate the log registry, command
        history, and historical telemetry to that point.
        """

        def __init__(self, tick_id: int) -> None:
            super().__init__()
            self.tick_id = tick_id

    def __init__(self, *, id: str | None = None) -> None:  # noqa: A002
        super().__init__(id=id)
        self._running_action_id: str | None = None
        self._plan_active: bool = False
        self._all_finished: bool = False
        self._pending_plan: FlightPlan | None = None
        self._last_plan_snapshot: PlanSnapshot | None = None
        self._last_multi_snapshot: MultiTrackSnapshot | None = None
        self._status_colors: dict[StepStatus, str] | None = None
        self._step_start_ticks: dict[StepKey, int] = {}
        """Tick ID at which each step's ACTION_START log was first observed."""
        self._step_statuses: dict[StepKey, StepStatus] = {}
        """Latest status per step, used to skip clicks on PENDING entries."""
        self._visible_step_keys: list[StepKey | None] = []
        """Maps each ListView item index to a step key, or None for headers."""
        self._selected_tick: int | None = None
        """Mirror of the screen-level selected tick. None means follow live."""

    def compose(self) -> ComposeResult:
        yield Static("[b]Control[/b]", id="control-panel-title")
        yield Static("", id="action-status-content")
        yield ListView(id="plan-steps-list")
        yield Static("", id="pending-plan-info")
        yield Button("Launch", id="pending-launch-btn", variant="primary", classes="action-btn")
        yield Button("Manual Command", id="pending-manual-btn", classes="action-btn")
        yield Button("Cancel", id="pending-cancel-btn", classes="action-btn")
        yield Button("Start Action", id="start-action-btn", classes="action-btn")
        yield Button("Load Flight Plan", id="load-plan-btn", classes="action-btn")
        yield Button("Manual Command", id="manual-cmd-btn", classes="action-btn")
        yield Button("Stop", id="stop-run-btn", variant="error", classes="action-btn")
        yield Button("Finish", id="finish-run-btn", variant="success", classes="action-btn")

    def on_mount(self) -> None:
        """Hide dynamic content areas, the pending-plan tray, and the Finish button initially."""
        self.query_one("#action-status-content", Static).display = False
        self.query_one("#plan-steps-list", ListView).display = False
        self.query_one("#finish-run-btn", Button).display = False
        self._set_pending_visibility(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        button_id = event.button.id
        if button_id == "start-action-btn":
            self.post_message(self.StartActionRequested())
        elif button_id == "load-plan-btn":
            self.post_message(self.LoadPlanRequested())
        elif button_id in ("manual-cmd-btn", "pending-manual-btn"):
            self.post_message(self.ManualCommandRequested())
        elif button_id == "pending-launch-btn":
            self.post_message(self.LaunchPendingRequested())
        elif button_id == "pending-cancel-btn":
            self.post_message(self.CancelPendingRequested())
        elif button_id == "stop-run-btn":
            self.post_message(self.StopRunRequested())
        elif button_id == "finish-run-btn":
            self.post_message(self.FinishRunRequested())

    def update_running(self, action_id: str | None) -> None:
        """Update which action (if any) is currently running.

        Called from the screen's poll loop each tick. Safe to call before
        the widget is fully mounted (NoMatches is caught).
        """
        if action_id == self._running_action_id:
            return
        self._running_action_id = action_id
        self._update_button_visibility()

        try:
            status_content = self.query_one("#action-status-content", Static)
            title = self.query_one("#control-panel-title", Static)
        except NoMatches:
            return

        if action_id is not None and not self._plan_active:
            # Look up the action label from registry
            actions = get_available_actions()
            action = next((a for a in actions if a.action_id == action_id), None)
            label = action.label if action else action_id
            status_content.display = True
            status_content.update(f"[b]RUNNING:[/b] {label}")
            title.update("[b]Control[/b]")
        elif not self._plan_active:
            status_content.display = False
            title.update("[b]Control[/b]")

    def update_plan(self, plan_snap: PlanSnapshot, multi_snap: MultiTrackSnapshot | None = None) -> None:
        """Update the plan step display based on the current plan snapshot.

        When *multi_snap* has multiple tracks, renders each track as a
        labeled section. For single-track plans, renders identically to
        the previous behavior (no section headers).
        """
        if plan_snap.plan_name is not None:
            if multi_snap is not None and multi_snap.is_multi_track:
                self._show_multi_track_mode(multi_snap)
            else:
                self._show_plan_mode(plan_snap)
            new_all_finished = multi_snap is not None and multi_snap.all_finished
            if new_all_finished != self._all_finished:
                self._all_finished = new_all_finished
                self._update_button_visibility()
        elif self._plan_active:
            self._show_idle_mode()

    def set_pending_plan(self, plan: FlightPlan | None) -> None:
        """Enter or leave pending-plan mode.

        While a plan is pending, the regular idle/plan/action content is
        hidden and the panel shows only the plan summary plus the
        Launch / Manual Command / Cancel tray.
        """
        self._pending_plan = plan
        in_pending = plan is not None
        self._set_pending_visibility(in_pending)

        try:
            title = self.query_one("#control-panel-title", Static)
            info = self.query_one("#pending-plan-info", Static)
            status_content = self.query_one("#action-status-content", Static)
            plan_content = self.query_one("#plan-steps-list", ListView)
        except NoMatches:
            return

        if in_pending and plan is not None:
            craft_line = f"craft: [b]{plan.craft}[/b]" if plan.craft else "[dim]no craft attached[/dim]"
            title.update("[b]Plan Ready to Launch[/b]")
            info.update(f"Plan: [b]{plan.name}[/b]\n{craft_line}")
            status_content.display = False
            plan_content.display = False
        else:
            info.update("")
            title.update("[b]Control[/b]")
            self._update_button_visibility()

    def record_logs(self, logs: list[LogEntry], tick_id: int) -> None:
        """Record the tick of each plan step's ``ACTION_START`` log entry.

        Called from the screen's poll loop with every tick's logs. The
        first ``ACTION_START`` for a given (track, step) wins so the
        click target is the original start tick, not any later restart.
        """
        for entry in logs:
            if entry.level != LogLevel.ACTION_START or entry.plan_step is None:
                continue
            key: StepKey = (entry.track_name, entry.plan_step)
            if key not in self._step_start_ticks:
                self._step_start_ticks[key] = tick_id

    def set_selected_tick(self, tick_id: int | None) -> None:
        """Sync the step list selection to the screen-level selected tick.

        When None, clears the selection. When a tick matches the start
        tick of a visible step, highlights that step so clicks elsewhere
        (e.g. on a log line at a step's start) reflect in the panel.
        Otherwise leaves the selection untouched so the user's last
        explicit step selection is preserved.
        """
        self._selected_tick = tick_id
        try:
            list_view = self.query_one("#plan-steps-list", ListView)
        except NoMatches:
            return
        if tick_id is None:
            list_view.index = None
            return
        for step_key, start_tick in self._step_start_ticks.items():
            if start_tick != tick_id:
                continue
            if step_key in self._visible_step_keys:
                list_view.index = self._visible_step_keys.index(step_key)
                return

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Post StepClicked when a started step is highlighted; ignore headers and pending.

        Suppresses the post when the resulting tick already matches the
        screen-level selected tick, so programmatic selection from
        ``set_selected_tick`` doesn't echo back as a navigation request.
        """
        if event.list_view.id != "plan-steps-list":
            return
        index = event.list_view.index
        if index is None or not (0 <= index < len(self._visible_step_keys)):
            return
        key = self._visible_step_keys[index]
        if key is None:
            return
        status = self._step_statuses.get(key)
        if status is None or status == StepStatus.PENDING:
            return
        tick_id = self._step_start_ticks.get(key)
        if tick_id is None or tick_id == self._selected_tick:
            return
        self.post_message(self.StepClicked(tick_id))

    def _set_pending_visibility(self, visible: bool) -> None:
        """Show or hide the pending-plan tray (info + 3 buttons)."""
        try:
            info = self.query_one("#pending-plan-info", Static)
            launch_btn = self.query_one("#pending-launch-btn", Button)
            manual_btn = self.query_one("#pending-manual-btn", Button)
            cancel_btn = self.query_one("#pending-cancel-btn", Button)
        except NoMatches:
            return
        info.display = visible
        launch_btn.display = visible
        manual_btn.display = visible
        cancel_btn.display = visible
        if visible:
            self._update_button_visibility()

    def _update_button_visibility(self) -> None:
        """Reconcile idle/running button visibility against the current state.

        - Pending mode: all idle/running buttons hidden (the pending tray takes over).
        - Running (action or plan), tracks not finished: Stop + Manual Command shown.
        - Running plan with every track finished: Finish replaces Stop.
        - Idle: Start Action, Load Plan, Manual Command shown; Stop and Finish hidden.
        """
        try:
            start_btn = self.query_one("#start-action-btn", Button)
            plan_btn = self.query_one("#load-plan-btn", Button)
            manual_btn = self.query_one("#manual-cmd-btn", Button)
            stop_run_btn = self.query_one("#stop-run-btn", Button)
            finish_btn = self.query_one("#finish-run-btn", Button)
        except NoMatches:
            return
        in_pending = self._pending_plan is not None
        running = self._running_action_id is not None or self._plan_active
        idle = not in_pending and not running
        finished = running and not in_pending and self._all_finished

        start_btn.display = idle
        plan_btn.display = idle
        manual_btn.display = not in_pending
        stop_run_btn.display = running and not in_pending and not finished
        finish_btn.display = finished

    def _resolve_status_colors(self) -> dict[StepStatus, str]:
        """Resolve theme CSS variables to hex colors, cached after first call."""
        if self._status_colors is None:
            self._status_colors = resolve_theme_colors(self.app, _STATUS_VARIABLE)
        return self._status_colors

    def _show_plan_mode(self, plan_snap: PlanSnapshot) -> None:
        """Switch to plan mode, rendering each step as a clickable list item."""
        try:
            list_view = self.query_one("#plan-steps-list", ListView)
            status_content = self.query_one("#action-status-content", Static)
            title = self.query_one("#control-panel-title", Static)
        except NoMatches:
            return

        if not self._plan_active:
            status_content.display = False
            list_view.display = True
            self._plan_active = True
            self._update_button_visibility()

        if plan_snap == self._last_plan_snapshot:
            return
        self._last_plan_snapshot = plan_snap

        current = plan_snap.current_step_index + 1
        total = plan_snap.total_steps
        title.update(f"[b]Flight Plan: {plan_snap.plan_name}[/b]  [dim]{current}/{total}[/dim]")

        items = self._build_step_items_for_track(plan_snap, track_name=None)
        self._render_step_items(items, list_view)

    def _show_multi_track_mode(self, multi_snap: MultiTrackSnapshot) -> None:
        """Render multiple tracks, each as a header item followed by step items."""
        try:
            list_view = self.query_one("#plan-steps-list", ListView)
            status_content = self.query_one("#action-status-content", Static)
            title = self.query_one("#control-panel-title", Static)
        except NoMatches:
            return

        if not self._plan_active:
            status_content.display = False
            list_view.display = True
            self._plan_active = True
            self._update_button_visibility()

        if multi_snap == self._last_multi_snapshot:
            return
        self._last_multi_snapshot = multi_snap
        primary = multi_snap.primary
        self._last_plan_snapshot = primary

        primary_name = primary.plan_name or "plan"
        title.update(f"[b]Flight Plan: {primary_name}[/b]")

        items: list[tuple[StepKey | None, str]] = []
        for track_snap in multi_snap.tracks:
            plan = track_snap.plan_snapshot
            if plan.plan_name is None:
                continue
            items.append((None, f"[b dim]\\[{track_snap.track_name}][/b dim]"))
            items.extend(self._build_step_items_for_track(plan, track_name=track_snap.track_name))
        self._render_step_items(items, list_view)

    def _build_step_items_for_track(
        self,
        plan_snap: PlanSnapshot,
        track_name: str | None,
    ) -> list[tuple[StepKey | None, str]]:
        """Build (key, markup) items for one track's steps, updating cached statuses."""
        colors = self._resolve_status_colors()
        items: list[tuple[StepKey | None, str]] = []
        for index, step_status in enumerate(plan_snap.step_statuses):
            label_text = plan_snap.step_action_labels[index]
            color = colors[step_status]
            status_tag = _STATUS_LABELS[step_status]
            step_number = index + 1
            status_part = f"[{color}]{status_tag:>{_STATUS_LABEL_WIDTH}}[/{color}]"

            if step_status == StepStatus.RUNNING:
                name_part = f"[bold]Step {step_number}: {label_text}[/bold]"
            elif step_status == StepStatus.PENDING:
                name_part = f"[dim]Step {step_number}: {label_text}[/dim]"
            else:
                name_part = f"Step {step_number}: {label_text}"

            key: StepKey = (track_name, step_number)
            self._step_statuses[key] = step_status
            items.append((key, f"{status_part}  {name_part}"))
        return items

    def _render_step_items(
        self,
        items: list[tuple[StepKey | None, str]],
        list_view: ListView,
    ) -> None:
        """Update the ListView, preserving selection when the structure is unchanged."""
        new_keys = [key for key, _ in items]
        if new_keys == self._visible_step_keys and len(list_view.children) == len(items):
            for index, (_, markup) in enumerate(items):
                static = list_view.children[index].query_one(Static)
                static.update(markup)
            return

        current_index = list_view.index
        selected_key: StepKey | None = None
        if current_index is not None and 0 <= current_index < len(self._visible_step_keys):
            selected_key = self._visible_step_keys[current_index]

        list_view.clear()
        for key, markup in items:
            item = ListItem(Static(markup, markup=True))
            if key is None:
                item.disabled = True
            list_view.append(item)

        self._visible_step_keys = new_keys

        if selected_key is not None and selected_key in new_keys:
            list_view.index = new_keys.index(selected_key)
        else:
            list_view.index = None

    def _show_idle_mode(self) -> None:
        """Switch back to idle mode (no plan, no action)."""
        try:
            list_view = self.query_one("#plan-steps-list", ListView)
            title = self.query_one("#control-panel-title", Static)
        except NoMatches:
            return

        list_view.display = False
        list_view.clear()
        self._visible_step_keys = []
        self._plan_active = False
        self._all_finished = False
        self._last_plan_snapshot = None
        self._last_multi_snapshot = None
        self._step_statuses.clear()
        self._step_start_ticks.clear()
        self._update_button_visibility()
        title.update("[b]Control[/b]")
