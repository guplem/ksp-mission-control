"""ActionListWidget - displays running action status and flight plan steps.

When idle, shows two buttons: "Run Action" and "Load Flight Plan".
When a single action is running, shows its status.
When a flight plan is active, shows each step with its status as Rich markup.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import Button, Static

from ksp_mission_control.control.actions.plan_executor import PlanSnapshot, StepStatus
from ksp_mission_control.control.actions.registry import get_available_actions
from ksp_mission_control.control.formatting import resolve_theme_colors

_STATUS_VARIABLE: dict[StepStatus, str] = {
    StepStatus.PENDING: "text-muted",
    StepStatus.RUNNING: "accent",
    StepStatus.SUCCEEDED: "success",
    StepStatus.FAILED: "error",
}

_STATUS_LABELS: dict[StepStatus, str] = {
    StepStatus.PENDING: "PENDING",
    StepStatus.RUNNING: "RUNNING",
    StepStatus.SUCCEEDED: "OK",
    StepStatus.FAILED: "FAILED",
}


class ActionListWidget(Static):
    """Displays action/plan status and launch buttons when idle."""

    DEFAULT_CSS = """
    #action-list-title {
        padding: 0 0 1 0;
    }

    #action-status-content {
        height: auto;
    }

    #plan-steps-content {
        height: auto;
    }

    .action-btn {
        margin-top: 1;
        width: 100%;
    }

    #manual-cmd-btn {
        margin-top: 1;
        width: 100%;
    }
    """

    class RunActionRequested(Message):
        """Posted when the user clicks the Run Action button."""

    class LoadPlanRequested(Message):
        """Posted when the user clicks the Load Flight Plan button."""

    class ManualCommandRequested(Message):
        """Posted when the user clicks the Manual Command button."""

    def __init__(self, *, id: str | None = None) -> None:  # noqa: A002
        super().__init__(id=id)
        self._running_action_id: str | None = None
        self._plan_active: bool = False
        self._last_plan_snapshot: PlanSnapshot | None = None
        self._status_colors: dict[StepStatus, str] | None = None

    def compose(self) -> ComposeResult:
        yield Static("[b]Actions[/b]", id="action-list-title")
        yield Static("", id="action-status-content")
        yield Static("", id="plan-steps-content")
        yield Button("Run Action", id="run-action-btn", variant="primary", classes="action-btn")
        yield Button(
            "Load Flight Plan", id="load-plan-btn", variant="default", classes="action-btn"
        )
        yield Button(
            "Manual Command", id="manual-cmd-btn", variant="warning"
        )

    def on_mount(self) -> None:
        """Hide dynamic content areas initially."""
        self.query_one("#action-status-content", Static).display = False
        self.query_one("#plan-steps-content", Static).display = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        if event.button.id == "run-action-btn":
            self.post_message(self.RunActionRequested())
        elif event.button.id == "load-plan-btn":
            self.post_message(self.LoadPlanRequested())
        elif event.button.id == "manual-cmd-btn":
            self.post_message(self.ManualCommandRequested())

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
            title = self.query_one("#action-list-title", Static)
        except NoMatches:
            return

        if action_id is not None and not self._plan_active:
            # Look up the action label from registry
            actions = get_available_actions()
            action = next((a for a in actions if a.action_id == action_id), None)
            label = action.label if action else action_id
            status_content.display = True
            status_content.update(f"[b]RUNNING:[/b] {label}")
            title.update("[b]Actions[/b]")
        elif not self._plan_active:
            status_content.display = False
            title.update("[b]Actions[/b]")

    def update_plan(self, plan_snap: PlanSnapshot) -> None:
        """Update the plan step display based on the current plan snapshot.

        Switches between idle mode and plan mode as needed.
        """
        if plan_snap.plan_name is not None:
            self._show_plan_mode(plan_snap)
        elif self._plan_active:
            self._show_idle_mode()

    def _update_button_visibility(self) -> None:
        """Show buttons only when idle (no action running, no plan active)."""
        try:
            run_btn = self.query_one("#run-action-btn", Button)
            plan_btn = self.query_one("#load-plan-btn", Button)
        except NoMatches:
            return
        idle = self._running_action_id is None and not self._plan_active
        run_btn.display = idle
        plan_btn.display = idle

    def _resolve_status_colors(self) -> dict[StepStatus, str]:
        """Resolve theme CSS variables to hex colors, cached after first call."""
        if self._status_colors is None:
            self._status_colors = resolve_theme_colors(self.app, _STATUS_VARIABLE)
        return self._status_colors

    def _show_plan_mode(self, plan_snap: PlanSnapshot) -> None:
        """Switch to plan mode, rendering steps as Rich markup."""
        try:
            plan_content = self.query_one("#plan-steps-content", Static)
            status_content = self.query_one("#action-status-content", Static)
            title = self.query_one("#action-list-title", Static)
        except NoMatches:
            return

        if not self._plan_active:
            status_content.display = False
            plan_content.display = True
            self._plan_active = True
            self._update_button_visibility()

        if plan_snap == self._last_plan_snapshot:
            return
        self._last_plan_snapshot = plan_snap

        colors = self._resolve_status_colors()
        action_lookup = {a.action_id: a for a in get_available_actions()}
        lines: list[str] = []

        current = plan_snap.current_step_index + 1
        total = plan_snap.total_steps
        title.update(f"[b]Flight Plan: {plan_snap.plan_name}[/b]  [dim]{current}/{total}[/dim]")

        for index, step_status in enumerate(plan_snap.step_statuses):
            action_id = plan_snap.step_action_ids[index]
            action_entry = action_lookup.get(action_id)
            label_text = action_entry.label if action_entry else action_id
            color = colors[step_status]
            status_tag = _STATUS_LABELS[step_status]

            step_number = index + 1
            status_part = f"[{color}]{status_tag:>7}[/{color}]"

            if step_status == StepStatus.RUNNING:
                name_part = f"[bold]Step {step_number}: {label_text}[/bold]"
            elif step_status == StepStatus.PENDING:
                name_part = f"[dim]Step {step_number}: {label_text}[/dim]"
            else:
                name_part = f"Step {step_number}: {label_text}"

            lines.append(f"{status_part}  {name_part}")

        plan_content.update("\n".join(lines))

    def _show_idle_mode(self) -> None:
        """Switch back to idle mode (no plan, no action)."""
        try:
            plan_content = self.query_one("#plan-steps-content", Static)
            title = self.query_one("#action-list-title", Static)
        except NoMatches:
            return

        plan_content.display = False
        self._plan_active = False
        self._last_plan_snapshot = None
        self._update_button_visibility()
        title.update("[b]Actions[/b]")
