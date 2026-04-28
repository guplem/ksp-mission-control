"""Tests for the RunScienceAction."""

from __future__ import annotations

from ksp_mission_control.control.actions.base import (
    ActionLogger,
    ActionStatus,
    ParamType,
    ScienceAction,
    ScienceExperiment,
    VesselCommands,
    VesselState,
)
from ksp_mission_control.control.actions.run_science.action import RunScienceAction

_SAMPLE_EXPERIMENTS = (
    ScienceExperiment(
        index=0,
        name="temperatureScan",
        title="2HOT Thermometer",
        part_title="2HOT Thermometer",
        available=True,
        has_data=False,
        inoperable=False,
        rerunnable=True,
        deployed=False,
        biome="Shores",
        science_value=0.0,
        science_cap=8.0,
    ),
    ScienceExperiment(
        index=1,
        name="mysteryGoo",
        title="Mystery Goo Observation",
        part_title="Mystery Goo Containment Unit",
        available=True,
        has_data=False,
        inoperable=False,
        rerunnable=False,
        deployed=False,
        biome="Shores",
        science_value=0.0,
        science_cap=13.0,
    ),
)


class TestRunScienceActionMetadata:
    """Tests for class-level metadata."""

    def test_action_id(self) -> None:
        assert RunScienceAction.action_id == "run_science"

    def test_label(self) -> None:
        assert RunScienceAction.label == "Run Science"

    def test_has_wait_for_apoapsis_param(self) -> None:
        param_ids = [p.param_id for p in RunScienceAction.params]
        assert "wait_for_apoapsis" in param_ids

    def test_wait_for_apoapsis_is_optional_bool_with_default_false(self) -> None:
        param = next(p for p in RunScienceAction.params if p.param_id == "wait_for_apoapsis")
        assert param.required is False
        assert param.default is False
        assert param.param_type == ParamType.BOOL


class TestRunScienceActionImmediate:
    """Tests for immediate science activation (wait_for_apoapsis=False)."""

    def _make_started_action(self, experiments: tuple[ScienceExperiment, ...] = _SAMPLE_EXPERIMENTS) -> RunScienceAction:
        action = RunScienceAction()
        state = VesselState(science_experiments=experiments)
        action.start(state, {"wait_for_apoapsis": False})
        return action

    def test_sets_all_science_run_on_first_tick(self) -> None:
        action = self._make_started_action()
        commands = VesselCommands()
        action.tick(VesselState(science_experiments=_SAMPLE_EXPERIMENTS), commands, dt=0.5, log=ActionLogger())
        assert commands.all_science == ScienceAction.RUN

    def test_succeeds_on_first_tick(self) -> None:
        action = self._make_started_action()
        result = action.tick(VesselState(science_experiments=_SAMPLE_EXPERIMENTS), VesselCommands(), dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.SUCCEEDED

    def test_logs_available_experiment_count(self) -> None:
        action = self._make_started_action()
        log = ActionLogger()
        action.tick(VesselState(science_experiments=_SAMPLE_EXPERIMENTS), VesselCommands(), dt=0.5, log=log)
        assert any("2" in entry.message for entry in log.entries)

    def test_logs_zero_when_no_experiments(self) -> None:
        action = self._make_started_action(experiments=())
        log = ActionLogger()
        action.tick(VesselState(), VesselCommands(), dt=0.5, log=log)
        assert any("0" in entry.message for entry in log.entries)


class TestRunScienceActionWaitForApoapsis:
    """Tests for science activation at apoapsis (wait_for_apoapsis=True)."""

    def _make_started_action(self, speed_vertical: float = 50.0) -> RunScienceAction:
        action = RunScienceAction()
        state = VesselState(speed_vertical=speed_vertical, science_experiments=_SAMPLE_EXPERIMENTS)
        action.start(state, {"wait_for_apoapsis": True})
        return action

    def test_running_while_ascending(self) -> None:
        action = self._make_started_action(speed_vertical=50.0)
        state = VesselState(speed_vertical=30.0, science_experiments=_SAMPLE_EXPERIMENTS)
        commands = VesselCommands()
        result = action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert commands.all_science is None

    def test_triggers_when_vertical_speed_crosses_zero(self) -> None:
        action = self._make_started_action(speed_vertical=50.0)
        # Still ascending
        state_ascending = VesselState(speed_vertical=5.0, science_experiments=_SAMPLE_EXPERIMENTS)
        action.tick(state_ascending, VesselCommands(), dt=0.5, log=ActionLogger())

        # Now descending: crossed apoapsis
        state_descending = VesselState(speed_vertical=-1.0, altitude_sea=20000.0, science_experiments=_SAMPLE_EXPERIMENTS)
        commands = VesselCommands()
        result = action.tick(state_descending, commands, dt=0.5, log=ActionLogger())
        assert commands.all_science == ScienceAction.RUN
        assert result.status == ActionStatus.SUCCEEDED

    def test_does_not_trigger_if_started_while_descending(self) -> None:
        """If the vessel is already descending at start, it should not trigger immediately."""
        action = self._make_started_action(speed_vertical=-10.0)
        state = VesselState(speed_vertical=-15.0, science_experiments=_SAMPLE_EXPERIMENTS)
        commands = VesselCommands()
        result = action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert result.status == ActionStatus.RUNNING
        assert commands.all_science is None

    def test_triggers_at_exact_zero_vertical_speed(self) -> None:
        action = self._make_started_action(speed_vertical=10.0)
        state = VesselState(speed_vertical=0.0, altitude_sea=20000.0, science_experiments=_SAMPLE_EXPERIMENTS)
        commands = VesselCommands()
        result = action.tick(state, commands, dt=0.5, log=ActionLogger())
        assert commands.all_science == ScienceAction.RUN
        assert result.status == ActionStatus.SUCCEEDED


class TestRunScienceActionStop:
    """Tests for stop() cleanup."""

    def test_stop_logs_message(self) -> None:
        action = RunScienceAction()
        state = VesselState()
        action.start(state, {"wait_for_apoapsis": False})
        log = ActionLogger()
        action.stop(state, VesselCommands(), log=log)
        assert any("stopped" in entry.message.lower() for entry in log.entries)
