"""Tests for ActionPicker - Select button and no-default-highlight behavior."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, ListView

from ksp_mission_control.control.action_picker import ActionPicker
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
