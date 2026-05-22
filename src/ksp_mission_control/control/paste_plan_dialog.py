"""PastePlanDialog - modal for pasting raw plan text and parsing it inline."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static, TextArea

from ksp_mission_control.control.actions.flight_plan import (
    FlightPlan,
    parse_flight_plan_text,
)

_INLINE_PLAN_NAME = "pasted"


class PastePlanDialog(ModalScreen[FlightPlan | None]):
    """Modal dialog for pasting plan text and parsing it inline.

    Accepts the same syntax as .plan files (``@craft``, ``@parallel``,
    ``@hidden``, comments, blank lines, ``action_id key=value ...``).
    Useful for re-running a partial plan after a manual fix without
    saving a file to disk. Dismisses with the parsed FlightPlan, or
    ``None`` on cancel.
    """

    AUTO_FOCUS = "#paste-textarea"

    DEFAULT_CSS = """
    PastePlanDialog {
        align: center middle;
    }

    #paste-container {
        width: 100;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        border: solid $primary;
        background: $surface;
    }

    #paste-title {
        padding: 0 0 1 0;
    }

    #paste-description {
        padding: 0 0 1 0;
        color: $text 60%;
    }

    #paste-textarea {
        height: 20;
    }

    #paste-error {
        color: $error;
        padding: 1 0 0 0;
    }

    #paste-buttons {
        dock: bottom;
        padding: 1 0 0 0;
        align-horizontal: right;
        height: auto;
        background: $surface;
    }

    #paste-buttons Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="paste-container"):
            yield Static("[b]Paste Flight Plan[/b]", id="paste-title")
            yield Static(
                "Paste plan text below using the same syntax as .plan files. @craft, @parallel, and @hidden directives are supported.",
                id="paste-description",
            )
            yield TextArea(id="paste-textarea")
            yield Static("", id="paste-error")
            with Horizontal(id="paste-buttons"):
                yield Button("Confirm", id="paste-confirm-btn", variant="primary")
                yield Button("Cancel", id="paste-cancel-btn", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "paste-confirm-btn":
            self._do_confirm()
        elif event.button.id == "paste-cancel-btn":
            self.dismiss(None)

    def _do_confirm(self) -> None:
        """Parse the textarea content and dismiss with the resulting plan."""
        textarea = self.query_one("#paste-textarea", TextArea)
        text = textarea.text
        error_widget = self.query_one("#paste-error", Static)

        try:
            plan = parse_flight_plan_text(text, name=_INLINE_PLAN_NAME)
        except ValueError as exc:
            error_widget.update(str(exc))
            return

        self.dismiss(plan)

    def action_cancel(self) -> None:
        self.dismiss(None)
