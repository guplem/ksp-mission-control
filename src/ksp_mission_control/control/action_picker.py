"""ActionPicker - modal for selecting an action to run."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Input, ListItem, ListView, Static

from ksp_mission_control.control.actions.base import Action
from ksp_mission_control.control.actions.registry import get_available_actions


def _action_matches_query(action: Action, query: str) -> bool:
    """Whether an action should appear given a search query.

    Case-insensitive substring match against the action label and description.
    """
    if not query:
        return True
    q = query.lower()
    return q in action.label.lower() or q in action.description.lower()


class ActionPicker(ModalScreen[Action | None]):
    """Modal dialog for selecting an action to run.

    Lists every registered action sorted alphabetically by label, with a
    search box that filters the visible items live. No action is
    pre-highlighted on mount: the ListView's default highlight is cleared,
    and the Select button stays disabled until the user clicks an item or
    moves through the list with the keyboard. Single-click on an item also
    dismisses with that action (the fast path), matching ListView's native
    Selected event.
    """

    AUTO_FOCUS = "#action-picker-search"

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

    #action-picker-search {
        margin: 0 0 1 0;
    }

    #action-picker-empty {
        color: $text 60%;
        padding: 1 0;
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
        self._actions: list[Action] = sorted(get_available_actions(), key=lambda action: action.label.lower())
        self._filtered_actions: list[Action] = list(self._actions)
        self._highlighted_index: int = -1
        """Index of the currently highlighted action in ``_filtered_actions`` (-1 when none)."""

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="action-picker-container"):
            yield Static("[b]Select Action[/b]", id="action-picker-title")
            yield Input(placeholder="Search actions...", id="action-picker-search")
            yield Static("", id="action-picker-empty")
            yield ListView(id="action-picker-listview", initial_index=None)
            with Horizontal(id="action-picker-buttons"):
                yield Button("Select", id="action-picker-select-btn", variant="primary")
                yield Button("Cancel", id="action-picker-cancel-btn", variant="error")

    async def on_mount(self) -> None:
        """Populate the ListView and clear the default highlight so no action looks pre-picked."""
        await self._refresh_list()

    async def _refresh_list(self) -> None:
        """Rebuild the visible ListView from ``_actions`` filtered by the search query.

        Async because ``ListView.clear()`` returns an ``AwaitRemove`` that
        must complete before new ListItems can be appended with the same
        IDs, otherwise Textual raises ``DuplicateIds``.
        """
        listview = self.query_one("#action-picker-listview", ListView)
        await listview.clear()

        query = self._current_search_query()
        self._filtered_actions = [action for action in self._actions if _action_matches_query(action, query)]

        for action in self._filtered_actions:
            listview.append(
                ListItem(
                    Static(f"{action.label}  [dim]{action.description}[/dim]"),
                    id=f"action-pick-{action.action_id}",
                )
            )

        empty_widget = self.query_one("#action-picker-empty", Static)
        if self._actions and not self._filtered_actions:
            empty_widget.update("No actions match the search.")
        else:
            empty_widget.update("")

        # Filter changes invalidate any prior highlight, so reset selection state.
        listview.index = None
        self._highlighted_index = -1
        self._refresh_select_button()

    def _current_search_query(self) -> str:
        """Lowercase, trimmed search text, or '' when the input is not yet mounted."""
        try:
            search_input = self.query_one("#action-picker-search", Input)
        except NoMatches:
            return ""
        return search_input.value.strip().lower()

    async def on_input_changed(self, event: Input.Changed) -> None:
        """Re-filter the action list whenever the search query changes."""
        if event.input.id == "action-picker-search":
            await self._refresh_list()

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
        if not (0 <= self._highlighted_index < len(self._filtered_actions)):
            return
        self.dismiss(self._filtered_actions[self._highlighted_index])

    def _refresh_select_button(self) -> None:
        """Enable Select only when a valid action row is highlighted."""
        select_btn = self.query_one("#action-picker-select-btn", Button)
        select_btn.disabled = not (0 <= self._highlighted_index < len(self._filtered_actions))

    def action_cancel(self) -> None:
        self.dismiss(None)
