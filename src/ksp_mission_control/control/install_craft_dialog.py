"""InstallCraftDialog - confirmation when a craft already exists in the save."""

from __future__ import annotations

from enum import Enum

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class InstallChoice(Enum):
    """User's choice when the craft is already present in the save's VAB."""

    USE_EXISTING = "use_existing"
    OVERWRITE = "overwrite"
    CANCEL = "cancel"


class InstallCraftDialog(ModalScreen[InstallChoice]):
    """Modal dialog shown before overwriting a craft already in the save."""

    AUTO_FOCUS = ""

    DEFAULT_CSS = """
    InstallCraftDialog {
        align: center middle;
    }

    #install-container {
        width: 64;
        height: auto;
        padding: 1 2;
        border: solid $warning;
        background: $surface;
    }

    #install-title {
        padding: 0 0 1 0;
    }

    #install-message {
        padding: 0 0 1 0;
    }

    #install-buttons {
        padding: 1 0 0 0;
        align-horizontal: right;
        height: auto;
    }

    #install-buttons Button {
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
        with Vertical(id="install-container"):
            yield Static("[b]Craft Already in Save[/b]", id="install-title")
            yield Static(
                f"A file [b]{self._craft_name}.craft[/b] already exists in the active save.\n"
                f"Use the copy that's already there, or overwrite it with the project's version?",
                id="install-message",
            )
            with Horizontal(id="install-buttons"):
                yield Button("Use Existing", id="use-existing-btn", variant="primary")
                yield Button("Overwrite", id="overwrite-btn", variant="warning")
                yield Button("Cancel", id="install-cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "use-existing-btn":
            self.dismiss(InstallChoice.USE_EXISTING)
        elif event.button.id == "overwrite-btn":
            self.dismiss(InstallChoice.OVERWRITE)
        elif event.button.id == "install-cancel-btn":
            self.dismiss(InstallChoice.CANCEL)

    def action_cancel(self) -> None:
        self.dismiss(InstallChoice.CANCEL)
