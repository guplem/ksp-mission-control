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

    @pytest.mark.asyncio
    async def test_actual_label_marks_clamped_when_below_target(self) -> None:
        # When KSP is running below the user's request, the actual-rate label
        # gets the ``clamped`` class so the styling can call attention to the
        # mismatch.
        async with WarpApp().run_test(size=(120, 10)) as pilot:
            widget = pilot.app.query_one("#warp-controller", WarpControllerWidget)
            widget.update_state(target_rate=100.0, actual_rate=50.0)
            await pilot.pause()
            assert widget.query_one("#warp-actual", Static).has_class("clamped")

    @pytest.mark.asyncio
    async def test_actual_label_clears_clamped_class_when_rates_match(self) -> None:
        # Once KSP catches up to the user's request, the ``clamped`` class
        # must drop so the label returns to the muted styling.
        async with WarpApp().run_test(size=(120, 10)) as pilot:
            widget = pilot.app.query_one("#warp-controller", WarpControllerWidget)
            widget.update_state(target_rate=100.0, actual_rate=50.0)
            await pilot.pause()
            widget.update_state(target_rate=100.0, actual_rate=100.0)
            await pilot.pause()
            assert not widget.query_one("#warp-actual", Static).has_class("clamped")


class TestWrap:
    """Row wraps to as many lines as needed when the widget gets narrower."""

    @pytest.mark.asyncio
    async def test_wide_screen_keeps_single_line_layout(self) -> None:
        # At 120 cells all 10 items fit on one row; rows must be 1.
        async with WarpApp().run_test(size=(120, 10)) as pilot:
            widget = pilot.app.query_one("#warp-controller", WarpControllerWidget)
            await pilot.pause()
            row = widget.query_one("#warp-row")
            assert row.styles.grid_size_rows == 1

    @pytest.mark.asyncio
    async def test_medium_width_wraps_to_two_rows(self) -> None:
        # At 40 cells (40 // 8 = 5 cols), 10 items wrap into 2 rows.
        async with WarpApp().run_test(size=(40, 10)) as pilot:
            widget = pilot.app.query_one("#warp-controller", WarpControllerWidget)
            await pilot.pause()
            row = widget.query_one("#warp-row")
            assert row.styles.grid_size_rows == 2

    @pytest.mark.asyncio
    async def test_narrow_width_wraps_to_more_rows(self) -> None:
        # At 24 cells (24 // 8 = 3 cols), 10 items wrap into 4 rows.
        async with WarpApp().run_test(size=(24, 10)) as pilot:
            widget = pilot.app.query_one("#warp-controller", WarpControllerWidget)
            await pilot.pause()
            row = widget.query_one("#warp-row")
            assert row.styles.grid_size_rows == 4


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

    @pytest.mark.asyncio
    async def test_reclicking_selected_button_posts_again(self) -> None:
        # Re-applying the same rate must still fire the message so KSP gets
        # the command resent. This lets the user recover when KSP clamped
        # the rate (e.g. altitude cap) and the requested level later becomes
        # available without an action restoring it.
        async with WarpApp().run_test(size=(120, 10)) as pilot:
            widget = pilot.app.query_one("#warp-controller", WarpControllerWidget)
            widget.update_state(target_rate=100.0, actual_rate=100.0)
            await pilot.pause()
            pilot.app.last_rate = None
            await pilot.click("#warp-rate-100")
            await pilot.pause()
            assert pilot.app.last_rate == 100.0
