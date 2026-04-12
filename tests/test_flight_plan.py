"""Tests for flight plan data structures and parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from ksp_mission_control.control.actions.flight_plan import (
    FlightPlan,
    FlightPlanStep,
    parse_flight_plan,
)


class TestFlightPlanDataStructures:
    """Tests for FlightPlan and FlightPlanStep dataclasses."""

    def test_step_stores_action_id_and_params(self) -> None:
        step = FlightPlanStep(action_id="hover", param_values={"target_altitude": 100.0})
        assert step.action_id == "hover"
        assert step.param_values == {"target_altitude": 100.0}

    def test_plan_stores_name_and_steps(self) -> None:
        steps = (
            FlightPlanStep(action_id="hover", param_values={}),
            FlightPlanStep(action_id="land", param_values={}),
        )
        plan = FlightPlan(name="test", steps=steps)
        assert plan.name == "test"
        assert len(plan.steps) == 2

    def test_step_is_frozen(self) -> None:
        step = FlightPlanStep(action_id="hover", param_values={})
        with pytest.raises(AttributeError):
            step.action_id = "land"  # type: ignore[misc]

    def test_plan_is_frozen(self) -> None:
        plan = FlightPlan(name="test", steps=())
        with pytest.raises(AttributeError):
            plan.name = "other"  # type: ignore[misc]


class TestParseFlightPlan:
    """Tests for parsing .plan files."""

    def test_parse_single_action_no_params(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "simple.plan"
        plan_file.write_text("hover\n")
        plan = parse_flight_plan(plan_file)
        assert plan.name == "simple"
        assert len(plan.steps) == 1
        assert plan.steps[0].action_id == "hover"
        assert plan.steps[0].param_values == {}

    def test_parse_action_with_float_params(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "with_params.plan"
        plan_file.write_text("hover  target_altitude=200.0  hover_duration=30\n")
        plan = parse_flight_plan(plan_file)
        assert plan.steps[0].param_values["target_altitude"] == 200.0
        assert plan.steps[0].param_values["hover_duration"] == 30.0

    def test_parse_action_with_bool_params(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "bool.plan"
        plan_file.write_text("hover  land_at_end=true\n")
        plan = parse_flight_plan(plan_file)
        assert plan.steps[0].param_values["land_at_end"] is True

    def test_parse_multiple_steps(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "multi.plan"
        plan_file.write_text("hover  target_altitude=100  hover_duration=10\nland\n")
        plan = parse_flight_plan(plan_file)
        assert len(plan.steps) == 2
        assert plan.steps[0].action_id == "hover"
        assert plan.steps[1].action_id == "land"

    def test_comments_and_blank_lines_ignored(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "comments.plan"
        plan_file.write_text("# This is a comment\n\nhover\n\n# Another comment\nland\n")
        plan = parse_flight_plan(plan_file)
        assert len(plan.steps) == 2

    def test_plan_name_from_filename(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "hover-and-land.plan"
        plan_file.write_text("hover\n")
        plan = parse_flight_plan(plan_file)
        assert plan.name == "hover-and-land"

    def test_unknown_action_raises(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "bad.plan"
        plan_file.write_text("nonexistent_action\n")
        with pytest.raises(ValueError, match="Unknown action"):
            parse_flight_plan(plan_file)

    def test_unknown_param_raises(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "bad_param.plan"
        plan_file.write_text("hover  fake_param=123\n")
        with pytest.raises(ValueError, match="Unknown parameter"):
            parse_flight_plan(plan_file)

    def test_invalid_param_format_raises(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "bad_format.plan"
        plan_file.write_text("hover  notakeyvalue\n")
        with pytest.raises(ValueError, match="Expected key=value"):
            parse_flight_plan(plan_file)

    def test_empty_plan_raises(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "empty.plan"
        plan_file.write_text("# Only comments\n\n")
        with pytest.raises(ValueError, match="has no steps"):
            parse_flight_plan(plan_file)

    def test_invalid_bool_value_raises(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "bad_bool.plan"
        plan_file.write_text("hover  land_at_end=maybe\n")
        with pytest.raises(ValueError, match="Invalid bool value"):
            parse_flight_plan(plan_file)

    def test_error_includes_line_number(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "line_error.plan"
        plan_file.write_text("hover\n# comment\nbad_action\n")
        with pytest.raises(ValueError, match="Line 3"):
            parse_flight_plan(plan_file)
