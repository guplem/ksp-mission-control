"""PlanFailureDialog - confirmation dialog when a flight plan step fails."""

from __future__ import annotations

from enum import Enum

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from ksp_mission_control.control.actions.plan_executor import PlanSnapshot


class FailureAction(Enum):
    """User's choice when a plan step fails."""

    CONTINUE = "continue"
    ABORT_TRACK = "abort_track"
    ABORT_ALL = "abort_all"


class PlanFailureDialog(ModalScreen[FailureAction]):
    """Modal dialog shown when a flight plan step fails.

    Asks the user whether to continue to the next step, abort just the
    failed track, or abort all tracks.

    For single-track plans, "Abort Track" is labeled "Abort Plan" and
    behaves identically to "Abort All".
    """

    AUTO_FOCUS = ""

    DEFAULT_CSS = """
    PlanFailureDialog {
        align: center middle;
    }

    #failure-container {
        width: 60;
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

    def __init__(
        self,
        plan_snap: PlanSnapshot,
        track_name: str | None = None,
        is_multi_track: bool = False,
    ) -> None:
        super().__init__()
        self._plan_snap = plan_snap
        self._track_name = track_name
        self._is_multi_track = is_multi_track

    def compose(self) -> ComposeResult:
        step_number = self._plan_snap.current_step_index + 1
        total = self._plan_snap.total_steps
        plan_name = self._plan_snap.plan_name or "Unknown"
        step_index = self._plan_snap.current_step_index
        if step_index < len(self._plan_snap.step_action_labels):
            action_label = self._plan_snap.step_action_labels[step_index]
        else:
            action_label = self._plan_snap.runner.action_label or "Unknown"

        track_info = ""
        if self._track_name is not None and self._is_multi_track:
            track_info = f" in track [b]{self._track_name}[/b]"

        with Vertical(id="failure-container"):
            yield Static("[b]Flight Plan Step Failed[/b]", id="failure-title")
            yield Static(
                f"Step {step_number}/{total} ({action_label}) failed{track_info} in plan [b]{plan_name}[/b].",
                id="failure-message",
            )
            with Horizontal(id="failure-buttons"):
                yield Button(
                    "Continue to Next Step",
                    id="continue-btn",
                    variant="primary",
                )
                if self._is_multi_track:
                    yield Button("Abort Track", id="abort-track-btn", variant="warning")
                    yield Button("Abort All", id="abort-all-btn", variant="error")
                else:
                    yield Button("Abort Plan", id="abort-all-btn", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "continue-btn":
            self.dismiss(FailureAction.CONTINUE)
        elif event.button.id == "abort-track-btn":
            self.dismiss(FailureAction.ABORT_TRACK)
        elif event.button.id == "abort-all-btn":
            self.dismiss(FailureAction.ABORT_ALL)

    def action_abort_plan(self) -> None:
        self.dismiss(FailureAction.ABORT_ALL)
