"""LoadCraftDialog - confirmation when a craft is already loaded into KSP."""

from __future__ import annotations

from enum import Enum

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class LoadChoice(Enum):
    """User's choice when the craft is already loaded in KSP's VAB."""

    USE_EXISTING = "use_existing"
    OVERWRITE = "overwrite"
    CANCEL = "cancel"


class LoadCraftDialog(ModalScreen[LoadChoice]):
    """Modal dialog shown before overwriting a craft already loaded into KSP."""

    AUTO_FOCUS = ""

    DEFAULT_CSS = """
    LoadCraftDialog {
        align: center middle;
    }

    #load-craft-container {
        width: 64;
        height: auto;
        padding: 1 2;
        border: solid $warning;
        background: $surface;
    }

    #load-craft-title {
        padding: 0 0 1 0;
    }

    #load-craft-message {
        padding: 0 0 1 0;
    }

    #load-craft-buttons {
        padding: 1 0 0 0;
        align-horizontal: right;
        height: auto;
    }

    #load-craft-buttons Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, craft_name: str) -> None:
        super().__init__()
        self._craft_name = craft_name

    def compose(self) -> ComposeResult:
        with Vertical(id="load-craft-container"):
            yield Static("[b]Craft Already Loaded[/b]", id="load-craft-title")
            yield Static(
                f"A file [b]{self._craft_name}.craft[/b] is already loaded into the active save.\n"
                f"Use the copy that's already there, or overwrite it with the project's version?",
                id="load-craft-message",
            )
            with Horizontal(id="load-craft-buttons"):
                yield Button("Use Existing", id="use-existing-btn", variant="primary")
                yield Button("Overwrite", id="overwrite-btn", variant="warning")
                yield Button("Cancel", id="load-craft-cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "use-existing-btn":
            self.dismiss(LoadChoice.USE_EXISTING)
        elif event.button.id == "overwrite-btn":
            self.dismiss(LoadChoice.OVERWRITE)
        elif event.button.id == "load-craft-cancel-btn":
            self.dismiss(LoadChoice.CANCEL)

    def action_cancel(self) -> None:
        self.dismiss(LoadChoice.CANCEL)
