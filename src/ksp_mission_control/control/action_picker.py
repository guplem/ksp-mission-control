"""ActionPicker - modal for selecting an action to run."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, ListItem, ListView, Static

from ksp_mission_control.control.actions.base import Action
from ksp_mission_control.control.actions.registry import get_available_actions


class ActionPicker(ModalScreen[Action | None]):
    """Modal dialog for selecting an action to run.

    Lists all registered actions with their descriptions. No action is
    pre-highlighted on mount: the ListView's default highlight is cleared,
    and the Select button stays disabled until the user clicks an item or
    moves through the list with the keyboard. Single-click on an item also
    dismisses with that action (the fast path), matching ListView's native
    Selected event.
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

    #action-picker-listview ListItem {
        padding: 0 0 1 0;
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
        self._highlighted_index: int = -1
        """Index of the currently highlighted action (-1 when none)."""

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
                yield Button("Select", id="action-picker-select-btn", variant="primary")
                yield Button("Cancel", id="action-picker-cancel-btn", variant="error")

    def on_mount(self) -> None:
        """Clear the ListView's default highlight so no action looks pre-picked."""
        listview = self.query_one("#action-picker-listview", ListView)
        listview.index = None
        self._highlighted_index = -1
        self._refresh_select_button()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Mirror the ListView highlight onto Select button state."""
        try:
            listview = self.query_one("#action-picker-listview", ListView)
        except NoMatches:
            return
        self._highlighted_index = listview.index if listview.index is not None else -1
        self._refresh_select_button()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Dismiss with the picked action (click on item or Enter when focused)."""
        item_id = event.item.id
        if item_id is None:
            return
        action_id = item_id.removeprefix("action-pick-")
        action = next((a for a in self._actions if a.action_id == action_id), None)
        if action is not None:
            self.dismiss(action)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "action-picker-select-btn":
            self._dismiss_with_highlighted_action()
        elif event.button.id == "action-picker-cancel-btn":
            self.dismiss(None)

    def _dismiss_with_highlighted_action(self) -> None:
        """Dismiss with the highlighted action; no-op when no row is highlighted."""
        if not (0 <= self._highlighted_index < len(self._actions)):
            return
        self.dismiss(self._actions[self._highlighted_index])

    def _refresh_select_button(self) -> None:
        """Enable Select only when a valid action row is highlighted."""
        select_btn = self.query_one("#action-picker-select-btn", Button)
        select_btn.disabled = not (0 <= self._highlighted_index < len(self._actions))

    def action_cancel(self) -> None:
        self.dismiss(None)
