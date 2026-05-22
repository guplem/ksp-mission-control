"""Tests for TelemetryDisplayWidget - historical state display and search filter."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Static

from ksp_mission_control.control.actions.base import ScienceExperiment, State
from ksp_mission_control.control.widgets.telemetry_display import (
    ScienceCardWidget,
    TelemetryDisplayWidget,
    filter_telemetry_text,
    science_matches_query,
)


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


class TestFilterTelemetryText:
    """Pure-function tests for filter_telemetry_text (section-aware keep)."""

    SAMPLE = "\n".join(
        [
            "[b]Overview[/b]",
            "Vessel: Test",
            "Situation: orbit",
            "",
            "[b]Altitude[/b]",
            "Surface: 100 m",
            "Sea level: 200 m",
            "",
            "[b]Speed[/b]",
            "Vertical: 5 m/s",
        ]
    )

    def test_empty_query_returns_input_unchanged(self) -> None:
        assert filter_telemetry_text(self.SAMPLE, "") == self.SAMPLE

    def test_query_matches_section_via_header(self) -> None:
        result = filter_telemetry_text(self.SAMPLE, "altitude")
        assert "[b]Altitude[/b]" in result
        assert "Surface: 100 m" in result
        assert "[b]Overview[/b]" not in result
        assert "[b]Speed[/b]" not in result

    def test_query_matches_section_via_line(self) -> None:
        result = filter_telemetry_text(self.SAMPLE, "vessel")
        assert "[b]Overview[/b]" in result
        assert "Vessel: Test" in result
        assert "[b]Altitude[/b]" not in result

    def test_query_is_case_insensitive(self) -> None:
        assert "Vessel: Test" in filter_telemetry_text(self.SAMPLE, "VESSEL")

    def test_no_match_returns_empty_string(self) -> None:
        assert filter_telemetry_text(self.SAMPLE, "nothing-like-this") == ""

    def test_markup_tags_are_ignored_in_match(self) -> None:
        text = "[red]Liquid fuel:[/red] 100"
        # Searching for the markup tag itself should not match;
        # only the visible content does.
        assert filter_telemetry_text(text, "red") == ""
        assert filter_telemetry_text(text, "fuel") == text


class TestScienceMatchesQuery:
    """Pure-function tests for science_matches_query."""

    def _make_exp(self, title: str, name: str = "expA", part_title: str = "Pod", name_tag: str = "") -> ScienceExperiment:
        return ScienceExperiment(
            index=0,
            name=name,
            title=title,
            part_title=part_title,
            name_tag=name_tag,
            available=True,
            has_data=False,
            inoperable=False,
            rerunnable=True,
            deployed=False,
            biome="",
            science_value=0.0,
            science_cap=10.0,
        )

    def test_empty_query_matches(self) -> None:
        assert science_matches_query(self._make_exp("Temperature Scan"), "") is True

    def test_matches_title(self) -> None:
        assert science_matches_query(self._make_exp("Temperature Scan"), "temp") is True

    def test_matches_internal_name(self) -> None:
        assert science_matches_query(self._make_exp("X", name="mysteryGoo"), "goo") is True

    def test_matches_part_title(self) -> None:
        assert science_matches_query(self._make_exp("X", part_title="Mystery Goo Container"), "container") is True

    def test_matches_name_tag(self) -> None:
        assert science_matches_query(self._make_exp("X", name_tag="upper-stage"), "upper") is True

    def test_no_match(self) -> None:
        assert science_matches_query(self._make_exp("Temperature Scan"), "barometer") is False


class TestSearchFilter:
    """Pilot tests for the live search input."""

    @pytest.mark.asyncio
    async def test_typing_filters_orbit_column(self) -> None:
        async with TelemetryApp().run_test(size=(160, 60)) as pilot:
            widget = pilot.app.query_one("#telemetry-display", TelemetryDisplayWidget)
            widget.update_vessel_state(State(orbit_apoapsis=12345.0))
            await pilot.pause()

            search = widget.query_one("#telemetry-search", Input)
            search.value = "apoapsis"
            await pilot.pause()

            orbit = widget.query_one("#telemetry-orbit", Static)
            rendered = orbit.render().plain
            assert "Apoapsis:" in rendered
            assert "Inclination" not in rendered  # other Orbit lines hidden

            flight = widget.query_one("#telemetry-flight", Static)
            assert flight.render().plain == ""  # no apoapsis content in flight column

    @pytest.mark.asyncio
    async def test_clearing_search_restores_all_sections(self) -> None:
        async with TelemetryApp().run_test(size=(160, 60)) as pilot:
            widget = pilot.app.query_one("#telemetry-display", TelemetryDisplayWidget)
            widget.update_vessel_state(State(altitude_surface=500.0))
            await pilot.pause()

            search = widget.query_one("#telemetry-search", Input)
            search.value = "apoapsis"
            await pilot.pause()
            assert widget.query_one("#telemetry-flight", Static).render().plain == ""

            search.value = ""
            await pilot.pause()
            flight = widget.query_one("#telemetry-flight", Static)
            assert "Vessel:" in flight.render().plain
            assert "500" in flight.render().plain

    @pytest.mark.asyncio
    async def test_live_updates_respect_active_filter(self) -> None:
        async with TelemetryApp().run_test(size=(160, 60)) as pilot:
            widget = pilot.app.query_one("#telemetry-display", TelemetryDisplayWidget)
            widget.update_vessel_state(State())
            await pilot.pause()

            search = widget.query_one("#telemetry-search", Input)
            search.value = "altitude"
            await pilot.pause()

            # A subsequent state update must keep the filter active.
            widget.update_vessel_state(State(altitude_surface=12345.0))
            await pilot.pause()

            flight = widget.query_one("#telemetry-flight", Static).render().plain
            assert "Altitude" in flight
            assert "12,345" in flight
            assert "Atmosphere" not in flight

    @pytest.mark.asyncio
    async def test_science_cards_are_filtered(self) -> None:
        experiments = (
            ScienceExperiment(
                index=0,
                name="temperatureScan",
                title="Temperature Scan",
                part_title="Thermometer",
                name_tag="",
                available=True,
                has_data=False,
                inoperable=False,
                rerunnable=True,
                deployed=False,
                biome="",
                science_value=0.0,
                science_cap=5.0,
            ),
            ScienceExperiment(
                index=1,
                name="mysteryGoo",
                title="Mystery Goo Observation",
                part_title="Goo Container",
                name_tag="",
                available=True,
                has_data=False,
                inoperable=False,
                rerunnable=True,
                deployed=False,
                biome="",
                science_value=0.0,
                science_cap=5.0,
            ),
        )
        async with TelemetryApp().run_test(size=(160, 60)) as pilot:
            widget = pilot.app.query_one("#telemetry-display", TelemetryDisplayWidget)
            widget.update_vessel_state(State(science_experiments=experiments))
            await pilot.pause()
            assert len(list(widget.query(ScienceCardWidget))) == 2

            search = widget.query_one("#telemetry-search", Input)
            search.value = "goo"
            await pilot.pause()

            cards = list(widget.query(ScienceCardWidget))
            assert len(cards) == 1
            assert "Goo" in cards[0].render().plain
