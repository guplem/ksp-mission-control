"""Tests for PastePlanDialog - pasted plan parsing and dismiss flow."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static, TextArea

from ksp_mission_control.control.actions.flight_plan import FlightPlan
from ksp_mission_control.control.paste_plan_dialog import PastePlanDialog


class PasteDialogTestApp(App[None]):
    """Host app that pushes a PastePlanDialog and records its dismiss value."""

    def __init__(self) -> None:
        super().__init__()
        self.dismissed_value: FlightPlan | None | str = "NOT_SET"

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        self.push_screen(PastePlanDialog(), callback=self._on_dismiss)

    def _on_dismiss(self, result: FlightPlan | None) -> None:
        self.dismissed_value = result


class TestPastePlanDialog:
    @pytest.mark.asyncio
    async def test_screen_mounts(self) -> None:
        async with PasteDialogTestApp().run_test() as pilot:
            assert isinstance(pilot.app.screen, PastePlanDialog)

    @pytest.mark.asyncio
    async def test_cancel_button_dismisses_with_none(self) -> None:
        app = PasteDialogTestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#paste-cancel-btn")
            await pilot.pause()
            assert app.dismissed_value is None

    @pytest.mark.asyncio
    async def test_confirm_with_valid_text_dismisses_with_plan(self) -> None:
        app = PasteDialogTestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            textarea = pilot.app.screen.query_one("#paste-textarea", TextArea)
            textarea.text = "hover  target_altitude=120\nland\n"
            await pilot.click("#paste-confirm-btn")
            await pilot.pause()

            plan = app.dismissed_value
            assert isinstance(plan, FlightPlan)
            assert plan.name == "pasted"
            assert len(plan.steps) == 2
            assert plan.steps[0].action_id == "hover"
            assert plan.steps[1].action_id == "land"

    @pytest.mark.asyncio
    async def test_confirm_with_empty_text_shows_error_and_stays_open(self) -> None:
        app = PasteDialogTestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#paste-confirm-btn")
            await pilot.pause()

            assert app.dismissed_value == "NOT_SET"
            error_widget = pilot.app.screen.query_one("#paste-error", Static)
            assert "has no steps" in str(error_widget._Static__content)

    @pytest.mark.asyncio
    async def test_confirm_with_invalid_action_shows_error(self) -> None:
        app = PasteDialogTestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            textarea = pilot.app.screen.query_one("#paste-textarea", TextArea)
            textarea.text = "not_a_real_action\n"
            await pilot.click("#paste-confirm-btn")
            await pilot.pause()

            assert app.dismissed_value == "NOT_SET"
            error_widget = pilot.app.screen.query_one("#paste-error", Static)
            assert "Unknown action" in str(error_widget._Static__content)
