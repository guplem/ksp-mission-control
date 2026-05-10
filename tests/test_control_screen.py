"""Tests for tick history formatting in the control screen."""

from __future__ import annotations

from xml.etree.ElementTree import fromstring

from ksp_mission_control.control.actions.base import (
    ActionStatus,
    LogEntry,
    LogLevel,
    State,
    VesselCommands,
)
from ksp_mission_control.control.actions.multi_track_executor import (
    MultiTrackSnapshot,
    TrackSnapshot,
)
from ksp_mission_control.control.actions.plan_executor import PlanSnapshot, StepStatus
from ksp_mission_control.control.actions.runner import RunnerSnapshot
from ksp_mission_control.control.screen import _format_tick_history
from ksp_mission_control.control.tick_record import TickRecord

_DEFAULT_STATE = State()
_EMPTY_SNAP = MultiTrackSnapshot()


def _ad_hoc_action_snap(action_id: str, label: str, status: ActionStatus = ActionStatus.RUNNING) -> MultiTrackSnapshot:
    """Snapshot for an ad-hoc action started outside any plan (track name 'main')."""
    runner = RunnerSnapshot(action_id=action_id, action_label=label, status=status)
    return MultiTrackSnapshot(tracks=(TrackSnapshot(track_name="main", plan_snapshot=PlanSnapshot(runner=runner)),))


def _plan_step_snap(
    plan_name: str,
    step_action_ids: tuple[str, ...],
    current_index: int,
    *,
    statuses: tuple[StepStatus, ...] | None = None,
    runner: RunnerSnapshot | None = None,
) -> MultiTrackSnapshot:
    """Snapshot for a single-track plan with explicit step state."""
    if statuses is None:
        statuses = tuple(StepStatus.RUNNING if i == current_index else StepStatus.PENDING for i in range(len(step_action_ids)))
    if runner is None:
        runner = RunnerSnapshot(
            action_id=step_action_ids[current_index],
            action_label=step_action_ids[current_index].title(),
            status=ActionStatus.RUNNING,
        )
    plan_snap = PlanSnapshot(
        plan_name=plan_name,
        current_step_index=current_index,
        total_steps=len(step_action_ids),
        step_statuses=statuses,
        step_action_ids=step_action_ids,
        step_action_labels=tuple(action_id.title() for action_id in step_action_ids),
        runner=runner,
    )
    return MultiTrackSnapshot(tracks=(TrackSnapshot(track_name=plan_name, plan_snapshot=plan_snap),))


def _two_track_snap(
    track_a: tuple[str, str],
    track_b: tuple[str, str],
) -> MultiTrackSnapshot:
    """Snapshot with two parallel tracks each running their own action.

    Each tuple is ``(track_name, action_id)``.
    """
    name_a, action_a = track_a
    name_b, action_b = track_b
    snap_a = PlanSnapshot(
        plan_name=name_a,
        current_step_index=0,
        total_steps=1,
        step_statuses=(StepStatus.RUNNING,),
        step_action_ids=(action_a,),
        step_action_labels=(action_a.title(),),
        runner=RunnerSnapshot(action_id=action_a, action_label=action_a.title(), status=ActionStatus.RUNNING),
    )
    snap_b = PlanSnapshot(
        plan_name=name_b,
        current_step_index=0,
        total_steps=1,
        step_statuses=(StepStatus.RUNNING,),
        step_action_ids=(action_b,),
        step_action_labels=(action_b.title(),),
        runner=RunnerSnapshot(action_id=action_b, action_label=action_b.title(), status=ActionStatus.RUNNING),
    )
    return MultiTrackSnapshot(
        tracks=(
            TrackSnapshot(track_name=name_a, plan_snapshot=snap_a),
            TrackSnapshot(track_name=name_b, plan_snapshot=snap_b),
        ),
    )


class TestIdleAndStructure:
    def test_idle_tick_with_no_logs_or_commands(self) -> None:
        tick = TickRecord(
            tick_number=1,
            met=5.0,
            state=_DEFAULT_STATE,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick])
        root = fromstring(result)
        tick_el = root.find("tick")
        assert tick_el is not None
        assert tick_el.get("number") == "1"
        assert tick_el.get("met") == "T+00:05.0"
        # The tick-level action attribute is intentionally gone; per-log
        # and per-track context now carry that information.
        assert tick_el.get("action") is None
        # Idle marker still appears when nothing changed at all.
        # (state is empty default vs no previous state -> all fields emit on tick 1)
        # so this tick is not actually idle; check that on a subsequent identical tick.

    def test_truly_idle_tick_marked_idle(self) -> None:
        # First tick emits the full state baseline; second identical tick has nothing.
        tick1 = TickRecord(
            tick_number=1,
            met=0.5,
            state=_DEFAULT_STATE,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        tick2 = TickRecord(
            tick_number=2,
            met=1.0,
            state=_DEFAULT_STATE,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick1, tick2])
        root = fromstring(result)
        ticks = root.findall("tick")
        assert ticks[1].find("idle") is not None

    def test_state_section_appears_before_other_children(self) -> None:
        tick = TickRecord(
            tick_number=1,
            met=5.0,
            state=_DEFAULT_STATE,
            multi_snap=_ad_hoc_action_snap("hover", "Hover"),
            logs=[LogEntry(level=LogLevel.LOG_INFO, message="test")],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick])
        root = fromstring(result)
        tick_el = root.find("tick")
        assert tick_el is not None
        tag_names = [child.tag for child in tick_el]
        assert tag_names.index("state") < tag_names.index("logs")
        assert tag_names.index("state") < tag_names.index("tracks")

    def test_output_is_valid_xml_with_declaration(self) -> None:
        tick = TickRecord(
            tick_number=1,
            met=0.0,
            state=_DEFAULT_STATE,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick])
        assert result.startswith("<?xml")
        fromstring(result)


class TestStateDelta:
    def test_includes_changed_fields(self) -> None:
        state = State(
            altitude_surface=150.3,
            speed_vertical=-2.5,
            control_throttle=0.65,
            control_sas=True,
        )
        tick = TickRecord(
            tick_number=1,
            met=10.0,
            state=state,
            multi_snap=_ad_hoc_action_snap("hover", "Hover"),
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick])
        root = fromstring(result)
        state_el = root.find("tick/state")
        assert state_el is not None
        assert state_el.findtext("altitude_surface") == "150.3000"
        assert state_el.findtext("speed_vertical") == "-2.5000"
        assert state_el.findtext("control_throttle") == "0.6500"
        assert state_el.findtext("control_sas") == "True"

    def test_omits_unchanged_fields(self) -> None:
        state1 = State(altitude_surface=100.0, speed_vertical=-1.0, control_throttle=0.5)
        state2 = State(altitude_surface=95.0, speed_vertical=-1.0, control_throttle=0.5)
        tick1 = TickRecord(
            tick_number=1,
            met=0.5,
            state=state1,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        tick2 = TickRecord(
            tick_number=2,
            met=1.0,
            state=state2,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick1, tick2])
        root = fromstring(result)
        ticks = root.findall("tick")
        state2_el = ticks[1].find("state")
        assert state2_el is not None
        assert state2_el.findtext("altitude_surface") == "95.0000"
        assert state2_el.findtext("speed_vertical") is None
        assert state2_el.findtext("control_throttle") is None

    def test_omitted_entirely_when_nothing_changed(self) -> None:
        state = State(altitude_surface=100.0)
        tick1 = TickRecord(
            tick_number=1,
            met=0.5,
            state=state,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        tick2 = TickRecord(
            tick_number=2,
            met=1.0,
            state=state,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick1, tick2])
        root = fromstring(result)
        ticks = root.findall("tick")
        assert ticks[0].find("state") is not None
        assert ticks[1].find("state") is None

    def test_float_jitter_below_format_precision_is_suppressed(self) -> None:
        """Floats that round to the same 4-decimal string should not emit a state change."""
        # 1.00001 and 0.99996 both format as "1.0000" - no real change.
        state1 = State(comms_signal_strength=1.00001, altitude_surface=100.0)
        state2 = State(comms_signal_strength=0.99996, altitude_surface=100.0)
        tick1 = TickRecord(
            tick_number=1,
            met=0.5,
            state=state1,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        tick2 = TickRecord(
            tick_number=2,
            met=1.0,
            state=state2,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick1, tick2])
        root = fromstring(result)
        # Tick 2 should have no <state> at all - both fields rounded to identical strings.
        assert root.findall("tick")[1].find("state") is None


class TestLogAttributes:
    def test_log_carries_track_action_step_when_present(self) -> None:
        tick = TickRecord(
            tick_number=1,
            met=10.0,
            state=_DEFAULT_STATE,
            multi_snap=_EMPTY_SNAP,
            logs=[
                LogEntry(
                    level=LogLevel.ACTION_RUNNING,
                    message="Throttling 80%",
                    track_name="hover-and-land",
                    action_id="launch",
                    plan_step=3,
                ),
            ],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick])
        root = fromstring(result)
        log_el = root.find("tick/logs/log")
        assert log_el is not None
        assert log_el.get("level") == "ACTION_RUNNING"
        assert log_el.get("track") == "hover-and-land"
        assert log_el.get("action") == "launch"
        assert log_el.get("step") == "3"
        assert log_el.text == "Throttling 80%"

    def test_log_omits_attributes_when_unset(self) -> None:
        tick = TickRecord(
            tick_number=1,
            met=10.0,
            state=_DEFAULT_STATE,
            multi_snap=_EMPTY_SNAP,
            logs=[LogEntry(level=LogLevel.LOG_INFO, message="standalone")],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick])
        root = fromstring(result)
        log_el = root.find("tick/logs/log")
        assert log_el is not None
        assert log_el.get("track") is None
        assert log_el.get("action") is None
        assert log_el.get("step") is None

    def test_step_transition_disambiguated_by_attributes(self) -> None:
        """The auto-advance moment renders cleanly: previous step ENDs and next RUNS, both tagged."""
        tick = TickRecord(
            tick_number=1,
            met=10.0,
            state=_DEFAULT_STATE,
            multi_snap=_EMPTY_SNAP,
            logs=[
                LogEntry(level=LogLevel.ACTION_END, message="Wait for Conditions", action_id="wait_for", plan_step=2),
                LogEntry(
                    level=LogLevel.ACTION_RUNNING,
                    message="Waiting for altitude > 1,000m",
                    action_id="launch",
                    plan_step=3,
                ),
            ],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick])
        root = fromstring(result)
        logs = root.findall("tick/logs/log")
        assert logs[0].get("action") == "wait_for"
        assert logs[0].get("step") == "2"
        assert logs[1].get("action") == "launch"
        assert logs[1].get("step") == "3"


class TestTracksBlock:
    def test_emits_tracks_on_first_tick_of_activity(self) -> None:
        tick = TickRecord(
            tick_number=1,
            met=10.0,
            state=_DEFAULT_STATE,
            multi_snap=_plan_step_snap("hover-and-land", ("wait_for", "launch", "land"), 1),
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick])
        root = fromstring(result)
        track_el = root.find("tick/tracks/track")
        assert track_el is not None
        assert track_el.get("name") == "hover-and-land"
        assert track_el.get("step") == "2"
        assert track_el.get("action") == "launch"
        assert track_el.get("status") == "running"

    def test_skips_tracks_when_unchanged_across_ticks(self) -> None:
        snap = _plan_step_snap("hover-and-land", ("launch",), 0)
        tick1 = TickRecord(
            tick_number=1,
            met=0.5,
            state=_DEFAULT_STATE,
            multi_snap=snap,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        tick2 = TickRecord(
            tick_number=2,
            met=1.0,
            state=_DEFAULT_STATE,
            multi_snap=snap,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick1, tick2])
        root = fromstring(result)
        ticks = root.findall("tick")
        assert ticks[0].find("tracks") is not None
        assert ticks[1].find("tracks") is None

    def test_emits_tracks_again_when_step_advances(self) -> None:
        tick1 = TickRecord(
            tick_number=1,
            met=0.5,
            state=_DEFAULT_STATE,
            multi_snap=_plan_step_snap("hover-and-land", ("wait_for", "launch"), 0),
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        tick2 = TickRecord(
            tick_number=2,
            met=1.0,
            state=_DEFAULT_STATE,
            multi_snap=_plan_step_snap("hover-and-land", ("wait_for", "launch"), 1),
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick1, tick2])
        root = fromstring(result)
        track2 = root.findall("tick")[1].find("tracks/track")
        assert track2 is not None
        assert track2.get("step") == "2"
        assert track2.get("action") == "launch"

    def test_ad_hoc_action_omits_step(self) -> None:
        tick = TickRecord(
            tick_number=1,
            met=10.0,
            state=_DEFAULT_STATE,
            multi_snap=_ad_hoc_action_snap("hover", "Hover"),
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick])
        root = fromstring(result)
        track_el = root.find("tick/tracks/track")
        assert track_el is not None
        assert track_el.get("name") == "main"
        assert track_el.get("step") is None
        assert track_el.get("action") == "hover"
        assert track_el.get("status") == "running"

    def test_finished_plan_reports_terminal_step_status(self) -> None:
        """When the runner has cleared but the plan still shows all-succeeded, status reflects that."""
        plan_snap = PlanSnapshot(
            plan_name="hover-and-land",
            current_step_index=2,
            total_steps=3,
            step_statuses=(StepStatus.SUCCEEDED, StepStatus.SUCCEEDED, StepStatus.SUCCEEDED),
            step_action_ids=("wait_for", "launch", "land"),
            step_action_labels=("Wait For", "Launch", "Land"),
            runner=RunnerSnapshot(),
        )
        snap = MultiTrackSnapshot(tracks=(TrackSnapshot(track_name="hover-and-land", plan_snapshot=plan_snap),))
        tick = TickRecord(
            tick_number=1,
            met=10.0,
            state=_DEFAULT_STATE,
            multi_snap=snap,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick])
        root = fromstring(result)
        track_el = root.find("tick/tracks/track")
        assert track_el is not None
        assert track_el.get("step") == "3"
        assert track_el.get("action") == "land"
        assert track_el.get("status") == "succeeded"


class TestCommandPruning:
    def test_emits_sent_and_redundant_blocks(self) -> None:
        tick = TickRecord(
            tick_number=1,
            met=10.0,
            state=_DEFAULT_STATE,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=VesselCommands(throttle=0.75, sas=True),
            applied_fields=frozenset({"throttle"}),
        )
        result = _format_tick_history([tick])
        root = fromstring(result)
        sent = root.find("tick/commands[@type='sent']")
        assert sent is not None
        assert sent.findtext("throttle") == "75%"
        redundant = root.find("tick/commands[@type='redundant']")
        assert redundant is not None
        assert redundant.findtext("sas") == "ON"

    def test_unchanged_command_value_is_pruned_on_subsequent_tick(self) -> None:
        commands = VesselCommands(throttle=1.0)
        tick1 = TickRecord(
            tick_number=1,
            met=0.5,
            state=_DEFAULT_STATE,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=commands,
            applied_fields=frozenset({"throttle"}),
        )
        tick2 = TickRecord(
            tick_number=2,
            met=1.0,
            state=_DEFAULT_STATE,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=commands,
            applied_fields=frozenset({"throttle"}),
        )
        result = _format_tick_history([tick1, tick2])
        root = fromstring(result)
        ticks = root.findall("tick")
        assert ticks[0].find("commands[@type='sent']/throttle") is not None
        # tick2 has no new commands element because the value+category match the previous tick.
        assert ticks[1].find("commands") is None

    def test_value_change_re_emits(self) -> None:
        tick1 = TickRecord(
            tick_number=1,
            met=0.5,
            state=_DEFAULT_STATE,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=VesselCommands(throttle=0.5),
            applied_fields=frozenset({"throttle"}),
        )
        tick2 = TickRecord(
            tick_number=2,
            met=1.0,
            state=_DEFAULT_STATE,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=VesselCommands(throttle=0.6),
            applied_fields=frozenset({"throttle"}),
        )
        result = _format_tick_history([tick1, tick2])
        root = fromstring(result)
        ticks = root.findall("tick")
        assert ticks[0].find("commands[@type='sent']/throttle").text == "50%"  # type: ignore[union-attr]
        assert ticks[1].find("commands[@type='sent']/throttle").text == "60%"  # type: ignore[union-attr]

    def test_category_change_re_emits_even_with_same_value(self) -> None:
        """When throttle moves from sent to redundant (vessel caught up), emit again."""
        tick1 = TickRecord(
            tick_number=1,
            met=0.5,
            state=_DEFAULT_STATE,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=VesselCommands(throttle=1.0),
            applied_fields=frozenset({"throttle"}),
        )
        tick2 = TickRecord(
            tick_number=2,
            met=1.0,
            state=_DEFAULT_STATE,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=VesselCommands(throttle=1.0),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick1, tick2])
        root = fromstring(result)
        ticks = root.findall("tick")
        assert ticks[0].find("commands[@type='sent']/throttle") is not None
        assert ticks[1].find("commands[@type='redundant']/throttle") is not None

    def test_gap_then_resume_re_emits(self) -> None:
        """If a field is absent for a tick and then reappears with same value, emit it."""
        tick1 = TickRecord(
            tick_number=1,
            met=0.5,
            state=_DEFAULT_STATE,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=VesselCommands(throttle=1.0),
            applied_fields=frozenset({"throttle"}),
        )
        tick2 = TickRecord(
            tick_number=2,
            met=1.0,
            state=_DEFAULT_STATE,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        tick3 = TickRecord(
            tick_number=3,
            met=1.5,
            state=_DEFAULT_STATE,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=VesselCommands(throttle=1.0),
            applied_fields=frozenset({"throttle"}),
        )
        result = _format_tick_history([tick1, tick2, tick3])
        root = fromstring(result)
        ticks = root.findall("tick")
        assert ticks[2].find("commands[@type='sent']/throttle") is not None


class TestMultiTrack:
    def test_two_tracks_each_render_a_track_element(self) -> None:
        tick = TickRecord(
            tick_number=1,
            met=10.0,
            state=_DEFAULT_STATE,
            multi_snap=_two_track_snap(("ascent", "launch"), ("patrol", "translate")),
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick])
        root = fromstring(result)
        tracks = root.findall("tick/tracks/track")
        assert len(tracks) == 2
        assert tracks[0].get("name") == "ascent"
        assert tracks[0].get("action") == "launch"
        assert tracks[1].get("name") == "patrol"
        assert tracks[1].get("action") == "translate"

    def test_logs_from_different_tracks_render_track_attribute(self) -> None:
        tick = TickRecord(
            tick_number=1,
            met=10.0,
            state=_DEFAULT_STATE,
            multi_snap=_two_track_snap(("ascent", "launch"), ("patrol", "translate")),
            logs=[
                LogEntry(
                    level=LogLevel.ACTION_RUNNING,
                    message="Throttling 80%",
                    track_name="ascent",
                    action_id="launch",
                    plan_step=1,
                ),
                LogEntry(
                    level=LogLevel.ACTION_RUNNING,
                    message="Translating right",
                    track_name="patrol",
                    action_id="translate",
                    plan_step=1,
                ),
            ],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick])
        root = fromstring(result)
        logs = root.findall("tick/logs/log")
        assert logs[0].get("track") == "ascent"
        assert logs[1].get("track") == "patrol"

    def test_conflict_warning_log_renders_with_no_track_attr(self) -> None:
        """The merge step emits a PYTHON_WARNING with no track_name; the log row should still parse."""
        tick = TickRecord(
            tick_number=1,
            met=10.0,
            state=_DEFAULT_STATE,
            multi_snap=_two_track_snap(("ascent", "launch"), ("patrol", "translate")),
            logs=[
                LogEntry(
                    level=LogLevel.PYTHON_WARNING,
                    message="Command conflict on 'throttle': set by 'ascent' (1.0) and 'patrol' (0.5). Using last value.",
                ),
            ],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick])
        root = fromstring(result)
        log_el = root.find("tick/logs/log")
        assert log_el is not None
        assert log_el.get("level") == "PYTHON_WARNING"
        assert log_el.get("track") is None
        assert log_el.get("action") is None

    def test_one_track_finishing_re_emits_tracks_block(self) -> None:
        """When the set of tracks changes (one stops, one continues), re-emit the block."""
        tick1 = TickRecord(
            tick_number=1,
            met=0.5,
            state=_DEFAULT_STATE,
            multi_snap=_two_track_snap(("ascent", "launch"), ("patrol", "translate")),
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        # Same content next tick: should NOT re-emit.
        tick2 = TickRecord(
            tick_number=2,
            met=1.0,
            state=_DEFAULT_STATE,
            multi_snap=_two_track_snap(("ascent", "launch"), ("patrol", "translate")),
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        # patrol track removed: should re-emit with one track.
        tick3 = TickRecord(
            tick_number=3,
            met=1.5,
            state=_DEFAULT_STATE,
            multi_snap=_plan_step_snap("ascent", ("launch",), 0),
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick1, tick2, tick3])
        root = fromstring(result)
        ticks = root.findall("tick")
        assert len(ticks[0].findall("tracks/track")) == 2
        assert ticks[1].find("tracks") is None
        assert len(ticks[2].findall("tracks/track")) == 1
        assert ticks[2].find("tracks/track").get("name") == "ascent"  # type: ignore[union-attr]


class TestEmptyTracksTransition:
    def test_tracks_going_empty_does_not_emit_empty_tracks_element(self) -> None:
        """When all plans/actions stop, ``<tracks>`` is suppressed (no content to show)."""
        tick1 = TickRecord(
            tick_number=1,
            met=0.5,
            state=_DEFAULT_STATE,
            multi_snap=_plan_step_snap("ascent", ("launch",), 0),
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        tick2 = TickRecord(
            tick_number=2,
            met=1.0,
            state=_DEFAULT_STATE,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick1, tick2])
        root = fromstring(result)
        ticks = root.findall("tick")
        assert ticks[0].find("tracks") is not None
        # No tracks element on tick 2: nothing meaningful to say.
        assert ticks[1].find("tracks") is None

    def test_tick_with_state_only_changes_is_not_marked_idle(self) -> None:
        """A tick that has a state delta but no logs/tracks/commands still has a child, so no <idle/>."""
        state1 = State(altitude_surface=100.0)
        state2 = State(altitude_surface=120.0)
        tick1 = TickRecord(
            tick_number=1,
            met=0.5,
            state=state1,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        tick2 = TickRecord(
            tick_number=2,
            met=1.0,
            state=state2,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick1, tick2])
        root = fromstring(result)
        tick2_el = root.findall("tick")[1]
        assert tick2_el.find("state") is not None
        assert tick2_el.find("idle") is None

    def test_tick_with_only_pruned_commands_is_idle(self) -> None:
        """If all commands are pruned and nothing else changed, the tick is genuinely empty."""
        commands = VesselCommands(throttle=1.0)
        tick1 = TickRecord(
            tick_number=1,
            met=0.5,
            state=_DEFAULT_STATE,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=commands,
            applied_fields=frozenset({"throttle"}),
        )
        tick2 = TickRecord(
            tick_number=2,
            met=1.0,
            state=_DEFAULT_STATE,
            multi_snap=_EMPTY_SNAP,
            logs=[],
            commands=commands,
            applied_fields=frozenset({"throttle"}),
        )
        result = _format_tick_history([tick1, tick2])
        root = fromstring(result)
        tick2_el = root.findall("tick")[1]
        # No state, no logs, no tracks, all commands pruned -> idle.
        assert tick2_el.find("state") is None
        assert tick2_el.find("commands") is None
        assert tick2_el.find("idle") is not None


class TestPlanLifecycleLogs:
    def test_plan_start_renders_with_inherited_step_context(self) -> None:
        """PLAN_START is annotated by PlanExecutor with the first step's action and step=1."""
        tick = TickRecord(
            tick_number=1,
            met=10.0,
            state=_DEFAULT_STATE,
            multi_snap=_plan_step_snap("hover-and-land", ("wait_for", "launch"), 0),
            logs=[
                LogEntry(
                    level=LogLevel.PLAN_START,
                    message="hover-and-land",
                    action_id="wait_for",
                    plan_step=1,
                ),
                LogEntry(
                    level=LogLevel.ACTION_START,
                    message="Wait for Conditions",
                    action_id="wait_for",
                    plan_step=1,
                ),
            ],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick])
        root = fromstring(result)
        logs = root.findall("tick/logs/log")
        assert logs[0].get("level") == "PLAN_START"
        assert logs[0].text == "hover-and-land"
        assert logs[0].get("action") == "wait_for"
        assert logs[0].get("step") == "1"
        assert logs[1].get("level") == "ACTION_START"

    def test_plan_end_renders_with_last_step_context(self) -> None:
        tick = TickRecord(
            tick_number=1,
            met=10.0,
            state=_DEFAULT_STATE,
            multi_snap=_EMPTY_SNAP,
            logs=[
                LogEntry(
                    level=LogLevel.ACTION_END,
                    message="Land",
                    action_id="land",
                    plan_step=3,
                ),
                LogEntry(
                    level=LogLevel.PLAN_END,
                    message="hover-and-land",
                    action_id="land",
                    plan_step=3,
                ),
            ],
            commands=VesselCommands(),
            applied_fields=frozenset(),
        )
        result = _format_tick_history([tick])
        root = fromstring(result)
        logs = root.findall("tick/logs/log")
        assert logs[1].get("level") == "PLAN_END"
        assert logs[1].text == "hover-and-land"
        assert logs[1].get("action") == "land"
        assert logs[1].get("step") == "3"
