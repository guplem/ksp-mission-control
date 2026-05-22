"""Tests for FlightPlanPicker - display-name logic and plan loading."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, DataTable

from ksp_mission_control.control.actions.flight_plan import FlightPlan
from ksp_mission_control.control.flight_plan_picker import (
    FlightPlanPicker,
    compute_plan_display_name,
    format_plan_cell,
)


class TestComputePlanDisplayName:
    """Tests for compute_plan_display_name (pure function)."""

    def test_top_level_plan_keeps_stem(self, tmp_path: Path) -> None:
        plans_dir = tmp_path
        plan_file = plans_dir / "altitude-steps.plan"
        plan_file.touch()
        counts = {plan_file.parent: 1}
        assert compute_plan_display_name(plan_file, plans_dir, counts) == "altitude-steps"

    def test_nested_non_main_plan_shows_full_path(self, tmp_path: Path) -> None:
        plans_dir = tmp_path
        plan_dir = plans_dir / "science" / "1-low-atmospheric-hop"
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "vessel_control.plan"
        plan_file.touch()
        counts = {plan_dir: 1}
        assert compute_plan_display_name(plan_file, plans_dir, counts) == "science/1-low-atmospheric-hop/vessel_control"

    def test_lone_main_collapses_to_folder(self, tmp_path: Path) -> None:
        plans_dir = tmp_path
        plan_dir = plans_dir / "science" / "1-low-atmospheric-hop"
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "main.plan"
        plan_file.touch()
        counts = {plan_dir: 1}
        assert compute_plan_display_name(plan_file, plans_dir, counts) == "science/1-low-atmospheric-hop"

    def test_main_with_visible_sibling_keeps_stem(self, tmp_path: Path) -> None:
        plans_dir = tmp_path
        plan_dir = plans_dir / "tests-folder"
        plan_dir.mkdir()
        main_file = plan_dir / "main.plan"
        main_file.touch()
        counts = {plan_dir: 2}
        assert compute_plan_display_name(main_file, plans_dir, counts) == "tests-folder/main"

    def test_top_level_main_returns_main(self, tmp_path: Path) -> None:
        plans_dir = tmp_path
        plan_file = plans_dir / "main.plan"
        plan_file.touch()
        counts = {plan_file.parent: 1}
        assert compute_plan_display_name(plan_file, plans_dir, counts) == "main"


class TestLoadPlans:
    """Tests for FlightPlanPicker._load_plans against a real plans directory."""

    def test_hidden_plans_are_excluded(self, tmp_path: Path) -> None:
        (tmp_path / "visible.plan").write_text("hover\n")
        (tmp_path / "secret.plan").write_text("@hidden\nhover\n")
        picker = FlightPlanPicker(plans_dir=tmp_path)
        picker._load_plans()
        assert set(picker._parsed_plans.keys()) == {"visible"}

    def test_lone_main_in_folder_collapses_display_name(self, tmp_path: Path) -> None:
        folder = tmp_path / "mission-a"
        folder.mkdir()
        (folder / "main.plan").write_text("@parallel mission-a/inner.plan\n")
        (folder / "inner.plan").write_text("@hidden\nhover\n")
        picker = FlightPlanPicker(plans_dir=tmp_path)
        picker._load_plans()
        assert "mission-a" in picker._parsed_plans
        assert "mission-a/main" not in picker._parsed_plans
        assert "mission-a/inner" not in picker._parsed_plans

    def test_main_with_visible_sibling_keeps_full_path(self, tmp_path: Path) -> None:
        folder = tmp_path / "mission-b"
        folder.mkdir()
        (folder / "main.plan").write_text("hover\n")
        (folder / "alt.plan").write_text("hover\n")
        picker = FlightPlanPicker(plans_dir=tmp_path)
        picker._load_plans()
        assert "mission-b/main" in picker._parsed_plans
        assert "mission-b/alt" in picker._parsed_plans

    def test_require_craft_drops_plans_without_craft(self, tmp_path: Path) -> None:
        (tmp_path / "with-craft.plan").write_text("@craft fart-1\nhover\n")
        (tmp_path / "no-craft.plan").write_text("hover\n")
        picker = FlightPlanPicker(plans_dir=tmp_path, require_craft=True)
        picker._load_plans()
        assert set(picker._parsed_plans.keys()) == {"with-craft"}

    def test_parse_errors_are_recorded(self, tmp_path: Path) -> None:
        (tmp_path / "bad.plan").write_text("nonexistent_action\n")
        picker = FlightPlanPicker(plans_dir=tmp_path)
        picker._load_plans()
        assert "bad" in picker._parse_errors
        assert picker._parsed_plans == {}

    def test_missing_plans_dir_is_silent(self, tmp_path: Path) -> None:
        missing_dir = tmp_path / "does-not-exist"
        picker = FlightPlanPicker(plans_dir=missing_dir)
        picker._load_plans()
        assert picker._parsed_plans == {}
        assert picker._parse_errors == {}


class TestFormatPlanCell:
    """Tests for format_plan_cell: folder prefix dimmed, leaf at full brightness."""

    def test_no_folder_prefix_is_undimmed(self) -> None:
        cell = format_plan_cell("altitude-steps")
        assert cell.plain == "altitude-steps"
        # Single uniform span, no styling applied.
        styles = {span.style for span in cell.spans}
        assert "dim" not in styles

    def test_single_folder_prefix_is_dimmed(self) -> None:
        cell = format_plan_cell("science/1-low-atmospheric-hop")
        assert cell.plain == "science/1-low-atmospheric-hop"
        dim_ranges = [cell.plain[span.start : span.end] for span in cell.spans if span.style == "dim"]
        assert dim_ranges == ["science/"]

    def test_nested_folder_prefix_is_dimmed_up_to_last_slash(self) -> None:
        cell = format_plan_cell("science/1-low-atmospheric-hop/vessel_control")
        assert cell.plain == "science/1-low-atmospheric-hop/vessel_control"
        dim_ranges = [cell.plain[span.start : span.end] for span in cell.spans if span.style == "dim"]
        assert dim_ranges == ["science/1-low-atmospheric-hop/"]


class _PickerTestApp(App[None]):
    """Host app that pushes a FlightPlanPicker and records its dismiss value."""

    def __init__(self, plans_dir: Path) -> None:
        super().__init__()
        self._plans_dir = plans_dir
        self.dismissed_value: FlightPlan | None | str = "NOT_SET"

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        self.push_screen(FlightPlanPicker(plans_dir=self._plans_dir), callback=self._on_dismiss)

    def _on_dismiss(self, result: FlightPlan | None) -> None:
        self.dismissed_value = result


class TestSelectButton:
    """The Select button confirms the currently highlighted plan.

    No plan is highlighted by default: the DataTable cursor is hidden on
    mount and only revealed once the user clicks a row or navigates with
    the keyboard. The button mirrors that state.
    """

    @pytest.mark.asyncio
    async def test_select_button_disabled_when_no_plans(self, tmp_path: Path) -> None:
        async with _PickerTestApp(tmp_path).run_test() as pilot:
            await pilot.pause()
            select_btn = pilot.app.screen.query_one("#picker-select-btn", Button)
            assert select_btn.disabled is True

    @pytest.mark.asyncio
    async def test_select_button_disabled_by_default_even_with_plans(self, tmp_path: Path) -> None:
        (tmp_path / "a.plan").write_text("hover\n")
        (tmp_path / "b.plan").write_text("hover\n")
        async with _PickerTestApp(tmp_path).run_test() as pilot:
            await pilot.pause()
            select_btn = pilot.app.screen.query_one("#picker-select-btn", Button)
            assert select_btn.disabled is True

    @pytest.mark.asyncio
    async def test_cursor_hidden_until_user_interacts(self, tmp_path: Path) -> None:
        (tmp_path / "a.plan").write_text("hover\n")
        (tmp_path / "b.plan").write_text("hover\n")
        async with _PickerTestApp(tmp_path).run_test() as pilot:
            await pilot.pause()
            table = pilot.app.screen.query_one("#picker-table", DataTable)
            assert table.show_cursor is False

    @pytest.mark.asyncio
    async def test_keyboard_navigation_reveals_cursor_and_enables_button(self, tmp_path: Path) -> None:
        (tmp_path / "a.plan").write_text("hover\n")
        (tmp_path / "b.plan").write_text("land\n")
        async with _PickerTestApp(tmp_path).run_test() as pilot:
            await pilot.pause()
            table = pilot.app.screen.query_one("#picker-table", DataTable)
            table.focus()
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()

            assert table.show_cursor is True
            select_btn = pilot.app.screen.query_one("#picker-select-btn", Button)
            assert select_btn.disabled is False

    @pytest.mark.asyncio
    async def test_select_button_dismisses_with_highlighted_plan(self, tmp_path: Path) -> None:
        (tmp_path / "a.plan").write_text("hover\n")
        (tmp_path / "b.plan").write_text("land\n")
        app = _PickerTestApp(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = pilot.app.screen.query_one("#picker-table", DataTable)
            table.focus()
            await pilot.pause()
            await pilot.press("down")  # reveal cursor at row 0
            await pilot.press("down")  # move to row 1
            await pilot.pause()
            await pilot.click("#picker-select-btn")
            await pilot.pause()

            plan = app.dismissed_value
            assert isinstance(plan, FlightPlan)
            assert plan.name == "b"

    @pytest.mark.asyncio
    async def test_cancel_button_still_dismisses_with_none(self, tmp_path: Path) -> None:
        (tmp_path / "a.plan").write_text("hover\n")
        app = _PickerTestApp(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#picker-cancel-btn")
            await pilot.pause()
            assert app.dismissed_value is None
