"""Tests for TelemetryDisplayWidget - historical state display."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from ksp_mission_control.control.actions.base import State
from ksp_mission_control.control.widgets.telemetry_display import TelemetryDisplayWidget


class TelemetryApp(App[None]):
    """Minimal app for testing the telemetry display widget."""

    def compose(self) -> ComposeResult:
        yield TelemetryDisplayWidget(id="telemetry-display")


class TestHistoricalState:
    """Verify that the widget freezes on historical state and resumes on live."""

    @pytest.mark.asyncio
    async def test_live_updates_render_normally(self) -> None:
        async with TelemetryApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#telemetry-display", TelemetryDisplayWidget)
            state = State(altitude_surface=500.0)
            widget.update_vessel_state(state)
            await pilot.pause()
            flight = widget.query_one("#telemetry-flight", Static)
            assert "500" in flight.render().plain

    @pytest.mark.asyncio
    async def test_show_historical_freezes_live_updates(self) -> None:
        async with TelemetryApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#telemetry-display", TelemetryDisplayWidget)
            historical = State(altitude_surface=100.0)
            widget.show_historical_state(historical, met=30.0)
            await pilot.pause()

            # Live update should be ignored while frozen
            live = State(altitude_surface=999.0)
            widget.update_vessel_state(live)
            await pilot.pause()

            flight = widget.query_one("#telemetry-flight", Static)
            assert "100" in flight.render().plain
            assert "999" not in flight.render().plain

    @pytest.mark.asyncio
    async def test_historical_title_shows_met(self) -> None:
        async with TelemetryApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#telemetry-display", TelemetryDisplayWidget)
            widget.show_historical_state(State(), met=65.5)
            await pilot.pause()
            title = widget.query_one("#telemetry-title", Static)
            rendered = str(title.render().plain)
            assert "historical" in rendered
            assert "T+01:05.5" in rendered

    @pytest.mark.asyncio
    async def test_resume_live_accepts_updates_again(self) -> None:
        async with TelemetryApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#telemetry-display", TelemetryDisplayWidget)
            widget.show_historical_state(State(altitude_surface=100.0), met=10.0)
            await pilot.pause()

            widget.resume_live()
            live = State(altitude_surface=777.0)
            widget.update_vessel_state(live)
            await pilot.pause()

            flight = widget.query_one("#telemetry-flight", Static)
            assert "777" in flight.render().plain

    @pytest.mark.asyncio
    async def test_resume_live_clears_historical_title(self) -> None:
        async with TelemetryApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#telemetry-display", TelemetryDisplayWidget)
            widget.show_historical_state(State(), met=10.0)
            await pilot.pause()

            widget.resume_live()
            await pilot.pause()
            title = widget.query_one("#telemetry-title", Static)
            assert "historical" not in str(title.render().plain)
