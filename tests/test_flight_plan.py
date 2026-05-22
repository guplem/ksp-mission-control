"""Tests for flight plan data structures and parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from ksp_mission_control.control.actions.flight_plan import (
    FlightPlan,
    FlightPlanStep,
    ParallelStep,
    parse_flight_plan,
    parse_flight_plan_text,
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
        plan_file.write_text("wait_for  apoapsis=true\n")
        plan = parse_flight_plan(plan_file)
        assert plan.steps[0].param_values["apoapsis"] is True

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

    def test_bare_boolean_flag(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "bare_flag.plan"
        plan_file.write_text("wait_for  apoapsis\n")
        plan = parse_flight_plan(plan_file)
        assert plan.steps[0].param_values["apoapsis"] is True

    def test_bare_non_boolean_param_raises(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "bad_bare.plan"
        plan_file.write_text("hover  target_altitude\n")
        with pytest.raises(ValueError, match="requires a value"):
            parse_flight_plan(plan_file)

    def test_unknown_bare_param_raises(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "bad_format.plan"
        plan_file.write_text("hover  notakeyvalue\n")
        with pytest.raises(ValueError, match="Unknown parameter"):
            parse_flight_plan(plan_file)

    def test_empty_plan_raises(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "empty.plan"
        plan_file.write_text("# Only comments\n\n")
        with pytest.raises(ValueError, match="has no steps"):
            parse_flight_plan(plan_file)

    def test_invalid_bool_value_raises(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "bad_bool.plan"
        plan_file.write_text("wait_for  apoapsis=maybe\n")
        with pytest.raises(ValueError, match="Invalid bool value"):
            parse_flight_plan(plan_file)

    def test_error_includes_line_number(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "line_error.plan"
        plan_file.write_text("hover\n# comment\nbad_action\n")
        with pytest.raises(ValueError, match="Line 3"):
            parse_flight_plan(plan_file)


class TestParseParallelDirective:
    """Tests for @parallel directive parsing in .plan files."""

    def test_parallel_directive_becomes_inline_step(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "with_parallel.plan"
        plan_file.write_text("@parallel science/collect.plan\nhover\n")
        plan = parse_flight_plan(plan_file)
        assert len(plan.steps) == 2
        assert plan.steps[0] == ParallelStep(plan_path="science/collect.plan")
        assert isinstance(plan.steps[1], FlightPlanStep)
        assert plan.steps[1].action_id == "hover"

    def test_multiple_parallel_directives_preserve_order(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "multi_parallel.plan"
        plan_file.write_text("@parallel science/collect.plan\n@parallel comms/relay.plan\nhover\n")
        plan = parse_flight_plan(plan_file)
        assert plan.steps == (
            ParallelStep(plan_path="science/collect.plan"),
            ParallelStep(plan_path="comms/relay.plan"),
            FlightPlanStep(action_id="hover", param_values={}),
        )

    def test_parallel_position_preserved_between_actions(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "interleaved.plan"
        plan_file.write_text("@parallel a.plan\nhover  target_altitude=100\n@parallel b.plan\nland\n")
        plan = parse_flight_plan(plan_file)
        assert len(plan.steps) == 4
        assert isinstance(plan.steps[0], ParallelStep)
        assert plan.steps[0].plan_path == "a.plan"
        assert isinstance(plan.steps[1], FlightPlanStep)
        assert plan.steps[1].action_id == "hover"
        assert isinstance(plan.steps[2], ParallelStep)
        assert plan.steps[2].plan_path == "b.plan"
        assert isinstance(plan.steps[3], FlightPlanStep)
        assert plan.steps[3].action_id == "land"

    def test_parallel_with_steps_and_comments(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "mixed.plan"
        plan_file.write_text("# Main flight plan\n@parallel science/hop.plan\n\nhover  target_altitude=100\nland\n")
        plan = parse_flight_plan(plan_file)
        assert len(plan.steps) == 3
        assert isinstance(plan.steps[0], ParallelStep)
        assert plan.steps[0].plan_path == "science/hop.plan"

    def test_no_parallel_yields_only_action_steps(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "no_parallel.plan"
        plan_file.write_text("hover\n")
        plan = parse_flight_plan(plan_file)
        assert all(isinstance(step, FlightPlanStep) for step in plan.steps)

    def test_parallel_empty_path_raises(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "bad_parallel.plan"
        plan_file.write_text("@parallel \nhover\n")
        with pytest.raises(ValueError, match="@parallel requires a file path"):
            parse_flight_plan(plan_file)

    def test_plan_with_only_parallel_is_valid(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "only_parallel.plan"
        plan_file.write_text("@parallel science/collect.plan\n")
        plan = parse_flight_plan(plan_file)
        assert plan.steps == (ParallelStep(plan_path="science/collect.plan"),)

    def test_plan_with_no_steps_and_no_parallel_raises(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "truly_empty.plan"
        plan_file.write_text("# Just comments\n")
        with pytest.raises(ValueError, match="has no steps"):
            parse_flight_plan(plan_file)

    def test_parallel_step_plan_name_strips_extension(self) -> None:
        step = ParallelStep(plan_path="science/1-atmospheric-hop/vessel_control.plan")
        assert step.plan_name == "vessel_control"


class TestParseCraftDirective:
    """Tests for @craft directive parsing in .plan files."""

    def test_craft_directive_parsed(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "with_craft.plan"
        plan_file.write_text("@craft fart-1\nhover\n")
        plan = parse_flight_plan(plan_file)
        assert plan.craft == "fart-1"
        assert len(plan.steps) == 1

    def test_no_craft_defaults_to_none(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "no_craft.plan"
        plan_file.write_text("hover\n")
        plan = parse_flight_plan(plan_file)
        assert plan.craft is None

    def test_craft_empty_name_raises(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "bad_craft.plan"
        plan_file.write_text("@craft \nhover\n")
        with pytest.raises(ValueError, match="@craft requires a craft name"):
            parse_flight_plan(plan_file)

    def test_craft_bare_directive_raises(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "bare_craft.plan"
        plan_file.write_text("@craft\nhover\n")
        with pytest.raises(ValueError, match="@craft requires a craft name"):
            parse_flight_plan(plan_file)

    def test_duplicate_craft_raises(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "dup_craft.plan"
        plan_file.write_text("@craft fart-1\n@craft fart-2\nhover\n")
        with pytest.raises(ValueError, match="duplicate @craft"):
            parse_flight_plan(plan_file)

    def test_craft_with_parallel_and_steps(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "all_directives.plan"
        plan_file.write_text("@craft fart-2\n@parallel science/collect.plan\nhover\n")
        plan = parse_flight_plan(plan_file)
        assert plan.craft == "fart-2"
        assert plan.steps == (
            ParallelStep(plan_path="science/collect.plan"),
            FlightPlanStep(action_id="hover", param_values={}),
        )

    def test_craft_only_no_steps_raises(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "craft_only.plan"
        plan_file.write_text("@craft fart-1\n")
        with pytest.raises(ValueError, match="has no steps"):
            parse_flight_plan(plan_file)

    def test_craft_with_only_parallel_is_valid(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "craft_parallel.plan"
        plan_file.write_text("@craft fart-1\n@parallel science/collect.plan\n")
        plan = parse_flight_plan(plan_file)
        assert plan.craft == "fart-1"
        assert plan.steps == (ParallelStep(plan_path="science/collect.plan"),)


class TestParseHiddenDirective:
    """Tests for @hidden directive parsing in .plan files."""

    def test_hidden_directive_sets_flag(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "secret.plan"
        plan_file.write_text("@hidden\nhover\n")
        plan = parse_flight_plan(plan_file)
        assert plan.is_hidden is True
        assert len(plan.steps) == 1

    def test_no_hidden_defaults_to_false(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "visible.plan"
        plan_file.write_text("hover\n")
        plan = parse_flight_plan(plan_file)
        assert plan.is_hidden is False

    def test_hidden_is_idempotent(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "double_hidden.plan"
        plan_file.write_text("@hidden\n@hidden\nhover\n")
        plan = parse_flight_plan(plan_file)
        assert plan.is_hidden is True

    def test_hidden_with_arguments_raises(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "bad_hidden.plan"
        plan_file.write_text("@hidden true\nhover\n")
        with pytest.raises(ValueError, match="@hidden takes no arguments"):
            parse_flight_plan(plan_file)

    def test_hidden_combines_with_craft_and_parallel(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "all_directives.plan"
        plan_file.write_text("@hidden\n@craft fart-1\n@parallel science/collect.plan\nhover\n")
        plan = parse_flight_plan(plan_file)
        assert plan.is_hidden is True
        assert plan.craft == "fart-1"
        assert plan.steps == (
            ParallelStep(plan_path="science/collect.plan"),
            FlightPlanStep(action_id="hover", param_values={}),
        )


class TestParseFlightPlanText:
    """Tests for parse_flight_plan_text (string input, no file required)."""

    def test_parses_inline_plan(self) -> None:
        plan = parse_flight_plan_text("hover  target_altitude=200\nland\n")
        assert plan.name == "inline"
        assert len(plan.steps) == 2
        assert plan.steps[0] == FlightPlanStep(action_id="hover", param_values={"target_altitude": 200.0})
        assert plan.steps[1] == FlightPlanStep(action_id="land", param_values={})

    def test_uses_explicit_name(self) -> None:
        plan = parse_flight_plan_text("hover\n", name="pasted")
        assert plan.name == "pasted"

    def test_supports_directives(self) -> None:
        plan = parse_flight_plan_text("@craft fart-1\n@parallel sub.plan\nhover\n", name="pasted")
        assert plan.craft == "fart-1"
        assert plan.steps[0] == ParallelStep(plan_path="sub.plan")
        assert plan.steps[1].action_id == "hover"

    def test_empty_text_raises_with_name(self) -> None:
        with pytest.raises(ValueError, match="'pasted' has no steps"):
            parse_flight_plan_text("# only comment\n", name="pasted")

    def test_line_numbers_propagate(self) -> None:
        with pytest.raises(ValueError, match="Line 3"):
            parse_flight_plan_text("hover\n# comment\nbogus_action\n")
