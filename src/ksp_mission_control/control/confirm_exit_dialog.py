"""ConfirmExitDialog - confirmation before leaving the control screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmExitDialog(ModalScreen[bool]):
    """Modal dialog shown when the user presses Escape on the control screen.

    Asks the user to confirm leaving the control session.
    Dismisses with True (confirm) or False (cancel).
    """

    AUTO_FOCUS = ""

    DEFAULT_CSS = """
    ConfirmExitDialog {
        align: center middle;
    }

    #exit-container {
        width: 50;
        height: auto;
        padding: 1 2;
        border: solid $warning;
        background: $surface;
    }

    #exit-title {
        padding: 0 0 1 0;
    }

    #exit-message {
        padding: 0 0 1 0;
    }

    #exit-buttons {
        padding: 1 0 0 0;
        align-horizontal: right;
        height: auto;
    }

    #exit-buttons Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="exit-container"):
            yield Static("[b]Leave Control Room?[/b]", id="exit-title")
            yield Static(
                "This will disconnect from the vessel and return to setup.",
                id="exit-message",
            )
            with Horizontal(id="exit-buttons"):
                yield Button("Leave", id="leave-btn", variant="warning")
                yield Button("Stay", id="stay-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "leave-btn":
            self.dismiss(True)
        elif event.button.id == "stay-btn":
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)
