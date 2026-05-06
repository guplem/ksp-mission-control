"""LoadVesselDialog - confirmation before placing a craft on the launch pad.

Shown unconditionally before every call to ``launch_vessel_from_vab`` because
kRPC silently recovers whatever is currently at the launch site, and there is
no API to ask "is the pad occupied right now". The dialog is informational:
it warns that *anything* at the pad will be recovered.

Despite the kRPC method being named ``launch_vessel_from_vab``, the operation
only loads the craft onto the pad with engines off; the actual launch (plan
execution / liftoff) happens later via the pending-plan Launch button.
"""

from __future__ import annotations

from enum import Enum

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class LoadChoice(Enum):
    """User's choice when loading the craft will recover whatever is on the pad."""

    LOAD = "load"
    CANCEL = "cancel"


class LoadVesselDialog(ModalScreen[LoadChoice]):
    """Modal dialog shown before placing a craft on the launch pad from the VAB."""

    AUTO_FOCUS = ""

    DEFAULT_CSS = """
    LoadVesselDialog {
        align: center middle;
    }

    #load-vessel-container {
        width: 64;
        height: auto;
        padding: 1 2;
        border: solid $warning;
        background: $surface;
    }

    #load-vessel-title {
        padding: 0 0 1 0;
    }

    #load-vessel-message {
        padding: 0 0 1 0;
    }

    #load-vessel-buttons {
        padding: 1 0 0 0;
        align-horizontal: right;
        height: auto;
    }

    #load-vessel-buttons Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, new_craft: str) -> None:
        super().__init__()
        self._new_craft = new_craft

    def compose(self) -> ComposeResult:
        with Vertical(id="load-vessel-container"):
            yield Static("[b]Load Craft to Pad[/b]", id="load-vessel-title")
            yield Static(
                f"Loading [b]{self._new_craft}[/b] from the VAB will recover any vessel currently on the launch pad.\nContinue?",
                id="load-vessel-message",
            )
            with Horizontal(id="load-vessel-buttons"):
                yield Button("Load", id="load-btn", variant="primary")
                yield Button("Cancel", id="load-cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "load-btn":
            self.dismiss(LoadChoice.LOAD)
        elif event.button.id == "load-cancel-btn":
            self.dismiss(LoadChoice.CANCEL)

    def action_cancel(self) -> None:
        self.dismiss(LoadChoice.CANCEL)
