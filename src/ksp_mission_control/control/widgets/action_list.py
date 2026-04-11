"""ActionListWidget - displays available actions with running status.

Shows a ListView of all registered actions. When the user selects one,
posts a Selected message for the parent screen to handle. Tracks which
action (if any) is currently running and updates the display accordingly.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import ListItem, ListView, Static

from ksp_mission_control.control.actions.base import Action
from ksp_mission_control.control.actions.registry import get_available_actions


class ActionListWidget(Static):
    """Displays available vessel actions and posts a message when one is selected."""

    DEFAULT_CSS = """
    #action-list-title {
        padding: 0 0 1 0;
    }

    #action-listview {
        height: auto;
    }
    """

    class Selected(Message):
        """Posted when the user selects an action from the list."""

        def __init__(self, action: Action) -> None:
            super().__init__()
            self.action = action

    def __init__(self, *, id: str | None = None) -> None:  # noqa: A002
        super().__init__(id=id)
        self._actions: list[Action] = get_available_actions()
        self._running_action_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("[b]Actions[/b]", id="action-list-title")
        with ListView(id="action-listview"):
            for action in self._actions:
                yield ListItem(
                    Static(action.label, id=f"action-{action.action_id}-label"),
                    id=f"action-{action.action_id}",
                )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Forward selection as an ActionListWidget.Selected message."""
        item_id = event.item.id
        if item_id is None:
            return
        action_id = item_id.removeprefix("action-")
        action = next((a for a in self._actions if a.action_id == action_id), None)
        if action is not None:
            self.post_message(self.Selected(action))

    def update_running(self, action_id: str | None) -> None:
        """Update which action (if any) shows the running indicator.

        Called from the screen's poll loop each tick. Safe to call before
        the widget is fully mounted (NoMatches is caught).
        """
        if action_id == self._running_action_id:
            return
        # Clear previous running indicator
        if self._running_action_id is not None:
            prev = next(
                (a for a in self._actions if a.action_id == self._running_action_id), None
            )
            if prev is not None:
                try:
                    label = self.query_one(f"#action-{prev.action_id}-label", Static)
                    label.update(prev.label)
                except NoMatches:
                    pass
        # Set new running indicator
        self._running_action_id = action_id
        if action_id is not None:
            action = next((a for a in self._actions if a.action_id == action_id), None)
            if action is not None:
                try:
                    label = self.query_one(f"#action-{action.action_id}-label", Static)
                    label.update(f"[b]RUNNING: {action.label}[/b]")
                except NoMatches:
                    pass
