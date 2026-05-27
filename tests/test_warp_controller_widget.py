"""Tests for WarpControllerWidget."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Static

from ksp_mission_control.control.widgets.warp_controller import WarpControllerWidget


class WarpApp(App[None]):
    """Minimal app for testing the warp controller widget."""

    last_rate: float | None

    def __init__(self) -> None:
        super().__init__()
        self.last_rate = None

    def compose(self) -> ComposeResult:
        yield WarpControllerWidget(id="warp-controller")

    def on_warp_controller_widget_rate_selected(self, event: WarpControllerWidget.RateSelected) -> None:
        self.last_rate = event.rate


class TestInitialRender:
    """Initial state and rendering."""

    @pytest.mark.asyncio
    async def test_renders_all_rails_warp_levels(self) -> None:
        async with WarpApp().run_test(size=(120, 10)) as pilot:
            widget = pilot.app.query_one("#warp-controller", WarpControllerWidget)
            buttons = widget.query(Button)
            assert len(buttons) == 8

    @pytest.mark.asyncio
    async def test_one_x_button_is_selected_by_default(self) -> None:
        async with WarpApp().run_test(size=(120, 10)) as pilot:
            widget = pilot.app.query_one("#warp-controller", WarpControllerWidget)
            button = widget.query_one("#warp-rate-1", Button)
            assert button.variant == "primary"
            other = widget.query_one("#warp-rate-100", Button)
            assert other.variant == "default"

    @pytest.mark.asyncio
    async def test_actual_label_shows_one_x_by_default(self) -> None:
        async with WarpApp().run_test(size=(120, 10)) as pilot:
            widget = pilot.app.query_one("#warp-controller", WarpControllerWidget)
            label = widget.query_one("#warp-actual", Static)
            assert "1" in label.render().plain
            assert "×" in label.render().plain


class TestUpdateState:
    """``update_state`` refreshes the selected button and the actual-rate label."""

    @pytest.mark.asyncio
    async def test_selecting_target_rate_highlights_matching_button(self) -> None:
        async with WarpApp().run_test(size=(120, 10)) as pilot:
            widget = pilot.app.query_one("#warp-controller", WarpControllerWidget)
            widget.update_state(target_rate=100.0, actual_rate=100.0)
            await pilot.pause()
            assert widget.query_one("#warp-rate-100", Button).variant == "primary"
            assert widget.query_one("#warp-rate-1", Button).variant == "default"

    @pytest.mark.asyncio
    async def test_actual_rate_shows_clamp_when_below_target(self) -> None:
        async with WarpApp().run_test(size=(120, 10)) as pilot:
            widget = pilot.app.query_one("#warp-controller", WarpControllerWidget)
            # User requested 100x, KSP clamped to 50x.
            widget.update_state(target_rate=100.0, actual_rate=50.0)
            await pilot.pause()
            label = widget.query_one("#warp-actual", Static)
            assert "50" in label.render().plain

    @pytest.mark.asyncio
    async def test_non_rails_target_leaves_no_button_highlighted(self) -> None:
        # If KSP is somehow running at a physics-warp rate (2x, 3x), no
        # rails-warp button should appear selected.
        async with WarpApp().run_test(size=(120, 10)) as pilot:
            widget = pilot.app.query_one("#warp-controller", WarpControllerWidget)
            widget.update_state(target_rate=3.0, actual_rate=3.0)
            await pilot.pause()
            for level in (1, 5, 10, 50, 100, 1000, 10000, 100000):
                assert widget.query_one(f"#warp-rate-{level}", Button).variant == "default"


class TestRateSelected:
    """Clicking a button posts a ``RateSelected`` message."""

    @pytest.mark.asyncio
    async def test_click_posts_rate_selected_message(self) -> None:
        async with WarpApp().run_test(size=(120, 10)) as pilot:
            await pilot.click("#warp-rate-50")
            await pilot.pause()
            assert pilot.app.last_rate == 50.0

    @pytest.mark.asyncio
    async def test_click_on_high_level_button_posts_correct_rate(self) -> None:
        async with WarpApp().run_test(size=(120, 10)) as pilot:
            await pilot.click("#warp-rate-10000")
            await pilot.pause()
            assert pilot.app.last_rate == 10000.0
