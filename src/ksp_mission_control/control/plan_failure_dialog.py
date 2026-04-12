"""PlanFailureDialog - confirmation dialog when a flight plan step fails."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from ksp_mission_control.control.actions.plan_executor import PlanSnapshot


class PlanFailureDialog(ModalScreen[bool]):
    """Modal dialog shown when a flight plan step fails.

    Asks the user whether to continue to the next step or abort the plan.
    Dismisses with True (continue) or False (abort).
    """

    DEFAULT_CSS = """
    PlanFailureDialog {
        align: center middle;
    }

    #failure-container {
        width: 50;
        height: auto;
        padding: 1 2;
        border: solid $error;
        background: $surface;
    }

    #failure-title {
        padding: 0 0 1 0;
    }

    #failure-message {
        padding: 0 0 1 0;
    }

    #failure-buttons {
        padding: 1 0 0 0;
        align-horizontal: right;
        height: auto;
    }

    #failure-buttons Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        ("escape", "abort_plan", "Abort Plan"),
    ]

    def __init__(self, plan_snap: PlanSnapshot) -> None:
        super().__init__()
        self._plan_snap = plan_snap

    def compose(self) -> ComposeResult:
        step_number = self._plan_snap.current_step_index + 1
        total = self._plan_snap.total_steps
        plan_name = self._plan_snap.plan_name or "Unknown"
        action_label = self._plan_snap.runner.action_label or "Unknown"

        with Vertical(id="failure-container"):
            yield Static("[b]Flight Plan Step Failed[/b]", id="failure-title")
            yield Static(
                f"Step {step_number}/{total} ({action_label}) failed in plan [b]{plan_name}[/b].",
                id="failure-message",
            )
            with Horizontal(id="failure-buttons"):
                yield Button(
                    "Continue to Next Step",
                    id="continue-btn",
                    variant="primary",
                )
                yield Button("Abort Plan", id="abort-btn", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "continue-btn":
            self.dismiss(True)
        elif event.button.id == "abort-btn":
            self.dismiss(False)

    def action_abort_plan(self) -> None:
        self.dismiss(False)
