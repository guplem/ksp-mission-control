"""ActionPicker - modal for selecting an action to run."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, ListItem, ListView, Static

from ksp_mission_control.control.actions.base import Action
from ksp_mission_control.control.actions.registry import get_available_actions


class ActionPicker(ModalScreen[Action | None]):
    """Modal dialog for selecting an action to run.

    Lists all registered actions with their descriptions.
    Dismisses with the chosen Action or None on cancel.
    """

    AUTO_FOCUS = ""

    DEFAULT_CSS = """
    ActionPicker {
        align: center middle;
    }

    #action-picker-container {
        width: 60;
        height: auto;
        max-height: 80%;
        padding: 1 2;
        border: solid $primary;
        background: $surface;
    }

    #action-picker-title {
        padding: 0 0 1 0;
    }

    #action-picker-listview {
        height: auto;
        max-height: 20;
    }

    #action-picker-buttons {
        dock: bottom;
        padding: 1 0 0 0;
        align-horizontal: right;
        height: auto;
        background: $surface;
    }

    #action-picker-buttons Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._actions: list[Action] = get_available_actions()

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="action-picker-container"):
            yield Static("[b]Select Action[/b]", id="action-picker-title")
            with ListView(id="action-picker-listview"):
                for action in self._actions:
                    yield ListItem(
                        Static(f"{action.label}  [dim]{action.description}[/dim]"),
                        id=f"action-pick-{action.action_id}",
                    )
            with Horizontal(id="action-picker-buttons"):
                yield Button("Cancel", id="action-picker-cancel-btn", variant="error")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Select and dismiss with the chosen action."""
        item_id = event.item.id
        if item_id is None:
            return
        action_id = item_id.removeprefix("action-pick-")
        action = next((a for a in self._actions if a.action_id == action_id), None)
        if action is not None:
            self.dismiss(action)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "action-picker-cancel-btn":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
