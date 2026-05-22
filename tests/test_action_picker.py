"""Tests for ActionPicker - Select button and no-default-highlight behavior."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.pilot import Pilot
from textual.widgets import Button, Input, ListView, Static

from ksp_mission_control.control.action_picker import ActionPicker, _action_matches_query
from ksp_mission_control.control.actions.base import Action


class _ActionPickerTestApp(App[None]):
    """Host app that pushes ActionPicker and records its dismiss value."""

    def __init__(self) -> None:
        super().__init__()
        self.dismissed_value: Action | None | str = "NOT_SET"

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        self.push_screen(ActionPicker(), callback=self._on_dismiss)

    def _on_dismiss(self, result: Action | None) -> None:
        self.dismissed_value = result


class TestActionPicker:
    """Mount + composition basics."""

    @pytest.mark.asyncio
    async def test_screen_mounts(self) -> None:
        async with _ActionPickerTestApp().run_test() as pilot:
            assert isinstance(pilot.app.screen, ActionPicker)

    @pytest.mark.asyncio
    async def test_no_action_highlighted_by_default(self) -> None:
        async with _ActionPickerTestApp().run_test() as pilot:
            await pilot.pause()
            listview = pilot.app.screen.query_one("#action-picker-listview", ListView)
            assert listview.index is None

    @pytest.mark.asyncio
    async def test_select_button_disabled_by_default(self) -> None:
        async with _ActionPickerTestApp().run_test() as pilot:
            await pilot.pause()
            select_btn = pilot.app.screen.query_one("#action-picker-select-btn", Button)
            assert select_btn.disabled is True


class TestActionPickerSelectButton:
    """The Select button activates after user interaction and confirms the highlighted action."""

    @pytest.mark.asyncio
    async def test_keyboard_navigation_enables_button(self) -> None:
        async with _ActionPickerTestApp().run_test() as pilot:
            await pilot.pause()
            listview = pilot.app.screen.query_one("#action-picker-listview", ListView)
            listview.focus()
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()

            select_btn = pilot.app.screen.query_one("#action-picker-select-btn", Button)
            assert select_btn.disabled is False
            assert listview.index is not None

    @pytest.mark.asyncio
    async def test_select_button_dismisses_with_highlighted_action(self) -> None:
        app = _ActionPickerTestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            listview = pilot.app.screen.query_one("#action-picker-listview", ListView)
            listview.focus()
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()

            highlighted_index = listview.index
            assert highlighted_index is not None
            picker = pilot.app.screen
            assert isinstance(picker, ActionPicker)
            expected_action = picker._actions[highlighted_index]

            await pilot.click("#action-picker-select-btn")
            await pilot.pause()

            assert isinstance(app.dismissed_value, Action)
            assert app.dismissed_value.action_id == expected_action.action_id

    @pytest.mark.asyncio
    async def test_cancel_button_dismisses_with_none(self) -> None:
        app = _ActionPickerTestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#action-picker-cancel-btn")
            await pilot.pause()
            assert app.dismissed_value is None


class TestActionMatchesQuery:
    """_action_matches_query: case-insensitive substring on label and description."""

    def _make_action(self, label: str, description: str) -> Action:
        class _StubAction:
            pass

        stub = _StubAction()
        stub.label = label  # type: ignore[attr-defined]
        stub.description = description  # type: ignore[attr-defined]
        return stub  # type: ignore[return-value]

    def test_empty_query_matches_everything(self) -> None:
        action = self._make_action("Hover", "Hold altitude")
        assert _action_matches_query(action, "") is True

    def test_matches_label_case_insensitive(self) -> None:
        action = self._make_action("Hover", "Hold altitude")
        assert _action_matches_query(action, "HOVER") is True

    def test_matches_description(self) -> None:
        action = self._make_action("Hover", "Hold altitude with PD controller")
        assert _action_matches_query(action, "controller") is True

    def test_no_match_returns_false(self) -> None:
        action = self._make_action("Hover", "Hold altitude")
        assert _action_matches_query(action, "deploy") is False


class TestActionPickerAlphabeticSort:
    """Actions appear alphabetically by label, independent of registry order."""

    @pytest.mark.asyncio
    async def test_actions_are_sorted_by_label(self) -> None:
        async with _ActionPickerTestApp().run_test() as pilot:
            await pilot.pause()
            picker = pilot.app.screen
            assert isinstance(picker, ActionPicker)
            labels = [a.label.lower() for a in picker._actions]
            assert labels == sorted(labels)


class TestActionPickerSearch:
    """Search filters visible items; empty / no-match states render the right message."""

    @staticmethod
    async def _drain(pilot: Pilot[None]) -> None:
        """Pause a few times so an awaited async refresh fully settles."""
        for _ in range(4):
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_typing_filters_visible_actions(self) -> None:
        async with _ActionPickerTestApp().run_test() as pilot:
            await pilot.pause()
            search = pilot.app.screen.query_one("#action-picker-search", Input)
            search.value = "hover"
            await self._drain(pilot)

            picker = pilot.app.screen
            assert isinstance(picker, ActionPicker)
            assert len(picker._filtered_actions) >= 1
            for action in picker._filtered_actions:
                assert "hover" in action.label.lower() or "hover" in action.description.lower()

    @pytest.mark.asyncio
    async def test_clearing_search_restores_all_items(self) -> None:
        async with _ActionPickerTestApp().run_test() as pilot:
            await pilot.pause()
            picker = pilot.app.screen
            assert isinstance(picker, ActionPicker)
            total = len(picker._actions)

            search = pilot.app.screen.query_one("#action-picker-search", Input)
            search.value = "hover"
            await self._drain(pilot)
            assert len(picker._filtered_actions) < total

            search.value = ""
            await self._drain(pilot)
            assert len(picker._filtered_actions) == total

    @pytest.mark.asyncio
    async def test_no_match_shows_empty_message(self) -> None:
        async with _ActionPickerTestApp().run_test() as pilot:
            await pilot.pause()
            search = pilot.app.screen.query_one("#action-picker-search", Input)
            search.value = "definitely-not-an-action-zzz"
            await self._drain(pilot)

            empty_widget = pilot.app.screen.query_one("#action-picker-empty", Static)
            assert "No actions match" in str(empty_widget._Static__content)

    @pytest.mark.asyncio
    async def test_filter_resets_highlight_and_disables_button(self) -> None:
        async with _ActionPickerTestApp().run_test() as pilot:
            await pilot.pause()
            listview = pilot.app.screen.query_one("#action-picker-listview", ListView)
            listview.focus()
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            select_btn = pilot.app.screen.query_one("#action-picker-select-btn", Button)
            assert select_btn.disabled is False

            search = pilot.app.screen.query_one("#action-picker-search", Input)
            search.value = "hover"
            await self._drain(pilot)

            assert select_btn.disabled is True
            assert listview.index is None
