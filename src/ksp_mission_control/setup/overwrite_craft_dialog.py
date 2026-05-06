"""OverwriteCraftDialog - confirmation when the project already has the .craft."""

from __future__ import annotations

from enum import Enum

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class OverwriteChoice(Enum):
    """User's choice when ``crafts/<name>.craft`` already exists in the project."""

    OVERWRITE = "overwrite"
    CANCEL = "cancel"


class OverwriteCraftDialog(ModalScreen[OverwriteChoice]):
    """Modal dialog shown before overwriting a craft already exported to the project."""

    AUTO_FOCUS = ""

    DEFAULT_CSS = """
    OverwriteCraftDialog {
        align: center middle;
    }

    #overwrite-craft-container {
        width: 64;
        height: auto;
        padding: 1 2;
        border: solid $warning;
        background: $surface;
    }

    #overwrite-craft-title {
        padding: 0 0 1 0;
    }

    #overwrite-craft-message {
        padding: 0 0 1 0;
    }

    #overwrite-craft-buttons {
        padding: 1 0 0 0;
        align-horizontal: right;
        height: auto;
    }

    #overwrite-craft-buttons Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, sanitized_name: str) -> None:
        super().__init__()
        self._sanitized_name = sanitized_name

    def compose(self) -> ComposeResult:
        with Vertical(id="overwrite-craft-container"):
            yield Static("[b]Craft Already Exists[/b]", id="overwrite-craft-title")
            yield Static(
                f"The project already contains [b]crafts/{self._sanitized_name}.craft[/b].\nOverwrite it with the active vessel's craft from KSP?",
                id="overwrite-craft-message",
            )
            with Horizontal(id="overwrite-craft-buttons"):
                yield Button("Overwrite", id="overwrite-craft-btn", variant="primary")
                yield Button("Cancel", id="overwrite-craft-cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "overwrite-craft-btn":
            self.dismiss(OverwriteChoice.OVERWRITE)
        elif event.button.id == "overwrite-craft-cancel-btn":
            self.dismiss(OverwriteChoice.CANCEL)

    def action_cancel(self) -> None:
        self.dismiss(OverwriteChoice.CANCEL)
