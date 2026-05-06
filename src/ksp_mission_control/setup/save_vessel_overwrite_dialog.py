"""SaveVesselOverwriteDialog - confirmation when the project already has the .craft."""

from __future__ import annotations

from enum import Enum

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class OverwriteChoice(Enum):
    """User's choice when ``vessels/<name>.craft`` already exists in the project."""

    OVERWRITE = "overwrite"
    CANCEL = "cancel"


class SaveVesselOverwriteDialog(ModalScreen[OverwriteChoice]):
    """Modal dialog shown before overwriting a craft already saved to the project."""

    AUTO_FOCUS = ""

    DEFAULT_CSS = """
    SaveVesselOverwriteDialog {
        align: center middle;
    }

    #save-overwrite-container {
        width: 64;
        height: auto;
        padding: 1 2;
        border: solid $warning;
        background: $surface;
    }

    #save-overwrite-title {
        padding: 0 0 1 0;
    }

    #save-overwrite-message {
        padding: 0 0 1 0;
    }

    #save-overwrite-buttons {
        padding: 1 0 0 0;
        align-horizontal: right;
        height: auto;
    }

    #save-overwrite-buttons Button {
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
        with Vertical(id="save-overwrite-container"):
            yield Static("[b]Vessel Already Saved[/b]", id="save-overwrite-title")
            yield Static(
                f"The project already contains [b]vessels/{self._sanitized_name}.craft[/b].\nOverwrite it with the live craft from KSP?",
                id="save-overwrite-message",
            )
            with Horizontal(id="save-overwrite-buttons"):
                yield Button("Overwrite", id="save-overwrite-btn", variant="primary")
                yield Button("Cancel", id="save-overwrite-cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-overwrite-btn":
            self.dismiss(OverwriteChoice.OVERWRITE)
        elif event.button.id == "save-overwrite-cancel-btn":
            self.dismiss(OverwriteChoice.CANCEL)

    def action_cancel(self) -> None:
        self.dismiss(OverwriteChoice.CANCEL)
