"""SpawnVesselDialog - confirmation before spawning a vessel on the launch pad.

Shown unconditionally before every call to ``launch_vessel_from_vab`` because
kRPC silently recovers whatever is currently at the launch site, and there is
no API to ask "is the pad occupied right now". The dialog is informational:
it warns that *anything* at the pad will be recovered.

The kRPC method is named ``launch_vessel_from_vab`` for historical reasons,
but the operation is a spawn: it instantiates a new vessel on the pad with
engines off. The actual launch (plan execution / liftoff) happens later via
the pending-plan Launch button.
"""

from __future__ import annotations

from enum import Enum

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class SpawnChoice(Enum):
    """User's choice when spawning a new vessel will recover whatever is on the pad."""

    SPAWN = "spawn"
    CANCEL = "cancel"


class SpawnVesselDialog(ModalScreen[SpawnChoice]):
    """Modal dialog shown before spawning a vessel on the launch pad."""

    AUTO_FOCUS = ""

    DEFAULT_CSS = """
    SpawnVesselDialog {
        align: center middle;
    }

    #spawn-vessel-container {
        width: 64;
        height: auto;
        padding: 1 2;
        border: solid $warning;
        background: $surface;
    }

    #spawn-vessel-title {
        padding: 0 0 1 0;
    }

    #spawn-vessel-message {
        padding: 0 0 1 0;
    }

    #spawn-vessel-buttons {
        padding: 1 0 0 0;
        align-horizontal: right;
        height: auto;
    }

    #spawn-vessel-buttons Button {
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
        with Vertical(id="spawn-vessel-container"):
            yield Static("[b]Spawn Vessel on Pad[/b]", id="spawn-vessel-title")
            yield Static(
                f"Spawning [b]{self._new_craft}[/b] will recover any vessel currently on the launch pad.\nContinue?",
                id="spawn-vessel-message",
            )
            with Horizontal(id="spawn-vessel-buttons"):
                yield Button("Spawn", id="spawn-btn", variant="primary")
                yield Button("Cancel", id="spawn-cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "spawn-btn":
            self.dismiss(SpawnChoice.SPAWN)
        elif event.button.id == "spawn-cancel-btn":
            self.dismiss(SpawnChoice.CANCEL)

    def action_cancel(self) -> None:
        self.dismiss(SpawnChoice.CANCEL)
