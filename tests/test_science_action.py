"""Tests for the ExecuteScienceAction."""

from __future__ import annotations

from typing import Any

import pytest

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionStatus,
    ScienceAction,
    ScienceExperiment,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.science.action import ExecuteScienceAction

ParamValue = float | int | bool | str | None

_DEFAULT_PARAMS: dict[str, Any] = {
    "action": None,
    "index": None,
    "count": None,
    "name": None,
    "title": None,
    "name-tag": None,
}


def _params(**overrides: ParamValue) -> dict[str, Any]:
    return {**_DEFAULT_PARAMS, **overrides}


def _experiment(
    index: int,
    name: str = "temperatureScan",
    title: str = "2HOT Thermometer",
    name_tag: str = "",
    available: bool = True,
    has_data: bool = False,
) -> ScienceExperiment:
    return ScienceExperiment(
        index=index,
        name=name,
        title=title,
        part_title=title,
        name_tag=name_tag,
        available=available,
        has_data=has_data,
        inoperable=False,
        rerunnable=True,
        deployed=False,
        biome="grasslands",
        science_value=0.0,
        science_cap=10.0,
    )


def _tick(action: ExecuteScienceAction, state: State) -> tuple[VesselCommands, Any]:
    commands = VesselCommands()
    result = action.tick(state, commands, 0.5, ActionLogger())
    return commands, result


class TestNoArgs:
    def test_falls_through_to_all_science(self) -> None:
        action = ExecuteScienceAction()
        state = State(science_experiments=(_experiment(0), _experiment(1)))
        action.start(state, _params())
        commands, result = _tick(action, state)
        assert result.status == ActionStatus.SUCCEEDED
        assert commands.all_science == ScienceAction.RUN
        assert commands.science_commands == ()

    def test_action_param_overrides_default(self) -> None:
        action = ExecuteScienceAction()
        state = State(science_experiments=(_experiment(0),))
        action.start(state, _params(action="transmit"))
        commands, _ = _tick(action, state)
        assert commands.all_science == ScienceAction.TRANSMIT

    def test_unknown_action_raises(self) -> None:
        action = ExecuteScienceAction()
        state = State()
        with pytest.raises(ValueError, match="Unknown science action"):
            action.start(state, _params(action="bogus"))


class TestIndex:
    def test_targets_specific_experiment(self) -> None:
        action = ExecuteScienceAction()
        experiments = (_experiment(0, title="A"), _experiment(1, title="B"), _experiment(2, title="C"))
        state = State(science_experiments=experiments)
        action.start(state, _params(index=1))
        commands, result = _tick(action, state)
        assert result.status == ActionStatus.SUCCEEDED
        assert len(commands.science_commands) == 1
        assert commands.science_commands[0].experiment_index == 1
        assert commands.all_science is None

    def test_out_of_range_fails_with_no_match(self) -> None:
        action = ExecuteScienceAction()
        state = State(science_experiments=(_experiment(0),))
        action.start(state, _params(index=5))
        _, result = _tick(action, state)
        assert result.status == ActionStatus.FAILED
        assert "index=5" in result.message

    def test_index_with_count_is_allowed(self) -> None:
        """Index narrows to one match; an extra count cap is a no-op, not an error."""
        action = ExecuteScienceAction()
        state = State(science_experiments=(_experiment(0), _experiment(1)))
        action.start(state, _params(index=0, count=2))
        commands, result = _tick(action, state)
        assert result.status == ActionStatus.SUCCEEDED
        assert tuple(c.experiment_index for c in commands.science_commands) == (0,)


class TestIndexCombinedWithFilters:
    def test_index_with_matching_name_runs(self) -> None:
        action = ExecuteScienceAction()
        experiments = (
            _experiment(0, name="temperatureScan"),
            _experiment(1, name="barometerScan"),
        )
        state = State(science_experiments=experiments)
        action.start(state, _params(index=0, name="temperatureScan"))
        commands, result = _tick(action, state)
        assert result.status == ActionStatus.SUCCEEDED
        assert tuple(c.experiment_index for c in commands.science_commands) == (0,)

    def test_index_with_non_matching_name_fails(self) -> None:
        action = ExecuteScienceAction()
        experiments = (
            _experiment(0, name="temperatureScan"),
            _experiment(1, name="barometerScan"),
        )
        state = State(science_experiments=experiments)
        action.start(state, _params(index=0, name="barometerScan"))
        _, result = _tick(action, state)
        assert result.status == ActionStatus.FAILED
        assert "barometerScan" in result.message


class TestNameFilter:
    def test_runs_all_matching_when_no_count(self) -> None:
        action = ExecuteScienceAction()
        experiments = (
            _experiment(0, name="temperatureScan"),
            _experiment(1, name="barometerScan"),
            _experiment(2, name="temperatureScan"),
        )
        state = State(science_experiments=experiments)
        action.start(state, _params(name="temperatureScan"))
        commands, result = _tick(action, state)
        assert result.status == ActionStatus.SUCCEEDED
        assert tuple(c.experiment_index for c in commands.science_commands) == (0, 2)

    def test_no_matches_fails(self) -> None:
        action = ExecuteScienceAction()
        state = State(science_experiments=(_experiment(0, name="temperatureScan"),))
        action.start(state, _params(name="seismicScan"))
        _, result = _tick(action, state)
        assert result.status == ActionStatus.FAILED
        assert "seismicScan" in result.message


class TestTitleFilter:
    def test_filters_by_exact_title(self) -> None:
        action = ExecuteScienceAction()
        experiments = (
            _experiment(0, title="2HOT Thermometer"),
            _experiment(1, title="PresMat Barometer"),
        )
        state = State(science_experiments=experiments)
        action.start(state, _params(title="2HOT Thermometer"))
        commands, result = _tick(action, state)
        assert result.status == ActionStatus.SUCCEEDED
        assert tuple(c.experiment_index for c in commands.science_commands) == (0,)


class TestNameTagFilter:
    def test_filters_by_name_tag(self) -> None:
        action = ExecuteScienceAction()
        experiments = (_experiment(0, name_tag="T1"), _experiment(1, name_tag="T2"), _experiment(2, name_tag="T1"))
        state = State(science_experiments=experiments)
        action.start(state, _params(**{"name-tag": "T1"}))
        commands, result = _tick(action, state)
        assert result.status == ActionStatus.SUCCEEDED
        assert tuple(c.experiment_index for c in commands.science_commands) == (0, 2)


class TestCombinedFilters:
    def test_filters_combine_with_and(self) -> None:
        action = ExecuteScienceAction()
        experiments = (
            _experiment(0, name="temperatureScan", name_tag="T1"),
            _experiment(1, name="temperatureScan", name_tag="T2"),
            _experiment(2, name="barometerScan", name_tag="T1"),
        )
        state = State(science_experiments=experiments)
        action.start(state, _params(name="temperatureScan", **{"name-tag": "T1"}))
        commands, _ = _tick(action, state)
        assert tuple(c.experiment_index for c in commands.science_commands) == (0,)


class TestCount:
    def test_takes_first_n_matches(self) -> None:
        action = ExecuteScienceAction()
        experiments = tuple(_experiment(i, name="temperatureScan") for i in range(5))
        state = State(science_experiments=experiments)
        action.start(state, _params(name="temperatureScan", count=2))
        commands, _ = _tick(action, state)
        assert tuple(c.experiment_index for c in commands.science_commands) == (0, 1)

    def test_count_without_filter_picks_first_n_fresh(self) -> None:
        action = ExecuteScienceAction()
        experiments = (_experiment(0), _experiment(1), _experiment(2))
        state = State(science_experiments=experiments)
        action.start(state, _params(count=2))
        commands, _ = _tick(action, state)
        assert tuple(c.experiment_index for c in commands.science_commands) == (0, 1)


class TestSkipsAlreadyRun:
    def test_count_skips_experiments_with_data(self) -> None:
        """Two consecutive 'count=2 thermometer' calls pick different experiments."""
        action = ExecuteScienceAction()
        experiments = (
            _experiment(0, name="temperatureScan", has_data=True),
            _experiment(1, name="temperatureScan", has_data=True),
            _experiment(2, name="temperatureScan", has_data=False),
            _experiment(3, name="temperatureScan", has_data=False),
        )
        state = State(science_experiments=experiments)
        action.start(state, _params(name="temperatureScan", count=2))
        commands, _ = _tick(action, state)
        assert tuple(c.experiment_index for c in commands.science_commands) == (2, 3)

    def test_filter_alone_skips_experiments_with_data(self) -> None:
        action = ExecuteScienceAction()
        experiments = (
            _experiment(0, name="temperatureScan", has_data=True),
            _experiment(1, name="temperatureScan", has_data=False),
        )
        state = State(science_experiments=experiments)
        action.start(state, _params(name="temperatureScan"))
        commands, _ = _tick(action, state)
        assert tuple(c.experiment_index for c in commands.science_commands) == (1,)

    def test_filter_skips_unavailable_experiments(self) -> None:
        action = ExecuteScienceAction()
        experiments = (
            _experiment(0, name="temperatureScan", available=False),
            _experiment(1, name="temperatureScan", available=True),
        )
        state = State(science_experiments=experiments)
        action.start(state, _params(name="temperatureScan"))
        commands, _ = _tick(action, state)
        assert tuple(c.experiment_index for c in commands.science_commands) == (1,)
