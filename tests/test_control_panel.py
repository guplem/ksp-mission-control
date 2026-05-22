"""Tests for ControlPanelWidget step click navigation."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import ListView

from ksp_mission_control.control.actions.base import LogEntry, LogLevel
from ksp_mission_control.control.actions.multi_track_executor import (
    MultiTrackSnapshot,
    TrackSnapshot,
)
from ksp_mission_control.control.actions.plan_executor import PlanSnapshot, StepStatus
from ksp_mission_control.control.widgets.control_panel import (
    ControlPanelWidget,
    format_step_tooltip,
)


class ControlPanelApp(App[None]):
    """Minimal app for exercising the control panel widget."""

    captured_step_clicks: list[int]

    def __init__(self) -> None:
        super().__init__()
        self.captured_step_clicks = []

    def compose(self) -> ComposeResult:
        yield ControlPanelWidget(id="control-panel")

    def on_control_panel_widget_step_clicked(self, event: ControlPanelWidget.StepClicked) -> None:
        self.captured_step_clicks.append(event.tick_id)


def _single_track_snap(statuses: list[StepStatus]) -> tuple[PlanSnapshot, MultiTrackSnapshot]:
    plan_snap = PlanSnapshot(
        plan_name="test-plan",
        current_step_index=0,
        total_steps=len(statuses),
        step_statuses=tuple(statuses),
        step_action_ids=tuple(["hover"] * len(statuses)),
        step_action_labels=tuple(["Hover"] * len(statuses)),
    )
    multi_snap = MultiTrackSnapshot(tracks=(TrackSnapshot(track_name="test-plan", plan_snapshot=plan_snap),))
    return plan_snap, multi_snap


def _multi_track_snap() -> tuple[PlanSnapshot, MultiTrackSnapshot]:
    main = PlanSnapshot(
        plan_name="main",
        current_step_index=0,
        total_steps=2,
        step_statuses=(StepStatus.RUNNING, StepStatus.PENDING),
        step_action_ids=("hover", "hover"),
        step_action_labels=("Hover", "Hover"),
    )
    side = PlanSnapshot(
        plan_name="side",
        current_step_index=0,
        total_steps=1,
        step_statuses=(StepStatus.RUNNING,),
        step_action_ids=("hover",),
        step_action_labels=("Hover",),
    )
    multi_snap = MultiTrackSnapshot(
        tracks=(
            TrackSnapshot(track_name="main", plan_snapshot=main),
            TrackSnapshot(track_name="side", plan_snapshot=side),
        ),
    )
    return main, multi_snap


class TestRecordLogs:
    """record_logs stores the first ACTION_START tick per (track, step)."""

    @pytest.mark.asyncio
    async def test_records_first_action_start(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            widget.record_logs(
                [LogEntry(level=LogLevel.ACTION_START, message="started", track_name=None, plan_step=1)],
                tick_id=42,
            )
            assert widget._step_start_ticks == {(None, 1): 42}

    @pytest.mark.asyncio
    async def test_first_start_wins_when_step_repeats(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            widget.record_logs(
                [LogEntry(level=LogLevel.ACTION_START, message="x", plan_step=1)],
                tick_id=10,
            )
            widget.record_logs(
                [LogEntry(level=LogLevel.ACTION_START, message="x", plan_step=1)],
                tick_id=99,
            )
            assert widget._step_start_ticks[(None, 1)] == 10

    @pytest.mark.asyncio
    async def test_ignores_logs_without_plan_step(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            widget.record_logs(
                [LogEntry(level=LogLevel.ACTION_START, message="manual")],
                tick_id=5,
            )
            assert widget._step_start_ticks == {}


class TestStepClick:
    """Highlighting a started step posts a StepClicked message."""

    @pytest.mark.asyncio
    async def test_click_started_step_posts_tick(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            plan_snap, multi_snap = _single_track_snap([StepStatus.SUCCEEDED, StepStatus.RUNNING])
            widget.update_plan(plan_snap, multi_snap=multi_snap)
            widget.record_logs(
                [LogEntry(level=LogLevel.ACTION_START, message="s1", plan_step=1)],
                tick_id=7,
            )
            widget.record_logs(
                [LogEntry(level=LogLevel.ACTION_START, message="s2", plan_step=2)],
                tick_id=15,
            )
            await pilot.pause()

            list_view = pilot.app.query_one("#plan-steps-list", ListView)
            list_view.index = 0  # Step 1 (SUCCEEDED)
            await pilot.pause()
            assert pilot.app.captured_step_clicks == [7]

            list_view.index = 1  # Step 2 (RUNNING)
            await pilot.pause()
            assert pilot.app.captured_step_clicks == [7, 15]

    @pytest.mark.asyncio
    async def test_click_pending_step_is_noop(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            plan_snap, multi_snap = _single_track_snap([StepStatus.RUNNING, StepStatus.PENDING])
            widget.update_plan(plan_snap, multi_snap=multi_snap)
            widget.record_logs(
                [LogEntry(level=LogLevel.ACTION_START, message="s1", plan_step=1)],
                tick_id=20,
            )
            await pilot.pause()

            list_view = pilot.app.query_one("#plan-steps-list", ListView)
            list_view.index = 1  # Step 2 (PENDING)
            await pilot.pause()
            assert pilot.app.captured_step_clicks == []

    @pytest.mark.asyncio
    async def test_click_step_without_recorded_start_is_noop(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            plan_snap, multi_snap = _single_track_snap([StepStatus.RUNNING])
            widget.update_plan(plan_snap, multi_snap=multi_snap)
            await pilot.pause()

            list_view = pilot.app.query_one("#plan-steps-list", ListView)
            list_view.index = 0
            await pilot.pause()
            assert pilot.app.captured_step_clicks == []


class TestMultiTrackHeaders:
    """Track headers in multi-track mode are not selectable."""

    @pytest.mark.asyncio
    async def test_header_items_are_disabled(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            primary, multi_snap = _multi_track_snap()
            widget.update_plan(primary, multi_snap=multi_snap)
            await pilot.pause()

            list_view = pilot.app.query_one("#plan-steps-list", ListView)
            # Items: [main header, main step 1, main step 2, side header, side step 1]
            assert list_view.children[0].disabled is True
            assert list_view.children[1].disabled is False
            assert list_view.children[3].disabled is True

    @pytest.mark.asyncio
    async def test_track_step_uses_track_name(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            primary, multi_snap = _multi_track_snap()
            widget.update_plan(primary, multi_snap=multi_snap)
            widget.record_logs(
                [LogEntry(level=LogLevel.ACTION_START, message="s", track_name="side", plan_step=1)],
                tick_id=33,
            )
            await pilot.pause()

            list_view = pilot.app.query_one("#plan-steps-list", ListView)
            list_view.index = 4  # side step 1
            await pilot.pause()
            assert pilot.app.captured_step_clicks == [33]


class TestSetSelectedTick:
    """set_selected_tick(None) clears the step selection; tick matching a step start highlights it."""

    @pytest.mark.asyncio
    async def test_none_clears_selection(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            plan_snap, multi_snap = _single_track_snap([StepStatus.RUNNING])
            widget.update_plan(plan_snap, multi_snap=multi_snap)
            widget.record_logs(
                [LogEntry(level=LogLevel.ACTION_START, message="s", plan_step=1)],
                tick_id=4,
            )
            await pilot.pause()

            list_view = pilot.app.query_one("#plan-steps-list", ListView)
            list_view.index = 0
            await pilot.pause()
            assert list_view.index == 0

            widget.set_selected_tick(None)
            await pilot.pause()
            assert list_view.index is None

    @pytest.mark.asyncio
    async def test_matching_step_start_tick_highlights_step(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            plan_snap, multi_snap = _single_track_snap([StepStatus.SUCCEEDED, StepStatus.RUNNING])
            widget.update_plan(plan_snap, multi_snap=multi_snap)
            widget.record_logs(
                [LogEntry(level=LogLevel.ACTION_START, message="s1", plan_step=1)],
                tick_id=10,
            )
            widget.record_logs(
                [LogEntry(level=LogLevel.ACTION_START, message="s2", plan_step=2)],
                tick_id=25,
            )
            await pilot.pause()

            list_view = pilot.app.query_one("#plan-steps-list", ListView)
            widget.set_selected_tick(25)
            await pilot.pause()
            assert list_view.index == 1

    @pytest.mark.asyncio
    async def test_non_step_tick_leaves_selection_alone(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            plan_snap, multi_snap = _single_track_snap([StepStatus.RUNNING])
            widget.update_plan(plan_snap, multi_snap=multi_snap)
            widget.record_logs(
                [LogEntry(level=LogLevel.ACTION_START, message="s1", plan_step=1)],
                tick_id=10,
            )
            await pilot.pause()

            list_view = pilot.app.query_one("#plan-steps-list", ListView)
            list_view.index = 0
            await pilot.pause()

            widget.set_selected_tick(999)  # tick that no step started at
            await pilot.pause()
            assert list_view.index == 0  # selection preserved


class TestMultiTrackRerendersWhenNonPrimaryTrackChanges:
    """Regression: a stale primary snapshot must not block re-rendering when
    a non-primary track advances. Previously the panel cached
    ``_last_multi_snapshot`` before comparing it, so the comparison was
    always True and the re-render was skipped whenever the primary track
    sat idle (e.g. the main plan finished while sub-tracks kept running)."""

    @pytest.mark.asyncio
    async def test_secondary_track_progress_renders(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)

            # Frozen primary track, secondary track has step 1 RUNNING.
            primary = PlanSnapshot(
                plan_name="main",
                current_step_index=0,
                total_steps=1,
                step_statuses=(StepStatus.SUCCEEDED,),
                step_action_ids=("hover",),
                step_action_labels=("Hover",),
            )
            side_pending = PlanSnapshot(
                plan_name="side",
                current_step_index=0,
                total_steps=2,
                step_statuses=(StepStatus.RUNNING, StepStatus.PENDING),
                step_action_ids=("hover", "hover"),
                step_action_labels=("Hover", "Hover"),
            )
            multi_a = MultiTrackSnapshot(
                tracks=(
                    TrackSnapshot(track_name="main", plan_snapshot=primary),
                    TrackSnapshot(track_name="side", plan_snapshot=side_pending),
                ),
            )
            widget.update_plan(primary, multi_snap=multi_a)
            await pilot.pause()

            # Primary unchanged, secondary advances: step 1 SUCCEEDED, step 2 RUNNING.
            side_advanced = PlanSnapshot(
                plan_name="side",
                current_step_index=1,
                total_steps=2,
                step_statuses=(StepStatus.SUCCEEDED, StepStatus.RUNNING),
                step_action_ids=("hover", "hover"),
                step_action_labels=("Hover", "Hover"),
            )
            multi_b = MultiTrackSnapshot(
                tracks=(
                    TrackSnapshot(track_name="main", plan_snapshot=primary),
                    TrackSnapshot(track_name="side", plan_snapshot=side_advanced),
                ),
            )
            widget.update_plan(primary, multi_snap=multi_b)
            await pilot.pause()

            # The panel should reflect side's first step as SUCCEEDED, second as RUNNING.
            assert widget._step_statuses[("side", 1)] == StepStatus.SUCCEEDED
            assert widget._step_statuses[("side", 2)] == StepStatus.RUNNING


class TestStatusUpdatesPreserveSelection:
    """Updating only step statuses does not rebuild the ListView."""

    @pytest.mark.asyncio
    async def test_selection_survives_status_change(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            running_snap, running_multi = _single_track_snap([StepStatus.RUNNING, StepStatus.PENDING])
            widget.update_plan(running_snap, multi_snap=running_multi)
            widget.record_logs(
                [LogEntry(level=LogLevel.ACTION_START, message="s", plan_step=1)],
                tick_id=12,
            )
            await pilot.pause()

            list_view = pilot.app.query_one("#plan-steps-list", ListView)
            list_view.index = 0
            await pilot.pause()
            assert list_view.index == 0

            done_snap, done_multi = _single_track_snap([StepStatus.SUCCEEDED, StepStatus.RUNNING])
            widget.update_plan(done_snap, multi_snap=done_multi)
            await pilot.pause()
            assert list_view.index == 0


class TestFormatStepTooltip:
    """format_step_tooltip renders param dicts as multi-line text or None."""

    def test_empty_params_returns_none(self) -> None:
        assert format_step_tooltip({}) is None

    def test_single_param_one_line(self) -> None:
        assert format_step_tooltip({"target_altitude": 100.0}) == "target_altitude = 100.0"

    def test_multiple_params_one_line_each(self) -> None:
        tooltip = format_step_tooltip({"target_altitude": 100.0, "hover_duration": 30.0})
        assert tooltip == "target_altitude = 100.0\nhover_duration = 30.0"

    def test_parallel_step_plan_path(self) -> None:
        assert format_step_tooltip({"plan_path": "science/collect.plan"}) == "plan_path = science/collect.plan"


class TestStepTooltips:
    """Each plan step ListItem carries a tooltip built from its params."""

    @pytest.mark.asyncio
    async def test_step_with_params_has_tooltip(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            plan_snap = PlanSnapshot(
                plan_name="test",
                current_step_index=0,
                total_steps=1,
                step_statuses=(StepStatus.RUNNING,),
                step_action_ids=("hover",),
                step_action_labels=("Hover",),
                step_params=({"target_altitude": 100.0, "hover_duration": 30.0},),
            )
            multi_snap = MultiTrackSnapshot(tracks=(TrackSnapshot(track_name="test", plan_snapshot=plan_snap),))
            widget.update_plan(plan_snap, multi_snap=multi_snap)
            await pilot.pause()

            list_view = pilot.app.query_one("#plan-steps-list", ListView)
            assert list_view.children[0].tooltip == "target_altitude = 100.0\nhover_duration = 30.0"

    @pytest.mark.asyncio
    async def test_step_without_params_has_no_tooltip(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            plan_snap = PlanSnapshot(
                plan_name="test",
                current_step_index=0,
                total_steps=1,
                step_statuses=(StepStatus.RUNNING,),
                step_action_ids=("hover",),
                step_action_labels=("Hover",),
                step_params=({},),
            )
            multi_snap = MultiTrackSnapshot(tracks=(TrackSnapshot(track_name="test", plan_snapshot=plan_snap),))
            widget.update_plan(plan_snap, multi_snap=multi_snap)
            await pilot.pause()

            list_view = pilot.app.query_one("#plan-steps-list", ListView)
            assert list_view.children[0].tooltip is None

    @pytest.mark.asyncio
    async def test_multi_track_header_has_no_tooltip(self) -> None:
        async with ControlPanelApp().run_test(size=(120, 40)) as pilot:
            widget = pilot.app.query_one("#control-panel", ControlPanelWidget)
            main = PlanSnapshot(
                plan_name="main",
                current_step_index=0,
                total_steps=1,
                step_statuses=(StepStatus.RUNNING,),
                step_action_ids=("hover",),
                step_action_labels=("Hover",),
                step_params=({"target_altitude": 50.0},),
            )
            side = PlanSnapshot(
                plan_name="side",
                current_step_index=0,
                total_steps=1,
                step_statuses=(StepStatus.RUNNING,),
                step_action_ids=("hover",),
                step_action_labels=("Hover",),
                step_params=({"target_altitude": 200.0},),
            )
            multi_snap = MultiTrackSnapshot(
                tracks=(
                    TrackSnapshot(track_name="main", plan_snapshot=main),
                    TrackSnapshot(track_name="side", plan_snapshot=side),
                ),
            )
            widget.update_plan(main, multi_snap=multi_snap)
            await pilot.pause()

            list_view = pilot.app.query_one("#plan-steps-list", ListView)
            # Items: [main header, main step 1, side header, side step 1]
            assert list_view.children[0].tooltip is None
            assert list_view.children[1].tooltip == "target_altitude = 50.0"
            assert list_view.children[2].tooltip is None
            assert list_view.children[3].tooltip == "target_altitude = 200.0"
