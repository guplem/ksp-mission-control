"""Tests for ConfirmExitDialog - confirmation before leaving the control screen."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Static

from ksp_mission_control.control.confirm_exit_dialog import ConfirmExitDialog


class ConfirmExitTestApp(App[None]):
    """Pushes ConfirmExitDialog on mount so the pilot can interact with it."""

    def __init__(self) -> None:
        super().__init__()
        self.dismissed_value: bool | None = "NOT_SET"  # type: ignore[assignment]

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        self.push_screen(ConfirmExitDialog(), callback=self._on_dismiss)

    def _on_dismiss(self, result: bool | None) -> None:
        self.dismissed_value = result


class TestConfirmExitDialogComposition:
    @pytest.mark.asyncio
    async def test_screen_mounts(self) -> None:
        async with ConfirmExitTestApp().run_test() as pilot:
            assert isinstance(pilot.app.screen, ConfirmExitDialog)

    @pytest.mark.asyncio
    async def test_shows_title(self) -> None:
        async with ConfirmExitTestApp().run_test() as pilot:
            await pilot.pause()
            title = pilot.app.screen.query_one("#exit-title", Static)
            assert "Leave Control Room" in str(title._Static__content)

    @pytest.mark.asyncio
    async def test_shows_message(self) -> None:
        async with ConfirmExitTestApp().run_test() as pilot:
            await pilot.pause()
            message = pilot.app.screen.query_one("#exit-message", Static)
            assert "disconnect" in str(message._Static__content).lower()

    @pytest.mark.asyncio
    async def test_has_leave_button(self) -> None:
        async with ConfirmExitTestApp().run_test() as pilot:
            await pilot.pause()
            btn = pilot.app.screen.query_one("#leave-btn", Button)
            assert btn is not None

    @pytest.mark.asyncio
    async def test_has_stay_button(self) -> None:
        async with ConfirmExitTestApp().run_test() as pilot:
            await pilot.pause()
            btn = pilot.app.screen.query_one("#stay-btn", Button)
            assert btn is not None


class TestConfirmExitDialogLeave:
    @pytest.mark.asyncio
    async def test_leave_button_dismisses_with_true(self) -> None:
        app = ConfirmExitTestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#leave-btn")
            await pilot.pause()
            assert app.dismissed_value is True

    @pytest.mark.asyncio
    async def test_leave_button_pops_dialog(self) -> None:
        app = ConfirmExitTestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#leave-btn")
            await pilot.pause()
            assert not isinstance(pilot.app.screen, ConfirmExitDialog)


class TestConfirmExitDialogStay:
    @pytest.mark.asyncio
    async def test_stay_button_dismisses_with_false(self) -> None:
        app = ConfirmExitTestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#stay-btn")
            await pilot.pause()
            assert app.dismissed_value is False

    @pytest.mark.asyncio
    async def test_escape_dismisses_with_false(self) -> None:
        app = ConfirmExitTestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert app.dismissed_value is False
